"""The Profile: the single source of truth for every answer this tool can give.

Designed against `docs/03-APPLICATION-DATA.md`. Anything an application form can ask that is
not derivable from here becomes an `AnswerRecord` so it is only ever asked once.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

YesNoPrefer = Literal["yes", "no", "prefer_not_to_say"]
WorkModel = Literal["remote", "hybrid", "onsite", "no_preference"]


# --------------------------------------------------------------------------- identity & contact
def _blank_to_none(value: Any) -> Any:
    """Web forms post "" for an untouched date; that means absent, not invalid."""
    return None if value in ("", " ") else value


class Identity(BaseModel):
    legal_first_name: str = ""
    legal_middle_name: str = ""
    legal_last_name: str = ""
    preferred_name: str = ""
    previous_name: str = ""
    suffix: str = ""
    pronouns: str = ""
    date_of_birth: date | None = None  # never auto-filled; used only for "are you over 18"

    _blank_dob = field_validator("date_of_birth", mode="before")(_blank_to_none)

    @property
    def full_name(self) -> str:
        parts = [self.legal_first_name, self.legal_middle_name, self.legal_last_name]
        return " ".join(p for p in parts if p).strip()

    @property
    def display_name(self) -> str:
        first = self.preferred_name or self.legal_first_name
        return f"{first} {self.legal_last_name}".strip()

    @property
    def initials(self) -> str:
        return "".join(p[0].upper() for p in [self.legal_first_name, self.legal_last_name] if p)


class Contact(BaseModel):
    email: str = ""
    alternate_email: str = ""
    phone: str = ""
    phone_country_code: str = "+1"
    phone_device_type: Literal["mobile", "home", "work"] = "mobile"
    preferred_contact_method: Literal["email", "phone", "either"] = "email"

    @field_validator("phone")
    @classmethod
    def _strip_phone(cls, v: str) -> str:
        return v.strip()

    @property
    def phone_digits(self) -> str:
        return "".join(c for c in self.phone if c.isdigit())

    @property
    def phone_e164(self) -> str:
        if not self.phone_digits:
            return ""
        return f"{self.phone_country_code}{self.phone_digits}"


class Address(BaseModel):
    line1: str = ""
    line2: str = ""
    city: str = ""
    state: str = ""
    state_code: str = ""
    postal_code: str = ""
    country: str = "United States"
    country_code: str = "US"
    county: str = ""
    timezone: str = ""

    @property
    def one_line(self) -> str:
        bits = [self.line1, self.line2, self.city, self.state_code or self.state, self.postal_code]
        return ", ".join(b for b in bits if b)

    @property
    def city_state_country(self) -> str:
        bits = [self.city, self.state_code or self.state, self.country]
        return ", ".join(b for b in bits if b)


class Links(BaseModel):
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    website: str = ""
    twitter: str = ""
    stackoverflow: str = ""
    dribbble: str = ""
    behance: str = ""
    google_scholar: str = ""
    orcid: str = ""
    kaggle: str = ""
    blog: str = ""
    other: str = ""

    def as_map(self) -> dict[str, str]:
        return {k: v for k, v in self.model_dump().items() if v}


# ------------------------------------------------------------------------------ work authorisation
class CountryAuthorization(BaseModel):
    authorized_to_work: YesNoPrefer = "yes"
    requires_sponsorship_now: YesNoPrefer = "no"
    requires_sponsorship_future: YesNoPrefer = "no"
    status: str = ""  # "US Citizen", "F-1 STEM OPT", "Green Card", ...
    visa_type: str = ""
    work_permit_expiry: date | None = None
    permanent_resident: YesNoPrefer = "no"
    notes: str = ""

    _blank_expiry = field_validator("work_permit_expiry", mode="before")(_blank_to_none)


class WorkAuthorization(BaseModel):
    """Keyed by ISO country code; forms ask the same question differently per country."""

    by_country: dict[str, CountryAuthorization] = Field(
        default_factory=lambda: {"US": CountryAuthorization()}
    )

    def for_country(self, code: str) -> CountryAuthorization:
        return self.by_country.get(code.upper()) or CountryAuthorization()


# --------------------------------------------------------------------------------------- education
class Education(BaseModel):
    institution: str = ""
    degree_level: str = ""  # Bachelor's, Master's, PhD, ...
    degree_name: str = ""  # "Bachelor of Technology"
    field_of_study: str = ""
    minor: str = ""  # explicitly called out in the brief - forms do ask
    second_major: str = ""
    concentration: str = ""
    gpa: str = ""
    gpa_scale: str = "4.0"
    start_date: str = ""  # YYYY-MM
    end_date: str = ""
    expected_graduation: str = ""
    currently_attending: bool = False
    graduated: bool = True
    location: str = ""
    honors: str = ""
    relevant_coursework: list[str] = Field(default_factory=list)
    thesis: str = ""


class Certification(BaseModel):
    name: str = ""
    issuer: str = ""
    credential_id: str = ""
    issue_date: str = ""
    expiry_date: str = ""
    url: str = ""


# -------------------------------------------------------------------------------------- experience
class Experience(BaseModel):
    company: str = ""
    title: str = ""
    employment_type: str = "Full-time"
    location: str = ""
    work_model: str = ""
    start_date: str = ""  # YYYY-MM
    end_date: str = ""
    currently_employed: bool = False
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    reason_for_leaving: str = ""
    supervisor_name: str = ""
    supervisor_title: str = ""
    supervisor_phone: str = ""
    may_contact: YesNoPrefer = "no"

    @property
    def duration_months(self) -> int:
        def parse(v: str) -> tuple[int, int] | None:
            try:
                y, m = v.split("-")[:2]
                return int(y), int(m)
            except Exception:
                return None

        start = parse(self.start_date)
        if not start:
            return 0
        if self.currently_employed or not self.end_date:
            today = date.today()
            end = (today.year, today.month)
        else:
            end = parse(self.end_date) or (start[0], start[1])
        return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]))


class Project(BaseModel):
    name: str = ""
    role: str = ""
    url: str = ""
    description: str = ""
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""


class SkillGroup(BaseModel):
    name: str = ""  # "Languages", "Cloud & Infra"
    skills: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    name: str
    years: float = 0
    level: Literal["beginner", "intermediate", "advanced", "expert"] = "intermediate"
    last_used_year: int | None = None

    _blank_year = field_validator("last_used_year", mode="before")(_blank_to_none)
    evidence: list[str] = Field(default_factory=list)  # where in the history it is demonstrated


class Language(BaseModel):
    name: str = ""
    proficiency: str = "Professional"  # Native, Fluent, Professional, Conversational, Basic


# ------------------------------------------------------------------------------------ preferences
class Compensation(BaseModel):
    desired_base_min: int | None = None
    desired_base_max: int | None = None
    currency: str = "USD"
    pay_period: Literal["annual", "hourly", "monthly"] = "annual"
    desired_total_comp: int | None = None
    hourly_rate: int | None = None
    negotiable: bool = True
    equity_expectation: str = ""
    bonus_expectation: str = ""
    current_salary_disclosure: Literal["disclose", "decline"] = "decline"
    current_salary: int | None = None

    def as_text(self) -> str:
        if not self.desired_base_min and not self.desired_base_max:
            return "Negotiable"
        lo, hi = self.desired_base_min, self.desired_base_max
        cur = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹"}.get(self.currency, "")
        if lo and hi:
            return f"{cur}{lo:,} - {cur}{hi:,}"
        value = lo or hi or 0
        return f"{cur}{value:,}"


class Preferences(BaseModel):
    work_model: WorkModel = "remote"
    acceptable_work_models: list[WorkModel] = Field(default_factory=lambda: ["remote", "hybrid"])
    max_days_in_office: int = 3
    preferred_locations: list[str] = Field(default_factory=list)
    willing_to_relocate: YesNoPrefer = "no"
    relocation_locations: list[str] = Field(default_factory=list)
    needs_relocation_assistance: YesNoPrefer = "no"
    willing_to_travel_percent: int = 10
    earliest_start_date: str = ""  # YYYY-MM-DD or "Immediately"
    notice_period_weeks: int = 2
    employment_types: list[str] = Field(default_factory=lambda: ["Full-time"])
    open_to_contract: bool = False
    shift_availability: str = "Standard business hours"
    weekend_availability: YesNoPrefer = "no"
    overtime_availability: YesNoPrefer = "yes"
    compensation: Compensation = Field(default_factory=Compensation)
    industries_preferred: list[str] = Field(default_factory=list)
    industries_excluded: list[str] = Field(default_factory=list)
    company_size_preference: str = ""
    remote_timezone_overlap: str = ""


# ----------------------------------------------------------------------------------------- EEO
class EEOInfo(BaseModel):
    """Voluntary self-identification. Every field defaults to declining."""

    share_eeo: bool = False
    gender: str = "Decline To Self Identify"
    race_ethnicity: str = "Decline To Self Identify"
    hispanic_or_latino: str = "Decline To Self Identify"
    veteran_status: str = "I don't wish to answer"
    disability_status: str = "I do not want to answer"
    # non-US diversity forms
    uk_ethnicity: str = "Prefer not to say"
    sexual_orientation: str = "Prefer not to say"
    religion: str = "Prefer not to say"
    gender_identity: str = "Prefer not to say"
    socioeconomic_background: str = "Prefer not to say"


class Screening(BaseModel):
    """Answers to the recurring yes/no screeners."""

    over_18: YesNoPrefer = "yes"
    can_perform_essential_functions: YesNoPrefer = "yes"
    consent_background_check: YesNoPrefer = "yes"
    consent_drug_test: YesNoPrefer = "yes"
    has_drivers_license: YesNoPrefer = "yes"
    has_reliable_transportation: YesNoPrefer = "yes"
    security_clearance: str = "None"
    active_clearance: YesNoPrefer = "no"
    non_compete_in_force: YesNoPrefer = "no"
    previously_employed_here: YesNoPrefer = "no"
    previously_applied_here: YesNoPrefer = "no"
    related_to_employee: YesNoPrefer = "no"
    currently_employed: YesNoPrefer = "yes"
    criminal_history_policy: Literal["always_escalate", "answer_from_profile"] = "always_escalate"
    criminal_history_answer: str = ""
    gdpr_consent: YesNoPrefer = "yes"
    gdpr_retention_months: int = 12
    marketing_opt_in: YesNoPrefer = "no"


class Referral(BaseModel):
    default_source: str = "Company website"
    referrer_name: str = ""
    referrer_email: str = ""
    recruiter_name: str = ""
    per_company: dict[str, dict[str, str]] = Field(default_factory=dict)


class AnswerRecord(BaseModel):
    """A question this tool has been taught the answer to. Never ask twice."""

    question_hash: str
    question: str
    answer: str
    field_key: str = ""
    company: str = ""  # empty = global answer
    ats: str = ""
    source: Literal["human", "llm", "profile", "imported"] = "human"
    confidence: float = 1.0
    times_used: int = 0
    updated_at: str = ""


class DocumentPaths(BaseModel):
    master_resume_pdf: str = ""
    master_resume_tex: str = ""
    cover_letter_template: str = ""
    transcript: str = ""
    portfolio: str = ""
    writing_sample: str = ""
    references_sheet: str = ""
    extra: dict[str, str] = Field(default_factory=dict)


class Profile(BaseModel):
    """Everything about the applicant."""

    version: int = 1
    identity: Identity = Field(default_factory=Identity)
    contact: Contact = Field(default_factory=Contact)
    address: Address = Field(default_factory=Address)
    links: Links = Field(default_factory=Links)
    work_authorization: WorkAuthorization = Field(default_factory=WorkAuthorization)
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    skill_groups: list[SkillGroup] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    preferences: Preferences = Field(default_factory=Preferences)
    eeo: EEOInfo = Field(default_factory=EEOInfo)
    screening: Screening = Field(default_factory=Screening)
    referral: Referral = Field(default_factory=Referral)
    documents: DocumentPaths = Field(default_factory=DocumentPaths)
    headline: str = ""
    summary: str = ""
    years_of_experience: float = 0
    current_title: str = ""
    current_company: str = ""
    target_titles: list[str] = Field(default_factory=list)
    notes: str = ""

    # ----------------------------------------------------------------- derived helpers
    @property
    def highest_education(self) -> Education | None:
        order = ["High School", "Associate", "Bachelor", "Master", "MBA", "PhD", "Doctor"]

        def rank(e: Education) -> int:
            for i, level in enumerate(order):
                if level.lower() in (e.degree_level or "").lower():
                    return i
            return 0

        return max(self.education, key=rank) if self.education else None

    @property
    def latest_experience(self) -> Experience | None:
        if not self.experience:
            return None
        current = [e for e in self.experience if e.currently_employed]
        pool = current or self.experience
        return sorted(pool, key=lambda e: e.start_date, reverse=True)[0]

    def skill_names(self) -> set[str]:
        names = {s.name.lower() for s in self.skills}
        for group in self.skill_groups:
            names |= {s.lower() for s in group.skills}
        for exp in self.experience:
            names |= {t.lower() for t in exp.technologies}
        for proj in self.projects:
            names |= {t.lower() for t in proj.technologies}
        return {n for n in names if n}

    def computed_years_of_experience(self) -> float:
        if self.years_of_experience:
            return self.years_of_experience
        months = sum(e.duration_months for e in self.experience)
        return round(months / 12, 1)

    def evidence_corpus(self) -> str:
        """All free text that can justify a claim - used by the truthfulness firewall."""
        chunks: list[str] = [self.summary, self.headline]
        for e in self.experience:
            chunks += [e.company, e.title, e.summary, *e.bullets, *e.technologies]
        for p in self.projects:
            chunks += [p.name, p.description, *p.bullets, *p.technologies]
        for ed in self.education:
            chunks += [ed.institution, ed.degree_name, ed.field_of_study, ed.minor,
                       ed.honors, ed.thesis, *ed.relevant_coursework]
        for c in self.certifications:
            chunks += [c.name, c.issuer]
        chunks += [s.name for s in self.skills]
        for g in self.skill_groups:
            chunks += g.skills
        return "\n".join(c for c in chunks if c)

    def summarize_for_llm(self) -> str:
        """Compact, stable text block - forms the cached prefix of every LLM call."""
        lines = [
            f"Name: {self.identity.display_name}",
            f"Headline: {self.headline}",
            f"Location: {self.address.city_state_country}",
            f"Years of experience: {self.computed_years_of_experience()}",
            f"Current: {self.current_title} at {self.current_company}",
            f"Summary: {self.summary}",
        ]
        if self.education:
            lines.append("Education:")
            for e in self.education:
                minor = f", minor in {e.minor}" if e.minor else ""
                lines.append(
                    f"  - {e.degree_level} in {e.field_of_study}{minor}, {e.institution} "
                    f"({e.start_date}..{e.end_date or e.expected_graduation}) GPA {e.gpa}/{e.gpa_scale}"
                )
        if self.experience:
            lines.append("Experience:")
            for e in self.experience:
                lines.append(f"  - {e.title} at {e.company} ({e.start_date}..{e.end_date or 'present'})")
                for b in e.bullets[:8]:
                    lines.append(f"      * {b}")
                if e.technologies:
                    lines.append(f"      tech: {', '.join(e.technologies)}")
        if self.projects:
            lines.append("Projects:")
            for p in self.projects:
                lines.append(f"  - {p.name}: {p.description}")
                if p.technologies:
                    lines.append(f"      tech: {', '.join(p.technologies)}")
        if self.skills or self.skill_groups:
            lines.append("Skills: " + ", ".join(sorted(self.skill_names())))
        return "\n".join(lines)

    # ----------------------------------------------------------------------- persistence
    @classmethod
    def load(cls, path: Path) -> Profile:
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

    def missing_required(self) -> list[str]:
        """What still has to be filled in before applying is sane."""
        missing = []
        checks: dict[str, Any] = {
            "identity.legal_first_name": self.identity.legal_first_name,
            "identity.legal_last_name": self.identity.legal_last_name,
            "contact.email": self.contact.email,
            "contact.phone": self.contact.phone,
            "address.city": self.address.city,
            "address.country": self.address.country,
            "experience": self.experience,
            "education": self.education,
        }
        for key, value in checks.items():
            if not value:
                missing.append(key)
        return missing
