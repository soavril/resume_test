"""Agent 3: Strategy Planner - Creates resume tailoring strategy."""

from __future__ import annotations

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.company import CompanyProfile
from resume_tailor.models.job import JobAnalysis
from resume_tailor.models.strategy import ResumeStrategy

STRATEGY_HINTS = {
    "tech": "기술적 depth, 프로젝트 임팩트, 시스템 설계 역량, 오픈소스 기여를 강조하세요.",
    "business": "규모감(예산/인원/매출), 리더십, 크로스펑셔널 협업, 비즈니스 임팩트를 강조하세요.",
    "design": "디자인 프로세스, 사용자 리서치, 비즈니스 임팩트, 포트폴리오 연계를 강조하세요.",
    "general": "",
}

SYSTEM_PROMPT = """\
당신은 이력서 전략 컨설턴트입니다. 회사 정보, 채용공고 분석, 지원자의 이력서를 종합하여 최적의 이력서 맞춤화 전략을 수립합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "match_matrix": [
    {
      "requirement": "채용공고 요구사항",
      "my_experience": "매칭되는 내 경험",
      "strength": "strong/moderate/weak",
      "talking_points": ["강조할 포인트 1", "포인트 2"]
    }
  ],
  "gaps": [
    {
      "requirement": "부족한 요구사항",
      "mitigation": "보완 전략"
    }
  ],
  "emphasis_points": ["특별히 강조할 경험/역량 1", "2"],
  "keyword_plan": [
    {
      "keyword": "삽입할 키워드",
      "placement": "삽입 위치 (예: 자기소개, 경력사항 등)"
    }
  ],
  "tone_guidance": "이력서 톤앤매너 가이드",
  "summary_direction": "자기소개 방향성"
}

전략 수립 원칙:
1. 지원자의 실제 경험만 활용합니다. 없는 경험을 만들어내지 마세요.
2. 강점(strong match)을 최대한 부각하는 방향으로 전략을 세웁니다.
3. 약점(gap)은 관련 경험이나 학습 의지로 보완합니다.
4. ATS 키워드를 자연스럽게 배치합니다.
5. 이력서와 채용공고의 언어가 다를 수 있습니다 (예: 한글 이력서 + 영문 JD). 두 언어 모두 이해하고 전략을 세우세요."""


class StrategyPlanner:
    def __init__(self, llm: LLMClient, model: str = "claude-sonnet-4-5-20250929"):
        self.llm = llm
        self.model = model

    async def plan(
        self,
        company: CompanyProfile,
        job: JobAnalysis,
        resume_text: str,
        *,
        language: str = "ko",
        role_category: str = "general",
    ) -> ResumeStrategy:
        """Create a tailoring strategy based on company, JD, and resume."""
        lang_note = ""
        if language == "en":
            lang_note = "\n\n**The final resume will be written in English. Plan keywords and tone accordingly.**"

        role_hint = STRATEGY_HINTS.get(role_category, "")
        if role_hint:
            role_hint_section = f"\n\n## 직군별 전략 가이드\n{role_hint}"
        else:
            role_hint_section = ""

        prompt = f"""다음 정보를 바탕으로 이력서 맞춤화 전략을 수립하세요.{lang_note}

## 회사 정보
- 회사명: {company.name}
- 산업: {company.industry}
- 설명: {company.description}
- 기업문화: {', '.join(company.culture_values)}
- 기술스택: {', '.join(company.tech_stack)}
- 사업방향: {company.business_direction}

## 채용공고 분석
- 포지션: {job.title}
- 시니어리티: {job.seniority_level}
- 필수 기술: {', '.join(job.hard_skills)}
- 소프트 스킬: {', '.join(job.soft_skills)}
- ATS 키워드: {', '.join(job.ats_keywords)}
- 핵심 업무: {', '.join(job.key_responsibilities)}
- 우대사항: {', '.join(job.preferred_qualifications)}
- 톤: {job.tone}

## 지원자 이력서
{resume_text}
{role_hint_section}
JSON 형식으로만 응답하세요."""

        data = await self.llm.generate_json(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=self.model,
        )
        return ResumeStrategy(**data)
