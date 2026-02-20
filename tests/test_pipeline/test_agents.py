"""Tests for pipeline agents with mocked LLM."""

import json

import pytest

from resume_tailor.models.company import CompanyProfile
from resume_tailor.models.job import JobAnalysis
from resume_tailor.models.qa import QAResult
from resume_tailor.models.resume import TailoredResume
from resume_tailor.models.strategy import ResumeStrategy
from resume_tailor.pipeline.company_researcher import CompanyResearcher
from resume_tailor.pipeline.jd_analyst import JDAnalyst
from resume_tailor.pipeline.qa_reviewer import QAReviewer
from resume_tailor.pipeline.resume_writer import ResumeWriter
from resume_tailor.pipeline.strategy_planner import StrategyPlanner


class TestCompanyResearcher:
    @pytest.mark.asyncio
    async def test_research(self, mock_llm_client, mock_search_client):
        mock_llm_client.generate_json.return_value = {
            "name": "네이버",
            "industry": "IT",
            "description": "검색 서비스",
            "culture_values": ["혁신"],
            "tech_stack": ["Java"],
            "recent_news": ["AI 강화"],
            "business_direction": "AI 중심",
        }
        researcher = CompanyResearcher(mock_llm_client, mock_search_client)
        result = await researcher.research("네이버")

        assert isinstance(result, CompanyProfile)
        assert result.name == "네이버"
        assert mock_search_client.search.called

    @pytest.mark.asyncio
    async def test_search_queries(self, mock_llm_client, mock_search_client):
        mock_llm_client.generate_json.return_value = {
            "name": "T",
            "industry": "T",
            "description": "T",
            "culture_values": [],
            "tech_stack": [],
            "recent_news": [],
            "business_direction": "T",
        }
        researcher = CompanyResearcher(mock_llm_client, mock_search_client)
        await researcher.research("카카오")
        # Should make 3 search calls (culture, hiring, news)
        assert mock_search_client.search.call_count == 3


class TestJDAnalyst:
    @pytest.mark.asyncio
    async def test_analyze(self, mock_llm_client, sample_jd_text):
        mock_llm_client.generate_json.return_value = {
            "title": "백엔드 개발자",
            "hard_skills": ["Java", "Spring Boot"],
            "soft_skills": ["커뮤니케이션"],
            "ats_keywords": ["Spring Boot", "MSA"],
            "seniority_level": "미들",
            "tone": "technical",
            "key_responsibilities": ["서버 개발"],
            "preferred_qualifications": ["K8s"],
        }
        analyst = JDAnalyst(mock_llm_client)
        result = await analyst.analyze(sample_jd_text)

        assert isinstance(result, JobAnalysis)
        assert result.title == "백엔드 개발자"
        assert "Java" in result.hard_skills

    @pytest.mark.asyncio
    async def test_prompt_includes_jd(self, mock_llm_client):
        mock_llm_client.generate_json.return_value = {
            "title": "T",
            "hard_skills": [],
            "soft_skills": [],
            "ats_keywords": [],
            "seniority_level": "주니어",
            "tone": "formal",
            "key_responsibilities": [],
            "preferred_qualifications": [],
        }
        analyst = JDAnalyst(mock_llm_client)
        await analyst.analyze("Python 개발자 모집")
        # Verify the JD text was passed in the prompt
        call_args = mock_llm_client.generate_json.call_args
        assert "Python 개발자 모집" in call_args.kwargs["prompt"]


class TestStrategyPlanner:
    @pytest.mark.asyncio
    async def test_plan(
        self, mock_llm_client, sample_company_profile, sample_job_analysis, sample_resume_text
    ):
        mock_llm_client.generate_json.return_value = {
            "match_matrix": [
                {
                    "requirement": "Java",
                    "my_experience": "3년",
                    "strength": "strong",
                    "talking_points": ["실무"],
                }
            ],
            "gaps": [],
            "emphasis_points": ["성능 최적화"],
            "keyword_plan": [{"keyword": "Spring Boot", "placement": "경력"}],
            "tone_guidance": "기술적",
            "summary_direction": "백엔드 전문가",
        }
        planner = StrategyPlanner(mock_llm_client)
        result = await planner.plan(
            sample_company_profile, sample_job_analysis, sample_resume_text
        )

        assert isinstance(result, ResumeStrategy)
        assert len(result.match_matrix) == 1
        assert result.match_matrix[0].strength == "strong"


class TestResumeWriter:
    @pytest.mark.asyncio
    async def test_write(self, mock_llm_client, sample_strategy, sample_resume_text):
        from resume_tailor.templates.loader import load_template

        mock_llm_client.generate_json.return_value = {
            "sections": [
                {"id": "header", "label": "인적사항", "content": "# 홍길동"},
                {"id": "summary", "label": "자기소개", "content": "백엔드 개발자"},
            ],
            "full_markdown": "# 홍길동\n\n## 자기소개\n백엔드 개발자",
        }
        writer = ResumeWriter(mock_llm_client)
        template = load_template("korean_standard")
        result = await writer.write(sample_strategy, sample_resume_text, template)

        assert isinstance(result, TailoredResume)
        assert len(result.sections) == 2
        assert "홍길동" in result.full_markdown

    @pytest.mark.asyncio
    async def test_build_markdown_fallback(self, mock_llm_client, sample_strategy, sample_resume_text):
        from resume_tailor.templates.loader import load_template

        mock_llm_client.generate_json.return_value = {
            "sections": [
                {"id": "header", "label": "인적사항", "content": "# 홍길동"},
            ],
            "full_markdown": "",
        }
        writer = ResumeWriter(mock_llm_client)
        template = load_template("korean_standard")
        result = await writer.write(sample_strategy, sample_resume_text, template)

        # Should build markdown from sections
        assert "인적사항" in result.full_markdown

    @pytest.mark.asyncio
    async def test_list_return_coerced_to_sections(
        self, mock_llm_client, sample_strategy, sample_resume_text
    ):
        """When LLM returns a JSON array instead of dict, treat as sections list."""
        from resume_tailor.templates.loader import load_template

        mock_llm_client.generate_json.return_value = [
            {"id": "header", "label": "인적사항", "content": "# 홍길동"},
            {"id": "summary", "label": "자기소개", "content": "백엔드 개발자"},
        ]
        writer = ResumeWriter(mock_llm_client)
        template = load_template("korean_standard")
        result = await writer.write(sample_strategy, sample_resume_text, template)

        assert isinstance(result, TailoredResume)
        assert len(result.sections) == 2
        assert result.sections[0].id == "header"
        # full_markdown should be built from sections, not str(list)
        assert "인적사항" in result.full_markdown
        assert "[{" not in result.full_markdown

    @pytest.mark.asyncio
    async def test_string_return_stored_as_markdown(
        self, mock_llm_client, sample_strategy, sample_resume_text
    ):
        """When LLM returns a plain string, store it as full_markdown."""
        from resume_tailor.templates.loader import load_template

        mock_llm_client.generate_json.return_value = "# 홍길동\n\n백엔드 개발자입니다."
        writer = ResumeWriter(mock_llm_client)
        template = load_template("korean_standard")
        result = await writer.write(sample_strategy, sample_resume_text, template)

        assert isinstance(result, TailoredResume)
        assert len(result.sections) == 0
        assert "홍길동" in result.full_markdown


class TestQAReviewer:
    @pytest.mark.asyncio
    async def test_review_pass(self, mock_llm_client):
        mock_llm_client.generate_json.return_value = {
            "factual_accuracy": 95,
            "keyword_coverage": 85,
            "template_compliance": 90,
            "overall_score": 90,
            "issues": [],
            "suggestions": ["좋습니다"],
            "pass": True,
        }
        reviewer = QAReviewer(mock_llm_client)
        result = await reviewer.review("generated", "original", "jd text")

        assert isinstance(result, QAResult)
        assert result.pass_ is True
        assert result.overall_score == 90

    @pytest.mark.asyncio
    async def test_review_fail(self, mock_llm_client):
        mock_llm_client.generate_json.return_value = {
            "factual_accuracy": 60,
            "keyword_coverage": 50,
            "template_compliance": 70,
            "overall_score": 60,
            "issues": ["원본에 없는 경력 추가"],
            "suggestions": ["경력 삭제 필요"],
            "pass": False,
        }
        reviewer = QAReviewer(mock_llm_client)
        result = await reviewer.review("generated", "original", "jd text")

        assert result.pass_ is False
        assert len(result.issues) == 1
