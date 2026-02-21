from __future__ import annotations

import logging
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

logger = logging.getLogger(__name__)

CSS_THEMES_DIR = Path(__file__).parent / "css_themes"
BASE_TEMPLATE_DIR = Path(__file__).parent

AVAILABLE_THEMES = ("professional", "modern", "minimal")


def render_pdf(
    resume_markdown: str,
    theme: str = "professional",
    title: str = "Resume",
) -> bytes:
    """Convert resume markdown to PDF bytes."""
    if theme not in AVAILABLE_THEMES:
        theme = "professional"
    html = _md_to_styled_html(resume_markdown, theme, title)
    return _html_to_pdf(html)


def render_html_preview(
    resume_markdown: str,
    theme: str = "professional",
    title: str = "Resume",
) -> str:
    """Convert resume markdown to themed HTML string (for preview)."""
    if theme not in AVAILABLE_THEMES:
        theme = "professional"
    return _md_to_styled_html(resume_markdown, theme, title)


def _md_to_styled_html(md_text: str, theme: str, title: str) -> str:
    """Convert markdown to themed HTML."""
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    css_path = CSS_THEMES_DIR / f"{theme}.css"
    css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    env = Environment(
        loader=FileSystemLoader(str(BASE_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("base.html")
    return template.render(title=title, css=Markup(css), body=Markup(html_body))


def _html_to_pdf(html: str) -> bytes:
    """Convert HTML string to PDF bytes using WeasyPrint, with fpdf2 fallback."""
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except (ImportError, OSError):
        logger.warning("WeasyPrint not available, using fpdf2 fallback")
        from resume_tailor.export.pdf_fallback import html_to_pdf_fpdf2
        return html_to_pdf_fpdf2(html)
