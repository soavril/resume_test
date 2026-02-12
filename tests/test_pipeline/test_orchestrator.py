"""Tests for pipeline orchestrator."""

import pytest

from resume_tailor.models.company import CompanyProfile
from resume_tailor.pipeline.orchestrator import PipelineOrchestrator, PipelineResult


@pytest.fixture
def mock_company_json():
    return {
        "name": "테스트",
        "industry": "IT",
        "description": "테스트 회사",
        "culture_values": ["혁신"],
        "tech_stack": ["Python"],
        "recent_news": ["뉴스"],
        "business_direction": "AI",
    }


@pytest.fixture
def mock_job_json():
    return {
        "title": "개발자",
        "hard_skills": ["Python"],
        "soft_skills": ["소통"],
        "ats_keywords": ["Python", "Django"],
        "seniority_level": "미들",
        "tone": "formal",
        "key_responsibilities": ["개발"],
        "preferred_qualifications": ["AWS"],
    }


@pytest.fixture
def mock_strategy_json():
    return {
        "match_matrix": [
            {
                "requirement": "Python",
                "my_experience": "3년",
                "strength": "strong",
                "talking_points": ["Django"],
            }
        ],
        "gaps": [],
        "emphasis_points": ["Python 전문성"],
        "keyword_plan": [{"keyword": "Python", "placement": "자기소개"}],
        "tone_guidance": "전문적",
        "summary_direction": "Python 백엔드 개발자",
    }


@pytest.fixture
def mock_resume_json():
    return {
        "sections": [
            {"id": "header", "label": "인적사항", "content": "# 홍길동"},
        ],
        "full_markdown": "# 홍길동\n\nPython 개발자",
    }


@pytest.fixture
def mock_qa_json():
    return {
        "factual_accuracy": 95,
        "keyword_coverage": 90,
        "template_compliance": 85,
        "overall_score": 90,
        "issues": [],
        "suggestions": [],
        "pass": True,
    }


def _make_dispatch(responses):
    """Create a side_effect function that dispatches by prompt content.

    This is needed because asyncio.gather makes LLM call order
    non-deterministic in Phase 1 (company research + JD analysis).
    """
    remaining = list(responses)

    async def _dispatch(prompt, **kwargs):
        if "회사 프로필을 작성하세요" in prompt:
            return responses["company"]
        if "채용공고를 분석하세요" in prompt:
            return responses["job"]
        # For sequential phases, pop from remaining list
        return remaining.pop(0)

    # Pre-fill remaining with sequential-phase responses only
    remaining.clear()
    for key in ("strategy", "resume", "qa", "resume2", "qa2"):
        if key in responses:
            remaining.append(responses[key])

    return _dispatch


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_full_pipeline(
        self,
        mock_llm_client,
        mock_search_client,
        mock_company_json,
        mock_job_json,
        mock_strategy_json,
        mock_resume_json,
        mock_qa_json,
    ):
        mock_llm_client.generate_json.side_effect = _make_dispatch({
            "company": mock_company_json,
            "job": mock_job_json,
            "strategy": mock_strategy_json,
            "resume": mock_resume_json,
            "qa": mock_qa_json,
        })

        orchestrator = PipelineOrchestrator(mock_llm_client, mock_search_client)
        result = await orchestrator.run(
            company_name="테스트",
            jd_text="Python 개발자 모집",
            resume_text="홍길동, Python 3년",
        )

        assert isinstance(result, PipelineResult)
        assert result.company.name == "테스트"
        assert result.job.title == "개발자"
        assert result.qa.pass_ is True
        assert result.rewrites == 0

    @pytest.mark.asyncio
    async def test_pipeline_with_cached_company(
        self,
        mock_llm_client,
        mock_search_client,
        sample_company_profile,
        mock_job_json,
        mock_strategy_json,
        mock_resume_json,
        mock_qa_json,
    ):
        mock_llm_client.generate_json.side_effect = [
            mock_job_json,
            mock_strategy_json,
            mock_resume_json,
            mock_qa_json,
        ]

        orchestrator = PipelineOrchestrator(mock_llm_client, mock_search_client)
        result = await orchestrator.run(
            company_name="네이버",
            jd_text="개발자 모집",
            resume_text="이력서",
            company_profile=sample_company_profile,
        )

        assert result.company.name == "네이버"
        # Search should not be called when company is cached
        assert not mock_search_client.search.called

    @pytest.mark.asyncio
    async def test_pipeline_with_rewrite(
        self,
        mock_llm_client,
        mock_search_client,
        mock_company_json,
        mock_job_json,
        mock_strategy_json,
        mock_resume_json,
    ):
        qa_fail = {
            "factual_accuracy": 60,
            "keyword_coverage": 50,
            "template_compliance": 70,
            "overall_score": 60,
            "issues": ["문제"],
            "suggestions": ["개선"],
            "pass": False,
        }
        qa_pass = {
            "factual_accuracy": 90,
            "keyword_coverage": 85,
            "template_compliance": 90,
            "overall_score": 88,
            "issues": [],
            "suggestions": [],
            "pass": True,
        }
        mock_llm_client.generate_json.side_effect = _make_dispatch({
            "company": mock_company_json,
            "job": mock_job_json,
            "strategy": mock_strategy_json,
            "resume": mock_resume_json,
            "qa": qa_fail,
            "resume2": mock_resume_json,
            "qa2": qa_pass,
        })

        orchestrator = PipelineOrchestrator(mock_llm_client, mock_search_client)
        result = await orchestrator.run(
            company_name="테스트",
            jd_text="개발자",
            resume_text="이력서",
        )

        assert result.rewrites == 1
        assert result.qa.pass_ is True

    @pytest.mark.asyncio
    async def test_research_only(self, mock_llm_client, mock_search_client, mock_company_json):
        mock_llm_client.generate_json.return_value = mock_company_json
        orchestrator = PipelineOrchestrator(mock_llm_client, mock_search_client)
        result = await orchestrator.research_only("테스트")

        assert isinstance(result, CompanyProfile)
        assert result.name == "테스트"

    @pytest.mark.asyncio
    async def test_progress_callback(
        self,
        mock_llm_client,
        mock_search_client,
        mock_company_json,
        mock_job_json,
        mock_strategy_json,
        mock_resume_json,
        mock_qa_json,
    ):
        mock_llm_client.generate_json.side_effect = _make_dispatch({
            "company": mock_company_json,
            "job": mock_job_json,
            "strategy": mock_strategy_json,
            "resume": mock_resume_json,
            "qa": mock_qa_json,
        })

        phases = []

        def on_phase(phase, detail):
            phases.append(phase)

        orchestrator = PipelineOrchestrator(mock_llm_client, mock_search_client)
        await orchestrator.run(
            company_name="테스트",
            jd_text="개발자",
            resume_text="이력서",
            on_phase=on_phase,
        )

        assert "phase1" in phases
        assert "done" in phases
