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

    def filter_exhibitions(self, exhibitions: list, query: str) -> list:
        import json
        import re
        lines = "\n".join(
            f"{i+1}. {e.name} | Category: {e.category} | Tags: {e.tags}"
            for i, e in enumerate(exhibitions)
        )
        prompt = f"""Bạn là một chuyên gia phân tích triển lãm thương mại B2B. 
Nhiệm vụ của bạn là phân tích danh sách triển lãm dưới đây và chọn ra những triển lãm có khả năng cao quy tụ các NHÀ CUNG CẤP (suppliers/vendors) cung cấp giải pháp hoặc sản phẩm mà người dùng đang tìm kiếm.

Yêu cầu tìm kiếm giải pháp của người dùng:
<user query>
"{query}"
</user query>

Yêu cầu đầu ra:
Chỉ trả về duy nhất một mảng JSON (JSON array) chứa các đối tượng. Không viết thêm lời dẫn nhập, không giải thích dông dài.
Nếu không có triển lãm nào phù hợp, trả về một mảng rỗng: []

Cấu trúc JSON bắt buộc:
[
  {{
    "index": 1,
    "exhibition_name": "Tên chính xác của triển lãm",
    "score": 85,
    "reason": "Lý do ngắn gọn (dưới 20 từ) giải thích vì sao triển lãm này quy tụ các nhà cung cấp giải pháp `{query}`"
  }}
]

Danh sách triển lãm cần phân tích (được đánh số thứ tự):
<danh sách triển lãm>
{lines}
</danh sách triển lãm>
"""

        result_str = self.llm.call("Bạn dùng để thực hiện nhiệm vụ phân loại triển lãm.", prompt)
        try:
            # Tìm JSON trong response
            json_match = re.search(r"\[.*\]", result_str, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
            else:
                data = json.loads(result_str)
            
            indices = set()
            for item in data:
                idx = int(item.get("index")) - 1
                if 0 <= idx < len(exhibitions):
                    logger.info(f"   [Lọc] Chọn: {exhibitions[idx].name} (Score: {item.get('score')}) - Lý do: {item.get('reason')}")
                    indices.add(idx)
            return [exhibitions[i] for i in sorted(indices)]
        except Exception as e:
            logger.error(f"Lỗi phân tích JSON từ LLM: {e}. Thử fallback tìm số.")
            indices = set()
            for part in re.findall(r"\d+", result_str):
                idx = int(part) - 1
                if 0 <= idx < len(exhibitions):
                    indices.add(idx)
            return [exhibitions[i] for i in sorted(indices)]

    async def run(self, excel_path: str, user_query: str, scan_all: bool=False) -> str:
        self._set_progress(0.02, "Đọc file Excel...")
        exhibitions = read_priority_exhibitions(excel_path)
        logger.info(f"Bước 1a: {len(exhibitions)} triển lãm (tất cả)")

        if not scan_all:
            self._set_progress(0.03, "Lọc triển lãm theo yêu cầu...")
            exhibitions = self.filter_exhibitions(exhibitions, user_query)
            logger.info(f"Bước 1b: {len(exhibitions)} triển lãm phù hợp với yêu cầu")
        else:
            logger.info("Bỏ qua bước lọc, quét tất cả triển lãm theo yêu cầu (scan_all=True)")

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
        
        companies_with_products = []
        for i, company in enumerate(unique):
            homepage_link = self.searcher.find_homepage(company)
            logger.info(f"   [{i+1}/{len(unique)}] {company} → {homepage_link or 'không tìm thấy homepage'}")
            homepage_rawl = self.crawler._crawl_playwright(homepage_link) if homepage_link else ""
            if homepage_rawl:
                # products = self.extractor.extract(homepage_rawl, user_query)
                products = self.extractor.matchCompany(homepage_rawl, user_query)
                if products:
                    match_cmp = products["answer"]
                    related_products = products["products"]
                    if match_cmp:
                        logger.info(f"   ✅ {company} có cung cấp sản phẩm liên quan đến yêu cầu")
                        logger.info(f"       → Sản phẩm liên quan: {related_products}")
                        companies_with_products.append({
                            "company": company,
                            "products": related_products,
                            "homepage": homepage_link,
                        })
                        if not scan_all:
                            break
                    else:
                        logger.info(f"   ❌ {company} không cung cấp sản phẩm liên quan đến yêu cầu")
                        
                    logger.info(f"       → {related_products} sản phẩm liên quan từ homepage")

        return companies_with_products

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
