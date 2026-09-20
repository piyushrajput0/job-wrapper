"""Turning rendered source into a PDF.

Engine cascade, best first:
  tectonic -> latexmk -> pdflatex -> xelatex -> remote LaTeX service (opt-in) -> HTML via
  the Playwright Chromium that is already installed for applying.

The last fallback matters: it means a user with no TeX installation still gets a per-job PDF.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import ResumeConfig
from ..logging_setup import get

log = get("resume.compile")

ENGINES = ["tectonic", "latexmk", "pdflatex", "xelatex"]


@dataclass
class CompileResult:
    pdf_path: Path | None = None
    engine: str = ""
    pages: int = 0
    log_tail: str = ""
    ok: bool = False
    error: str = ""


# A .app launched from Finder inherits launchd's PATH - /usr/bin:/bin:/usr/sbin:/sbin -
# not the shell's. Homebrew and MacTeX both install outside it, so an engine the user has
# installed is invisible to the desktop build while working fine from a terminal.
EXTRA_BIN_DIRS = (
    "/opt/homebrew/bin",          # Homebrew, Apple silicon
    "/usr/local/bin",             # Homebrew, Intel
    "/Library/TeX/texbin",        # MacTeX
    "/usr/local/texlive/2025/bin/universal-darwin",
    "/usr/local/texlive/2024/bin/universal-darwin",
    str(Path.home() / ".cargo" / "bin"),          # cargo install tectonic
    str(Path.home() / ".local" / "bin"),
    "/snap/bin",
)


def find_engine(name: str) -> str | None:
    """Full path to a LaTeX engine, searching beyond PATH."""
    found = shutil.which(name)
    if found:
        return found
    for directory in EXTRA_BIN_DIRS:
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def available_engines() -> list[str]:
    return [engine for engine in ENGINES if find_engine(engine)]


def count_pages(pdf: Path) -> int:
    try:
        raw = pdf.read_bytes()
    except OSError:
        return 0
    counts = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    if counts:
        return counts
    match = re.findall(rb"/Count\s+(\d+)", raw)
    return int(match[-1]) if match else 0


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr)[-4000:]
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]} timed out after {timeout}s"


def compile_latex(tex_source: str, out_pdf: Path, config: ResumeConfig | None = None) -> CompileResult:
    config = config or ResumeConfig()
    engines = available_engines()
    if config.engine not in ("auto", "remote", "html") and config.engine in engines:
        engines = [config.engine]

    with tempfile.TemporaryDirectory(prefix="jobwrapper-tex-") as tmp:
        workdir = Path(tmp)
        tex_file = workdir / "resume.tex"
        tex_file.write_text(tex_source, encoding="utf-8")

        for engine in engines:
            binary = find_engine(engine) or engine
            if engine == "tectonic":
                code, output = _run([binary, "-X", "compile", "--outfmt", "pdf",
                                     "--keep-logs", "-o", str(workdir), str(tex_file)], workdir)
                if code != 0:  # older tectonic has no `-X compile`
                    code, output = _run([binary, str(tex_file)], workdir)
            elif engine == "latexmk":
                code, output = _run([binary, "-pdf", "-interaction=nonstopmode",
                                     "-halt-on-error", str(tex_file)], workdir)
            else:
                code, output = _run([binary, "-interaction=nonstopmode", "-halt-on-error",
                                     str(tex_file)], workdir)
                if code == 0:  # second pass for references/page numbers
                    _run([binary, "-interaction=nonstopmode", str(tex_file)], workdir)

            produced = workdir / "resume.pdf"
            if produced.exists() and produced.stat().st_size > 1000:
                out_pdf.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(produced, out_pdf)
                return CompileResult(pdf_path=out_pdf, engine=engine, pages=count_pages(out_pdf),
                                     log_tail=output[-1200:], ok=True)
            log.debug("%s failed (exit %s)", engine, code)

    if config.allow_remote_latex:
        result = _compile_remote(tex_source, out_pdf, config)
        if result.ok:
            return result

    return CompileResult(ok=False, error="no LaTeX engine produced a PDF "
                                         f"(tried: {', '.join(engines) or 'none installed'})")


def _compile_remote(tex_source: str, out_pdf: Path, config: ResumeConfig) -> CompileResult:
    """Opt-in only: this uploads the resume source to a third-party compile service."""
    import httpx

    try:
        response = httpx.post(
            config.remote_latex_url,
            data={"filecontents[]": tex_source, "filename[]": "resume.tex",
                  "engine": "pdflatex", "return": "pdf"},
            timeout=90, follow_redirects=True)
        if response.status_code == 200 and response.content[:4] == b"%PDF":
            out_pdf.parent.mkdir(parents=True, exist_ok=True)
            out_pdf.write_bytes(response.content)
            return CompileResult(pdf_path=out_pdf, engine="remote", pages=count_pages(out_pdf),
                                 ok=True)
        return CompileResult(ok=False, error=f"remote compile returned {response.status_code}")
    except Exception as exc:
        return CompileResult(ok=False, error=f"remote compile failed: {exc}")


def _print_html(html_source: str, out_pdf: Path) -> CompileResult:
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="jobwrapper-html-") as tmp:
        html_file = Path(tmp) / "resume.html"
        html_file.write_text(html_source, encoding="utf-8")
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(html_file.as_uri(), wait_until="load")
                out_pdf.parent.mkdir(parents=True, exist_ok=True)
                page.pdf(path=str(out_pdf), format="Letter", print_background=True,
                         margin={"top": "14mm", "bottom": "14mm", "left": "13mm", "right": "13mm"})
                browser.close()
        except Exception as exc:
            return CompileResult(ok=False, error=f"chromium print failed: {exc}")
    return CompileResult(pdf_path=out_pdf, engine="html", pages=count_pages(out_pdf), ok=True)


def compile_html(html_source: str, out_pdf: Path) -> CompileResult:
    """Print HTML to PDF with the bundled Chromium. Always available once Playwright is set up.

    Runs in a worker thread on purpose: resumes are compiled while the apply loop already holds
    a sync Playwright session, and the sync API refuses to start inside a thread that already
    has a running event loop.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        return CompileResult(ok=False, error="playwright is not installed")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_print_html, html_source, out_pdf).result()


def compile_resume(*, tex_source: str | None, html_source: str | None, out_pdf: Path,
                   config: ResumeConfig | None = None) -> CompileResult:
    """Try LaTeX, then HTML. Returns whichever produced a PDF."""
    config = config or ResumeConfig()
    if tex_source and config.engine != "html":
        result = compile_latex(tex_source, out_pdf, config)
        if result.ok:
            return result
        log.info("LaTeX unavailable (%s) - falling back to the HTML renderer", result.error)
    if html_source:
        return compile_html(html_source, out_pdf)
    return CompileResult(ok=False, error="nothing to compile")
