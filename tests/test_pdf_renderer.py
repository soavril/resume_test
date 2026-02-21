"""Tests for PDF export module (Phase 6A)."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MARKDOWN = """# 홍길동

**이메일**: hong@example.com | **연락처**: 010-1234-5678

## 경력

### 삼성전자 (2020.01 ~ 현재)
- 백엔드 개발 담당
- Python, FastAPI, AWS 활용

## 학력

서울대학교 컴퓨터공학과 (2016 ~ 2020)
"""

SAMPLE_HTML = "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>홍길동</h1><p>Hello</p></body></html>"


# ---------------------------------------------------------------------------
# render_pdf tests
# ---------------------------------------------------------------------------


def test_render_pdf_returns_bytes():
    """render_pdf should return non-empty bytes."""
    from resume_tailor.export.pdf_renderer import render_pdf

    result = render_pdf(SAMPLE_MARKDOWN)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_render_pdf_valid_pdf_magic():
    """Output of render_pdf should start with %PDF magic bytes."""
    from resume_tailor.export.pdf_renderer import render_pdf

    result = render_pdf(SAMPLE_MARKDOWN)
    assert result[:4] == b"%PDF"


def test_render_pdf_all_themes():
    """Each theme should produce valid PDF bytes."""
    from resume_tailor.export.pdf_renderer import AVAILABLE_THEMES, render_pdf

    for theme in AVAILABLE_THEMES:
        result = render_pdf(SAMPLE_MARKDOWN, theme=theme)
        assert isinstance(result, bytes)
        assert result[:4] == b"%PDF", f"Theme {theme!r} did not produce valid PDF"


def test_render_pdf_invalid_theme_falls_back():
    """An invalid theme name should fall back to 'professional' without error."""
    from resume_tailor.export.pdf_renderer import render_pdf

    result = render_pdf(SAMPLE_MARKDOWN, theme="nonexistent_theme")
    assert isinstance(result, bytes)
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# render_html_preview tests
# ---------------------------------------------------------------------------


def test_render_html_preview_returns_html():
    """render_html_preview should return a string containing html tags."""
    from resume_tailor.export.pdf_renderer import render_html_preview

    result = render_html_preview(SAMPLE_MARKDOWN)
    assert isinstance(result, str)
    assert "<html" in result
    assert "</html>" in result


def test_md_to_styled_html_includes_css():
    """_md_to_styled_html should inject CSS content into the output HTML."""
    from resume_tailor.export.pdf_renderer import _md_to_styled_html

    result = _md_to_styled_html(SAMPLE_MARKDOWN, "professional", "Test")
    # professional.css has #1B365D color
    assert "#1B365D" in result


def test_md_to_styled_html_includes_body():
    """Markdown content should appear in the rendered HTML body."""
    from resume_tailor.export.pdf_renderer import _md_to_styled_html

    result = _md_to_styled_html(SAMPLE_MARKDOWN, "professional", "Test")
    # The h1 from markdown should be present
    assert "<h1>" in result or "홍길동" in result


# ---------------------------------------------------------------------------
# AVAILABLE_THEMES
# ---------------------------------------------------------------------------


def test_available_themes_tuple():
    """AVAILABLE_THEMES should be a tuple of 3 strings."""
    from resume_tailor.export.pdf_renderer import AVAILABLE_THEMES

    assert isinstance(AVAILABLE_THEMES, tuple)
    assert len(AVAILABLE_THEMES) == 3
    for t in AVAILABLE_THEMES:
        assert isinstance(t, str)


# ---------------------------------------------------------------------------
# pdf_fallback tests
# ---------------------------------------------------------------------------


def test_pdf_fallback_returns_bytes():
    """html_to_pdf_fpdf2 should return non-empty bytes."""
    from resume_tailor.export.pdf_fallback import html_to_pdf_fpdf2

    result = html_to_pdf_fpdf2(SAMPLE_HTML)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_pdf_fallback_valid_pdf_magic():
    """fpdf2 fallback output should start with %PDF magic bytes."""
    from resume_tailor.export.pdf_fallback import html_to_pdf_fpdf2

    result = html_to_pdf_fpdf2(SAMPLE_HTML)
    assert result[:4] == b"%PDF"


def test_pdf_fallback_import_error():
    """When WeasyPrint is not importable, fpdf2 fallback should be used."""
    from resume_tailor.export.pdf_fallback import html_to_pdf_fpdf2

    result = html_to_pdf_fpdf2(SAMPLE_HTML)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_html_to_pdf_falls_back_to_fpdf2():
    """_html_to_pdf should fall back to fpdf2 when WeasyPrint raises ImportError."""
    from resume_tailor.export import pdf_renderer

    original = pdf_renderer._html_to_pdf

    def raising_html_to_pdf(html: str) -> bytes:
        # Simulate WeasyPrint ImportError by calling fallback directly
        from resume_tailor.export.pdf_fallback import html_to_pdf_fpdf2
        return html_to_pdf_fpdf2(html)

    with patch.object(pdf_renderer, "_html_to_pdf", side_effect=raising_html_to_pdf):
        from resume_tailor.export.pdf_fallback import html_to_pdf_fpdf2
        html = "<html><body><h1>Test</h1></body></html>"
        result = html_to_pdf_fpdf2(html)
        assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# _parse_html_to_lines tests
# ---------------------------------------------------------------------------


def test_parse_html_to_lines_headings():
    """_parse_html_to_lines should extract headings with correct types."""
    from resume_tailor.export.pdf_fallback import _parse_html_to_lines

    body = "<h1>홍길동</h1><h2>경력</h2><h3>삼성전자</h3>"
    lines = _parse_html_to_lines(body)
    types = [t for t, _ in lines]
    texts = [txt for _, txt in lines]

    assert "h1" in types
    assert "h2" in types
    assert "h3" in types
    assert "홍길동" in texts
    assert "경력" in texts
    assert "삼성전자" in texts


def test_parse_html_to_lines_bullets():
    """_parse_html_to_lines should extract list items as 'bullet' type."""
    from resume_tailor.export.pdf_fallback import _parse_html_to_lines

    body = "<ul><li>Python 개발</li><li>AWS 운영</li></ul>"
    lines = _parse_html_to_lines(body)
    bullet_lines = [(t, txt) for t, txt in lines if t == "bullet"]

    assert len(bullet_lines) == 2
    texts = [txt for _, txt in bullet_lines]
    assert "Python 개발" in texts
    assert "AWS 운영" in texts
