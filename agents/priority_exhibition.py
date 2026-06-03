import asyncio
import logging

from core.llm_client import LLMClient
from core.searcher import Searcher
from core.crawler import WebCrawler
from core.extractor import CompanyExtractor
from core.reporter import ReportCompiler
from core.exhibition_reader import read_priority_exhibitions
from core.exhibitor_finder import ExhibitorFinder
from core.search_providers import BaseSearchProvider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class PriorityExhibitionAgent:
    def __init__(self, search_provider: str | BaseSearchProvider = None, progress_callback=None):
        self.llm = LLMClient()
        self.searcher = Searcher(provider=search_provider)
        self.crawler = WebCrawler()
        self.extractor = CompanyExtractor(self.llm)
        self.finder = ExhibitorFinder(search_provider=search_provider)
        self.reporter = ReportCompiler()
        self._progress = progress_callback

    def _set_progress(self, pct: float, msg: str):
        if self._progress:
            self._progress(pct, desc=msg)

    def _filter_exhibitions(self, exhibitions: list, query: str) -> list:
        lines = "\n".join(
            f"{i+1}. {e.name} | Category: {e.category} | Tags: {e.tags}"
            for i, e in enumerate(exhibitions)
        )
        prompt = f"""From the list below, select exhibitions whose category or tags are RELEVANT to: "{query}"
Return only the line numbers of relevant exhibitions, separated by commas.
If none, return: NONE

{lines}"""
        result = self.llm.call("You are a domain expert in defense and security exhibitions.", prompt)
        if not result or result.strip().upper() == "NONE":
            return []
        indices = set()
        for part in result.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(exhibitions):
                    indices.add(idx)
        return [exhibitions[i] for i in sorted(indices)]

    async def run(self, excel_path: str, user_query: str) -> str:
        self._set_progress(0.02, "Đọc file Excel...")
        exhibitions = read_priority_exhibitions(excel_path)
        logger.info(f"Bước 1a: {len(exhibitions)} triển lãm (tất cả)")

        self._set_progress(0.03, "Lọc triển lãm theo yêu cầu...")
        exhibitions = self._filter_exhibitions(exhibitions, user_query)
        logger.info(f"Bước 1b: {len(exhibitions)} triển lãm phù hợp với yêu cầu")
        if not exhibitions:
            return "Không có triển lãm nào phù hợp với yêu cầu."

        self._set_progress(0.05, f"Tìm hãng từ {len(exhibitions)} triển lãm...")
        all_raw = []
        batch_size = 5
        total = len(exhibitions)
        for start in range(0, total, batch_size):
            batch = exhibitions[start:start + batch_size]
            tasks = [self.finder.find_exhibitors(exh.name) for exh in batch]
            results = await asyncio.gather(*tasks)
            for i, companies in enumerate(results):
                idx = start + i + 1
                self._set_progress(0.05 + 0.55 * idx / total, f"Triển lãm {idx}/{total}: {batch[i].name}")
                logger.info(f"   [{idx}/{total}] {batch[i].name} → {len(companies)} hãng")
                all_raw.extend(companies)

        unique = list(dict.fromkeys(c.lower() for c in all_raw))
        logger.info(f"   Tổng hãng (sau dedup): {len(unique)}")

        if not unique:
            return "Không tìm thấy hãng nào từ danh sách triển lãm."

        self._set_progress(0.60, f"Tìm sản phẩm cho từng hãng theo yêu cầu...")
        relevant = await self._find_relevant_companies(unique, user_query)
        logger.info(f"   Số hãng có sản phẩm phù hợp: {len(relevant)}")

        if not relevant:
            return "Không có hãng nào phù hợp với yêu cầu."

        self._set_progress(0.80, f"Tìm homepage cho {len(relevant)} hãng...")
        homepages = []
        for i, company in enumerate(relevant):
            self._set_progress(0.80 + 0.15 * (i + 1) / len(relevant), f"Tìm homepage: {company}")
            url = self.searcher.find_homepage(company)
            homepages.append({"company": company, "url": url})
            logger.info(f"   {'✅' if url else '❌'} {company} -> {url or 'không tìm thấy'}")

        self._set_progress(0.95, "Tổng hợp báo cáo...")
        report = self.reporter.compile(user_query, relevant, homepages)
        self._set_progress(1.0, "Hoàn tất!")
        return report

    async def _find_relevant_companies(self, companies: list[str], query: str) -> list[str]:
        async def check(company: str) -> str | None:
            results = self.searcher.search([f"{company} {query}"])
            if not results:
                return None
            snippets = " ".join(r.get("snippet", "")[:200] for r in results[:5])
            if len(snippets) < 20:
                return None
            prompt = f"""Does this company provide products or solutions related to "{query}"?
Based on the search snippets below, answer only YES or NO.

Company: {company}
Snippets: {snippets}"""
            answer = self.llm.call("You are a product research assistant.", prompt)
            if answer and "YES" in answer.upper():
                logger.info(f"   ✅ {company} — có sản phẩm liên quan")
                return company
            return None

        relevant = []
        batch_size = 10
        for i in range(0, len(companies), batch_size):
            batch = companies[i:i + batch_size]
            self._set_progress(0.60 + 0.20 * i / len(companies), f"Kiểm tra hãng {i+1}-{min(i+batch_size, len(companies))}/{len(companies)}...")
            tasks = [check(c) for c in batch]
            results = await asyncio.gather(*tasks)
            for r in results:
                if r:
                    relevant.append(r)
        return relevant


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print('Usage: python -m agents.priority_exhibition <excel_path> "Yêu cầu sản phẩm"')
        sys.exit(1)
    excel_path = sys.argv[1]
    query = " ".join(sys.argv[2:])
    agent = PriorityExhibitionAgent()
    result = asyncio.run(agent.run(excel_path, query))
    print("\n" + result)
