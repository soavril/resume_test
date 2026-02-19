"""Tests for Pydantic data models."""

import pytest

from resume_tailor.models.company import CompanyProfile
from resume_tailor.models.job import JobAnalysis
from resume_tailor.models.qa import QAResult
from resume_tailor.models.resume import ResumeSection, TailoredResume
from resume_tailor.models.strategy import (
    GapItem,
    KeywordPlan,
    MatchItem,
    ResumeStrategy,
)


class TestCompanyProfile:
    def test_create_minimal(self):
        profile = CompanyProfile(
            name="테스트",
            industry="IT",
            description="설명",
            culture_values=["혁신"],
            tech_stack=["Python"],
            recent_news=["뉴스"],
            business_direction="AI",
        )
        assert profile.name == "테스트"
        assert profile.employee_count is None

    def test_create_full(self, sample_company_profile):
        assert sample_company_profile.name == "네이버"
        assert sample_company_profile.employee_count == "약 6,000명"

    def test_serialization(self, sample_company_profile):
        data = sample_company_profile.model_dump()
        restored = CompanyProfile(**data)
        assert restored == sample_company_profile


class TestJobAnalysis:
    def test_create(self, sample_job_analysis):
        assert sample_job_analysis.title == "백엔드 개발자"
        assert "Java" in sample_job_analysis.hard_skills
        assert sample_job_analysis.years_experience == "3-5년"

    def test_serialization(self, sample_job_analysis):
        data = sample_job_analysis.model_dump()
        restored = JobAnalysis(**data)
        assert restored == sample_job_analysis


class TestResumeStrategy:
    def test_create(self, sample_strategy):
        assert len(sample_strategy.match_matrix) == 1
        assert sample_strategy.match_matrix[0].strength == "strong"
        assert len(sample_strategy.gaps) == 1

    def test_match_item(self):
        item = MatchItem(
            requirement="Python",
            my_experience="3년 경험",
            strength="strong",
            talking_points=["Django", "FastAPI"],
        )
        assert item.strength == "strong"

    def test_keyword_plan(self):
        plan = KeywordPlan(keyword="Spring Boot", placement="경력사항")
        assert plan.keyword == "Spring Boot"


class TestTailoredResume:
    def test_create(self, sample_tailored_resume):
        assert len(sample_tailored_resume.sections) == 3
        assert sample_tailored_resume.sections[0].id == "header"

    def test_section(self):
        section = ResumeSection(id="test", label="테스트", content="내용")
        assert section.id == "test"


class TestQAResult:
    def test_create_with_alias(self):
        result = QAResult(
            factual_accuracy=90,
            keyword_coverage=85,
            template_compliance=80,
            overall_score=85,
            issues=["issue1"],
            suggestions=["suggestion1"],
            **{"pass": True},
        )
        assert result.pass_ is True

    def test_create_with_field_name(self):
        result = QAResult(
            factual_accuracy=90,
            keyword_coverage=85,
            template_compliance=80,
            overall_score=85,
            issues=[],
            suggestions=[],
            pass_=False,
        )
        assert result.pass_ is False

    def test_suggestion_examples_default(self):
        result = QAResult(
            factual_accuracy=90,
            keyword_coverage=85,
            template_compliance=80,
            overall_score=85,
            issues=[],
            suggestions=["키워드를 추가하세요"],
            pass_=True,
        )
        assert result.suggestion_examples == []

    def test_suggestion_examples_provided(self):
        result = QAResult(
            factual_accuracy=90,
            keyword_coverage=85,
            template_compliance=80,
            overall_score=85,
            issues=[],
            suggestions=["Python 키워드를 추가하세요"],
            suggestion_examples=["Python 3.11 기반 REST API 개발 경험"],
            pass_=True,
        )
        assert len(result.suggestion_examples) == 1
        assert "Python" in result.suggestion_examples[0]

    def test_serialization(self, sample_qa_result):
        data = sample_qa_result.model_dump(by_alias=True)
        assert "pass" in data
        restored = QAResult(**data)
        assert restored.pass_ is True
