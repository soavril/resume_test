"""Usage logging data models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UsageLog(BaseModel):
    """Single usage log entry for a pipeline run."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = "anonymous"
    timestamp: datetime = Field(default_factory=datetime.now)
    mode: str  # "resume_tailor" | "form_answers"
    company_name: str | None = None
    job_title: str | None = None
    qa_score: int | None = None
    rewrites: int = 0
    elapsed_seconds: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    search_count: int = 0
    estimated_cost_usd: float = 0.0
    role_category: str | None = None
    language: str = "ko"
    success: bool = True
    error_message: str | None = None
