"""Tests for form_parser: parse_text and _extract_char_limit."""

import pytest

from resume_tailor.parsers.form_parser import FormQuestion, _extract_char_limit, parse_text


class TestParseText:
    def test_parse_text_numbered(self):
        text = "1. 자기소개를 해주세요 (500자 이내)\n2. 지원동기를 작성해주세요 (1,000자 이내)"
        result = parse_text(text)
        assert len(result) == 2
        assert result[0].max_length == 500
        assert result[1].max_length == 1000

    def test_parse_text_with_counter(self):
        # Label must be >20 chars with a keyword to pass _parse_question_line,
        # then the counter line "0/1,000" on the next line sets max_length.
        text = "자기소개를 간략하게 작성해주세요 (본인의 강점 중심으로)\n0/1,000"
        result = parse_text(text)
        assert len(result) == 1
        assert result[0].max_length == 1000

    def test_parse_text_empty(self):
        result = parse_text("")
        assert result == []

    def test_parse_text_single_question(self):
        text = "1. 자기소개를 작성해주세요"
        result = parse_text(text)
        assert len(result) == 1

    def test_parse_text_question_mark(self):
        text = "지원동기가 무엇인가요?"
        result = parse_text(text)
        assert len(result) == 1
        assert result[0].label == "지원동기가 무엇인가요?"

    def test_parse_text_deduplicates(self):
        text = "지원동기가 무엇인가요?\n지원동기가 무엇인가요?"
        result = parse_text(text)
        assert len(result) == 1

    def test_parse_text_skips_counter_lines(self):
        text = "자기소개를 작성해주세요\n0/1,000\n지원동기가 무엇인가요?"
        result = parse_text(text)
        # counter line "0/1,000" should be consumed, not turned into a question
        labels = [q.label for q in result]
        assert not any("0/1,000" in l for l in labels)


class TestExtractCharLimit:
    def test_extract_char_limit_korean(self):
        assert _extract_char_limit("500자 이내") == 500

    def test_extract_char_limit_comma(self):
        assert _extract_char_limit("1,000자 내외") == 1000

    def test_extract_char_limit_max(self):
        assert _extract_char_limit("max 500") == 500

    def test_extract_char_limit_none(self):
        assert _extract_char_limit("no limit") is None

    def test_extract_char_limit_in_parens(self):
        assert _extract_char_limit("(1,000자 이내)") == 1000


class TestFormQuestionModel:
    def test_form_question_defaults(self):
        q = FormQuestion(label="자기소개를 해주세요")
        assert q.label == "자기소개를 해주세요"
        assert q.max_length is None
        assert q.field_type == "textarea"
        assert q.options is None
        assert q.section == ""

    def test_form_question_with_values(self):
        q = FormQuestion(
            label="지원동기",
            max_length=500,
            field_type="text",
            options=["A", "B"],
            section="자기소개서",
        )
        assert q.max_length == 500
        assert q.field_type == "text"
        assert q.options == ["A", "B"]
        assert q.section == "자기소개서"
