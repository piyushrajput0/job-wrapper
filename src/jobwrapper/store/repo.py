"""Typed repositories over the SQLite tables."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import Application, Job
from ..models.profile import AnswerRecord
from ..models.resume import TailoredResume
from .db import Database


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_question(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[\*✱]|\brequired\b|\boptional\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def question_hash(text: str) -> str:
    return hashlib.sha1(normalize_question(text).encode()).hexdigest()[:16]


class JobRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, job: Job) -> bool:
        """Returns True if this was a new job."""
        existing = self.get(job.id)
        if existing:
            # keep the richest description and the earliest discovery timestamp
            if len(job.description) > len(existing.description):
                existing.description = job.description
                existing.description_html = job.description_html
            existing.apply_url = existing.apply_url or job.apply_url
            existing.salary = existing.salary if existing.salary.min else job.salary
            existing.ats = existing.ats or job.ats
            existing.tags = sorted(set(existing.tags) | set(job.tags))
            self._write(existing, status=None)
            return False
        self._write(job, status="new")
        return True

    def _write(self, job: Job, status: str | None) -> None:
        row = (
            job.id, job.source, job.source_job_id, job.company, job.company_domain, job.title,
            job.location, int(job.remote), job.work_model, job.employment_type, job.seniority,
            job.url, job.apply_url, job.ats, job.salary.min, job.salary.max, job.salary.currency,
            job.posted_at, job.discovered_at, job.description, job.match_score,
            status or self.status(job.id) or "new",
            json.dumps(job.model_dump(mode="json")),
        )
        self.conn.execute(
            """INSERT INTO jobs (id, source, source_job_id, company, company_domain, title,
                   location, remote, work_model, employment_type, seniority, url, apply_url, ats,
                   salary_min, salary_max, salary_currency, posted_at, discovered_at, description,
                   match_score, status, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                   company=excluded.company, title=excluded.title, location=excluded.location,
                   apply_url=excluded.apply_url, ats=excluded.ats, description=excluded.description,
                   match_score=excluded.match_score, salary_min=excluded.salary_min,
                   salary_max=excluded.salary_max, data=excluded.data""",
            row,
        )
        self.conn.commit()

    def status(self, job_id: str) -> str | None:
        row = self.conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["status"] if row else None

    def set_status(self, job_id: str, status: str) -> None:
        self.conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
        self.conn.commit()

    def set_score(self, job: Job) -> None:
        self.conn.execute(
            "UPDATE jobs SET match_score=?, data=? WHERE id=?",
            (job.match_score, json.dumps(job.model_dump(mode="json")), job.id),
        )
        self.conn.commit()

    def get(self, job_id: str) -> Job | None:
        row = self.conn.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return Job.model_validate(json.loads(row["data"])) if row else None

    def list(self, *, status: str | None = None, min_score: int = 0, limit: int = 100,
             company: str | None = None, search: str | None = None,
             order: str = "match_score DESC") -> list[Job]:
        clauses = ["match_score >= ?"]
        params: list[Any] = [min_score]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if company:
            clauses.append("LOWER(company) LIKE ?")
            params.append(f"%{company.lower()}%")
        if search:
            clauses.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)")
            params += [f"%{search.lower()}%", f"%{search.lower()}%"]
        sql = f"SELECT data FROM jobs WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [Job.model_validate(json.loads(r["data"])) for r in rows]

    def count(self, status: str | None = None) -> int:
        if status:
            row = self.conn.execute("SELECT COUNT(*) c FROM jobs WHERE status=?", (status,)).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()
        return int(row["c"])

    def delete_older_than(self, days: int) -> int:
        cutoff = datetime.now(UTC).timestamp() - days * 86400
        rows = self.conn.execute("SELECT id, discovered_at FROM jobs").fetchall()
        stale = []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["discovered_at"]).timestamp()
            except Exception:
                continue
            if ts < cutoff:
                stale.append(r["id"])
        for job_id in stale:
            self.conn.execute("DELETE FROM jobs WHERE id=? AND status='new'", (job_id,))
        self.conn.commit()
        return len(stale)


class ApplicationRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, app: Application) -> Application:
        if not app.id:
            app.id = uuid.uuid4().hex[:12]
        self.conn.execute(
            """INSERT INTO applications (id, job_id, company, title, url, ats, status, autonomy,
                   resume_path, cover_letter_path, match_score, fields_filled, fields_flagged,
                   error, confirmation_id, created_at, submitted_at, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
                   resume_path=excluded.resume_path, cover_letter_path=excluded.cover_letter_path,
                   fields_filled=excluded.fields_filled, fields_flagged=excluded.fields_flagged,
                   error=excluded.error, confirmation_id=excluded.confirmation_id,
                   submitted_at=excluded.submitted_at, data=excluded.data""",
            (app.id, app.job_id, app.company, app.title, app.url, app.ats, app.status, app.autonomy,
             app.resume_path, app.cover_letter_path, app.match_score, app.fields_filled,
             app.fields_flagged, app.error, app.confirmation_id, app.created_at, app.submitted_at,
             json.dumps(app.model_dump(mode="json"))),
        )
        self.conn.commit()
        return app

    def get(self, app_id: str) -> Application | None:
        row = self.conn.execute("SELECT data FROM applications WHERE id=?", (app_id,)).fetchone()
        return Application.model_validate(json.loads(row["data"])) if row else None

    def for_job(self, job_id: str) -> Application | None:
        row = self.conn.execute(
            "SELECT data FROM applications WHERE job_id=? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return Application.model_validate(json.loads(row["data"])) if row else None

    def list(self, *, status: str | None = None, limit: int = 100) -> list[Application]:
        if status:
            rows = self.conn.execute(
                "SELECT data FROM applications WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM applications ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [Application.model_validate(json.loads(r["data"])) for r in rows]

    def count_today(self) -> int:
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE submitted_at LIKE ? AND status='submitted'",
            (f"{today}%",)).fetchone()
        return int(row["c"])

    def count_attempts_today(self) -> int:
        """Everything worked on today, however it ended - this is what the daily cap limits."""
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE created_at LIKE ? "
            "AND status IN ('submitted','ready_for_review','needs_input','failed','duplicate')",
            (f"{today}%",)).fetchone()
        return int(row["c"])

    def count_for_company(self, company: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE LOWER(company)=? AND status IN ('submitted','ready_for_review')",
            (company.lower(),)).fetchone()
        return int(row["c"])

    def stats(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM applications GROUP BY status").fetchall()
        return {r["status"]: int(r["c"]) for r in rows}


class AnswerRepo:
    """The memory that stops the tool asking the same question twice."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @staticmethod
    def _key(qhash: str, company: str) -> str:
        return f"{qhash}:{(company or '').lower()}"

    def remember(self, question: str, answer: str, *, field_key: str = "", company: str = "",
                 ats: str = "", source: str = "human", confidence: float = 1.0) -> AnswerRecord:
        qhash = question_hash(question)
        record = AnswerRecord(
            question_hash=qhash, question=question, answer=answer, field_key=field_key,
            company=company, ats=ats, source=source, confidence=confidence, updated_at=_now(),
        )
        self.conn.execute(
            """INSERT INTO answers (key, question_hash, question, answer, field_key, company, ats,
                   source, confidence, times_used, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,0,?)
               ON CONFLICT(key) DO UPDATE SET answer=excluded.answer, field_key=excluded.field_key,
                   source=excluded.source, confidence=excluded.confidence,
                   updated_at=excluded.updated_at""",
            (self._key(qhash, company), qhash, question, answer, field_key, company, ats, source,
             confidence, record.updated_at),
        )
        self.conn.commit()
        return record

    def recall(self, question: str, company: str = "") -> AnswerRecord | None:
        qhash = question_hash(question)
        for key in ([self._key(qhash, company)] if company else []) + [self._key(qhash, "")]:
            row = self.conn.execute("SELECT * FROM answers WHERE key=?", (key,)).fetchone()
            if row:
                self.conn.execute("UPDATE answers SET times_used=times_used+1 WHERE key=?", (key,))
                self.conn.commit()
                return AnswerRecord(
                    question_hash=row["question_hash"], question=row["question"],
                    answer=row["answer"], field_key=row["field_key"] or "", company=row["company"] or "",
                    ats=row["ats"] or "", source=row["source"], confidence=row["confidence"],
                    times_used=row["times_used"], updated_at=row["updated_at"] or "",
                )
        return None

    def list(self, limit: int = 500) -> list[AnswerRecord]:
        rows = self.conn.execute(
            "SELECT * FROM answers ORDER BY times_used DESC, updated_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [AnswerRecord(
            question_hash=r["question_hash"], question=r["question"], answer=r["answer"],
            field_key=r["field_key"] or "", company=r["company"] or "", ats=r["ats"] or "",
            source=r["source"], confidence=r["confidence"], times_used=r["times_used"],
            updated_at=r["updated_at"] or "") for r in rows]

    def forget(self, question: str, company: str = "") -> bool:
        cur = self.conn.execute(
            "DELETE FROM answers WHERE key=?", (self._key(question_hash(question), company),))
        self.conn.commit()
        return cur.rowcount > 0


class ResumeRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, tailored: TailoredResume) -> TailoredResume:
        if not tailored.id:
            tailored.id = uuid.uuid4().hex[:12]
        self.conn.execute(
            """INSERT INTO resumes (id, job_id, company, title, pdf_path, tex_path, ats_score,
                   keyword_coverage, engine_used, created_at, data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET pdf_path=excluded.pdf_path, tex_path=excluded.tex_path,
                   ats_score=excluded.ats_score, data=excluded.data""",
            (tailored.id, tailored.job_id, tailored.company, tailored.title, tailored.pdf_path,
             tailored.tex_path, tailored.ats_score, tailored.keyword_coverage, tailored.engine_used,
             tailored.created_at, json.dumps(tailored.model_dump(mode="json"))),
        )
        self.conn.commit()
        return tailored

    def for_job(self, job_id: str) -> TailoredResume | None:
        row = self.conn.execute(
            "SELECT data FROM resumes WHERE job_id=? ORDER BY created_at DESC LIMIT 1",
            (job_id,)).fetchone()
        return TailoredResume.model_validate(json.loads(row["data"])) if row else None

    def list(self, limit: int = 50) -> list[TailoredResume]:
        rows = self.conn.execute(
            "SELECT data FROM resumes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [TailoredResume.model_validate(json.loads(r["data"])) for r in rows]


class EventRepo:
    """Append-only audit trail. Every submission is reconstructable from this."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def log(self, kind: str, message: str, ref: str = "", **data: Any) -> None:
        self.conn.execute(
            "INSERT INTO events (at, kind, ref, message, data) VALUES (?,?,?,?,?)",
            (_now(), kind, ref, message, json.dumps(data, default=str)),
        )
        self.conn.commit()

    def recent(self, limit: int = 50, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


class SourceStateRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record_run(self, source_id: str, count: int, error: str = "") -> None:
        self.conn.execute(
            """INSERT INTO source_state (source_id, last_run, last_count, last_error)
               VALUES (?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET last_run=excluded.last_run,
                   last_count=excluded.last_count, last_error=excluded.last_error""",
            (source_id, _now(), count, error))
        self.conn.commit()

    def all(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM source_state").fetchall()]


class CompanyRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def remember(self, domain: str, **fields: Any) -> None:
        current = self.get(domain) or {}
        current.update({k: v for k, v in fields.items() if v is not None})
        self.conn.execute(
            """INSERT INTO company_profiles (domain, company, ats, board_token, careers_url,
                   has_account, notes, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(domain) DO UPDATE SET company=excluded.company, ats=excluded.ats,
                   board_token=excluded.board_token, careers_url=excluded.careers_url,
                   has_account=excluded.has_account, notes=excluded.notes,
                   updated_at=excluded.updated_at""",
            (domain, current.get("company", ""), current.get("ats", ""),
             current.get("board_token", ""), current.get("careers_url", ""),
             int(current.get("has_account", 0)), current.get("notes", ""), _now()))
        self.conn.commit()

    def get(self, domain: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM company_profiles WHERE domain=?", (domain,)).fetchone()
        return dict(row) if row else None


class Store:
    """One handle for everything persistent."""

    def __init__(self, path: Path | None = None) -> None:
        self.db = Database(path)
        conn = self.db.conn
        self.jobs = JobRepo(conn)
        self.applications = ApplicationRepo(conn)
        self.answers = AnswerRepo(conn)
        self.resumes = ResumeRepo(conn)
        self.events = EventRepo(conn)
        self.sources = SourceStateRepo(conn)
        self.companies = CompanyRepo(conn)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
