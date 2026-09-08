"""ATS adapter contract.

The base class is fully functional on its own - it is the generic adapter, driven entirely by
`ats_maps.json` plus the label resolver. Subclasses only encode what is genuinely
vendor-specific: an iframe, a React input, a wizard, an account requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...autofill import Catalog
from ...logging_setup import get
from ...models.application import FieldDescriptor
from ..browser import BrowserSession

log = get("apply.ats")


@dataclass
class StepResult:
    fields: list[FieldDescriptor] = field(default_factory=list)
    has_next: bool = False
    is_final: bool = False
    note: str = ""


class ATSAdapter:
    name = "generic"
    requires_account = False
    assisted_only = False

    def __init__(self, catalog: Catalog | None = None) -> None:
        self.catalog = catalog or Catalog()
        self.spec: dict[str, Any] = self.catalog.ats(self.name)

    # ------------------------------------------------------------------ detection
    @classmethod
    def detect(cls, url: str, html: str, catalog: Catalog) -> bool:
        spec = catalog.ats(cls.name)
        detect = spec.get("detect", {})
        lowered_url = (url or "").lower()
        if any(token.lower() in lowered_url for token in detect.get("url", [])):
            return True
        lowered_html = (html or "").lower()
        return any(token.lower() in lowered_html for token in detect.get("text", []))

    # ------------------------------------------------------------------ flow
    def open_application(self, session: BrowserSession, apply_url: str) -> bool:
        if not session.goto(apply_url):
            return False
        session.dismiss_cookie_banner()
        self.click_apply(session)
        return True

    def click_apply(self, session: BrowserSession) -> bool:
        """Many boards show the JD first with an Apply button above the form."""
        for name in ("Apply for this job", "Apply now", "Apply", "Submit application",
                     "I'm interested", "Apply for this position"):
            try:
                button = session.page.get_by_role("button", name=name, exact=False).first
                if button.count() and button.is_visible():
                    button.click(timeout=4000)
                    session.page.wait_for_timeout(1200)
                    return True
                link = session.page.get_by_role("link", name=name, exact=False).first
                if link.count() and link.is_visible():
                    link.click(timeout=4000)
                    session.page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        return False

    def current_step(self, session: BrowserSession) -> StepResult:
        fields = session.extract_fields()
        has_next = bool(self._find_first(session, self.spec.get("next", [])))
        return StepResult(fields=fields, has_next=has_next, is_final=not has_next)

    def before_fill(self, session: BrowserSession) -> None:
        return None

    def after_fill(self, session: BrowserSession) -> None:
        return None

    def next_step(self, session: BrowserSession) -> bool:
        locator = self._find_first(session, self.spec.get("next", []))
        if not locator:
            return False
        try:
            locator.click(timeout=8000)
            session.page.wait_for_timeout(1800)
            return True
        except Exception as exc:
            log.debug("next-step click failed: %s", exc)
            return False

    def submit(self, session: BrowserSession) -> bool:
        locator = self._find_first(session, self.spec.get("submit", []))
        if not locator:
            log.warning("no submit control found for %s", self.name)
            return False
        try:
            locator.scroll_into_view_if_needed(timeout=4000)
            locator.click(timeout=10000)
            session.page.wait_for_timeout(4000)
            return True
        except Exception as exc:
            log.warning("submit click failed: %s", exc)
            return False

    def result(self, session: BrowserSession) -> str:
        text = session.page_text().lower()
        for phrase in self.spec.get("duplicate_text", []):
            if phrase in text:
                return "duplicate"
        for phrase in self.spec.get("success_text", []):
            if phrase in text:
                return "submitted"
        generic = self.catalog.ats("generic")
        for phrase in generic.get("success_text", []):
            if phrase in text:
                return "submitted"
        if "error" in text or "required" in text:
            return "error"
        return "unknown"

    def validation_errors(self, session: BrowserSession) -> list[str]:
        selectors = ["[aria-invalid='true']", ".error", ".field-error", "[role='alert']",
                     "[class*='errorMessage']", "[data-automation-id='errorMessage']"]
        found: list[str] = []
        for selector in selectors:
            try:
                locator = session.page.locator(selector)
                for index in range(min(locator.count(), 8)):
                    text = (locator.nth(index).inner_text() or "").strip()
                    if text and len(text) < 200:
                        found.append(text)
            except Exception:
                continue
        return list(dict.fromkeys(found))[:10]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _find_first(session: BrowserSession, selectors: list[str]) -> Any:
        for selector in selectors:
            try:
                locator = session.page.locator(selector).first
                if locator.count() and locator.is_visible():
                    return locator
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------ accounts
    def sign_in(self, session: BrowserSession, username: str, password: str) -> bool:
        return False

    def sign_up(self, session: BrowserSession, username: str, password: str) -> bool:
        return False
