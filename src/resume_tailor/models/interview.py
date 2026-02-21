"""Models for resume quality checking and interview enrichment."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ResumeQualityCheck:
    """Result of heuristic resume quality analysis."""
    word_count: int
    line_count: int
    has_experience: bool
    experience_items: int
    has_quantitative: bool
    richness_score: float  # 0.0 - 1.0


def check_resume_quality(resume_text: str) -> ResumeQualityCheck:
    """Quick heuristic check on resume input quality.

    Returns a ResumeQualityCheck with a composite richness_score.
    Score < 0.4 indicates a sparse resume that would benefit from enrichment.
    """
    words = resume_text.split()
    lines = [line for line in resume_text.split("\n") if line.strip()]

    # Detect experience sections
    exp_markers = ["경력", "경험", "experience", "career", "프로젝트", "project"]
    has_exp = any(m in resume_text.lower() for m in exp_markers)

    # Count experience items (bullet points)
    exp_items = len(re.findall(r"^[\-\*\u2022]\s", resume_text, re.MULTILINE))

    # Quantitative evidence
    has_quant = bool(re.search(r"\d+[%명건만억원]|\d{2,}", resume_text))

    # Composite score
    score = min(
        1.0,
        (
            min(len(words) / 300, 1.0) * 0.3
            + min(exp_items / 8, 1.0) * 0.3
            + (1.0 if has_quant else 0.0) * 0.2
            + min(len(lines) / 20, 1.0) * 0.2
        ),
    )

    return ResumeQualityCheck(
        word_count=len(words),
        line_count=len(lines),
        has_experience=has_exp,
        experience_items=exp_items,
        has_quantitative=has_quant,
        richness_score=round(score, 3),
    )
