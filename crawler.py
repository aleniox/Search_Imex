import logging
from crawl4ai import AsyncWebCrawler

logger = logging.getLogger(__name__)


class WebCrawler:
    async def crawl(self, url: str) -> str:
        try:
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url)
                md = (result.markdown or "")
                if md.strip():
                    logger.info(f"✅ {len(md)} chars from {url}")
                    return md
                return ""
        except Exception as e:
            logger.warning(f"⚠️ {url}: {e}")
            return ""
