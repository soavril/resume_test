"""Tests for hwpx_filler.py — extract_hwpx_structure, list_hwpx_placeholders,
fill_hwpx_template, execute_hwpx_fill_plan, and _md_to_plain."""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpx.document import HwpxDocument

from resume_tailor.templates.hwpx_filler import (
    _md_to_plain,
    execute_hwpx_fill_plan,
    extract_hwpx_structure,
    fill_hwpx_template,
    list_hwpx_placeholders,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_hwpx_paragraphs(path: Path, texts: list[str]) -> Path:
    """Create a HWPX with only paragraphs."""
    doc = HwpxDocument.new()
    for text in texts:
        doc.add_paragraph(text)
    doc.save_to_path(str(path))
    doc.close()
    return path


def _create_hwpx_with_table(
    path: Path,
    rows: int = 3,
    cols: int = 3,
    headers: list[str] | None = None,
) -> Path:
    """Create a HWPX with one paragraph and one table."""
    doc = HwpxDocument.new()
    doc.add_paragraph("Test Document")
    table = doc.add_table(rows=rows, cols=cols)
    if headers:
        for i, h in enumerate(headers):
            if i < cols:
                table.set_cell_text(0, i, h)
    doc.save_to_path(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
# extract_hwpx_structure tests
# ---------------------------------------------------------------------------

class TestExtractHwpxStructure:
    def test_extract_paragraphs_count(self, tmp_path):
        """Structure contains one entry per non-empty paragraph."""
        path = tmp_path / "doc.hwpx"
        _create_hwpx_paragraphs(path, ["첫 번째 문단", "두 번째 문단"])

        structure = extract_hwpx_structure(path)

        assert len(structure["paragraphs"]) == 2

    def test_extract_paragraphs_text(self, tmp_path):
        """Paragraph entries contain the original text."""
        path = tmp_path / "doc.hwpx"
        _create_hwpx_paragraphs(path, ["안녕하세요"])

        structure = extract_hwpx_structure(path)

        assert structure["paragraphs"][0]["text"] == "안녕하세요"

    def test_extract_table_count(self, tmp_path):
        """Structure contains exactly one table when the HWPX has one table."""
        path = tmp_path / "doc.hwpx"
        _create_hwpx_with_table(path, rows=3, cols=3)

        structure = extract_hwpx_structure(path)

        assert len(structure["tables"]) == 1

    def test_extract_table_dimensions(self, tmp_path):
        """Table entry reports the correct row and column counts."""
        path = tmp_path / "doc.hwpx"
        _create_hwpx_with_table(path, rows=4, cols=2)

        structure = extract_hwpx_structure(path)
        table_info = structure["tables"][0]

        assert table_info["rows"] == 4
        assert table_info["cols"] == 2

    def test_extract_structure_keys(self, tmp_path):
        """Top-level structure always has 'paragraphs' and 'tables' keys."""
        path = tmp_path / "doc.hwpx"
        _create_hwpx_paragraphs(path, ["text"])

        structure = extract_hwpx_structure(path)

        assert "paragraphs" in structure
        assert "tables" in structure


# ---------------------------------------------------------------------------
# list_hwpx_placeholders tests
# ---------------------------------------------------------------------------

class TestListHwpxPlaceholders:
    def test_finds_placeholders(self, tmp_path):
        """Placeholders {{이름}} and {{경력}} are detected and returned sorted."""
        tpl = tmp_path / "template.hwpx"
        _create_hwpx_paragraphs(tpl, ["안녕하세요 {{이름}}님", "경력: {{경력}}"])

        result = list_hwpx_placeholders(tpl)

        assert result == ["경력", "이름"]

    def test_empty_template(self, tmp_path):
        """Template with no placeholders returns an empty list."""
        tpl = tmp_path / "empty.hwpx"
        _create_hwpx_paragraphs(tpl, ["No placeholders here.", "Plain text."])

        result = list_hwpx_placeholders(tpl)

        assert result == []

    def test_deduplicates(self, tmp_path):
        """The same placeholder appearing twice is returned only once."""
        tpl = tmp_path / "dup.hwpx"
        _create_hwpx_paragraphs(tpl, ["{{이름}} 위", "{{이름}} 아래"])

        result = list_hwpx_placeholders(tpl)

        assert result.count("이름") == 1

    def test_finds_placeholders_in_table_cells(self, tmp_path):
        """Placeholders inside table cells are detected."""
        tpl = tmp_path / "table_tpl.hwpx"
        doc = HwpxDocument.new()
        table = doc.add_table(2, 2)
        table.set_cell_text(0, 0, "{{이름}}")
        table.set_cell_text(0, 1, "{{직급}}")
        doc.save_to_path(str(tpl))
        doc.close()

        result = list_hwpx_placeholders(tpl)

        assert "이름" in result
        assert "직급" in result


# ---------------------------------------------------------------------------
# fill_hwpx_template tests
# ---------------------------------------------------------------------------

class TestFillHwpxTemplate:
    def test_replaces_section_by_id(self, tmp_path, sample_tailored_resume):
        """{{summary}} placeholder is replaced with the summary section content."""
        tpl = tmp_path / "tpl.hwpx"
        _create_hwpx_paragraphs(tpl, ["자기소개: {{summary}}"])

        out = tmp_path / "filled.hwpx"
        fill_hwpx_template(tpl, sample_tailored_resume, out)

        doc = HwpxDocument.open(str(out))
        all_text = " ".join(p.text or "" for p in doc.paragraphs)
        doc.close()
        assert "{{summary}}" not in all_text
        assert "대규모 트래픽" in all_text

    def test_with_extra_vars(self, tmp_path, sample_tailored_resume):
        """extra_vars dict values replace matching {{placeholder}} markers."""
        tpl = tmp_path / "tpl.hwpx"
        _create_hwpx_paragraphs(tpl, ["커스텀 필드: {{custom_field}}"])

        out = tmp_path / "filled.hwpx"
        fill_hwpx_template(
            tpl, sample_tailored_resume, out,
            extra_vars={"custom_field": "특별한 값"},
        )

        doc = HwpxDocument.open(str(out))
        all_text = " ".join(p.text or "" for p in doc.paragraphs)
        doc.close()
        assert "{{custom_field}}" not in all_text
        assert "특별한 값" in all_text

    def test_returns_output_path(self, tmp_path, sample_tailored_resume):
        """fill_hwpx_template returns the output path as a Path object."""
        tpl = tmp_path / "tpl.hwpx"
        _create_hwpx_paragraphs(tpl, ["{{summary}}"])

        out = tmp_path / "filled.hwpx"
        result = fill_hwpx_template(tpl, sample_tailored_resume, out)

        assert isinstance(result, Path)
        assert result == out


# ---------------------------------------------------------------------------
# execute_hwpx_fill_plan tests
# ---------------------------------------------------------------------------

class TestExecuteHwpxFillPlan:
    def test_fills_table_cell(self, tmp_path):
        """execute_hwpx_fill_plan writes the specified value into the correct cell."""
        src = tmp_path / "template.hwpx"
        _create_hwpx_with_table(src, rows=3, cols=3, headers=["A", "B", "C"])

        out = tmp_path / "filled.hwpx"
        plan = {
            "fill_plan": [
                {
                    "target": "table",
                    "table_idx": 0,
                    "row": 1,
                    "fills": [{"col": 0, "value": "채워진값"}],
                }
            ]
        }

        result = execute_hwpx_fill_plan(src, plan, out)

        assert out.exists()
        doc = HwpxDocument.open(str(out))
        tables = []
        for p in doc.paragraphs:
            if hasattr(p, "tables"):
                tables.extend(p.tables)
        cell_text = tables[0].cell(1, 0).text
        doc.close()
        assert "채워진값" in cell_text

    def test_returns_output_path(self, tmp_path):
        """execute_hwpx_fill_plan returns a Path pointing to the output file."""
        src = tmp_path / "template.hwpx"
        _create_hwpx_with_table(src, rows=2, cols=2)

        out = tmp_path / "filled.hwpx"
        plan = {"fill_plan": []}

        result = execute_hwpx_fill_plan(src, plan, out)

        assert isinstance(result, Path)
        assert result == out


# ---------------------------------------------------------------------------
# _md_to_plain tests
# ---------------------------------------------------------------------------

class TestMdToPlain:
    def test_strips_headers(self):
        result = _md_to_plain("## Title\nText")
        assert result == "Title\nText"

    def test_strips_bold(self):
        result = _md_to_plain("**bold** text")
        assert result == "bold text"

    def test_strips_links(self):
        result = _md_to_plain("[홈페이지](https://example.com)")
        assert result == "홈페이지"

    def test_strips_horizontal_rule(self):
        result = _md_to_plain("line one\n---\nline two")
        assert "---" not in result

    def test_plain_text_unchanged(self):
        plain = "일반 텍스트 내용입니다."
        result = _md_to_plain(plain)
        assert result == plain
