"""Source adapter contract + a polite HTTP client."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import httpx

from ..config import SearchConfig, SourceConfig
from ..logging_setup import get
from ..models import Job

log = get("sources")

DEFAULT_UA = "jobwrapper/0.1 (+https://github.com/piyushrajput0/job-wrapper)"


class HttpClient:
    """One shared client: sane timeouts, retries, a real User-Agent, and per-host throttling."""

    def __init__(self, user_agent: str = DEFAULT_UA, *, timeout: float = 25.0,
                 min_interval: float = 0.7) -> None:
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self.min_interval = min_interval
        self._last_call: dict[str, float] = {}

    def _throttle(self, url: str) -> None:
        host = httpx.URL(url).host or ""
        last = self._last_call.get(host, 0.0)
        wait = self.min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        self._last_call[host] = time.monotonic()

    def get(self, url: str, *, params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None, retries: int = 2) -> httpx.Response | None:
        for attempt in range(retries + 1):
            try:
                self._throttle(url)
                response = self.client.get(url, params=params, headers=headers)
                if response.status_code == 429:
                    time.sleep(2 + attempt * 3)
                    continue
                if response.status_code >= 500:
                    time.sleep(1 + attempt)
                    continue
                if response.status_code >= 400:
                    log.debug("GET %s -> %s", url, response.status_code)
                    return None
                return response
            except httpx.HTTPError as exc:
                log.debug("GET %s failed (%s/%s): %s", url, attempt + 1, retries + 1, exc)
                time.sleep(1 + attempt)
        return None

    def get_json(self, url: str, **kwargs: Any) -> Any:
        response = self.get(url, **kwargs)
        if response is None:
            return None
        try:
            return response.json()
        except Exception:
            log.debug("non-JSON body from %s", url)
            return None

    def post_json(self, url: str, payload: dict[str, Any], *,
                  headers: dict[str, str] | None = None) -> Any:
        try:
            self._throttle(url)
            response = self.client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                return None
            return response.json()
        except Exception as exc:
            log.debug("POST %s failed: %s", url, exc)
            return None

    def close(self) -> None:
        self.client.close()


class JobSource(ABC):
    """One job platform. `fetch` yields normalised Jobs; failures are logged, never raised."""

    kind: str = "base"
    label: str = "Base"
    needs_key: bool = False
    respects_tos: bool = True

    def __init__(self, config: SourceConfig, http: HttpClient, search: SearchConfig) -> None:
        self.config = config
        self.http = http
        self.search = search

    @property
    def id(self) -> str:
        return self.config.id

    def param(self, name: str, default: Any = None) -> Any:
        return self.config.params.get(name, default)

    @abstractmethod
    def fetch(self) -> Iterable[Job]:
        ...

    def query_terms(self) -> list[str]:
        return [t for t in (self.search.titles + self.search.keywords) if t]

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"
