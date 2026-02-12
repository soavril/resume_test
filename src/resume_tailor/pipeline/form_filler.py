"""Generate tailored answers for application form questions."""

from __future__ import annotations

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.models.resume import TailoredResume
from resume_tailor.parsers.form_parser import FormQuestion
from resume_tailor.utils.json_parser import extract_json


FORM_FILLER_SYSTEM = """\
당신은 채용 지원서 작성 전문가입니다.

주어진 이력서 내용과 채용공고를 바탕으로, 지원서 문항에 맞는 답변을 작성합니다.

규칙:
1. 이력서에 있는 사실만 사용하세요. 없는 경험을 만들지 마세요.
2. 채용공고의 요구사항과 이력서 내용을 매칭하여 강조하세요.
3. 구체적인 수치와 성과를 포함하세요.
4. **글자수 제한은 절대 위반 금지입니다.**
   - 제한이 N자이면, 반드시 N자 미만으로 작성하세요.
   - 글자수를 세면서 작성하세요. 초과하느니 짧게 쓰는 것이 낫습니다.
   - 마크다운 서식(#, **, -, ```) 없이 순수 텍스트로 작성하세요. 서식 문자도 글자수에 포함됩니다.
5. 한국어로 작성하되, 기술 용어는 영어 그대로 사용하세요.
6. 자연스럽고 진정성 있는 톤으로 작성하세요.
7. 각 문항의 의도를 파악하여 적절한 구조로 답변하세요."""


STRUCTURED_EXTRACTOR_SYSTEM = """\
당신은 이력서에서 구조화된 정보를 추출하는 전문가입니다.
이력서 텍스트를 읽고, 채용 지원서의 각 필드에 채울 수 있는 정보를 JSON으로 추출합니다.
이력서에 없는 정보는 null로 남기세요. 절대 만들어내지 마세요."""


async def generate_form_answers(
    llm: LLMClient,
    questions: list[FormQuestion],
    resume: TailoredResume,
    jd_text: str = "",
    company_name: str = "",
    language: str = "ko",
) -> list[dict]:
    """Generate answers for each form question.

    Returns list of {"question": str, "answer": str, "char_count": int}
    """
    results = []

    for q in questions:
        answer = await _answer_question(
            llm=llm,
            question=q,
            resume=resume,
            jd_text=jd_text,
            company_name=company_name,
            language=language,
        )

        # Hard truncate if still over limit
        if q.max_length and len(answer) > q.max_length:
            answer = _smart_truncate(answer, q.max_length)

        results.append({
            "question": q.label,
            "answer": answer,
            "char_count": len(answer),
            "max_length": q.max_length,
        })

    return results


async def extract_structured_fields(
    llm: LLMClient,
    resume: TailoredResume,
    form_fields: list[str] | None = None,
) -> dict:
    """Extract structured data from resume for form filling."""
    fields_hint = ""
    if form_fields:
        fields_hint = f"\n\n이 지원서에 있는 필드 목록: {', '.join(form_fields)}"

    prompt = f"""다음 이력서에서 구조화된 정보를 JSON으로 추출하세요.{fields_hint}

## 이력서
{resume.full_markdown}

아래 형식으로 추출하세요:
{{
  "personal": {{
    "name": "이름",
    "email": "이메일",
    "phone": "연락처",
    "military_status": "병역구분 (해당시)"
  }},
  "career": [
    {{
      "company": "회사명",
      "position": "직급/직책",
      "department": "근무부서",
      "employment_type": "정규직/계약직 등",
      "start_date": "YYYY.MM",
      "end_date": "YYYY.MM 또는 현재",
      "is_current": true/false,
      "description": "담당업무 요약 1줄"
    }}
  ],
  "education": [
    {{
      "school": "학교명",
      "degree": "학사/석사/박사",
      "major": "전공",
      "start_date": "YYYY.MM",
      "end_date": "YYYY.MM"
    }}
  ],
  "certifications": [
    {{
      "name": "자격증/수상명",
      "type": "자격증 또는 수상",
      "issuer": "발급기관",
      "date": "YYYY"
    }}
  ],
  "languages": [
    {{
      "language": "언어",
      "test": "시험명",
      "score": "점수/급",
      "institution": "주최기관"
    }}
  ],
  "skills": [
    {{
      "name": "프로그램/기술명",
      "category": "프로그래밍/오피스/기타",
      "level": "상/중/하",
      "duration": "N년"
    }}
  ]
}}

이력서에 없는 항목은 빈 배열이나 null로 남기세요."""

    data = await llm.generate_json(
        prompt=prompt,
        system=STRUCTURED_EXTRACTOR_SYSTEM,
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
    )
    return data


async def _answer_question(
    llm: LLMClient,
    question: FormQuestion,
    resume: TailoredResume,
    jd_text: str,
    company_name: str,
    language: str = "ko",
) -> str:
    """Generate an answer for a single question."""
    char_limit_note = ""
    if question.max_length:
        # Target 75% to leave comfortable margin
        target = int(question.max_length * 0.75)
        hard_max = question.max_length
        char_limit_note = (
            f"\n\n**[절대 규칙] 글자수 제한: {hard_max}자**\n"
            f"- 목표: {target}자 내외로 작성\n"
            f"- 절대 {hard_max}자를 넘기지 마세요\n"
            f"- 마크다운(#, **, -)을 사용하지 마세요 — 순수 텍스트만\n"
            f"- 짧더라도 제한 내에 맞추는 것이 최우선입니다"
        )

    jd_section = ""
    if jd_text:
        jd_section = f"\n\n## 채용공고\n{jd_text[:3000]}"

    company_section = ""
    if company_name:
        company_section = f"\n지원 회사: {company_name}"

    lang_instruction = ""
    if language == "en":
        lang_instruction = "\n\n**[CRITICAL] Write the answer in English. Do NOT use Korean.**"

    prompt = f"""다음 지원서 문항에 대한 답변을 작성하세요.{lang_instruction}

## 문항
{question.label}{char_limit_note}

## 내 이력서
{resume.full_markdown}{jd_section}{company_section}

위 정보를 바탕으로 이 문항에 맞는 답변만 작성하세요. 다른 설명 없이 답변 텍스트만 출력하세요."""

    resp = await llm.generate(
        prompt=prompt,
        system=FORM_FILLER_SYSTEM,
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        temperature=0.3,
    )
    return resp.text.strip()


def _smart_truncate(text: str, max_length: int) -> str:
    """Truncate text at the last sentence boundary before max_length."""
    if len(text) <= max_length:
        return text

    # Try to cut at last sentence ending (. or 다.)
    truncated = text[:max_length]

    # Find last sentence boundary
    for ending in [".\n", "다.\n", "다. ", "습니다. ", "합니다. ", ". "]:
        last_pos = truncated.rfind(ending)
        if last_pos > max_length * 0.5:  # at least keep 50%
            return truncated[:last_pos + len(ending)].rstrip()

    # Fallback: cut at last space
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.5:
        return truncated[:last_space].rstrip()

    return truncated.rstrip()
