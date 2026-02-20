"""Streamlit Web UI for resume-tailor.

Two modes:
  A) Resume Tailoring  — PDF/DOCX resume + company + JD + DOCX template → filled DOCX
  B) Form Answer Gen   — resume + questions text → per-question answers + .txt download
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

import nest_asyncio
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
nest_asyncio.apply()

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
from resume_tailor.templates.docx_renderer import (
    fill_docx_template,
    generate_docx,
    list_docx_placeholders,
)
from resume_tailor.parsers.jd_image_parser import extract_jd_from_file
from resume_tailor.templates.smart_filler import smart_fill_docx

# Optional PDF support via weasyprint
try:
    import markdown as _markdown_mod
    import weasyprint

    def _md_to_pdf(md_text: str) -> bytes:
        """Convert markdown text to PDF bytes with Korean font support."""
        html_body = _markdown_mod.markdown(md_text, extensions=["tables", "fenced_code"])
        css = (
            '@import url("https://fonts.googleapis.com/css2?'
            'family=Noto+Sans+KR:wght@400;700&display=swap");\n'
            "body { font-family: 'Noto Sans KR', sans-serif; "
            "font-size: 11pt; line-height: 1.6; margin: 2cm; }\n"
            "h1, h2, h3 { margin-top: 1em; }\n"
            "table { border-collapse: collapse; width: 100%; }\n"
            "th, td { border: 1px solid #ccc; padding: 6px 10px; }\n"
        )
        full_html = f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"
        return weasyprint.HTML(string=full_html).write_pdf()

    _PDF_AVAILABLE = True
except (ImportError, OSError):
    _PDF_AVAILABLE = False

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Resume Tailor",
    page_icon=":page_facing_up:",
    layout="wide",
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
    st.markdown("## Resume Tailor")
    pw = st.text_input("비밀번호를 입력하세요", type="password")
    if pw and pw == APP_PASSWORD:
        st.session_state.authenticated = True
        st.rerun()
    elif pw:
        st.error("비밀번호가 틀립니다")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — shared across modes
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Resume Tailor")
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

    resume_file = st.file_uploader(
        "내 이력서 업로드",
        type=["pdf", "docx", "doc", "txt", "md"],
        help="PDF, DOCX, TXT 또는 MD 파일 (10MB 이하)",
    )
    if resume_file and resume_file.size > 10 * 1024 * 1024:
        st.error("이력서 파일 크기가 10MB를 초과합니다.")
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

    company_name = st.text_input("회사명", placeholder="예: 삼성전자", max_chars=100)

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
        "채용공고 붙여넣기",
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
                    extracted = asyncio.run(
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
                    st.error("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

    docx_template = st.file_uploader(
        "DOCX 양식 업로드 (선택)",
        type=["docx"],
        help="회사에서 제공하는 이력서 양식 (5MB 이하). 없으면 마크다운만 생성.",
    )
    if docx_template and docx_template.size > 5 * 1024 * 1024:
        st.error("DOCX 파일 크기가 5MB를 초과합니다.")
        st.stop()

    # Validation
    can_run = bool(resume_file and company_name and jd_text)

    if st.button("생성 시작", type="primary", disabled=not can_run):
        if not resume_file:
            st.error("이력서 파일을 사이드바에서 업로드하세요.")
            return

        resume_text = _parse_uploaded_resume(resume_file)
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

        # Run pipeline with progress
        phases = {
            "phase1": (0.15, "회사 리서치 + 채용공고 분석 중..."),
            "phase1_done": (0.25, "분석 완료"),
            "phase2": (0.35, "전략 수립 중..."),
            "writing": (0.55, "이력서 작성 중..."),
            "qa": (0.75, "품질 검수 중..."),
            "rewrite": (0.85, "재작성 중..."),
            "done": (1.0, "완료!"),
        }
        progress_bar = st.progress(0, text="준비 중...")

        def on_phase(phase: str, detail: str):
            pct, label = phases.get(phase, (0, detail))
            progress_bar.progress(pct, text=detail)

        # Clear stale state from previous runs
        for key in (
            "refined_resume_md", "refinement_suggestions", "refinement_original",
            "pipeline_result", "download_md", "docx_default_bytes",
            "safe_fname", "result_jd_text", "result_docx_template",
        ):
            st.session_state.pop(key, None)

        try:
            result = asyncio.run(
                orchestrator.run(
                    company_name=company_name,
                    jd_text=jd_text,
                    resume_text=resume_text,
                    company_profile=cached_profile,
                    on_phase=on_phase,
                    language=lang_code,
                    role_category=role_category,
                )
            )
        except Exception:
            logger.exception("Resume tailoring pipeline failed")
            st.error("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
            return
        progress_bar.progress(1.0, text=f"완료! 점수: {result.qa.overall_score}점, 소요: {result.elapsed_seconds:.1f}초")

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

        # Generate DOCX from scratch (no template needed)
        _docx_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
        _docx_tmp.close()
        _docx_tmp_path = Path(_docx_tmp.name)
        try:
            generate_docx(resume=result.resume, output_path=_docx_tmp_path, title=f"{company_name} 이력서")
            docx_default_bytes = _docx_tmp_path.read_bytes()
        except Exception:
            logger.exception("DOCX generation failed")
            docx_default_bytes = None
        finally:
            _docx_tmp_path.unlink(missing_ok=True)

        safe_fname = f"{company_name}_{result.job.title}".replace(" ", "_")

        # Persist to session_state so results survive rerun
        st.session_state["pipeline_result"] = result
        st.session_state["download_md"] = download_md
        st.session_state["docx_default_bytes"] = docx_default_bytes
        st.session_state["safe_fname"] = safe_fname
        st.session_state["result_jd_text"] = jd_text
        if docx_template:
            st.session_state["result_docx_template"] = docx_template
        else:
            st.session_state.pop("result_docx_template", None)

    # -----------------------------------------------------------------------
    # Render results from session_state (survives rerun after download click)
    # -----------------------------------------------------------------------
    if "pipeline_result" in st.session_state:
        result = st.session_state["pipeline_result"]
        download_md = st.session_state.get("refined_resume_md", st.session_state["download_md"])
        docx_default_bytes = st.session_state["docx_default_bytes"]
        safe_fname = st.session_state["safe_fname"]

        # Show detected role and completion status
        role_labels = {"tech": "개발/엔지니어링", "business": "비즈니스/전략", "design": "디자인", "general": "일반"}
        detected = result.metadata.get("role_category", "general")
        st.success(f"직군: {role_labels.get(detected, detected)} | 점수: {result.qa.overall_score}점 | 소요: {result.elapsed_seconds:.1f}초")

        # Download buttons: MD + DOCX + PDF in a row
        dl_cols = st.columns(3) if _PDF_AVAILABLE else st.columns(2)
        with dl_cols[0]:
            st.download_button(
                label="MD 다운로드",
                data=download_md.encode("utf-8"),
                file_name=f"{safe_fname}.md",
                mime="text/markdown",
                type="secondary",
            )
        with dl_cols[1]:
            if docx_default_bytes is not None:
                st.download_button(
                    label="DOCX 다운로드",
                    data=docx_default_bytes,
                    file_name=f"{safe_fname}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    type="secondary",
                )
            else:
                st.warning("DOCX 생성 실패")
        if _PDF_AVAILABLE:
            with dl_cols[2]:
                try:
                    pdf_bytes = _md_to_pdf(download_md)
                    st.download_button(
                        label="PDF 다운로드",
                        data=pdf_bytes,
                        file_name=f"{safe_fname}.pdf",
                        mime="application/pdf",
                        type="secondary",
                    )
                except Exception:
                    logger.exception("PDF generation failed")
                    st.warning("PDF 생성 실패")

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
                        suggestions = asyncio.run(
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

        # DOCX template fill
        _docx_tmpl = st.session_state.get("result_docx_template")
        if _docx_tmpl:
            st.divider()
            st.subheader("DOCX 다운로드")

            tmp_docx_in = _save_upload_to_tmp(_docx_tmpl)
            _tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
            _tmp_out.close()
            tmp_docx_out = Path(_tmp_out.name)

            _fill_llm = LLMClient(timeout=_get_config().llm.timeout)
            try:
                with st.spinner("DOCX 양식에 내용 채우는 중..."):
                    placeholders = list_docx_placeholders(tmp_docx_in)
                    if placeholders:
                        fill_docx_template(
                            template_path=tmp_docx_in,
                            resume=result.resume,
                            output_path=tmp_docx_out,
                        )
                    else:
                        try:
                            asyncio.run(
                                smart_fill_docx(
                                    template_path=tmp_docx_in,
                                    resume=result.resume,
                                    output_path=tmp_docx_out,
                                    llm=_fill_llm,
                                )
                            )
                        except Exception:
                            logger.exception("DOCX smart fill failed")
                            st.error("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

                if tmp_docx_out.exists():
                    docx_bytes = tmp_docx_out.read_bytes()
                    st.download_button(
                        label="DOCX 다운로드",
                        data=docx_bytes,
                        file_name=f"{safe_fname}_이력서.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        type="primary",
                    )
            finally:
                tmp_docx_in.unlink(missing_ok=True)
                tmp_docx_out.unlink(missing_ok=True)

    elif not can_run:
        missing = []
        if not resume_file:
            missing.append("이력서 파일")
        if not company_name:
            missing.append("회사명")
        if not jd_text:
            missing.append("채용공고")
        st.info(f"필수 입력: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Mode B: Form Answer Generation
# ---------------------------------------------------------------------------


def _mode_form_answers():
    st.header("지원서 답변 생성")
    st.markdown("채용 지원서 문항에 최적화된 답변을 자동 생성합니다.")

    col1, col2 = st.columns(2)
    with col1:
        company_name = st.text_input("회사명 (선택)", placeholder="예: 카카오", max_chars=100)
    with col2:
        pass  # spacer

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
                structured, answers = asyncio.run(_run_all())
            except Exception:
                logger.exception("Form answer generation failed")
                st.error("오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
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
        missing = []
        if not resume_file:
            missing.append("이력서 파일")
        if not questions_text:
            missing.append("문항 텍스트")
        st.info(f"필수 입력: {', '.join(missing)}")


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
