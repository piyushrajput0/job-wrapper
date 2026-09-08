"""Filesystem layout. Everything the tool owns lives under one root."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
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


def atomic_write(path: Path, text: str) -> Path:
    """Write via a temporary file and rename.

    A half-written profile.json is worse than no profile.json: the app cannot start and the
    desktop window has no terminal to show the traceback in. Renaming is atomic on POSIX, so a
    crash mid-write leaves the previous file intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def quarantine(path: Path, reason: str = "") -> Path | None:
    """Move a file we could not read aside instead of deleting or overwriting it."""
    if not path.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    spoiled = path.with_name(f"{path.name}.corrupt-{stamp}")
    counter = 1
    while spoiled.exists():                 # two failures in the same second must not collide
        spoiled = path.with_name(f"{path.name}.corrupt-{stamp}-{counter}")
        counter += 1
    try:
        path.rename(spoiled)
        logging.getLogger("jobwrapper").warning(
            "%s could not be read (%s); kept a copy at %s and started from defaults",
            path.name, reason or "unreadable", spoiled.name)
        return spoiled
    except OSError:
        return None
