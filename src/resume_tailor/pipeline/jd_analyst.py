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
  "years_experience": "요구 경력 (예: 3-5년)"
}

주의사항:
- 채용공고가 한국어든 영어든 상관없이 분석합니다. 영문 JD의 키워드는 영어 그대로 추출하세요.
- ats_keywords는 이력서에 반드시 포함되어야 할 키워드를 추출합니다
- hard_skills와 soft_skills를 명확히 구분합니다
- 채용공고에 명시되지 않은 내용은 추론하지 마세요"""


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
