"""Extract application form questions from a URL or pasted text.

Supports:
  - URL → Playwright headless browser (handles SPA/JS-rendered pages)
  - Pasted text → regex-based question extraction
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FormQuestion:
    """A single question/field extracted from an application form."""
    label: str
    max_length: int | None = None
    field_type: str = "textarea"   # textarea, text, select, etc.
    options: list[str] | None = None
    section: str = ""              # e.g. "기본정보", "자기소개서"


async def extract_from_url(url: str) -> list[FormQuestion]:
    """Render a URL with Playwright and extract form questions."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # Wait a bit for dynamic content
        await page.wait_for_timeout(2000)

        # Extract all text content + form structure via JS
        form_data = await page.evaluate("""() => {
            const results = [];

            // Strategy 1: Find textareas with labels
            document.querySelectorAll('textarea').forEach(ta => {
                const maxLen = ta.maxLength > 0 ? ta.maxLength : null;
                // Find label: previous sibling, parent's label, aria-label, placeholder
                let label = '';

                // Check aria-label
                if (ta.getAttribute('aria-label')) {
                    label = ta.getAttribute('aria-label');
                }

                // Check for label element
                const id = ta.id;
                if (id) {
                    const labelEl = document.querySelector(`label[for="${id}"]`);
                    if (labelEl) label = labelEl.textContent.trim();
                }

                // Walk up to find nearest heading/label text
                if (!label) {
                    let el = ta.parentElement;
                    for (let i = 0; i < 5 && el; i++) {
                        const prev = el.previousElementSibling;
                        if (prev) {
                            const text = prev.textContent.trim();
                            if (text.length > 3 && text.length < 500) {
                                label = text;
                                break;
                            }
                        }
                        el = el.parentElement;
                    }
                }

                if (!label) label = ta.placeholder || '';

                if (label) {
                    results.push({
                        label: label,
                        maxLength: maxLen,
                        type: 'textarea'
                    });
                }
            });

            // Strategy 2: Find labeled input fields
            document.querySelectorAll('label').forEach(label => {
                const text = label.textContent.trim();
                if (!text || text.length < 2) return;

                // Check if this label already captured via textarea
                if (results.some(r => r.label === text)) return;

                const forId = label.getAttribute('for');
                let field = null;
                if (forId) field = document.getElementById(forId);
                if (!field) field = label.querySelector('input, textarea, select');
                if (!field) {
                    const parent = label.closest('.form-group, .field, [class*=field], [class*=form]');
                    if (parent) field = parent.querySelector('input, textarea, select');
                }

                if (field) {
                    const maxLen = field.maxLength > 0 ? field.maxLength : null;
                    results.push({
                        label: text,
                        maxLength: maxLen,
                        type: field.tagName.toLowerCase()
                    });
                }
            });

            return results;
        }""")

        # Also grab full visible text for LLM-based extraction if needed
        visible_text = await page.evaluate("""() => {
            return document.body.innerText;
        }""")

        await browser.close()

    # Filter and deduplicate results
    questions = []
    seen = set()
    for item in form_data:
        label = item["label"].strip()
        if label in seen or len(label) < 2:
            continue

        # Skip script content, CSS, generic placeholders
        if any(skip in label.lower() for skip in [
            "window.", "function ", "datalayer", "<script",
            "내용을 입력해", "선택해주세요", "example@",
        ]):
            continue

        # Skip very generic short labels that are just field names, not questions
        if len(label) < 5 and not _QUESTION_KEYWORDS.search(label):
            continue

        # Skip if it's just "내용 (N자 이내)" — likely a placeholder for a named field above
        if re.match(r"^내용\s*\(", label):
            # Try to attach max_length to the previous question
            maxlen = _extract_char_limit(label)
            if maxlen and questions:
                questions[-1].max_length = maxlen
            continue

        seen.add(label)
        questions.append(FormQuestion(
            label=label,
            max_length=item.get("maxLength") or _extract_char_limit(label),
            field_type=item.get("type", "textarea"),
        ))

    # If Playwright JS didn't find textarea questions, parse the visible text
    if len([q for q in questions if q.field_type == "textarea"]) < 1:
        text_questions = parse_text(visible_text)
        for tq in text_questions:
            if tq.label not in seen:
                questions.append(tq)
                seen.add(tq.label)

    return questions


def extract_from_url_sync(url: str) -> list[FormQuestion]:
    """Synchronous wrapper for extract_from_url."""
    import asyncio
    return asyncio.run(extract_from_url(url))


def parse_text(text: str) -> list[FormQuestion]:
    """Parse pasted text to extract questions.

    Handles formats like:
    - Numbered: "1. 자기소개 (500자 이내)"
    - Bulleted: "- 지원동기"
    - Labeled: "지원동기:"
    - Bracketed: "[자기소개]"
    - Lines with character counters: "0/1,000"
    - Lines ending with ? or containing common keywords
    """
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    questions: list[FormQuestion] = []
    seen: set[str] = set()

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if next line is a character counter like "0/1,000" or "0/10,000"
        char_limit = None
        if i + 1 < len(lines):
            counter_match = re.match(r"^(\d+)\s*/\s*([\d,]+)$", lines[i + 1])
            if counter_match:
                char_limit = int(counter_match.group(2).replace(",", ""))

        q = _parse_question_line(line, override_max_length=char_limit)
        if q and q.label not in seen:
            questions.append(q)
            seen.add(q.label)
            if char_limit:
                i += 1  # skip the counter line

        i += 1

    return questions


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_QUESTION_KEYWORDS = re.compile(
    r"(자기소개|지원동기|지원사유|경력.*기술|프로젝트|역량|강점|약점|목표|계획|"
    r"성장|성과|협업|리더십|problem|motivation|strength|experience|introduction|"
    r"입사\s*후|포부|비전|가치관|직무|기여|도전|keyword|키워드|"
    r"뛰어난|표현|서술|작성)",
    re.IGNORECASE,
)


def _parse_question_line(line: str, override_max_length: int | None = None) -> FormQuestion | None:
    """Try to parse a single line as a question."""
    if len(line) < 3 or len(line) > 500:
        return None

    # Skip obvious non-question lines
    if re.match(r"^(이름|연락처|이메일|성별|생년월일|우편번호|선택해주세요|내용을 입력|검색)$", line):
        return None
    if re.match(r"^\d+\s*/\s*[\d,]+$", line):  # character counter
        return None

    maxlen = override_max_length or _extract_char_limit(line)

    # Long descriptive question (common in Korean application forms)
    if len(line) > 20 and _QUESTION_KEYWORDS.search(line):
        return FormQuestion(label=line, max_length=maxlen, field_type="textarea")

    # Numbered section header: "1. 기본정보" — skip these
    m = re.match(r"^\d+\.\s*(.+)", line)
    if m:
        content = m.group(1)
        if len(content) < 6 and not _QUESTION_KEYWORDS.search(content):
            return None  # section header like "1. 기본정보"
        if _QUESTION_KEYWORDS.search(content):
            return FormQuestion(label=content, max_length=maxlen)

    # Question ending with ?
    if line.endswith("?") or line.endswith("?"):
        return FormQuestion(label=line, max_length=maxlen)

    return None


def _extract_char_limit(text: str) -> int | None:
    """Extract character limit from text like '(1,000자 내외)' or 'max 1000'."""
    m = re.search(r"([\d,]+)\s*자\s*(이내|내외|이하|제한|까지)?", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"max\w*\s*(\d{2,5})", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None
