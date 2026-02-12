"""Pydantic models for Company Researcher output."""

from __future__ import annotations

from pydantic import BaseModel


class CompanyProfile(BaseModel):
    name: str
    industry: str
    description: str
    culture_values: list[str]
    tech_stack: list[str]
    recent_news: list[str]
    business_direction: str
    employee_count: str | None = None
    headquarters: str | None = None
