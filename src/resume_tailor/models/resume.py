"""Pydantic models for Resume Writer output."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ResumeSection(BaseModel):
    id: str
    label: str
    content: str  # Markdown content


class TailoredResume(BaseModel):
    sections: list[ResumeSection]
    full_markdown: str
    metadata: dict[str, Any]  # tokens used, model, etc.
