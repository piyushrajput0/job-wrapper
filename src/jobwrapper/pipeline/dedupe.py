"""De-duplication.

The same posting reaches us from up to four directions: the company's Greenhouse board, an
aggregator that mirrors it, a remote-jobs site, and the extension. Exact-id matching handles
most of it; the rest needs a similarity pass because titles drift ("Senior Backend Engineer"
vs "Backend Engineer (Senior)") and locations expand ("Remote" vs "Remote - US").
"""

from __future__ import annotations

from difflib import SequenceMatcher

from ..models.job import Job, _norm, _norm_loc, _norm_title

# Prefer the source that gives us a real application form over a mirror that gives a redirect.
SOURCE_RANK = {
    "greenhouse": 100, "lever": 100, "ashby": 100, "workable": 95, "smartrecruiters": 95,
    "recruitee": 90, "workday": 90, "personio": 85, "breezy": 85, "careerpage": 80,
    "extension": 75, "themuse": 60, "usajobs": 60, "adzuna": 55, "remoteok": 50,
    "remotive": 50, "himalayas": 50, "jobicy": 45, "arbeitnow": 45, "hn_hiring": 40, "manual": 30,
}


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _merge(primary: Job, other: Job) -> Job:
    """Keep the best of both. Primary wins on identity, other fills the gaps."""
    if len(other.description) > len(primary.description):
        primary.description = other.description
        primary.description_html = other.description_html or primary.description_html
    primary.apply_url = primary.apply_url or other.apply_url
    primary.ats = primary.ats or other.ats
    primary.location = primary.location or other.location
    primary.locations = sorted(set(primary.locations) | set(other.locations))
    primary.seniority = primary.seniority or other.seniority
    primary.employment_type = primary.employment_type or other.employment_type
    primary.work_model = primary.work_model or other.work_model
    primary.department = primary.department or other.department
    primary.company_domain = primary.company_domain or other.company_domain
    if not primary.salary.min and other.salary.min:
        primary.salary = other.salary
    if not primary.posted_at and other.posted_at:
        primary.posted_at = other.posted_at
    primary.tags = sorted(set(primary.tags) | set(other.tags) | {f"also:{other.source}"})
    primary.remote = primary.remote or other.remote
    primary.sponsorship_mentioned = primary.sponsorship_mentioned or other.sponsorship_mentioned
    return primary


def dedupe_jobs(jobs: list[Job], *, title_threshold: float = 0.86) -> list[Job]:
    """Exact-id collapse, then a company-scoped fuzzy pass."""
    by_id: dict[str, Job] = {}
    for job in jobs:
        existing = by_id.get(job.id)
        if not existing:
            by_id[job.id] = job
            continue
        keep, drop = ((existing, job)
                      if SOURCE_RANK.get(existing.source, 0) >= SOURCE_RANK.get(job.source, 0)
                      else (job, existing))
        by_id[job.id] = _merge(keep, drop)

    buckets: dict[str, list[Job]] = {}
    for job in by_id.values():
        buckets.setdefault(_norm(job.company), []).append(job)

    result: list[Job] = []
    for group in buckets.values():
        group.sort(key=lambda j: SOURCE_RANK.get(j.source, 0), reverse=True)
        kept: list[Job] = []
        for job in group:
            duplicate_of = None
            for candidate in kept:
                title_sim = _similar(_norm_title(job.title), _norm_title(candidate.title))
                same_place = (_norm_loc(job.location) == _norm_loc(candidate.location)
                              or not job.location or not candidate.location)
                if title_sim >= title_threshold and same_place:
                    duplicate_of = candidate
                    break
            if duplicate_of is not None:
                _merge(duplicate_of, job)
            else:
                kept.append(job)
        result.extend(kept)
    return result
