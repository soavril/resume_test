"""Pydantic models for sentence refinement suggestions."""

from __future__ import annotations

from pydantic import BaseModel


class RefinementSuggestion(BaseModel):
    """A single alternative suggestion for a selected sentence."""

    alternative: str        # Alternative text
    rationale: str          # One-line explanation
    improvement_type: str   # "conciseness" | "impact" | "keyword" | "tone"
