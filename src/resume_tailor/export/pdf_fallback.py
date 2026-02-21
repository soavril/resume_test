"""Fallback PDF renderer using fpdf2 (pure Python, no system deps)."""

from __future__ import annotations

import html
import logging
import re
from io import BytesIO
from pathlib import Path

from fpdf import FPDF

logger = logging.getLogger(__name__)

# Korean-capable font search paths (macOS, Linux, Windows)
_KOREAN_FONT_PATHS = [
    # macOS
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    # Linux (apt install fonts-nanum)
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    # Linux (apt install fonts-noto-cjk)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    # Windows
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/gulim.ttc",
]


def _find_korean_font() -> str | None:
    """Search for a Korean-capable TTF/TTC font on the system."""
    for path in _KOREAN_FONT_PATHS:
        if Path(path).exists() and (path.endswith(".ttf") or path.endswith(".ttc")):
            return path
    return None


def html_to_pdf_fpdf2(html_content: str) -> bytes:
    """Fallback PDF generation using fpdf2 when WeasyPrint is unavailable."""
    body_match = re.search(r"<body>(.*?)</body>", html_content, re.DOTALL)
    body = body_match.group(1) if body_match else html_content

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Try to load a Korean-capable font
    font_name = "Helvetica"
    korean_font = _find_korean_font()
    if korean_font:
        try:
            pdf.add_font("KoreanFont", "", korean_font)
            font_name = "KoreanFont"
        except Exception:
            logger.debug("Failed to load Korean font %s", korean_font)

    pdf.set_font(font_name, size=10)

    lines = _parse_html_to_lines(body)
    for line_type, text in lines:
        safe_text = _safe_text(text, pdf)
        try:
            if line_type == "h1":
                pdf.set_font_size(16)
                pdf.multi_cell(0, 10, safe_text)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                pdf.ln(3)
                pdf.set_font_size(10)
            elif line_type == "h2":
                pdf.ln(3)
                pdf.set_font_size(13)
                pdf.multi_cell(0, 8, safe_text)
                pdf.ln(2)
                pdf.set_font_size(10)
            elif line_type == "h3":
                pdf.ln(2)
                pdf.set_font_size(11)
                pdf.multi_cell(0, 7, safe_text)
                pdf.set_font_size(10)
            elif line_type == "bullet":
                pdf.multi_cell(0, 6, f"  - {safe_text}")
            elif line_type == "text" and safe_text.strip():
                pdf.multi_cell(0, 6, safe_text)
            elif line_type == "break":
                pdf.ln(3)
        except Exception:
            logger.debug("Failed to render line: %s %s", line_type, safe_text[:30])

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def _safe_text(text: str, pdf: FPDF) -> str:
    """Ensure text is encodable by the current font. Replace if needed."""
    if pdf.is_ttf_font:
        return text
    # For built-in fonts (Helvetica etc.), strip non-latin chars
    try:
        text.encode("latin-1")
        return text
    except UnicodeEncodeError:
        return text.encode("latin-1", errors="replace").decode("latin-1")


def _parse_html_to_lines(body_html: str) -> list[tuple[str, str]]:
    """Parse simple HTML into (type, text) pairs."""
    lines: list[tuple[str, str]] = []
    parts = re.split(r"(</?(?:h[1-3]|p|li|ul|ol|br\s*/?)>)", body_html)
    current_tag = "text"
    for part in parts:
        part = part.strip()
        if not part:
            continue
        tag_match = re.match(r"<(/?)(h[1-3]|p|li|ul|ol|br\s*/?)>", part)
        if tag_match:
            closing = tag_match.group(1) == "/"
            tag = tag_match.group(2).rstrip("/").strip()
            if closing:
                if tag in ("ul", "ol"):
                    lines.append(("break", ""))
                current_tag = "text"
            else:
                if tag in ("h1", "h2", "h3"):
                    current_tag = tag
                elif tag == "li":
                    current_tag = "bullet"
                elif tag in ("br", "br /"):
                    lines.append(("break", ""))
                elif tag == "p":
                    current_tag = "text"
        else:
            text = _strip_html(part)
            if text:
                lines.append((current_tag, text))
    return lines


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
