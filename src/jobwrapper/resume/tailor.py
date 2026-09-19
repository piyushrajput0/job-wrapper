"""The tailoring engine.

Pipeline: keywords -> plan -> apply -> truthfulness firewall -> ATS lint.

The plan comes from Claude when a key is available and from a deterministic ranker when it is
not; both produce the same `TailoringPlan`, so everything downstream is identical. The firewall
runs on the *output*, not the model's promises: whatever produced the text, the text is checked
against the master resume before a PDF is ever compiled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import Config
from ..llm import LLMClient, LLMUnavailable
from ..llm.prompts import TAILOR_SYSTEM
from ..logging_setup import get
from ..models import Job, Profile
from ..models.resume import (
    MasterResume,
    ResumeBullet,
    TailoredResume,
    TailoringPlan,
    TruthViolation,
)
from ..pipeline.match import canonical_skill, extract_skills
from .ats import ats_lint
from .keywords import Keyword, analyse_gaps, extract_keywords, keyword_coverage

log = get("resume.tailor")

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|x\b|k\b|m\b|bn?\b|ms\b|s\b|million|billion)?",
                        re.I)


@dataclass
class TailorOptions:
    max_bullets_per_role: int = 6
    max_roles: int = 4
    max_projects: int = 3
    truthfulness: str = "strict"
    use_llm: bool = True


class Tailor:
    def __init__(self, config: Config, master: MasterResume, profile: Profile,
                 llm: LLMClient | None = None) -> None:
        self.config = config
        self.master = master
        self.profile = profile
        self.llm = llm or LLMClient(config.llm)
        self._cached_context: str | None = None

    # ------------------------------------------------------------------ public
    def tailor(self, job: Job, options: TailorOptions | None = None) -> TailoredResume:
        options = options or TailorOptions(truthfulness=self.config.resume.truthfulness)
        keywords = extract_keywords(job, self.master, self.llm,
                                    use_llm=options.use_llm and self.config.llm.enabled)
        gaps = analyse_gaps(keywords)
        log.info("%s: %d keywords, %d supported by the master resume (%.0f%%)",
                 job.short(), len(keywords), len(gaps.supported), gaps.support_rate * 100)

        plan = None
        if options.use_llm and self.llm.available():
            plan = self._plan_with_llm(job, keywords)
        if plan is None:
            plan = self._plan_deterministically(job, keywords, options)

        tailored = self._apply_plan(plan, keywords, options)
        violations = self._firewall(tailored, plan)
        if violations and options.truthfulness == "strict":
            tailored, violations = self._repair(tailored, violations)

        text = tailored.text_corpus()
        report = ats_lint(tailored, keywords, text)
        return TailoredResume(
            job_id=job.id, company=job.company, title=job.title,
            resume=tailored, plan=plan, violations=violations,
            ats_score=report.score, ats_notes=report.notes + [f"PASS: {p}" for p in report.passed],
            keyword_coverage=keyword_coverage(keywords, text),
        )

    # ------------------------------------------------------------------ planning
    def cached_context(self) -> str:
        """Stable across every job in a run - this is the prompt-cache prefix."""
        if self._cached_context is None:
            self._cached_context = (
                "=== CANDIDATE PROFILE ===\n"
                f"{self.profile.summarize_for_llm()}\n\n"
                "=== MASTER RESUME (the ceiling on what may be claimed) ===\n"
                f"{self._master_as_text()}"
            )
        return self._cached_context

    def _master_as_text(self) -> str:
        lines = [f"summary: {self.master.summary}"]
        for i, exp in enumerate(self.master.experience):
            lines.append(f"experience[{i}]: {exp.title} at {exp.company} "
                         f"({exp.start_date}..{exp.end_date or 'present'}) {exp.location}")
            for j, bullet in enumerate(exp.bullets):
                lines.append(f"  bullet[{i}][{j}]: {bullet.text}")
            if exp.technologies:
                lines.append(f"  tech: {', '.join(exp.technologies)}")
        for i, proj in enumerate(self.master.projects):
            lines.append(f"project[{i}]: {proj.name} - {proj.description}")
            for j, bullet in enumerate(proj.bullets):
                lines.append(f"  bullet[{j}]: {bullet.text}")
        for i, edu in enumerate(self.master.education):
            minor = f", minor {edu.minor}" if edu.minor else ""
            lines.append(f"education[{i}]: {edu.degree} {edu.field_of_study}{minor}, "
                         f"{edu.institution} ({edu.start_date}..{edu.end_date}) GPA {edu.gpa}")
        for group, skills in self.master.skill_groups.items():
            lines.append(f"skills[{group}]: {', '.join(skills)}")
        if self.master.certifications:
            lines.append(f"certifications: {', '.join(self.master.certifications)}")
        return "\n".join(lines)

    def _plan_with_llm(self, job: Job, keywords: list[Keyword]) -> TailoringPlan | None:
        supported = [k.term for k in keywords if k.in_master]
        unsupported = [k.term for k in keywords if not k.in_master]
        prompt = (
            f"=== TARGET JOB ===\n"
            f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.location}\n\n"
            f"Job description:\n{job.description[:14000]}\n\n"
            f"=== EXTRACTED KEYWORDS ===\n"
            f"Supported by the master resume (use these freely): {', '.join(supported) or 'none'}\n"
            f"NOT supported by the master resume (you may not claim these; list them in "
            f"keywords_skipped_unsupported): {', '.join(unsupported) or 'none'}\n\n"
            f"Produce the tailoring plan. Indices refer to the master resume arrays above."
        )
        try:
            return self.llm.parse(TailoringPlan, system=TAILOR_SYSTEM, prompt=prompt,
                                  cached_context=self.cached_context(), effort="medium")
        except LLMUnavailable as exc:
            log.info("tailoring without the model: %s", exc)
        except Exception as exc:
            log.warning("tailoring model call failed (%s); falling back to the ranker", exc)
        return None

    def _bullet_relevance(self, text: str, keywords: list[Keyword]) -> float:
        lowered = text.lower()
        score = 0.0
        for keyword in keywords:
            term = keyword.term.lower()
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
                score += keyword.importance
        if _NUMBER_RE.search(text):
            score += 0.35  # quantified bullets always earn their place
        first = lowered.split()[0].strip(",.") if lowered.split() else ""
        if first in {"built", "led", "designed", "shipped", "reduced", "scaled", "architected"}:
            score += 0.15
        return score

    def _plan_deterministically(self, job: Job, keywords: list[Keyword],
                                options: TailorOptions) -> TailoringPlan:
        """No model needed: rank what already exists against the JD."""
        plan = TailoringPlan(keywords_targeted=[k.term for k in keywords if k.in_master],
                             keywords_skipped_unsupported=[k.term for k in keywords
                                                           if not k.in_master])
        role_scores: list[tuple[int, float]] = []
        for index, exp in enumerate(self.master.experience):
            bullet_scores = [self._bullet_relevance(b.text, keywords) for b in exp.bullets]
            recency_bonus = max(0.0, 1.2 - index * 0.25)
            role_scores.append((index, sum(sorted(bullet_scores, reverse=True)[:4]) + recency_bonus))
        plan.experience_order = [i for i, _ in sorted(role_scores, key=lambda p: -p[1])]

        for index, exp in enumerate(self.master.experience):
            ranked = sorted(range(len(exp.bullets)),
                            key=lambda j: -self._bullet_relevance(exp.bullets[j].text, keywords))
            keep = set(ranked[: options.max_bullets_per_role])
            for j in range(len(exp.bullets)):
                if j not in keep:
                    plan.dropped_bullets.append([index, j])

        project_scores = []
        for index, proj in enumerate(self.master.projects):
            text = f"{proj.name} {proj.description} " + " ".join(b.text for b in proj.bullets)
            project_scores.append((index, self._bullet_relevance(text, keywords)))
        plan.project_order = [i for i, _ in sorted(project_scores, key=lambda p: -p[1])]

        # skills: same content, JD-relevant terms first
        wanted = {k.term.lower() for k in keywords}
        for group, skills in self.master.skill_groups.items():
            plan.skill_groups[group] = sorted(
                skills, key=lambda s: (0 if (canonical_skill(s) or s).lower() in wanted else 1,
                                       skills.index(s)))
        plan.skills_surfaced = self._surface_supported_skills(keywords, plan.skill_groups)

        top_terms = [k.term for k in keywords if k.in_master][:6]
        base = self.master.summary or self.profile.summary
        years = self.profile.computed_years_of_experience()
        role_noun = re.sub(r"\s*[-–|(].*$", "", job.title).strip()
        summary = (f"{role_noun} with {years:g}+ years building "
                   f"{', '.join(top_terms[:3]) if top_terms else 'production software'}.")
        if base:
            trimmed = base.split(". ")
            summary = f"{summary} {'. '.join(trimmed[:2]).strip().rstrip('.')}."
        if top_terms[3:]:
            summary += f" Recent work spans {', '.join(top_terms[3:6])}."
        plan.summary = summary.strip()
        plan.headline = f"{role_noun}" if role_noun else self.master.headline
        plan.notes = "deterministic ranker (no model call)"
        return plan

    def _surface_supported_skills(self, keywords: list[Keyword],
                                   groups: dict[str, list[str]]) -> list[str]:
        """Promote JD terms the résumé already demonstrates into the skills list.

        A term the master evidences in a bullet but never lists - "Kafka" described in a
        role, absent from Skills - is a keyword the candidate has genuinely earned and the
        ATS cannot see. Surfacing it is tailoring. Terms the résumé cannot support are not
        added here at any truthfulness setting: `in_master` is the gate, and the firewall
        re-checks it afterwards.
        """
        listed = {(canonical_skill(s) or s).lower()
                  for skills in groups.values() for s in skills}
        budget = max(0, self.config.resume.max_new_keywords)
        added: list[str] = []
        for keyword in sorted((k for k in keywords if k.in_master and k.kind == "skill"),
                              key=lambda k: -k.importance):
            if len(added) >= budget:
                break
            term = keyword.canonical or keyword.term
            if term.lower() in listed:
                continue
            listed.add(term.lower())
            groups.setdefault(self._group_for(term), []).insert(0, term)
            added.append(term)
        return added

    def _group_for(self, skill: str) -> str:
        """The skills heading a surfaced term belongs under, matching the importer's labels."""
        from ..pipeline.match import _taxonomy

        labels = {"language": "Languages", "frontend": "Frontend", "backend": "Backend",
                  "data": "Data", "ml": "Machine Learning", "cloud": "Cloud & Infrastructure",
                  "mobile": "Mobile", "tools": "Tools", "practice": "Practices"}
        category = _taxonomy()["skills"].get(skill, {}).get("category", "tools")
        wanted = labels.get(category, "Tools")
        for existing in self.master.skill_groups:
            if existing.lower() == wanted.lower():
                return existing
        # no matching heading on this résumé - put it where the most skills already are
        return max(self.master.skill_groups, key=lambda g: len(self.master.skill_groups[g]),
                   default=wanted) if self.master.skill_groups else wanted

    # ------------------------------------------------------------------ applying
    def _apply_plan(self, plan: TailoringPlan, keywords: list[Keyword],
                    options: TailorOptions) -> MasterResume:
        out = self.master.model_copy(deep=True)
        # the contact block often lives in the LaTeX preamble rather than the parsed body
        out.name = out.name or self.profile.identity.display_name
        out.email = out.email or self.profile.contact.email
        out.phone = out.phone or self.profile.contact.phone
        out.location = out.location or self.profile.address.city_state_country
        for key, value in self.profile.links.as_map().items():
            out.links.setdefault(key, value)
        out.summary = plan.summary or out.summary
        if plan.headline:
            out.headline = plan.headline

        rewrites = {(r.experience_index, r.bullet_index): r for r in plan.bullet_rewrites}
        dropped = {tuple(pair) for pair in plan.dropped_bullets if len(pair) == 2}

        for exp_index, exp in enumerate(out.experience):
            bullets: list[ResumeBullet] = []
            for bullet_index, bullet in enumerate(exp.bullets):
                if (exp_index, bullet_index) in dropped:
                    continue
                rewrite = rewrites.get((exp_index, bullet_index))
                if rewrite and rewrite.new_text.strip():
                    bullets.append(ResumeBullet(
                        text=rewrite.new_text.strip(), keywords=rewrite.keywords_added,
                        origin="rewritten", source_index=bullet_index,
                        impact_score=self._bullet_relevance(rewrite.new_text, keywords)))
                else:
                    bullet.impact_score = self._bullet_relevance(bullet.text, keywords)
                    bullet.source_index = bullet_index
                    bullets.append(bullet)
            exp.bullets = bullets[: options.max_bullets_per_role]

        if plan.experience_order:
            order = [i for i in plan.experience_order if 0 <= i < len(out.experience)]
            order += [i for i in range(len(out.experience)) if i not in order]
            out.experience = [out.experience[i] for i in order]
        out.experience = out.experience[: max(options.max_roles, 1)] + [
            e for e in out.experience[options.max_roles:] if e.bullets and len(out.experience) <= 5]

        if plan.project_order:
            order = [i for i in plan.project_order if 0 <= i < len(out.projects)]
            order += [i for i in range(len(out.projects)) if i not in order]
            out.projects = [out.projects[i] for i in order][: options.max_projects]

        # Projects were only ever reordered, so a JD term the project itself describes
        # ("built the ingestion with Kafka") never reached its technology line, where both
        # the ATS and a skimming reader look first. Only terms that project's own text
        # supports are added, and only a couple, so the entry still reads as written.
        for project in out.projects:
            own_text = (f"{project.name} {project.description} "
                        + " ".join(b.text for b in project.bullets)).lower()
            listed = {t.lower() for t in project.technologies}
            for keyword in sorted(keywords, key=lambda k: -k.importance):
                if len(project.technologies) >= len(listed) + 3:
                    break
                term = keyword.canonical or keyword.term
                if term.lower() in listed or keyword.kind != "skill":
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", own_text):
                    project.technologies.append(term)

        if plan.skill_groups:
            merged: dict[str, list[str]] = {}
            master_pool = {s.lower(): s for group in self.master.skill_groups.values()
                           for s in group}
            # A term the résumé demonstrates in a bullet or a project, but never lists under
            # Skills, is still the candidate's. Let it through; anything the master cannot
            # evidence at all still cannot be added, and the firewall re-checks the result.
            evidenced = {s.lower(): s for s in extract_skills(self.master.text_corpus())}
            for group, skills in plan.skill_groups.items():
                merged[group] = [master_pool.get(s.lower()) or evidenced.get(s.lower(), s)
                                 for s in skills
                                 if s.lower() in master_pool or s.lower() in evidenced]
            for group, skills in self.master.skill_groups.items():
                if group not in merged or not merged[group]:
                    merged[group] = skills
            # a group the master never had contributes no skills, and an empty heading on a
            # resume is worse than no heading - drop it rather than render it
            out.skill_groups = {name: skills for name, skills in merged.items() if skills}
        return out

    # ------------------------------------------------------------------ firewall
    def _firewall(self, tailored: MasterResume, plan: TailoringPlan) -> list[TruthViolation]:
        """Check the produced text against the master. Model or ranker, same audit."""
        violations: list[TruthViolation] = []
        master_corpus = self.master.text_corpus().lower()
        master_numbers = set(_NUMBER_RE.findall(master_corpus))
        # Compare canonical-to-canonical: "GitHub Actions" in the master supports "Git" in the
        # output. Comparing raw strings would raise false alarms on every alias.
        master_skills = extract_skills(self.master.text_corpus())
        master_skills |= {canonical_skill(s) or s.title() for s in self.master.all_skills()}
        master_skills = {s.lower() for s in master_skills}

        # 1. skills that appear in the output but not in the master
        for skill in extract_skills(tailored.text_corpus()):
            if skill.lower() in master_skills:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(skill.lower())}(?![a-z0-9])", master_corpus):
                continue
            violations.append(TruthViolation(
                kind="unsupported_keyword",
                detail=f"'{skill}' appears in the tailored resume but not in the master",
                location="body"))

        # 2. metrics invented inside a rewritten bullet
        originals = {(i, j): b.text for i, exp in enumerate(self.master.experience)
                     for j, b in enumerate(exp.bullets)}
        for rewrite in plan.bullet_rewrites:
            original = originals.get((rewrite.experience_index, rewrite.bullet_index), "")
            original_numbers = set(_NUMBER_RE.findall(original.lower()))
            for number in _NUMBER_RE.findall(rewrite.new_text.lower()):
                token = number.strip()
                if not token or not any(c.isdigit() for c in token):
                    continue
                if token not in original_numbers and token not in master_numbers:
                    violations.append(TruthViolation(
                        kind="new_metric",
                        detail=f"'{token}' is not in the original bullet: "
                               f"\"{rewrite.new_text[:80]}\"",
                        location=f"experience[{rewrite.experience_index}]"
                                 f"[{rewrite.bullet_index}]"))

        # 3. employers and degrees must match the master exactly
        master_companies = {e.company.lower() for e in self.master.experience}
        for exp in tailored.experience:
            if exp.company.lower() not in master_companies:
                violations.append(TruthViolation(
                    kind="new_employer", detail=f"employer '{exp.company}' is not in the master"))
        master_degrees = {f"{e.degree} {e.field_of_study}".lower() for e in self.master.education}
        for edu in tailored.education:
            if f"{edu.degree} {edu.field_of_study}".lower() not in master_degrees:
                violations.append(TruthViolation(
                    kind="new_degree", detail=f"degree '{edu.degree} {edu.field_of_study}' "
                                              f"is not in the master"))
        return violations

    def _repair(self, tailored: MasterResume,
                violations: list[TruthViolation]) -> tuple[MasterResume, list[TruthViolation]]:
        """Strict mode: revert every rewritten bullet implicated in a violation."""
        bad_locations = {v.location for v in violations if v.location.startswith("experience")}
        reverted = 0

        # the summary is the other place a model can smuggle a claim in
        unsupported = [v.detail.split("'")[1] for v in violations
                       if v.kind == "unsupported_keyword" and "'" in v.detail]
        if any(re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])",
                         tailored.summary.lower()) for term in unsupported):
            tailored.summary = self.master.summary or self.profile.summary
            log.warning("truthfulness firewall reset the summary")
        for exp_index, exp in enumerate(tailored.experience):
            for bullet in exp.bullets:
                if bullet.origin != "rewritten" or bullet.source_index is None:
                    continue
                location = f"experience[{exp_index}][{bullet.source_index}]"
                if location in bad_locations or any(
                        v.kind == "unsupported_keyword"
                        and v.detail.split("'")[1].lower() in bullet.text.lower()
                        for v in violations):
                    original = self._original_bullet(exp.company, bullet.source_index)
                    if original:
                        bullet.text = original
                        bullet.origin = "master"
                        reverted += 1
        if reverted:
            log.warning("truthfulness firewall reverted %d rewritten bullet(s)", reverted)
        remaining = self._firewall(tailored, TailoringPlan())
        return tailored, remaining

    def _original_bullet(self, company: str, index: int) -> str | None:
        for exp in self.master.experience:
            if exp.company.lower() == company.lower() and 0 <= index < len(exp.bullets):
                return exp.bullets[index].text
        return None

    # ------------------------------------------------------------------ trimming
    @staticmethod
    def trim(resume: MasterResume, drop: int = 2) -> MasterResume:
        """Deterministic page-overflow trim: drop the lowest-impact bullets first."""
        scored = [(exp_index, bullet_index, bullet.impact_score)
                  for exp_index, exp in enumerate(resume.experience)
                  for bullet_index, bullet in enumerate(exp.bullets)]
        scored.sort(key=lambda t: t[2])
        remove: dict[int, set[int]] = {}
        for exp_index, bullet_index, _score in scored[:drop]:
            if len(resume.experience[exp_index].bullets) - len(remove.get(exp_index, set())) <= 2:
                continue
            remove.setdefault(exp_index, set()).add(bullet_index)
        for exp_index, indexes in remove.items():
            exp = resume.experience[exp_index]
            exp.bullets = [b for j, b in enumerate(exp.bullets) if j not in indexes]
        return resume
