from search_wb import WebSearchProductTool


class Searcher:
    def __init__(self):
        self.tool = WebSearchProductTool()

    def search(self, queries: list[str]) -> list[dict]:
        raw = self.tool.search(queries)
        results = []
        for r in raw:
            results.extend(r.get("results", []))
        return results

    def find_homepage(self, company: str) -> str:
        queries = [f"{company} official website", f"{company} trang chủ"]
        results = self.search(queries)
        for r in results:
            link = r.get("link", "")
            title = r.get("title", "").lower()
            name_parts = company.lower().split()
            if any(p in link.lower() for p in name_parts if len(p) > 3):
                return link
            if name_parts[0] in title and ("official" in title or "home" in title or "trang ch" in title):
                return link
        for r in results:
            link = r.get("link", "")
            if not any(d in link.lower() for d in ["facebook", "youtube", "twitter", "linkedin"]):
                return link
        return ""
