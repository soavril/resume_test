"""Pydantic models for JD Analyst output."""

from __future__ import annotations

from pydantic import BaseModel


class JobAnalysis(BaseModel):
    title: str
    hard_skills: list[str]
    soft_skills: list[str]
    ats_keywords: list[str]
    seniority_level: str
    tone: str  # formal, casual, etc.
    key_responsibilities: list[str]
    preferred_qualifications: list[str]
    years_experience: str | None = None
    role_category: str = "general"  # "tech", "business", "design", "general"
