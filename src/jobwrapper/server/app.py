"""Local companion server: the web UI's backend and the browser extension's brain.

Binds to 127.0.0.1 by default. The UI itself is unauthenticated (it is your own machine); the
extension endpoints under /api/ext require the bearer token printed on startup, because a web
page could otherwise talk to them.
"""

from __future__ import annotations

import secrets
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import paths
from ..autofill import AnswerEngine, Catalog, FieldResolver, ResolveContext
from ..config import Config, SourceConfig
from ..llm import LLMClient
from ..logging_setup import get
from ..models import Job, Profile
from ..models.application import FieldDescriptor
from ..models.resume import MasterResume
from ..pipeline.match import score_job
from ..resume.compile import available_engines
from ..store import Store
from .schema import completeness, ui_schema
from .tasks import registry

log = get("server")
WEB_DIR = Path(__file__).resolve().parent / "web"


class AppState:
    """One place for the objects every request needs."""

    def __init__(self) -> None:
        layout = paths.ensure_layout()
        self.layout = layout
        self.config = Config.load()
        self.store = Store()
        self.profile = Profile.load(layout["profile"])
        self.master = MasterResume.load(layout["master_resume"])
        self.llm = LLMClient(self.config.llm)
        self.catalog = Catalog()
        if not self.config.server.token:
            self.config.server.token = secrets.token_urlsafe(24)
            self.config.save()

        self._mtimes: dict[str, float] = {}
        self._stamp()

    def _stamp(self) -> None:
        for key in ("profile", "master_resume", "config"):
            path = self.layout[key]
            self._mtimes[key] = path.stat().st_mtime if path.exists() else 0.0

    def refresh_if_changed(self) -> None:
        """The CLI and the UI write the same files - pick up whichever changed last."""
        for key in ("profile", "master_resume", "config"):
            path = self.layout[key]
            current = path.stat().st_mtime if path.exists() else 0.0
            if current == self._mtimes.get(key):
                continue
            self._mtimes[key] = current
            if key == "profile":
                self.profile = Profile.load(path)
            elif key == "master_resume":
                self.master = MasterResume.load(path)
            else:
                token = self.config.server.token
                self.config = Config.load()
                self.config.server.token = self.config.server.token or token

    def reload_profile(self) -> None:
        self.profile = Profile.load(self.layout["profile"])
        self.master = MasterResume.load(self.layout["master_resume"])
        self._stamp()


state: AppState | None = None


def get_state() -> AppState:
    global state
    if state is None:
        state = AppState()
    else:
        state.refresh_if_changed()
    return state


def require_token(request: Request, app_state: AppState = Depends(get_state)) -> None:
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if not app_state.config.server.token or token != app_state.config.server.token:
        raise HTTPException(status_code=401, detail="invalid or missing extension token")


def _chromium_ready() -> bool:
    try:
        from ..apply.browser import chromium_installed

        return chromium_installed()
    except Exception:
        return False


def create_app() -> FastAPI:
    app = FastAPI(title="Job Wrapper", version="0.1.0", docs_url="/api/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # the extension's origin is chrome-extension://<id>
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ meta
    @app.get("/api/status")
    def status(s: AppState = Depends(get_state)) -> dict[str, Any]:
        profile_dict = s.profile.model_dump(mode="json")
        return {
            "profile_complete": completeness(profile_dict)["_overall"],
            "missing_required": s.profile.missing_required(),
            "jobs": {"total": s.store.jobs.count(), "new": s.store.jobs.count("new")},
            "applications": s.store.applications.stats(),
            "applied_today": s.store.applications.count_today(),
            "daily_cap": s.config.apply.daily_cap,
            "autonomy": s.config.apply.autonomy,
            "llm": {"enabled": s.config.llm.enabled, "available": s.llm.available(),
                    "model": s.config.llm.model, "usage": s.llm.tracker.summary()},
            "browser": {"ready": _chromium_ready(),
                        "hint": "Job Wrapper drives a real browser to fill applications."},
            "resume": {"master_loaded": bool(s.master.experience),
                       "roles": len(s.master.experience),
                       "latex_engines": available_engines() or ["html (chromium)"]},
            "sources": [{"id": x.id, "kind": x.kind, "enabled": x.enabled} for x in s.config.sources],
            "source_runs": s.store.sources.all(),
            "extension_token": s.config.server.token,
        }

    @app.get("/api/schema")
    def schema(s: AppState = Depends(get_state)) -> dict[str, Any]:
        return {"schema": ui_schema(),
                "completeness": completeness(s.profile.model_dump(mode="json"))}

    # ------------------------------------------------------------------ profile
    @app.get("/api/profile")
    def read_profile(s: AppState = Depends(get_state)) -> dict[str, Any]:
        return s.profile.model_dump(mode="json")

    @app.put("/api/profile")
    def write_profile(payload: dict[str, Any] = Body(...),
                      s: AppState = Depends(get_state)) -> dict[str, Any]:
        try:
            profile = Profile.model_validate(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)[:800]) from exc
        profile.save(s.layout["profile"])
        s.profile = profile
        s._stamp()
        return {"ok": True,
                "completeness": completeness(profile.model_dump(mode="json")),
                "missing_required": profile.missing_required()}

    # ------------------------------------------------------------------ config
    @app.get("/api/config")
    def read_config(s: AppState = Depends(get_state)) -> dict[str, Any]:
        return s.config.model_dump(mode="json")

    @app.put("/api/config")
    def write_config(payload: dict[str, Any] = Body(...),
                     s: AppState = Depends(get_state)) -> dict[str, Any]:
        try:
            config = Config.model_validate(payload)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)[:800]) from exc
        config.save()
        s.config = config
        s._stamp()
        return {"ok": True}

    @app.post("/api/sources/detect")
    def detect_source(payload: dict[str, Any] = Body(...),
                      s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..sources import HttpClient, detect_from_url

        url = payload.get("url", "")
        http = HttpClient(user_agent=s.config.user_agent)
        try:
            found = detect_from_url(url, http, company=payload.get("company", ""))
        finally:
            http.close()
        if not found:
            raise HTTPException(status_code=404, detail=f"no known ATS found at {url}")
        source_id = f"{found.ats}:{found.token or found.tenant}"
        if payload.get("save"):
            s.config.sources.append(SourceConfig(id=source_id, kind=found.ats,
                                                 params=found.as_source_params()))
            s.config.save()
        return {"ats": found.ats, "token": found.token, "company": found.company,
                "id": source_id, "saved": bool(payload.get("save"))}

    # ------------------------------------------------------------------ secrets
    @app.get("/api/secrets")
    def read_secrets(s: AppState = Depends(get_state)) -> dict[str, Any]:
        """Never returns the key itself - only whether one is set, and its last four."""
        import os

        from ..vault import Vault

        env_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        stored = ""
        try:
            stored = Vault(interactive=False).get_api_key("anthropic")
        except Exception as exc:
            log.debug("vault read failed: %s", exc)
        return {
            "anthropic": {
                "set": bool(stored) or env_key,
                "source": "environment" if env_key else ("saved" if stored else "none"),
                "hint": f"…{stored[-4:]}" if stored else "",
                "usable": s.llm.available(),
            }
        }

    @app.put("/api/secrets")
    def write_secrets(payload: dict[str, Any] = Body(...),
                      s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..vault import Vault

        key = (payload.get("anthropic_api_key") or "").strip()
        vault = Vault(interactive=False)
        if not key:
            vault.clear_api_key("anthropic")
            s.llm.forget_key()
            return {"ok": True, "cleared": True}
        if not key.startswith("sk-"):
            raise HTTPException(status_code=422,
                                detail="that does not look like an Anthropic API key (sk-…)")
        vault.set_api_key("anthropic", key)
        s.llm.forget_key()
        return {"ok": True, "usable": s.llm.available()}

    @app.post("/api/secrets/test")
    def test_secret(s: AppState = Depends(get_state)) -> dict[str, Any]:
        """One tiny call, so the user can confirm the key works before a real run."""
        s.llm.forget_key()
        if not s.llm.available():
            return {"ok": False, "error": "no key found"}
        try:
            reply = s.llm.text(system="Reply with the single word: ready.",
                               prompt="ping", effort="low", max_tokens=16)
            return {"ok": True, "model": s.config.llm.model, "reply": reply[:40],
                    "cost_usd": round(s.llm.cost_so_far(), 5)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:300]}

    @app.post("/api/setup/browser")
    def install_browser() -> dict[str, Any]:
        """Download the browser from inside the app - a packaged user has no terminal."""
        from ..apply.browser import install_chromium

        if registry.running("browser-setup"):
            raise HTTPException(status_code=409, detail="already downloading")

        def run(task: Any) -> dict[str, Any]:
            task.emit({"stage": "setup", "message": "downloading the browser (about 150 MB)…"})
            ok, output = install_chromium()
            task.emit({"stage": "setup",
                       "message": "browser ready" if ok else f"failed: {output[-160:]}"})
            return {"ok": ok, "output": output}

        return registry.start("browser-setup", run).as_dict()

    # ------------------------------------------------------------------ autopilot
    @app.post("/api/autopilot")
    def start_autopilot(payload: dict[str, Any] = Body(default={}),
                        s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..pipeline import Autopilot

        if registry.running("autopilot"):
            raise HTTPException(status_code=409, detail="a run is already in progress")

        missing = s.profile.missing_required()
        if missing:
            raise HTTPException(status_code=400,
                                detail=f"profile incomplete: {', '.join(missing)}")

        limit = int(payload.get("limit") or 5)
        autonomy = payload.get("autonomy") or s.config.apply.autonomy
        do_search = bool(payload.get("search", True))
        do_overleaf = bool(payload.get("overleaf", True))
        job_ids = payload.get("job_ids") or None

        def run(task: Any) -> dict[str, Any]:
            store = Store()
            config = s.config.model_copy(deep=True)
            config.apply.autonomy = autonomy
            pilot = Autopilot(config, store, s.profile, s.master, s.llm,
                              on_progress=lambda e: task.emit(e.as_dict()))
            task.controller = pilot
            try:
                return pilot.run(limit=limit, do_search=do_search, do_overleaf=do_overleaf,
                                 job_ids=job_ids).as_dict()
            finally:
                store.close()

        return registry.start("autopilot", run).as_dict()

    @app.post("/api/autopilot/stop")
    def stop_autopilot(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        task_id = payload.get("task_id")
        if not task_id:
            running = registry.running("autopilot")
            task_id = running[0].id if running else None
        if not task_id or not registry.stop(task_id):
            raise HTTPException(status_code=404, detail="no stoppable run")
        return {"ok": True, "task_id": task_id}

    @app.get("/api/autopilot/current")
    def current_autopilot() -> dict[str, Any]:
        running = registry.running("autopilot")
        if running:
            return running[0].as_dict()
        recent = [t for t in registry.all() if t.kind == "autopilot"]
        return recent[0].as_dict() if recent else {"status": "idle"}

    # ------------------------------------------------------------------ jobs
    @app.get("/api/jobs")
    def list_jobs(status: str | None = None, min_score: int = 0, limit: int = 200,
                  q: str | None = None, s: AppState = Depends(get_state)) -> list[dict[str, Any]]:
        jobs = s.store.jobs.list(status=status, min_score=min_score, limit=limit, search=q)
        return [j.model_dump(mode="json") for j in jobs]

    @app.post("/api/jobs/{job_id}/status")
    def set_job_status(job_id: str, payload: dict[str, Any] = Body(...),
                       s: AppState = Depends(get_state)) -> dict[str, Any]:
        s.store.jobs.set_status(job_id, payload.get("status", "new"))
        return {"ok": True}

    @app.post("/api/search")
    def start_search(payload: dict[str, Any] = Body(default={}),
                     s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..pipeline import SearchEngine

        only = payload.get("sources") or None

        def run(task: Any) -> dict[str, Any]:
            store = Store()
            engine = SearchEngine(s.config, store, s.profile)
            task.progress = "fetching sources"
            try:
                report = engine.run(only=only)
                return report.as_dict()
            finally:
                engine.close()
                store.close()

        return registry.start("search", run).as_dict()

    # ------------------------------------------------------------------ applications
    @app.get("/api/applications")
    def list_applications(status: str | None = None, limit: int = 100,
                          s: AppState = Depends(get_state)) -> list[dict[str, Any]]:
        return [a.model_dump(mode="json") for a in s.store.applications.list(status=status, limit=limit)]

    @app.post("/api/applications/{application_id}/review")
    def review_application(application_id: str,
                           s: AppState = Depends(get_state)) -> dict[str, Any]:
        """Re-open a filled application in a visible browser and put the values back."""
        from ..apply import ApplicationRunner, BrowserSession

        application = s.store.applications.get(application_id)
        if not application:
            raise HTTPException(status_code=404, detail="unknown application")
        if not (application.plan and application.plan.fields):
            raise HTTPException(status_code=400, detail="this application has no stored plan")
        if registry.running("review"):
            raise HTTPException(status_code=409, detail="a review browser is already open")

        class Handle:
            """Keeps the browser open until the user is finished with it."""

            def __init__(self) -> None:
                self.done = False
                self.submitted = False

            def stop(self) -> None:
                self.done = True

        def run(task: Any) -> dict[str, Any]:
            import time

            store = Store()
            config = s.config.model_copy(deep=True)
            config.apply.headless = False
            handle = Handle()
            task.controller = handle
            runner = ApplicationRunner(config, store, s.profile, s.master, s.llm)
            try:
                with BrowserSession(config.apply) as session:
                    filled, failed = runner.replay(application, session)
                    task.emit({"stage": "review", "message":
                               f"refilled {filled} field(s); check the browser and submit",
                               "company": application.company, "title": application.title})
                    deadline = time.monotonic() + 20 * 60
                    while not handle.done and time.monotonic() < deadline:
                        time.sleep(2)
                    if handle.submitted:
                        from datetime import UTC, datetime

                        application.status = "submitted"
                        application.submitted_at = datetime.now(UTC).isoformat()
                        store.jobs.set_status(application.job_id, "submitted")
                    store.applications.save(application)
                    return {"filled": filled, "failed": failed,
                            "submitted": handle.submitted}
            finally:
                store.close()

        return registry.start("review", run).as_dict()

    @app.post("/api/applications/{application_id}/review/close")
    def close_review(application_id: str, payload: dict[str, Any] = Body(default={}),
                     ) -> dict[str, Any]:
        running = registry.running("review")
        if not running:
            raise HTTPException(status_code=404, detail="no review browser is open")
        handle = running[0].controller
        handle.submitted = bool(payload.get("submitted"))
        handle.done = True
        return {"ok": True, "submitted": handle.submitted}

    @app.post("/api/apply")
    def start_apply(payload: dict[str, Any] = Body(...),
                    s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..apply import ApplicationRunner

        job_ids = payload.get("job_ids") or []
        autonomy = payload.get("autonomy") or s.config.apply.autonomy
        limit = int(payload.get("limit") or len(job_ids) or 5)

        def run(task: Any) -> dict[str, Any]:
            store = Store()
            config = s.config.model_copy(deep=True)
            config.apply.autonomy = autonomy
            jobs = [store.jobs.get(job_id) for job_id in job_ids]
            jobs = [job for job in jobs if job]
            if not jobs:
                jobs = store.jobs.list(status="new",
                                       min_score=config.match.min_score_to_apply, limit=limit)
            task.progress = f"applying to {len(jobs)} job(s) at autonomy '{autonomy}'"
            runner = ApplicationRunner(config, store, s.profile, s.master, s.llm)
            try:
                return runner.run(jobs, limit=limit).as_dict()
            finally:
                store.close()

        return registry.start("apply", run).as_dict()

    @app.get("/api/tasks")
    def list_tasks() -> list[dict[str, Any]]:
        return [t.as_dict() for t in registry.all()]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = registry.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="unknown task")
        return task.as_dict()

    # ------------------------------------------------------------------ answers
    @app.get("/api/answers")
    def list_answers(s: AppState = Depends(get_state)) -> list[dict[str, Any]]:
        return [a.model_dump(mode="json") for a in s.store.answers.list()]

    @app.post("/api/answers")
    def save_answer(payload: dict[str, Any] = Body(...),
                    s: AppState = Depends(get_state)) -> dict[str, Any]:
        record = s.store.answers.remember(
            payload["question"], payload["answer"], field_key=payload.get("field_key", ""),
            company=payload.get("company", ""), source="human")
        return record.model_dump(mode="json")

    @app.delete("/api/answers")
    def delete_answer(question: str = Query(...), company: str = Query(default=""),
                      s: AppState = Depends(get_state)) -> dict[str, Any]:
        return {"deleted": s.store.answers.forget(question, company)}

    # ------------------------------------------------------------------ resume
    @app.get("/api/resume/master")
    def read_master(s: AppState = Depends(get_state)) -> dict[str, Any]:
        return s.master.model_dump(mode="json")

    @app.post("/api/resume/import")
    def import_resume(payload: dict[str, Any] = Body(...),
                      s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..resume.importer import import_master_resume

        path = Path(payload["path"]).expanduser()
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"{path} not found")
        master = import_master_resume(path, s.llm, use_llm=bool(payload.get("use_llm", True)))
        master.save(s.layout["master_resume"])
        s.master = master
        return {"ok": True, "roles": len(master.experience), "projects": len(master.projects),
                "education": len(master.education), "skill_groups": len(master.skill_groups)}

    @app.post("/api/resume/tailor")
    def tailor_resume(payload: dict[str, Any] = Body(...),
                      s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..resume.tailor import Tailor

        job = s.store.jobs.get(payload.get("job_id", ""))
        if not job:
            raise HTTPException(status_code=404, detail="unknown job")
        tailored = Tailor(s.config, s.master, s.profile, s.llm).tailor(job)
        return {"ats_score": tailored.ats_score, "coverage": tailored.keyword_coverage,
                "violations": [v.model_dump(mode="json") for v in tailored.violations],
                "notes": tailored.ats_notes, "summary": tailored.resume.summary,
                "plan": tailored.plan.model_dump(mode="json")}

    @app.get("/api/artifact")
    def artifact(path: str = Query(...), s: AppState = Depends(get_state)) -> FileResponse:
        resolved = Path(path).expanduser().resolve()
        root = s.layout["root"].resolve()
        if root not in resolved.parents:
            raise HTTPException(status_code=403, detail="outside the artifact directory")
        if not resolved.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(resolved)

    # ------------------------------------------------------------------ extension API
    @app.get("/api/ext/ping", dependencies=[Depends(require_token)])
    def ext_ping(s: AppState = Depends(get_state)) -> dict[str, Any]:
        return {"ok": True, "name": s.profile.identity.display_name,
                "autonomy": s.config.apply.autonomy}

    @app.get("/api/ext/profile", dependencies=[Depends(require_token)])
    def ext_profile(s: AppState = Depends(get_state)) -> dict[str, Any]:
        return {"profile": s.profile.model_dump(mode="json"),
                "catalog_version": s.catalog.version}

    @app.post("/api/ext/analyze", dependencies=[Depends(require_token)])
    def ext_analyze(payload: dict[str, Any] = Body(...),
                    s: AppState = Depends(get_state)) -> dict[str, Any]:
        """The extension found a posting on a career site: score it and remember it."""
        from ..resume.keywords import extract_keywords

        job = Job(source="extension", company=payload.get("company", ""),
                  title=payload.get("title", ""), location=payload.get("location", ""),
                  description=payload.get("description", ""), url=payload.get("url", ""),
                  apply_url=payload.get("url", ""), ats=payload.get("ats", ""))
        result = score_job(job, s.profile, s.config.search, s.config.match)
        job.match_score = result.score
        job.match_reasons, job.match_gaps = result.reasons, result.gaps
        s.store.jobs.upsert(job)
        keywords = extract_keywords(job, s.master, s.llm,
                                    use_llm=bool(payload.get("use_llm", False)))
        return {
            "job_id": job.id, "score": result.score, "reasons": result.reasons,
            "gaps": result.gaps, "matched_skills": result.matched_skills,
            "missing_skills": result.missing_skills,
            "keywords": [{"term": k.term, "importance": k.importance, "in_master": k.in_master}
                         for k in keywords],
        }

    @app.post("/api/ext/plan", dependencies=[Depends(require_token)])
    def ext_plan(payload: dict[str, Any] = Body(...),
                 s: AppState = Depends(get_state)) -> dict[str, Any]:
        """Fields observed in the page in, a fill plan out. The heart of V2."""
        descriptors = [FieldDescriptor.model_validate(f) for f in payload.get("fields", [])]
        job = s.store.jobs.get(payload.get("job_id", "")) if payload.get("job_id") else None
        context = ResolveContext(
            job=job, company=payload.get("company", "") or (job.company if job else ""),
            ats=payload.get("ats", "generic"),
            resume_path=payload.get("resume_path", "") or s.profile.documents.master_resume_pdf,
            cover_letter_text=payload.get("cover_letter_text", ""))
        resolver = FieldResolver(s.profile, context, s.store.answers, s.catalog)
        plan = resolver.resolve_form(descriptors, url=payload.get("url", ""),
                                     job_id=payload.get("job_id", ""))
        if plan.unresolved and payload.get("use_llm", True) and s.llm.available():
            engine = AnswerEngine(s.profile, s.llm, s.store.answers, s.master, s.catalog)
            filled, still = engine.answer_batch(plan.unresolved, job, context.company, context)
            plan.fields.extend(filled)
            plan.unresolved = still
        return plan.model_dump(mode="json")

    @app.post("/api/ext/tailor", dependencies=[Depends(require_token)])
    def ext_tailor(payload: dict[str, Any] = Body(...),
                   s: AppState = Depends(get_state)) -> dict[str, Any]:
        """Produce a fresh PDF for the job the extension is looking at."""
        from ..apply.runner import ApplicationRunner

        job = s.store.jobs.get(payload.get("job_id", ""))
        if not job:
            raise HTTPException(status_code=404, detail="unknown job - call /analyze first")
        runner = ApplicationRunner(s.config, s.store, s.profile, s.master, s.llm)
        tailored, cover_path, cover_text = runner.prepare_documents(job)
        return {"resume_path": tailored.pdf_path, "tex_path": tailored.tex_path,
                "ats_score": tailored.ats_score, "coverage": tailored.keyword_coverage,
                "violations": [v.model_dump(mode="json") for v in tailored.violations],
                "cover_letter": cover_text, "cover_letter_path": cover_path,
                "download": f"/api/artifact?path={tailored.pdf_path}"}

    @app.post("/api/ext/answer", dependencies=[Depends(require_token)])
    def ext_answer(payload: dict[str, Any] = Body(...),
                   s: AppState = Depends(get_state)) -> dict[str, Any]:
        descriptor = FieldDescriptor.model_validate(payload.get("field", {}))
        job = s.store.jobs.get(payload.get("job_id", "")) if payload.get("job_id") else None
        engine = AnswerEngine(s.profile, s.llm, s.store.answers, s.master, s.catalog)
        filled, unresolved = engine.answer_batch([descriptor], job, payload.get("company", ""))
        if filled:
            return filled[0].model_dump(mode="json")
        return {"value": "", "needs_human": True,
                "question": descriptor.question_text()}

    @app.post("/api/ext/record", dependencies=[Depends(require_token)])
    def ext_record(payload: dict[str, Any] = Body(...),
                   s: AppState = Depends(get_state)) -> dict[str, Any]:
        from ..models import Application

        application = Application(
            job_id=payload.get("job_id", ""), company=payload.get("company", ""),
            title=payload.get("title", ""), url=payload.get("url", ""),
            ats=payload.get("ats", ""), status=payload.get("status", "submitted"),
            autonomy="extension", resume_path=payload.get("resume_path", ""),
            fields_filled=int(payload.get("fields_filled", 0)),
            fields_flagged=int(payload.get("fields_flagged", 0)))
        if application.status == "submitted":
            from datetime import datetime

            application.submitted_at = datetime.now(UTC).isoformat()
        s.store.applications.save(application)
        s.store.events.log("extension", application.status, ref=application.id,
                           company=application.company, url=application.url)
        return {"ok": True, "application_id": application.id}

    # ------------------------------------------------------------------ static UI
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: Any) -> Any:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        index = WEB_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"detail": "web UI not installed"}, status_code=404)

    return app


def serve(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    import uvicorn

    app_state = get_state()
    host = host or app_state.config.server.host
    port = port or app_state.config.server.port
    log.info("Job Wrapper UI:  http://%s:%s", host, port)
    log.info("Extension token: %s", app_state.config.server.token)
    uvicorn.run(create_app(), host=host, port=port, reload=reload, log_level="warning")
