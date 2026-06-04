import sys
import asyncio
import logging

from core.llm_client import LLMClient
from core.crawler import WebCrawler
from core.searcher import Searcher
from core.extractor import CompanyExtractor
from core.reporter import ReportCompiler
from core.search_providers import BaseSearchProvider
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class ProductDiscoveryAgent:
    def __init__(self, search_provider: str | BaseSearchProvider = None, progress_callback=None):
        self.llm = LLMClient()
        self.crawler = WebCrawler()
        self.searcher = Searcher(provider=search_provider)
        self.extractor = CompanyExtractor(self.llm)
        self.reporter = ReportCompiler()
        self.companies: list[str] = []
        self.homepages: list[dict] = []
        self.last_response = ""
        self._progress = progress_callback

    def _set_progress(self, pct: float, msg: str):
        if self._progress:
            self._progress(pct, desc=msg)

    async def run(self, user_query: str) -> str:
        self.companies = []
        self.homepages = []
        self.last_response = ""

        self._set_progress(0.05, "Dịch query sang tiếng Anh...")
        logger.info(f"Step 1: Search URLs for: {user_query}")

        en_query = self.llm.call(
            """
        You are an expert sourcing and supplier discovery assistant.

        Given a product or technology, generate English search queries that help find real manufacturers, suppliers, vendors, distributors, and solution providers.

        Return ONLY valid JSON:

        {
        "search_queries": [
            "...",
            "...",
            "...",
            "..."
        ]
        }

        Rules:
        - Generate 6 search queries
        - Focus on discovering real companies
        - Prioritize manufacturer and supplier discovery
        - Use industry terminology when appropriate
        - Include different company types:
        - manufacturers
        - suppliers
        - vendors
        - distributors
        - solution providers
        - Avoid duplicate queries
        - Avoid simply replacing one synonym with another
        - Keep queries concise
        - No explanations
        - No markdown
        - No extra fields

        Query patterns should include:
        - <product> manufacturer
        - <product> supplier
        - <product> vendor
        - <product> company
        - <product> solutions
        - industry-specific variations
        """,
            f"Product: {user_query}",
        )
        if en_query:
            en_query = en_query.strip().strip('"\'')
        logger.info(f"   English: {en_query}")

        self._set_progress(0.1, "Đang search web...")
        data = json.loads(en_query)
        search_queries = data.get("search_queries", [])
        results = self.searcher.search(search_queries or [user_query])
        logger.info(f"   Got {len(results)} search results")

        self._set_progress(0.2, "Đang crawl & trích xuất hãng...")
        all_companies = []
        seen = set()
        urls = list(dict.fromkeys(r["link"] for r in results if r.get("link")))
        total_urls = min(len(urls), 3)

        for i, url in enumerate(urls[:3], 1):
            self._set_progress(0.2 + 0.5 * i / total_urls, f"Crawl {i}/{total_urls}...")
            logger.info(f"[{i}/{total_urls}] Crawling: {url}")
            md = await self.crawler.crawl(url)
            if not md:
                continue
            print(md + "\n---\n")
            companies = self.extractor.extract(md, user_query)
            for c in companies:
                if c.lower() not in seen:
                    seen.add(c.lower())
                    all_companies.append(c)

        self.companies = all_companies

        if not self.companies:
            return "Không tìm thấy hãng nào phù hợp."

        self._set_progress(0.7, f"Tìm homepage cho {len(self.companies)} hãng...")
        for i, company in enumerate(self.companies):
            self._set_progress(0.7 + 0.25 * (i + 1) / len(self.companies), f"Tìm homepage: {company}")
            url = self.searcher.find_homepage(company)
            self.homepages.append({"company": company, "url": url})
            logger.info(f"   {'✅' if url else '❌'} {company} -> {url or 'không tìm thấy'}")

        self._set_progress(0.95, "Tổng hợp báo cáo...")
        self.last_response = self.reporter.compile(user_query, self.companies, self.homepages)
        self._set_progress(1.0, "Hoàn tất!")
        return self.last_response


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python -m agents.product_discovery "Yêu cầu sản phẩm"')
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    agent = ProductDiscoveryAgent()
    result = asyncio.run(agent.run(query))
    print("\n" + result)
