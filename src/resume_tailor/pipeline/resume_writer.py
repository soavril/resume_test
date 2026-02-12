"""Agent 4: Resume Writer - Generates tailored resume in Markdown."""

from __future__ import annotations

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.resume import ResumeSection, TailoredResume
from resume_tailor.models.strategy import ResumeStrategy
from resume_tailor.templates.loader import ResumeTemplate

SYSTEM_PROMPT = """\
당신은 전문 이력서 작성가입니다. 주어진 전략과 템플릿 구조에 따라 최적화된 이력서를 Markdown으로 작성합니다.

작성 원칙:
1. 반드시 제공된 템플릿 섹션 순서와 구조를 따릅니다.
2. 지원자의 원본 이력서에 있는 사실만 사용합니다. 새로운 경험을 만들지 마세요.
3. 전략의 강조 포인트와 키워드를 자연스럽게 반영합니다.
4. 수치와 성과 중심으로 작성합니다 (예: "매출 30% 증가" > "매출 증가에 기여").
5. 각 경력 항목은 STAR 형식(Situation-Task-Action-Result)으로 작성합니다.
6. ATS 최적화를 위해 키워드를 자연스럽게 포함합니다.

응답은 반드시 아래 JSON 형식으로:
{
  "sections": [
    {"id": "섹션ID", "label": "섹션 라벨", "content": "마크다운 내용"}
  ],
  "full_markdown": "전체 이력서 마크다운"
}"""


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
    ) -> TailoredResume:
        """Generate a tailored resume based on strategy and template."""
        template_spec = self._format_template(template)
        strategy_spec = self._format_strategy(strategy)

        lang_instruction = ""
        if language == "en":
            lang_instruction = (
                "\n\n**[CRITICAL] Write the ENTIRE resume in English.** "
                "Translate all section labels and content to English. "
                "Keep technical terms as-is. Do NOT use Korean.\n"
            )

        prompt = f"""다음 전략과 템플릿에 따라 맞춤 이력서를 작성하세요.{lang_instruction}

## 템플릿 구조 (반드시 이 순서와 섹션을 따르세요)
{template_spec}

## 맞춤화 전략
{strategy_spec}

## 원본 이력서
{resume_text}

위 템플릿 구조의 각 섹션에 맞춰 이력서를 작성하세요. JSON 형식으로만 응답하세요."""

        data = await self.llm.generate_json(
            prompt=prompt,
            system=SYSTEM_PROMPT,
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
