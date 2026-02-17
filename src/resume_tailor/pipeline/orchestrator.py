"""Main pipeline orchestrator - coordinates all agents."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.clients.search_client import SearchClient
from resume_tailor.models.company import CompanyProfile
from resume_tailor.models.job import JobAnalysis
from resume_tailor.models.qa import QAResult
from resume_tailor.models.resume import TailoredResume
from resume_tailor.models.strategy import ResumeStrategy
from resume_tailor.pipeline.company_researcher import CompanyResearcher
from resume_tailor.pipeline.jd_analyst import JDAnalyst
from resume_tailor.pipeline.qa_reviewer import QAReviewer
from resume_tailor.pipeline.resume_writer import ResumeWriter
from resume_tailor.pipeline.strategy_planner import StrategyPlanner
from resume_tailor.templates.loader import ResumeTemplate, load_template

TEMPLATE_MAP: dict[str, str] = {
    "tech": "korean_developer",
    "business": "korean_business",
    "general": "korean_standard",
    "design": "korean_standard",
}


@dataclass
class PipelineResult:
    """Complete result from the tailoring pipeline."""

    company: CompanyProfile
    job: JobAnalysis
    strategy: ResumeStrategy
    resume: TailoredResume
    qa: QAResult
    rewrites: int = 0
    elapsed_seconds: float = 0.0
    metadata: dict = field(default_factory=dict)


class PipelineOrchestrator:
    """Orchestrates the 5-agent resume tailoring pipeline."""

    def __init__(
        self,
        llm: LLMClient,
        search: SearchClient,
        *,
        haiku_model: str = "claude-haiku-4-5-20251001",
        sonnet_model: str = "claude-sonnet-4-5-20250929",
        qa_threshold: int = 80,
        max_rewrites: int = 1,
        writer_temperature: float = 0.3,
    ):
        self.researcher = CompanyResearcher(llm, search, model=haiku_model)
        self.jd_analyst = JDAnalyst(llm, model=haiku_model)
        self.strategy_planner = StrategyPlanner(llm, model=sonnet_model)
        self.resume_writer = ResumeWriter(llm, model=sonnet_model)
        self.qa_reviewer = QAReviewer(llm, model=haiku_model)
        self.qa_threshold = qa_threshold
        self.max_rewrites = max_rewrites

    async def run(
        self,
        company_name: str,
        jd_text: str,
        resume_text: str,
        template_name: str = "korean_standard",
        *,
        company_profile: CompanyProfile | None = None,
        on_phase: callable | None = None,
        language: str = "ko",
        role_category: str = "auto",
    ) -> PipelineResult:
        """Run the full tailoring pipeline.

        Args:
            company_name: Target company name.
            jd_text: Job description text.
            resume_text: Applicant's resume as plain text.
            template_name: Name of the resume template to use.
            company_profile: Pre-cached company profile (skips research).
            on_phase: Optional callback(phase_name, detail) for progress.
            language: Output language - "ko" for Korean, "en" for English.
            role_category: Role preset - "auto" to detect from JD, or
                "tech"/"business"/"design"/"general".
        """
        start = time.monotonic()

        def _notify(phase: str, detail: str = ""):
            if on_phase:
                on_phase(phase, detail)

        # --- Phase 1: Parallel research + JD analysis ---
        _notify("phase1", "회사 리서치 + 채용공고 분석 시작")

        if company_profile:
            company = company_profile
            job = await self.jd_analyst.analyze(jd_text)
        else:
            company, job = await asyncio.gather(
                self.researcher.research(company_name),
                self.jd_analyst.analyze(jd_text),
            )

        _notify("phase1_done", f"회사: {company.name}, 포지션: {job.title}")

        # --- Resolve role_category ---
        effective_category = job.role_category if role_category == "auto" else role_category

        # Auto-map template when using the default template_name
        if template_name == "korean_standard":
            template_name = TEMPLATE_MAP.get(effective_category, "korean_standard")

        template = load_template(template_name)

        # --- Phase 2: Sequential strategy → write → QA ---
        _notify("phase2", "전략 수립 중")
        strategy = await self.strategy_planner.plan(
            company, job, resume_text, language=language, role_category=effective_category,
        )

        _notify("writing", "이력서 작성 중")
        resume = await self.resume_writer.write(
            strategy, resume_text, template, language=language, role_category=effective_category,
        )

        _notify("qa", "품질 검수 중")
        qa = await self.qa_reviewer.review(
            resume.full_markdown, resume_text, jd_text
        )

        # --- QA rewrite loop ---
        rewrites = 0
        while not qa.pass_ and rewrites < self.max_rewrites:
            _notify("rewrite", f"QA 점수 {qa.overall_score} < {self.qa_threshold}, 재작성 중")
            resume = await self.resume_writer.write(
                strategy, resume_text, template, language=language, role_category=effective_category,
            )
            qa = await self.qa_reviewer.review(
                resume.full_markdown, resume_text, jd_text
            )
            rewrites += 1

        elapsed = time.monotonic() - start
        _notify("done", f"완료! 점수: {qa.overall_score}, 소요: {elapsed:.1f}초")

        return PipelineResult(
            company=company,
            job=job,
            strategy=strategy,
            resume=resume,
            qa=qa,
            rewrites=rewrites,
            elapsed_seconds=elapsed,
            metadata={"role_category": effective_category},
        )

    async def research_only(self, company_name: str) -> CompanyProfile:
        """Run company research only (useful for caching)."""
        return await self.researcher.research(company_name)
