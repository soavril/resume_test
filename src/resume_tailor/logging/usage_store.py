"""SQLite-backed usage log storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from resume_tailor.logging.models import UsageLog

DEFAULT_DB_PATH = Path.home() / ".resume-tailor" / "usage.db"


class UsageStore:
    """SQLite-backed store for pipeline usage logs with WAL mode."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS usage_logs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    company_name TEXT,
                    job_title TEXT,
                    qa_score INTEGER,
                    rewrites INTEGER NOT NULL DEFAULT 0,
                    elapsed_seconds REAL NOT NULL DEFAULT 0.0,
                    total_input_tokens INTEGER NOT NULL DEFAULT 0,
                    total_output_tokens INTEGER NOT NULL DEFAULT 0,
                    search_count INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                    role_category TEXT,
                    language TEXT NOT NULL DEFAULT 'ko',
                    success INTEGER NOT NULL DEFAULT 1,
                    error_message TEXT
                )
            """)

    def save_log(self, log: UsageLog) -> None:
        """Persist a usage log entry."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO usage_logs
                   (id, session_id, timestamp, mode, company_name, job_title,
                    qa_score, rewrites, elapsed_seconds, total_input_tokens,
                    total_output_tokens, search_count, estimated_cost_usd,
                    role_category, language, success, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log.id,
                    log.session_id,
                    log.timestamp.isoformat(),
                    log.mode,
                    log.company_name,
                    log.job_title,
                    log.qa_score,
                    log.rewrites,
                    log.elapsed_seconds,
                    log.total_input_tokens,
                    log.total_output_tokens,
                    log.search_count,
                    log.estimated_cost_usd,
                    log.role_category,
                    log.language,
                    1 if log.success else 0,
                    log.error_message,
                ),
            )

    def get_logs(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[UsageLog]:
        """Retrieve usage logs, optionally filtered by session_id."""
        with self._connect() as conn:
            if session_id is not None:
                rows = conn.execute(
                    "SELECT * FROM usage_logs WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM usage_logs ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_log(row) for row in rows]

    def get_monthly_stats(self) -> dict:
        """Get aggregated stats for the current month."""
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT
                       COUNT(*) as total_runs,
                       SUM(total_input_tokens) as total_input,
                       SUM(total_output_tokens) as total_output,
                       SUM(search_count) as total_searches,
                       SUM(estimated_cost_usd) as total_cost,
                       AVG(qa_score) as avg_qa_score,
                       SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count
                   FROM usage_logs
                   WHERE timestamp >= ?""",
                (month_start.isoformat(),),
            ).fetchone()
        return {
            "total_runs": row[0] or 0,
            "total_input_tokens": row[1] or 0,
            "total_output_tokens": row[2] or 0,
            "total_searches": row[3] or 0,
            "total_cost_usd": row[4] or 0.0,
            "avg_qa_score": round(row[5], 1) if row[5] is not None else None,
            "success_rate": (row[6] / row[0] * 100) if row[0] else 0.0,
            "month": now.strftime("%Y-%m"),
        }

    def get_total_cost(self) -> float:
        """Get total estimated cost across all logs."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(estimated_cost_usd) FROM usage_logs"
            ).fetchone()
        return row[0] or 0.0

    @staticmethod
    def _row_to_log(row: tuple) -> UsageLog:
        return UsageLog(
            id=row[0],
            session_id=row[1],
            timestamp=datetime.fromisoformat(row[2]),
            mode=row[3],
            company_name=row[4],
            job_title=row[5],
            qa_score=row[6],
            rewrites=row[7],
            elapsed_seconds=row[8],
            total_input_tokens=row[9],
            total_output_tokens=row[10],
            search_count=row[11],
            estimated_cost_usd=row[12],
            role_category=row[13],
            language=row[14],
            success=bool(row[15]),
            error_message=row[16],
        )
