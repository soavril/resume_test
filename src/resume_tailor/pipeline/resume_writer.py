"""Agent 4: Resume Writer - Generates tailored resume in Markdown."""

from __future__ import annotations

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.resume import ResumeSection, TailoredResume
from resume_tailor.models.strategy import ResumeStrategy
from resume_tailor.templates.loader import ResumeTemplate

EXPERIENCE_FORMAT = {
    "tech": """각 경력 항목은 프로젝트 단위로 구분하여 STAR 형식으로 작성합니다.
프로젝트명을 볼드 표기하고, S(상황)-T(과제)-A(행동)-R(결과) 구조를 따르되 기술적 의사결정과 정량 성과를 강조합니다.
사용 기술은 Action에 자연스럽게 포함합니다.""",

    "business": """각 경력 항목은 '주요업무 → 성과' 구조로 작성합니다.
주요업무를 볼드 표기하고, 그 아래 bullet point로 구체적 성과를 나열합니다.
업무 규모(예산, 인원, 범위)와 정량 결과(매출, 비용절감, 전환율)를 강조합니다.
리더십과 크로스펑셔널 협업 경험을 부각합니다.""",

    "design": """각 경력 항목은 '프로젝트 → 프로세스 → 임팩트' 구조로 작성합니다.
프로젝트명을 볼드 표기하고, 디자인 프로세스(리서치, 와이어프레임, 프로토타입, 테스트)와 비즈니스 임팩트를 강조합니다.""",

    "general": """각 경력 항목은 '주요업무 → 성과' 구조를 기본으로 하되,
프로젝트성 업무는 STAR 형식을 병행할 수 있습니다. 업무 범위와 성과를 균형있게 서술합니다.""",
}

SYSTEM_PROMPT_KO = """\
당신은 전문 이력서 작성가입니다. 주어진 전략과 템플릿 구조에 따라 최적화된 이력서를 Markdown으로 작성합니다.

작성 원칙:
1. 반드시 제공된 템플릿 섹션 순서와 구조를 따릅니다.
2. 지원자의 원본 이력서에 있는 사실만 사용합니다. 새로운 경험을 만들지 마세요.
3. 전략의 강조 포인트와 키워드를 자연스럽게 반영합니다.
4. 원본에 구체적 수치가 있으면 그대로 사용합니다. 원본에 없는 수치를 추정하거나 부풀리지 마세요.
5. {experience_format}
6. ATS 최적화를 위해 키워드를 자연스럽게 포함합니다.
7. **과장 금지**: "혁신적", "획기적", "탁월한", "독보적" 같은 수식어를 사용하지 마세요. 사실 기반의 담백한 톤으로 작성하세요.
8. 원본 이력서의 표현 수준과 톤을 유지하세요. 원본보다 과도하게 화려하게 쓰지 마세요.
9. 전체 분량은 A4 2장 이내로 작성합니다. 경력기술서 수준의 상세한 경력 서술을 포함하세요.
10. **반드시 한국어로만 작성합니다.** 채용공고가 영문이더라도 이력서 본문은 100% 한국어로 작성하세요. 영문 키워드를 그대로 삽입하지 마세요. 회사명, 제품명 등 고유명사와 TOEIC, JLPT 같은 공인 시험명만 영문을 허용합니다.
11. 원본 이력서에 없는 항목(이메일, 연락처, 주소 등)을 플레이스홀더로 만들지 마세요. 원본에 있는 정보만 사용합니다.

응답은 반드시 아래 JSON 형식으로:
{{
  "sections": [
    {{"id": "섹션ID", "label": "섹션 라벨", "content": "마크다운 내용"}}
  ],
  "full_markdown": "전체 이력서 마크다운 (한국어)"
}}"""

SYSTEM_PROMPT_EN = """\
You are a professional resume writer. Generate an optimized resume in Markdown based on the given strategy and template structure.

CRITICAL: The ENTIRE resume MUST be written in English. Even if the source resume is in Korean, translate and write everything in English.

Writing principles:
1. Follow the provided template section order and structure exactly.
2. Use ONLY facts from the applicant's original resume. Do NOT fabricate experiences.
3. Naturally incorporate the strategy's emphasis points and keywords.
4. Use specific numbers from the original only. Do NOT inflate or estimate numbers not in the source.
5. {experience_format}
6. Include ATS-optimized keywords naturally.
7. **No exaggeration**: Avoid words like "revolutionary", "groundbreaking", "exceptional". Write in a fact-based, professional tone.
8. Maintain a tone consistent with the original resume. Do not over-embellish.
9. Keep the resume to 1 page. Be concise — prioritize impact over exhaustiveness.

Respond ONLY in this JSON format:
{{
  "sections": [
    {{"id": "section_id", "label": "Section Label", "content": "markdown content"}}
  ],
  "full_markdown": "Full resume markdown (in English)"
}}"""


class ResumeWriter:
    def __init__(self, llm: LLMClient, model: str = "claude-sonnet-4-5-20250929"):
        self.llm = llm
        self.model = model

    async def write(
        self,
        strategy: ResumeStrategy,
        resume_text: str,
        template: ResumeTemplate,
        *,
        language: str = "ko",
        role_category: str = "general",
    ) -> TailoredResume:
        """Generate a tailored resume based on strategy and template."""
        template_spec = self._format_template(template)
        strategy_spec = self._format_strategy(strategy)

        exp_format = EXPERIENCE_FORMAT.get(role_category, EXPERIENCE_FORMAT["general"])
        system_prompt_template = SYSTEM_PROMPT_EN if language == "en" else SYSTEM_PROMPT_KO
        system_prompt = system_prompt_template.format(experience_format=exp_format)

        prompt = f"""다음 전략과 템플릿에 따라 맞춤 이력서를 작성하세요.

## 템플릿 구조 (반드시 이 순서와 섹션을 따르세요)
{template_spec}

## 맞춤화 전략
{strategy_spec}

## 원본 이력서
{resume_text}

위 템플릿 구조의 각 섹션에 맞춰 이력서를 작성하세요. JSON 형식으로만 응답하세요."""

        data = await self.llm.generate_json(
            prompt=prompt,
            system=system_prompt,
            model=self.model,
            temperature=0.3,
        )

        if not isinstance(data, dict):
            data = {"sections": [], "full_markdown": str(data)}

        sections = [ResumeSection(**s) for s in data.get("sections", [])]
        full_md = data.get("full_markdown", "")

        if not full_md and sections:
            full_md = self._build_markdown(sections)

        return TailoredResume(
            sections=sections,
            full_markdown=full_md,
            metadata={},
        )

    def _format_template(self, template: ResumeTemplate) -> str:
        lines = [f"템플릿: {template.name}\n"]
        for s in template.sections:
            req = "필수" if s.required else "선택"
            line = f"- [{s.id}] {s.label} ({req})"
            if s.max_length:
                line += f" | 최대 {s.max_length}자"
            if s.content_type:
                line += f" | 형식: {s.content_type}"
            lines.append(line)
        return "\n".join(lines)

    def _format_strategy(self, strategy: ResumeStrategy) -> str:
        parts = []
        parts.append(f"톤앤매너: {strategy.tone_guidance}")
        parts.append(f"자기소개 방향: {strategy.summary_direction}")
        parts.append(f"\n강조 포인트: {', '.join(strategy.emphasis_points)}")

        parts.append("\n키워드 배치 계획:")
        for kp in strategy.keyword_plan:
            parts.append(f"  - '{kp.keyword}' → {kp.placement}")

        parts.append("\n매칭 분석:")
        for m in strategy.match_matrix:
            parts.append(f"  - [{m.strength}] {m.requirement} ← {m.my_experience}")

        if strategy.gaps:
            parts.append("\n갭 분석:")
            for g in strategy.gaps:
                parts.append(f"  - {g.requirement}: {g.mitigation}")

        return "\n".join(parts)

    def _build_markdown(self, sections: list[ResumeSection]) -> str:
        parts = []
        for s in sections:
            parts.append(f"## {s.label}\n\n{s.content}")
        return "\n\n".join(parts)
