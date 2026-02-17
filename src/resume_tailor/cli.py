"""CLI interface using typer + rich."""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from resume_tailor.cache.company_cache import CompanyCache
from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.clients.search_client import SearchClient
from resume_tailor.config import load_config
from resume_tailor.parsers.jd_parser import load_jd_file
from resume_tailor.parsers.resume_parser import parse_resume
from resume_tailor.pipeline.orchestrator import PipelineOrchestrator
from resume_tailor.templates.docx_renderer import (
    fill_docx_template,
    generate_docx,
    list_docx_placeholders,
)
from resume_tailor.templates.smart_filler import (
    smart_fill_docx_sync,
)
from resume_tailor.parsers.form_parser import extract_from_url, parse_text
from resume_tailor.pipeline.form_filler import generate_form_answers, extract_structured_fields
from resume_tailor.models.resume import TailoredResume, ResumeSection
from resume_tailor.templates.loader import list_templates, load_template
from resume_tailor.templates.renderer import render_to_html, save_html

app = typer.Typer(
    name="resume-tailor",
    help="AI 이력서 맞춤 자동화 시스템",
    no_args_is_help=True,
)
console = Console()


@app.command()
def tailor(
    company: str = typer.Argument(help="지원 회사명"),
    jd: Path = typer.Option(..., "--jd", help="채용공고 텍스트 파일 경로"),
    resume: Path = typer.Option(..., "--resume", help="내 이력서 파일 경로 (PDF/DOCX/TXT)"),
    template: str = typer.Option("korean_standard", "--template", "-t", help="이력서 템플릿명"),
    output: Path = typer.Option(None, "--output", "-o", help="출력 파일 경로 (.md)"),
    html: bool = typer.Option(False, "--html", help="HTML 미리보기 파일도 생성"),
    docx: Path = typer.Option(None, "--docx", help="DOCX 템플릿 경로 → 채워서 .docx 출력"),
    docx_out: bool = typer.Option(False, "--docx-out", help="템플릿 없이 깨끗한 .docx 생성"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="상세 출력"),
) -> None:
    """채용공고에 맞춤화된 이력서를 생성합니다."""
    if not jd.exists():
        console.print(f"[red]채용공고 파일을 찾을 수 없습니다: {jd}[/red]")
        raise typer.Exit(1)
    if not resume.exists():
        console.print(f"[red]이력서 파일을 찾을 수 없습니다: {resume}[/red]")
        raise typer.Exit(1)

    config = load_config()
    jd_text = load_jd_file(str(jd))
    resume_text = parse_resume(str(resume))

    if verbose:
        console.print(f"[dim]회사: {company}[/dim]")
        console.print(f"[dim]채용공고: {len(jd_text)}자[/dim]")
        console.print(f"[dim]이력서: {len(resume_text)}자[/dim]")
        console.print(f"[dim]템플릿: {template}[/dim]")

    # Check cache
    cache = CompanyCache(
        db_path=config.cache.resolved_db_path,
        ttl_days=config.cache.ttl_days,
    )
    cached_profile = cache.get(company)
    if cached_profile:
        console.print(f"[green]캐시된 회사 정보 사용: {company}[/green]")

    llm = LLMClient(timeout=config.llm.timeout)
    search = SearchClient()
    orchestrator = PipelineOrchestrator(
        llm,
        search,
        haiku_model=config.llm.haiku_model,
        sonnet_model=config.llm.sonnet_model,
        qa_threshold=config.pipeline.qa_threshold,
        max_rewrites=config.pipeline.max_rewrites,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("이력서 생성 중...", total=None)

        def on_phase(phase: str, detail: str) -> None:
            progress.update(task, description=detail)

        result = asyncio.run(
            orchestrator.run(
                company_name=company,
                jd_text=jd_text,
                resume_text=resume_text,
                template_name=template,
                company_profile=cached_profile,
                on_phase=on_phase,
            )
        )

    # Cache company profile
    if not cached_profile:
        cache.put(company, result.company)

    # Determine output path
    if output is None:
        output = Path(f"./output/{company}_{result.job.title}.md".replace(" ", "_"))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.resume.full_markdown, encoding="utf-8")
    console.print(f"\n[green]이력서 저장: {output}[/green]")

    # QA results
    qa = result.qa
    score_color = "green" if qa.pass_ else "yellow"
    console.print(
        Panel(
            f"정확성: {qa.factual_accuracy} | 키워드: {qa.keyword_coverage} | "
            f"템플릿: {qa.template_compliance} | [bold {score_color}]총점: {qa.overall_score}[/bold {score_color}]"
            + (f"\n재작성: {result.rewrites}회" if result.rewrites else "")
            + f"\n소요: {result.elapsed_seconds:.1f}초",
            title="QA 결과",
        )
    )

    if qa.issues:
        console.print("\n[yellow]주의사항:[/yellow]")
        for issue in qa.issues:
            console.print(f"  - {issue}")

    # HTML output
    if html:
        html_path = output.with_suffix(".html")
        html_content = render_to_html(result.resume.full_markdown, title=f"{company} 이력서")
        save_html(html_content, str(html_path))
        console.print(f"[green]HTML 저장: {html_path}[/green]")

    # DOCX output — template fill
    if docx:
        if not docx.exists():
            console.print(f"[red]DOCX 템플릿을 찾을 수 없습니다: {docx}[/red]")
        else:
            docx_path = output.with_suffix(".docx")
            placeholders = list_docx_placeholders(docx)
            if placeholders:
                # Placeholder-based template ({{자기소개}} 등)
                fill_docx_template(
                    template_path=docx,
                    resume=result.resume,
                    output_path=docx_path,
                )
                console.print(f"[green]DOCX 저장 (플레이스홀더): {docx_path}[/green]")
            else:
                # Universal smart fill (LLM이 양식 구조 분석 → 자동 채움)
                console.print("[dim]양식 구조 분석 중 (LLM smart fill)...[/dim]")
                smart_fill_docx_sync(
                    template_path=docx,
                    resume=result.resume,
                    output_path=docx_path,
                    llm=llm,
                )
                console.print(f"[green]DOCX 저장 (smart fill): {docx_path}[/green]")

    # DOCX output — from scratch
    if docx_out:
        docx_path = output.with_suffix(".docx")
        generate_docx(
            resume=result.resume,
            output_path=docx_path,
            title=f"{company} 이력서",
        )
        console.print(f"[green]DOCX 저장: {docx_path}[/green]")


@app.command()
def research(
    company: str = typer.Argument(help="리서치할 회사명"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="상세 출력"),
) -> None:
    """회사 리서치만 실행합니다 (결과 캐시 저장)."""
    config = load_config()
    cache = CompanyCache(
        db_path=config.cache.resolved_db_path,
        ttl_days=config.cache.ttl_days,
    )

    cached = cache.get(company)
    if cached:
        console.print(f"[yellow]이미 캐시된 정보가 있습니다 ({company}). 새로 검색합니다.[/yellow]")

    llm = LLMClient(timeout=config.llm.timeout)
    search = SearchClient()
    orchestrator = PipelineOrchestrator(
        llm,
        search,
        haiku_model=config.llm.haiku_model,
        sonnet_model=config.llm.sonnet_model,
    )

    with console.status("회사 리서치 중..."):
        profile = asyncio.run(orchestrator.research_only(company))

    cache.put(company, profile)

    console.print(Panel(
        f"[bold]{profile.name}[/bold] ({profile.industry})\n"
        f"{profile.description}\n\n"
        f"기업문화: {', '.join(profile.culture_values)}\n"
        f"기술스택: {', '.join(profile.tech_stack)}\n"
        f"사업방향: {profile.business_direction}\n"
        f"최근소식: {', '.join(profile.recent_news[:3])}",
        title="회사 프로필",
    ))
    console.print("[green]캐시에 저장되었습니다.[/green]")


@app.command()
def templates() -> None:
    """사용 가능한 이력서 템플릿 목록을 표시합니다."""
    names = list_templates()
    if not names:
        console.print("[yellow]템플릿이 없습니다.[/yellow]")
        return

    for name in sorted(names):
        tmpl = load_template(name)
        sections = ", ".join(s.label for s in tmpl.sections)
        console.print(f"  [bold]{name}[/bold]: {tmpl.name} [{sections}]")


@app.command("docx-check")
def docx_check(
    file: Path = typer.Argument(help="DOCX 템플릿 파일 경로"),
) -> None:
    """DOCX 템플릿의 {{플레이스홀더}} 목록을 확인합니다."""
    if not file.exists():
        console.print(f"[red]파일을 찾을 수 없습니다: {file}[/red]")
        raise typer.Exit(1)

    placeholders = list_docx_placeholders(file)
    if not placeholders:
        console.print("[yellow]플레이스홀더를 찾을 수 없습니다.[/yellow]")
        console.print("[dim]팁: DOCX 파일에 {{자기소개}}, {{경력사항}} 같은 마커를 넣으세요.[/dim]")
        return

    console.print(f"\n[bold]발견된 플레이스홀더 ({len(placeholders)}개):[/bold]")
    for ph in placeholders:
        console.print(f"  {{{{{ph}}}}}")

    console.print(
        "\n[dim]사용 가능한 키: header, summary/자기소개, experience/경력사항, "
        "skills/기술 스택, education/학력, projects/프로젝트, "
        "certifications/자격증, full/전체[/dim]"
    )


@app.command("fill-form")
def fill_form(
    resume: Path = typer.Option(..., "--resume", help="이력서 파일 (생성된 .md 또는 원본 PDF/DOCX/TXT)"),
    url: str = typer.Option(None, "--url", help="채용 지원 페이지 URL"),
    questions: Path = typer.Option(None, "--questions", "-q", help="문항 텍스트 파일 경로"),
    jd: Path = typer.Option(None, "--jd", help="채용공고 텍스트 파일 (선택)"),
    company: str = typer.Option("", "--company", "-c", help="회사명 (선택)"),
    output: Path = typer.Option(None, "--output", "-o", help="결과 저장 경로 (.txt)"),
    auto_fill: bool = typer.Option(False, "--auto-fill", help="브라우저를 열고 폼에 자동 입력"),
) -> None:
    """채용 지원서 문항에 맞는 답변을 생성합니다.

    사용법:
      # URL에서 문항 자동 추출
      resume-tailor fill-form --resume ./output/my_resume.md --url https://careers.example.com/apply

      # 문항 텍스트 파일로 입력
      resume-tailor fill-form --resume ./my_resume.pdf --questions ./questions.txt

      # 대화형 (직접 붙여넣기)
      resume-tailor fill-form --resume ./my_resume.pdf
    """
    if not resume.exists():
        console.print(f"[red]이력서 파일을 찾을 수 없습니다: {resume}[/red]")
        raise typer.Exit(1)

    # Load resume
    if resume.suffix == ".md":
        md_content = resume.read_text(encoding="utf-8")
    else:
        md_content = parse_resume(str(resume))

    tailored = TailoredResume(
        full_markdown=md_content,
        sections=[ResumeSection(id="full", label="전체", content=md_content)],
        metadata={},
    )

    # Load JD if provided
    jd_text = ""
    if jd and jd.exists():
        jd_text = load_jd_file(str(jd))

    # Extract questions from URL, file, or interactive input
    form_questions = []

    if url:
        with console.status("페이지에서 문항 추출 중..."):
            try:
                form_questions = asyncio.run(extract_from_url(url))
            except Exception as e:
                console.print(f"[red]URL 접근 실패: {e}[/red]")
                console.print("[yellow]문항을 직접 입력해주세요.[/yellow]")

    if not form_questions and questions and questions.exists():
        text = questions.read_text(encoding="utf-8")
        form_questions = parse_text(text)

    if not form_questions:
        # Interactive mode
        console.print("\n[bold]문항을 붙여넣기 하세요[/bold] (빈 줄 2개로 종료):\n")
        lines: list[str] = []
        empty_count = 0
        try:
            while True:
                line = input()
                if not line.strip():
                    empty_count += 1
                    if empty_count >= 2:
                        break
                else:
                    empty_count = 0
                lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass

        if lines:
            form_questions = parse_text("\n".join(lines))

    if not form_questions:
        console.print("[red]문항을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    # Show extracted questions
    console.print(f"\n[bold]발견된 문항 ({len(form_questions)}개):[/bold]")
    for i, q in enumerate(form_questions, 1):
        limit_str = f" [dim]({q.max_length}자)[/dim]" if q.max_length else ""
        console.print(f"  {i}. {q.label}{limit_str}")

    # Generate answers + structured data
    config = load_config()
    llm = LLMClient(timeout=config.llm.timeout)

    async def _run_all():
        import asyncio as aio
        structured_task = extract_structured_fields(llm, tailored)
        answers_task = generate_form_answers(
            llm=llm,
            questions=form_questions,
            resume=tailored,
            jd_text=jd_text,
            company_name=company,
        )
        return await aio.gather(structured_task, answers_task)

    with console.status("구조화 데이터 추출 + 답변 생성 중..."):
        structured, answers = asyncio.run(_run_all())

    # --- Display structured fields ---
    result_parts = []

    if structured:
        console.print("\n[bold]== 구조화 필드 (복붙용) ==[/bold]\n")

        # Personal info
        personal = structured.get("personal", {})
        if personal:
            console.print(Panel(
                "\n".join(f"  {k}: {v}" for k, v in personal.items() if v),
                title="인적사항",
                border_style="blue",
            ))

        # Career
        career = structured.get("career", [])
        if career:
            career_lines = []
            for j, c in enumerate(career, 1):
                current = " (재직중)" if c.get("is_current") else ""
                career_lines.append(
                    f"  [{j}] {c.get('company', '')}{current}\n"
                    f"      직급: {c.get('position', '-')} | 부서: {c.get('department', '-')} | "
                    f"고용형태: {c.get('employment_type', '-')}\n"
                    f"      기간: {c.get('start_date', '')} ~ {c.get('end_date', '')}\n"
                    f"      업무: {c.get('description', '-')}"
                )
            console.print(Panel("\n".join(career_lines), title="경력사항", border_style="blue"))

        # Education
        education = structured.get("education", [])
        if education:
            edu_lines = [
                f"  {e.get('school', '')} | {e.get('degree', '')} {e.get('major', '')} | "
                f"{e.get('start_date', '')} ~ {e.get('end_date', '')}"
                for e in education
            ]
            console.print(Panel("\n".join(edu_lines), title="학력사항", border_style="blue"))

        # Certifications
        certs = structured.get("certifications", [])
        if certs:
            cert_lines = [
                f"  {c.get('name', '')} | {c.get('type', '')} | {c.get('issuer', '-')} | {c.get('date', '')}"
                for c in certs
            ]
            console.print(Panel("\n".join(cert_lines), title="자격증/수상", border_style="blue"))

        # Languages
        langs = structured.get("languages", [])
        if langs:
            lang_lines = [
                f"  {l.get('language', '')} | {l.get('test', '-')} | {l.get('score', '-')} | {l.get('institution', '-')}"
                for l in langs
            ]
            console.print(Panel("\n".join(lang_lines), title="어학", border_style="blue"))

        # Skills
        skills = structured.get("skills", [])
        if skills:
            skill_lines = [
                f"  {s.get('name', '')} | {s.get('category', '-')} | 수준: {s.get('level', '-')} | {s.get('duration', '-')}"
                for s in skills
            ]
            console.print(Panel("\n".join(skill_lines), title="컴퓨터 활용능력/기술", border_style="blue"))

        # Build structured section for file output
        result_parts.append("# 구조화 필드\n")
        import json
        result_parts.append(f"```json\n{json.dumps(structured, ensure_ascii=False, indent=2)}\n```\n")

    # --- Display essay answers ---
    console.print("\n[bold]== 서술형 답변 ==[/bold]\n")

    for i, ans in enumerate(answers, 1):
        limit_info = ""
        if ans["max_length"]:
            over = ans["char_count"] > ans["max_length"]
            color = "red" if over else "green"
            limit_info = f" [{color}]({ans['char_count']}/{ans['max_length']}자)[/{color}]"
        else:
            limit_info = f" [dim]({ans['char_count']}자)[/dim]"

        console.print(Panel(
            ans["answer"],
            title=f"Q{i}. {ans['question']}{limit_info}",
            border_style="cyan",
        ))

        result_parts.append(f"## Q{i}. {ans['question']}\n\n{ans['answer']}\n")

    # Save to file (.txt for easy copy-paste)
    if output is None:
        safe_company = company.replace(" ", "_") if company else "form"
        output = Path(f"./output/{safe_company}_form_answers.txt")

    output.parent.mkdir(parents=True, exist_ok=True)

    # Build plain text output — easy to copy-paste
    txt_parts = []
    if structured:
        import json
        txt_parts.append("=" * 50)
        txt_parts.append("구조화 필드 (JSON)")
        txt_parts.append("=" * 50)
        txt_parts.append(json.dumps(structured, ensure_ascii=False, indent=2))
        txt_parts.append("")

    for i, ans in enumerate(answers, 1):
        limit_str = f" [{ans['char_count']}/{ans['max_length']}자]" if ans["max_length"] else f" [{ans['char_count']}자]"
        txt_parts.append("=" * 50)
        txt_parts.append(f"Q{i}. {ans['question']}{limit_str}")
        txt_parts.append("=" * 50)
        txt_parts.append(ans["answer"])
        txt_parts.append("")

    output.write_text("\n".join(txt_parts), encoding="utf-8")
    console.print(f"\n[green]답변 저장: {output}[/green]")

    # Auto-fill in browser (주석 처리 — 추후 필요 시 활성화)
    # if auto_fill and url:
    #     console.print("\n[bold]브라우저에서 자동 입력 중...[/bold]")
    #     from resume_tailor.pipeline.form_autofill import autofill_form
    #     filled = asyncio.run(autofill_form(url, answers))
    #     console.print(f"[green]{filled}개 필드 자동 입력 완료[/green]")


@app.command()
def preview(
    file: Path = typer.Argument(help="미리보기할 마크다운 파일"),
) -> None:
    """생성된 이력서를 HTML로 변환하여 브라우저에서 미리봅니다."""
    if not file.exists():
        console.print(f"[red]파일을 찾을 수 없습니다: {file}[/red]")
        raise typer.Exit(1)

    md_content = file.read_text(encoding="utf-8")
    html_path = file.with_suffix(".html")
    html_content = render_to_html(md_content, title="이력서 미리보기")
    save_html(html_content, str(html_path))

    console.print(f"[green]HTML 생성: {html_path}[/green]")
    webbrowser.open(str(html_path))


if __name__ == "__main__":
    app()
