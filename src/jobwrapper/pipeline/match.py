"""Scoring a job against the profile and the search config.

Deterministic and explainable: every point is attributable to a named reason, so `jobwrapper
list` can tell you why something scored 82 and not 40. No LLM involved.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from .. import paths
from ..config import MatchConfig, SearchConfig
from ..models import Job, Profile
from .normalize import detect_seniority

SENIORITY_ORDER = ["intern", "entry", "mid", "senior", "staff", "principal", "manager"]


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    return json.loads(paths.package_data("skill_taxonomy.json").read_text())


def canonical_skill(term: str) -> str | None:
    return _taxonomy()["alias_index"].get(term.lower().strip())


def extract_skills(text: str) -> set[str]:
    """Deterministic keyword extraction against the curated taxonomy."""
    lowered = f" {text.lower()} "
    found: set[str] = set()
    for term, canonical in _taxonomy()["alias_index"].items():
        if len(term) <= 2:
            pattern = rf"(?<![a-z0-9+#]){re.escape(term)}(?![a-z0-9+#])"
        else:
            pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        if re.search(pattern, lowered):
            found.add(canonical)
    return found


@dataclass
class MatchResult:
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    disqualified: bool = False
    disqualified_reason: str = ""


def score_job(job: Job, profile: Profile, search: SearchConfig,
              config: MatchConfig | None = None) -> MatchResult:
    config = config or MatchConfig()
    weights = config.weights
    result = MatchResult()
    text = f"{job.title}\n{job.description}"
    title_low = job.title.lower()

    # ------------------------------------------------------------------ hard filters
    for term in search.exclude_titles:
        if term and re.search(rf"(?<![a-z]){re.escape(term.lower())}(?![a-z])", title_low):
            result.disqualified = True
            result.disqualified_reason = f"excluded title term '{term}'"
            return result
    for company in search.exclude_companies:
        if company and company.lower() in job.company.lower():
            result.disqualified = True
            result.disqualified_reason = f"excluded company '{company}'"
            return result
    if search.only_companies and not any(
            c.lower() in job.company.lower() for c in search.only_companies):
        result.disqualified = True
        result.disqualified_reason = "not in only_companies"
        return result
    for term in search.exclude_keywords:
        if term and term.lower() in text.lower():
            result.disqualified = True
            result.disqualified_reason = f"excluded keyword '{term}'"
            return result
    if search.remote_only and not job.remote and job.work_model != "remote":
        result.disqualified = True
        result.disqualified_reason = "not remote"
        return result

    total = 0.0

    # ------------------------------------------------------------------ title fit
    targets = [t.lower() for t in (search.titles or profile.target_titles or [])]
    title_score = 0.0
    for target in targets:
        target_words = set(re.findall(r"[a-z]+", target))
        title_words = set(re.findall(r"[a-z]+", title_low))
        if not target_words:
            continue
        overlap = len(target_words & title_words) / len(target_words)
        title_score = max(title_score, overlap)
    if title_score >= 0.99:
        result.reasons.append(f"title matches target '{job.title}'")
    elif title_score >= 0.5:
        result.reasons.append(f"title partially matches ({int(title_score * 100)}%)")
    else:
        result.gaps.append("title is off-target")
    total += title_score * weights.get("title", 0.25) * 100

    # ------------------------------------------------------------------ skills overlap
    job_skills = extract_skills(text)
    profile_skills = {canonical_skill(s) or s.title() for s in profile.skill_names()}
    matched = job_skills & profile_skills
    missing = job_skills - profile_skills
    result.matched_skills = sorted(matched)
    result.missing_skills = sorted(missing)
    if job_skills:
        coverage = len(matched) / len(job_skills)
        if matched:
            result.reasons.append(
                f"{len(matched)}/{len(job_skills)} required skills present"
                f" ({', '.join(sorted(matched)[:6])})")
        if missing:
            result.gaps.append(f"missing: {', '.join(sorted(missing)[:6])}")
    else:
        coverage = 0.5  # no extractable requirements - do not punish
    total += coverage * weights.get("skills", 0.30) * 100

    # ------------------------------------------------------------------ seniority fit
    job_level = job.seniority or detect_seniority(job.title, job.description)
    seniority_score = 0.5
    if job_level:
        years = profile.computed_years_of_experience()
        expected = ("intern" if years < 0.5 else "entry" if years < 2 else "mid" if years < 5
                    else "senior" if years < 9 else "staff")
        distance = abs(SENIORITY_ORDER.index(job_level) - SENIORITY_ORDER.index(expected)) \
            if job_level in SENIORITY_ORDER else 2
        seniority_score = max(0.0, 1 - distance * 0.35)
        if distance == 0:
            result.reasons.append(f"seniority matches ({job_level})")
        elif distance >= 2:
            result.gaps.append(f"seniority mismatch: role is {job_level}, profile reads {expected}")
    total += seniority_score * weights.get("seniority", 0.15) * 100

    # ------------------------------------------------------------------ location fit
    location_score = 0.0
    prefs = [p.lower() for p in (search.locations or profile.preferences.preferred_locations)]
    job_loc = (job.location or "").lower()
    if job.remote or job.work_model == "remote":
        if profile.preferences.work_model in ("remote", "no_preference") or "remote" in prefs:
            location_score = 1.0
            result.reasons.append("remote role matches preference")
        else:
            location_score = 0.7
    elif prefs:
        for pref in prefs:
            if pref and (pref in job_loc or job_loc in pref):
                location_score = 1.0
                result.reasons.append(f"location matches '{job.location}'")
                break
        else:
            home = profile.address.city.lower()
            if home and home in job_loc:
                location_score = 0.9
                result.reasons.append("role is in your city")
            else:
                location_score = 0.2
                result.gaps.append(f"location '{job.location}' is outside your preferences")
    else:
        location_score = 0.6
    if job.work_model and job.work_model not in profile.preferences.acceptable_work_models \
            and job.work_model != "remote":
        location_score *= 0.6
        result.gaps.append(f"work model is {job.work_model}")
    total += location_score * weights.get("location", 0.15) * 100

    # ------------------------------------------------------------------ salary fit
    salary_score = 0.5
    wanted = profile.preferences.compensation.desired_base_min
    offered = job.salary.annualized_max
    if wanted and offered:
        if offered >= wanted:
            salary_score = 1.0
            result.reasons.append(f"salary {job.salary.as_text()} meets your floor")
        else:
            salary_score = max(0.0, offered / wanted)
            result.gaps.append(f"salary {job.salary.as_text()} is below your floor")
    if search.min_salary and offered and offered < search.min_salary:
        result.disqualified = True
        result.disqualified_reason = f"salary below min_salary ({job.salary.as_text()})"
        return result
    total += salary_score * weights.get("salary", 0.05) * 100

    # ------------------------------------------------------------------ recency
    age = job.age_days
    recency_score = 1.0 if age is None else max(0.0, 1 - (age / max(search.posted_within_days, 1)))
    if age is not None and age > search.posted_within_days:
        result.gaps.append(f"posted {int(age)} days ago")
    elif age is not None and age <= 3:
        result.reasons.append("posted in the last 3 days")
    total += recency_score * weights.get("recency", 0.05) * 100

    # ------------------------------------------------------------------ work authorisation
    auth_score = 1.0
    country = "US"
    auth = profile.work_authorization.for_country(country)
    needs_sponsorship = auth.requires_sponsorship_now == "yes" or auth.requires_sponsorship_future == "yes"
    if needs_sponsorship:
        from .normalize import sponsorship_signal

        mentioned, friendly = sponsorship_signal(job.description)
        if mentioned and not friendly:
            auth_score = 0.0
            result.gaps.append("posting states it cannot sponsor")
            if search.require_sponsorship_friendly:
                result.disqualified = True
                result.disqualified_reason = "no sponsorship available"
                return result
        elif friendly:
            result.reasons.append("posting mentions sponsorship is available")
    total += auth_score * weights.get("authorization", 0.05) * 100

    # ------------------------------------------------------------------ keyword bonuses
    bonus = 0
    for keyword in search.keywords:
        if keyword and keyword.lower() in text.lower():
            bonus += 3
            result.reasons.append(f"contains keyword '{keyword}'")
    total = min(100.0, total + bonus)

    result.score = int(round(total))
    return result
