"""Sentence refinement agent — generates alternative expressions for selected text."""

from __future__ import annotations

import logging

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.refinement import RefinementSuggestion

logger = logging.getLogger(__name__)

REFINE_SYSTEM = """\
당신은 이력서 문장 개선 전문가입니다.
주어진 문장에 대해 {num_alternatives}개의 대안을 제시합니다.

규칙:
1. 원문의 사실은 유지하되 표현만 변경
2. 각 대안은 서로 다른 개선 방향 (간결성, 임팩트, 키워드, 톤)
3. 채용공고 맥락에 맞는 개선을 우선
4. 원문보다 과장하지 않음
5. 동일 글자수 내외로 유지

JSON 배열로만 응답:
[{{"alternative": "...", "rationale": "...", "improvement_type": "conciseness|impact|keyword|tone"}}]"""


class SentenceRefiner:
    """Generate alternative expressions for a selected sentence in a resume."""

    def __init__(self, llm: LLMClient, model: str = "claude-haiku-4-5-20251001"):
        self.llm = llm
        self.model = model

    async def refine(
        self,
        selected_text: str,
        full_resume: str,
        jd_text: str,
        num_alternatives: int = 3,
        language: str = "ko",
    ) -> list[RefinementSuggestion]:
        """Generate alternative suggestions for the selected text.

        Returns an empty list on error or if selected_text is empty.
        """
        if not selected_text or not selected_text.strip():
            return []

        system = REFINE_SYSTEM.replace("{num_alternatives}", str(num_alternatives))

        prompt = f"""다음 이력서에서 선택된 문장의 대안을 {num_alternatives}개 제시하세요.

채용공고:
{jd_text}

전체 이력서:
{full_resume}

선택된 문장:
{selected_text}

{num_alternatives}개의 대안을 JSON 배열로 응답하세요."""

        try:
            data = await self.llm.generate_json(
                prompt=prompt,
                system=system,
                model=self.model,
            )
        except Exception:
            logger.exception("Sentence refinement LLM call failed")
            return []

        return self._parse_suggestions(data, num_alternatives)

    @staticmethod
    def _parse_suggestions(data, max_count: int) -> list[RefinementSuggestion]:
        """Parse LLM response into RefinementSuggestion list."""
        # Handle dict wrapper (e.g. {"suggestions": [...]})
        if isinstance(data, dict):
            for key in ("suggestions", "alternatives", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                return []

        if not isinstance(data, list):
            return []

        result = []
        for item in data[:max_count]:
            if not isinstance(item, dict):
                continue
            try:
                result.append(RefinementSuggestion(**item))
            except Exception:
                continue
        return result
