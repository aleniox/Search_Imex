"""Agent tìm hãng sản xuất — search web, crawl từng URL để lấy danh sách hãng.

Cách dùng:
    import asyncio
    from searchs.exhibition_research_agent import ProductDiscoveryAgent
    agent = ProductDiscoveryAgent()
    result = asyncio.run(agent.run("Phần mềm phân tích mã độc cho hệ thống máy tính"))
    print(result)
"""
import sys
import asyncio
import logging

from llm_client import LLMClient
from crawler import WebCrawler
from searcher import Searcher
from extractor import CompanyExtractor
from reporter import ReportCompiler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class ProductDiscoveryAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.crawler = WebCrawler()
        self.searcher = Searcher()
        self.extractor = CompanyExtractor(self.llm)
        self.reporter = ReportCompiler()
        self.companies: list[str] = []
        self.homepages: list[dict] = []
        self.last_response = ""

    async def run(self, user_query: str) -> str:
        self.companies = []
        self.homepages = []
        self.last_response = ""

        logger.info("─" * 50)
        logger.info(f"Step 1: Search URLs for: {user_query}")

        en_query = self.llm.call(
            "You are a translator. Return only the English translation, nothing else.",
            f"Translate to English: {user_query}",
        )
        if en_query:
            en_query = en_query.strip().strip('"\'')
        logger.info(f"   English: {en_query}")

        results = self.searcher.search([user_query, en_query or user_query])
        logger.info(f"   Got {len(results)} search results")

        logger.info("─" * 50)
        logger.info("Step 2: Crawl each URL and extract companies")

        all_companies = []
        seen = set()
        urls = list(dict.fromkeys(r["link"] for r in results if r.get("link")))

        for i, url in enumerate(urls[:3], 1):
            logger.info(f"[{i}/{min(len(urls), 3)}] Crawling: {url}")
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

        logger.info("─" * 50)
        logger.info(f"Step 3: Find homepages for {len(self.companies)} companies")
        for company in self.companies:
            url = self.searcher.find_homepage(company)
            self.homepages.append({"company": company, "url": url})
            logger.info(f"   {'✅' if url else '❌'} {company} -> {url or 'không tìm thấy'}")

        logger.info("─" * 50)
        logger.info("Step 4: Compile report")
        self.last_response = self.reporter.compile(user_query, self.companies, self.homepages)
        return self.last_response


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python exhibition_research_agent.py "Yêu cầu sản phẩm"')
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    agent = ProductDiscoveryAgent()
    result = asyncio.run(agent.run(query))
    print("\n" + result)
