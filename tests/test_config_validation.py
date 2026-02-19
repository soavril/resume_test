"""Tests for config validation."""

import pytest

from resume_tailor.config import load_config


class TestConfigValidation:
    def test_valid_defaults(self):
        """Default config passes validation without raising."""
        # Pass a non-existent path so load_config falls back to defaults
        config = load_config(None)
        # Verify a few representative defaults to confirm the object is valid
        assert config.pipeline.qa_threshold == 80
        assert config.llm.timeout == 120
        assert config.cache.ttl_days == 7

    def test_invalid_qa_threshold(self, tmp_path):
        """qa_threshold above 100 raises ValueError."""
        yaml = tmp_path / "bad.yaml"
        yaml.write_text("pipeline:\n  qa_threshold: 200\n")
        with pytest.raises(ValueError, match="qa_threshold"):
            load_config(yaml)

    def test_invalid_max_rewrites(self, tmp_path):
        """max_rewrites above 10 raises ValueError."""
        yaml = tmp_path / "bad.yaml"
        yaml.write_text("pipeline:\n  max_rewrites: 99\n")
        with pytest.raises(ValueError, match="max_rewrites"):
            load_config(yaml)

    def test_invalid_timeout(self, tmp_path):
        """timeout of 0 (below minimum of 1) raises ValueError."""
        yaml = tmp_path / "bad.yaml"
        yaml.write_text("llm:\n  timeout: 0\n")
        with pytest.raises(ValueError, match="timeout"):
            load_config(yaml)

    def test_invalid_ttl_days(self, tmp_path):
        """ttl_days above 365 raises ValueError."""
        yaml = tmp_path / "bad.yaml"
        yaml.write_text("cache:\n  ttl_days: 999\n")
        with pytest.raises(ValueError, match="ttl_days"):
            load_config(yaml)
