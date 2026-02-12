"""LLM-based smart DOCX filler — handles any template structure.

Pipeline:
  1. Extract DOCX structure → compact JSON description
  2. LLM analyzes structure + resume → produces fill_plan
  3. Execute fill_plan on the DOCX
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from docx import Document
from docx.shared import Pt

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.resume import TailoredResume
from resume_tailor.utils.json_parser import extract_json

# ---------------------------------------------------------------------------
# Step 1: Extract DOCX structure
# ---------------------------------------------------------------------------


def extract_docx_structure(path: str | Path) -> dict:
    """Parse a DOCX file into a compact JSON structure description.

    Returns a dict like:
    {
      "paragraphs": [
        {"idx": 0, "style": "Heading 1", "text": "경력기술서"}
      ],
      "tables": [
        {
          "idx": 0,
          "rows": 8, "cols": 8,
          "cells": [
            {"row": 0, "col": 0, "text": "근무기간", "merged_cols": 7},
            {"row": 2, "col": 0, "text": "", "empty": true},
            ...
          ]
        }
      ]
    }
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
                "text": text[:200],
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

        for ri, row in enumerate(table.rows):
            cells_info = []
            seen_ids = set()
            col_idx = 0

            for cell in row.cells:
                cid = id(cell._tc)
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)

                # Count how many column slots this cell spans
                span = sum(1 for c in row.cells if id(c._tc) == cid)

                text = cell.text.strip()
                cell_data = {
                    "col": col_idx,
                    "text": text[:100] if text else "",
                }
                if span > 1:
                    cell_data["span"] = span
                if not text:
                    cell_data["empty"] = True

                cells_info.append(cell_data)
                col_idx += span

            row_data = {"row": ri, "cells": cells_info}

            # Classify as header or data row
            all_empty = all(c.get("empty") for c in cells_info)
            if all_empty:
                table_info["data_rows"].append(row_data)
            elif any(not c.get("empty") for c in cells_info):
                # Could be header or partially filled
                if ri < 3 and not all_empty:
                    table_info["header_rows"].append(row_data)
                else:
                    table_info["data_rows"].append(row_data)

        structure["tables"].append(table_info)

    return structure


def format_structure_for_llm(structure: dict) -> str:
    """Format the DOCX structure into a compact readable string for the LLM."""
    parts = []

    if structure["paragraphs"]:
        parts.append("=== 문단 (테이블 외부) ===")
        for p in structure["paragraphs"]:
            parts.append(f"  P[{p['idx']}] ({p['style']}): \"{p['text']}\"")

    for t in structure["tables"]:
        parts.append(f"\n=== 표 {t['idx']} ({t['rows']}행 x {t['cols']}열) ===")

        if t["header_rows"]:
            parts.append("  헤더:")
            for hr in t["header_rows"]:
                cells_str = " | ".join(
                    f"[col{c['col']}" + (f",span{c['span']}" if c.get("span") else "") + f"] \"{c['text']}\""
                    for c in hr["cells"]
                )
                parts.append(f"    Row {hr['row']}: {cells_str}")

        empty_count = len(t["data_rows"])
        if empty_count:
            first = t["data_rows"][0]["row"]
            last = t["data_rows"][-1]["row"]
            parts.append(f"  빈 데이터 행: Row {first}~{last} ({empty_count}행)")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Step 2: LLM produces fill_plan
# ---------------------------------------------------------------------------

ANALYZER_SYSTEM = """\
당신은 DOCX 이력서 양식 분석 전문가입니다.

주어진 DOCX 구조와 이력서 내용을 분석하여, 양식의 어느 위치에 어떤 내용을 채워야 하는지 계획을 세웁니다.

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
}

fill_plan 규칙:
1. target "table": 표의 특정 셀에 값을 채웁니다. fills 배열에 col과 value를 지정합니다.
2. target "paragraph": 기존 문단을 교체(replace)하거나 뒤에 삽입(insert)합니다.
3. 빈 데이터 행에만 내용을 채우세요. 헤더 행은 수정하지 마세요.
4. 경력 항목은 최근부터 역순으로 배치합니다.
5. 표의 날짜 열 구조에 맞춰 년/월/일을 개별 셀에 넣으세요.
6. description 내용은 마크다운을 제거한 순수 텍스트로 작성하세요.
7. 이력서 원본에 있는 사실만 사용하세요."""


async def analyze_and_plan(
    llm: LLMClient,
    structure: dict,
    resume: TailoredResume,
) -> dict:
    """LLM analyzes DOCX structure and produces a fill plan."""
    structure_text = format_structure_for_llm(structure)

    prompt = f"""다음 DOCX 양식 구조를 분석하고, 이력서 내용을 채워넣을 계획을 세우세요.

## DOCX 양식 구조
{structure_text}

## 채울 이력서 내용
{resume.full_markdown}

양식의 구조를 정확히 파악한 뒤, 각 빈 칸에 어떤 내용을 넣을지 fill_plan JSON으로 응답하세요."""

    data = await llm.generate_json(
        prompt=prompt,
        system=ANALYZER_SYSTEM,
        model="claude-sonnet-4-5-20250929",
        max_tokens=8192,
    )
    return data


# ---------------------------------------------------------------------------
# Step 3: Execute fill_plan
# ---------------------------------------------------------------------------


def execute_fill_plan(doc_path: str | Path, plan: dict, output_path: str | Path) -> Path:
    """Execute a fill plan on a DOCX document."""
    doc_path = Path(doc_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document(str(doc_path))
    fills = plan.get("fill_plan", [])

    for item in fills:
        target = item.get("target")

        if target == "table":
            _execute_table_fill(doc, item)
        elif target == "paragraph":
            _execute_paragraph_fill(doc, item)

    doc.save(str(output_path))
    return output_path


def _execute_table_fill(doc: Document, item: dict) -> None:
    """Fill table cells according to the plan."""
    table_idx = item.get("table_idx", 0)
    row_idx = item.get("row")

    if table_idx >= len(doc.tables) or row_idx is None:
        return

    table = doc.tables[table_idx]

    # Add rows if needed
    while row_idx >= len(table.rows):
        _add_table_row(table)

    row = table.rows[row_idx]

    # Build a map from unique-cell-index to actual cell objects
    unique_cells = _get_unique_cells_with_col(row)

    for fill in item.get("fills", []):
        col = fill.get("col")
        value = str(fill.get("value", ""))
        if col is None or not value:
            continue

        cell = unique_cells.get(col)
        if cell:
            _set_cell_text(cell, _strip_md(value))


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
            # Insert a new paragraph after this one
            new_para = _insert_paragraph_after(para, value)


def _insert_paragraph_after(paragraph, text: str):
    """Insert a new paragraph after the given paragraph."""
    from docx.oxml.ns import qn
    from copy import deepcopy

    new_p = deepcopy(paragraph._p)
    # Clear content
    for child in list(new_p):
        if child.tag.endswith("}r"):
            new_p.remove(child)

    paragraph._p.addnext(new_p)

    # Add text run
    from docx.oxml import OxmlElement
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
    """Get a {col_index: cell} mapping of unique cells in a row."""
    result = {}
    seen = set()
    col_idx = 0
    for cell in row.cells:
        cid = id(cell._tc)
        if cid not in seen:
            seen.add(cid)
            result[col_idx] = cell
        col_idx += 1
    return result


def _set_cell_text(cell, text: str, font_size: int = 10) -> None:
    """Set cell text, preserving existing formatting."""
    for para in cell.paragraphs:
        for run in para.runs:
            run.text = ""

    if cell.paragraphs:
        para = cell.paragraphs[0]
        if para.runs:
            para.runs[0].text = text
        else:
            run = para.add_run(text)
            run.font.size = Pt(font_size)
    else:
        cell.add_paragraph(text)


def _add_table_row(table) -> None:
    """Add a new row copying format from the last row."""
    from copy import deepcopy

    last_row = table.rows[-1]
    new_tr = deepcopy(last_row._tr)
    for tc in new_tr.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
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
# Public API
# ---------------------------------------------------------------------------


async def smart_fill_docx(
    template_path: str | Path,
    resume: TailoredResume,
    output_path: str | Path,
    llm: LLMClient,
) -> Path:
    """Analyze any DOCX template and intelligently fill it with resume data.

    1. Extract DOCX structure
    2. LLM analyzes structure + resume → fill_plan
    3. Execute fill_plan on the DOCX
    """
    structure = extract_docx_structure(template_path)
    plan = await analyze_and_plan(llm, structure, resume)
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
