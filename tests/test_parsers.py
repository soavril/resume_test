"""Tests for resume and JD parsers."""

from pathlib import Path

import pytest

from resume_tailor.parsers.jd_parser import load_jd_file, parse_jd
from resume_tailor.parsers.resume_parser import parse_resume


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
