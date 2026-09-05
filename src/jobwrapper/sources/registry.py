"""Maps a config `kind` to an adapter class."""

from __future__ import annotations

from ..config import SearchConfig, SourceConfig
from ..logging_setup import get
from .aggregators import (
    Adzuna,
    Arbeitnow,
    HackerNewsHiring,
    Himalayas,
    Jobicy,
    RemoteOK,
    Remotive,
    TheMuse,
    USAJobs,
)
from .base import HttpClient, JobSource
from .boards import (
    Ashby,
    Breezy,
    Greenhouse,
    Lever,
    Personio,
    Recruitee,
    SmartRecruiters,
    Workable,
    Workday,
)
from .careerpage import CareerPage

log = get("sources")

REGISTRY: dict[str, type[JobSource]] = {
    cls.kind: cls
    for cls in (
        Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Breezy, Workday,
        RemoteOK, Remotive, Arbeitnow, Jobicy, Himalayas, TheMuse, Adzuna, USAJobs,
        HackerNewsHiring, CareerPage,
    )
}


def build_source(config: SourceConfig, http: HttpClient, search: SearchConfig) -> JobSource | None:
    cls = REGISTRY.get(config.kind)
    if cls is None:
        log.warning("unknown source kind '%s' (id=%s)", config.kind, config.id)
        return None
    return cls(config, http, search)


def available_kinds() -> list[dict[str, str | bool]]:
    return [
        {"kind": cls.kind, "label": cls.label, "needs_key": cls.needs_key}
        for cls in sorted(REGISTRY.values(), key=lambda c: c.kind)
    ]
