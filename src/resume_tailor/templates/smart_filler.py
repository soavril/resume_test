"""LLM-based smart DOCX filler — handles any template structure.

Pipeline:
  1. Extract DOCX structure → compact JSON description
  2. LLM analyzes structure + resume → produces fill_plan
  3. Validate fill_plan against actual structure
  4. Retry with error feedback if validation fails
  5. Execute fill_plan on the DOCX
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.resume import TailoredResume
from resume_tailor.utils.json_parser import extract_json

logger = logging.getLogger(__name__)

MAX_ADD_ROWS = 20

# ---------------------------------------------------------------------------
# Step 1: Extract DOCX structure
# ---------------------------------------------------------------------------


def extract_docx_structure(path: str | Path) -> dict:
    """Parse a DOCX file into a compact JSON structure description.

    Uses sequential unique-cell indices (0, 1, 2, ...) for consistency
    between extraction and execution. Each cell includes a column header
    mapping to help the LLM understand the table layout.
    """
    doc = Document(str(path))
    structure: dict = {"paragraphs": [], "tables": []}

    # Paragraphs (outside tables)
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if text:
            structure["paragraphs"].append({
                "idx": i,
                "style": para.style.name,
                "text": text[:300],
            })

    # Tables
    for ti, table in enumerate(doc.tables):
        table_info: dict = {
            "idx": ti,
            "rows": len(table.rows),
            "cols": len(table.columns),
            "header_rows": [],
            "data_rows": [],
        }

        # First pass: collect all rows to detect headers intelligently
        all_rows_data = []
        for ri, row in enumerate(table.rows):
            cells_info = []
            seen_ids = set()
            unique_idx = 0

            for cell in row.cells:
                cid = id(cell._tc)
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)

                # Count how many column slots this cell spans
                span = sum(1 for c in row.cells if id(c._tc) == cid)

                text = cell.text.strip()
                cell_data = {
                    "col": unique_idx,
                    "text": text[:300] if text else "",
                }
                if span > 1:
                    cell_data["span"] = span
                if not text:
                    cell_data["empty"] = True

                cells_info.append(cell_data)
                unique_idx += 1

            all_rows_data.append({"row": ri, "cells": cells_info})

        # Second pass: classify rows as header or data
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

    return structure


def _is_header_row(ri: int, cells: list[dict], all_rows: list[dict]) -> bool:
    """Detect header rows using content patterns rather than position alone.

    A row is a header if:
    - It's in the first 2 rows, OR
    - It has mostly non-empty cells and the next row has mostly empty cells
      (section header pattern), OR
    - Its cell texts look like field labels (short, no digits, common keywords)
    """
    non_empty = [c for c in cells if not c.get("empty")]
    non_empty_ratio = len(non_empty) / max(len(cells), 1)

    # First 2 rows with content are almost always headers
    if ri < 2 and non_empty_ratio > 0.3:
        return True

    # Check if this looks like a section header (most cells filled with labels)
    if non_empty_ratio >= 0.5:
        label_keywords = {"기간", "근무", "회사", "직위", "직급", "담당", "업무",
                          "학교", "학력", "전공", "기술", "자격", "수상", "어학",
                          "년", "월", "일", "시작", "종료", "성명", "생년월일",
                          "주소", "연락처", "이메일", "성별"}
        label_like = sum(
            1 for c in non_empty
            if any(kw in c["text"] for kw in label_keywords)
        )
        if label_like >= 2:
            return True

        # Check if next row is mostly empty (header → data pattern)
        if ri + 1 < len(all_rows):
            next_cells = all_rows[ri + 1]["cells"]
            next_empty_ratio = sum(
                1 for c in next_cells if c.get("empty")
            ) / max(len(next_cells), 1)
            if next_empty_ratio >= 0.5 and non_empty_ratio >= 0.6:
                return True

    return False


def _build_column_header_map(table_info: dict) -> dict[int, str]:
    """Build a mapping from column index to header text.

    Traverses header rows to find what each column represents.
    Returns {col_idx: "header text"} for columns that have headers.
    """
    col_headers: dict[int, str] = {}
    for hr in table_info["header_rows"]:
        for cell in hr["cells"]:
            col = cell["col"]
            text = cell.get("text", "").strip()
            if text and col not in col_headers:
                col_headers[col] = text
    return col_headers


def format_structure_for_llm(structure: dict) -> str:
    """Format the DOCX structure into a compact readable string for the LLM.

    Includes column-header mapping for each table to help the LLM
    understand what each column represents.
    """
    parts = []

    if structure["paragraphs"]:
        parts.append("=== 문단 (테이블 외부) ===")
        for p in structure["paragraphs"]:
            parts.append(f"  P[{p['idx']}] ({p['style']}): \"{p['text']}\"")

    for t in structure["tables"]:
        parts.append(f"\n=== 표 {t['idx']} ({t['rows']}행 x {t['cols']}열) ===")

        # Column-header mapping
        col_headers = _build_column_header_map(t)
        if col_headers:
            parts.append("  열-헤더 매핑:")
            for col_idx in sorted(col_headers.keys()):
                parts.append(f"    col{col_idx}: \"{col_headers[col_idx]}\"")

        if t["header_rows"]:
            parts.append("  헤더 행:")
            for hr in t["header_rows"]:
                cells_str = " | ".join(
                    f"[col{c['col']}"
                    + (f",span{c['span']}" if c.get("span") else "")
                    + f"] \"{c['text']}\""
                    for c in hr["cells"]
                )
                parts.append(f"    Row {hr['row']}: {cells_str}")

        if t["data_rows"]:
            empty_rows = [r for r in t["data_rows"]
                          if all(c.get("empty") for c in r["cells"])]
            filled_rows = [r for r in t["data_rows"]
                           if not all(c.get("empty") for c in r["cells"])]

            if filled_rows:
                parts.append("  채워진 데이터 행:")
                for fr in filled_rows:
                    cells_str = " | ".join(
                        f"[col{c['col']}] \"{c['text']}\""
                        for c in fr["cells"]
                        if not c.get("empty")
                    )
                    parts.append(f"    Row {fr['row']}: {cells_str}")

            if empty_rows:
                first = empty_rows[0]["row"]
                last = empty_rows[-1]["row"]
                # Show column structure from the first empty row
                first_cells = empty_rows[0]["cells"]
                col_count = len(first_cells)
                parts.append(
                    f"  빈 데이터 행: Row {first}~{last} "
                    f"({len(empty_rows)}행, 각 {col_count}열)"
                )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Step 2: LLM produces fill_plan
# ---------------------------------------------------------------------------

ANALYZER_SYSTEM = """\
당신은 DOCX 이력서 양식 분석 전문가입니다.

주어진 DOCX 구조와 이력서 내용을 분석하여, 양식의 어느 위치에 어떤 내용을 채워야 하는지 계획을 세웁니다.

## 중요 규칙

1. **col 인덱스는 고유 셀 순번입니다.** 표의 열-헤더 매핑을 반드시 참고하여 올바른 col에 값을 넣으세요.
2. **병합된 셀**: span이 표시된 셀은 여러 열을 차지합니다. 하나의 col 인덱스로만 참조하세요.
3. **헤더 행 수정 금지**: header_rows로 표시된 행은 절대 수정하지 마세요.
4. **빈 데이터 행에만** 내용을 채우세요.
5. 경력 항목은 **최근부터 역순**으로 배치합니다.
6. 날짜 열: 년/월/일이 개별 열이면 각각 분리해서 넣으세요.
7. 줄바꿈이 필요한 경우 \\n을 사용하세요 (실제 줄바꿈으로 변환됩니다).
8. 마크다운 서식(**, #, - 등)을 제거한 순수 텍스트로 작성하세요.
9. 이력서 원본에 있는 **사실만** 사용하세요.

## 예시

다음과 같은 한국 경력기술서 표 구조가 있을 때:

```
=== 표 0 (10행 x 8열) ===
  열-헤더 매핑:
    col0: "근무기간"
    col1: "근무기간"
    col2: "회사명"
    col3: "부서/직급"
    col4: "담당업무"
  헤더 행:
    Row 0: [col0,span2] "근무기간" | [col2] "회사명" | [col3] "부서/직급" | [col4] "담당업무"
    Row 1: [col0] "시작" | [col1] "종료" | [col2] "" | [col3] "" | [col4] ""
  빈 데이터 행: Row 2~9 (8행, 각 5열)
```

올바른 fill_plan:
```json
{
  "analysis": "경력기술서 표. 5열 구조: 시작일, 종료일, 회사명, 부서/직급, 담당업무.",
  "fill_plan": [
    {
      "target": "table",
      "table_idx": 0,
      "row": 2,
      "fills": [
        {"col": 0, "value": "2022.03"},
        {"col": 1, "value": "현재"},
        {"col": 2, "value": "삼성전자"},
        {"col": 3, "value": "개발팀/선임"},
        {"col": 4, "value": "백엔드 API 설계 및 개발\\n성능 최적화 30% 달성"}
      ]
    }
  ]
}
```

## 응답 형식

반드시 아래 JSON 형식으로 응답하세요:
{
  "analysis": "양식 구조에 대한 간단한 분석",
  "fill_plan": [
    {
      "target": "table",
      "table_idx": 0,
      "row": 2,
      "fills": [
        {"col": 0, "value": "2022"},
        {"col": 1, "value": "03"},
        {"col": 7, "value": "상세 내용..."}
      ]
    },
    {
      "target": "paragraph",
      "paragraph_idx": 3,
      "action": "replace",
      "value": "새 내용"
    },
    {
      "target": "paragraph",
      "after_paragraph_idx": 0,
      "action": "insert",
      "value": "추가할 내용"
    }
  ]
}"""


async def analyze_and_plan(
    llm: LLMClient,
    structure: dict,
    resume: TailoredResume,
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """LLM analyzes DOCX structure and produces a fill plan."""
    structure_text = format_structure_for_llm(structure)

    prompt = f"""다음 DOCX 양식 구조를 분석하고, 이력서 내용을 채워넣을 계획을 세우세요.

## DOCX 양식 구조
{structure_text}

## 채울 이력서 내용
{resume.full_markdown}

양식의 열-헤더 매핑을 정확히 참고하여, 각 빈 칸에 어떤 내용을 넣을지 fill_plan JSON으로 응답하세요.
col 인덱스는 고유 셀 순번(0부터 시작)입니다."""

    data = await llm.generate_json(
        prompt=prompt,
        system=ANALYZER_SYSTEM,
        model=model,
        max_tokens=8192,
    )
    return data


# ---------------------------------------------------------------------------
# Step 2.5: Validate fill_plan
# ---------------------------------------------------------------------------


def validate_fill_plan(structure: dict, plan: dict) -> list[str]:
    """Validate a fill_plan against the actual DOCX structure.

    Returns a list of error messages. Empty list means valid.
    """
    errors = []
    fills = plan.get("fill_plan", [])
    tables = structure.get("tables", [])
    paragraphs = structure.get("paragraphs", [])

    # Track which cells are targeted (detect duplicates)
    seen_cells: set[tuple[int, int, int]] = set()  # (table_idx, row, col)

    # Collect header rows per table for checking
    header_rows_by_table: dict[int, set[int]] = {}
    for t in tables:
        header_rows_by_table[t["idx"]] = {hr["row"] for hr in t["header_rows"]}

    # Collect valid column indices per table row
    valid_cols_by_row: dict[tuple[int, int], set[int]] = {}
    for t in tables:
        for row_data in t["header_rows"] + t["data_rows"]:
            key = (t["idx"], row_data["row"])
            valid_cols_by_row[key] = {c["col"] for c in row_data["cells"]}

    for i, item in enumerate(fills):
        target = item.get("target")

        if target == "table":
            table_idx = item.get("table_idx", 0)
            row = item.get("row")

            # Check table_idx range
            if table_idx >= len(tables):
                errors.append(
                    f"fill_plan[{i}]: table_idx={table_idx} 범위 초과 "
                    f"(표 {len(tables)}개)"
                )
                continue

            if row is None:
                errors.append(f"fill_plan[{i}]: row가 지정되지 않음")
                continue

            # Check if row is a header row
            if row in header_rows_by_table.get(table_idx, set()):
                errors.append(
                    f"fill_plan[{i}]: Row {row}은 헤더 행이므로 수정 불가"
                )
                continue

            # Check row range (allow adding rows up to MAX_ADD_ROWS beyond existing)
            table = tables[table_idx]
            max_row = table["rows"] + MAX_ADD_ROWS
            if row >= max_row:
                errors.append(
                    f"fill_plan[{i}]: row={row} 범위 초과 "
                    f"(표 행 수: {table['rows']}, 최대 추가: {MAX_ADD_ROWS})"
                )
                continue

            # Validate column indices in fills
            valid_cols = valid_cols_by_row.get((table_idx, row))
            for fill in item.get("fills", []):
                col = fill.get("col")
                if col is None:
                    continue

                # Check duplicate cell targeting
                cell_key = (table_idx, row, col)
                if cell_key in seen_cells:
                    errors.append(
                        f"fill_plan[{i}]: 표{table_idx} Row{row} col{col} "
                        f"중복 채우기 감지"
                    )
                seen_cells.add(cell_key)

                # Check col validity if we know the row structure
                if valid_cols is not None and col not in valid_cols:
                    errors.append(
                        f"fill_plan[{i}]: 표{table_idx} Row{row}에 "
                        f"col{col}이 존재하지 않음 "
                        f"(유효: {sorted(valid_cols)})"
                    )

        elif target == "paragraph":
            action = item.get("action", "replace")
            if action == "replace":
                idx = item.get("paragraph_idx")
                if idx is not None and idx >= len(paragraphs):
                    errors.append(
                        f"fill_plan[{i}]: paragraph_idx={idx} 범위 초과"
                    )
            elif action == "insert":
                after_idx = item.get("after_paragraph_idx")
                if after_idx is not None and after_idx >= len(paragraphs):
                    errors.append(
                        f"fill_plan[{i}]: after_paragraph_idx={after_idx} "
                        f"범위 초과"
                    )

    return errors


# ---------------------------------------------------------------------------
# Step 3: Execute fill_plan
# ---------------------------------------------------------------------------


def execute_fill_plan(
    doc_path: str | Path, plan: dict, output_path: str | Path,
) -> Path:
    """Execute a fill plan on a DOCX document."""
    doc_path = Path(doc_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document(str(doc_path))
    fills = plan.get("fill_plan", [])

    filled_count = 0
    failed_count = 0

    for item in fills:
        target = item.get("target")

        if target == "table":
            ok, fail = _execute_table_fill(doc, item)
            filled_count += ok
            failed_count += fail
        elif target == "paragraph":
            _execute_paragraph_fill(doc, item)
            filled_count += 1

    logger.info("DOCX fill complete: %d cells filled, %d failed",
                filled_count, failed_count)

    doc.save(str(output_path))
    return output_path


def _execute_table_fill(doc: Document, item: dict) -> tuple[int, int]:
    """Fill table cells according to the plan.

    Returns (filled_count, failed_count).
    """
    table_idx = item.get("table_idx", 0)
    row_idx = item.get("row")
    filled = 0
    failed = 0

    if table_idx >= len(doc.tables) or row_idx is None:
        return 0, 1

    table = doc.tables[table_idx]

    # Add rows if needed (with upper bound)
    rows_added = 0
    while row_idx >= len(table.rows) and rows_added < MAX_ADD_ROWS:
        _add_table_row(table)
        rows_added += 1

    if row_idx >= len(table.rows):
        logger.warning(
            "Row %d exceeds table size and MAX_ADD_ROWS (%d)", row_idx, MAX_ADD_ROWS
        )
        return 0, len(item.get("fills", []))

    row = table.rows[row_idx]

    # Build a map from unique-cell-index to actual cell objects
    # Uses SAME sequential indexing as extract_docx_structure
    unique_cells = _get_unique_cells_with_col(row)

    for fill in item.get("fills", []):
        col = fill.get("col")
        value = str(fill.get("value", ""))
        if col is None or not value:
            continue

        cell = unique_cells.get(col)
        if cell:
            _set_cell_text(cell, _strip_md(value))
            filled += 1
        else:
            logger.warning(
                "Table %d Row %d: col %d not found (valid: %s)",
                table_idx, row_idx, col, sorted(unique_cells.keys()),
            )
            failed += 1

    return filled, failed


def _execute_paragraph_fill(doc: Document, item: dict) -> None:
    """Replace or insert a paragraph."""
    action = item.get("action", "replace")
    value = _strip_md(str(item.get("value", "")))

    if action == "replace":
        idx = item.get("paragraph_idx")
        if idx is not None and idx < len(doc.paragraphs):
            para = doc.paragraphs[idx]
            # Clear and set
            for run in para.runs:
                run.text = ""
            if para.runs:
                para.runs[0].text = value
            else:
                para.add_run(value)

    elif action == "insert":
        after_idx = item.get("after_paragraph_idx")
        if after_idx is not None and after_idx < len(doc.paragraphs):
            para = doc.paragraphs[after_idx]
            _insert_paragraph_after(para, value)


def _insert_paragraph_after(paragraph, text: str):
    """Insert a new paragraph after the given paragraph."""
    from copy import deepcopy

    new_p = deepcopy(paragraph._p)
    # Clear content
    for child in list(new_p):
        if child.tag.endswith("}r"):
            new_p.remove(child)

    paragraph._p.addnext(new_p)

    # Add text run
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    new_p.append(r)

    return new_p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_unique_cells_with_col(row) -> dict:
    """Get a {col_index: cell} mapping of unique cells in a row.

    Uses sequential unique-cell indices (0, 1, 2, ...) matching
    the indexing in extract_docx_structure.
    """
    result = {}
    seen = set()
    unique_idx = 0
    for cell in row.cells:
        cid = id(cell._tc)
        if cid not in seen:
            seen.add(cid)
            result[unique_idx] = cell
            unique_idx += 1
    return result


def _set_cell_text(cell, text: str, font_size: int = 10) -> None:
    """Set cell text, preserving existing formatting.

    Handles multiline text by creating proper paragraph breaks.
    """
    # Capture existing format from first run
    existing_font_size = None
    existing_bold = None
    existing_font_name = None
    if cell.paragraphs and cell.paragraphs[0].runs:
        first_run = cell.paragraphs[0].runs[0]
        if first_run.font.size:
            existing_font_size = first_run.font.size
        existing_bold = first_run.font.bold
        existing_font_name = first_run.font.name

    # Clear all existing content
    for para in cell.paragraphs:
        for run in para.runs:
            run.text = ""

    # Split on \n for multiline support
    lines = text.split("\n")

    if cell.paragraphs:
        # Use first paragraph for first line
        para = cell.paragraphs[0]
        if para.runs:
            para.runs[0].text = lines[0]
        else:
            run = para.add_run(lines[0])
            _apply_font(run, existing_font_size, existing_bold,
                        existing_font_name, font_size)

        # Add additional paragraphs for remaining lines
        for line in lines[1:]:
            new_para = cell.add_paragraph()
            run = new_para.add_run(line)
            _apply_font(run, existing_font_size, existing_bold,
                        existing_font_name, font_size)
    else:
        # No existing paragraphs — create one
        para = cell.add_paragraph()
        run = para.add_run(lines[0])
        _apply_font(run, existing_font_size, existing_bold,
                    existing_font_name, font_size)
        for line in lines[1:]:
            new_para = cell.add_paragraph()
            run = new_para.add_run(line)
            _apply_font(run, existing_font_size, existing_bold,
                        existing_font_name, font_size)


def _apply_font(
    run, existing_size, existing_bold, existing_name, default_size: int,
) -> None:
    """Apply font formatting to a run, preferring existing style."""
    if existing_size:
        run.font.size = existing_size
    elif default_size:
        run.font.size = Pt(default_size)
    if existing_bold is not None:
        run.font.bold = existing_bold
    if existing_name:
        run.font.name = existing_name


def _add_table_row(table) -> None:
    """Add a new row copying format from the last row."""
    from copy import deepcopy

    last_row = table.rows[-1]
    new_tr = deepcopy(last_row._tr)
    for tc in new_tr.findall(
        ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    ):
        tc.text = ""
    table._tbl.append(new_tr)


def _strip_md(text: str) -> str:
    """Strip markdown formatting."""
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^-{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Step 4: Retry with validation errors
# ---------------------------------------------------------------------------


async def _retry_with_errors(
    llm: LLMClient,
    structure: dict,
    resume: TailoredResume,
    plan: dict,
    errors: list[str],
    model: str = "claude-sonnet-4-5-20250929",
) -> dict:
    """Ask LLM to fix the fill_plan based on validation errors."""
    structure_text = format_structure_for_llm(structure)
    errors_text = "\n".join(f"- {e}" for e in errors)

    prompt = f"""이전 fill_plan에 다음 오류가 발견되었습니다:

{errors_text}

## DOCX 양식 구조
{structure_text}

## 이전 fill_plan
{json.dumps(plan, ensure_ascii=False, indent=2)}

## 이력서 내용
{resume.full_markdown}

오류를 수정한 새로운 fill_plan JSON으로 응답하세요.
col 인덱스는 고유 셀 순번(0부터 시작)이며, 열-헤더 매핑을 참고하세요."""

    return await llm.generate_json(
        prompt=prompt,
        system=ANALYZER_SYSTEM,
        model=model,
        max_tokens=8192,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def smart_fill_docx(
    template_path: str | Path,
    resume: TailoredResume,
    output_path: str | Path,
    llm: LLMClient,
    max_attempts: int = 2,
    model: str = "claude-sonnet-4-5-20250929",
) -> Path:
    """Analyze any DOCX template and intelligently fill it with resume data.

    1. Extract DOCX structure
    2. LLM analyzes structure + resume → fill_plan
    3. Validate fill_plan
    4. Retry with error feedback if validation fails (up to max_attempts)
    5. Execute fill_plan on the DOCX
    """
    structure = extract_docx_structure(template_path)

    plan = await analyze_and_plan(llm, structure, resume, model=model)

    for attempt in range(max_attempts):
        errors = validate_fill_plan(structure, plan)
        if not errors:
            break
        logger.warning(
            "Fill plan validation failed (attempt %d/%d): %s",
            attempt + 1, max_attempts, errors,
        )
        if attempt < max_attempts - 1:
            plan = await _retry_with_errors(
                llm, structure, resume, plan, errors, model=model,
            )

    if errors:
        logger.warning("Proceeding with %d validation errors after "
                       "%d attempts", len(errors), max_attempts)

    return execute_fill_plan(template_path, plan, output_path)


def smart_fill_docx_sync(
    template_path: str | Path,
    resume: TailoredResume,
    output_path: str | Path,
    llm: LLMClient,
) -> Path:
    """Synchronous wrapper for smart_fill_docx."""
    return asyncio.run(
        smart_fill_docx(template_path, resume, output_path, llm)
    )
