"""Turning sixteen upstream shapes into one. All pure functions - trivially testable."""

from __future__ import annotations

import html as html_mod
import json
import re
from datetime import UTC, datetime
from functools import lru_cache

from .. import paths
from ..models.job import SalaryRange


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    return json.loads(paths.package_data("skill_taxonomy.json").read_text())


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_BR_RE = re.compile(r"<(br|/p|/div|/li|/h[1-6])\s*/?>", re.I)
_LI_RE = re.compile(r"<li[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]+>")


def html_to_text(html: str) -> str:
    """Deliberately dependency-light: JDs are messy and BeautifulSoup is overkill per-posting.

    Runs twice, because several boards (Greenhouse among them) return HTML that is itself
    HTML-escaped - one pass leaves you with visible <h2> tags in the "plain text".
    """
    if not html:
        return ""
    text = html
    for _ in range(2):
        text = _TAG_RE.sub(" ", text)
        text = _LI_RE.sub("\n- ", text)
        text = _BR_RE.sub("\n", text)
        text = _ANY_TAG.sub(" ", text)
        text = html_mod.unescape(text)
        if "<" not in text:
            break
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


_SALARY_RE = re.compile(
    r"(?P<cur>[$£€₹]|USD|GBP|EUR|INR|CAD)?\s?(?P<lo>\d{2,3}(?:[,.]\d{3})+|\d{2,3}(?:\.\d)?[kK]?)"
    r"\s*(?:-|–|—|to)\s*"
    r"(?P<cur2>[$£€₹]|USD|GBP|EUR|INR|CAD)?\s?(?P<hi>\d{2,3}(?:[,.]\d{3})+|\d{2,3}(?:\.\d)?[kK]?)",
)
_SINGLE_SALARY_RE = re.compile(
    r"(?P<cur>[$£€₹])\s?(?P<val>\d{2,3}(?:[,.]\d{3})+|\d{2,3}[kK])(?!\s*(?:-|–|to))")

_CUR_MAP = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR", "USD": "USD", "GBP": "GBP",
            "EUR": "EUR", "INR": "INR", "CAD": "CAD"}

# "12-18 LPA", "₹12,00,000", "1.2 crore" - Indian postings quote pay in lakhs per annum, and
# group digits 2-2-3 rather than 3-3-3. Read as plain numbers these are wrong by 100x.
_LPA_RE = re.compile(
    r"(?:₹|INR|Rs\.?)?\s*(\d{1,3}(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d{1,3}(?:\.\d+)?)\s*"
    r"(lpa|lakhs?\s*(?:per\s*annum|p\.?a\.?)?|cr|crores?)", re.I)
_INDIAN_GROUPED_RE = re.compile(
    r"(?:₹|INR|Rs\.?)\s*(\d{1,2}(?:,\d{2})+,\d{3})\s*(?:-|–|—|to)\s*"
    r"(?:₹|INR|Rs\.?)?\s*(\d{1,2}(?:,\d{2})+,\d{3})")


def _to_int(token: str) -> int | None:
    token = token.strip().replace(",", "")
    try:
        if token.lower().endswith("k"):
            return int(float(token[:-1]) * 1000)
        if "." in token and len(token.split(".")[-1]) == 3:  # european thousands separator
            return int(token.replace(".", ""))
        return int(float(token))
    except ValueError:
        return None


def parse_salary(text: str, *, default_currency: str = "USD") -> SalaryRange:
    if not text:
        return SalaryRange()
    window = text[:4000]
    period = "annual"
    lowered = window.lower()
    if re.search(r"\bper hour\b|/\s?hour|\bhourly\b|\bph\b", lowered):
        period = "hourly"
    elif re.search(r"\bper month\b|/\s?month|\bmonthly\b|\bpm\b", lowered):
        period = "monthly"

    indian = _LPA_RE.search(window)
    if indian:
        unit = indian.group(3).lower()
        multiplier = 10_000_000 if unit.startswith(("cr",)) else 100_000
        low = int(float(indian.group(1)) * multiplier)
        high = int(float(indian.group(2)) * multiplier)
        return SalaryRange(min=low, max=high, currency="INR", period=period)

    grouped = _INDIAN_GROUPED_RE.search(window)
    if grouped:
        low = int(grouped.group(1).replace(",", ""))
        high = int(grouped.group(2).replace(",", ""))
        return SalaryRange(min=low, max=high, currency="INR", period=period)

    match = _SALARY_RE.search(window)
    if match:
        lo, hi = _to_int(match.group("lo")), _to_int(match.group("hi"))
        cur = _CUR_MAP.get(match.group("cur") or match.group("cur2") or "", default_currency)
        if lo and hi and hi >= lo:
            if period == "annual" and lo < 1000 and hi < 1000:
                lo, hi = lo * 1000, hi * 1000
            if period == "annual" and hi < 1000:
                period = "hourly"
            return SalaryRange(min=lo, max=hi, currency=cur, period=period)

    single = _SINGLE_SALARY_RE.search(window)
    if single:
        value = _to_int(single.group("val"))
        if value:
            return SalaryRange(min=value, max=value,
                               currency=_CUR_MAP.get(single.group("cur"), default_currency),
                               period=period)
    return SalaryRange(currency=default_currency, period=period)


def detect_work_model(text: str, location: str = "") -> str:
    haystack = f"{location} {text[:2500]}".lower()
    models = taxonomy()["work_model"]
    for model in ("hybrid", "remote", "onsite"):
        if any(term in haystack for term in models[model]):
            return model
    return ""


def detect_seniority(title: str, description: str = "") -> str:
    haystack = f" {title.lower()} "
    levels = taxonomy()["seniority"]
    for level in ("intern", "principal", "staff", "manager", "senior", "mid", "entry"):
        for term in levels[level]:
            token = term.strip()
            if not token:
                continue
            if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", haystack):
                return level
    if re.search(r"\b(\d+)\+?\s*years", description.lower()):
        years = int(re.search(r"\b(\d+)\+?\s*years", description.lower()).group(1))
        if years >= 8:
            return "senior"
        if years >= 4:
            return "mid"
        if years <= 1:
            return "entry"
    return ""


def detect_employment_type(text: str) -> str:
    lowered = text.lower()[:2500]
    for kind, terms in taxonomy()["employment_types"].items():
        if any(term in lowered for term in terms):
            return kind
    return "full_time"


def sponsorship_signal(text: str) -> tuple[bool, bool]:
    """Returns (mentions_sponsorship, sponsorship_friendly)."""
    lowered = text.lower()
    tax = taxonomy()
    negative = any(term in lowered for term in tax["sponsorship_negative"])
    positive = any(term in lowered for term in tax["sponsorship_positive"])
    return (negative or positive), (positive and not negative)


def iso_date(value: object) -> str:
    """Accepts epoch seconds/ms, ISO strings, and common date formats. Returns ISO-8601 UTC."""
    if value in (None, "", 0):
        return ""
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if text.isdigit():
        # "2025" is a year; only a long run of digits is an epoch. Reading a year as epoch
        # seconds dated postings to 1970 and made every one of them look 55 years stale.
        if len(text) == 4 and 1900 <= int(text) <= 2100:
            return iso_date(f"{text}-01-01")
        if len(text) >= 9:
            return iso_date(int(text))
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y",
                "%B %Y", "%b %Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(text.replace("Z", "+0000") if fmt.endswith("%z") else text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.isoformat()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.isoformat()
    except ValueError:
        return ""


def extract_requirements(text: str, limit: int = 25) -> list[str]:
    """Pull the bulleted requirement lines out of a JD."""
    lines = [line.strip(" -•*\t") for line in text.splitlines()]
    out: list[str] = []
    capture = False
    for line in lines:
        low = line.lower()
        if re.match(r"^(what you|requirements|qualifications|who you are|you have|we.re looking|"
                    r"basic qualifications|minimum qualifications|about you|skills)", low):
            capture = True
            continue
        if re.match(r"^(benefits|what we offer|perks|about us|equal opportunity|compensation)", low):
            capture = False
        if capture and 12 < len(line) < 300:
            out.append(line)
        if len(out) >= limit:
            break
    if not out:
        out = [line for line in lines if 25 < len(line) < 250][:limit]
    return out
