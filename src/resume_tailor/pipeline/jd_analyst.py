"""Agent 2: JD Analyst - Analyzes job descriptions to extract requirements."""

from __future__ import annotations

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.job import JobAnalysis

SYSTEM_PROMPT = """\
당신은 채용공고 분석 전문가입니다. 주어진 채용공고를 분석하여 구직자가 이력서를 맞춤화하는 데 필요한 핵심 정보를 추출합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "title": "채용 포지션명",
  "hard_skills": ["필수 기술 역량 1", "필수 기술 역량 2"],
  "soft_skills": ["소프트 스킬 1", "소프트 스킬 2"],
  "ats_keywords": ["ATS 통과에 중요한 키워드 1", "키워드 2"],
  "seniority_level": "시니어/미들/주니어",
  "tone": "formal/casual/technical",
  "key_responsibilities": ["핵심 업무 1", "핵심 업무 2"],
  "preferred_qualifications": ["우대사항 1", "우대사항 2"],
  "years_experience": "요구 경력 (예: 3-5년)",
  "role_category": "tech/business/design/general 중 하나"
}

주의사항:
- 채용공고가 한국어든 영어든 상관없이 분석합니다.
- 영문 JD의 키워드는 "한국어 번역 (영문 원문)" 형태로 추출하세요. 예: "분쟁 해결 (dispute resolution)", "규제 준수 (regulatory compliance)". 단, 고유명사(회사명, 제품명)와 널리 쓰이는 약어(ATS, CRM 등)는 영어 그대로 유지합니다.
- ats_keywords는 이력서에 반드시 포함되어야 할 키워드를 추출합니다
- hard_skills와 soft_skills를 명확히 구분합니다
- 채용공고에 명시되지 않은 내용은 추론하지 마세요
- role_category 분류 기준:
  tech: 소프트웨어 개발, 데이터 엔지니어링, DevOps, QA, 인프라
  business: 전략기획, PM, 컨설팅, 사업개발, 마케팅, 경영지원
  design: UX/UI, 프로덕트 디자인, 그래픽 디자인, 브랜드
  general: 위에 해당하지 않는 직군"""


class JDAnalyst:
    def __init__(self, llm: LLMClient, model: str = "claude-haiku-4-5-20251001"):
        self.llm = llm
        self.model = model

    async def analyze(self, jd_text: str) -> JobAnalysis:
        """Analyze a job description and return structured analysis."""
        prompt = f"""다음 채용공고를 분석하세요:

---
{jd_text}
---

JSON 형식으로만 응답하세요."""

        data = await self.llm.generate_json(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=self.model,
        )
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict from LLM, got {type(data).__name__}")
        return JobAnalysis(**data)
