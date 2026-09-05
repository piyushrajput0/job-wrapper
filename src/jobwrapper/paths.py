"""Filesystem layout. Everything the tool owns lives under one root."""

from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    """Data root. Override with JOBWRAPPER_HOME (useful for tests and multiple profiles)."""
    env = os.environ.get("JOBWRAPPER_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".jobwrapper"


def ensure_layout() -> dict[str, Path]:
    r = root()
    layout = {
        "root": r,
        "db": r / "jobwrapper.db",
        "config": r / "config.yaml",
        "profile": r / "profile.json",
        "master_resume": r / "master_resume.json",
        "vault": r / "vault.enc",
        "resumes": r / "artifacts" / "resumes",
        "cover_letters": r / "artifacts" / "cover_letters",
        "screenshots": r / "artifacts" / "screenshots",
        "pages": r / "artifacts" / "pages",
        "overleaf": r / "overleaf",
        "browser": r / "browser",
        "logs": r / "logs",
        "cache": r / "cache",
    }
    for key, path in layout.items():
        if key in {"db", "config", "profile", "master_resume", "vault"}:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    return layout


def package_data(name: str) -> Path:
    """A file shipped inside the package (the shared knowledge base)."""
    return Path(__file__).parent / "data" / name
