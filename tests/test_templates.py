"""Tests for template loading and rendering."""

import pytest

from resume_tailor.templates.loader import (
    ResumeTemplate,
    TemplateField,
    list_templates,
    load_template,
)
from resume_tailor.templates.renderer import render_to_html, save_html


class TestTemplateLoader:
    def test_load_korean_standard(self):
        template = load_template("korean_standard")
        assert template.name == "한국 표준 이력서"
        assert len(template.sections) >= 4
        section_ids = [s.id for s in template.sections]
        assert "header" in section_ids
        assert "experience" in section_ids

    def test_load_korean_developer(self):
        template = load_template("korean_developer")
        assert template.name == "한국 개발자 이력서"
        section_ids = [s.id for s in template.sections]
        assert "skills" in section_ids
        assert "projects" in section_ids

    def test_load_nonexistent(self):
        with pytest.raises(FileNotFoundError, match="Template not found"):
            load_template("nonexistent")

    def test_list_templates(self):
        names = list_templates()
        assert "korean_standard" in names
        assert "korean_developer" in names

    def test_template_field_model(self):
        field = TemplateField(
            id="test",
            label="테스트",
            required=True,
            max_length=500,
            content_type="paragraph",
        )
        assert field.id == "test"
        assert field.max_length == 500

    def test_template_required_sections(self):
        template = load_template("korean_standard")
        required = [s for s in template.sections if s.required]
        assert len(required) >= 4


class TestRenderer:
    def test_render_to_html(self):
        html = render_to_html("<h1>홍길동</h1>", title="테스트 이력서")
        assert "<h1>홍길동</h1>" in html
        assert "테스트 이력서" in html
        assert "Pretendard" in html

    def test_save_html(self, tmp_path):
        html_content = "<html><body>Test</body></html>"
        path = save_html(html_content, str(tmp_path / "output" / "test.html"))
        assert path.exists()
        assert path.read_text() == html_content

    def test_save_html_creates_dirs(self, tmp_path):
        path = save_html("test", str(tmp_path / "a" / "b" / "c.html"))
        assert path.exists()
