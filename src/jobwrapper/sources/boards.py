"""Per-company ATS job-board APIs.

These are the highest-quality source in the system: the data is first-party, the JD is complete,
and the apply URL leads to a form we have a first-class adapter for. Greenhouse even hands us
the application's field definitions before we open a browser.
"""

from __future__ import annotations

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


def _finish(job: Job) -> Job:
    job.seniority = job.seniority or detect_seniority(job.title, job.description)
    job.work_model = job.work_model or detect_work_model(job.description, job.location)
    job.remote = job.remote or job.work_model == "remote"
    job.employment_type = job.employment_type or detect_employment_type(job.description)
    if not job.salary.min:
        job.salary = parse_salary(job.description)
    job.sponsorship_mentioned = sponsorship_signal(job.description)[0]
    job.id = job.compute_id()
    return job


def _boards(source: JobSource) -> list[dict[str, str]]:
    """`boards` is a list of {token, company} - one adapter instance can cover many companies."""
    raw = source.param("boards") or []
    out = []
    for entry in raw:
        if isinstance(entry, str):
            out.append({"token": entry, "company": entry})
        elif isinstance(entry, dict) and entry.get("token"):
            out.append({"token": entry["token"], "company": entry.get("company", entry["token"])})
    token = source.param("token")
    if token:
        out.append({"token": token, "company": source.param("company", token)})
    return out


class Greenhouse(JobSource):
    kind = "greenhouse"
    label = "Greenhouse"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            token = board["token"]
            data = self.http.get_json(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                params={"content": "true"})
            for row in (data or {}).get("jobs", []):
                content = html_to_text(row.get("content", ""))
                offices = [o.get("name", "") for o in row.get("offices", []) if o.get("name")]
                job = Job(
                    source="greenhouse",
                    source_job_id=str(row.get("id", "")),
                    company=(row.get("company_name") or board["company"]),
                    title=row.get("title", ""),
                    location=(row.get("location") or {}).get("name", ""),
                    locations=offices,
                    url=row.get("absolute_url", ""),
                    apply_url=row.get("absolute_url", ""),
                    ats="greenhouse",
                    description=content,
                    description_html=row.get("content", ""),
                    posted_at=iso_date(row.get("updated_at") or row.get("first_published")),
                    department=", ".join(d.get("name", "") for d in row.get("departments", [])),
                    raw={"board_token": token},
                )
                metadata = row.get("metadata") or []
                for meta in metadata:
                    if "salary" in str(meta.get("name", "")).lower() and meta.get("value"):
                        job.salary = parse_salary(str(meta["value"]))
                yield _finish(job)

    def application_questions(self, token: str, job_id: str) -> list[dict[str, Any]]:
        """Greenhouse publishes the application's own field definitions. Free fill plan."""
        data = self.http.get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}",
            params={"questions": "true"})
        return (data or {}).get("questions", []) or []


class Lever(JobSource):
    kind = "lever"
    label = "Lever"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            site = board["token"]
            skip = 0
            while True:
                rows = self.http.get_json(
                    f"https://api.lever.co/v0/postings/{site}",
                    params={"mode": "json", "limit": 100, "skip": skip})
                if not rows:
                    break
                for row in rows:
                    categories = row.get("categories") or {}
                    description = html_to_text(row.get("description", ""))
                    lists_text = "\n".join(
                        f"{item.get('text', '')}\n{html_to_text(item.get('content', ''))}"
                        for item in row.get("lists", []))
                    full = f"{description}\n\n{lists_text}".strip()
                    job = Job(
                        source="lever",
                        source_job_id=str(row.get("id", "")),
                        company=board["company"],
                        title=row.get("text", ""),
                        location=categories.get("location", ""),
                        url=row.get("hostedUrl", ""),
                        apply_url=row.get("applyUrl") or f"{row.get('hostedUrl', '')}/apply",
                        ats="lever",
                        description=full,
                        description_html=row.get("descriptionPlain", ""),
                        posted_at=iso_date(row.get("createdAt")),
                        department=categories.get("team", ""),
                        employment_type=categories.get("commitment", ""),
                        work_model="remote" if categories.get("location", "").lower().startswith(
                            "remote") else "",
                        raw={"site": site},
                    )
                    if categories.get("allLocations"):
                        job.locations = categories["allLocations"]
                    yield _finish(job)
                if len(rows) < 100:
                    break
                skip += 100


class Ashby(JobSource):
    kind = "ashby"
    label = "Ashby"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            name = board["token"]
            data = self.http.get_json(
                f"https://api.ashbyhq.com/posting-api/job-board/{name}",
                params={"includeCompensation": "true"})
            for row in (data or {}).get("jobs", []):
                description = html_to_text(row.get("descriptionHtml", "")) or row.get(
                    "descriptionPlain", "")
                job = Job(
                    source="ashby",
                    source_job_id=str(row.get("id", "")),
                    company=board["company"],
                    title=row.get("title", ""),
                    location=row.get("location", ""),
                    locations=[a.get("postingLocation", {}).get("locationName", "")
                               for a in row.get("secondaryLocations", [])],
                    remote=bool(row.get("isRemote")),
                    url=row.get("jobUrl", ""),
                    apply_url=row.get("applyUrl") or row.get("jobUrl", ""),
                    ats="ashby",
                    description=description,
                    description_html=row.get("descriptionHtml", ""),
                    posted_at=iso_date(row.get("publishedAt")),
                    department=row.get("department", ""),
                    employment_type=row.get("employmentType", ""),
                    raw={"board": name},
                )
                comp = row.get("compensation") or {}
                for tier in comp.get("compensationTiers", []) or []:
                    for component in tier.get("components", []) or []:
                        if component.get("compensationType") == "Salary":
                            job.salary.min = int(component.get("minValue") or 0) or None
                            job.salary.max = int(component.get("maxValue") or 0) or None
                            job.salary.currency = component.get("currencyCode", "USD")
                            break
                yield _finish(job)


class Workable(JobSource):
    kind = "workable"
    label = "Workable"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            account = board["token"]
            data = self.http.get_json(
                f"https://apply.workable.com/api/v1/widget/accounts/{account}",
                params={"details": "true"})
            for row in (data or {}).get("jobs", []):
                description = html_to_text(row.get("description", ""))
                job = Job(
                    source="workable",
                    source_job_id=str(row.get("shortcode", "")),
                    company=(data.get("name") or board["company"]),
                    title=row.get("title", ""),
                    location=", ".join(
                        p for p in [row.get("city"), row.get("state"), row.get("country")] if p),
                    remote=bool(row.get("telecommuting")),
                    url=row.get("url") or row.get("application_url", ""),
                    apply_url=row.get("application_url") or row.get("url", ""),
                    ats="workable",
                    description=description,
                    description_html=row.get("description", ""),
                    posted_at=iso_date(row.get("published_on") or row.get("created_at")),
                    department=row.get("department", ""),
                    employment_type=row.get("employment_type", ""),
                    raw={"account": account},
                )
                yield _finish(job)


class SmartRecruiters(JobSource):
    kind = "smartrecruiters"
    label = "SmartRecruiters"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            company = board["token"]
            offset = 0
            while True:
                data = self.http.get_json(
                    f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                    params={"limit": 100, "offset": offset})
                rows = (data or {}).get("content", [])
                if not rows:
                    break
                for row in rows:
                    location = row.get("location") or {}
                    detail = self.http.get_json(
                        f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{row.get('id')}")
                    sections = ((detail or {}).get("jobAd") or {}).get("sections") or {}
                    description = "\n\n".join(
                        html_to_text((sections.get(key) or {}).get("text", ""))
                        for key in ("companyDescription", "jobDescription", "qualifications",
                                    "additionalInformation"))
                    job = Job(
                        source="smartrecruiters",
                        source_job_id=str(row.get("id", "")),
                        company=(row.get("company") or {}).get("name", board["company"]),
                        title=row.get("name", ""),
                        location=", ".join(
                            p for p in [location.get("city"), location.get("region"),
                                        location.get("country")] if p),
                        remote=bool(location.get("remote")),
                        url=row.get("ref", ""),
                        apply_url=f"https://jobs.smartrecruiters.com/{company}/{row.get('id')}",
                        ats="smartrecruiters",
                        description=description.strip(),
                        posted_at=iso_date(row.get("releasedDate")),
                        department=(row.get("department") or {}).get("label", ""),
                        employment_type=(row.get("typeOfEmployment") or {}).get("label", ""),
                        raw={"company": company},
                    )
                    yield _finish(job)
                offset += 100
                if offset > int(self.param("max", 300)):
                    break


class Recruitee(JobSource):
    kind = "recruitee"
    label = "Recruitee"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            company = board["token"]
            data = self.http.get_json(f"https://{company}.recruitee.com/api/offers/")
            for row in (data or {}).get("offers", []):
                description = html_to_text(row.get("description", "")) + "\n" + html_to_text(
                    row.get("requirements", ""))
                job = Job(
                    source="recruitee",
                    source_job_id=str(row.get("id", "")),
                    company=board["company"],
                    title=row.get("title", ""),
                    location=row.get("location") or row.get("city", ""),
                    remote=bool(row.get("remote")),
                    url=row.get("careers_url") or row.get("careers_apply_url", ""),
                    apply_url=row.get("careers_apply_url", ""),
                    ats="recruitee",
                    description=description.strip(),
                    posted_at=iso_date(row.get("published_at")),
                    department=row.get("department", ""),
                    employment_type=row.get("employment_type_code", ""),
                )
                yield _finish(job)


class Personio(JobSource):
    kind = "personio"
    label = "Personio"

    def fetch(self) -> Iterable[Job]:
        import xml.etree.ElementTree as ET

        for board in _boards(self):
            company = board["token"]
            response = self.http.get(f"https://{company}.jobs.personio.de/xml")
            if response is None:
                continue
            try:
                root = ET.fromstring(response.text)
            except ET.ParseError:
                continue
            for position in root.iter("position"):
                def text(tag: str, element=position) -> str:
                    node = element.find(tag)
                    return (node.text or "").strip() if node is not None else ""

                description = html_to_text(
                    " ".join(el.text or "" for el in position.iter("value")))
                job = Job(
                    source="personio",
                    source_job_id=text("id"),
                    company=board["company"],
                    title=text("name"),
                    location=text("office"),
                    url=f"https://{company}.jobs.personio.de/job/{text('id')}",
                    ats="personio",
                    description=description,
                    posted_at=iso_date(text("createdAt")),
                    department=text("department"),
                    employment_type=text("employmentType"),
                )
                yield _finish(job)


class Breezy(JobSource):
    kind = "breezy"
    label = "Breezy HR"

    def fetch(self) -> Iterable[Job]:
        for board in _boards(self):
            company = board["token"]
            rows = self.http.get_json(f"https://{company}.breezy.hr/json")
            for row in rows or []:
                description = html_to_text(row.get("description", ""))
                location = row.get("location") or {}
                job = Job(
                    source="breezy",
                    source_job_id=str(row.get("id", "")),
                    company=board["company"],
                    title=row.get("name", ""),
                    location=", ".join(p for p in [
                        (location.get("city") or ""),
                        ((location.get("country") or {}).get("name", ""))] if p),
                    remote=bool(location.get("is_remote")),
                    url=row.get("url", ""),
                    ats="breezy",
                    description=description,
                    posted_at=iso_date(row.get("published_date")),
                    department=(row.get("department") or ""),
                    employment_type=(row.get("type") or {}).get("name", ""),
                )
                yield _finish(job)


class Workday(JobSource):
    """The CXS endpoint Workday's own SPA uses. One entry per tenant+site."""

    kind = "workday"
    label = "Workday"

    def fetch(self) -> Iterable[Job]:
        tenants = self.param("tenants") or []
        for tenant in tenants:
            host = tenant.get("host")          # e.g. acme.wd1.myworkdayjobs.com
            name = tenant.get("tenant")        # e.g. acme
            site = tenant.get("site")          # e.g. External
            company = tenant.get("company", name)
            if not (host and name and site):
                continue
            offset = 0
            while offset <= int(self.param("max", 200)):
                data = self.http.post_json(
                    f"https://{host}/wday/cxs/{name}/{site}/jobs",
                    {"appliedFacets": {}, "limit": 20, "offset": offset,
                     "searchText": (self.query_terms() or [""])[0]},
                    headers={"Content-Type": "application/json", "Accept": "application/json"})
                rows = (data or {}).get("jobPostings", [])
                if not rows:
                    break
                for row in rows:
                    path = row.get("externalPath", "")
                    detail = self.http.get_json(f"https://{host}/wday/cxs/{name}/{site}{path}")
                    info = (detail or {}).get("jobPostingInfo", {})
                    description = html_to_text(info.get("jobDescription", ""))
                    job = Job(
                        source="workday",
                        source_job_id=str(info.get("id") or row.get("bulletFields", [""])[0]),
                        company=company,
                        title=row.get("title", ""),
                        location=row.get("locationsText") or info.get("location", ""),
                        url=f"https://{host}/en-US/{site}{path}",
                        apply_url=info.get("externalUrl")
                        or f"https://{host}/en-US/{site}{path}/apply",
                        ats="workday",
                        description=description,
                        description_html=info.get("jobDescription", ""),
                        posted_at=iso_date(info.get("startDate")),
                        employment_type=info.get("timeType", ""),
                        remote=bool(info.get("remoteType")),
                        raw={"host": host, "tenant": name, "site": site},
                    )
                    yield _finish(job)
                offset += 20
