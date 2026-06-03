from ddgs import DDGS
from typing import List, Dict

SPAM_DOMAINS = ["xnxx", "xhamster", "xvideo", "pornhat", "sexvid", "porn", "xxx", "xvideos"]


class WebSearchProductTool:
    def search(self, queries: List[str]) -> List[Dict]:
        all_results = []
        for query in queries:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=8):
                    link = r.get("href") or ""
                    # Lọc spam
                    if any(d in link.lower() for d in SPAM_DOMAINS):
                        continue
                    results.append({
                        "title": r.get("title", ""),
                        "link": link,
                        "snippet": r.get("body", ""),
                    })
            all_results.append({"query": query, "results": results})
        return all_results

    def format_for_llm(self, search_results: List[Dict]) -> str:
        output = []
        for res in search_results:
            output.append(f"Query: {res.get('query')}")
            for i, item in enumerate(res.get("results", []), 1):
                output.append(f"{i}. {item['title']}")
                output.append(f"   Link: {item['link']}")
                if item.get("snippet"):
                    output.append(f"   {item['snippet']}")
            output.append("")
        return "\n".join(output)
