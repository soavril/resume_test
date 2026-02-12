"""SQLite cache for company research results (TTL 7 days)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from resume_tailor.models.company import CompanyProfile

DEFAULT_DB_PATH = Path.home() / ".resume-tailor" / "cache.db"
DEFAULT_TTL_DAYS = 7


class CompanyCache:
    """SQLite-backed company profile cache with TTL expiration."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB_PATH,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ):
        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_days * 86400
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_cache (
                    company_name TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    cached_at REAL NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def get(self, company_name: str) -> CompanyProfile | None:
        """Get cached company profile if not expired."""
        key = company_name.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT profile_json, cached_at FROM company_cache WHERE company_name = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None

        profile_json, cached_at = row
        if time.time() - cached_at > self.ttl_seconds:
            self.delete(company_name)
            return None

        return CompanyProfile(**json.loads(profile_json))

    def put(self, company_name: str, profile: CompanyProfile) -> None:
        """Cache a company profile."""
        key = company_name.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO company_cache
                   (company_name, profile_json, cached_at)
                   VALUES (?, ?, ?)""",
                (key, profile.model_dump_json(), time.time()),
            )

    def delete(self, company_name: str) -> None:
        """Delete a cached company profile."""
        key = company_name.strip().lower()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM company_cache WHERE company_name = ?", (key,)
            )

    def clear(self) -> int:
        """Clear all cached entries. Returns count of deleted rows."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM company_cache")
            return cursor.rowcount

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM company_cache"
            ).fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM company_cache WHERE ? - cached_at > ?",
                (time.time(), self.ttl_seconds),
            ).fetchone()[0]
        return {"total": total, "expired": expired, "active": total - expired}
