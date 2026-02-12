"""Application configuration loaded from config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class LLMConfig:
    haiku_model: str = "claude-haiku-4-5-20251001"
    sonnet_model: str = "claude-sonnet-4-5-20250929"
    max_retries: int = 3
    timeout: int = 60


@dataclass(frozen=True)
class SearchConfig:
    max_results: int = 3
    search_depth: str = "advanced"


@dataclass(frozen=True)
class PipelineConfig:
    qa_threshold: int = 80
    max_rewrites: int = 1
    writer_temperature: float = 0.3


@dataclass(frozen=True)
class CacheConfig:
    ttl_days: int = 7
    db_path: str = "~/.resume-tailor/cache.db"

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()


@dataclass(frozen=True)
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from YAML file, falling back to defaults."""
    if path is None:
        # Look for config.yaml relative to the project root
        candidates = [
            Path.cwd() / "config.yaml",
            Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
        ]
        for c in candidates:
            if c.exists():
                path = c
                break

    raw: dict = {}
    if path is not None:
        p = Path(path)
        if p.exists():
            raw = yaml.safe_load(p.read_text()) or {}

    return AppConfig(
        llm=LLMConfig(**raw.get("llm", {})),
        search=SearchConfig(**raw.get("search", {})),
        pipeline=PipelineConfig(**raw.get("pipeline", {})),
        cache=CacheConfig(**raw.get("cache", {})),
    )
