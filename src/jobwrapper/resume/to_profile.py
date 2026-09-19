"""Fill the profile from an imported résumé.

The résumé already contains most of what an application form asks for. Re-typing it into the
profile is the single most tedious part of setting this up, so this maps one onto the other and
shows you exactly what it proposes to change before anything is written.

Nothing that you have already filled in is overwritten unless you ask for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..logging_setup import get
from ..models import Profile
from ..models.profile import Education, Experience, Language, Project, Skill, SkillGroup
from ..models.resume import MasterResume

log = get("resume.profile")

# "Bachelor of Science", "B.Tech", "MEng" -> the level an application form asks for
DEGREE_LEVELS: list[tuple[str, str]] = [
    (r"ph\.?\s?d|doctor", "PhD"),
    (r"\bmba\b", "MBA"),
    (r"master|m\.?\s?tech|m\.?\s?eng|m\.?\s?sc|m\.?s\.?\b|m\.?a\.?\b|mca|llm", "Master's"),
    (r"bachelor|b\.?\s?tech|b\.?\s?eng|b\.?\s?sc|b\.?s\.?\b|b\.?a\.?\b|bca|bba|llb", "Bachelor's"),
    (r"associate", "Associate"),
    (r"diploma|certificate", "Certificate"),
    (r"high school|secondary", "High School"),
]

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
COUNTRY_ALIASES = {
    "usa": ("United States", "US"), "us": ("United States", "US"),
    "united states": ("United States", "US"), "uk": ("United Kingdom", "GB"),
    "united kingdom": ("United Kingdom", "GB"), "england": ("United Kingdom", "GB"),
    "india": ("India", "IN"), "canada": ("Canada", "CA"), "germany": ("Germany", "DE"),
    "france": ("France", "FR"), "netherlands": ("Netherlands", "NL"),
    "australia": ("Australia", "AU"), "singapore": ("Singapore", "SG"),
    "ireland": ("Ireland", "IE"), "spain": ("Spain", "ES"), "poland": ("Poland", "PL"),
}
CODE_TO_COUNTRY = {
    "+91": ("India", "IN"), "+1": ("United States", "US"), "+44": ("United Kingdom", "GB"),
    "+49": ("Germany", "DE"), "+33": ("France", "FR"), "+31": ("Netherlands", "NL"),
    "+61": ("Australia", "AU"), "+65": ("Singapore", "SG"), "+353": ("Ireland", "IE"),
    "+34": ("Spain", "ES"), "+48": ("Poland", "PL"), "+81": ("Japan", "JP"),
    "+82": ("South Korea", "KR"), "+86": ("China", "CN"), "+55": ("Brazil", "BR"),
    "+27": ("South Africa", "ZA"), "+971": ("United Arab Emirates", "AE"),
    "+880": ("Bangladesh", "BD"), "+92": ("Pakistan", "PK"), "+94": ("Sri Lanka", "LK"),
    "+977": ("Nepal", "NP"), "+64": ("New Zealand", "NZ"), "+46": ("Sweden", "SE"),
    "+41": ("Switzerland", "CH"), "+39": ("Italy", "IT"), "+351": ("Portugal", "PT"),
    "+52": ("Mexico", "MX"), "+63": ("Philippines", "PH"), "+84": ("Vietnam", "VN"),
    "+62": ("Indonesia", "ID"), "+60": ("Malaysia", "MY"), "+66": ("Thailand", "TH"),
}
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "phd", "ph.d.", "md", "mba"}


@dataclass
class Change:
    path: str
    label: str
    current: Any = None
    proposed: Any = None
    kind: str = "field"          # field | list

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "label": self.label, "kind": self.kind,
                "current": _short(self.current), "proposed": _short(self.proposed)}


@dataclass
class FillResult:
    profile: Profile
    changes: list[Change] = field(default_factory=list)
    skipped: list[Change] = field(default_factory=list)   # already filled in, left alone

    def as_dict(self) -> dict[str, Any]:
        return {"changes": [c.as_dict() for c in self.changes],
                "skipped": [c.as_dict() for c in self.skipped],
                "counts": {"changed": len(self.changes), "skipped": len(self.skipped)}}


def _short(value: Any, limit: int = 80) -> Any:
    if isinstance(value, list):
        return f"{len(value)} item(s)"
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "…"


# --------------------------------------------------------------------------- little parsers
def split_name(full: str) -> tuple[str, str, str, str]:
    """"Alex J. Rivera Jr." -> first, middle, last, suffix."""
    parts = [p for p in re.split(r"\s+", (full or "").strip()) if p]
    suffix = ""
    if parts and parts[-1].lower().strip(",") in NAME_SUFFIXES:
        suffix = parts.pop().strip(",")
    if not parts:
        return "", "", "", suffix
    if len(parts) == 1:
        return parts[0], "", "", suffix
    return parts[0], " ".join(parts[1:-1]), parts[-1], suffix


# ITU calling codes, as a set so a prefix can be recognised rather than guessed. A greedy
# "first three digits" read turns "+918765432109" into "+918" / "920445907" - a wrong code
# and a nine-digit number, on every application.
CALLING_CODES = {
    "1", "7", "20", "27", "30", "31", "32", "33", "34", "36", "39", "40", "41", "43", "44",
    "45", "46", "47", "48", "49", "51", "52", "54", "55", "56", "57", "58", "60", "61", "62",
    "63", "64", "65", "66", "81", "82", "84", "86", "90", "91", "92", "93", "94", "95", "98",
    "211", "212", "213", "216", "218", "220", "221", "233", "234", "249", "251", "254", "255",
    "256", "260", "263", "264", "265", "266", "267", "268", "269", "351", "352", "353", "354",
    "355", "356", "357", "358", "359", "370", "371", "372", "373", "374", "375", "376", "377",
    "380", "381", "382", "385", "386", "387", "389", "420", "421", "423", "501", "502", "503",
    "504", "505", "506", "507", "509", "591", "593", "595", "598", "670", "673", "674",
    "675", "676", "677", "679", "680", "690", "691", "852", "853", "855", "856", "880", "886",
    "960", "961", "962", "963", "964", "965", "966", "967", "968", "970", "971", "972", "973",
    "974", "975", "976", "977", "992", "993", "994", "995", "996", "998",
}


def split_phone(raw: str) -> tuple[str, str]:
    """"+44 7700 900123" -> ("+44", "7700900123"). Keeps the number as digits."""
    text = (raw or "").strip()
    if text.startswith("+") or text.startswith("00"):
        digits = re.sub(r"\D", "", text)
        if text.startswith("00"):
            digits = digits[2:]
        # longest real code first, but only if what is left is a plausible number
        for size in (3, 2, 1):
            code, rest = digits[:size], digits[size:]
            if code in CALLING_CODES and 6 <= len(rest) <= 12:
                return f"+{code}", rest
        for size in (3, 2, 1):                       # nothing plausible: take a real code anyway
            if digits[:size] in CALLING_CODES:
                return f"+{digits[:size]}", digits[size:]
        return "", digits
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        return "+1", digits[1:]
    return ("+1" if len(digits) == 10 else ""), digits


def parse_location(raw: str) -> dict[str, str]:
    """"San Francisco, CA" / "London, United Kingdom" / "Bengaluru, India"."""
    out = {"city": "", "state": "", "state_code": "", "country": "", "country_code": ""}
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    if not parts:
        return out
    out["city"] = parts[0]
    for part in parts[1:]:
        upper, lower = part.upper(), part.lower()
        if upper in US_STATES:
            out["state_code"] = upper
            out["country"], out["country_code"] = "United States", "US"
        elif lower in COUNTRY_ALIASES:
            out["country"], out["country_code"] = COUNTRY_ALIASES[lower]
        elif not out["state"]:
            out["state"] = part
    if out["state"] and not out["country"]:
        out["country"], out["country_code"] = COUNTRY_ALIASES.get(
            out["state"].lower(), (out["country"], out["country_code"]))
        if out["country"]:
            out["state"] = ""
    return out


def degree_level(degree: str) -> str:
    lowered = (degree or "").lower()
    for pattern, level in DEGREE_LEVELS:
        if re.search(pattern, lowered):
            return level
    return ""


def infer_skill_years(skill: str, experiences: list[Experience]) -> float:
    """How long has this person been near this technology, per their own history?"""
    needle = skill.lower()
    months = 0
    for exp in experiences:
        haystack = " ".join([*exp.technologies, exp.summary, *exp.bullets]).lower()
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack):
            months += exp.duration_months
    return round(months / 12, 1)


# --------------------------------------------------------------------------- the mapping
def profile_from_resume(master: MasterResume, existing: Profile | None = None,
                        overwrite: bool = False) -> FillResult:
    profile = (existing or Profile()).model_copy(deep=True)
    pristine = Profile()
    result = FillResult(profile=profile)

    def default_for(path: str) -> Any:
        node: Any = pristine
        for part in path.split("."):
            node = getattr(node, part, None)
            if node is None:
                return None
        return node

    def answered(path: str, current: Any) -> bool:
        """A model default is not an answer.

        The profile ships with country "United States" and calling code "+1"; treating those as
        the user's own answers would refuse to take "London, United Kingdom" from their résumé.
        """
        return bool(current) and current != default_for(path)

    def put(path: str, label: str, value: Any) -> None:
        """Set a scalar, unless the user already answered it."""
        if value in (None, "", []):
            return
        node: Any = profile
        parts = path.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        current = getattr(node, parts[-1])
        change = Change(path=path, label=label, current=current, proposed=value)
        if answered(path, current) and not overwrite:
            result.skipped.append(change)
            return
        if current == value:
            return
        setattr(node, parts[-1], value)
        result.changes.append(change)

    def put_list(path: str, label: str, items: list[Any]) -> None:
        if not items:
            return
        node: Any = profile
        parts = path.split(".")
        for part in parts[:-1]:
            node = getattr(node, part)
        current = getattr(node, parts[-1])
        change = Change(path=path, label=label, current=current, proposed=items, kind="list")
        if answered(path, current) and not overwrite:
            result.skipped.append(change)
            return
        setattr(node, parts[-1], items)
        result.changes.append(change)

    # identity and contact
    first, middle, last, suffix = split_name(master.name)
    put("identity.legal_first_name", "First name", first)
    put("identity.legal_middle_name", "Middle name", middle)
    put("identity.legal_last_name", "Last name", last)
    put("identity.suffix", "Suffix", suffix)
    put("contact.email", "Email", master.email)
    if master.phone:
        code, number = split_phone(master.phone)
        put("contact.phone", "Phone", number)
        put("contact.phone_country_code", "Country calling code", code)

    # address, as far as a résumé ever states it
    located = parse_location(master.location)
    if not located.get("country") and master.phone:
        # A résumé that prints "Rohini, Delhi" and "+91..." has said which country it is.
        # Leaving the model default in place instead makes the profile claim United States,
        # and that answer goes on to drive the work-authorization questions.
        inferred = CODE_TO_COUNTRY.get(split_phone(master.phone)[0])
        if inferred:
            located["country"], located["country_code"] = inferred
    for key, value in located.items():
        put(f"address.{key}", f"Address {key.replace('_', ' ')}", value)
    for key, value in (master.postal_address or {}).items():
        put(f"address.{key}", f"Address {key.replace('_', ' ')}", value)

    # links
    for key, value in (master.links or {}).items():
        if hasattr(profile.links, key):
            put(f"links.{key}", key.title(), value)

    # headline and summary
    put("headline", "Headline", master.headline)
    put("summary", "Professional summary", master.summary)

    # experience
    experiences = [
        Experience(
            company=exp.company, title=exp.title, location=exp.location,
            start_date=exp.start_date, end_date=exp.end_date,
            currently_employed=not exp.end_date,
            bullets=[b.text for b in exp.bullets], technologies=exp.technologies)
        for exp in master.experience if exp.company or exp.title
    ]
    put_list("experience", "Work history", experiences)
    if experiences:
        put("current_title", "Current title", experiences[0].title)
        put("current_company", "Current company", experiences[0].company)

    # education
    education = [
        Education(
            institution=edu.institution, degree_name=edu.degree,
            degree_level=degree_level(edu.degree), field_of_study=edu.field_of_study,
            minor=edu.minor, gpa=edu.gpa, start_date=edu.start_date, end_date=edu.end_date,
            location=edu.location, graduated=bool(edu.end_date),
            **({"gpa_scale": edu.gpa_scale} if edu.gpa_scale else {}))
        for edu in master.education if edu.institution or edu.degree
    ]
    put_list("education", "Education", education)

    # spoken languages
    if master.spoken_languages:
        put_list("languages", "Languages",
                 [Language(name=name, proficiency=level)
                  for name, level in master.spoken_languages.items()])

    # projects
    projects = [
        Project(name=proj.name, url=proj.url, description=proj.description,
                bullets=[b.text for b in proj.bullets], technologies=proj.technologies,
                start_date=proj.start_date, end_date=proj.end_date)
        for proj in master.projects if proj.name
    ]
    put_list("projects", "Projects", projects)

    # skills, with years inferred from the history rather than invented
    groups = [SkillGroup(name=name, skills=list(items))
              for name, items in (master.skill_groups or {}).items() if items]
    put_list("skill_groups", "Skill groups", groups)
    named = sorted({s for items in (master.skill_groups or {}).values() for s in items})
    skills = []
    for name in named:
        years = infer_skill_years(name, experiences)
        # a skill the résumé lists but never dates is unknown, not junior - calling it
        # "beginner" would answer a proficiency question worse than saying nothing
        level = ("expert" if years >= 6 else "advanced" if years >= 3
                 else "intermediate" if years >= 1 else "intermediate")
        skills.append(Skill(name=name, years=years, level=level))
    put_list("skills", "Skills with years", skills)

    # certifications named on the résumé
    if master.certifications:
        from ..models.profile import Certification

        put_list("certifications", "Certifications",
                 [Certification(name=c) for c in master.certifications if c])

    total_months = sum(e.duration_months for e in experiences)
    if total_months:
        put("years_of_experience", "Years of experience", round(total_months / 12, 1))

    log.info("résumé fills %d profile field(s); %d already answered were left alone",
             len(result.changes), len(result.skipped))
    return result
