"""Agent 5: QA Reviewer - Validates generated resume for accuracy and quality."""

from __future__ import annotations

import logging

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.qa import QAResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
당신은 이력서 품질 검수 전문가입니다. 생성된 이력서를 원본과 비교하여 사실 정확성, 키워드 커버리지, 템플릿 준수율을 평가합니다.

평가 기준:
1. **사실 정확성 (factual_accuracy)**: 원본에 없는 경력, 기술, 수치가 추가되었는지 확인
2. **키워드 커버리지 (keyword_coverage)**: 채용공고의 핵심 키워드가 이력서에 포함되었는지 확인
3. **템플릿 준수 (template_compliance)**: 요청된 섹션 구조를 따르는지 확인

반드시 아래 JSON 형식으로만 응답하세요:
{
  "factual_accuracy": 0-100,
  "keyword_coverage": 0-100,
  "template_compliance": 0-100,
  "overall_score": 0-100,
  "issues": ["발견된 문제점 1", "문제점 2"],
  "suggestions": ["개선 제안 1", "제안 2"],
  "suggestion_examples": ["제안 1에 대한 구체적 예시 문장", "제안 2에 대한 구체적 예시 문장"],
  "pass": true/false
}

suggestion_examples 작성 규칙:
- suggestions와 1:1 대응 (같은 인덱스)
- 각 예시는 이력서에 바로 넣을 수 있는 구체적 문장으로 작성
- 예: suggestion이 "Python 키워드를 추가하세요"이면, example은 "Python 3.11 기반 REST API 서버 개발 및 운영 (일 평균 10만 요청 처리)"

채점 기준:
- factual_accuracy: 원본에 없는 정보가 있으면 -20점/건
- keyword_coverage: (포함된 키워드 수 / 총 키워드 수) × 100
- template_compliance: 필수 섹션 누락 시 -20점/건
- overall_score: 세 점수의 가중 평균 (정확성 40%, 키워드 30%, 템플릿 30%)
- pass: overall_score >= 80"""


class QAReviewer:
    def __init__(self, llm: LLMClient, model: str = "claude-haiku-4-5-20251001"):
        self.llm = llm
        self.model = model

    async def review(
        self,
        generated_resume: str,
        original_resume: str,
        jd_text: str,
    ) -> QAResult:
        """Review a generated resume against the original and JD."""
        logger.info("Reviewing resume quality...")
        prompt = f"""다음 생성된 이력서를 검수하세요.

## 생성된 이력서
{generated_resume}

## 원본 이력서
{original_resume}

## 채용공고
{jd_text}

위 평가 기준에 따라 점수를 매기고 JSON 형식으로만 응답하세요."""

        data = await self.llm.generate_json(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=self.model,
        )

        # Handle "pass" being a Python keyword
        if "pass" in data and "pass_" not in data:
            data["pass_"] = data.pop("pass")

        # Defensive padding: ensure suggestion_examples matches suggestions length
        suggestions = data.get("suggestions", [])
        examples = data.get("suggestion_examples", [])
        if len(examples) < len(suggestions):
            logger.warning(
                "LLM returned %d suggestion_examples for %d suggestions; padding with empty strings",
                len(examples), len(suggestions),
            )
            data["suggestion_examples"] = examples + [""] * (len(suggestions) - len(examples))

        return QAResult(**data)
