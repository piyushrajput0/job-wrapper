"""Overleaf sync via the Git bridge.

Overleaf has no compile API, but paid projects expose a Git remote
(https://git.overleaf.com/<project-id>). We clone it, read the .tex, and compile locally. The
token is stored in the encrypted vault, never in the config file.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from ..logging_setup import get
from ..vault import Credential, Vault

log = get("resume.overleaf")
OVERLEAF_HOST = "git.overleaf.com"


@dataclass
class SyncResult:
    ok: bool
    path: Path | None = None
    main_tex: Path | None = None
    message: str = ""


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _authenticated_url(url: str, token: str) -> str:
    parsed = urlparse(url)
    netloc = f"git:{quote(token, safe='')}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def find_main_tex(directory: Path) -> Path | None:
    candidates = sorted(directory.rglob("*.tex"))
    for name in ("main.tex", "resume.tex", "cv.tex"):
        for candidate in candidates:
            if candidate.name.lower() == name:
                return candidate
    for candidate in candidates:
        try:
            if re.search(r"\\documentclass", candidate.read_text(errors="replace")):
                return candidate
        except OSError:
            continue
    return candidates[0] if candidates else None


def sync(git_url: str, dest: Path, vault: Vault | None = None,
         token: str | None = None) -> SyncResult:
    """Clone (first run) or pull (subsequent runs) the Overleaf project."""
    if not git_url:
        return SyncResult(False, message="no overleaf_git_url configured")

    if token is None and vault is not None:
        cred = vault.get(OVERLEAF_HOST)
        token = cred.password if cred else None
    if not token:
        return SyncResult(False, message=(
            "no Overleaf git token. Create one at Overleaf > Account Settings > Git integration, "
            "then run: jobwrapper resume overleaf-auth"))

    dest.mkdir(parents=True, exist_ok=True)
    authenticated = _authenticated_url(git_url, token)

    if (dest / ".git").exists():
        code, output = _run(["git", "pull", "--ff-only", authenticated], cwd=dest)
        action = "pulled"
    else:
        for child in dest.iterdir():
            if child.is_dir():
                import shutil

                shutil.rmtree(child)
            else:
                child.unlink()
        code, output = _run(["git", "clone", "--depth", "1", authenticated, str(dest)])
        action = "cloned"

    if code != 0:
        redacted = output.replace(token, "***")
        return SyncResult(False, message=f"git {action} failed: {redacted[:400]}")

    main = find_main_tex(dest)
    log.info("%s Overleaf project into %s (main: %s)", action, dest, main.name if main else "?")
    return SyncResult(True, path=dest, main_tex=main, message=f"{action} successfully")


def save_token(token: str, vault: Vault) -> None:
    vault.put(Credential(domain=OVERLEAF_HOST, username="git", password=token,
                         notes="Overleaf git-bridge token"))


def push(dest: Path, message: str = "Update from jobwrapper", token: str | None = None,
         git_url: str = "") -> SyncResult:
    """Optional: write tailored variants back to the Overleaf project."""
    code, output = _run(["git", "add", "-A"], cwd=dest)
    if code != 0:
        return SyncResult(False, message=output[:300])
    code, output = _run(["git", "commit", "-m", message], cwd=dest)
    if code != 0 and "nothing to commit" in output:
        return SyncResult(True, message="nothing to push")
    remote = _authenticated_url(git_url, token) if (git_url and token) else "origin"
    code, output = _run(["git", "push", remote], cwd=dest)
    if code != 0:
        return SyncResult(False, message=(output.replace(token or "\0", "***"))[:300])
    return SyncResult(True, message="pushed")
