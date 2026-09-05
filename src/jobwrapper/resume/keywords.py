"""What does this job description actually want?

Two passes:
  1. Deterministic - the curated taxonomy plus phrase mining. Free, instant, no API key.
  2. LLM (optional) - catches the domain vocabulary a taxonomy can never enumerate
     ("claims adjudication", "multi-tenant billing", "FedRAMP").
Both produce the same Keyword shape, and every keyword is tagged with whether the master resume
can actually support it. That tag is what the truthfulness firewall runs on.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import BaseModel, Field

from ..llm import LLMClient, LLMUnavailable
from ..llm.prompts import KEYWORD_SYSTEM
from ..logging_setup import get
from ..models import Job
from ..models.resume import MasterResume
from ..pipeline.match import _taxonomy, canonical_skill, extract_skills

log = get("resume.keywords")


@dataclass
class Keyword:
    term: str
    importance: float = 0.5
    canonical: str = ""
    in_master: bool = False
    kind: str = "skill"  # skill | phrase | responsibility
    evidence: str = ""

    def key(self) -> str:
        return (self.canonical or self.term).lower()


class _LLMKeyword(BaseModel):
    term: str
    importance: float = Field(ge=0, le=1)
    kind: str = "skill"


class _LLMKeywords(BaseModel):
    keywords: list[_LLMKeyword] = Field(default_factory=list)
    role_summary: str = ""
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _stopwords() -> set[str]:
    return set(_taxonomy()["stopwords"])


_PHRASE_RE = re.compile(r"\b([A-Z][a-zA-Z0-9+#.]{2,}(?:\s+[A-Za-z0-9+#.]{2,}){0,2})\b")


def _mine_phrases(text: str, limit: int = 25) -> Counter[str]:
    """Capitalised multi-word nouns are usually the domain vocabulary a taxonomy misses."""
    counts: Counter[str] = Counter()
    for match in _PHRASE_RE.finditer(text):
        phrase = match.group(1).strip()
        words = phrase.lower().split()
        if any(w in _stopwords() for w in words) or len(phrase) < 4:
            continue
        if phrase.isupper() and len(phrase) <= 3:
            continue
        counts[phrase] += 1
    return Counter(dict(counts.most_common(limit)))


def _master_supports(term: str, master_corpus: str, master_skills: set[str]) -> bool:
    lowered = term.lower()
    if lowered in master_skills:
        return True
    canonical = canonical_skill(term)
    if canonical and canonical.lower() in master_skills:
        return True
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(lowered)}(?![a-z0-9])", master_corpus))


def extract_keywords(job: Job, master: MasterResume, llm: LLMClient | None = None,
                     *, use_llm: bool = True, limit: int = 40) -> list[Keyword]:
    text = f"{job.title}\n{job.description}"
    lowered = text.lower()
    head = lowered[: max(600, len(lowered) // 3)]
    master_corpus = master.text_corpus().lower()
    master_skills = {s.lower() for s in master.all_skills()}

    found: dict[str, Keyword] = {}

    # pass 1a - taxonomy skills
    for canonical in extract_skills(text):
        occurrences = len(re.findall(
            rf"(?<![a-z0-9]){re.escape(canonical.lower())}(?![a-z0-9])", lowered)) or 1
        importance = min(1.0, 0.45 + 0.12 * occurrences)
        if canonical.lower() in head:
            importance = min(1.0, importance + 0.2)
        if canonical.lower() in job.title.lower():
            importance = 1.0
        found[canonical.lower()] = Keyword(
            term=canonical, canonical=canonical, importance=round(importance, 2),
            in_master=_master_supports(canonical, master_corpus, master_skills), kind="skill")

    # pass 1b - phrase mining
    for phrase, count in _mine_phrases(job.description).items():
        key = phrase.lower()
        if key in found or canonical_skill(phrase):
            continue
        importance = min(0.85, 0.3 + 0.1 * count + (0.2 if key in head else 0))
        found[key] = Keyword(term=phrase, importance=round(importance, 2),
                             in_master=_master_supports(phrase, master_corpus, master_skills),
                             kind="phrase")

    # pass 2 - LLM enrichment
    if use_llm and llm and llm.available():
        try:
            result = llm.parse(
                _LLMKeywords,
                system=KEYWORD_SYSTEM,
                prompt=(f"Job title: {job.title}\nCompany: {job.company}\n"
                        f"Location: {job.location}\n\nJob description:\n{job.description[:14000]}"),
                effort="low", max_tokens=3000)
            for item in result.keywords:
                key = item.term.lower().strip()
                if not key:
                    continue
                canonical = canonical_skill(item.term) or ""
                existing = found.get(canonical.lower() or key)
                if existing:
                    existing.importance = max(existing.importance, item.importance)
                else:
                    found[canonical.lower() or key] = Keyword(
                        term=canonical or item.term, importance=item.importance,
                        canonical=canonical, kind=item.kind,
                        in_master=_master_supports(item.term, master_corpus, master_skills))
            for must in result.must_haves:
                key = (canonical_skill(must) or must).lower()
                if key in found:
                    found[key].importance = 1.0
        except LLMUnavailable:
            log.debug("keyword LLM pass unavailable, using deterministic extraction only")
        except Exception as exc:
            log.warning("keyword LLM pass failed (%s); continuing deterministically", exc)

    ordered = sorted(found.values(), key=lambda k: (-k.importance, k.term.lower()))
    return ordered[:limit]


def keyword_coverage(keywords: list[Keyword], text: str) -> float:
    """Share of importance-weighted keywords that appear in the given resume text."""
    if not keywords:
        return 1.0
    lowered = text.lower()
    total = sum(k.importance for k in keywords)
    hit = sum(k.importance for k in keywords
              if re.search(rf"(?<![a-z0-9]){re.escape(k.term.lower())}(?![a-z0-9])", lowered))
    return round(hit / total, 3) if total else 1.0


@dataclass
class GapAnalysis:
    supported: list[Keyword] = field(default_factory=list)
    unsupported: list[Keyword] = field(default_factory=list)

    @property
    def support_rate(self) -> float:
        total = len(self.supported) + len(self.unsupported)
        return round(len(self.supported) / total, 3) if total else 1.0


def analyse_gaps(keywords: list[Keyword]) -> GapAnalysis:
    return GapAnalysis(
        supported=[k for k in keywords if k.in_master],
        unsupported=[k for k in keywords if not k.in_master],
    )
