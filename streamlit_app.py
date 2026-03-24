"""Streamlit Web UI for resume-tailor.

Two modes:
  A) Resume Tailoring  — PDF/DOCX resume + company + JD → tailored MD
  B) Form Answer Gen   — resume + questions text → per-question answers + .txt download
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

import concurrent.futures

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

_ASYNC_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _run_async(coro):
    """Run an async coroutine in a clean thread with its own event loop.

    Uses a plain thread (no Streamlit context) to avoid both sniffio
    detection errors and Tornado event loop deadlocks.
    """
    return _ASYNC_POOL.submit(asyncio.run, coro).result()


# Streamlit Cloud: sync st.secrets → os.environ so backend clients can read them
for key in ("ANTHROPIC_API_KEY", "TAVILY_API_KEY"):
    if key not in os.environ:
        try:
            os.environ[key] = st.secrets[key]
        except Exception:
            pass

from resume_tailor.cache.company_cache import CompanyCache
from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.clients.search_client import SearchClient
from resume_tailor.config import load_config
from resume_tailor.models.resume import ResumeSection, TailoredResume
from resume_tailor.parsers.form_parser import parse_text
from resume_tailor.parsers.resume_parser import clean_markdown, parse_resume
from resume_tailor.pipeline.form_filler import (
    extract_structured_fields,
    generate_form_answers,
)
from resume_tailor.pipeline.orchestrator import PipelineOrchestrator
from resume_tailor.parsers.jd_image_parser import extract_jd_from_file
from resume_tailor.templates.docx_renderer import (
    fill_docx_template,
    list_docx_placeholders,
)
from resume_tailor.templates.smart_filler import smart_fill_docx

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Resume Tailor",
    page_icon=":page_facing_up:",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Global CSS — subtle polish without external packages
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    /* Typography & base */
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Login page centering */
    .login-container {
        max-width: 440px;
        margin: 80px auto 0 auto;
        padding: 0 24px;
    }
    .login-brand {
        font-size: 1.75rem;
        font-weight: 600;
        letter-spacing: -0.03em;
        color: #0f172a;
        margin-bottom: 6px;
        font-family: 'DM Sans', sans-serif;
    }
    .login-tagline {
        font-size: 0.95rem;
        color: #475569;
        line-height: 1.6;
        margin-bottom: 32px;
    }
    .login-desc {
        font-size: 0.875rem;
        color: #64748b;
        background: #f8fafc;
        border-left: 3px solid #e2e8f0;
        padding: 12px 16px;
        border-radius: 0 6px 6px 0;
        margin-bottom: 28px;
        line-height: 1.7;
    }

    /* Step guide cards */
    .step-guide {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 20px 24px;
        margin: 16px 0;
    }
    .step-guide h4 {
        font-size: 0.875rem;
        font-weight: 600;
        color: #334155;
        margin-bottom: 14px;
        letter-spacing: 0.02em;
        text-transform: uppercase;
    }
    .step-item {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        margin-bottom: 12px;
    }
    .step-num {
        background: #0f172a;
        color: white;
        border-radius: 50%;
        width: 22px;
        height: 22px;
        min-width: 22px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.75rem;
        font-weight: 600;
        margin-top: 1px;
    }
    .step-text {
        font-size: 0.9rem;
        color: #475569;
        line-height: 1.5;
    }
    .step-text strong {
        color: #0f172a;
        font-weight: 600;
    }

    /* Success banner */
    .success-banner {
        background: #f0fdf4;
        border: 1px solid #bbf7d0;
        border-radius: 8px;
        padding: 16px 20px;
        margin: 12px 0 20px 0;
    }
    .success-banner .score {
        font-size: 1.5rem;
        font-weight: 700;
        color: #15803d;
        letter-spacing: -0.02em;
    }
    .success-banner .meta {
        font-size: 0.85rem;
        color: #166534;
        margin-top: 4px;
    }

    /* Download section */
    .download-primary [data-testid="stDownloadButton"] button {
        font-size: 1rem;
        font-weight: 600;
        padding: 12px 24px;
    }

    /* Time estimate notice */
    .time-estimate {
        font-size: 0.85rem;
        color: #64748b;
        background: #fafafa;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        padding: 8px 14px;
        margin-bottom: 12px;
        display: inline-block;
    }

    /* Sidebar upload hint */
    .sidebar-hint {
        background: #fffbeb;
        border: 1px solid #fde68a;
        border-radius: 6px;
        padding: 12px 14px;
        font-size: 0.875rem;
        color: #78350f;
        line-height: 1.6;
        margin: 8px 0 16px 0;
    }

    /* Section dividers */
    hr {
        border: none;
        border-top: 1px solid #e2e8f0;
        margin: 24px 0;
    }

    /* Compact metric display */
    .inline-meta {
        display: inline-flex;
        gap: 16px;
        font-size: 0.875rem;
        color: #475569;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 8px 16px;
        margin-bottom: 16px;
    }
    .inline-meta span {
        font-weight: 600;
        color: #0f172a;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

try:
    APP_PASSWORD = st.secrets["APP_PASSWORD"]
except Exception:
    APP_PASSWORD = os.environ.get("APP_PASSWORD", "resume2026")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown(
        """
        <div class="login-container">
          <div class="login-brand">Resume Tailor</div>
          <div class="login-tagline">채용공고에 맞게 이력서를 자동으로 최적화합니다.</div>
          <div class="login-desc">
            회사 리서치 · 채용공고 분석 · 맞춤 이력서 작성 · 품질 검토까지<br>
            5단계 AI 파이프라인이 60~90초 안에 처리합니다.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_left, col_center, col_right = st.columns([1, 2, 1])
    with col_center:
        pw = st.text_input("접근 코드", type="password", placeholder="비밀번호를 입력하세요", label_visibility="collapsed")
        if pw and pw == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        elif pw:
            st.error("접근 코드가 올바르지 않습니다. 다시 확인해주세요.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — shared across modes
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("**Resume Tailor**")
    st.caption("AI 이력서 맞춤 자동화")

    mode = st.radio(
        "모드 선택",
        ["이력서 맞춤 생성", "지원서 답변 생성"],
        index=0,
    )

    st.divider()

    language = st.radio(
        "생성 언어",
        ["한국어", "English"],
        index=0,
        horizontal=True,
    )
    lang_code = "ko" if language == "한국어" else "en"

    st.divider()

    st.markdown("**1단계 — 내 이력서 업로드**")
    resume_file = st.file_uploader(
        "이력서 파일",
        type=["pdf", "docx", "doc", "txt", "md"],
        help="PDF, DOCX, TXT 또는 MD 파일 (10MB 이하)",
        label_visibility="collapsed",
    )
    if resume_file:
        st.success(f"{resume_file.name} 업로드 완료")
    if resume_file and resume_file.size > 10 * 1024 * 1024:
        st.error("이력서 파일 크기가 10MB를 초과합니다. 10MB 이하 파일을 사용해주세요.")
        st.stop()



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_upload_to_tmp(uploaded_file) -> Path:
    """Save a Streamlit UploadedFile to a temp file and return its Path."""
    suffix = Path(uploaded_file.name).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    return Path(tmp.name)


def _parse_uploaded_resume(uploaded_file) -> str:
    """Parse an uploaded resume file to plain text."""
    tmp_path = _save_upload_to_tmp(uploaded_file)
    try:
        return parse_resume(str(tmp_path))
    finally:
        tmp_path.unlink(missing_ok=True)


def _get_config():
    return load_config()


def _get_clients():
    config = _get_config()
    try:
        llm = LLMClient(timeout=config.llm.timeout)
    except Exception as e:
        raise RuntimeError(f"LLM 클라이언트 초기화 실패 — ANTHROPIC_API_KEY를 확인하세요: {e}") from e
    try:
        search = SearchClient()
    except Exception as e:
        raise RuntimeError(f"검색 클라이언트 초기화 실패 — TAVILY_API_KEY를 확인하세요: {e}") from e
    return llm, search


# ---------------------------------------------------------------------------
# Mode A: Resume Tailoring
# ---------------------------------------------------------------------------


def _mode_resume_tailor():
    st.header("이력서 맞춤 생성")
    st.markdown("회사 채용공고에 최적화된 이력서를 자동 생성합니다.")

    # F2: Sidebar upload awareness — shown when resume is not yet uploaded
    if not resume_file:
        st.markdown(
            """
            <div class="sidebar-hint">
              <strong>왼쪽 사이드바에서 이력서를 먼저 업로드하세요.</strong><br>
              PDF, DOCX, TXT, MD 형식을 지원합니다. (10MB 이하)
            </div>
            """,
            unsafe_allow_html=True,
        )

    company_name = st.text_input("2단계 — 회사명", placeholder="예: 삼성전자", max_chars=100)

    role_preset = st.radio(
        "직군",
        ["자동 감지", "개발/엔지니어링", "비즈니스/전략"],
        index=0,
        horizontal=True,
        help="채용공고를 분석하여 직군을 자동 감지합니다. 수동 선택도 가능합니다.",
    )
    PRESET_MAP = {"자동 감지": "auto", "개발/엔지니어링": "tech", "비즈니스/전략": "business"}
    role_category = PRESET_MAP[role_preset]

    # Initialize session state for extracted JD text
    if "jd_text_extracted" not in st.session_state:
        st.session_state.jd_text_extracted = ""

    jd_text = st.text_area(
        "3단계 — 채용공고 붙여넣기",
        value=st.session_state.jd_text_extracted,
        height=200,
        placeholder="채용공고 전문을 여기에 붙여넣으세요...",
        max_chars=10000,
    )

    with st.expander("이미지/PDF에서 채용공고 추출", expanded=False):
        jd_image_file = st.file_uploader(
            "이미지 또는 PDF 업로드",
            type=["png", "jpg", "jpeg", "pdf"],
            help="채용공고 스크린샷 또는 PDF (5MB 이하)",
        )
        if jd_image_file and jd_image_file.size > 5 * 1024 * 1024:
            st.error("JD 파일 크기가 5MB를 초과합니다.")
            st.stop()
        if jd_image_file and st.button("텍스트 추출"):
            with st.spinner("텍스트 추출 중..."):
                try:
                    llm_for_ocr = LLMClient(timeout=_get_config().llm.timeout)
                    extracted = _run_async(
                        extract_jd_from_file(
                            llm_for_ocr,
                            jd_image_file.getvalue(),
                            jd_image_file.name,
                        )
                    )
                    st.session_state.jd_text_extracted = extracted
                    st.rerun()
                except Exception:
                    logger.exception("JD image extraction failed")
                    st.error("채용공고 텍스트 추출에 실패했습니다. 이미지가 선명한지 확인하거나, 텍스트를 직접 복사해서 붙여넣으세요.")

    template_file = st.file_uploader(
        "DOCX 양식 업로드 (선택)",
        type=["docx"],
        help="이력서 양식 DOCX 파일 — 생성된 내용으로 양식을 채워 다운로드합니다 (10MB 이하).",
    )
    if template_file and template_file.size > 10 * 1024 * 1024:
        st.error("양식 파일 크기가 10MB를 초과합니다.")
        template_file = None

    # Validation
    can_run = bool(resume_file and company_name and jd_text)

    if can_run:
        st.markdown(
            '<div class="time-estimate">생성에 약 60~90초가 소요됩니다. 생성 중에는 창을 닫지 마세요.</div>',
            unsafe_allow_html=True,
        )

    if st.button("생성 시작", type="primary", disabled=not can_run):
        if not resume_file:
            st.error("이력서 파일을 사이드바에서 업로드하세요.")
            return

        resume_text = _parse_uploaded_resume(resume_file)

        # Resume quality check — disabled until InterviewAgent (Phase 6C) is ready
        # from resume_tailor.models.interview import check_resume_quality
        # quality = check_resume_quality(resume_text)
        # if quality.richness_score < 0.4:
        #     details = []
        #     if quality.experience_items < 3:
        #         details.append(f"경력 항목: {quality.experience_items}개 (권장: 3개 이상)")
        #     if not quality.has_quantitative:
        #         details.append("정량적 성과: 없음 (권장: 매출, 사용자 수 등 수치 포함)")
        #     if quality.word_count < 150:
        #         details.append(f"분량: {quality.word_count}단어 (권장: 150단어 이상)")
        #     warning_msg = "이력서 내용이 다소 간략합니다.\n" + "\n".join(f"- {d}" for d in details)
        #     st.warning(warning_msg)

        config = _get_config()
        llm, search = _get_clients()

        # Check company cache
        cache = CompanyCache(
            db_path=config.cache.resolved_db_path,
            ttl_days=config.cache.ttl_days,
        )
        cached_profile = cache.get(company_name)

        orchestrator = PipelineOrchestrator(
            llm,
            search,
            haiku_model=config.llm.haiku_model,
            sonnet_model=config.llm.sonnet_model,
            qa_threshold=config.pipeline.qa_threshold,
            max_rewrites=config.pipeline.max_rewrites,
        )

        # Clear stale state from previous runs
        for key in (
            "refined_resume_md", "refinement_suggestions", "refinement_original",
            "pipeline_result", "download_md",
            "safe_fname", "result_jd_text",
            "result_template", "result_template_name",
            "filled_template_bytes", "filled_template_name",
        ):
            st.session_state.pop(key, None)

        try:
            with st.spinner("이력서 생성 중... (약 60~90초 소요)"):
                result = _run_async(
                    orchestrator.run(
                        company_name=company_name,
                        jd_text=jd_text,
                        resume_text=resume_text,
                        company_profile=cached_profile,
                        language=lang_code,
                        role_category=role_category,
                    )
                )
        except RuntimeError as e:
            logger.exception("Resume tailoring pipeline failed")
            st.error(str(e))
            return
        except Exception as e:
            logger.exception("Resume tailoring pipeline failed")
            st.error(
                "이력서 생성 중 오류가 발생했습니다. "
                "잠시 후 다시 시도하거나, 채용공고 내용이 너무 짧거나 이미지만으로 구성된 경우 텍스트를 직접 붙여넣어 주세요."
            )
            with st.expander("오류 상세"):
                st.code(f"{type(e).__name__}: {e}")
            return
        st.success(f"완료! 점수: {result.qa.overall_score}점, 소요: {result.elapsed_seconds:.1f}초")

        # Save usage log
        try:
            from resume_tailor.logging.usage_store import UsageStore
            from resume_tailor.logging.models import UsageLog
            store = UsageStore()
            log = UsageLog(
                session_id=st.session_state.get("session_id", "anonymous"),
                mode="resume_tailor",
                company_name=company_name,
                job_title=result.job.title if result.job else None,
                qa_score=result.qa.overall_score if result.qa else None,
                rewrites=result.rewrites,
                elapsed_seconds=result.elapsed_seconds,
                total_input_tokens=result.total_input_tokens,
                total_output_tokens=result.total_output_tokens,
                search_count=result.search_count,
                estimated_cost_usd=result.estimated_cost_usd,
                role_category=result.metadata.get("role_category"),
                language=lang_code,
            )
            store.save_log(log)
        except Exception:
            logger.exception("Failed to save usage log")

        # Cache company profile
        if not cached_profile:
            cache.put(company_name, result.company)

        # Save markdown internally (best-effort; Cloud filesystem may be read-only)
        download_md = clean_markdown(result.resume.full_markdown)
        try:
            output_dir = Path("./output")
            output_dir.mkdir(parents=True, exist_ok=True)
            md_path = output_dir / f"{company_name}_{result.job.title}.md".replace(" ", "_")
            md_path.write_text(download_md, encoding="utf-8")
        except OSError:
            logger.debug("Could not write markdown to disk (read-only filesystem)")

        safe_fname = f"{company_name}_{result.job.title}".replace(" ", "_")

        # Persist to session_state so results survive rerun
        st.session_state["pipeline_result"] = result
        st.session_state["download_md"] = download_md
        st.session_state["safe_fname"] = safe_fname
        st.session_state["result_jd_text"] = jd_text

        # Save template bytes for post-pipeline fill (DOCX)
        if template_file:
            st.session_state["result_template"] = template_file.getvalue()
            st.session_state["result_template_name"] = template_file.name

    # -----------------------------------------------------------------------
    # Render results from session_state (survives rerun after download click)
    # -----------------------------------------------------------------------
    if "pipeline_result" in st.session_state:
        result = st.session_state["pipeline_result"]
        download_md = st.session_state.get("refined_resume_md", st.session_state["download_md"])
        safe_fname = st.session_state["safe_fname"]

        # Show detected role and completion status — polished success banner
        role_labels = {"tech": "개발/엔지니어링", "business": "비즈니스/전략", "design": "디자인", "general": "일반"}
        detected = result.metadata.get("role_category", "general")
        role_label = role_labels.get(detected, detected)
        score = result.qa.overall_score
        elapsed = result.elapsed_seconds
        st.markdown(
            f"""
            <div class="success-banner">
              <div class="score">품질 점수 {score}점</div>
              <div class="meta">
                직군: {role_label} &nbsp;|&nbsp; 소요: {elapsed:.1f}초
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # PDF theme and download
        from resume_tailor.export.pdf_renderer import render_pdf, AVAILABLE_THEMES, render_html_preview

        theme_labels = {"professional": "프로페셔널", "modern": "모던", "minimal": "미니멀"}
        selected_theme = st.selectbox(
            "PDF 테마",
            AVAILABLE_THEMES,
            format_func=lambda t: theme_labels.get(t, t),
        )

        try:
            pdf_bytes = render_pdf(download_md, theme=selected_theme, title=f"{safe_fname}")
            pdf_available = True
        except Exception:
            logger.exception("PDF rendering failed")
            pdf_available = False

        # Download section — PDF primary (large), MD secondary (small)
        if pdf_available:
            st.download_button(
                label="PDF 다운로드",
                data=pdf_bytes,
                file_name=f"{safe_fname}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        else:
            st.warning("PDF 렌더링에 실패했습니다. 아래 MD 파일을 다운로드하거나 이력서 내용을 복사하세요.")

        col_md, col_spacer = st.columns([1, 2])
        with col_md:
            st.download_button(
                label="마크다운(.md) 다운로드",
                data=download_md.encode("utf-8"),
                file_name=f"{safe_fname}.md",
                mime="text/markdown",
                type="secondary",
            )

        with st.expander("PDF 미리보기", expanded=False):
            preview_html = render_html_preview(download_md, theme=selected_theme, title=safe_fname)
            st.components.v1.html(preview_html, height=600, scrolling=True)

        # Display results in tabs
        tab_resume, tab_company = st.tabs(
            ["생성된 이력서", "회사 분석"]
        )

        with tab_resume:
            # Use refined version if user applied an alternative
            current_md = st.session_state.get("refined_resume_md", result.resume.full_markdown)
            st.markdown(current_md)

            # Sentence refinement UI
            st.divider()
            st.subheader("문장 수정 추천")
            selected = st.text_area(
                "수정하고 싶은 문장을 붙여넣으세요",
                height=80,
                max_chars=500,
                key="refine_input",
            )
            _refine_jd = st.session_state.get("result_jd_text", "")
            if st.button("대안 생성", key="btn_refine") and selected.strip():
                from resume_tailor.pipeline.sentence_refiner import SentenceRefiner

                _refine_llm = LLMClient(timeout=_get_config().llm.timeout)
                refiner = SentenceRefiner(_refine_llm)
                with st.spinner("대안 생성 중..."):
                    try:
                        suggestions = _run_async(
                            refiner.refine(
                                selected_text=selected,
                                full_resume=current_md,
                                jd_text=_refine_jd,
                            )
                        )
                    except Exception:
                        logger.exception("Sentence refinement failed")
                        st.error("대안 생성에 실패했습니다.")
                        suggestions = []

                if suggestions:
                    st.session_state["refinement_suggestions"] = [
                        s.model_dump() for s in suggestions
                    ]
                    st.session_state["refinement_original"] = selected

            # Display saved suggestions
            if "refinement_suggestions" in st.session_state:
                original = st.session_state.get("refinement_original", "")
                for i, sug_dict in enumerate(
                    st.session_state["refinement_suggestions"]
                ):
                    type_labels = {
                        "conciseness": "간결성",
                        "impact": "임팩트",
                        "keyword": "키워드",
                        "tone": "톤",
                    }
                    imp_type = sug_dict.get("improvement_type", "")
                    label = type_labels.get(imp_type, imp_type)

                    with st.container(border=True):
                        st.markdown(f"**대안 {i + 1}** -- {label}")
                        st.info(sug_dict["alternative"])
                        st.caption(sug_dict["rationale"])
                        if st.button("이 대안 적용", key=f"apply_{i}"):
                            current = st.session_state.get(
                                "refined_resume_md",
                                result.resume.full_markdown,
                            )
                            st.session_state["refined_resume_md"] = current.replace(
                                original, sug_dict["alternative"], 1
                            )
                            del st.session_state["refinement_suggestions"]
                            st.session_state.pop("refinement_original", None)
                            st.rerun()

        with tab_company:
            cp = result.company
            st.subheader(f"{cp.name} ({cp.industry})")
            st.write(cp.description)
            st.markdown(f"**기업문화**: {', '.join(cp.culture_values)}")
            st.markdown(f"**기술스택**: {', '.join(cp.tech_stack)}")
            st.markdown(f"**사업방향**: {cp.business_direction}")
            if cp.recent_news:
                st.markdown("**최근 소식**")
                for news in cp.recent_news[:5]:
                    st.markdown(f"- {news}")

        # Template fill section (DOCX)
        if "result_template" in st.session_state:
            st.divider()
            template_bytes = st.session_state["result_template"]
            template_name = st.session_state.get("result_template_name", "template.docx")

            st.subheader("DOCX 양식 채우기")
            st.caption(f"업로드한 양식({template_name})에 생성된 이력서 내용을 자동으로 채워넣습니다.")

            if st.button("양식에 채워넣기", key="btn_template_fill"):
                with st.spinner("DOCX 양식 분석 및 채우기 중..."):
                    tmp_template_path = None
                    tmp_output_path = None
                    try:
                        tmp_template = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
                        tmp_template.write(template_bytes)
                        tmp_template.close()
                        tmp_template_path = tmp_template.name

                        tmp_output = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
                        tmp_output.close()
                        tmp_output_path = tmp_output.name

                        placeholders = list_docx_placeholders(tmp_template_path)
                        if placeholders:
                            st.info(f"플레이스홀더 발견: {', '.join(placeholders)}")
                            fill_docx_template(
                                tmp_template_path, result.resume, tmp_output_path,
                            )
                        else:
                            st.info("플레이스홀더 없음 — AI 분석으로 양식을 채웁니다...")
                            fill_llm = LLMClient(timeout=_get_config().llm.timeout)
                            _run_async(
                                smart_fill_docx(
                                    tmp_template_path, result.resume,
                                    tmp_output_path, fill_llm,
                                )
                            )

                        filled_bytes = Path(tmp_output_path).read_bytes()
                        st.session_state["filled_template_bytes"] = filled_bytes
                        st.session_state["filled_template_name"] = f"{safe_fname}.docx"
                    except Exception:
                        logger.exception("DOCX template fill failed")
                        st.error("DOCX 양식 채우기에 실패했습니다.")
                        st.session_state.pop("filled_template_bytes", None)
                        st.session_state.pop("filled_template_name", None)
                    finally:
                        if tmp_template_path:
                            Path(tmp_template_path).unlink(missing_ok=True)
                        if tmp_output_path:
                            Path(tmp_output_path).unlink(missing_ok=True)

            if "filled_template_bytes" in st.session_state:
                filled_name = st.session_state.get("filled_template_name", f"{safe_fname}.docx")
                st.download_button(
                    label="DOCX 다운로드",
                    data=st.session_state["filled_template_bytes"],
                    file_name=filled_name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="primary",
                )

    elif not can_run:
        # Empty state — clear step-by-step guide
        st.markdown(
            """
            <div class="step-guide">
              <h4>시작 방법</h4>
              <div class="step-item">
                <div class="step-num">1</div>
                <div class="step-text"><strong>이력서 업로드</strong> — 왼쪽 사이드바에서 PDF, DOCX, TXT 파일을 올려주세요.</div>
              </div>
              <div class="step-item">
                <div class="step-num">2</div>
                <div class="step-text"><strong>회사명 입력</strong> — 지원하려는 회사 이름을 입력하세요. AI가 자동으로 기업 정보를 리서치합니다.</div>
              </div>
              <div class="step-item">
                <div class="step-num">3</div>
                <div class="step-text"><strong>채용공고 붙여넣기</strong> — 채용 사이트에서 공고 전문을 복사해 붙여넣으세요.</div>
              </div>
              <div class="step-item">
                <div class="step-num">4</div>
                <div class="step-text"><strong>생성 시작</strong> — 버튼을 누르면 60~90초 안에 맞춤 이력서가 완성됩니다.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Mode B: Form Answer Generation
# ---------------------------------------------------------------------------


def _mode_form_answers():
    st.header("지원서 답변 생성")
    st.markdown("채용 지원서 문항에 최적화된 답변을 자동 생성합니다.")

    # F2: Sidebar upload awareness
    if not resume_file:
        st.markdown(
            """
            <div class="sidebar-hint">
              <strong>왼쪽 사이드바에서 이력서를 먼저 업로드하세요.</strong><br>
              PDF, DOCX, TXT, MD 형식을 지원합니다. (10MB 이하)
            </div>
            """,
            unsafe_allow_html=True,
        )

    company_name = st.text_input("회사명 (선택)", placeholder="예: 카카오", max_chars=100)

    jd_text = st.text_area(
        "채용공고 (선택)",
        height=150,
        placeholder="채용공고가 있으면 더 정확한 답변을 생성합니다...",
        max_chars=10000,
    )

    questions_text = st.text_area(
        "문항 붙여넣기",
        height=200,
        placeholder='예:\n1. 자기소개를 해주세요 (500자 이내)\n2. 지원동기를 작성해주세요 (1,000자 이내)\n3. 입사 후 포부를 작성해주세요 (800자 이내)',
        max_chars=10000,
    )

    can_run = bool(resume_file and questions_text)

    if st.button("답변 생성", type="primary", disabled=not can_run):
        if not resume_file:
            st.error("이력서 파일을 사이드바에서 업로드하세요.")
            return

        resume_text = _parse_uploaded_resume(resume_file)
        tailored = TailoredResume(
            full_markdown=resume_text,
            sections=[ResumeSection(id="full", label="전체", content=resume_text)],
            metadata={},
        )

        # Parse questions
        form_questions = parse_text(questions_text)
        if not form_questions:
            st.error("문항을 파싱할 수 없습니다. 번호 또는 키워드가 포함된 형식으로 입력하세요.")
            return

        st.info(f"발견된 문항: {len(form_questions)}개")

        llm = LLMClient(timeout=_get_config().llm.timeout)

        # Generate answers + structured fields in parallel
        async def _run_all():
            return await asyncio.gather(
                extract_structured_fields(llm, tailored),
                generate_form_answers(
                    llm=llm,
                    questions=form_questions,
                    resume=tailored,
                    jd_text=jd_text,
                    company_name=company_name,
                    language=lang_code,
                ),
            )

        with st.status("답변 생성 중...", expanded=True) as status:
            st.write("구조화 데이터 추출 + 답변 생성 중...")
            try:
                structured, answers = _run_async(_run_all())
            except Exception:
                logger.exception("Form answer generation failed")
                st.error(
                    "답변 생성 중 오류가 발생했습니다. "
                    "이력서 파일이 올바른지, 문항 형식이 번호 또는 키워드로 시작하는지 확인해주세요."
                )
                return
            status.update(label="답변 생성 완료!", state="complete")

        # Display answers
        st.subheader("서술형 답변")

        for i, ans in enumerate(answers, 1):
            char_count = ans["char_count"]
            max_len = ans["max_length"]

            if max_len:
                over = char_count > max_len
                badge = f":red[{char_count}/{max_len}자]" if over else f":green[{char_count}/{max_len}자]"
            else:
                badge = f"{char_count}자"

            with st.expander(f"Q{i}. {ans['question']} {badge}", expanded=True):
                st.text_area(
                    "답변 (복사용)",
                    value=ans["answer"],
                    height=200,
                    key=f"answer_{i}",
                    label_visibility="collapsed",
                )

        # Structured fields
        if structured:
            with st.expander("구조화 필드 (인적사항/경력/학력/자격증/기술)", expanded=False):
                _render_structured_fields(structured)

        # Build .txt for download
        txt_parts = []
        if structured:
            txt_parts.append("=" * 50)
            txt_parts.append("구조화 필드 (JSON)")
            txt_parts.append("=" * 50)
            txt_parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
            txt_parts.append("")

        for i, ans in enumerate(answers, 1):
            limit_str = (
                f" [{ans['char_count']}/{ans['max_length']}자]"
                if ans["max_length"]
                else f" [{ans['char_count']}자]"
            )
            txt_parts.append("=" * 50)
            txt_parts.append(f"Q{i}. {ans['question']}{limit_str}")
            txt_parts.append("=" * 50)
            txt_parts.append(ans["answer"])
            txt_parts.append("")

        txt_content = "\n".join(txt_parts)
        safe_company = company_name.replace(" ", "_") if company_name else "form"

        st.download_button(
            label=".txt 다운로드",
            data=txt_content.encode("utf-8"),
            file_name=f"{safe_company}_answers.txt",
            mime="text/plain",
            type="primary",
        )

    elif not can_run:
        st.markdown(
            """
            <div class="step-guide">
              <h4>시작 방법</h4>
              <div class="step-item">
                <div class="step-num">1</div>
                <div class="step-text"><strong>이력서 업로드</strong> — 왼쪽 사이드바에서 PDF, DOCX, TXT 파일을 올려주세요.</div>
              </div>
              <div class="step-item">
                <div class="step-num">2</div>
                <div class="step-text"><strong>회사명 / 채용공고 입력 (선택)</strong> — 입력할수록 더 정확한 맞춤 답변이 생성됩니다.</div>
              </div>
              <div class="step-item">
                <div class="step-num">3</div>
                <div class="step-text"><strong>문항 붙여넣기</strong> — 지원서의 자기소개, 지원동기 등 문항을 번호 형식으로 붙여넣으세요.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_structured_fields(structured: dict):
    """Render structured fields in a readable format."""
    personal = structured.get("personal", {})
    if personal:
        st.markdown("**인적사항**")
        for k, v in personal.items():
            if v:
                st.markdown(f"- {k}: {v}")

    career = structured.get("career", [])
    if career:
        st.markdown("**경력사항**")
        for j, c in enumerate(career, 1):
            current = " (재직중)" if c.get("is_current") else ""
            st.markdown(
                f"{j}. **{c.get('company', '')}**{current} "
                f"| {c.get('position', '-')} | {c.get('department', '-')} "
                f"| {c.get('start_date', '')} ~ {c.get('end_date', '')}"
            )
            if c.get("description"):
                st.caption(f"   {c['description']}")

    education = structured.get("education", [])
    if education:
        st.markdown("**학력사항**")
        for e in education:
            st.markdown(
                f"- {e.get('school', '')} | {e.get('degree', '')} {e.get('major', '')} "
                f"| {e.get('start_date', '')} ~ {e.get('end_date', '')}"
            )

    certs = structured.get("certifications", [])
    if certs:
        st.markdown("**자격증/수상**")
        for c in certs:
            st.markdown(
                f"- {c.get('name', '')} | {c.get('type', '')} "
                f"| {c.get('issuer', '-')} | {c.get('date', '')}"
            )

    langs = structured.get("languages", [])
    if langs:
        st.markdown("**어학**")
        for lang in langs:
            st.markdown(
                f"- {lang.get('language', '')} | {lang.get('test', '-')} "
                f"| {lang.get('score', '-')}"
            )

    skills = structured.get("skills", [])
    if skills:
        st.markdown("**기술**")
        for s in skills:
            st.markdown(
                f"- {s.get('name', '')} | {s.get('category', '-')} "
                f"| 수준: {s.get('level', '-')} | {s.get('duration', '-')}"
            )


# ---------------------------------------------------------------------------
# Main router
# ---------------------------------------------------------------------------

if mode == "이력서 맞춤 생성":
    _mode_resume_tailor()
else:
    _mode_form_answers()
