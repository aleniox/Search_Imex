import logging
from .searcher import Searcher
from .crawler import WebCrawler
from .extractor import CompanyExtractor
from .search_providers import BaseSearchProvider

logger = logging.getLogger(__name__)


class ExhibitorFinder:
    def __init__(self, search_provider: str | BaseSearchProvider = None):
        self.searcher = Searcher(provider=search_provider)
        self.crawler = WebCrawler()
        self.extractor = CompanyExtractor()

    async def find_exhibitors(self, exhibition_name: str) -> list[str]:
        queries = [
            f"{exhibition_name} exhibitors list 2025",
            f"{exhibition_name} exhibitor list",
        ]
        results = self.searcher.search(queries)
        urls = list(dict.fromkeys(r["link"] for r in results if r.get("link")))

        companies = {}
        for url in urls[:2]:
            md = await self.crawler.crawl(url)
            if not md:
                continue
            extracted = self.extractor.extract(md, exhibition_name)
            if extracted:
                logger.info(f"      → {len(extracted)} hãng từ {url.split('/')[2]}")
            for c in extracted:
                companies[c.lower()] = c

        return list(companies.values())
