"""Pydantic models for Strategy Planner output."""

from __future__ import annotations

from pydantic import BaseModel


class MatchItem(BaseModel):
    requirement: str
    my_experience: str
    strength: str  # "strong", "moderate", "weak"
    talking_points: list[str]


class GapItem(BaseModel):
    requirement: str
    mitigation: str


class KeywordPlan(BaseModel):
    keyword: str
    placement: str  # where to place in resume


class ResumeStrategy(BaseModel):
    match_matrix: list[MatchItem]
    gaps: list[GapItem]
    emphasis_points: list[str]
    keyword_plan: list[KeywordPlan]
    tone_guidance: str
    summary_direction: str
