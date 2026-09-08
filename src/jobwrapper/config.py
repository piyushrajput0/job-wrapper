"""Runtime configuration: YAML on disk, environment overrides, safe defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from . import paths

AutonomyLevel = Literal["dryrun", "review", "auto"]


class SearchConfig(BaseModel):
    titles: list[str] = Field(default_factory=lambda: ["Software Engineer"])
    exclude_titles: list[str] = Field(default_factory=lambda: ["Intern", "Manager", "Director"])
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["Remote"])
    remote_only: bool = False
    seniority: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=lambda: ["full_time"])
    posted_within_days: int = 30
    min_salary: int | None = None
    exclude_companies: list[str] = Field(default_factory=list)
    only_companies: list[str] = Field(default_factory=list)
    require_sponsorship_friendly: bool = False


class SourceConfig(BaseModel):
    """One configured job source. `params` is adapter-specific (board token, key, ...)."""

    id: str
    kind: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class MatchConfig(BaseModel):
    min_score_to_list: int = 40
    min_score_to_apply: int = 65
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "title": 0.25,
            "skills": 0.30,
            "seniority": 0.15,
            "location": 0.15,
            "salary": 0.05,
            "recency": 0.05,
            "authorization": 0.05,
        }
    )


class ResumeConfig(BaseModel):
    engine: Literal["auto", "tectonic", "pdflatex", "xelatex", "latexmk", "remote", "html"] = "auto"
    max_pages: int = 1
    template: str = "resume.tex.j2"
    html_template: str = "resume.html.j2"
    allow_remote_latex: bool = False
    remote_latex_url: str = "https://texlive.net/cgi-bin/latexcgi"
    truthfulness: Literal["strict", "review", "off"] = "strict"
    max_new_keywords: int = 12
    keep_every_pdf: bool = True
    overleaf_git_url: str | None = None


class ApplyConfig(BaseModel):
    autonomy: AutonomyLevel = "review"
    daily_cap: int = 15
    per_company_cap: int = 3
    headless: bool = False
    slow_mo_ms: int = 120
    timeout_ms: int = 45_000
    auto_signup: bool = False
    allow_domains: list[str] = Field(default_factory=list)
    block_domains: list[str] = Field(default_factory=list)
    screenshot_every_step: bool = True
    pause_on_captcha: bool = True
    min_seconds_between_applications: int = 45
    generate_cover_letter: bool = True


class LLMConfig(BaseModel):
    enabled: bool = True
    provider: str = "anthropic"          # see llm/providers.py for the full list
    model: str = "claude-sonnet-5"
    cheap_model: str = ""                # falls back to `model` when empty
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = 8000
    cache_prompts: bool = True
    offline_fallback: bool = True
    monthly_budget_usd: float | None = None


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787
    token: str | None = None
    allow_extension_origins: list[str] = Field(default_factory=list)


class Config(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    match: MatchConfig = Field(default_factory=MatchConfig)
    resume: ResumeConfig = Field(default_factory=ResumeConfig)
    apply: ApplyConfig = Field(default_factory=ApplyConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    user_agent: str = "jobwrapper/0.1 (+https://github.com/piyushrajput0/job-wrapper)"

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or paths.ensure_layout()["config"]
        if path.exists():
            raw = yaml.safe_load(path.read_text()) or {}
            cfg = cls.model_validate(raw)
        else:
            cfg = cls()
            if not cfg.sources:
                cfg.sources = default_sources()
            cfg.save(path)
        return cfg.apply_env()

    def apply_env(self) -> Config:
        if os.environ.get("JOBWRAPPER_HEADLESS"):
            self.apply.headless = os.environ["JOBWRAPPER_HEADLESS"] not in {"0", "false", ""}
        if os.environ.get("JOBWRAPPER_AUTONOMY"):
            level = os.environ["JOBWRAPPER_AUTONOMY"]
            if level in {"dryrun", "review", "auto"}:
                self.apply.autonomy = level  # type: ignore[assignment]
        if os.environ.get("JOBWRAPPER_NO_LLM"):
            self.llm.enabled = False
        if os.environ.get("JOBWRAPPER_SERVER_TOKEN"):
            self.server.token = os.environ["JOBWRAPPER_SERVER_TOKEN"]
        return self

    def save(self, path: Path | None = None) -> Path:
        path = path or paths.ensure_layout()["config"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False))
        return path


def default_sources() -> list[SourceConfig]:
    """Sources that work with no API key at all."""
    return [
        SourceConfig(id="remoteok", kind="remoteok"),
        SourceConfig(id="remotive", kind="remotive"),
        SourceConfig(id="arbeitnow", kind="arbeitnow"),
        SourceConfig(id="jobicy", kind="jobicy"),
        SourceConfig(id="himalayas", kind="himalayas"),
        SourceConfig(id="themuse", kind="themuse"),
        SourceConfig(id="hn_hiring", kind="hn_hiring", enabled=False),
        SourceConfig(id="usajobs", kind="usajobs", enabled=False, params={"api_key": "", "email": ""}),
        SourceConfig(id="adzuna", kind="adzuna", enabled=False, params={"app_id": "", "app_key": "", "country": "us"}),
    ]
