"""Rendering a structured resume into LaTeX or HTML.

Jinja2 is configured with LaTeX-safe delimiters ((* *)) / ((( ))) so a template can contain
braces and backslashes without fighting the templating language.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ..models import Profile
from ..models.resume import MasterResume

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def latex_escape(value: object) -> str:
    text = "" if value is None else str(value)
    out = []
    for char in text:
        out.append(_LATEX_ESCAPES.get(char, char))
    escaped = "".join(out)
    # keep en-dashes readable and collapse the whitespace LaTeX would collapse anyway
    escaped = escaped.replace("–", "--").replace("—", "---")
    return re.sub(r"[ \t]+", " ", escaped).strip()


def _date_range(start: str, end: str) -> str:
    def pretty(value: str) -> str:
        if not value:
            return ""
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        match = re.match(r"(\d{4})-(\d{1,2})", value)
        if match:
            year, month = match.groups()
            index = max(1, min(12, int(month)))
            return f"{months[index - 1]} {year}"
        return value

    left, right = pretty(start), pretty(end) or "Present"
    return f"{left} \u2013 {right}" if left else right


def latex_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        block_start_string="((*", block_end_string="*))",
        variable_start_string="(((", variable_end_string=")))",
        comment_start_string="((#", comment_end_string="#))",
        trim_blocks=True, lstrip_blocks=True, autoescape=False, undefined=StrictUndefined,
    )
    env.filters["tex"] = latex_escape
    env.filters["daterange"] = _date_range
    return env


def html_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True, lstrip_blocks=True,
        autoescape=select_autoescape(["html"]), undefined=StrictUndefined,
    )
    env.filters["daterange"] = _date_range
    return env


def _context(resume: MasterResume, profile: Profile | None) -> dict:
    links = dict(resume.links)
    if profile:
        for key, value in profile.links.as_map().items():
            links.setdefault(key, value)
    return {
        "r": resume,
        "name": resume.name or (profile.identity.display_name if profile else ""),
        "email": resume.email or (profile.contact.email if profile else ""),
        "phone": resume.phone or (profile.contact.phone if profile else ""),
        "location": resume.location or (profile.address.city_state_country if profile else ""),
        "links": {k: v for k, v in links.items() if v},
    }


def render_latex(resume: MasterResume, profile: Profile | None = None,
                 template: str = "resume.tex.j2") -> str:
    return latex_env().get_template(template).render(**_context(resume, profile))


def render_html(resume: MasterResume, profile: Profile | None = None,
                template: str = "resume.html.j2") -> str:
    return html_env().get_template(template).render(**_context(resume, profile))
