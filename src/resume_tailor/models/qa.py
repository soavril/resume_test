"""Pydantic models for QA Reviewer output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QAResult(BaseModel):
    factual_accuracy: int  # 0-100
    keyword_coverage: int  # 0-100
    template_compliance: int  # 0-100
    overall_score: int  # 0-100
    issues: list[str]
    suggestions: list[str]
    suggestion_examples: list[str] = []  # 각 suggestion에 대응하는 구체적 예시 문장
    pass_: bool = Field(alias="pass")  # overall_score >= threshold

    model_config = {"populate_by_name": True}
