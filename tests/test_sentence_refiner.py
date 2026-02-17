"""Tests for SentenceRefiner agent and RefinementSuggestion model."""

from __future__ import annotations

import pytest

from resume_tailor.models.refinement import RefinementSuggestion
from resume_tailor.pipeline.sentence_refiner import SentenceRefiner


def _make_suggestion_dicts(count: int = 3) -> list[dict]:
    """Create sample suggestion dicts for mocking."""
    types = ["conciseness", "impact", "keyword", "tone"]
    return [
        {
            "alternative": f"Alternative text {i + 1}",
            "rationale": f"Rationale {i + 1}",
            "improvement_type": types[i % len(types)],
        }
        for i in range(count)
    ]


class TestRefinementSuggestionModel:
    """Tests for the RefinementSuggestion Pydantic model."""

    def test_refinement_suggestion_model(self):
        """Pydantic model validates and stores fields correctly."""
        suggestion = RefinementSuggestion(
            alternative="Improved sentence",
            rationale="More concise",
            improvement_type="conciseness",
        )
        assert suggestion.alternative == "Improved sentence"
        assert suggestion.rationale == "More concise"
        assert suggestion.improvement_type == "conciseness"

    def test_refinement_suggestion_model_rejects_missing_fields(self):
        """Model raises ValidationError when required fields are missing."""
        with pytest.raises(Exception):
            RefinementSuggestion(alternative="text")  # type: ignore[call-arg]


class TestSentenceRefiner:
    """Tests for the SentenceRefiner agent."""

    @pytest.mark.asyncio
    async def test_refine_returns_suggestions(self, mock_llm_client):
        """LLM returning 3 suggestions produces 3 RefinementSuggestion objects."""
        mock_llm_client.generate_json.return_value = _make_suggestion_dicts(3)
        refiner = SentenceRefiner(llm=mock_llm_client)

        result = await refiner.refine(
            selected_text="Spring Boot 기반 API 서버 개발",
            full_resume="홍길동\n경력: Spring Boot 기반 API 서버 개발",
            jd_text="백엔드 개발자 모집",
        )

        assert len(result) == 3
        assert all(isinstance(s, RefinementSuggestion) for s in result)
        assert result[0].improvement_type == "conciseness"
        assert result[1].improvement_type == "impact"
        mock_llm_client.generate_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_refine_with_custom_count(self, mock_llm_client):
        """num_alternatives=2 returns exactly 2 suggestions."""
        mock_llm_client.generate_json.return_value = _make_suggestion_dicts(2)
        refiner = SentenceRefiner(llm=mock_llm_client)

        result = await refiner.refine(
            selected_text="MySQL 쿼리 최적화",
            full_resume="경력: MySQL 쿼리 최적화로 응답 시간 40% 개선",
            jd_text="DB 경험 필수",
            num_alternatives=2,
        )

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_refine_empty_text(self, mock_llm_client):
        """Empty selected_text returns empty list without calling LLM."""
        refiner = SentenceRefiner(llm=mock_llm_client)

        result = await refiner.refine(
            selected_text="",
            full_resume="resume content",
            jd_text="jd content",
        )

        assert result == []
        mock_llm_client.generate_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_refine_whitespace_only_text(self, mock_llm_client):
        """Whitespace-only selected_text returns empty list."""
        refiner = SentenceRefiner(llm=mock_llm_client)

        result = await refiner.refine(
            selected_text="   \n  ",
            full_resume="resume content",
            jd_text="jd content",
        )

        assert result == []
        mock_llm_client.generate_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_refine_preserves_context(self, mock_llm_client):
        """full_resume and jd_text appear in the prompt sent to LLM."""
        mock_llm_client.generate_json.return_value = _make_suggestion_dicts(3)
        refiner = SentenceRefiner(llm=mock_llm_client)

        await refiner.refine(
            selected_text="선택 문장",
            full_resume="UNIQUE_RESUME_CONTENT",
            jd_text="UNIQUE_JD_CONTENT",
        )

        call_kwargs = mock_llm_client.generate_json.call_args
        prompt = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get("prompt") or call_kwargs[0][0]
        assert "UNIQUE_RESUME_CONTENT" in prompt
        assert "UNIQUE_JD_CONTENT" in prompt

    @pytest.mark.asyncio
    async def test_refine_handles_llm_error(self, mock_llm_client):
        """LLM exception returns empty list without crashing."""
        mock_llm_client.generate_json.side_effect = RuntimeError("API error")
        refiner = SentenceRefiner(llm=mock_llm_client)

        result = await refiner.refine(
            selected_text="Some text",
            full_resume="resume",
            jd_text="jd",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_refine_handles_dict_wrapper(self, mock_llm_client):
        """LLM returning {"suggestions": [...]} is unwrapped correctly."""
        mock_llm_client.generate_json.return_value = {
            "suggestions": _make_suggestion_dicts(3)
        }
        refiner = SentenceRefiner(llm=mock_llm_client)

        result = await refiner.refine(
            selected_text="Redis 캐싱 도입",
            full_resume="Redis 캐싱 도입으로 DB 부하 60% 감소",
            jd_text="캐싱 경험 우대",
        )

        assert len(result) == 3
        assert all(isinstance(s, RefinementSuggestion) for s in result)


class TestParseSuggestions:
    """Tests for the _parse_suggestions static method."""

    def test_parse_empty_list(self):
        assert SentenceRefiner._parse_suggestions([], 3) == []

    def test_parse_non_list(self):
        assert SentenceRefiner._parse_suggestions("not a list", 3) == []

    def test_parse_dict_without_known_key(self):
        assert SentenceRefiner._parse_suggestions({"unknown": []}, 3) == []

    def test_parse_truncates_to_max_count(self):
        data = _make_suggestion_dicts(5)
        result = SentenceRefiner._parse_suggestions(data, 2)
        assert len(result) == 2

    def test_parse_skips_invalid_items(self):
        data = [
            {"alternative": "ok", "rationale": "ok", "improvement_type": "impact"},
            "not a dict",
            {"alternative": "ok2", "rationale": "ok2", "improvement_type": "tone"},
        ]
        result = SentenceRefiner._parse_suggestions(data, 5)
        assert len(result) == 2

    def test_parse_alternatives_key(self):
        """Dict wrapper with 'alternatives' key is handled."""
        data = {"alternatives": _make_suggestion_dicts(2)}
        result = SentenceRefiner._parse_suggestions(data, 3)
        assert len(result) == 2
