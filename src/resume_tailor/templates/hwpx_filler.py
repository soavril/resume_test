"""HWPX template filler — placeholder replacement + LLM-based smart fill.

Mirrors the DOCX filler (docx_renderer.py + smart_filler.py) for HWPX files.
Requires python-hwpx (pip install python-hwpx).

Pipeline (smart fill):
  1. Extract HWPX structure → compact JSON description (with merge-aware unique cell indexing)
  2. Reuse smart_filler LLM logic → fill_plan
  3. Execute fill_plan on the HWPX via direct TC element access
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from resume_tailor.models.resume import TailoredResume
from resume_tailor.parsers.resume_parser import EMOJI_PATTERN

logger = logging.getLogger(__name__)

try:
    from hwpx.document import HwpxDocument
    from lxml import etree as _lxml_etree
except ImportError:
    HwpxDocument = None  # type: ignore[assignment,misc]
    _lxml_etree = None  # type: ignore[assignment]

MAX_ADD_ROWS = 20

# HWPX XML namespace for paragraph elements
_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = f"{{{_HP_NS}}}"

# Placeholder patterns for post-fill auto-correction
_NAME_PLACEHOLDERS = {"(한글)", "(한자)", "(영문)"}
_SCHOOL_TYPE_LABELS = {
    "고등학교", "전문대학", "대학교", "대학원(석사)", "대학원(박사)",
}


def _require_hwpx() -> None:
    """Raise a clear error if python-hwpx or lxml is not installed."""
    if HwpxDocument is None or _lxml_etree is None:
        raise ImportError(
            "python-hwpx와 lxml이 필요합니다. 설치: pip install python-hwpx lxml"
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
# Smart fill (LLM-based) — merge-aware structure extraction
# ---------------------------------------------------------------------------


def _get_row_tc_info(table_element, row_idx: int) -> list[dict]:
    """Extract unique TC elements and their cellSpan info from a table row.

    Returns a list of dicts with keys: col (unique index), text, span,
    rowSpan, and empty.
    """
    trs = table_element.findall(f"{_HP}tr")
    if row_idx >= len(trs):
        return []

    tr = trs[row_idx]
    tcs = tr.findall(f"{_HP}tc")
    cells_info = []
    grid_col = 0

    for unique_idx, tc in enumerate(tcs):
        # Read cellSpan attributes
        span_el = tc.find(f"{_HP}cellSpan")
        col_span = 1
        row_span = 1
        if span_el is not None:
            cs = span_el.get("colSpan", "1")
            rs = span_el.get("rowSpan", "1")
            col_span = int(cs) if cs.isdigit() else 1
            row_span = int(rs) if rs.isdigit() else 1

        # Read text from this TC
        texts = [t.text for t in tc.findall(f".//{_HP}t") if t.text]
        text = "".join(texts).strip()

        cell_data: dict = {
            "col": unique_idx,
            "text": text[:300] if text else "",
            "grid_start": grid_col,
        }
        if col_span > 1:
            cell_data["span"] = col_span
        if row_span > 1:
            cell_data["rowSpan"] = row_span
        if not text:
            cell_data["empty"] = True

        cells_info.append(cell_data)
        grid_col += col_span

    return cells_info


def extract_hwpx_structure(path: str | Path) -> dict:
    """Parse a HWPX file into a compact JSON structure description.

    Uses actual TC elements with cellSpan detection for unique cell indexing,
    mirroring the DOCX filler's approach. This produces a clean logical view
    instead of the raw grid (which duplicates merged cells).
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
                    cells_info = _get_row_tc_info(table.element, ri)
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
    """Detect header rows using content patterns (same logic as smart_filler).

    Rows with many empty cells are treated as data input rows, not headers,
    even if they contain label-like keywords (e.g. "년 월" + empty slots).
    """
    non_empty = [c for c in cells if not c.get("empty")]
    non_empty_ratio = len(non_empty) / max(len(cells), 1)
    empty_ratio = 1 - non_empty_ratio

    # First 2 rows with content are almost always headers,
    # but rows with many empty cells may be data input rows (label + empty pattern)
    if ri < 2 and non_empty_ratio > 0.3 and empty_ratio < 0.3:
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
        # Only treat as header if most cells are filled (not label + empty input pattern)
        if label_like >= 2 and empty_ratio < 0.3:
            return True

        if ri + 1 < len(all_rows):
            next_cells = all_rows[ri + 1]["cells"]
            next_empty_ratio = sum(
                1 for c in next_cells if c.get("empty")
            ) / max(len(next_cells), 1)
            if next_empty_ratio >= 0.5 and non_empty_ratio >= 0.6:
                return True

    return False


def _remap_plan_cols(structure: dict, plan: dict) -> dict:
    """Remap grid-column indices to TC indices in the fill plan.

    The LLM sometimes uses grid column numbers instead of sequential TC indices
    in heavily merged tables. This function detects out-of-range col values and
    remaps them using the grid_start metadata from structure extraction.
    """
    # Build grid→TC maps from structure
    grid_maps: dict[tuple[int, int], dict[int, int]] = {}
    tc_counts: dict[tuple[int, int], int] = {}

    for t in structure.get("tables", []):
        for row_data in t["header_rows"] + t["data_rows"]:
            ri = row_data["row"]
            key = (t["idx"], ri)
            tc_counts[key] = len(row_data["cells"])
            grid_map: dict[int, int] = {}
            for cell in row_data["cells"]:
                tc_idx = cell["col"]
                grid_start = cell.get("grid_start", tc_idx)
                span = cell.get("span", 1)
                for g in range(grid_start, grid_start + span):
                    grid_map[g] = tc_idx
            grid_maps[key] = grid_map

    remapped_count = 0
    for item in plan.get("fill_plan", []):
        if item.get("target") != "table":
            continue
        table_idx = item.get("table_idx", 0)
        row_idx = item.get("row")
        if row_idx is None:
            continue

        key = (table_idx, row_idx)
        max_tc = tc_counts.get(key, 0)
        grid_map = grid_maps.get(key, {})

        for fill in item.get("fills", []):
            col = fill.get("col")
            if col is None or col < max_tc:
                continue  # Already a valid TC index

            # Out of range — try remapping from grid column
            if col in grid_map:
                old_col = col
                fill["col"] = grid_map[col]
                remapped_count += 1
                logger.info(
                    "Remapped grid col %d → TC %d (table %d row %d)",
                    old_col, fill["col"], table_idx, row_idx,
                )

    if remapped_count:
        logger.info("Total remapped columns: %d", remapped_count)

    # Deduplicate fills — multiple grid cols may map to same TC
    for item in plan.get("fill_plan", []):
        if item.get("target") != "table":
            continue
        fills = item.get("fills", [])
        seen_cols: set[int] = set()
        deduped: list[dict] = []
        for fill in fills:
            col = fill.get("col")
            if col not in seen_cols:
                seen_cols.add(col)
                deduped.append(fill)
        item["fills"] = deduped

    return plan


def execute_hwpx_fill_plan(
    doc_path: str | Path, plan: dict, output_path: str | Path,
) -> Path:
    """Execute a fill plan on a HWPX document.

    Uses unique-cell TC indexing (matching extract_hwpx_structure) to correctly
    handle merged cells. The col index in the fill plan refers to the sequential
    TC element index within the row, not the grid column.
    """
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


def _set_tc_text(tc_element: Any, text: str, table: Any | None = None) -> None:
    """Set text on a TC element using lxml directly.

    Bypasses HwpxOxmlTableCell._ensure_text_element which has a stdlib/lxml
    mismatch bug (uses ET.SubElement on lxml elements) causing TypeError on
    empty cells that lack existing <hp:t> elements.
    """
    LET = _lxml_etree

    # Navigate: tc -> subList -> p -> run -> t
    sublist = tc_element.find(f"{_HP}subList")
    if sublist is None:
        sublist = LET.SubElement(tc_element, f"{_HP}subList", {
            "id": "",
            "textDirection": "HORIZONTAL",
            "lineWrap": "BREAK",
            "vertAlign": "CENTER",
            "linkListIDRef": "0",
            "linkListNextIDRef": "0",
            "textWidth": "0",
            "textHeight": "0",
            "hasTextRef": "0",
        })

    # Remove only truly empty extra paragraphs.
    # Keep paragraphs that contain template text (e.g. "(  년  개월)").
    # This prevents text being pushed to cell bottom in large cells (40+ empty paras)
    # while preserving template formatting in small cells.
    all_paras = sublist.findall(f"{_HP}p")
    if len(all_paras) > 1:
        for extra_p in all_paras[1:]:
            has_text = any(
                (t_el.text or "").strip()
                for t_el in extra_p.iter(f"{_HP}t")
            )
            if not has_text:
                sublist.remove(extra_p)

    paragraph = sublist.find(f"{_HP}p")
    if paragraph is None:
        paragraph = LET.SubElement(sublist, f"{_HP}p", {
            "id": "0",
            "paraPrIDRef": "0",
            "styleIDRef": "0",
            "pageBreak": "0",
            "columnBreak": "0",
        })

    # Clear existing runs and leftover text nodes
    for old_run in paragraph.findall(f"{_HP}run"):
        paragraph.remove(old_run)
    for old_t in paragraph.findall(f"{_HP}t"):
        paragraph.remove(old_t)

    run = LET.SubElement(paragraph, f"{_HP}run", {"charPrIDRef": "0"})
    t_elem = LET.SubElement(run, f"{_HP}t")
    t_elem.text = text

    # Mark dirty so the library re-serializes this cell on save
    tc_element.set("dirty", "1")
    if table is not None:
        table.mark_dirty()


def _execute_table_fill(
    tables: list, item: dict,
) -> tuple[int, int]:
    """Fill table cells using unique-cell TC indexing.

    The col index in the fill plan refers to the sequential TC element index
    within the row (matching extract_hwpx_structure), not the grid column.
    """
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

    # Access the actual TR and TC elements
    trs = table.element.findall(f"{_HP}tr")
    if row_idx >= len(trs):
        return 0, len(item.get("fills", []))

    tr = trs[row_idx]
    tcs = tr.findall(f"{_HP}tc")

    for fill in item.get("fills", []):
        col = fill.get("col")
        value = str(fill.get("value", ""))
        if col is None or not value:
            continue

        if col >= len(tcs):
            logger.warning(
                "Table %d Row %d: col %d out of range (max %d TCs)",
                table_idx, row_idx, col, len(tcs) - 1,
            )
            failed += 1
            continue

        try:
            clean = _strip_md(value)
            tc_element = tcs[col]
            _set_tc_text(tc_element, clean, table=table)
            filled += 1
        except Exception:
            logger.warning(
                "Table %d Row %d col %d: set text failed",
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
# Post-fill auto-correction
# ---------------------------------------------------------------------------


def _extract_personal_data(resume: TailoredResume) -> dict[str, str]:
    """Extract name variants from resume for placeholder replacement."""
    data: dict[str, str] = {}
    for section in resume.sections:
        if section.id == "personal" or section.label in ("기본사항", "인적사항"):
            for line in section.content.split("\n"):
                line = line.strip()
                if "성명" not in line and "이름" not in line:
                    continue
                parts = line.split(":", 1)
                if len(parts) < 2:
                    continue
                name_part = parts[1].strip()
                # Korean name: before ( or /
                korean = re.split(r"[(/]", name_part)[0].strip()
                if korean:
                    data["(한글)"] = korean
                # English name: in parentheses with capital letters
                eng_match = re.search(r"\(([A-Z][A-Za-z\s]+)\)", name_part)
                if eng_match:
                    data["(영문)"] = eng_match.group(1).strip()
            break
    return data


def _extract_school_names(resume: TailoredResume) -> dict[str, str]:
    """Extract school name by type from resume.

    Returns {school_type_label: actual_school_name}.
    """
    schools: dict[str, str] = {}
    for section in resume.sections:
        if section.id == "education" or section.label in ("학력사항", "학력"):
            content = section.content
            for school_type in ["대학원", "대학교", "전문대학", "고등학교"]:
                pattern = rf"\S*{re.escape(school_type)}\S*"
                matches = re.findall(pattern, content)
                for match in matches:
                    clean = re.sub(r"\([^)]*\)", "", match).strip()
                    if clean and clean != school_type:
                        if school_type == "대학원":
                            schools.setdefault("대학원(석사)", clean)
                            schools.setdefault("대학원(박사)", clean)
                        else:
                            schools[school_type] = clean
                        break
            break
    return schools


def _post_fill_corrections(
    output_path: Path,
    resume: TailoredResume,
) -> None:
    """Fix unreplaced placeholders after LLM fill.

    Scans the filled HWPX for known placeholder patterns ((한글), (영문),
    school type labels like '대학교') and replaces them with actual data
    from the resume.  This is a safety net for LLM non-determinism.
    """
    personal = _extract_personal_data(resume)
    schools = _extract_school_names(resume)

    if not personal and not schools:
        return

    _require_hwpx()
    doc = HwpxDocument.open(str(output_path))
    try:
        corrections = 0
        tables = []
        for para in doc.paragraphs:
            if hasattr(para, "tables"):
                tables.extend(para.tables)

        for table in tables:
            trs = table.element.findall(f"{_HP}tr")
            for tr in trs:
                tcs = tr.findall(f"{_HP}tc")
                for tc in tcs:
                    # Extract current text from TC
                    texts = []
                    for t_el in tc.iter(f"{_HP}t"):
                        if t_el.text:
                            texts.append(t_el.text)
                    text = " ".join(texts).strip()
                    if not text:
                        continue

                    new_text = None

                    # Check name placeholders: exact match
                    if text in _NAME_PLACEHOLDERS and text in personal:
                        new_text = personal[text]

                    # Check school type labels: exact match
                    if text in _SCHOOL_TYPE_LABELS and text in schools:
                        new_text = schools[text]

                    if new_text and new_text != text:
                        _set_tc_text(tc, new_text, table=table)
                        corrections += 1
                        logger.info(
                            "Post-fill correction: '%s' -> '%s'",
                            text, new_text,
                        )

        if corrections:
            doc.save_to_path(str(output_path))
            logger.info("Post-fill: %d placeholder(s) corrected", corrections)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Public API — smart fill with LLM
# ---------------------------------------------------------------------------


async def smart_fill_hwpx(
    template_path: str | Path,
    resume: TailoredResume,
    output_path: str | Path,
    llm: "LLMClient",  # noqa: F821
    max_attempts: int = 3,
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

    # Remap grid-column indices to TC indices before validation
    plan = _remap_plan_cols(structure, plan)

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
            # Remap again after retry
            plan = _remap_plan_cols(structure, plan)

    if errors:
        logger.warning(
            "Proceeding with %d validation errors after %d attempts",
            len(errors), max_attempts,
        )

    result = execute_hwpx_fill_plan(template_path, plan, output_path)

    # Post-fill: fix unreplaced placeholders ((한글), 대학교, etc.)
    try:
        _post_fill_corrections(result, resume)
    except Exception:
        logger.warning("Post-fill corrections failed", exc_info=True)

    return result


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


def _strip_md(text: str, *, strip_emoji: bool = False) -> str:
    """Strip markdown formatting, optionally removing emoji."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)
    if strip_emoji:
        text = re.sub(EMOJI_PATTERN, "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _md_to_plain(md: str) -> str:
    """Convert simple markdown to plain text for HWPX embedding."""
    return _strip_md(md, strip_emoji=True)
