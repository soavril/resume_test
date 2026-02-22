"""HWPX template filler — placeholder replacement + LLM-based smart fill.

Mirrors the DOCX filler (docx_renderer.py + smart_filler.py) for HWPX files.
Requires python-hwpx (pip install python-hwpx).

Pipeline (smart fill):
  1. Extract HWPX structure → compact JSON description
  2. Reuse smart_filler LLM logic → fill_plan
  3. Execute fill_plan on the HWPX via python-hwpx API
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from resume_tailor.models.resume import TailoredResume
from resume_tailor.parsers.resume_parser import EMOJI_PATTERN

logger = logging.getLogger(__name__)

try:
    from hwpx.document import HwpxDocument
except ImportError:
    HwpxDocument = None  # type: ignore[assignment,misc]

MAX_ADD_ROWS = 20


def _require_hwpx() -> None:
    """Raise a clear error if python-hwpx is not installed."""
    if HwpxDocument is None:
        raise ImportError(
            "python-hwpx가 필요합니다. 설치: pip install python-hwpx"
        )


# ---------------------------------------------------------------------------
# Placeholder-based fill
# ---------------------------------------------------------------------------


def list_hwpx_placeholders(template_path: str | Path) -> list[str]:
    """Scan a .hwpx template and return all {{placeholder}} keys found.

    Scans both paragraphs and table cells.
    """
    _require_hwpx()
    doc = HwpxDocument.open(str(template_path))
    try:
        placeholders: set[str] = set()
        pattern = re.compile(r"\{\{(.+?)\}\}")

        for para in doc.paragraphs:
            text = para.text or ""
            for m in pattern.finditer(text):
                placeholders.add(m.group(1).strip())

            # Scan table cells within this paragraph
            tables = para.tables if hasattr(para, "tables") else []
            for table in tables:
                for ri in range(table.row_count):
                    for ci in range(table.column_count):
                        cell_text = table.cell(ri, ci).text or ""
                        for m in pattern.finditer(cell_text):
                            placeholders.add(m.group(1).strip())

        return sorted(placeholders)
    finally:
        doc.close()


def fill_hwpx_template(
    template_path: str | Path,
    resume: TailoredResume,
    output_path: str | Path,
    extra_vars: dict[str, str] | None = None,
) -> Path:
    """Fill a .hwpx template by replacing {{placeholder}} markers.

    Supported placeholders (case-insensitive):
      - {{전체}} or {{full}}         → full_markdown (plain text)
      - {{섹션ID}} e.g. {{summary}} → section content by id
      - {{섹션라벨}} e.g. {{자기소개}} → section content by label
      - Any key from extra_vars      → custom value
    """
    _require_hwpx()
    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.open(str(template_path))
    try:
        replacements = _build_replacement_map(resume, extra_vars)

        replaced = 0
        for key, value in replacements.items():
            clean = _md_to_plain(value)
            placeholder = "{{" + key + "}}"
            count = doc.replace_text_in_runs(placeholder, clean)
            if count == 0:
                placeholder_lower = "{{" + key.lower() + "}}"
                count = doc.replace_text_in_runs(placeholder_lower, clean)
            replaced += count

        logger.info("HWPX placeholder fill: %d replacements made", replaced)
        doc.save_to_path(str(output_path))
        return output_path
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Smart fill (LLM-based)
# ---------------------------------------------------------------------------


def extract_hwpx_structure(path: str | Path) -> dict:
    """Parse a HWPX file into a compact JSON structure description.

    Returns the same format as smart_filler.extract_docx_structure so we can
    reuse the LLM prompt, validation, and formatting logic.
    """
    _require_hwpx()
    doc = HwpxDocument.open(str(path))
    try:
        structure: dict = {"paragraphs": [], "tables": []}

        para_idx = 0
        table_idx = 0

        for para in doc.paragraphs:
            text = (para.text or "").strip()

            # Paragraphs (text outside tables)
            tables = para.tables if hasattr(para, "tables") else []
            if text and not tables:
                structure["paragraphs"].append({
                    "idx": para_idx,
                    "style": "Normal",
                    "text": text[:300],
                })
            para_idx += 1

            # Tables embedded in this paragraph
            for table in tables:
                row_count = table.row_count
                col_count = table.column_count
                table_info: dict = {
                    "idx": table_idx,
                    "rows": row_count,
                    "cols": col_count,
                    "header_rows": [],
                    "data_rows": [],
                }

                all_rows_data = []
                for ri in range(row_count):
                    cells_info = []
                    for ci in range(col_count):
                        cell = table.cell(ri, ci)
                        cell_text = (cell.text or "").strip()
                        cell_data: dict = {
                            "col": ci,
                            "text": cell_text[:300] if cell_text else "",
                        }
                        if not cell_text:
                            cell_data["empty"] = True
                        cells_info.append(cell_data)
                    all_rows_data.append({"row": ri, "cells": cells_info})

                # Classify rows as header or data
                for row_data in all_rows_data:
                    ri = row_data["row"]
                    cells = row_data["cells"]
                    non_empty = [c for c in cells if not c.get("empty")]
                    all_empty = len(non_empty) == 0

                    if all_empty:
                        table_info["data_rows"].append(row_data)
                    elif _is_header_row(ri, cells, all_rows_data):
                        table_info["header_rows"].append(row_data)
                    else:
                        table_info["data_rows"].append(row_data)

                structure["tables"].append(table_info)
                table_idx += 1

        return structure
    finally:
        doc.close()


def _is_header_row(
    ri: int, cells: list[dict], all_rows: list[dict],
) -> bool:
    """Detect header rows using content patterns (same logic as smart_filler)."""
    non_empty = [c for c in cells if not c.get("empty")]
    non_empty_ratio = len(non_empty) / max(len(cells), 1)

    if ri < 2 and non_empty_ratio > 0.3:
        return True

    if non_empty_ratio >= 0.5:
        label_keywords = {
            "기간", "근무", "회사", "직위", "직급", "담당", "업무",
            "학교", "학력", "전공", "기술", "자격", "수상", "어학",
            "년", "월", "일", "시작", "종료", "성명", "생년월일",
            "주소", "연락처", "이메일", "성별",
        }
        label_like = sum(
            1 for c in non_empty
            if any(kw in c["text"] for kw in label_keywords)
        )
        if label_like >= 2:
            return True

        if ri + 1 < len(all_rows):
            next_cells = all_rows[ri + 1]["cells"]
            next_empty_ratio = sum(
                1 for c in next_cells if c.get("empty")
            ) / max(len(next_cells), 1)
            if next_empty_ratio >= 0.5 and non_empty_ratio >= 0.6:
                return True

    return False


def execute_hwpx_fill_plan(
    doc_path: str | Path, plan: dict, output_path: str | Path,
) -> Path:
    """Execute a fill plan on a HWPX document."""
    _require_hwpx()
    doc_path = Path(doc_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = HwpxDocument.open(str(doc_path))
    try:
        fills = plan.get("fill_plan", [])

        # Collect all tables from the document
        tables = []
        for para in doc.paragraphs:
            if hasattr(para, "tables"):
                tables.extend(para.tables)

        filled_count = 0
        failed_count = 0

        for item in fills:
            target = item.get("target")

            if target == "table":
                ok, fail = _execute_table_fill(tables, item)
                filled_count += ok
                failed_count += fail
            elif target == "paragraph":
                _execute_paragraph_fill(doc, item)
                filled_count += 1

        logger.info(
            "HWPX fill complete: %d cells filled, %d failed",
            filled_count, failed_count,
        )

        doc.save_to_path(str(output_path))
        return output_path
    finally:
        doc.close()


def _execute_table_fill(
    tables: list, item: dict,
) -> tuple[int, int]:
    """Fill table cells according to the plan."""
    table_idx = item.get("table_idx", 0)
    row_idx = item.get("row")
    filled = 0
    failed = 0

    if table_idx >= len(tables) or row_idx is None:
        return 0, 1

    table = tables[table_idx]

    if row_idx >= table.row_count:
        logger.warning(
            "Row %d exceeds table size %d", row_idx, table.row_count,
        )
        return 0, len(item.get("fills", []))

    for fill in item.get("fills", []):
        col = fill.get("col")
        value = str(fill.get("value", ""))
        if col is None or not value:
            continue

        if col >= table.column_count:
            logger.warning(
                "Table %d Row %d: col %d out of range (max %d)",
                table_idx, row_idx, col, table.column_count - 1,
            )
            failed += 1
            continue

        try:
            clean = _strip_md(value)
            table.set_cell_text(row_idx, col, clean)
            filled += 1
        except Exception:
            logger.warning(
                "Table %d Row %d col %d: set_cell_text failed",
                table_idx, row_idx, col, exc_info=True,
            )
            failed += 1

    return filled, failed


def _execute_paragraph_fill(doc, item: dict) -> None:
    """Replace paragraph text via replace_text_in_runs."""
    action = item.get("action", "replace")
    value = _strip_md(str(item.get("value", "")))

    if action == "replace":
        idx = item.get("paragraph_idx")
        if idx is not None:
            # Find the paragraph text at this index and replace it
            non_table_paras = [
                p for p in doc.paragraphs
                if not (hasattr(p, "tables") and p.tables)
            ]
            if idx < len(non_table_paras):
                old_text = non_table_paras[idx].text or ""
                if old_text.strip():
                    doc.replace_text_in_runs(old_text.strip(), value)

    elif action == "insert":
        # HWPX doesn't support insert-after easily;
        # append as a new paragraph instead
        doc.add_paragraph(value)


# ---------------------------------------------------------------------------
# Public API — smart fill with LLM
# ---------------------------------------------------------------------------


async def smart_fill_hwpx(
    template_path: str | Path,
    resume: TailoredResume,
    output_path: str | Path,
    llm: "LLMClient",  # noqa: F821
    max_attempts: int = 2,
    model: str = "claude-sonnet-4-5-20250929",
) -> Path:
    """Analyze any HWPX template and intelligently fill it with resume data.

    Reuses smart_filler's LLM analysis and validation logic.
    """
    from resume_tailor.templates.smart_filler import (
        analyze_and_plan,
        validate_fill_plan,
    )

    structure = extract_hwpx_structure(template_path)

    plan = await analyze_and_plan(llm, structure, resume, model=model)

    errors: list[str] = []
    for attempt in range(max_attempts):
        errors = validate_fill_plan(structure, plan)
        if not errors:
            break
        logger.warning(
            "Fill plan validation failed (attempt %d/%d): %s",
            attempt + 1, max_attempts, errors,
        )
        if attempt < max_attempts - 1:
            from resume_tailor.templates.smart_filler import _retry_with_errors
            plan = await _retry_with_errors(
                llm, structure, resume, plan, errors, model=model,
            )

    if errors:
        logger.warning(
            "Proceeding with %d validation errors after %d attempts",
            len(errors), max_attempts,
        )

    return execute_hwpx_fill_plan(template_path, plan, output_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_replacement_map(
    resume: TailoredResume,
    extra_vars: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a {placeholder_key: content} map."""
    m: dict[str, str] = {}
    m["전체"] = resume.full_markdown
    m["full"] = resume.full_markdown

    for section in resume.sections:
        m[section.id] = section.content
        m[section.label] = section.content

    if extra_vars:
        m.update(extra_vars)
    return m


def _md_to_plain(md: str) -> str:
    """Convert simple markdown to plain text for HWPX embedding."""
    text = md
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(EMOJI_PATTERN, "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_md(text: str) -> str:
    """Strip markdown formatting."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
