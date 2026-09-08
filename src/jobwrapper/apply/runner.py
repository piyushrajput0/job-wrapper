"""The apply loop.

Guardrails first, then tailor, then fill, then - only at the highest autonomy level and only
when the plan is complete - submit. Every step is screenshotted and written to the audit trail,
so any application can be reconstructed after the fact.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from .. import paths
from ..autofill import AnswerEngine, Catalog, FieldResolver, ResolveContext
from ..config import Config
from ..llm import LLMClient
from ..logging_setup import get
from ..models import Application, Job, Profile
from ..models.resume import MasterResume, TailoredResume
from ..resume.compile import compile_html, compile_resume
from ..resume.render import render_html, render_latex
from ..resume.tailor import Tailor
from ..store import Store
from ..vault import Vault
from .ats import adapter_for
from .browser import BrowserSession

log = get("apply.runner")

MAX_STEPS = 12


@dataclass
class RunReport:
    attempted: int = 0
    submitted: int = 0
    ready_for_review: int = 0
    needs_input: int = 0
    failed: int = 0
    skipped: int = 0
    applications: list[Application] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"attempted": self.attempted, "submitted": self.submitted,
                "ready_for_review": self.ready_for_review, "needs_input": self.needs_input,
                "failed": self.failed, "skipped": self.skipped}


def artifact_basename(profile: Profile, job: Job, stamp: str) -> str:
    """The filename is the first thing a recruiter sees in their downloads folder, so it leads
    with the candidate's name rather than with the company's."""
    who = _slug(profile.identity.display_name or profile.identity.full_name, 28)
    return f"{who}-{_slug(job.title, 30)}-{_slug(job.company, 20)}-{stamp}".strip("-")


def _cover_letter_html(text: str, profile: Profile, job: Job) -> str:
    """A plain, parser-friendly letter. Same typography as the résumé so they look like a pair."""
    from html import escape

    paragraphs = "".join(f"<p>{escape(p.strip())}</p>"
                         for p in text.split("\n\n") if p.strip())
    contact = " &middot; ".join(escape(x) for x in [
        profile.contact.email, profile.contact.phone, profile.address.city_state_country] if x)
    return f"""<!doctype html><meta charset="utf-8"><title>Cover letter</title>
<style>@page {{ size: letter; margin: 22mm 20mm; }}
body {{ font-family: Charter, Georgia, "Times New Roman", serif; font-size: 11pt;
        line-height: 1.5; color: #16181d; }}
h1 {{ font-size: 15pt; margin: 0 0 2px; }} .c {{ color: #444; font-size: 9.5pt; margin-bottom: 18px; }}
p {{ margin: 0 0 11px; }} .to {{ margin-bottom: 16px; }}</style>
<h1>{escape(profile.identity.display_name)}</h1>
<div class="c">{contact}</div>
<div class="to">{escape(job.company)}<br>Re: {escape(job.title)}</div>
{paragraphs}
<p>Sincerely,<br>{escape(profile.identity.display_name)}</p>"""


def _slug(text: str, limit: int = 40) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in (text or "")).strip("-")
    while "--" in keep:
        keep = keep.replace("--", "-")
    return keep[:limit] or "job"


class ApplicationRunner:
    def __init__(self, config: Config, store: Store, profile: Profile,
                 master: MasterResume, llm: LLMClient | None = None,
                 vault: Vault | None = None) -> None:
        self.config = config
        self.store = store
        self.profile = profile
        self.master = master
        self.llm = llm or LLMClient(config.llm)
        self.vault = vault or Vault()
        self.catalog = Catalog()
        self.tailor = Tailor(config, master, profile, self.llm)
        self.answers = AnswerEngine(profile, self.llm, store.answers, master, self.catalog)

    # ------------------------------------------------------------------ guardrails
    def guardrail_block(self, job: Job) -> str | None:
        apply_config = self.config.apply
        existing = self.store.applications.for_job(job.id)
        if existing and existing.status in {"submitted", "ready_for_review"}:
            return f"already {existing.status}"
        # count attempts, not just submissions: at autonomy `review` nothing is ever submitted,
        # so a submission-only cap meant no cap at all
        attempts = self.store.applications.count_attempts_today()
        if attempts >= apply_config.daily_cap:
            return f"daily cap reached ({attempts}/{apply_config.daily_cap} today)"
        if self.store.applications.count_for_company(job.company) >= apply_config.per_company_cap:
            return f"per-company cap reached for {job.company}"
        if job.match_score < self.config.match.min_score_to_apply:
            return (f"match score {job.match_score} is below the apply floor "
                    f"({self.config.match.min_score_to_apply})")
        host = (urlparse(job.apply_url or job.url).hostname or "").lower()
        if apply_config.block_domains and any(d.lower() in host for d in apply_config.block_domains):
            return f"{host} is in block_domains"
        if apply_config.allow_domains and not any(
                d.lower() in host for d in apply_config.allow_domains):
            return f"{host} is not in allow_domains"
        if not (job.apply_url or job.url):
            return "no application URL"
        return None

    # ------------------------------------------------------------------ documents
    def prepare_documents(self, job: Job) -> tuple[TailoredResume, str, str]:
        """A fresh resume per application, as specified."""
        tailored = self.tailor.tailor(job)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        base = artifact_basename(self.profile, job, stamp)
        directory = paths.ensure_layout()["resumes"]
        pdf_path = directory / f"{base}.pdf"
        tex_path = directory / f"{base}.tex"

        tex_source = render_latex(tailored.resume, self.profile, self.config.resume.template)
        html_source = render_html(tailored.resume, self.profile, self.config.resume.html_template)
        tex_path.write_text(tex_source, encoding="utf-8")

        result = compile_resume(tex_source=tex_source, html_source=html_source,
                                out_pdf=pdf_path, config=self.config.resume)
        if result.ok and result.pages > self.config.resume.max_pages:
            log.info("resume ran to %d pages; trimming to %d", result.pages,
                     self.config.resume.max_pages)
            trimmed = Tailor.trim(tailored.resume, drop=3 * (result.pages - self.config.resume.max_pages))
            tex_source = render_latex(trimmed, self.profile, self.config.resume.template)
            html_source = render_html(trimmed, self.profile, self.config.resume.html_template)
            tex_path.write_text(tex_source, encoding="utf-8")
            result = compile_resume(tex_source=tex_source, html_source=html_source,
                                    out_pdf=pdf_path, config=self.config.resume)

        tailored.tex_path = str(tex_path)
        tailored.pdf_path = str(pdf_path) if result.ok else ""
        tailored.engine_used = result.engine
        self.store.resumes.save(tailored)

        cover_letter_path = ""
        cover_text = ""
        if self.config.apply.generate_cover_letter:
            cover_text = self.answers.cover_letter(job)
            cover_dir = paths.ensure_layout()["cover_letters"]
            Path(cover_dir / f"{base}-cover.txt").write_text(cover_text, encoding="utf-8")
            # upload fields want a document, not a .txt - render the same text to PDF
            cover_pdf = cover_dir / f"{base}-cover.pdf"
            rendered = compile_html(_cover_letter_html(cover_text, self.profile, job), cover_pdf)
            cover_letter_path = str(cover_pdf if rendered.ok else cover_dir / f"{base}-cover.txt")

        if not result.ok:
            log.error("resume compilation failed for %s: %s", job.short(), result.error)
        return tailored, cover_letter_path, cover_text

    # ------------------------------------------------------------------ accounts
    def _vault_password(self, url: str) -> str:
        """Never let a locked or missing vault break a run."""
        try:
            cred = self.vault.get(urlparse(url).hostname or "")
            return cred.password if cred else ""
        except Exception as exc:
            log.debug("vault unavailable: %s", exc)
            return ""

    def ensure_account(self, session: BrowserSession, adapter, job: Job,
                       application: Application) -> bool:
        host = (urlparse(session.page.url).hostname or "").lower()
        cred = self.vault.get(host)
        username = self.profile.contact.email

        if cred and adapter.sign_in(session, cred.username or username, cred.password):
            application.log("signed_in", host=host)
            log.info("signed in to %s", host)
            return True

        if not self.config.apply.auto_signup:
            cred, created = self.vault.get_or_create(host, username)
            prefilled = adapter.sign_up(session, cred.username, cred.password)
            application.status = "needs_input"
            application.log("signup_paused", host=host, prefilled=prefilled)
            log.warning("%s needs an account. The registration form is pre-filled and the "
                        "generated password is in the vault - press submit yourself, or set "
                        "apply.auto_signup: true to let the tool finish it.", host)
            return False

        cred, created = self.vault.get_or_create(host, username)
        if adapter.sign_up(session, cred.username, cred.password):
            application.log("signed_up", host=host, created=created)
            for text in ("Create Account", "Sign Up", "Register", "Continue"):
                try:
                    button = session.page.get_by_role("button", name=text, exact=False).first
                    if button.count() and button.is_visible():
                        button.click(timeout=6000)
                        session.page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue
            obstacle = session.needs_human()
            if obstacle and self.config.apply.pause_on_captcha:
                session.pause_for_human(f"account creation on {host} hit {obstacle}")
            return True
        return False

    # ------------------------------------------------------------------ one application
    def apply_to(self, job: Job, session: BrowserSession) -> Application:
        application = Application(
            job_id=job.id, company=job.company, title=job.title,
            url=job.apply_url or job.url, ats=job.ats or "", match_score=job.match_score,
            autonomy=self.config.apply.autonomy)
        self.store.applications.save(application)

        blocked = self.guardrail_block(job)
        if blocked:
            application.status = "skipped"
            application.notes = blocked
            application.log("skipped", reason=blocked)
            log.info("skip %s - %s", job.short(), blocked)
            return self.store.applications.save(application)

        application.status = "in_progress"
        self.store.applications.save(application)

        adapter = adapter_for(name=job.ats, url=job.apply_url or job.url, catalog=self.catalog)
        application.ats = adapter.name
        if adapter.assisted_only:
            application.status = "needs_input"
            application.notes = f"{adapter.name} is assisted-only: drive it yourself"
            return self.store.applications.save(application)

        if not adapter.open_application(session, job.apply_url or job.url):
            application.status = "failed"
            application.error = "could not open the application page"
            return self.store.applications.save(application)

        closed = adapter.is_closed(session)
        if closed:
            application.status = "skipped"
            application.notes = f"posting is closed ({closed})"
            application.log("closed", marker=closed)
            self.store.jobs.set_status(job.id, "closed")
            log.info("%s is closed - skipping and marking the job", job.short())
            return self.store.applications.save(application)

        # Only now is it worth tailoring: writing a resume for a posting that turns out to be
        # closed burns model tokens and a compile for nothing.
        tailored, cover_path, cover_text = self.prepare_documents(job)
        application.resume_path = tailored.pdf_path
        application.resume_id = tailored.id
        application.cover_letter_path = cover_path
        application.log("resume_ready", pdf=tailored.pdf_path, ats_score=tailored.ats_score,
                        coverage=tailored.keyword_coverage, violations=len(tailored.violations))
        if not tailored.pdf_path:
            application.status = "failed"
            application.error = "resume PDF could not be produced"
            return self.store.applications.save(application)
        self.store.applications.save(application)

        detected = self.catalog.detect_ats(session.page.url, session.html(40000))
        if detected != "generic" and detected != adapter.name:
            adapter = adapter_for(name=detected, catalog=self.catalog)
            application.ats = adapter.name
            log.info("detected %s on the page", detected)

        if adapter.requires_account and not self.ensure_account(session, adapter, job, application):
            if application.status == "needs_input":
                application.screenshots.append(session.screenshot(f"{application.id}-signup"))
                return self.store.applications.save(application)

        context = ResolveContext(
            job=job, company=job.company, ats=adapter.name,
            resume_path=tailored.pdf_path, cover_letter_path=cover_path,
            cover_letter_text=cover_text,
            # only unlock the vault when the site actually demands an account, so an ordinary
            # run never prompts for a passphrase
            generated_password=(self._vault_password(session.page.url)
                                if adapter.requires_account else ""))
        resolver = FieldResolver(self.profile, context, self.store.answers, self.catalog)

        merged_plan = None
        for step in range(MAX_STEPS):
            obstacle = session.needs_human()
            if obstacle:
                if self.config.apply.pause_on_captcha:
                    if not session.pause_for_human(obstacle):
                        application.status = "needs_input"
                        application.notes = f"stopped at {obstacle}"
                        application.screenshots.append(
                            session.screenshot(f"{application.id}-blocked"))
                        return self.store.applications.save(application)
                else:
                    application.status = "needs_input"
                    application.notes = f"stopped at {obstacle}"
                    return self.store.applications.save(application)

            adapter.before_fill(session)
            state = adapter.current_step(session)
            if not state.fields:
                log.debug("step %d had no fields", step)
                if not state.has_next:
                    break

            plan = resolver.resolve_form(state.fields, url=session.page.url, job_id=job.id)
            if plan.unresolved:
                filled, still = self.answers.answer_batch(
                    plan.unresolved, job, job.company, context)
                plan.fields.extend(filled)
                plan.unresolved = still

            merged_plan = merged_plan or plan
            if merged_plan is not plan:
                merged_plan.fields.extend(plan.fields)
                merged_plan.unresolved.extend(plan.unresolved)
                merged_plan.blocking.extend(plan.blocking)

            if self.config.apply.autonomy == "dryrun":
                application.status = "planned"
                application.plan = merged_plan
                application.fields_filled = merged_plan.resolved_count
                application.fields_flagged = merged_plan.review_count
                application.log("dry_run", step=step, fields=len(plan.fields))
                return self.store.applications.save(application)

            errors = 0
            for filled in plan.fields:
                ok, error = session.apply_field(filled, frame=filled.frame)
                if not ok:
                    filled.error = error
                    errors += 1
                    log.debug("could not fill %s: %s", filled.question[:50], error)
            adapter.after_fill(session)

            application.fields_filled += len([f for f in plan.fields if not f.error])
            application.fields_flagged += plan.review_count
            application.log("step_filled", step=step, filled=len(plan.fields), errors=errors,
                            unresolved=len(plan.unresolved))
            if self.config.apply.screenshot_every_step:
                shot = session.screenshot(f"{application.id}-step{step}")
                if shot:
                    application.screenshots.append(shot)

            if state.is_final or not state.has_next:
                break
            if not adapter.next_step(session):
                break

        application.plan = merged_plan
        blocking = list(merged_plan.blocking) if merged_plan else []
        required_missing = merged_plan.unresolved_required() if merged_plan else []

        if blocking or required_missing:
            application.status = "needs_input"
            application.notes = "; ".join(
                blocking + [f"unanswered required: {d.question_text()[:60]}"
                            for d in required_missing])[:600]
            application.screenshots.append(session.screenshot(f"{application.id}-review"))
            self.store.events.log("application", "needs input", ref=application.id,
                                  company=job.company, notes=application.notes)
            return self.store.applications.save(application)

        if self.config.apply.autonomy != "auto":
            application.status = "ready_for_review"
            application.screenshots.append(session.screenshot(f"{application.id}-review"))
            log.info("filled and ready for your review: %s", job.short())
            return self.store.applications.save(application)

        if not adapter.submit(session):
            application.status = "needs_input"
            application.notes = "submit control not found"
            return self.store.applications.save(application)

        outcome = adapter.result(session)
        application.screenshots.append(session.screenshot(f"{application.id}-result"))
        if outcome == "submitted":
            application.status = "submitted"
            application.submitted_at = datetime.now(UTC).isoformat()
            log.info("submitted: %s", job.short())
        elif outcome == "duplicate":
            application.status = "duplicate"
        else:
            errors = adapter.validation_errors(session)
            application.status = "needs_input" if errors else "ready_for_review"
            application.notes = "; ".join(errors)[:500]
        application.log("result", outcome=outcome, notes=application.notes)
        self.store.jobs.set_status(job.id, application.status)
        self.store.events.log("application", outcome, ref=application.id, company=job.company,
                              title=job.title, url=application.url)
        return self.store.applications.save(application)

    # ------------------------------------------------------------------ review
    def replay(self, application: Application, session: BrowserSession) -> tuple[int, int]:
        """Re-open a filled application and put the same values back on the page.

        At autonomy `review` the browser closes when the run ends, taking the filled form with
        it. The plan is stored, so re-filling is deterministic and costs nothing: no tailoring,
        no model call, the same values the user already reviewed.
        """
        if not application.plan or not application.plan.fields:
            return 0, 0
        if not session.goto(application.url):
            return 0, len(application.plan.fields)
        session.dismiss_cookie_banner()

        adapter = adapter_for(name=application.ats, url=application.url, catalog=self.catalog)
        adapter.open_application(session, application.url)
        adapter.before_fill(session)

        filled = failed = 0
        for item in application.plan.fields:
            ok, error = session.apply_field(item, frame=item.frame)
            if ok:
                filled += 1
            else:
                failed += 1
                log.debug("replay could not fill %s: %s", item.question[:50], error)
        adapter.after_fill(session)
        application.log("replayed", filled=filled, failed=failed)
        return filled, failed

    # ------------------------------------------------------------------ batch
    def run(self, jobs: list[Job], limit: int | None = None) -> RunReport:
        report = RunReport()
        selected = jobs[: limit or len(jobs)]
        if not selected:
            return report

        with BrowserSession(self.config.apply) as session:
            for index, job in enumerate(selected):
                report.attempted += 1
                try:
                    application = self.apply_to(job, session)
                except Exception as exc:
                    log.exception("unhandled error applying to %s", job.short())
                    application = Application(job_id=job.id, company=job.company, title=job.title,
                                              status="failed", error=str(exc)[:400])
                    self.store.applications.save(application)
                report.applications.append(application)
                bucket = {"submitted": "submitted", "ready_for_review": "ready_for_review",
                          "needs_input": "needs_input", "failed": "failed",
                          "skipped": "skipped", "duplicate": "skipped",
                          "planned": "ready_for_review"}.get(application.status, "failed")
                setattr(report, bucket, getattr(report, bucket) + 1)

                if index < len(selected) - 1:
                    pause = self.config.apply.min_seconds_between_applications
                    if pause:
                        log.debug("pausing %ss before the next application", pause)
                        time.sleep(pause)
        self.store.events.log("run", "apply run finished", **report.as_dict())
        return report
