import logging
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

TIMEOUT = 10
logger = logging.getLogger(__name__)


def _is_reachable(url: str) -> bool:
    try:
        r = requests.head(url, timeout=5)
        return r.status_code < 500
    except Exception:
        return False


class WebCrawler:
    async def crawl(self, url: str) -> str:
        if not _is_reachable(url):
            logger.warning(f"⚠️ {url} — unreachable, skip")
            return ""
        md = await self._crawl_playwright(url)
        if md:
            return md
        return self._crawl_requests(url)

    async def _crawl_playwright(self, url: str) -> str:
        try:
            config = CrawlerRunConfig(
                magic=True,
                simulate_user=True,
                override_navigator=True,
                page_timeout=TIMEOUT * 1000,
            )
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)
                md = (result.markdown or "").strip()
                if md:
                    logger.info(f"✅ {len(md)} chars from {url}")
                    return md
        except Exception as e:
            logger.debug(f"Playwright fail {url}: {e}")
        return ""

    def _crawl_requests(self, url: str) -> str:
        try:
            resp = requests.get(url, timeout=TIMEOUT, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            if resp.status_code != 200:
                return ""
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            lines = [l for l in text.split("\n") if len(l) > 30]
            result = "\n".join(lines[:200])
            if result:
                logger.info(f"✅ requests fallback: {len(result)} chars from {url}")
                return result
        except Exception as e:
            logger.debug(f"Requests fail {url}: {e}")
        return ""
