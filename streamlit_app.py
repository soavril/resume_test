"""Streamlit Web UI for resume-tailor.

Two modes:
  A) Resume Tailoring  — PDF/DOCX resume + company + JD + DOCX template → filled DOCX
  B) Form Answer Gen   — resume + questions text → per-question answers + .txt download
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from io import BytesIO
from pathlib import Path

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
from resume_tailor.parsers.resume_parser import parse_resume
from resume_tailor.pipeline.form_filler import (
    extract_structured_fields,
    generate_form_answers,
)
from resume_tailor.pipeline.orchestrator import PipelineOrchestrator
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
        help="PDF, DOCX, TXT 또는 MD 파일",
    )


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
    return LLMClient(), SearchClient()


# ---------------------------------------------------------------------------
# Mode A: Resume Tailoring
# ---------------------------------------------------------------------------


def _mode_resume_tailor():
    st.header("이력서 맞춤 생성")
    st.markdown("회사 채용공고에 최적화된 이력서를 자동 생성합니다.")

    company_name = st.text_input("회사명", placeholder="예: 삼성전자")

    jd_text = st.text_area(
        "채용공고 붙여넣기",
        height=200,
        placeholder="채용공고 전문을 여기에 붙여넣으세요...",
    )

    docx_template = st.file_uploader(
        "DOCX 양식 업로드 (선택)",
        type=["docx"],
        help="회사에서 제공하는 이력서 양식. 없으면 마크다운만 생성.",
    )

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
        with st.status("이력서 생성 중...", expanded=True) as status:

            def on_phase(phase: str, detail: str):
                status.update(label=detail)
                st.write(detail)

            result = asyncio.run(
                orchestrator.run(
                    company_name=company_name,
                    jd_text=jd_text,
                    resume_text=resume_text,
                    template_name="korean_standard",
                    company_profile=cached_profile,
                    on_phase=on_phase,
                    language=lang_code,
                )
            )
            status.update(
                label=f"완료! 점수: {result.qa.overall_score}점, 소요: {result.elapsed_seconds:.1f}초",
                state="complete",
            )

        # Cache company profile
        if not cached_profile:
            cache.put(company_name, result.company)

        # Save markdown internally
        output_dir = Path("./output")
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / f"{company_name}_{result.job.title}.md".replace(" ", "_")
        md_path.write_text(result.resume.full_markdown, encoding="utf-8")

        # Display results in tabs
        tab_resume, tab_qa, tab_company = st.tabs(
            ["생성된 이력서", "QA 점수", "회사 분석"]
        )

        with tab_resume:
            st.markdown(result.resume.full_markdown)

        with tab_qa:
            qa = result.qa
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("정확성", f"{qa.factual_accuracy}")
            c2.metric("키워드", f"{qa.keyword_coverage}")
            c3.metric("템플릿", f"{qa.template_compliance}")
            c4.metric("총점", f"{qa.overall_score}", delta="PASS" if qa.pass_ else "FAIL")

            if qa.issues:
                st.subheader("주의사항")
                for issue in qa.issues:
                    st.warning(issue)
            if qa.suggestions:
                st.subheader("개선 제안")
                for sug in qa.suggestions:
                    st.info(sug)

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

        # DOCX generation
        if docx_template:
            st.divider()
            st.subheader("DOCX 다운로드")

            tmp_docx_in = _save_upload_to_tmp(docx_template)
            tmp_docx_out = Path(tempfile.mktemp(suffix=".docx"))

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
                        asyncio.run(
                            smart_fill_docx(
                                template_path=tmp_docx_in,
                                resume=result.resume,
                                output_path=tmp_docx_out,
                                llm=llm,
                            )
                        )

                docx_bytes = tmp_docx_out.read_bytes()
                st.download_button(
                    label="DOCX 다운로드",
                    data=docx_bytes,
                    file_name=f"{company_name}_이력서.docx",
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
        company_name = st.text_input("회사명 (선택)", placeholder="예: 카카오")
    with col2:
        pass  # spacer

    jd_text = st.text_area(
        "채용공고 (선택)",
        height=150,
        placeholder="채용공고가 있으면 더 정확한 답변을 생성합니다...",
    )

    questions_text = st.text_area(
        "문항 붙여넣기",
        height=200,
        placeholder='예:\n1. 자기소개를 해주세요 (500자 이내)\n2. 지원동기를 작성해주세요 (1,000자 이내)\n3. 입사 후 포부를 작성해주세요 (800자 이내)',
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

        llm = LLMClient()

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
            structured, answers = asyncio.run(_run_all())
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
