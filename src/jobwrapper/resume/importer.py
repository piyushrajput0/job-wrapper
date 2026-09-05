"""Getting the user's existing resume into `master_resume.json`.

Accepts:
  * .json  - already structured (round-trip)
  * .tex   - the Overleaf case: a deterministic LaTeX parser, with an optional model pass that
             does a far better job on unusual templates
  * .md / .txt - plain text with conventional headings
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..llm import LLMClient, LLMUnavailable
from ..logging_setup import get
from ..models.resume import (
    MasterResume,
    ResumeBullet,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    ResumeSection,
)

log = get("resume.import")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
URL_RE = re.compile(r"https?://[^\s{}\\,)]+")
DATE_RANGE_RE = re.compile(
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|\d{4}-\d{2}|\d{4})"
    r"\s*(?:-|--|–|—|to)\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|Present|Current|\d{4}-\d{2}|\d{4})",
    re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

SECTION_ALIASES = {
    "experience": ["experience", "work experience", "professional experience", "employment",
                   "work history", "career"],
    "education": ["education", "academics", "academic background"],
    "projects": ["projects", "personal projects", "selected projects", "side projects"],
    "skills": ["skills", "technical skills", "technologies", "core competencies", "expertise"],
    "summary": ["summary", "profile", "objective", "about", "professional summary"],
    "certifications": ["certifications", "certificates", "licenses"],
}


def normalize_month_year(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if re.fullmatch(r"\d{4}-\d{1,2}", value):
        year, month = value.split("-")
        return f"{year}-{int(month):02d}"
    if re.fullmatch(r"\d{4}", value):
        return f"{value}-01"
    if value.lower() in {"present", "current", "now"}:
        return ""
    match = re.match(r"([A-Za-z]{3})[a-z]*\.?\s*(\d{4})", value)
    if match:
        month = MONTHS.get(match.group(1).lower(), 1)
        return f"{match.group(2)}-{month:02d}"
    return value


def strip_latex(text: str) -> str:
    """Reduce LaTeX to readable text without needing a TeX parser."""
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^}]*\}(\[[^\]]*\])?", " ", text)
    text = re.sub(r"\\href\{([^}]*)\}\{([^}]*)\}", r"\2 (\1)", text)
    text = re.sub(r"\\url\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\(textbf|textit|emph|underline|texttt|mbox|small|large|Large|LARGE|huge|Huge)"
                  r"\{([^{}]*)\}", r"\2", text)
    text = re.sub(r"\\\\\*?(\[[^\]]*\])?", "\n", text)          # LaTeX line breaks
    text = re.sub(r"\\([%$&#_{}])", r"\1", text)                # unescape \% \$ \& ...
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", text)
    text = text.replace("{", " ").replace("}", " ").replace("~", " ")
    text = text.replace("$\\cdot$", "·").replace("$\\bullet$", "·").replace("--", "-")
    return re.sub(r"[ \t]+", " ", text).strip()


def _split_skill_line(line: str) -> tuple[str, list[str]] | None:
    if ":" not in line:
        return None
    group, _, rest = line.partition(":")
    group = strip_latex(group).strip(" -•\t")
    trim = lambda value: re.sub(r"^[\s.;\\]+|[\s.;\\]+$", "", value)  # noqa: E731
    items = [t for t in (trim(s) for s in re.split(r"[,;|]", strip_latex(rest))) if t]
    if not group or len(group) > 40 or not items:
        return None
    return group, items


def parse_latex(source: str) -> MasterResume:
    resume = MasterResume(latex_source=source)
    preamble, _, body = source.partition(r"\begin{document}")
    resume.latex_preamble = preamble

    email = EMAIL_RE.search(source)
    if email:
        resume.email = email.group(0)
    for url in URL_RE.findall(source):
        low = url.lower()
        for key in ("linkedin", "github", "twitter", "medium", "kaggle", "orcid"):
            if key in low:
                resume.links.setdefault(key, url)
                break
        else:
            resume.links.setdefault("website", url)
    phone = PHONE_RE.search(strip_latex(body[:1500]))
    if phone:
        resume.phone = phone.group(0).strip()

    # name: the first \Huge/\LARGE/\name{} chunk, else the first non-empty text line
    name_match = re.search(
        r"\\(?:name|Huge|LARGE|huge|scshape)\s*\{?\s*([A-Z][^}\\\n]{2,58})", body)
    if name_match:
        resume.name = strip_latex(name_match.group(1)).strip()
    if not resume.name:
        for line in strip_latex(body[:800]).splitlines():
            candidate = line.strip()
            if 4 < len(candidate) < 50 and not EMAIL_RE.search(candidate) and " " in candidate:
                resume.name = candidate
                break

    # sections
    section_pattern = re.compile(
        r"\\(?:section|subsection|cvsection|resumeSection|heading)\*?\{([^}]*)\}", re.I)
    matches = list(section_pattern.finditer(body))
    for index, match in enumerate(matches):
        title = strip_latex(match.group(1)).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[start:end]
        kind = next((key for key, names in SECTION_ALIASES.items()
                     if any(title.startswith(n) or n in title for n in names)), None)

        if kind == "summary":
            resume.summary = " ".join(strip_latex(chunk).split())[:800]
        elif kind == "skills":
            for line in strip_latex(chunk).splitlines():
                parsed = _split_skill_line(line)
                if parsed:
                    resume.skill_groups[parsed[0]] = parsed[1]
            if not resume.skill_groups:
                items = [s.strip() for s in re.split(r"[,;]", strip_latex(chunk)) if 1 < len(s.strip()) < 40]
                if items:
                    resume.skill_groups["Skills"] = items[:40]
        elif kind == "certifications":
            resume.certifications = [strip_latex(i) for i in re.findall(r"\\item\s*(.+)", chunk)]
        elif kind in {"experience", "projects", "education"}:
            _parse_entries(chunk, kind, resume)
        elif title:
            items = [strip_latex(i) for i in re.findall(r"\\item\s*(.+)", chunk)]
            if items:
                resume.extra_sections.append(
                    ResumeSection(title=match.group(1).strip().title(), items=items))
    return resume


ENTRY_MACRO_RE = re.compile(
    r"\\(resumeSubheading|resumeProjectHeading|resumeSubItem|cventry|cvitem|subheading|"
    r"twocolentry|entry|educationItem|experienceItem)\s*(?=[\{\[])")

TITLE_WORDS = re.compile(
    r"engineer|developer|manager|analyst|scientist|designer|architect|consultant|intern|"
    r"lead|director|specialist|administrator|researcher|founder|associate|president|officer",
    re.I)
DEGREE_WORDS = re.compile(
    r"bachelor|master|b\.?\s?tech|m\.?\s?tech|b\.?\s?e\b|b\.?\s?sc|m\.?\s?sc|b\.?s\.?\b|"
    r"m\.?s\.?\b|ph\.?d|mba|diploma|associate of|degree",
    re.I)
INSTITUTION_WORDS = re.compile(
    r"universit|college|institute|school|academy|polytechnic|iit\b|nit\b|\bbits\b", re.I)
LOCATION_RE = re.compile(r"^[A-Z][A-Za-z .'-]{1,28},\s*(?:[A-Z]{2}|[A-Z][a-z]{2,})$")
TECH_LIST_RE = re.compile(r"^[A-Za-z0-9+#./ -]+(?:,\s*[A-Za-z0-9+#./ -]+){1,}$")


def _brace_args(text: str, start: int) -> tuple[list[str], int]:
    """Read the consecutive balanced {...} (and [...]) groups that follow a macro."""
    args: list[str] = []
    i = start
    while i < len(text):
        while i < len(text) and text[i] in " \t\n":
            i += 1
        if i >= len(text) or text[i] not in "{[":
            break
        opener, closer = ("{", "}") if text[i] == "{" else ("[", "]")
        depth, j = 0, i
        while j < len(text):
            if text[j] == opener:
                depth += 1
            elif text[j] == closer:
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            break
        if opener == "{":
            args.append(text[i + 1:j])
        i = j + 1
    return args, i


def _classify_args(args: list[str]) -> dict[str, str]:
    """Templates order these arguments differently, so classify by content, not position."""
    cleaned = [strip_latex(a).strip(" ,") for a in args]
    cleaned = [c for c in cleaned if c and len(c) < 160]
    out = {"title": "", "company": "", "location": "", "start": "", "end": "", "degree": ""}
    leftovers: list[str] = []
    for value in cleaned:
        dates = DATE_RANGE_RE.search(value)
        if dates and not out["start"]:
            out["start"] = normalize_month_year(dates.group(1))
            out["end"] = normalize_month_year(dates.group(2))
            continue
        if not out["start"] and re.fullmatch(r"[A-Za-z.]*\s*\d{4}", value):
            out["start"] = normalize_month_year(value)
            continue
        if DEGREE_WORDS.search(value) and not out["degree"]:
            out["degree"] = value
            continue
        if INSTITUTION_WORDS.search(value) and not out["company"]:
            out["company"] = value
            continue
        if LOCATION_RE.match(value) and not INSTITUTION_WORDS.search(value) \
                and not out["location"]:
            out["location"] = value
            continue
        if TITLE_WORDS.search(value) and not out["title"]:
            out["title"] = value
            continue
        leftovers.append(value)
    for value in leftovers:
        for slot in ("company", "title", "location"):
            if not out[slot]:
                out[slot] = value
                break
    return out


def _bullets_from(chunk: str) -> list[str]:
    items = [strip_latex(b).strip() for b in re.findall(r"\\item\s*(.+)", chunk)]
    if not items:
        items = [strip_latex(line).strip(" -•*\t")
                 for line in chunk.splitlines() if line.strip().startswith(("-", "•", "*"))]
    return [b for b in items if len(b) > 5]


def _parse_entries(chunk: str, kind: str, resume: MasterResume) -> None:
    """Split a section into entries, preferring macro arguments over line heuristics."""
    matches = list(ENTRY_MACRO_RE.finditer(chunk))
    entries: list[tuple[list[str], str]] = []

    if matches:
        for index, match in enumerate(matches):
            args, after = _brace_args(chunk, match.end())
            body_end = matches[index + 1].start() if index + 1 < len(matches) else len(chunk)
            entries.append((args, chunk[after:body_end]))
    else:
        for block in re.split(r"\n\s*\n", chunk):
            if not strip_latex(block).strip():
                continue
            header = next((line for line in strip_latex(block).splitlines() if line.strip()), "")
            entries.append(([p for p in re.split(r"\||·|\s{3,}", header) if p.strip()], block))

    for args, body in entries:
        info = _classify_args(args)
        bullets = _bullets_from(body)
        if not any(info.values()) and not bullets:
            continue

        if kind == "experience":
            if not (info["title"] or info["company"]):
                continue
            resume.experience.append(ResumeExperience(
                title=info["title"] or info["degree"], company=info["company"],
                location=info["location"], start_date=info["start"], end_date=info["end"],
                bullets=[ResumeBullet(text=b) for b in bullets]))
        elif kind == "projects":
            cleaned = [strip_latex(a).strip(" ,") for a in args if strip_latex(a).strip(" ,")]
            tech_source = next(
                (c for c in cleaned[1:] if TECH_LIST_RE.match(c) and "," in c), "")
            name = cleaned[0] if cleaned else (info["title"] or info["company"])
            if not name:
                continue
            resume.projects.append(ResumeProject(
                name=name[:100],
                technologies=[t.strip() for t in re.split(r"[,/|]", tech_source) if t.strip()],
                description=(bullets[0] if bullets else ""),
                bullets=[ResumeBullet(text=b) for b in bullets[1:]],
                start_date=info["start"], end_date=info["end"]))
        else:
            institution = info["company"] or info["title"]
            degree = info["degree"]
            text = f"{' '.join(args)} {body}"
            gpa = re.search(r"(?:gpa|cgpa)\s*[:\-]?\s*([\d.]+)", text, re.I)
            minor = re.search(r"minor\s*(?:in|:)?\s*([A-Za-z &]+)", text, re.I)
            if not institution and not degree:
                continue
            resume.education.append(ResumeEducation(
                institution=institution[:120], degree=degree[:120],
                field_of_study=_field_of_study(degree),
                minor=(minor.group(1).strip().rstrip(". ")[:60] if minor else ""),
                start_date=info["start"], end_date=info["end"],
                location=info["location"],
                gpa=(gpa.group(1) if gpa else ""),
                details=_useful_education_details(bullets)[:3]))


def _useful_education_details(bullets: list[str]) -> list[str]:
    """Drop lines that only restate the GPA or minor - both get their own rendered slot."""
    kept: list[str] = []
    for bullet in bullets:
        remainder = " ".join(
            sentence for sentence in re.split(r"(?<=[.;])\s+", bullet)
            if not re.search(r"\b(gpa|cgpa|minor)\b", sentence, re.I)).strip()
        if len(remainder) > 8:
            kept.append(bullet if len(remainder) > 0.7 * len(bullet) else remainder)
    return kept


def _field_of_study(degree_line: str) -> str:
    """"Bachelor of Science in Computer Science" -> "Computer Science"."""
    match = re.search(r"\bin\s+([A-Za-z &]+)$", degree_line.strip())
    if not match:
        match = re.search(r"\bof\s+([A-Za-z &]+)$", degree_line.strip())
    return match.group(1).strip()[:80] if match else ""


def parse_plaintext(text: str) -> MasterResume:
    resume = MasterResume()
    email = EMAIL_RE.search(text)
    if email:
        resume.email = email.group(0)
    phone = PHONE_RE.search(text)
    if phone:
        resume.phone = phone.group(0).strip()
    lines = [line.rstrip() for line in text.splitlines()]
    resume.name = next((line.strip() for line in lines[:5] if line.strip()), "")

    current = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if current and buffer:
            chunk = "\n".join(buffer)
            if current == "summary":
                resume.summary = " ".join(chunk.split())[:800]
            elif current == "skills":
                for line in buffer:
                    parsed = _split_skill_line(line)
                    if parsed:
                        resume.skill_groups[parsed[0]] = parsed[1]
            elif current == "certifications":
                resume.certifications = [line.strip("-• ") for line in buffer if line.strip("-• ")]
            else:
                _parse_entries("\n".join(f"\\item {line.strip('-• ')}" if line.strip().startswith(("-", "•", "*"))
                                         else line for line in buffer), current, resume)
        buffer = []

    for line in lines:
        heading = line.strip().lower().strip("#: ")
        kind = next((key for key, names in SECTION_ALIASES.items()
                     if heading in names or any(heading == n for n in names)), None)
        if kind and len(line.strip()) < 60:
            flush()
            current = kind
            continue
        buffer.append(line)
    flush()
    return resume


class _ImportedResume(MasterResume):
    """Same shape - used as the structured-output target for the model-assisted import."""


def import_master_resume(path: Path, llm: LLMClient | None = None,
                         use_llm: bool = True) -> MasterResume:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()

    if suffix == ".json":
        return MasterResume.model_validate(json.loads(raw))

    deterministic = parse_latex(raw) if suffix == ".tex" else parse_plaintext(raw)

    if use_llm and llm and llm.available():
        try:
            parsed = llm.parse(
                _ImportedResume,
                system=("You convert a resume into structured JSON. Copy the content exactly as "
                        "written - do not improve, summarise, or invent anything. Dates use "
                        "YYYY-MM. An empty end_date means the role is current. Preserve every "
                        "bullet verbatim."),
                prompt=f"Resume source ({suffix}):\n\n{raw[:60000]}",
                effort="medium", max_tokens=16000)
            parsed.latex_source = raw if suffix == ".tex" else ""
            parsed.latex_preamble = deterministic.latex_preamble
            # keep whichever pass found more structure
            if len(parsed.experience) >= len(deterministic.experience):
                log.info("imported with model assistance: %d roles, %d projects, %d skill groups",
                         len(parsed.experience), len(parsed.projects), len(parsed.skill_groups))
                return parsed
            log.info("model pass found less structure than the parser; keeping the parser output")
        except LLMUnavailable:
            log.info("no model available - using the deterministic parser")
        except Exception as exc:
            log.warning("model-assisted import failed (%s); using the deterministic parser", exc)

    log.info("imported: %d roles, %d projects, %d education, %d skill groups",
             len(deterministic.experience), len(deterministic.projects),
             len(deterministic.education), len(deterministic.skill_groups))
    return deterministic
