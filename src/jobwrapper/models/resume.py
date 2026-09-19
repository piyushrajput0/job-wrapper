"""Structured resume + the tailoring plan the LLM returns."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ResumeBullet(BaseModel):
    text: str
    keywords: list[str] = Field(default_factory=list)
    impact_score: float = 0.5  # used when trimming to fit a page
    origin: Literal["master", "rewritten"] = "master"
    source_index: int | None = None


class ResumeExperience(BaseModel):
    company: str = ""
    title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[ResumeBullet] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class ResumeEducation(BaseModel):
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    minor: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    gpa_scale: str = ""
    details: list[str] = Field(default_factory=list)


class ResumeProject(BaseModel):
    name: str = ""
    url: str = ""
    description: str = ""
    bullets: list[ResumeBullet] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    start_date: str = ""      # the importer was already passing these; pydantic dropped them
    end_date: str = ""


class ResumeSection(BaseModel):
    """Free-form extra section preserved from the master (Publications, Awards, ...)."""

    title: str = ""
    items: list[str] = Field(default_factory=list)


class MasterResume(BaseModel):
    """The user's canonical resume: the ceiling on what any tailored version may claim."""

    name: str = ""
    headline: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: dict[str, str] = Field(default_factory=dict)
    summary: str = ""
    experience: list[ResumeExperience] = Field(default_factory=list)
    education: list[ResumeEducation] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    skill_groups: dict[str, list[str]] = Field(default_factory=dict)
    spoken_languages: dict[str, str] = Field(default_factory=dict)
    postal_address: dict[str, str] = Field(default_factory=dict)
    certifications: list[str] = Field(default_factory=list)
    extra_sections: list[ResumeSection] = Field(default_factory=list)
    latex_source: str = ""  # original Overleaf .tex, kept for reference/round-trip
    latex_preamble: str = ""

    def all_skills(self) -> set[str]:
        out: set[str] = set()
        for group in self.skill_groups.values():
            out |= {s.lower().strip() for s in group}
        for exp in self.experience:
            out |= {t.lower().strip() for t in exp.technologies}
        for proj in self.projects:
            out |= {t.lower().strip() for t in proj.technologies}
        return {s for s in out if s}

    def text_corpus(self) -> str:
        parts = [self.summary, self.headline]
        for e in self.experience:
            parts += [e.company, e.title, *[b.text for b in e.bullets], *e.technologies]
        for p in self.projects:
            parts += [p.name, p.description, *[b.text for b in p.bullets], *p.technologies]
        for ed in self.education:
            parts += [ed.institution, ed.degree, ed.field_of_study, ed.minor, *ed.details]
        for group in self.skill_groups.values():
            parts += group
        parts += self.certifications
        for s in self.extra_sections:
            parts += [s.title, *s.items]
        return "\n".join(p for p in parts if p)

    @classmethod
    def load(cls, path: Path) -> MasterResume:
        """Never fail to start because a file on disk is damaged."""
        if not path.exists():
            return cls()
        try:
            return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            from .. import paths as _paths

            _paths.quarantine(path, type(exc).__name__)
            return cls()

    def save(self, path: Path) -> Path:
        from .. import paths as _paths

        return _paths.atomic_write(
            path, json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False))


# ----------------------------------------------------------------- what the LLM is asked to return
class BulletRewrite(BaseModel):
    experience_index: int
    bullet_index: int
    new_text: str
    keywords_added: list[str] = Field(default_factory=list)
    rationale: str = ""


class TailoringPlan(BaseModel):
    """Structured output of the tailoring call - validated before anything is rendered."""

    summary: str = ""
    experience_order: list[int] = Field(default_factory=list)
    bullet_rewrites: list[BulletRewrite] = Field(default_factory=list)
    dropped_bullets: list[list[int]] = Field(default_factory=list)  # [exp_index, bullet_index]
    project_order: list[int] = Field(default_factory=list)
    skill_groups: dict[str, list[str]] = Field(default_factory=dict)
    keywords_targeted: list[str] = Field(default_factory=list)
    keywords_skipped_unsupported: list[str] = Field(default_factory=list)
    skills_surfaced: list[str] = Field(default_factory=list)   # evidenced, was not listed
    headline: str = ""
    notes: str = ""


class TruthViolation(BaseModel):
    kind: Literal["unsupported_keyword", "new_employer", "new_degree", "new_metric", "new_date"]
    detail: str
    location: str = ""


class TailoredResume(BaseModel):
    id: str = ""
    job_id: str = ""
    company: str = ""
    title: str = ""
    resume: MasterResume = Field(default_factory=MasterResume)
    plan: TailoringPlan = Field(default_factory=TailoringPlan)
    violations: list[TruthViolation] = Field(default_factory=list)
    ats_score: int = 0
    ats_notes: list[str] = Field(default_factory=list)
    keyword_coverage: float = 0.0
    tex_path: str = ""
    pdf_path: str = ""
    engine_used: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
