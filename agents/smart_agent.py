import asyncio
import json
import logging
import re
from urllib.parse import urlparse

from core.llm_client import LLMClient, call_chat_api
from core.crawler import WebCrawler
from core.searcher import Searcher
from core.extractor import CompanyExtractor
from core.search_providers import BaseSearchProvider
from core.exhibition_reader import read_priority_exhibitions

logger = logging.getLogger(__name__)


def extract_json(text: str):
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


class SmartAgent:
    def __init__(self, search_provider: str | BaseSearchProvider = None, progress_callback=None):
        self.llm = LLMClient()
        self.searcher = Searcher(provider=search_provider)
        self.crawler = WebCrawler()
        self.extractor = CompanyExtractor(self.llm)
        self._progress = progress_callback
        self.max_steps = 20

    def _set_progress(self, pct: float, msg: str):
        if self._progress:
            self._progress(pct, desc=msg)

    def _search_web(self, query: str) -> str:
        results = self.searcher.search([query])
        lines = []
        for r in results[:5]:
            lines.append(f"Title: {r.get('title', '')}")
            lines.append(f"Link: {r.get('link', '')}")
            lines.append(f"Snippet: {r.get('snippet', '')}")
            lines.append("")
        return "\n".join(lines)

    async def _extract_web(self, url: str) -> str:
        return await self.crawler.crawl(url)

    def _build_prompt(self, query: str, context: str, history: str, visited: set, step: int, exhibitions: str = "") -> str:
        sys_prompt = """Bạn là chuyên gia phân tích web tìm hãng cung cấp sản phẩm.

<tools>
search_web: Tìm kiếm thông tin trên web. Input MUST be a search query string.
extract_web: Trích xuất nội dung từ URL. Input MUST be a single URL.
answer: Kết thúc và trả về danh sách hãng tìm được.
</tools>

<rules>
- Mỗi lần chỉ gọi MỘT tool duy nhất.
- Không gọi lại tool với input đã dùng.
- Không visit URL đã có trong visited_urls.
- Nội dung trả về phải là JSON array, mỗi phần tử có dạng:
  {
    "reason": "Lý do ngắn gọn",
    "next_action": "search_web | extract_web | answer",
    "input": "nội dung query hoặc URL",
    "context": "tóm tắt nội dung vừa lấy được",
    "imex": ["tên hãng tìm được, để trống nếu chưa có"]
  }
- Nếu số bước đạt tối đa, trả về answer để kết thúc.
- Khi có đủ thông tin, trả về answer kèm danh sách hãng.
</rules>"""

        user = f"""<query>{query}</query>
<step>{step}/{self.max_steps}</step>
<visited_urls>{", ".join(visited) or "chưa có"}</visited_urls>
<history>{history[-5000:]}</history>
<context>{context[-40000:]}</context>
{f'<exhibitions>{exhibitions}</exhibitions>' if exhibitions else ''}
<task>Tìm hãng cung cấp sản phẩm liên quan đến "{query}". Quyết định 1 hành động duy nhất.</task>"""
        return sys_prompt, user

    async def run(self, query: str, seed_url: str = "", excel_path: str = "") -> list[dict]:
        context = ""
        history = ""
        visited_urls = set()
        found_companies = []
        action_history = []

        exhibitions_data = ""
        if excel_path:
            try:
                exhs = read_priority_exhibitions(excel_path)
                exhibitions_data = "\n".join(
                    f"{e.name} | {e.website} | Cat: {e.category} | Tags: {e.tags}"
                    for e in exhs
                )
            except Exception as e:
                logger.warning(f"Không đọc được Excel: {e}")

        if seed_url:
            self._set_progress(0.05, f"Seed URL: {seed_url}")
            content = await self._extract_web(seed_url)
            if content:
                context += f"\n--- Nội dung từ {seed_url} ---\n{content[:10000]}"
                visited_urls.add(seed_url)

        self._set_progress(0.1, "Bắt đầu vòng lặp agent...")

        for step in range(self.max_steps):
            if len(found_companies) >= 5:
                break

            self._set_progress(0.1 + 0.8 * step / self.max_steps, f"Step {step+1}/{self.max_steps}...")

            sys_prompt, user_msg = self._build_prompt(
                query, context, history, visited_urls, step + 1, exhibitions_data
            )

            resp = call_chat_api(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_msg},
                ],
                stream=False,
            )
            if resp.status_code != 200:
                logger.error(f"LLM error: {resp.status_code}")
                continue

            raw = resp.json()["choices"][0]["message"]["content"]
            logger.info(f"LLM: {raw[:200]}")

            try:
                actions = extract_json(raw)
            except Exception as e:
                logger.warning(f"Parse JSON fail: {e}")
                continue

            if isinstance(actions, dict):
                actions = [actions]

            for act in actions:
                action = act.get("next_action", "")
                inp = act.get("input", "")

                if action == "answer":
                    imex = act.get("imex", [])
                    if isinstance(imex, list):
                        found_companies.extend(imex)
                    break

                if action == "search_web":
                    data = self._search_web(inp)
                    context += f"\n--- Search: {inp} ---\n{data[:5000]}"
                    history += f"[S{step+1}] search_web('{inp}')\n"

                elif action == "extract_web":
                    if inp in visited_urls:
                        logger.warning(f"Bỏ qua URL đã visit: {inp}")
                        continue
                    visited_urls.add(inp)
                    data = await self._extract_web(inp)
                    if data:
                        context += f"\n--- Extract: {inp} ---\n{data[:10000]}"
                    history += f"[S{step+1}] extract_web('{inp}')\n"

                extracted = act.get("imex", [])
                if isinstance(extracted, list):
                    for c in extracted:
                        if c and c not in found_companies:
                            found_companies.append(c)

                if len(found_companies) >= 5:
                    break

        self._set_progress(0.9, f"Verify {len(found_companies)} hãng...")

        verified = []
        for company in found_companies:
            if len(verified) >= 5:
                break
            logger.info(f"Verify: {company}")
            hp = self.searcher.find_homepage(company)
            if not hp:
                verified.append({"company": company, "homepage": "", "products": [], "verified": False})
                continue
            hp_content = await self._extract_web(hp)
            if hp_content:
                match = self.extractor.matchCompany(hp_content, query)
                if match and match.get("answer"):
                    verified.append({
                        "company": company,
                        "homepage": hp,
                        "products": match.get("products", []),
                        "verified": True,
                    })
                    logger.info(f"   ✅ {company} — {match.get('products', [])}")
                    continue
            verified.append({"company": company, "homepage": hp, "products": [], "verified": False})
            logger.info(f"   ❌ {company} — không xác nhận được")

        self._set_progress(1.0, "Hoàn tất!")
        return verified


if __name__ == "__main__":
    import sys

    async def main():
        agent = SmartAgent()
        excel = r"data/AIPT_Global_Defense_Security_Exhibitions_Full_Database.xlsx" if len(sys.argv) > 2 else ""
        seed = sys.argv[1] if len(sys.argv) > 1 else ""
        query = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1] if len(sys.argv) > 1 else ""
        result = await agent.run(query, seed_url=seed, excel_path=excel)
        for r in result:
            status = "✅" if r["verified"] else "❌"
            print(f'{status} {r["company"]:30s} | {r["homepage"]:40s} | SP: {", ".join(r["products"])}')

    asyncio.run(main())
