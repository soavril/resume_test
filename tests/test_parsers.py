"""Tests for resume and JD parsers."""

from pathlib import Path

import pytest

from resume_tailor.parsers.jd_parser import load_jd_file, parse_jd
from resume_tailor.parsers.resume_parser import _clean_markdown, parse_resume


class TestJDParser:
    def test_parse_jd_cleans_whitespace(self):
        text = "  Hello   World  \n\n\n\nLine 2  "
        result = parse_jd(text)
        assert "   " not in result
        assert "\n\n\n" not in result

    def test_parse_jd_strips_lines(self):
        text = "  line 1  \n  line 2  "
        result = parse_jd(text)
        for line in result.splitlines():
            assert line == line.strip()

    def test_load_jd_file(self, tmp_path):
        jd_file = tmp_path / "test.txt"
        jd_file.write_text("테스트 채용공고\n\n요구사항: Python", encoding="utf-8")
        result = load_jd_file(str(jd_file))
        assert "테스트 채용공고" in result
        assert "Python" in result


class TestResumeParser:
    def test_parse_txt_file(self, tmp_path):
        txt_file = tmp_path / "resume.txt"
        txt_file.write_text("홍길동\n경력사항: ...", encoding="utf-8")
        result = parse_resume(str(txt_file))
        assert "홍길동" in result

    def test_parse_md_file(self, tmp_path):
        md_file = tmp_path / "resume.md"
        md_file.write_text("# 홍길동\n## 경력", encoding="utf-8")
        result = parse_resume(str(md_file))
        assert "홍길동" in result

    def test_unsupported_format(self, tmp_path):
        bad_file = tmp_path / "resume.xyz"
        bad_file.write_text("test")
        with pytest.raises(ValueError, match="Unsupported file format"):
            parse_resume(str(bad_file))


class TestCleanMarkdown:
    """Tests for Google Docs markdown cleanup."""

    def test_removes_emoji_icons(self):
        text = "📧이메일:test@example.com\n📞연락처:010-1234-5678\n📍주소:서울시"
        result = _clean_markdown(text)
        assert "📧" not in result
        assert "📞" not in result
        assert "📍" not in result
        assert "이메일:test@example.com" in result
        assert "연락처:010-1234-5678" in result

    def test_normalizes_whitespace(self):
        text = "제목\n\n\n\n\n본문  내용   여기\n\n\n\n끝"
        result = _clean_markdown(text)
        assert "\n\n\n" not in result
        assert "본문 내용 여기" in result

    def test_normalizes_bullets(self):
        text = "● 항목1\n•  항목2\n◆ 항목3\n*   항목4"
        result = _clean_markdown(text)
        assert "- 항목1" in result
        assert "- 항목2" in result
        assert "- 항목3" in result
        assert "- 항목4" in result
        assert "●" not in result
        assert "•" not in result

    def test_removes_unicode_artifacts(self):
        text = "\ufeffHello\u200bWorld\u200c테스트\u00ad끝"
        result = _clean_markdown(text)
        assert "\ufeff" not in result
        assert "\u200b" not in result
        assert "\u200c" not in result
        assert "\u00ad" not in result
        assert "HelloWorld테스트끝" in result

    def test_preserves_content(self):
        text = "# 최홍익\n\n비즈니스 전략 및 경영관리 전문가\n\n- 경력: 6년 2개월\n- 이메일: test@example.com"
        result = _clean_markdown(text)
        assert "# 최홍익" in result
        assert "비즈니스 전략 및 경영관리 전문가" in result
        assert "경력: 6년 2개월" in result
        assert "test@example.com" in result

    def test_parse_md_applies_cleanup(self, tmp_path):
        md_file = tmp_path / "resume.md"
        md_file.write_text(
            "📧이메일:test@test.com\n\n\n\n\n● 항목1\n•  항목2",
            encoding="utf-8",
        )
        result = parse_resume(str(md_file))
        assert "📧" not in result
        assert "\n\n\n" not in result
        assert "- 항목1" in result
        assert "- 항목2" in result
