"""Tests for form_filler: generate_form_answers, extract_structured_fields, _smart_truncate."""

from unittest.mock import AsyncMock

import pytest

from resume_tailor.clients.llm_client import LLMResponse
from resume_tailor.parsers.form_parser import FormQuestion
from resume_tailor.pipeline.form_filler import (
    _smart_truncate,
    extract_structured_fields,
    generate_form_answers,
)


class TestGenerateFormAnswers:
    @pytest.mark.asyncio
    async def test_generate_form_answers_returns_list(self, sample_tailored_resume):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text="답변 텍스트", input_tokens=10, output_tokens=5)
        )
        questions = [
            FormQuestion(label="자기소개를 해주세요"),
            FormQuestion(label="지원동기가 무엇인가요?"),
        ]
        result = await generate_form_answers(mock_llm, questions, sample_tailored_resume)
        assert isinstance(result, list)
        assert len(result) == 2
        for item in result:
            assert "question" in item
            assert "answer" in item
            assert "char_count" in item
            assert "max_length" in item

    @pytest.mark.asyncio
    async def test_generate_form_answers_parallel(self, sample_tailored_resume):
        call_count = 0

        async def dispatch(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            return LLMResponse(text="답변", input_tokens=10, output_tokens=5)

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=dispatch)
        questions = [
            FormQuestion(label="자기소개를 해주세요"),
            FormQuestion(label="지원동기가 무엇인가요?"),
            FormQuestion(label="입사 후 포부를 작성해주세요"),
        ]
        await generate_form_answers(mock_llm, questions, sample_tailored_resume)
        # All three questions must be answered (asyncio.gather runs them all)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_generate_form_answers_respects_max_length(self, sample_tailored_resume):
        long_answer = "가" * 50  # 50 chars, well over max_length=10

        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(
            return_value=LLMResponse(text=long_answer, input_tokens=10, output_tokens=5)
        )
        questions = [FormQuestion(label="자기소개를 해주세요", max_length=10)]
        result = await generate_form_answers(mock_llm, questions, sample_tailored_resume)
        assert result[0]["char_count"] <= 10

    @pytest.mark.asyncio
    async def test_generate_form_answers_empty_questions(self, sample_tailored_resume):
        mock_llm = AsyncMock()
        result = await generate_form_answers(mock_llm, [], sample_tailored_resume)
        assert result == []
        mock_llm.generate.assert_not_called()


class TestExtractStructuredFields:
    @pytest.mark.asyncio
    async def test_extract_structured_fields_returns_dict(self, sample_tailored_resume):
        expected = {"personal": {"name": "홍길동"}}
        mock_llm = AsyncMock()
        mock_llm.generate_json = AsyncMock(return_value=expected)
        result = await extract_structured_fields(mock_llm, sample_tailored_resume)
        assert isinstance(result, dict)
        assert result == expected

    @pytest.mark.asyncio
    async def test_extract_structured_fields_passes_resume_markdown(
        self, sample_tailored_resume
    ):
        mock_llm = AsyncMock()
        mock_llm.generate_json = AsyncMock(return_value={})
        await extract_structured_fields(mock_llm, sample_tailored_resume)
        call_kwargs = mock_llm.generate_json.call_args.kwargs
        assert sample_tailored_resume.full_markdown in call_kwargs["prompt"]


class TestSmartTruncate:
    def test_smart_truncate_under_limit(self):
        text = "짧은 텍스트"
        result = _smart_truncate(text, 100)
        assert result == text

    def test_smart_truncate_at_boundary(self):
        text = "첫 문장입니다. 두번째 문장입니다. 세번째 문장입니다."
        result = _smart_truncate(text, 25)
        assert len(result) <= 25
        # Must not end mid-sentence (should cut at a sentence boundary or space)
        assert len(result) > 0

    def test_smart_truncate_at_space(self):
        # Long text with no sentence-ending punctuation, only spaces
        text = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10"
        result = _smart_truncate(text, 20)
        assert len(result) <= 20
        # Should end at a word boundary (no trailing space)
        assert not result.endswith(" ")

    def test_smart_truncate_exact_limit(self):
        text = "가" * 10
        result = _smart_truncate(text, 10)
        assert result == text
