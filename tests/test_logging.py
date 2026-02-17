"""Tests for UsageLog model and UsageStore."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from resume_tailor.logging.models import UsageLog
from resume_tailor.logging.usage_store import UsageStore


# --- UsageLog model tests ---


class TestUsageLog:
    def test_create_minimal(self):
        log = UsageLog(mode="resume_tailor")
        assert log.mode == "resume_tailor"
        assert log.session_id == "anonymous"
        assert log.success is True
        assert log.rewrites == 0
        assert log.language == "ko"
        assert log.id  # uuid auto-generated

    def test_create_full(self):
        log = UsageLog(
            mode="form_answers",
            session_id="sess-123",
            company_name="Acme Corp",
            job_title="Backend Engineer",
            qa_score=85,
            rewrites=1,
            elapsed_seconds=42.5,
            total_input_tokens=5000,
            total_output_tokens=3000,
            search_count=3,
            estimated_cost_usd=0.05,
            role_category="developer",
            language="en",
            success=True,
        )
        assert log.company_name == "Acme Corp"
        assert log.qa_score == 85
        assert log.total_input_tokens == 5000
        assert log.estimated_cost_usd == 0.05

    def test_unique_ids(self):
        a = UsageLog(mode="resume_tailor")
        b = UsageLog(mode="resume_tailor")
        assert a.id != b.id

    def test_timestamp_auto(self):
        before = datetime.now()
        log = UsageLog(mode="resume_tailor")
        after = datetime.now()
        assert before <= log.timestamp <= after

    def test_error_fields(self):
        log = UsageLog(
            mode="resume_tailor",
            success=False,
            error_message="API timeout",
        )
        assert log.success is False
        assert log.error_message == "API timeout"


# --- UsageStore tests ---


@pytest.fixture
def store(tmp_path: Path) -> UsageStore:
    return UsageStore(db_path=tmp_path / "test_usage.db")


class TestUsageStore:
    def test_save_and_get(self, store: UsageStore):
        log = UsageLog(mode="resume_tailor", company_name="TestCo")
        store.save_log(log)
        logs = store.get_logs()
        assert len(logs) == 1
        assert logs[0].id == log.id
        assert logs[0].company_name == "TestCo"

    def test_get_by_session_id(self, store: UsageStore):
        store.save_log(UsageLog(mode="resume_tailor", session_id="s1"))
        store.save_log(UsageLog(mode="resume_tailor", session_id="s2"))
        store.save_log(UsageLog(mode="form_answers", session_id="s1"))

        s1_logs = store.get_logs(session_id="s1")
        assert len(s1_logs) == 2

        s2_logs = store.get_logs(session_id="s2")
        assert len(s2_logs) == 1

    def test_get_logs_limit(self, store: UsageStore):
        for i in range(10):
            store.save_log(UsageLog(mode="resume_tailor"))
        logs = store.get_logs(limit=3)
        assert len(logs) == 3

    def test_get_logs_empty(self, store: UsageStore):
        logs = store.get_logs()
        assert logs == []

    def test_monthly_stats(self, store: UsageStore):
        store.save_log(
            UsageLog(
                mode="resume_tailor",
                total_input_tokens=1000,
                total_output_tokens=500,
                search_count=2,
                estimated_cost_usd=0.03,
                qa_score=90,
            )
        )
        store.save_log(
            UsageLog(
                mode="resume_tailor",
                total_input_tokens=2000,
                total_output_tokens=1000,
                search_count=1,
                estimated_cost_usd=0.05,
                qa_score=80,
            )
        )
        stats = store.get_monthly_stats()
        assert stats["total_runs"] == 2
        assert stats["total_input_tokens"] == 3000
        assert stats["total_output_tokens"] == 1500
        assert stats["total_searches"] == 3
        assert stats["total_cost_usd"] == pytest.approx(0.08)
        assert stats["avg_qa_score"] == 85.0
        assert stats["success_rate"] == 100.0

    def test_monthly_stats_empty(self, store: UsageStore):
        stats = store.get_monthly_stats()
        assert stats["total_runs"] == 0
        assert stats["total_cost_usd"] == 0.0
        assert stats["avg_qa_score"] is None

    def test_get_total_cost(self, store: UsageStore):
        store.save_log(UsageLog(mode="resume_tailor", estimated_cost_usd=0.10))
        store.save_log(UsageLog(mode="form_answers", estimated_cost_usd=0.25))
        assert store.get_total_cost() == pytest.approx(0.35)

    def test_get_total_cost_empty(self, store: UsageStore):
        assert store.get_total_cost() == 0.0

    def test_roundtrip_preserves_fields(self, store: UsageStore):
        log = UsageLog(
            mode="resume_tailor",
            session_id="sess-rt",
            company_name="RoundTrip Inc",
            job_title="Senior Dev",
            qa_score=92,
            rewrites=2,
            elapsed_seconds=120.5,
            total_input_tokens=8000,
            total_output_tokens=4000,
            search_count=5,
            estimated_cost_usd=0.12,
            role_category="developer",
            language="en",
            success=False,
            error_message="QA failed",
        )
        store.save_log(log)
        retrieved = store.get_logs()[0]
        assert retrieved.mode == log.mode
        assert retrieved.session_id == log.session_id
        assert retrieved.company_name == log.company_name
        assert retrieved.job_title == log.job_title
        assert retrieved.qa_score == log.qa_score
        assert retrieved.rewrites == log.rewrites
        assert retrieved.elapsed_seconds == log.elapsed_seconds
        assert retrieved.total_input_tokens == log.total_input_tokens
        assert retrieved.total_output_tokens == log.total_output_tokens
        assert retrieved.search_count == log.search_count
        assert retrieved.estimated_cost_usd == pytest.approx(log.estimated_cost_usd)
        assert retrieved.role_category == log.role_category
        assert retrieved.language == log.language
        assert retrieved.success is False
        assert retrieved.error_message == "QA failed"

    def test_wal_mode(self, tmp_path: Path):
        store = UsageStore(db_path=tmp_path / "wal_test.db")
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "wal_test.db"))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"
