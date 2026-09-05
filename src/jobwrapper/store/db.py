"""SQLite storage. Stdlib only - no native build step, works everywhere Python does."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import paths

SCHEMA_VERSION = 3

MIGRATIONS: list[str] = [
    # v1 - core tables
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_job_id TEXT,
        company TEXT,
        company_domain TEXT,
        title TEXT,
        location TEXT,
        remote INTEGER DEFAULT 0,
        work_model TEXT,
        employment_type TEXT,
        seniority TEXT,
        url TEXT,
        apply_url TEXT,
        ats TEXT,
        salary_min INTEGER,
        salary_max INTEGER,
        salary_currency TEXT,
        posted_at TEXT,
        discovered_at TEXT,
        description TEXT,
        match_score INTEGER DEFAULT 0,
        status TEXT DEFAULT 'new',
        data TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
    CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score DESC);
    CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

    CREATE TABLE IF NOT EXISTS applications (
        id TEXT PRIMARY KEY,
        job_id TEXT,
        company TEXT,
        title TEXT,
        url TEXT,
        ats TEXT,
        status TEXT,
        autonomy TEXT,
        resume_path TEXT,
        cover_letter_path TEXT,
        match_score INTEGER DEFAULT 0,
        fields_filled INTEGER DEFAULT 0,
        fields_flagged INTEGER DEFAULT 0,
        error TEXT,
        confirmation_id TEXT,
        created_at TEXT,
        submitted_at TEXT,
        data TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_apps_job ON applications(job_id);
    CREATE INDEX IF NOT EXISTS idx_apps_status ON applications(status);
    CREATE INDEX IF NOT EXISTS idx_apps_company ON applications(company);

    CREATE TABLE IF NOT EXISTS answers (
        key TEXT PRIMARY KEY,
        question_hash TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        field_key TEXT,
        company TEXT DEFAULT '',
        ats TEXT DEFAULT '',
        source TEXT DEFAULT 'human',
        confidence REAL DEFAULT 1.0,
        times_used INTEGER DEFAULT 0,
        updated_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_answers_hash ON answers(question_hash);

    CREATE TABLE IF NOT EXISTS resumes (
        id TEXT PRIMARY KEY,
        job_id TEXT,
        company TEXT,
        title TEXT,
        pdf_path TEXT,
        tex_path TEXT,
        ats_score INTEGER,
        keyword_coverage REAL,
        engine_used TEXT,
        created_at TEXT,
        data TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_resumes_job ON resumes(job_id);

    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT,
        kind TEXT,
        ref TEXT,
        message TEXT,
        data TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
    CREATE INDEX IF NOT EXISTS idx_events_ref ON events(ref);
    """,
    # v2 - source bookkeeping
    """
    CREATE TABLE IF NOT EXISTS source_state (
        source_id TEXT PRIMARY KEY,
        last_run TEXT,
        last_count INTEGER DEFAULT 0,
        cursor TEXT,
        last_error TEXT
    );
    """,
    # v3 - company-level knowledge learned while applying
    """
    CREATE TABLE IF NOT EXISTS company_profiles (
        domain TEXT PRIMARY KEY,
        company TEXT,
        ats TEXT,
        board_token TEXT,
        careers_url TEXT,
        has_account INTEGER DEFAULT 0,
        notes TEXT,
        updated_at TEXT
    );
    """,
]


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or paths.ensure_layout()["db"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.ensure_layout()["db"]
        self.conn = connect(self.path)
        self.migrate()

    def migrate(self) -> None:
        cur = self.conn.execute("PRAGMA user_version")
        current = cur.fetchone()[0]
        for index, script in enumerate(MIGRATIONS, start=1):
            if index > current:
                self.conn.executescript(script)
                self.conn.execute(f"PRAGMA user_version = {index}")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
