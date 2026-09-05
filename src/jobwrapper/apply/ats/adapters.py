"""Vendor adapters. Each one encodes only what the generic path cannot handle."""

from __future__ import annotations

from ...logging_setup import get
from ..browser import BrowserSession
from .base import ATSAdapter, StepResult

log = get("apply.ats")


class GreenhouseAdapter(ATSAdapter):
    name = "greenhouse"

    def before_fill(self, session: BrowserSession) -> None:
        # the form is often embedded; make sure the iframe has loaded before extraction
        try:
            frame = session.page.locator("#grnhse_iframe")
            if frame.count():
                session.page.wait_for_timeout(1500)
        except Exception:
            pass

    def after_fill(self, session: BrowserSession) -> None:
        """The location field is a Places autocomplete: typing alone leaves it empty."""
        for selector in ("#job_application_location", "input[name='job_application[location]']",
                         "input[autocomplete='address-level2']"):
            try:
                locator = session.page.locator(selector).first
                if locator.count() and locator.is_visible():
                    value = locator.input_value()
                    if value:
                        session.fill_autocomplete(selector, value)
                    break
            except Exception:
                continue


class LeverAdapter(ATSAdapter):
    name = "lever"

    def click_apply(self, session: BrowserSession) -> bool:
        url = session.page.url
        if url.endswith("/apply"):
            return True
        if "jobs.lever.co" in url:
            return session.goto(url.rstrip("/") + "/apply")
        return super().click_apply(session)


class AshbyAdapter(ATSAdapter):
    name = "ashby"

    def click_apply(self, session: BrowserSession) -> bool:
        url = session.page.url
        if "/application" in url:
            return True
        if "jobs.ashbyhq.com" in url:
            return session.goto(url.rstrip("/") + "/application")
        return super().click_apply(session)

    def before_fill(self, session: BrowserSession) -> None:
        # React controlled inputs: give hydration a beat before reading the DOM
        session.page.wait_for_timeout(1500)


class WorkableAdapter(ATSAdapter):
    name = "workable"

    def click_apply(self, session: BrowserSession) -> bool:
        url = session.page.url
        if url.rstrip("/").endswith("/apply"):
            return True
        if "apply.workable.com" in url and "/j/" in url:
            return session.goto(url.rstrip("/") + "/apply/")
        return super().click_apply(session)


class SmartRecruitersAdapter(ATSAdapter):
    name = "smartrecruiters"

    def before_fill(self, session: BrowserSession) -> None:
        for text in ("Continue with your own information", "Fill in manually", "Apply manually"):
            try:
                button = session.page.get_by_role("button", name=text, exact=False).first
                if button.count() and button.is_visible():
                    button.click(timeout=3000)
                    session.page.wait_for_timeout(900)
                    return
            except Exception:
                continue


class WorkdayAdapter(ATSAdapter):
    """The wizard. Requires an account, so this is where sign-in-else-sign-up lives."""

    name = "workday"
    requires_account = True

    def open_application(self, session: BrowserSession, apply_url: str) -> bool:
        if not session.goto(apply_url):
            return False
        session.dismiss_cookie_banner()
        for text in ("Apply", "Apply Now", "Autofill with Resume", "Apply Manually"):
            try:
                button = session.page.get_by_role("button", name=text, exact=False).first
                if button.count() and button.is_visible():
                    # prefer manual: resume autofill produces fields we then have to correct
                    if text == "Autofill with Resume":
                        continue
                    button.click(timeout=5000)
                    session.page.wait_for_timeout(2000)
                    break
            except Exception:
                continue
        return True

    def sign_in(self, session: BrowserSession, username: str, password: str) -> bool:
        try:
            email = session.page.locator("[data-automation-id='email'], input[type='email']").first
            pw = session.page.locator("[data-automation-id='password'], input[type='password']").first
            if not (email.count() and pw.count()):
                return False
            email.fill(username)
            pw.fill(password)
            button = session.page.locator(
                "[data-automation-id='signInSubmitButton'], button[type='submit']").first
            button.click(timeout=8000)
            session.page.wait_for_timeout(3500)
            return "signin" not in session.page.url.lower()
        except Exception as exc:
            log.debug("workday sign-in failed: %s", exc)
            return False

    def sign_up(self, session: BrowserSession, username: str, password: str) -> bool:
        """Fills the registration form and stops at the button unless auto_signup is on."""
        try:
            link = session.page.get_by_text("Create Account", exact=False).first
            if link.count() and link.is_visible():
                link.click(timeout=5000)
                session.page.wait_for_timeout(1800)
            fields = {
                "[data-automation-id='email']": username,
                "[data-automation-id='password']": password,
                "[data-automation-id='verifyPassword']": password,
            }
            filled = 0
            for selector, value in fields.items():
                locator = session.page.locator(selector).first
                if locator.count():
                    locator.fill(value)
                    filled += 1
            checkbox = session.page.locator("[data-automation-id='createAccountCheckbox']").first
            if checkbox.count():
                checkbox.check(timeout=4000)
            return filled >= 2
        except Exception as exc:
            log.debug("workday sign-up prefill failed: %s", exc)
            return False

    def current_step(self, session: BrowserSession) -> StepResult:
        fields = session.extract_fields()
        text = session.page_text(4000).lower()
        has_next = bool(self._find_first(session, self.spec.get("next", [])))
        is_final = "review" in text[:1500] and "submit" in text
        return StepResult(fields=fields, has_next=has_next and not is_final, is_final=is_final)


class ICIMSAdapter(ATSAdapter):
    name = "icims"

    def before_fill(self, session: BrowserSession) -> None:
        session.page.wait_for_timeout(1500)  # iframe-heavy


class TaleoAdapter(ATSAdapter):
    name = "taleo"
    assisted_only = True


class GenericAdapter(ATSAdapter):
    name = "generic"

    @classmethod
    def detect(cls, url: str, html: str, catalog) -> bool:
        return True


ADAPTERS: list[type[ATSAdapter]] = [
    GreenhouseAdapter, LeverAdapter, AshbyAdapter, WorkableAdapter, SmartRecruitersAdapter,
    WorkdayAdapter, ICIMSAdapter, TaleoAdapter, GenericAdapter,
]
