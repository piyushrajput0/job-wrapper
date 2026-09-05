"""ATS lint: the mechanical rules that decide whether a resume parses cleanly."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models.resume import MasterResume
from .keywords import Keyword, keyword_coverage


@dataclass
class ATSReport:
    score: int = 0
    notes: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    coverage: float = 0.0


WEAK_OPENERS = {"responsible", "worked", "helped", "assisted", "participated", "involved",
                "tasked", "duties"}
STRONG_VERBS = {"built", "designed", "led", "shipped", "reduced", "increased", "migrated",
                "automated", "scaled", "launched", "architected", "owned", "delivered",
                "improved", "cut", "drove", "implemented", "rewrote", "optimized", "optimised"}


def ats_lint(resume: MasterResume, keywords: list[Keyword] | None = None,
             rendered_text: str | None = None) -> ATSReport:
    report = ATSReport()
    text = rendered_text or resume.text_corpus()
    score = 100.0

    # contact block
    if not resume.email:
        report.notes.append("no email address - most parsers will reject the file outright")
        score -= 15
    else:
        report.passed.append("email present")
    if not resume.phone:
        report.notes.append("no phone number")
        score -= 5
    if not resume.location:
        report.notes.append("no location - recruiters filter on this")
        score -= 4

    # structure
    if not resume.experience:
        report.notes.append("no experience section")
        score -= 25
    if not resume.education:
        report.notes.append("no education section")
        score -= 5
    if not resume.skill_groups:
        report.notes.append("no skills section - this is where keyword matching happens")
        score -= 10
    else:
        report.passed.append(f"{sum(len(v) for v in resume.skill_groups.values())} skills listed")

    # bullets
    bullets = [b.text for exp in resume.experience for b in exp.bullets]
    bullets += [b.text for proj in resume.projects for b in proj.bullets]
    if bullets:
        weak = [b for b in bullets if b.split() and b.split()[0].lower().strip(",.") in WEAK_OPENERS]
        if weak:
            report.notes.append(f"{len(weak)} bullet(s) open with a weak verb "
                                f"(e.g. \"{weak[0][:60]}\")")
            score -= min(10, len(weak) * 2)
        strong = [b for b in bullets if b.split() and b.split()[0].lower().strip(",.") in STRONG_VERBS]
        if strong:
            report.passed.append(f"{len(strong)}/{len(bullets)} bullets open with a strong verb")
        quantified = [b for b in bullets if re.search(r"\d+\s*(%|x\b|k\b|m\b|million|ms\b|s\b|/)", b.lower())]
        ratio = len(quantified) / len(bullets)
        if ratio < 0.3:
            report.notes.append(
                f"only {int(ratio * 100)}% of bullets contain a number - aim for 40%+")
            score -= 8
        else:
            report.passed.append(f"{int(ratio * 100)}% of bullets are quantified")
        long_bullets = [b for b in bullets if len(b) > 220]
        if long_bullets:
            report.notes.append(f"{len(long_bullets)} bullet(s) exceed 220 characters")
            score -= min(6, len(long_bullets) * 2)
    else:
        report.notes.append("no bullets at all")
        score -= 20

    # dates
    undated = [e for e in resume.experience if not e.start_date]
    if undated:
        report.notes.append(f"{len(undated)} experience entry/entries missing a start date")
        score -= min(8, len(undated) * 4)

    # keyword coverage
    if keywords:
        coverage = keyword_coverage(keywords, text)
        report.coverage = coverage
        if coverage < 0.4:
            report.notes.append(f"keyword coverage {int(coverage * 100)}% - below the 40% floor")
            score -= 12
        elif coverage < 0.6:
            report.notes.append(f"keyword coverage {int(coverage * 100)}% - could be higher")
            score -= 5
        else:
            report.passed.append(f"keyword coverage {int(coverage * 100)}%")

    # parser hostility
    if re.search(r"[─-╿▀-▟]", text):
        report.notes.append("box-drawing characters found - many parsers mangle these")
        score -= 5

    report.score = max(0, min(100, int(round(score))))
    return report
