"""The end-to-end run: find jobs, then work through them one at a time.

    Overleaf pull ─▶ search every source ─▶ dedupe + score ─▶ shortlist
                                                                 │
                        ┌────────────────── per job, in turn ─────┘
                        ▼
      extract the JD's keywords ─▶ rewrite the résumé around them (truthfulness
      firewall) ─▶ compile a PDF for this job ─▶ open the form ─▶ fill it ─▶
      review or submit ─▶ record ─▶ next job

One browser session is reused across the whole run, and there is a pause between
applications. Progress is reported step by step so the UI can show what it is doing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..config import Config
from ..llm import LLMClient
from ..logging_setup import get
from ..models import Application, Job, Profile
from ..models.resume import MasterResume
from ..store import Store

log = get("autopilot")

ProgressFn = Callable[["AutopilotEvent"], None]


@dataclass
class AutopilotEvent:
    stage: str                 # overleaf | search | shortlist | tailor | apply | done | error
    message: str
    index: int = 0
    total: int = 0
    job_id: str = ""
    company: str = ""
    title: str = ""
    status: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict:
        return {"stage": self.stage, "message": self.message, "index": self.index,
                "total": self.total, "job_id": self.job_id, "company": self.company,
                "title": self.title, "status": self.status, "at": self.at}


@dataclass
class AutopilotReport:
    searched: dict = field(default_factory=dict)
    shortlisted: int = 0
    submitted: int = 0
    ready_for_review: int = 0
    needs_input: int = 0
    skipped: int = 0
    failed: int = 0
    resumes_built: int = 0
    events: list[dict] = field(default_factory=list)
    applications: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"searched": self.searched, "shortlisted": self.shortlisted,
                "submitted": self.submitted, "ready_for_review": self.ready_for_review,
                "needs_input": self.needs_input, "skipped": self.skipped, "failed": self.failed,
                "resumes_built": self.resumes_built, "applications": self.applications,
                "events": self.events[-60:]}


class Autopilot:
    def __init__(self, config: Config, store: Store, profile: Profile, master: MasterResume,
                 llm: LLMClient | None = None, on_progress: ProgressFn | None = None) -> None:
        self.config = config
        self.store = store
        self.profile = profile
        self.master = master
        self.llm = llm or LLMClient(config.llm)
        self.on_progress = on_progress
        self.report = AutopilotReport()
        self._stop = False

    def stop(self) -> None:
        """Asked to stop: finish the job in flight, then halt."""
        self._stop = True

    def _emit(self, event: AutopilotEvent) -> None:
        self.report.events.append(event.as_dict())
        log.info("[%s] %s", event.stage, event.message)
        if self.on_progress:
            try:
                self.on_progress(event)
            except Exception:
                pass

    # ------------------------------------------------------------------ stages
    def sync_overleaf(self) -> None:
        url = self.config.resume.overleaf_git_url
        if not url:
            return
        from pathlib import Path

        from .. import paths
        from ..resume.importer import import_master_resume
        from ..resume.overleaf import sync
        from ..vault import Vault

        self._emit(AutopilotEvent("overleaf", "pulling the latest résumé from Overleaf"))
        result = sync(url, paths.ensure_layout()["overleaf"], Vault(interactive=False))
        if not result.ok or not result.main_tex:
            self._emit(AutopilotEvent("overleaf", f"skipped: {result.message}"))
            return
        master = import_master_resume(Path(result.main_tex), self.llm,
                                      use_llm=self.llm.available())
        master.save(paths.ensure_layout()["master_resume"])
        self.master = master
        self._emit(AutopilotEvent(
            "overleaf", f"imported {len(master.experience)} role(s) from {result.main_tex.name}"))

    def search(self) -> None:
        from .search import SearchEngine

        self._emit(AutopilotEvent("search", "searching every enabled source"))
        engine = SearchEngine(self.config, self.store, self.profile)
        try:
            report = engine.run()
        finally:
            engine.close()
        self.report.searched = report.as_dict()
        self._emit(AutopilotEvent(
            "search", f"{report.fetched} found, {report.after_dedupe} unique, "
                      f"{report.new} new above the score floor"))

    def shortlist(self, limit: int) -> list[Job]:
        floor = self.config.match.min_score_to_apply
        candidates = self.store.jobs.list(status="new", min_score=floor, limit=limit * 4)
        picked: list[Job] = []
        for job in candidates:
            existing = self.store.applications.for_job(job.id)
            if existing and existing.status in {"submitted", "ready_for_review", "needs_input"}:
                continue
            picked.append(job)
            if len(picked) >= limit:
                break
        self.report.shortlisted = len(picked)
        self._emit(AutopilotEvent(
            "shortlist", f"{len(picked)} job(s) scoring {floor}+ and not yet applied to",
            total=len(picked)))
        return picked

    # ------------------------------------------------------------------ the run
    def run(self, limit: int = 10, do_search: bool = True, do_overleaf: bool = True,
            job_ids: list[str] | None = None) -> AutopilotReport:
        import time

        from ..apply import ApplicationRunner
        from ..apply.browser import BrowserSession

        if do_overleaf:
            self.sync_overleaf()
        if do_search and not job_ids:
            self.search()

        if job_ids:
            jobs = [j for j in (self.store.jobs.get(i) for i in job_ids) if j]
            self.report.shortlisted = len(jobs)
        else:
            jobs = self.shortlist(limit)

        if not jobs:
            self._emit(AutopilotEvent("done", "nothing to apply to right now"))
            return self.report

        runner = ApplicationRunner(self.config, self.store, self.profile, self.master, self.llm)
        total = len(jobs)

        with BrowserSession(self.config.apply) as session:
            for index, job in enumerate(jobs, start=1):
                if self._stop:
                    self._emit(AutopilotEvent("done", f"stopped after {index - 1} of {total}"))
                    break

                self._emit(AutopilotEvent(
                    "tailor", "reading the job description and rewriting the résumé for it",
                    index=index, total=total, job_id=job.id, company=job.company, title=job.title))

                try:
                    application = runner.apply_to(job, session)
                except Exception as exc:                     # one bad page must not end the run
                    log.exception("autopilot: %s failed", job.short())
                    application = Application(job_id=job.id, company=job.company, title=job.title,
                                              status="failed", error=str(exc)[:400])
                    self.store.applications.save(application)

                if application.resume_path:
                    self.report.resumes_built += 1
                bucket = {"submitted": "submitted", "ready_for_review": "ready_for_review",
                          "needs_input": "needs_input", "skipped": "skipped",
                          "duplicate": "skipped", "planned": "ready_for_review"}.get(
                              application.status, "failed")
                setattr(self.report, bucket, getattr(self.report, bucket) + 1)
                self.report.applications.append({
                    "id": application.id, "company": application.company,
                    "title": application.title, "status": application.status,
                    "fields_filled": application.fields_filled,
                    "resume": application.resume_path, "notes": application.notes[:200],
                })

                self._emit(AutopilotEvent(
                    "apply", self._describe(application), index=index, total=total,
                    job_id=job.id, company=job.company, title=job.title,
                    status=application.status))

                if index < total and not self._stop:
                    pause = self.config.apply.min_seconds_between_applications
                    if pause:
                        time.sleep(pause)

        self._emit(AutopilotEvent(
            "done", f"{self.report.submitted} submitted · "
                    f"{self.report.ready_for_review} ready for your review · "
                    f"{self.report.needs_input} need an answer · {self.report.failed} failed"))
        self.store.events.log("autopilot", "run finished", **{
            k: v for k, v in self.report.as_dict().items() if isinstance(v, (int, str))})
        return self.report

    @staticmethod
    def _describe(application: Application) -> str:
        return {
            "submitted": "submitted",
            "ready_for_review": f"filled {application.fields_filled} field(s) - waiting for you to submit",
            "needs_input": f"needs you: {application.notes[:90]}",
            "skipped": f"skipped: {application.notes[:90]}",
            "duplicate": "already applied",
            "planned": "planned (dry run)",
            "failed": f"failed: {application.error[:90]}",
        }.get(application.status, application.status)
