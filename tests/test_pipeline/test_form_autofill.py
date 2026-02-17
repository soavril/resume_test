"""Tests for form_autofill._find_matching_answer (matching logic only, no Playwright)."""

import pytest

from resume_tailor.pipeline.form_autofill import _find_matching_answer


class TestFindMatchingAnswer:
    def test_find_matching_answer_exact(self):
        answers = [{"question": "자기소개를 해주세요", "answer": "저는 백엔드 개발자입니다."}]
        result = _find_matching_answer("자기소개를 해주세요", answers)
        assert result is not None
        assert result["answer"] == "저는 백엔드 개발자입니다."

    def test_find_matching_answer_substring(self):
        # label contains the question text as a substring
        answers = [{"question": "자기소개를 해주세요", "answer": "저는 개발자입니다."}]
        result = _find_matching_answer("Please: 자기소개를 해주세요 (500자 이내)", answers)
        assert result is not None

    def test_find_matching_answer_keyword_overlap(self):
        # label and question share 2+ words
        answers = [
            {"question": "지원동기 및 입사 포부를 작성해주세요", "answer": "포부 텍스트"}
        ]
        result = _find_matching_answer("지원동기 입사 후 계획 작성", answers)
        assert result is not None

    def test_find_matching_answer_no_match(self):
        answers = [{"question": "자기소개를 해주세요", "answer": "저는 개발자입니다."}]
        result = _find_matching_answer("학력 사항을 입력해주세요", answers)
        assert result is None

    def test_find_matching_answer_empty_list(self):
        result = _find_matching_answer("자기소개를 해주세요", [])
        assert result is None
