"""The field catalog and the profile -> value bridge.

`field_catalog.json` says *what* a field is; this module says *what value goes in it* for this
particular candidate, job and application. Both editions load the same JSON.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

from .. import paths
from ..models import Job, Profile

YES_NO = {"yes": "Yes", "no": "No", "prefer_not_to_say": "Prefer not to say"}


@lru_cache(maxsize=1)
def _catalog_data() -> dict[str, Any]:
    return json.loads(paths.package_data("field_catalog.json").read_text())


@lru_cache(maxsize=1)
def _ats_maps() -> dict[str, Any]:
    return json.loads(paths.package_data("ats_maps.json").read_text())


@lru_cache(maxsize=1)
def _question_patterns() -> dict[str, Any]:
    return json.loads(paths.package_data("question_patterns.json").read_text())


@dataclass
class ResolveContext:
    """Everything that varies per application."""

    job: Job | None = None
    company: str = ""
    ats: str = "generic"
    resume_path: str = ""
    cover_letter_path: str = ""
    cover_letter_text: str = ""
    generated_password: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class Catalog:
    def __init__(self) -> None:
        data = _catalog_data()
        self.version: int = data["version"]
        self.fields: list[dict[str, Any]] = data["fields"]
        self.by_key: dict[str, dict[str, Any]] = {f["key"]: f for f in self.fields}
        self.option_synonyms: dict[str, list[str]] = data["option_synonyms"]
        self.sensitive_never_fill: list[str] = data["sensitive_never_fill"]
        self.human_required_signals: list[str] = data["human_required_signals"]
        self.ats_maps: dict[str, Any] = _ats_maps()["ats"]
        self.patterns: dict[str, Any] = _question_patterns()

    def ats(self, name: str) -> dict[str, Any]:
        return self.ats_maps.get(name) or self.ats_maps["generic"]

    def detect_ats(self, url: str = "", html: str = "") -> str:
        haystack = f"{url}\n{html[:20000]}".lower()
        for name, spec in self.ats_maps.items():
            if name == "generic":
                continue
            detect = spec.get("detect", {})
            if any(token.lower() in (url or "").lower() for token in detect.get("url", [])):
                return name
            if any(token.lower() in haystack for token in detect.get("text", [])):
                return name
            if html and any(sel.strip("#.[]").lower() in haystack
                            for sel in detect.get("dom", []) if len(sel) > 6):
                return name
        return "generic"

    def is_sensitive(self, question: str) -> bool:
        lowered = question.lower()
        return any(term in lowered for term in self.sensitive_never_fill)

    def needs_human(self, text: str) -> str | None:
        lowered = text.lower()
        for signal in self.human_required_signals:
            if signal in lowered:
                return signal
        for signal in self.patterns["escalate_always"]:
            if signal in lowered:
                return signal
        return None


class ValueProvider:
    """Computes the value for a catalog key from the profile plus the current context."""

    def __init__(self, profile: Profile, context: ResolveContext | None = None) -> None:
        self.profile = profile
        self.context = context or ResolveContext()
        self._computers: dict[str, Callable[[], str]] = self._build()

    # ------------------------------------------------------------------ public
    def value_for(self, key: str) -> str:
        spec = Catalog().by_key.get(key)
        if not spec:
            return ""
        value = spec.get("value") or {}
        if "const" in value:
            return self._normalize(value["const"], spec)
        if "compute" in value:
            fn = self._computers.get(value["compute"])
            return self._normalize(fn() if fn else "", spec)
        if "path" in value:
            return self._normalize(self._by_path(value["path"]), spec)
        return ""

    def _normalize(self, value: Any, spec: dict[str, Any]) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            value = "yes" if value else "no"
        text = str(value)
        if spec.get("enum") == "yes_no" or text in YES_NO:
            return YES_NO.get(text, text)
        return text

    def _by_path(self, path: str) -> Any:
        node: Any = self.profile
        for part in path.split("."):
            node = getattr(node, part, None)
            if node is None:
                return ""
        return node

    # ------------------------------------------------------------------ computers
    def _build(self) -> dict[str, Callable[[], str]]:
        p = self.profile
        ctx = self.context

        def education() -> Any:
            return p.highest_education

        def experience() -> Any:
            return p.latest_experience

        def auth() -> Any:
            country = (p.address.country_code or "US").upper()
            return p.work_authorization.for_country(country)

        return {
            "full_name": lambda: p.identity.display_name or p.identity.full_name,
            "location_city_state_country": lambda: p.address.city_state_country,
            "today": lambda: date.today().isoformat(),

            # work authorisation
            "work_authorized": lambda: YES_NO.get(auth().authorized_to_work, "Yes"),
            "requires_sponsorship": lambda: YES_NO.get(
                "yes" if (auth().requires_sponsorship_now == "yes"
                          or auth().requires_sponsorship_future == "yes") else "no", "No"),
            "visa_status": lambda: auth().status or auth().visa_type,
            "work_permit_expiry": lambda: (auth().work_permit_expiry.isoformat()
                                           if auth().work_permit_expiry else ""),
            "permanent_resident": lambda: YES_NO.get(auth().permanent_resident, "No"),

            # education
            "school": lambda: getattr(education(), "institution", ""),
            "degree": lambda: (getattr(education(), "degree_name", "")
                               or getattr(education(), "degree_level", "")),
            "field_of_study": lambda: getattr(education(), "field_of_study", ""),
            "minor": lambda: getattr(education(), "minor", ""),
            "gpa": lambda: getattr(education(), "gpa", ""),
            "gpa_scale": lambda: getattr(education(), "gpa_scale", ""),
            "education_start": lambda: getattr(education(), "start_date", ""),
            "education_end": lambda: (getattr(education(), "end_date", "")
                                      or getattr(education(), "expected_graduation", "")),
            "currently_attending": lambda: "Yes" if getattr(
                education(), "currently_attending", False) else "No",

            # experience
            "current_company": lambda: p.current_company or getattr(experience(), "company", ""),
            "current_title": lambda: p.current_title or getattr(experience(), "title", ""),
            "years_experience": lambda: f"{p.computed_years_of_experience():g}",
            "employment_start": lambda: getattr(experience(), "start_date", ""),
            "employment_end": lambda: getattr(experience(), "end_date", ""),
            "reason_for_leaving": lambda: getattr(experience(), "reason_for_leaving", ""),
            "may_contact_employer": lambda: YES_NO.get(
                getattr(experience(), "may_contact", "no"), "No"),
            "supervisor_name": lambda: getattr(experience(), "supervisor_name", ""),

            # compensation & logistics
            "desired_salary": lambda: p.preferences.compensation.as_text(),
            "current_salary": lambda: (
                str(p.preferences.compensation.current_salary or "")
                if p.preferences.compensation.current_salary_disclosure == "disclose"
                else "Prefer not to disclose"),
            "hourly_rate": lambda: str(p.preferences.compensation.hourly_rate or ""),
            "earliest_start_date": lambda: p.preferences.earliest_start_date or "Immediately",
            "notice_period": lambda: (f"{p.preferences.notice_period_weeks} weeks"
                                      if p.preferences.notice_period_weeks else "None"),
            "willing_to_relocate": lambda: YES_NO.get(p.preferences.willing_to_relocate, "No"),
            "relocation_assistance": lambda: YES_NO.get(
                p.preferences.needs_relocation_assistance, "No"),
            "work_model_preference": lambda: p.preferences.work_model.title(),
            "commute_ok": self._commute_ok,
            "willing_to_travel": lambda: "Yes" if p.preferences.willing_to_travel_percent else "No",
            "employment_type_pref": lambda: (p.preferences.employment_types or ["Full-time"])[0],

            # screening / EEO
            "criminal_history": lambda: "",  # always escalated - never auto-answered
            "eeo_gender": lambda: (p.eeo.gender if p.eeo.share_eeo
                                   else "Decline To Self Identify"),
            "eeo_race": lambda: (p.eeo.race_ethnicity if p.eeo.share_eeo
                                 else "Decline To Self Identify"),
            "eeo_veteran": lambda: (p.eeo.veteran_status if p.eeo.share_eeo
                                    else "I don't wish to answer"),
            "eeo_disability": lambda: (p.eeo.disability_status if p.eeo.share_eeo
                                       else "I do not want to answer"),

            # source
            "how_heard": self._how_heard,
            "referrer_name": self._referrer_name,
            "referrer_email": self._referrer_email,

            # documents & account
            "resume_path": lambda: ctx.resume_path or p.documents.master_resume_pdf,
            "cover_letter_path": lambda: ctx.cover_letter_path,
            "cover_letter_text": lambda: ctx.cover_letter_text,
            "generated_password": lambda: ctx.generated_password,
            "essay": lambda: "",  # produced by the answer engine, not a static value
        }

    def _commute_ok(self) -> str:
        p = self.profile
        if p.preferences.work_model == "remote" and "hybrid" not in p.preferences.acceptable_work_models:
            return "No"
        job = self.context.job
        if job and job.location:
            home = p.address.city.lower()
            if home and home in job.location.lower():
                return "Yes"
            if job.remote or "remote" in job.location.lower():
                return "Yes"
            return "Yes" if p.preferences.willing_to_relocate == "yes" else "No"
        return "Yes"

    def _company_referral(self) -> dict[str, str]:
        company = (self.context.company or "").lower()
        return self.profile.referral.per_company.get(company, {})

    def _how_heard(self) -> str:
        override = self._company_referral().get("source")
        if override:
            return override
        if self._referrer_name():
            return "Referral"
        job = self.context.job
        if job:
            mapping = {"linkedin": "LinkedIn", "hn_hiring": "Hacker News",
                       "remoteok": "Job board", "remotive": "Job board",
                       "adzuna": "Job board", "themuse": "Job board",
                       "usajobs": "Job board", "himalayas": "Job board",
                       "jobicy": "Job board", "arbeitnow": "Job board"}
            if job.source in mapping:
                return mapping[job.source]
            return "Company website"
        return self.profile.referral.default_source

    def _referrer_name(self) -> str:
        return self._company_referral().get("referrer_name") or self.profile.referral.referrer_name

    def _referrer_email(self) -> str:
        return self._company_referral().get("referrer_email") or self.profile.referral.referrer_email


def match_option(value: str, options: list[str], catalog: Catalog | None = None) -> str | None:
    """Map a profile value onto one of the options a select/radio actually offers."""
    if not options:
        return value or None
    catalog = catalog or Catalog()
    # drop placeholder options ("", "Select...") - an empty string is a substring of every
    # value, so leaving it in makes the containment pass match it every time
    options = [o for o in options if str(o).strip()
               and str(o).strip().lower() not in {"select", "select...", "select one",
                                                  "choose", "choose one", "-", "--", "n/a -"}]
    if not options:
        return None
    lowered = [o.lower().strip() for o in options]
    target = (value or "").lower().strip()
    if not target:
        return None

    for index, option in enumerate(lowered):           # exact
        if option == target:
            return options[index]
    for index, option in enumerate(lowered):           # containment, longest first
        if target and (target in option or option in target) and abs(len(option) - len(target)) < 25:
            return options[index]

    synonyms = catalog.option_synonyms
    bucket = None
    for name, terms in synonyms.items():
        if target in terms or any(target.startswith(t) for t in terms):
            bucket = name
            break
    if bucket:
        for index, option in enumerate(lowered):
            if option in synonyms[bucket] or any(option.startswith(t) for t in synonyms[bucket]):
                return options[index]
        if bucket == "decline":
            for index, option in enumerate(lowered):
                if any(term in option for term in
                       ("decline", "not wish", "not want", "prefer not", "not disclose")):
                    return options[index]

    target_words = set(re.findall(r"[a-z0-9]+", target))
    best, best_score = None, 0.0
    for index, option in enumerate(lowered):
        option_words = set(re.findall(r"[a-z0-9]+", option))
        if not option_words:
            continue
        score = len(target_words & option_words) / len(target_words | option_words)
        if score > best_score:
            best, best_score = options[index], score
    if best_score >= 0.34:
        return best

    # last resort: stem overlap, so "Bachelor of Science" finds "Bachelor's Degree"
    def stems(text: str) -> set[str]:
        return {word[:5] for word in re.findall(r"[a-z]+", text) if len(word) > 2}

    target_stems = stems(target)
    if not target_stems:
        return None
    best, best_score = None, 0.0
    for index, option in enumerate(lowered):
        option_stems = stems(option)
        if not option_stems:
            continue
        score = len(target_stems & option_stems) / len(target_stems)
        if score > best_score:
            best, best_score = options[index], score
    return best if best_score >= 0.5 else None
