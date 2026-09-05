"""Normalised job posting - one shape for sixteen different upstream formats."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobSource = Literal[
    "greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "personio",
    "breezy", "workday", "remoteok", "remotive", "arbeitnow", "jobicy", "himalayas", "themuse",
    "adzuna", "usajobs", "hn_hiring", "careerpage", "extension", "manual",
]


class SalaryRange(BaseModel):
    min: int | None = None
    max: int | None = None
    currency: str = "USD"
    period: Literal["annual", "hourly", "monthly", "daily"] = "annual"

    @property
    def annualized_max(self) -> int | None:
        if self.max is None:
            return None
        return {"annual": 1, "monthly": 12, "daily": 260, "hourly": 2080}[self.period] * self.max

    def as_text(self) -> str:
        if self.min is None and self.max is None:
            return ""
        sym = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹", "CAD": "C$"}.get(self.currency, "")
        if self.min and self.max:
            return f"{sym}{self.min:,}-{sym}{self.max:,}/{self.period[:2]}"
        return f"{sym}{(self.min or self.max):,}/{self.period[:2]}"


class Job(BaseModel):
    id: str = ""
    source: str = "manual"
    source_job_id: str = ""
    company: str = ""
    company_domain: str = ""
    title: str = ""
    location: str = ""
    locations: list[str] = Field(default_factory=list)
    remote: bool = False
    work_model: str = ""  # remote / hybrid / onsite
    employment_type: str = ""
    department: str = ""
    seniority: str = ""
    description: str = ""  # plain text
    description_html: str = ""
    requirements: list[str] = Field(default_factory=list)
    url: str = ""
    apply_url: str = ""
    ats: str = ""  # detected ATS vendor for the apply flow
    salary: SalaryRange = Field(default_factory=SalaryRange)
    posted_at: str = ""
    discovered_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    tags: list[str] = Field(default_factory=list)
    sponsorship_mentioned: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)

    # scoring, filled by the matcher
    match_score: int = 0
    match_reasons: list[str] = Field(default_factory=list)
    match_gaps: list[str] = Field(default_factory=list)

    def compute_id(self) -> str:
        """Stable identity across sources: company + normalised title + normalised location."""
        norm = f"{_norm(self.company)}|{_norm_title(self.title)}|{_norm_loc(self.location)}"
        return hashlib.sha1(norm.encode()).hexdigest()[:16]

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = self.compute_id()
        if not self.apply_url:
            self.apply_url = self.url

    @property
    def age_days(self) -> float | None:
        if not self.posted_at:
            return None
        try:
            posted = datetime.fromisoformat(self.posted_at.replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=UTC)
            return (datetime.now(UTC) - posted).total_seconds() / 86400
        except Exception:
            return None

    def short(self) -> str:
        return f"{self.title} @ {self.company} ({self.location or 'n/a'})"


_STOP_TITLE = {
    "senior", "sr", "junior", "jr", "staff", "principal", "lead", "i", "ii", "iii", "iv",
    "1", "2", "3", "4", "the", "a", "an", "and", "of", "for",
}


def _norm(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"\b(inc|llc|ltd|corp|corporation|gmbh|plc|co)\b\.?", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _norm_title(title: str) -> str:
    words = re.split(r"[^a-z0-9+#]+", (title or "").lower())
    keep = [w for w in words if w and w not in _STOP_TITLE]
    return "".join(sorted(set(keep)))


def _norm_loc(loc: str) -> str:
    loc = (loc or "").lower()
    if any(k in loc for k in ("remote", "anywhere", "distributed")):
        return "remote"
    first = re.split(r"[,;/|]", loc)[0]
    return re.sub(r"[^a-z0-9]+", "", first)
