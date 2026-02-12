"""Tests for company cache."""

import time

import pytest

from resume_tailor.cache.company_cache import CompanyCache
from resume_tailor.models.company import CompanyProfile


@pytest.fixture
def cache(tmp_path):
    return CompanyCache(db_path=tmp_path / "test_cache.db", ttl_days=1)


@pytest.fixture
def profile():
    return CompanyProfile(
        name="테스트",
        industry="IT",
        description="테스트 회사",
        culture_values=["혁신"],
        tech_stack=["Python"],
        recent_news=["뉴스"],
        business_direction="AI",
    )


class TestCompanyCache:
    def test_put_and_get(self, cache, profile):
        cache.put("테스트", profile)
        result = cache.get("테스트")
        assert result is not None
        assert result.name == "테스트"

    def test_get_nonexistent(self, cache):
        assert cache.get("없는회사") is None

    def test_case_insensitive(self, cache, profile):
        cache.put("Naver", profile)
        assert cache.get("naver") is not None
        assert cache.get("NAVER") is not None

    def test_strip_whitespace(self, cache, profile):
        cache.put("  테스트  ", profile)
        assert cache.get("테스트") is not None

    def test_delete(self, cache, profile):
        cache.put("테스트", profile)
        cache.delete("테스트")
        assert cache.get("테스트") is None

    def test_clear(self, cache, profile):
        cache.put("회사1", profile)
        cache.put("회사2", profile)
        count = cache.clear()
        assert count == 2
        assert cache.get("회사1") is None

    def test_stats(self, cache, profile):
        cache.put("회사1", profile)
        cache.put("회사2", profile)
        stats = cache.stats()
        assert stats["total"] == 2
        assert stats["active"] == 2
        assert stats["expired"] == 0

    def test_ttl_expiration(self, tmp_path, profile):
        """Cache entries expire after TTL."""
        # Create cache with 0-day TTL (immediate expiration)
        cache = CompanyCache(db_path=tmp_path / "ttl_test.db", ttl_days=0)
        cache.put("테스트", profile)
        # With TTL=0, entry should be expired immediately
        time.sleep(0.1)
        assert cache.get("테스트") is None

    def test_upsert(self, cache, profile):
        cache.put("테스트", profile)
        updated = CompanyProfile(
            name="테스트 업데이트",
            industry="금융",
            description="업데이트됨",
            culture_values=["변화"],
            tech_stack=["Java"],
            recent_news=["새 뉴스"],
            business_direction="핀테크",
        )
        cache.put("테스트", updated)
        result = cache.get("테스트")
        assert result.name == "테스트 업데이트"
        assert result.industry == "금융"
