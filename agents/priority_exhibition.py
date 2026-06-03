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

    async def run(self, excel_path: str, user_query: str) -> str:
        self._set_progress(0.02, "Đọc file Excel...")
        exhibitions = read_priority_exhibitions(excel_path)
        logger.info(f"Bước 1: {len(exhibitions)} triển lãm")

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

        self._set_progress(0.60, f"Lọc {len(unique)} hãng theo yêu cầu...")
        relevant = await self._filter_relevant(unique, user_query)
        logger.info(f"   Số hãng phù hợp: {len(relevant)}")

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

    async def _filter_relevant(self, companies: list[str], query: str) -> list[str]:
        batch_size = 50
        relevant = []
        for i in range(0, len(companies), batch_size):
            batch = companies[i:i + batch_size]
            company_list = "\n".join(f"- {c}" for c in batch)
            prompt = f"""From the following list of companies, which ones produce or supply products related to "{query}"?
Return only the company names that are relevant, one per line, without dashes or numbers.
If none are relevant, return exactly: NONE

Companies:
{company_list}"""
            result = self.llm.call("You are a product research expert.", prompt)
            if result and result.strip().upper() != "NONE":
                for line in result.split("\n"):
                    line = line.strip().lstrip("- ").strip().lstrip("1234567890. ").strip()
                    if line and line.upper() != "NONE":
                        relevant.append(line)
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
