import asyncio
import os
import re
import json
from urllib.parse import urlparse

from dotenv import load_dotenv
import requests
from ddgs import DDGS
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

load_dotenv()

LLM_API = os.getenv("LLM_API_URL", "http://10.0.99.116:8070/v1/chat/completions")
BLOCKED_DOMAINS = [
    "wikipedia", "facebook", "youtube", "twitter", "linkedin",
    "crunchbase", "bloomberg", "reuters", "forbes", "glassdoor",
    "indeed", "zoominfo", "linkedin", "instagram", "tiktok",
]
SPAM_DOMAINS = ["xnxx", "xhamster", "xvideo", "pornhat", "sexvid", "porn", "xxx", "xvideos"]


def call_llm(system: str, user: str) -> tuple[str | None, dict]:
    payload = {
        "model": "", "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ], "stream": False,
        "options": {"temperature": 0.0, "top_p": 0.95, "top_k": 64, "num_ctx": 40000},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    resp = requests.post(LLM_API, json=payload, stream=False, timeout=120)
    if resp.status_code != 200:
        return None, {}
    data = resp.json()
    print(data.get("usage", data))
    return data["choices"][0]["message"]["content"], data.get("usage", {})


def search_web(queries: list[str]) -> str:
    if isinstance(queries, str):
        queries = [queries]
    text = ""
    for q in queries:
        with DDGS() as ddgs:
            for r in ddgs.text(q, max_results=5):
                link = r.get("href") or ""
                if any(d in link.lower() for d in SPAM_DOMAINS):
                    continue
                text += f"""Title: {r.get("title", "")}
Link: {link}
Snippet: {r.get("body", "")}\n"""
    return text


async def extract_web(url: str) -> str:
    try:
        config = CrawlerRunConfig(magic=True, simulate_user=True, override_navigator=True, page_timeout=15000)
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)
            md = (result.markdown or "").strip()
            if md:
                return md
    except Exception:
        pass
    try:
        resp = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        if resp.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            lines = [l.strip() for l in soup.get_text(separator="\n").split("\n") if len(l.strip()) > 30]
            return "\n".join(lines[:200])
    except Exception:
        pass
    return ""


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    return json.loads(text.strip())


def read_priority_exhibitions(filepath: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(filepath)
    ws = wb["AIPT Priority Shortlist"]
    lines = []
    for row in range(2, ws.max_row + 1):
        name = ws.cell(row, 5).value
        if not name:
            continue
        lines.append(f"{name} | Website: {ws.cell(row, 6).value or ''} | Category: {ws.cell(row, 7).value or ''} | Tags: {ws.cell(row, 8).value or ''}")
    return "\n".join(lines)


async def main():
    excel_path = r"D:\Search_Imex\AIPT_Global_Defense_Security_Exhibitions_Full_Database.xlsx"
    query = "Máy bay không người lái"
    MAX_STEPS = 20

    exhibitions = read_priority_exhibitions(excel_path)
    context = ""
    history = ""
    visited_urls = set()
    found: list[dict] = []

    system_prompt = """Bạn là chuyên gia tìm hãng cung cấp sản phẩm.

<tools>
search_web: Tìm kiếm web. Input: search query string.
extract_web: Đọc nội dung trang web. Input: một URL duy nhất.
answer: Kết thúc, trả danh sách hãng.
</tools>

<rules>
- Mỗi lần chỉ gọi MỘT tool.
- Không lặp tool/input đã dùng.
- Chỉ thêm hãng vào imex sau khi đã đọc website của họ để xác nhận.
- Khi đủ 5 hãng hoặc hết bước thì answer.
- Chỉ đọc web (HTML), không đọc file PDF/doc.
- Output là JSON array:
  [{"reason": "...", "next_action": "search_web|extract_web|answer", "input": "...", "context": "tóm tắt", "imex": ["hãng1"]}]
</rules>"""

    for step in range(MAX_STEPS):
        if len(found) >= 5:
            break

        print(f"\n===== STEP {step+1}/{MAX_STEPS} =====")

        user = f"""<query>{query}</query>
<step>{step+1}/{MAX_STEPS}</step>
<visited_urls>{", ".join(visited_urls) or "chưa có"}</visited_urls>
<history>{history[-5000:]}</history>
<context>{context[-40000:]}</context>
<exhibitions>{exhibitions}</exhibitions>
<companies_found_so_far>{json.dumps(found, ensure_ascii=False)}</companies_found_so_far>
<task>Tìm hãng cung cấp "{query}" từ danh sách triển lãm.

Hướng dẫn:
- extract_web website triển lãm → nội dung có link đến danh sách nhà triển lãm
- extract_web link đó để lấy tên các hãng
- search_web tìm website của hãng
- extract_web website hãng để xác nhận họ có sản phẩm phù hợp không
- Chỉ thêm hãng vào imex khi đã xác nhận qua website của họ</task>"""

        resp = call_llm(system_prompt, user)
        if not resp:
            print("LLM không phản hồi")
            continue

        print(f"LLM: {resp[:300]}")

        try:
            actions = extract_json(resp)
        except Exception as e:
            print(f"Parse JSON lỗi: {e}")
            continue

        if isinstance(actions, dict):
            actions = [actions]

        for act in actions:
            action = act.get("next_action", "")
            inp = act.get("input", "")

            if action == "answer":
                imex = act.get("imex", [])
                if isinstance(imex, list):
                    for c in imex:
                        if isinstance(c, str) and not any(f["company"] == c for f in found):
                            found.append({"company": c, "homepage": "", "match": True})
                break

            print(f"→ {action}: {inp[:100]}")

            if action == "search_web":
                data = search_web(inp)
                context += f"\n--- Search: {inp} ---\n{data[:5000]}"
                history += f"[S{step+1}] search_web('{inp}')\n"

            elif action == "extract_web":
                if inp in visited_urls:
                    print(f"  Bỏ qua URL đã visit")
                    continue
                visited_urls.add(inp)
                data = await extract_web(inp)
                if data:
                    context += f"\n--- Extract: {inp} ---\n{data[:10000]}"
                history += f"[S{step+1}] extract_web('{inp}')\n"

            imex = act.get("imex", [])
            if isinstance(imex, list):
                for c in imex:
                    if isinstance(c, str) and not any(f["company"] == c for f in found):
                        found.append({"company": c, "homepage": "", "match": True})
                        print(f"  + Hãng: {c}")

            if len(found) >= 5:
                break

    print(f"\n{'='*50}")
    print("KẾT QUẢ:")
    print("=" * 50)
    for v in found:
        print(f'{"✅" if v["match"] else "?"} {v["company"]:30s}')


if __name__ == "__main__":
    asyncio.run(main())
