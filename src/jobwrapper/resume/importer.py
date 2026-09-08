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
# US, UK, India, EU. The regex is deliberately loose about grouping and the digit count is
# checked afterwards, because "+49 30 12345678" and "(415) 555-0142" have nothing in common
# structurally beyond "a run of digits with separators".
PHONE_RE = re.compile(
    r"(?<![\d/\-])(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{2,5}\)[\s.\-]?)?"
    r"\d{2,5}(?:[\s.\-]?\d{2,5}){1,3}(?![\d/\-])")


HEADER_LOCATION_RE = re.compile(
    r"(?<![A-Za-z])([A-Z][A-Za-z.'-]+(?:[ -][A-Z][A-Za-z.'-]+){0,2},\s*"
    r"(?:[A-Z]{2}\b|[A-Z][a-z]+(?: [A-Z][a-z]+)?))")


def find_location(text: str) -> str:
    """The "San Francisco, CA" in the contact line - a résumé rarely states more than that."""
    for line in text.splitlines()[:8]:
        # skip the whole line, not just the match: "University of California, Berkeley" contains
        # a perfectly location-shaped substring
        if re.search(r"universit|college|institute|school|inc\.|llc|ltd|gmbh", line, re.I):
            continue
        if "@" in line or "http" in line:
            line = re.sub(r"\S+@\S+|https?://\S+", " ", line)
        match = HEADER_LOCATION_RE.search(line)
        if match:
            return match.group(1).strip()
    return ""


def find_phone(text: str) -> str:
    """First candidate with a plausible number of digits (7-15, per E.164)."""
    for match in PHONE_RE.finditer(text):
        candidate = match.group(0).strip()
        digits = sum(c.isdigit() for c in candidate)
        if 7 <= digits <= 15:
            return candidate
    return ""
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


SKILL_GROUP_WORDS = re.compile(
    r"^(languages?|frameworks?|libraries|tools?|technolog\w+|infrastructure|cloud|databases?|"
    r"practices?|skills?|platforms?|methodolog\w+|devops|testing|other)\b[:\s]+(.+)$", re.I)


def _split_skill_line(line: str) -> tuple[str, list[str]] | None:
    if ":" not in line:
        # PDF extraction drops the colon: "Languages Python, Go, SQL"
        match = SKILL_GROUP_WORDS.match(line.strip())
        if match and "," in match.group(2):
            items = [s.strip(" .;") for s in match.group(2).split(",") if s.strip(" .;")]
            return (match.group(1).title(), items) if items else None
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
    resume.phone = find_phone(strip_latex(body[:2000]))
    resume.location = find_location(strip_latex(body[:1200]))

    # name: the first \Huge/\LARGE/\name{} chunk, else the first non-empty text line
    two_part = re.search(r"\\(?:name|author)\s*\{([^{}]{1,40})\}\s*\{([^{}]{0,40})\}", source)
    if two_part:
        resume.name = " ".join(
            strip_latex(part).strip() for part in two_part.groups() if part.strip()).strip()
    if not resume.name:
        name_match = re.search(
            r"\\(?:name|author|Huge|LARGE|huge|scshape)\s*\{?\s*([A-Z][^}\\\n]{2,58})", body)
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
    inherited: str | None = None
    for index, match in enumerate(matches):
        title = strip_latex(match.group(1)).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        chunk = body[start:end]
        kind = next((key for key, names in SECTION_ALIASES.items()
                     if any(title.startswith(n) or n in title for n in names)), None)
        # "\\section{Experience}" followed by "\\subsection{Vocational}" - the subsection has no
        # alias of its own, but its entries still belong to the parent section
        is_subsection = match.group(0).lstrip("\\").startswith("subsection")
        if kind:
            inherited = kind
        elif is_subsection and inherited:
            kind = inherited
        elif not is_subsection:
            inherited = None

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
    r"\\(resumeSubheading|resumeProjectHeading|cventry|cvevent|cvsubsection|subheading|"
    r"twocolentry|entry|educationItem|experienceItem|honor|position)\s*(?=[\{\[])")

TITLE_WORDS = re.compile(
    r"engineer|developer|manager|analyst|scientist|designer|architect|consultant|intern|"
    r"lead|director|specialist|administrator|researcher|founder|associate|president|officer",
    re.I)
DEGREE_WORDS = re.compile(
    r"bachelor|master|doctor(?:ate)?|"
    r"b\.?\s?tech|m\.?\s?tech|b\.?\s?eng|m\.?\s?eng|b\.?\s?e\b|m\.?\s?e\b|"
    r"b\.?\s?sc|m\.?\s?sc|b\.?s\.?\b|m\.?s\.?\b|b\.?a\.?\b|m\.?a\.?\b|"
    r"bba|mba|bca|mca|llb|llm|md\b|ph\.?\s?d|"
    r"diploma|associate of|honours|honors degree|degree",
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


BULLET_MACROS = ("resumeItem", "resumeSubItem", "cvitem", "cvlistitem", "cvline",
                 "achievement", "item")


def _macro_first_args(text: str, macros: tuple[str, ...]) -> list[str]:
    r"""Every `\macro{...}` invocation's first argument, brace-balanced.

    Needed because the popular templates wrap bullets in their own macro rather than \item,
    and those arguments routinely contain nested braces (\textbf{...}, $...$, \href{}{}).
    """
    pattern = re.compile(r"\\(" + "|".join(macros) + r")\s*(?=[\{\[])")
    out: list[str] = []
    for match in pattern.finditer(text):
        args, _end = _brace_args(text, match.end())
        if args:
            out.append(args[0])
    return out


def _bullets_from(chunk: str) -> list[str]:
    items = [strip_latex(b).strip() for b in _macro_first_args(chunk, BULLET_MACROS)]
    if not items:
        items = [strip_latex(b).strip() for b in re.findall(r"\\item\s+([^\n]+)", chunk)]
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
        if not bullets:
            # \cventry{date}{title}{org}{city}{grade}{description} - the prose is an argument,
            # not an \item, so nothing above finds it
            bullets = [text for text in (strip_latex(a).strip() for a in args[4:])
                       if len(text) > 25]
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


CITY_PREFIXES = {"San", "New", "Los", "Las", "Santa", "Saint", "St.", "St", "Fort", "Ft.",
                 "Port", "El", "Rio", "Sao", "São", "Mount", "Mountain", "Lake", "North",
                 "South", "East", "West", "Upper", "Lower", "Greater"}

# two-word places whose first word is not a generic prefix, so the rule above cannot find them
MULTIWORD_CITIES = {
    "palo alto", "menlo park", "ann arbor", "long beach", "redwood city", "culver city",
    "jersey city", "kansas city", "salt lake city", "buenos aires", "hong kong", "tel aviv",
    "kuala lumpur", "ho chi minh", "abu dhabi", "cape town", "milton keynes", "silicon valley",
    "research triangle", "boca raton", "coral gables", "walnut creek",
    "navi mumbai", "gurgaon haryana", "electronic city", "hi tech city", "salt lake",
}

LOCATION_SUFFIX_RE = re.compile(
    r"^[A-Z][A-Za-z.'-]+(?:[ -][A-Z][A-Za-z.'-]+){0,2},\s*"
    r"(?:[A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)$")


def _split_company_location(line: str) -> tuple[str, str]:
    """Split "Northwind Data San Francisco, CA" into company and location.

    PDF extraction collapses whatever whitespace separated the two columns, so the only way back
    is to take the longest trailing run that reads like a place while still leaving a company
    behind - "San Francisco, CA", not "Francisco, CA".
    """
    line = line.strip()
    for separator in ("|", "\u00b7", "  "):
        if separator in line:
            parts = [p.strip() for p in line.split(separator) if p.strip()]
            if len(parts) >= 2:
                return parts[0][:120], parts[-1][:80]

    words = line.split()
    for start in range(len(words) - 1, 0, -1):             # shortest plausible place first
        suffix = " ".join(words[start:])
        if not LOCATION_SUFFIX_RE.match(suffix):
            continue
        # "San Francisco, CA" not "Francisco, CA": absorb the words that begin a place name
        while start > 1 and words[start - 1] in CITY_PREFIXES:
            start -= 1
        if start > 1:
            city = " ".join(words[start - 1:]).split(",")[0].strip().lower()
            if city in MULTIWORD_CITIES:
                start -= 1
        return " ".join(words[:start])[:120], " ".join(words[start:])[:80]
    return line[:120], ""


def _parse_plain_entries(lines: list[str], kind: str, resume: MasterResume) -> None:
    """Parse a plain-text section, as extracted from a PDF or written in Markdown.

    Real résumés put the date range on the same line as the role and the company on the next,
    then list achievements with no bullet marker at all once a PDF has been through a text
    extractor. A date range is the one reliable signal that a new entry has started.
    """
    blocks: list[list[str]] = []
    for line in [ln.rstrip() for ln in lines]:
        if not line.strip():
            continue
        if DATE_RANGE_RE.search(line) or not blocks:
            blocks.append([line])
        else:
            blocks[-1].append(line)

    for block in blocks:
        header = block[0]
        dates = DATE_RANGE_RE.search(header)
        start = normalize_month_year(dates.group(1)) if dates else ""
        end = normalize_month_year(dates.group(2)) if dates else ""
        title_line = DATE_RANGE_RE.sub("", header).strip(" ,|·-\t")

        second = block[1] if len(block) > 1 else ""
        second_is_meta = bool(second) and len(second) < 90 and not second.endswith(".")
        body = block[2:] if second_is_meta else block[1:]
        bullets = [b.strip(" -•*\t") for b in body if len(b.strip()) > 18]

        company, location = (_split_company_location(second) if second_is_meta
                             else ("", ""))

        if kind == "experience":
            if not title_line and not company:
                continue
            resume.experience.append(ResumeExperience(
                title=title_line[:120], company=company[:120], location=location[:80],
                start_date=start, end_date=end,
                bullets=[ResumeBullet(text=b) for b in bullets]))
        elif kind == "projects":
            if not title_line:
                continue
            resume.projects.append(ResumeProject(
                name=title_line[:100], description=(bullets[0] if bullets else ""),
                bullets=[ResumeBullet(text=b) for b in bullets[1:]],
                start_date=start, end_date=end))
        else:
            text = " ".join(block)
            gpa = re.search(r"(?:gpa|cgpa)\s*[:\-]?\s*([\d.]+)", text, re.I)
            minor = re.search(r"minor\s*(?:in|:)?\s*([A-Za-z &]+)", text, re.I)
            institution = title_line if not DEGREE_WORDS.search(title_line) else company
            degree = title_line if DEGREE_WORDS.search(title_line) else (
                company if DEGREE_WORDS.search(company) else "")
            if not institution and not degree:
                continue
            degree = re.split(r"\s*[(\u2022]|\s+GPA\b|\s+Minor\b", degree, maxsplit=1)[0].strip()
            resume.education.append(ResumeEducation(
                institution=(institution or company)[:120], degree=degree[:120],
                field_of_study=_field_of_study(degree), location=location,
                minor=(minor.group(1).strip().rstrip(". ")[:60] if minor else ""),
                start_date=start, end_date=end, gpa=(gpa.group(1) if gpa else ""),
                details=_useful_education_details(bullets)[:3]))


def _fill_skill_gap(resume: MasterResume) -> None:
    """No Skills section? Derive one from the text.

    Plenty of résumés list technologies only inside bullets. Without a skills section the tailor
    has nothing to re-order and the ATS lint marks the résumé down, so synthesise the group from
    what the text demonstrably contains.
    """
    if resume.skill_groups:
        return
    from ..pipeline.match import _taxonomy, extract_skills

    found = extract_skills(resume.text_corpus())
    if not found:
        return
    categories = _taxonomy()["skills"]
    grouped: dict[str, list[str]] = {}
    labels = {"language": "Languages", "frontend": "Frontend", "backend": "Backend",
              "data": "Data", "ml": "Machine Learning", "cloud": "Cloud & Infrastructure",
              "mobile": "Mobile", "tools": "Tools", "practice": "Practices", "soft": "Strengths"}
    for skill in sorted(found):
        category = categories.get(skill, {}).get("category", "tools")
        grouped.setdefault(labels.get(category, "Skills"), []).append(skill)
    resume.skill_groups = {k: v for k, v in grouped.items() if k != "Strengths"}
    log.info("no skills section found - derived %d skill(s) from the résumé text",
             sum(len(v) for v in resume.skill_groups.values()))


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
    resume.phone = find_phone(text[:2000])
    resume.location = find_location(text[:1200])
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
                _parse_plain_entries(buffer, current, resume)
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


INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


def inline_inputs(source: str, base: Path, depth: int = 0, seen: set[str] | None = None) -> str:
    """Splice in \\input{...} / \\include{...} files.

    Overleaf projects are routinely split into sections/experience.tex and friends. Parsing only
    the main file then yields a resume with a name and nothing else - which is exactly what
    Awesome-CV's template does.
    """
    if depth > 4:
        return source
    seen = seen if seen is not None else set()

    def replace(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        for candidate in (base / target, base / f"{target}.tex"):
            resolved = candidate.resolve()
            if resolved.is_file() and str(resolved) not in seen:
                seen.add(str(resolved))
                try:
                    nested = resolved.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return ""
                return inline_inputs(nested, resolved.parent, depth + 1, seen)
        return ""

    return INPUT_RE.sub(replace, source)


def pdf_to_text(path: Path) -> str:
    """Most people have a PDF and no .tex. Extract the text so they can still import it."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:                                    # pragma: no cover
        raise RuntimeError("reading a PDF résumé needs pypdf: uv add pypdf") from exc

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        # PDF extraction often loses the bullet glyph but keeps the indent
        pages.append(re.sub(r"\n(?=[A-Z][a-z]+ed\b|\u2022)", "\n- ", text))
    return "\n".join(pages)


def import_master_resume(path: Path, llm: LLMClient | None = None,
                         use_llm: bool = True) -> MasterResume:
    suffix = path.suffix.lower()
    raw = (pdf_to_text(path) if suffix == ".pdf"
           else path.read_text(encoding="utf-8", errors="replace"))
    if suffix == ".tex":
        expanded = inline_inputs(raw, path.parent)
        if len(expanded) > len(raw):
            log.info("inlined %d bytes from \\input/\\include files",
                     len(expanded) - len(raw))
        raw = expanded

    if suffix == ".json":
        return MasterResume.model_validate(json.loads(raw))

    deterministic = parse_latex(raw) if suffix == ".tex" else parse_plaintext(raw)
    _fill_skill_gap(deterministic)

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
