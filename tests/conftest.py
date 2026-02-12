"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from resume_tailor.clients.llm_client import LLMClient, LLMResponse
from resume_tailor.clients.search_client import SearchClient
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

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_jd_text() -> str:
    return """[네이버] 백엔드 개발자 (경력 3-5년)

주요업무:
- 대규모 트래픽 처리를 위한 서버 개발
- RESTful API 설계 및 구현
- 마이크로서비스 아키텍처 설계

자격요건:
- Java/Kotlin 기반 서버 개발 경력 3년 이상
- Spring Boot, Spring Cloud 경험
- MySQL, Redis 활용 경험
- 대용량 데이터 처리 경험

우대사항:
- Kubernetes/Docker 운영 경험
- 카프카 등 메시지 큐 활용 경험
- 오픈소스 기여 경험
"""


@pytest.fixture
def sample_resume_text() -> str:
    return """홍길동
email: hong@example.com | phone: 010-1234-5678

경력사항:
- ABC 테크 (2021.03 ~ 현재) - 백엔드 개발자
  - Spring Boot 기반 API 서버 개발 (일 100만 리퀘스트)
  - MySQL 쿼리 최적화로 응답 시간 40% 개선
  - Redis 캐싱 도입으로 DB 부하 60% 감소

- XYZ 스타트업 (2019.01 ~ 2021.02) - 주니어 개발자
  - Python/Django REST API 개발
  - AWS EC2, RDS 인프라 관리

학력:
- 한국대학교 컴퓨터공학과 학사 (2015 ~ 2019)

기술:
- Java, Kotlin, Python
- Spring Boot, Django
- MySQL, PostgreSQL, Redis
- Docker, AWS
"""


@pytest.fixture
def sample_company_profile() -> CompanyProfile:
    return CompanyProfile(
        name="네이버",
        industry="IT/인터넷",
        description="대한민국 최대 인터넷 기업으로 검색, 커머스, 핀테크 등 다양한 서비스를 운영합니다.",
        culture_values=["기술 혁신", "자율과 책임", "도전정신"],
        tech_stack=["Java", "Kotlin", "Spring Boot", "Kubernetes", "Kafka"],
        recent_news=["AI 서비스 강화", "클라우드 사업 확대"],
        business_direction="AI와 클라우드 중심의 기술 플랫폼 기업으로 성장",
        employee_count="약 6,000명",
        headquarters="성남시 분당구",
    )


@pytest.fixture
def sample_job_analysis() -> JobAnalysis:
    return JobAnalysis(
        title="백엔드 개발자",
        hard_skills=["Java", "Kotlin", "Spring Boot", "MySQL", "Redis"],
        soft_skills=["커뮤니케이션", "문제 해결"],
        ats_keywords=["Spring Boot", "마이크로서비스", "대규모 트래픽", "REST API", "Kubernetes"],
        seniority_level="미들",
        tone="technical",
        key_responsibilities=["서버 개발", "API 설계", "MSA 설계"],
        preferred_qualifications=["Kubernetes", "Kafka", "오픈소스"],
        years_experience="3-5년",
    )


@pytest.fixture
def sample_strategy() -> ResumeStrategy:
    return ResumeStrategy(
        match_matrix=[
            MatchItem(
                requirement="Java/Spring Boot 경험",
                my_experience="ABC 테크에서 Spring Boot 기반 API 서버 개발",
                strength="strong",
                talking_points=["일 100만 리퀘스트 처리", "3년 경험"],
            ),
        ],
        gaps=[
            GapItem(
                requirement="Kubernetes 경험",
                mitigation="Docker 경험을 강조하고 K8s 학습 중임을 언급",
            ),
        ],
        emphasis_points=["대규모 트래픽 처리 경험", "성능 최적화 성과"],
        keyword_plan=[
            KeywordPlan(keyword="마이크로서비스", placement="자기소개"),
            KeywordPlan(keyword="Spring Boot", placement="경력사항"),
        ],
        tone_guidance="기술적이고 구체적인 성과 중심",
        summary_direction="대규모 트래픽 처리와 성능 최적화에 강점을 가진 백엔드 개발자",
    )


@pytest.fixture
def sample_tailored_resume() -> TailoredResume:
    return TailoredResume(
        sections=[
            ResumeSection(id="header", label="인적사항", content="# 홍길동\nemail: hong@example.com"),
            ResumeSection(id="summary", label="자기소개", content="대규모 트래픽 처리 전문 백엔드 개발자"),
            ResumeSection(id="experience", label="경력사항", content="## ABC 테크\n- Spring Boot API"),
        ],
        full_markdown="# 홍길동\n\n## 자기소개\n대규모 트래픽 처리 전문 백엔드 개발자\n\n## 경력사항\n...",
        metadata={},
    )


@pytest.fixture
def sample_qa_result() -> QAResult:
    return QAResult(
        factual_accuracy=95,
        keyword_coverage=85,
        template_compliance=90,
        overall_score=90,
        issues=[],
        suggestions=["Kubernetes 관련 내용 보강 권장"],
        pass_=True,
    )


@pytest.fixture
def mock_llm_client() -> LLMClient:
    """Create a mock LLM client."""
    client = AsyncMock(spec=LLMClient)
    client.generate = AsyncMock(
        return_value=LLMResponse(text="{}", input_tokens=100, output_tokens=50)
    )
    client.generate_json = AsyncMock(return_value={})
    return client


@pytest.fixture
def mock_search_client() -> SearchClient:
    """Create a mock search client."""
    client = AsyncMock(spec=SearchClient)
    client.search = AsyncMock(
        return_value=[
            {"title": "Test", "url": "https://example.com", "content": "Test content"}
        ]
    )
    return client
