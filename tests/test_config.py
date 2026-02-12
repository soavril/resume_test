"""Tests for config loading."""

import pytest

from resume_tailor.config import AppConfig, CacheConfig, LLMConfig, load_config


class TestConfig:
    def test_defaults(self):
        config = AppConfig()
        assert config.llm.haiku_model == "claude-haiku-4-5-20251001"
        assert config.pipeline.qa_threshold == 80
        assert config.cache.ttl_days == 7

    def test_load_config_defaults(self, tmp_path):
        """Loading from non-existent path returns defaults."""
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.llm.sonnet_model == "claude-sonnet-4-5-20250929"

    def test_load_config_from_yaml(self, tmp_path):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(
            "llm:\n  haiku_model: test-model\npipeline:\n  qa_threshold: 90\n"
        )
        config = load_config(yaml_path)
        assert config.llm.haiku_model == "test-model"
        assert config.pipeline.qa_threshold == 90
        # Defaults for unspecified
        assert config.search.max_results == 3

    def test_cache_resolved_path(self):
        cache = CacheConfig(db_path="~/test.db")
        resolved = cache.resolved_db_path
        assert "~" not in str(resolved)

    def test_frozen_config(self):
        config = LLMConfig()
        with pytest.raises(AttributeError):
            config.haiku_model = "changed"
