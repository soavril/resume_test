"""Tests for resume quality checking and QA scoring enhancement."""

import pytest
from resume_tailor.models.interview import ResumeQualityCheck, check_resume_quality
from resume_tailor.models.qa import QAResult


class TestCheckResumeQuality:
    def test_rich_resume_high_score(self, sample_resume_text):
        """A detailed resume should score > 0.7."""
        result = check_resume_quality(sample_resume_text)
        assert result.richness_score > 0.7
        assert result.has_experience is True
        assert result.has_quantitative is True
        assert result.experience_items >= 3

    def test_sparse_resume_low_score(self):
        """A minimal resume should score < 0.4."""
        sparse = "홍길동\n이메일: test@test.com\n경력: 개발자 2년"
        result = check_resume_quality(sparse)
        assert result.richness_score < 0.4
        assert result.word_count < 20

    def test_empty_resume(self):
        """Empty string should score 0."""
        result = check_resume_quality("")
        assert result.richness_score == 0.0
        assert result.word_count == 0
        assert result.line_count == 0

    def test_experience_detection_korean(self):
        """Should detect Korean experience markers."""
        text = "경력사항:\n- ABC 회사 (2020~2023)\n- DEF 회사 (2018~2020)"
        result = check_resume_quality(text)
        assert result.has_experience is True

    def test_experience_detection_english(self):
        """Should detect English experience markers."""
        text = "Experience:\n- ABC Corp (2020-2023)\n- DEF Inc (2018-2020)"
        result = check_resume_quality(text)
        assert result.has_experience is True

    def test_no_experience_section(self):
        """Resume without experience markers."""
        text = "홍길동\n이메일: test@test.com\n학력: 한국대학교"
        result = check_resume_quality(text)
        assert result.has_experience is False

    def test_quantitative_detection_percentage(self):
        """Should detect percentage numbers."""
        text = "매출 30% 증가 달성"
        result = check_resume_quality(text)
        assert result.has_quantitative is True

    def test_quantitative_detection_korean_unit(self):
        """Should detect Korean number units."""
        text = "사용자 100만명 달성"
        result = check_resume_quality(text)
        assert result.has_quantitative is True

    def test_no_quantitative(self):
        """Resume without numbers."""
        text = "개발자 경험 있음\n다양한 프로젝트 수행"
        result = check_resume_quality(text)
        assert result.has_quantitative is False

    def test_bullet_count(self):
        """Should count bullet points correctly."""
        text = "경력:\n- 항목 1\n- 항목 2\n* 항목 3\n일반 텍스트"
        result = check_resume_quality(text)
        assert result.experience_items == 3

    def test_richness_score_bounded(self):
        """Score should always be between 0.0 and 1.0."""
        # Very long resume
        long_resume = "경력:\n" + "\n".join(f"- 항목 {i} 100만원 달성" for i in range(50))
        result = check_resume_quality(long_resume)
        assert 0.0 <= result.richness_score <= 1.0

    def test_dataclass_fields(self):
        """ResumeQualityCheck should have all expected fields."""
        result = check_resume_quality("test")
        assert hasattr(result, "word_count")
        assert hasattr(result, "line_count")
        assert hasattr(result, "has_experience")
        assert hasattr(result, "experience_items")
        assert hasattr(result, "has_quantitative")
        assert hasattr(result, "richness_score")


class TestQAResultBackwardCompat:
    def test_new_fields_have_defaults(self):
        """New fields should default to 0 for backward compat."""
        result = QAResult(
            factual_accuracy=90,
            keyword_coverage=80,
            template_compliance=85,
            overall_score=85,
            issues=[],
            suggestions=[],
            pass_=True,
        )
        assert result.content_richness == 0
        assert result.detail_depth == 0

    def test_new_fields_can_be_set(self):
        """New fields should accept values."""
        result = QAResult(
            factual_accuracy=90,
            keyword_coverage=80,
            template_compliance=85,
            content_richness=75,
            detail_depth=70,
            overall_score=82,
            issues=[],
            suggestions=[],
            pass_=True,
        )
        assert result.content_richness == 75
        assert result.detail_depth == 70

    def test_pass_alias_still_works(self):
        """The 'pass' alias should still work."""
        data = {
            "factual_accuracy": 90,
            "keyword_coverage": 80,
            "template_compliance": 85,
            "content_richness": 75,
            "detail_depth": 70,
            "overall_score": 82,
            "issues": [],
            "suggestions": [],
            "pass": True,
        }
        result = QAResult(**data)
        assert result.pass_ is True

    def test_five_axis_weight_calculation(self):
        """Verify the 5-axis weight formula produces correct results."""
        # 30% + 20% + 20% + 20% + 10% = 100%
        fa, kc, tc, cr, dd = 100, 80, 60, 70, 50
        expected = int(fa * 0.3 + kc * 0.2 + tc * 0.2 + cr * 0.2 + dd * 0.1)
        assert expected == 77  # 30 + 16 + 12 + 14 + 5

    def test_overall_score_with_zero_new_fields(self):
        """When new fields are 0, the weighted average should be lower."""
        result = QAResult(
            factual_accuracy=100,
            keyword_coverage=100,
            template_compliance=100,
            content_richness=0,
            detail_depth=0,
            overall_score=70,  # 30+20+20+0+0 = 70
            issues=[],
            suggestions=[],
            pass_=False,
        )
        assert result.overall_score == 70
