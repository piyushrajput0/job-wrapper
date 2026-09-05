"""Aggregator sources: public, documented, key-free (or free-key) job feeds."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..models import Job
from ..pipeline.normalize import (
    detect_employment_type,
    detect_seniority,
    detect_work_model,
    html_to_text,
    iso_date,
    parse_salary,
    sponsorship_signal,
)
from .base import JobSource


def _finish(job: Job, text: str) -> Job:
    job.description = job.description or text
    job.seniority = job.seniority or detect_seniority(job.title, job.description)
    job.work_model = job.work_model or detect_work_model(job.description, job.location)
    job.remote = job.remote or job.work_model == "remote"
    job.employment_type = job.employment_type or detect_employment_type(job.description)
    if not job.salary.min:
        job.salary = parse_salary(job.description)
    mentioned, _friendly = sponsorship_signal(job.description)
    job.sponsorship_mentioned = mentioned
    job.id = job.compute_id()
    return job


class RemoteOK(JobSource):
    kind = "remoteok"
    label = "RemoteOK"

    def fetch(self) -> Iterable[Job]:
        data = self.http.get_json("https://remoteok.com/api")
        if not isinstance(data, list):
            return []
        for row in data:
            if not isinstance(row, dict) or "position" not in row:
                continue  # element 0 is RemoteOK's legal notice
            description = html_to_text(row.get("description", ""))
            job = Job(
                source="remoteok",
                source_job_id=str(row.get("id", "")),
                company=row.get("company", "").strip(),
                title=row.get("position", "").strip(),
                location=row.get("location") or "Remote",
                remote=True,
                work_model="remote",
                url=row.get("url", ""),
                apply_url=row.get("apply_url") or row.get("url", ""),
                description=description,
                description_html=row.get("description", ""),
                posted_at=iso_date(row.get("epoch") or row.get("date")),
                tags=[t for t in row.get("tags", []) if t],
            )
            if row.get("salary_min"):
                job.salary.min = int(row["salary_min"])
                job.salary.max = int(row.get("salary_max") or row["salary_min"])
            yield _finish(job, description)


class Remotive(JobSource):
    kind = "remotive"
    label = "Remotive"

    def fetch(self) -> Iterable[Job]:
        seen: set[str] = set()
        queries = self.query_terms() or [""]
        for query in queries[:4]:
            data = self.http.get_json(
                "https://remotive.com/api/remote-jobs",
                params={"search": query, "limit": self.param("limit", 100)})
            for row in (data or {}).get("jobs", []):
                job_id = str(row.get("id"))
                if job_id in seen:
                    continue
                seen.add(job_id)
                description = html_to_text(row.get("description", ""))
                job = Job(
                    source="remotive",
                    source_job_id=job_id,
                    company=row.get("company_name", ""),
                    title=row.get("title", ""),
                    location=row.get("candidate_required_location") or "Remote",
                    remote=True,
                    work_model="remote",
                    employment_type=(row.get("job_type") or "").replace("_", " "),
                    url=row.get("url", ""),
                    description=description,
                    description_html=row.get("description", ""),
                    posted_at=iso_date(row.get("publication_date")),
                    department=row.get("category", ""),
                    tags=row.get("tags", []) or [],
                )
                if row.get("salary"):
                    job.salary = parse_salary(row["salary"])
                yield _finish(job, description)


class Arbeitnow(JobSource):
    kind = "arbeitnow"
    label = "Arbeitnow"

    def fetch(self) -> Iterable[Job]:
        url: str | None = "https://www.arbeitnow.com/api/job-board-api"
        pages = int(self.param("pages", 3))
        for _ in range(pages):
            if not url:
                break
            data = self.http.get_json(url)
            if not data:
                break
            for row in data.get("data", []):
                description = html_to_text(row.get("description", ""))
                job = Job(
                    source="arbeitnow",
                    source_job_id=str(row.get("slug", "")),
                    company=row.get("company_name", ""),
                    title=row.get("title", ""),
                    location=row.get("location", ""),
                    remote=bool(row.get("remote")),
                    url=row.get("url", ""),
                    description=description,
                    description_html=row.get("description", ""),
                    posted_at=iso_date(row.get("created_at")),
                    tags=(row.get("tags") or []) + (row.get("job_types") or []),
                )
                yield _finish(job, description)
            url = (data.get("links") or {}).get("next")


class Jobicy(JobSource):
    kind = "jobicy"
    label = "Jobicy"

    def fetch(self) -> Iterable[Job]:
        params: dict[str, Any] = {"count": self.param("count", 50)}
        if self.param("geo"):
            params["geo"] = self.param("geo")
        if self.param("industry"):
            params["industry"] = self.param("industry")
        data = self.http.get_json("https://jobicy.com/api/v2/remote-jobs", params=params)
        for row in (data or {}).get("jobs", []):
            description = html_to_text(row.get("jobDescription", ""))
            job = Job(
                source="jobicy",
                source_job_id=str(row.get("id", "")),
                company=row.get("companyName", ""),
                title=row.get("jobTitle", ""),
                location=row.get("jobGeo") or "Remote",
                remote=True,
                work_model="remote",
                employment_type=", ".join(row.get("jobType", []) or []),
                url=row.get("url", ""),
                description=description,
                posted_at=iso_date(row.get("pubDate")),
                department=row.get("jobIndustry", [""])[0] if row.get("jobIndustry") else "",
            )
            if row.get("annualSalaryMin"):
                job.salary.min = int(row["annualSalaryMin"])
                job.salary.max = int(row.get("annualSalaryMax") or row["annualSalaryMin"])
                job.salary.currency = row.get("salaryCurrency", "USD")
            yield _finish(job, description)


class Himalayas(JobSource):
    kind = "himalayas"
    label = "Himalayas"

    def fetch(self) -> Iterable[Job]:
        data = self.http.get_json("https://himalayas.app/jobs/api",
                                  params={"limit": self.param("limit", 100)})
        for row in (data or {}).get("jobs", []):
            description = html_to_text(row.get("description", ""))
            locations = row.get("locationRestrictions") or []
            job = Job(
                source="himalayas",
                source_job_id=str(row.get("guid", "")),
                company=row.get("companyName", ""),
                title=row.get("title", ""),
                location=", ".join(locations) or "Remote",
                locations=locations,
                remote=True,
                work_model="remote",
                url=row.get("applicationLink") or row.get("guid", ""),
                description=description,
                posted_at=iso_date(row.get("pubDate")),
                seniority=(row.get("seniority") or [""])[0] if row.get("seniority") else "",
                tags=row.get("categories", []) or [],
            )
            if row.get("minSalary"):
                job.salary.min = int(row["minSalary"])
                job.salary.max = int(row.get("maxSalary") or row["minSalary"])
            yield _finish(job, description)


class TheMuse(JobSource):
    kind = "themuse"
    label = "The Muse"

    def fetch(self) -> Iterable[Job]:
        pages = int(self.param("pages", 3))
        for page in range(1, pages + 1):
            params: dict[str, Any] = {"page": page}
            if self.param("category"):
                params["category"] = self.param("category")
            if self.param("api_key"):
                params["api_key"] = self.param("api_key")
            data = self.http.get_json("https://www.themuse.com/api/public/jobs", params=params)
            if not data:
                break
            for row in data.get("results", []):
                description = html_to_text(row.get("contents", ""))
                locations = [loc.get("name", "") for loc in row.get("locations", [])]
                job = Job(
                    source="themuse",
                    source_job_id=str(row.get("id", "")),
                    company=(row.get("company") or {}).get("name", ""),
                    title=row.get("name", ""),
                    location=locations[0] if locations else "",
                    locations=locations,
                    url=(row.get("refs") or {}).get("landing_page", ""),
                    description=description,
                    description_html=row.get("contents", ""),
                    posted_at=iso_date(row.get("publication_date")),
                    seniority=(row.get("levels") or [{}])[0].get("name", "").lower(),
                    department=(row.get("categories") or [{}])[0].get("name", ""),
                )
                yield _finish(job, description)


class Adzuna(JobSource):
    kind = "adzuna"
    label = "Adzuna"
    needs_key = True

    def fetch(self) -> Iterable[Job]:
        app_id, app_key = self.param("app_id"), self.param("app_key")
        if not app_id or not app_key:
            return []
        country = self.param("country", "us")
        for term in (self.query_terms() or [""])[:3]:
            data = self.http.get_json(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1",
                params={"app_id": app_id, "app_key": app_key, "results_per_page": 50,
                        "what": term, "where": (self.search.locations or [""])[0],
                        "max_days_old": self.search.posted_within_days,
                        "content-type": "application/json"})
            for row in (data or {}).get("results", []):
                description = row.get("description", "")
                job = Job(
                    source="adzuna",
                    source_job_id=str(row.get("id", "")),
                    company=(row.get("company") or {}).get("display_name", ""),
                    title=row.get("title", ""),
                    location=(row.get("location") or {}).get("display_name", ""),
                    url=row.get("redirect_url", ""),
                    description=description,
                    posted_at=iso_date(row.get("created")),
                    employment_type=row.get("contract_time", ""),
                )
                if row.get("salary_min"):
                    job.salary.min = int(row["salary_min"])
                    job.salary.max = int(row.get("salary_max") or row["salary_min"])
                    job.salary.currency = {"us": "USD", "gb": "GBP", "in": "INR"}.get(country, "USD")
                yield _finish(job, description)


class USAJobs(JobSource):
    kind = "usajobs"
    label = "USAJOBS"
    needs_key = True

    def fetch(self) -> Iterable[Job]:
        api_key, email = self.param("api_key"), self.param("email")
        if not api_key or not email:
            return []
        headers = {"Authorization-Key": api_key, "User-Agent": email, "Host": "data.usajobs.gov"}
        for term in (self.query_terms() or [""])[:3]:
            data = self.http.get_json(
                "https://data.usajobs.gov/api/search",
                params={"Keyword": term, "ResultsPerPage": 50,
                        "LocationName": (self.search.locations or [""])[0]},
                headers=headers)
            items = ((data or {}).get("SearchResult") or {}).get("SearchResultItems", [])
            for item in items:
                row = item.get("MatchedObjectDescriptor", {})
                summary = row.get("UserArea", {}).get("Details", {}).get("JobSummary", "")
                description = html_to_text(summary or row.get("QualificationSummary", ""))
                locations = [loc.get("LocationName", "") for loc in row.get("PositionLocation", [])]
                job = Job(
                    source="usajobs",
                    source_job_id=str(row.get("PositionID", "")),
                    company=row.get("OrganizationName", ""),
                    title=row.get("PositionTitle", ""),
                    location=locations[0] if locations else "",
                    locations=locations,
                    url=row.get("PositionURI", ""),
                    apply_url=(row.get("ApplyURI") or [""])[0],
                    description=description,
                    posted_at=iso_date(row.get("PublicationStartDate")),
                    employment_type=", ".join(
                        s.get("Name", "") for s in row.get("PositionSchedule", [])),
                )
                pay = (row.get("PositionRemuneration") or [{}])[0]
                if pay.get("MinimumRange"):
                    job.salary.min = int(float(pay["MinimumRange"]))
                    job.salary.max = int(float(pay.get("MaximumRange") or pay["MinimumRange"]))
                yield _finish(job, description)


class HackerNewsHiring(JobSource):
    """The monthly 'Ask HN: Who is hiring?' thread - top-level comments are the postings."""

    kind = "hn_hiring"
    label = "HN Who is Hiring"

    def fetch(self) -> Iterable[Job]:
        search = self.http.get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": "Ask HN: Who is hiring?", "tags": "story", "hitsPerPage": 3})
        for hit in (search or {}).get("hits", []):
            if "who is hiring" not in (hit.get("title") or "").lower():
                continue
            thread = self.http.get_json(f"https://hn.algolia.com/api/v1/items/{hit['objectID']}")
            for comment in (thread or {}).get("children", [])[: int(self.param("limit", 120))]:
                text = html_to_text(comment.get("text") or "")
                if len(text) < 60:
                    continue
                header = text.splitlines()[0]
                company = re.split(r"\||\s[-–—]\s", header)[0].strip()[:80]
                title_match = re.search(
                    r"(engineer|developer|designer|scientist|manager|analyst|architect|sre|"
                    r"devops|researcher|lead)[^|\n]{0,60}", text, re.I)
                job = Job(
                    source="hn_hiring",
                    source_job_id=str(comment.get("id", "")),
                    company=company,
                    title=(title_match.group(0).strip()[:100] if title_match else header[:100]),
                    location="Remote" if re.search(r"\bremote\b", text, re.I) else "",
                    url=f"https://news.ycombinator.com/item?id={comment.get('id')}",
                    description=text,
                    posted_at=iso_date(comment.get("created_at")),
                    tags=["hn"],
                )
                if not job.company or not job.title:
                    continue
                yield _finish(job, text)
