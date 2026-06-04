import asyncio
from crawl4ai import *

async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://www.tualcom.com/",
        )
        print(result.markdown)

# In Jupyter notebooks, just await directly
asyncio.run(main())