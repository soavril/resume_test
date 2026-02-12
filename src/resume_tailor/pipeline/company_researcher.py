"""Agent 1: Company Researcher - Analyzes target company using web search."""

from __future__ import annotations

from resume_tailor.clients.llm_client import LLMClient
from resume_tailor.clients.search_client import SearchClient
from resume_tailor.models.company import CompanyProfile

SYSTEM_PROMPT = """\
당신은 채용 시장 전문 리서처입니다. 주어진 회사에 대한 검색 결과를 분석하여 구직자에게 유용한 회사 프로필을 JSON으로 작성합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "name": "회사명",
  "industry": "산업 분야",
  "description": "회사 설명 (2-3문장)",
  "culture_values": ["핵심 가치 1", "핵심 가치 2"],
  "tech_stack": ["기술1", "기술2"],
  "recent_news": ["최근 뉴스/동향 1", "최근 뉴스/동향 2"],
  "business_direction": "사업 방향성 요약",
  "employee_count": "직원 수 (알 수 있는 경우)",
  "headquarters": "본사 위치"
}"""


class CompanyResearcher:
    def __init__(
        self,
        llm: LLMClient,
        search: SearchClient,
        model: str = "claude-haiku-4-5-20251001",
    ):
        self.llm = llm
        self.search = search
        self.model = model

    async def research(self, company_name: str) -> CompanyProfile:
        """Research a company and return a structured profile."""
        search_results = await self._search_company(company_name)
        search_context = self._format_search_results(search_results)

        prompt = f"""다음 검색 결과를 바탕으로 '{company_name}'의 회사 프로필을 작성하세요.

검색 결과:
{search_context}

JSON 형식으로만 응답하세요."""

        data = await self.llm.generate_json(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            model=self.model,
        )
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict from LLM, got {type(data).__name__}")
        return CompanyProfile(**data)

    async def _search_company(self, company_name: str) -> list[dict]:
        """Run multiple searches for comprehensive company info."""
        queries = [
            f"{company_name} 회사 기업문화 기술스택",
            f"{company_name} 채용 복지 연봉",
            f"{company_name} 최근 뉴스 사업 방향",
        ]
        all_results = []
        for query in queries:
            results = await self.search.search(query, max_results=3)
            all_results.extend(results)
        return all_results

    def _format_search_results(self, results: list[dict]) -> str:
        """Format search results into a readable context string."""
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] {r['title']}\n{r['content']}\n")
        return "\n".join(parts)
