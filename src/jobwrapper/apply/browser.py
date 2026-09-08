"""Playwright driver.

Deliberately boring: a persistent browser profile (so a login survives between runs), a real
viewport, human-ish pacing, and no evasion of bot detection. If a site does not want to be
automated, the correct response is to hand the browser to the human, which is what
`pause_for_human` does.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from ..config import ApplyConfig
from ..logging_setup import get
from ..models.application import FieldDescriptor, FilledField

log = get("apply.browser")

EXTRACT_JS = paths.package_data("extract_fields.js")

COOKIE_BUTTON_TEXTS = [
    "reject all", "decline all", "only necessary", "necessary only", "essential only",
    "reject non-essential", "deny", "decline", "accept necessary",
]
COOKIE_FALLBACK_TEXTS = ["accept all", "accept cookies", "i agree", "got it", "ok"]


@dataclass
class PageContext:
    page: Any
    frame: Any = None

    @property
    def target(self) -> Any:
        return self.frame or self.page


class BrowserSession:
    def __init__(self, config: ApplyConfig, profile_dir: Path | None = None) -> None:
        self.config = config
        self.profile_dir = profile_dir or paths.ensure_layout()["browser"]
        self._pw: Any = None
        self.context: Any = None
        self.page: Any = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context.set_default_timeout(self.config.timeout_ms)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def stop(self) -> None:
        try:
            if self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()

    def __enter__(self) -> BrowserSession:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ------------------------------------------------------------------ navigation
    def goto(self, url: str, wait: str = "domcontentloaded") -> bool:
        try:
            self.page.goto(url, wait_until=wait, timeout=self.config.timeout_ms)
            self.page.wait_for_timeout(900)
            return True
        except Exception as exc:
            log.warning("navigation to %s failed: %s", url, exc)
            return False

    def dismiss_cookie_banner(self) -> bool:
        """Privacy-preserving: reject non-essential where the site offers it."""
        for text in COOKIE_BUTTON_TEXTS:
            try:
                button = self.page.get_by_role("button", name=text, exact=False).first
                if button.count() and button.is_visible():
                    button.click(timeout=2500)
                    self.page.wait_for_timeout(400)
                    log.debug("dismissed cookie banner via '%s'", text)
                    return True
            except Exception:
                continue
        return False

    # ------------------------------------------------------------------ extraction
    def frames(self) -> list[Any]:
        return [self.page, *[f for f in self.page.frames if f != self.page.main_frame]]

    def extract_fields(self) -> list[FieldDescriptor]:
        script = EXTRACT_JS.read_text()
        found: list[FieldDescriptor] = []
        for index, frame in enumerate(self.frames()):
            try:
                raw = frame.evaluate(script)
            except Exception:
                continue
            frame_name = "" if index == 0 else (getattr(frame, "name", "") or f"frame{index}")
            for item in raw or []:
                item["frame"] = frame_name
                try:
                    found.append(FieldDescriptor.model_validate(item))
                except Exception:
                    continue
        # de-duplicate by (frame, selector)
        unique: dict[tuple[str, str], FieldDescriptor] = {}
        for descriptor in found:
            unique.setdefault((descriptor.frame, descriptor.selector), descriptor)
        return list(unique.values())

    def _frame_for(self, descriptor_frame: str) -> Any:
        if not descriptor_frame:
            return self.page
        for index, frame in enumerate(self.frames()):
            name = "" if index == 0 else (getattr(frame, "name", "") or f"frame{index}")
            if name == descriptor_frame:
                return frame
        return self.page

    def _locator(self, descriptor_frame: str, selector: str) -> Any:
        return self._frame_for(descriptor_frame).locator(selector).first

    # ------------------------------------------------------------------ filling
    def apply_field(self, filled: FilledField, frame: str = "") -> tuple[bool, str]:
        frame = frame or filled.frame
        try:
            locator = self._locator(frame, filled.selector)
            if filled.action == "upload":
                path = Path(filled.value)
                if not path.exists():
                    return False, f"file not found: {path}"
                locator.set_input_files(str(path), timeout=self.config.timeout_ms)
                self.page.wait_for_timeout(1200)
                return True, ""

            if filled.action == "check":
                checked = locator.is_checked()
                want = filled.value.strip().lower() in {"yes", "true", "1", "on", "checked"}
                if checked != want:
                    locator.set_checked(want, timeout=8000)
                return True, ""

            if filled.action == "select":
                return self._select(locator, filled, frame)

            locator.scroll_into_view_if_needed(timeout=5000)
            locator.click(timeout=8000)
            locator.fill("")
            locator.type(filled.value, delay=18)
            return True, ""
        except Exception as exc:
            return False, str(exc)[:200]

    def _select(self, locator: Any, filled: FilledField, frame: str = "") -> tuple[bool, str]:
        # native <select>
        try:
            if locator.evaluate("el => el.tagName.toLowerCase()") == "select":
                locator.select_option(label=filled.value, timeout=6000)
                return True, ""
        except Exception:
            pass
        # radio group: click the input whose label matches
        try:
            if "type=\"radio\"" in filled.selector or "type='radio'" in filled.selector:
                group = self._frame_for(frame).locator(filled.selector)
                count = group.count()
                for index in range(count):
                    radio = group.nth(index)
                    label = radio.evaluate(
                        "el => (el.closest('label')?.innerText) || "
                        "(el.id && document.querySelector(`label[for='${el.id}']`)?.innerText) || el.value")
                    if (label or "").strip().lower() == filled.value.strip().lower():
                        radio.check(timeout=6000)
                        return True, ""
                for index in range(count):
                    radio = group.nth(index)
                    label = radio.evaluate(
                        "el => (el.closest('label')?.innerText) || el.value") or ""
                    if filled.value.strip().lower() in label.strip().lower():
                        radio.check(timeout=6000)
                        return True, ""
                return False, f"no radio matched '{filled.value}'"
        except Exception as exc:
            return False, str(exc)[:200]
        # custom listbox: open it, then click the option
        try:
            locator.click(timeout=6000)
            self.page.wait_for_timeout(400)
            option = self.page.get_by_role("option", name=filled.value, exact=False).first
            if option.count():
                option.click(timeout=6000)
                return True, ""
            typed = self.page.locator("input:focus")
            if typed.count():
                typed.type(filled.value, delay=25)
                self.page.wait_for_timeout(700)
                option = self.page.get_by_role("option", name=filled.value, exact=False).first
                if option.count():
                    option.click(timeout=6000)
                    return True, ""
            return False, f"no option matched '{filled.value}'"
        except Exception as exc:
            return False, str(exc)[:200]

    def fill_autocomplete(self, selector: str, value: str) -> bool:
        """Google-Places style inputs need a suggestion click or the value is discarded."""
        try:
            locator = self.page.locator(selector).first
            locator.click(timeout=6000)
            locator.fill("")
            locator.type(value, delay=60)
            self.page.wait_for_timeout(1100)
            for candidate in ("[role=option]", ".pac-item", "li[role='option']", ".select__option"):
                option = self.page.locator(candidate).first
                if option.count() and option.is_visible():
                    option.click(timeout=4000)
                    return True
            self.page.keyboard.press("ArrowDown")
            self.page.keyboard.press("Enter")
            return True
        except Exception as exc:
            log.debug("autocomplete fill failed for %s: %s", selector, exc)
            return False

    # ------------------------------------------------------------------ human handoff
    def needs_human(self) -> str | None:
        """CAPTCHA / MFA / identity checks: detect, never solve."""
        markers = [
            ("iframe[src*='recaptcha']", "reCAPTCHA"),
            ("iframe[src*='hcaptcha']", "hCaptcha"),
            ("iframe[title*='captcha' i]", "captcha"),
            ("#px-captcha", "PerimeterX captcha"),
            ("[data-testid='challenge']", "challenge"),
        ]
        for selector, label in markers:
            try:
                if self.page.locator(selector).first.count():
                    return label
            except Exception:
                continue
        try:
            body = (self.page.inner_text("body") or "").lower()[:6000]
        except Exception:
            return None
        for phrase in ("verify you are human", "i'm not a robot", "verification code",
                       "two-factor", "enter the code we sent", "unusual activity"):
            if phrase in body:
                return phrase
        return None

    def pause_for_human(self, reason: str, timeout_seconds: int = 300) -> bool:
        """Hand the browser over and wait. Returns True if the obstacle cleared."""
        log.warning("HUMAN NEEDED: %s - the browser is yours; the run resumes when it clears",
                    reason)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(3)
            if not self.needs_human():
                log.info("obstacle cleared, resuming")
                return True
        return False

    # ------------------------------------------------------------------ misc
    def screenshot(self, name: str) -> str:
        directory = paths.ensure_layout()["screenshots"]
        path = directory / f"{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as exc:
            log.debug("screenshot failed: %s", exc)
            return ""

    def page_text(self, limit: int = 20000) -> str:
        try:
            return (self.page.inner_text("body") or "")[:limit]
        except Exception:
            return ""

    def html(self, limit: int = 250000) -> str:
        try:
            return self.page.content()[:limit]
        except Exception:
            return ""

    @contextmanager
    def temporary_timeout(self, ms: int) -> Iterator[None]:
        previous = self.config.timeout_ms
        self.context.set_default_timeout(ms)
        try:
            yield
        finally:
            self.context.set_default_timeout(previous)
