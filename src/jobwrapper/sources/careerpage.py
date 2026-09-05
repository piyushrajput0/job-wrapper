"""Point the tool at any company careers page and it works out the rest.

This is the bridge between the two editions: V1 uses it to add a company board from a URL, and
V2 uses the same signatures in the browser to decide which ATS adapter to run.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from ..logging_setup import get
from ..models import Job
from .base import HttpClient, JobSource

log = get("careerpage")

# (ats, regex with a capturing group for the board token)
SIGNATURES: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board/js\?for=([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"grnhse[\"'_-]?(?:board|for)[\"'\s:=]+([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_.-]+)", re.I)),
    ("lever", re.compile(r"api\.lever\.co/v0/postings/([a-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([a-z0-9_.-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9_-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"https?://([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("personio", re.compile(r"https?://([a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
    ("breezy", re.compile(r"https?://([a-z0-9-]+)\.breezy\.hr", re.I)),
    ("bamboohr", re.compile(r"https?://([a-z0-9-]+)\.bamboohr\.(?:com|co\.uk)/(?:jobs|careers)", re.I)),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/([a-z0-9_-]+)", re.I)),
    ("icims", re.compile(r"https?://([a-z0-9-]+)\.icims\.com", re.I)),
    ("teamtailor", re.compile(r"https?://([a-z0-9-]+)\.teamtailor\.com", re.I)),
]

WORKDAY_RE = re.compile(
    r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")

BOARD_KINDS = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee",
               "personio", "breezy"}


@dataclass
class DetectedBoard:
    ats: str
    token: str = ""
    company: str = ""
    url: str = ""
    host: str = ""
    tenant: str = ""
    site: str = ""
    confidence: float = 0.0

    def as_source_params(self) -> dict:
        if self.ats == "workday":
            return {"tenants": [{"host": self.host, "tenant": self.tenant, "site": self.site,
                                 "company": self.company}]}
        return {"boards": [{"token": self.token, "company": self.company}]}


def detect_from_text(text: str, *, company: str = "", url: str = "") -> DetectedBoard | None:
    workday = WORKDAY_RE.search(text)
    if workday:
        tenant, pod, site = workday.groups()
        return DetectedBoard(ats="workday", company=company or tenant, url=url,
                            host=f"{tenant}.{pod}.myworkdayjobs.com", tenant=tenant, site=site,
                            confidence=0.95)
    for ats, pattern in SIGNATURES:
        match = pattern.search(text)
        if match:
            token = match.group(1)
            if token.lower() in {"www", "job", "jobs", "careers", "embed", "api", "static"}:
                continue
            return DetectedBoard(ats=ats, token=token, company=company or token, url=url,
                                 confidence=0.9)
    return None


def detect_from_url(url: str, http: HttpClient, *, company: str = "") -> DetectedBoard | None:
    """Try the URL itself, then the page HTML, then a couple of conventional careers paths."""
    direct = detect_from_text(url, company=company, url=url)
    if direct:
        return direct

    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = parsed.netloc
    company = company or domain.replace("www.", "").split(".")[0].title()

    candidates = [url if "://" in url else f"https://{url}"]
    if not parsed.path or parsed.path == "/":
        candidates += [f"https://{domain}/careers", f"https://{domain}/jobs",
                       f"https://{domain}/careers/open-positions", f"https://{domain}/about/careers"]

    for candidate in candidates:
        response = http.get(candidate)
        if response is None:
            continue
        found = detect_from_text(response.text, company=company, url=candidate)
        if found:
            log.info("detected %s board '%s' from %s", found.ats, found.token or found.tenant,
                     candidate)
            return found
    return None


class CareerPage(JobSource):
    """Config-driven wrapper: `params.url` -> detect -> delegate to the right board adapter."""

    kind = "careerpage"
    label = "Company career page"

    def fetch(self) -> Iterable[Job]:
        from .registry import build_source

        url = self.param("url")
        if not url:
            return []
        detected = detect_from_url(url, self.http, company=self.param("company", ""))
        if not detected:
            log.warning("no known ATS found at %s", url)
            return []
        if detected.ats not in BOARD_KINDS and detected.ats != "workday":
            log.warning("%s uses %s, which has no read API; use the V2 extension on that page",
                        url, detected.ats)
            return []
        from ..config import SourceConfig

        delegate = build_source(
            SourceConfig(id=f"{self.id}:{detected.ats}", kind=detected.ats,
                         params=detected.as_source_params()),
            self.http, self.search)
        return delegate.fetch() if delegate else []
