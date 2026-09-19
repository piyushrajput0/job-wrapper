"""The V1 discovery run: fan out to every enabled source, normalise, dedupe, score, store."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ..config import Config
from ..logging_setup import get
from ..models import Job, Profile
from ..store import Store
from .dedupe import dedupe_jobs
from .match import score_job

log = get("search")


@dataclass
class SearchReport:
    fetched: int = 0
    after_dedupe: int = 0
    new: int = 0
    updated: int = 0
    disqualified: int = 0
    off_target: int = 0
    per_source: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"fetched": self.fetched, "after_dedupe": self.after_dedupe, "new": self.new,
                "updated": self.updated, "disqualified": self.disqualified,
                "off_target": self.off_target,
                "per_source": self.per_source, "errors": self.errors}


class SearchEngine:
    def __init__(self, config: Config, store: Store, profile: Profile) -> None:
        # imported here rather than at module scope: sources import pipeline.normalize,
        # so a top-level import would close a cycle.
        from ..sources import HttpClient

        self.config = config
        self.store = store
        self.profile = profile
        self.http = HttpClient(user_agent=config.user_agent)

    def _title_prefilter(self, job: Job) -> bool:
        """Cheap filter before scoring, so a 10k-job aggregator pull does not cost 10k scorings."""
        search = self.config.search
        if not search.titles and not search.keywords:
            return True
        haystack = f"{job.title} {job.department}".lower()
        for term in search.titles:
            words = [w for w in re.findall(r"[a-z]+", term.lower()) if len(w) > 2]
            if words and all(w in haystack for w in words[:2]):
                return True
        for term in search.keywords:
            if term.lower() in haystack or term.lower() in job.description.lower()[:3000]:
                return True
        return False

    def run(self, *, only: list[str] | None = None, workers: int = 6) -> SearchReport:
        report = SearchReport()
        configs = [s for s in self.config.sources
                   if s.enabled and (not only or s.id in only or s.kind in only)]
        if not configs:
            log.warning("no sources enabled - add one with `jobwrapper sources add`")
            return report

        from ..sources import build_source

        collected: list[Job] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for source_config in configs:
                source = build_source(source_config, self.http, self.config.search)
                if source:
                    futures[pool.submit(self._fetch_one, source)] = source_config.id

            for future in as_completed(futures):
                source_id = futures[future]
                try:
                    jobs = future.result()
                    collected.extend(jobs)
                    report.per_source[source_id] = len(jobs)
                    self.store.sources.record_run(source_id, len(jobs))
                    log.info("%-16s %4d jobs", source_id, len(jobs))
                except Exception as exc:  # a broken source must not kill the run
                    report.errors[source_id] = str(exc)
                    self.store.sources.record_run(source_id, 0, str(exc))
                    log.warning("%-16s failed: %s", source_id, exc)

        report.fetched = len(collected)
        deduped = dedupe_jobs(collected)
        report.after_dedupe = len(deduped)

        for job in deduped:
            if not self._title_prefilter(job):
                report.off_target += 1
                continue
            result = score_job(job, self.profile, self.config.search, self.config.match)
            if result.disqualified:
                report.disqualified += 1
                continue
            job.match_score = result.score
            job.match_reasons = result.reasons
            job.match_gaps = result.gaps
            if result.score < self.config.match.min_score_to_list:
                report.disqualified += 1
                continue
            if self.store.jobs.upsert(job):
                report.new += 1
            else:
                report.updated += 1
                self.store.jobs.set_score(job)

        self.store.events.log("search", f"{report.new} new, {report.updated} updated",
                              **report.as_dict())
        return report

    @staticmethod
    def _fetch_one(source) -> list[Job]:
        return [job for job in source.fetch() if job.title and job.company]

    def close(self) -> None:
        self.http.close()
