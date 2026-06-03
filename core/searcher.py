from urllib.parse import urlparse
from .search_providers import create_provider, DuckDuckGoProvider, BaseSearchProvider

BLOCKED_DOMAINS = [
    "wikipedia", "facebook", "youtube", "twitter", "linkedin",
    "crunchbase", "bloomberg", "reuters", "forbes", "glassdoor",
    "indeed", "zoominfo", "linkedin", "instagram", "tiktok",
]


class Searcher:
    def __init__(self, provider: str | BaseSearchProvider = None):
        if isinstance(provider, BaseSearchProvider):
            self.provider = provider
        else:
            self.provider = create_provider(provider)

    def search(self, queries: list[str]) -> list[dict]:
        raw = self.provider.search(queries)
        results = []
        for r in raw:
            results.extend(r.get("results", []))
        return results

    def find_homepage(self, company: str) -> str:
        ddg = DuckDuckGoProvider()
        queries = [f"{company} official website", f"{company} trang chủ"]
        results = []
        raw = ddg.search(queries)
        for r in raw:
            results.extend(r.get("results", []))
        name_parts = company.lower().split()

        def domain(link: str) -> str:
            return urlparse(link).hostname or ""

        def is_blocked(link: str) -> bool:
            d = domain(link)
            return any(b in d for b in BLOCKED_DOMAINS)

        def name_in_domain(link: str) -> bool:
            d = domain(link).replace("www.", "")
            segments = d.split(".")
            joined = company.lower().replace(" ", "")
            if any(joined == seg for seg in segments):
                return True
            for p in name_parts:
                if len(p) > 3 and any(p == seg for seg in segments):
                    return True
            return False

        for r in results:
            link = r.get("link", "")
            if name_in_domain(link) and not is_blocked(link):
                return link

        for r in results:
            link = r.get("link", "")
            if is_blocked(link):
                continue
            title = r.get("title", "").lower()
            has_company = any(p in title for p in name_parts if len(p) > 3)
            has_official = any(w in title for w in ["official", "home", "trang ch"])
            if has_company and has_official:
                return link

        for r in results:
            link = r.get("link", "")
            if is_blocked(link):
                continue
            if any(p in link.lower() for p in name_parts if len(p) > 3):
                return link

        for r in results:
            link = r.get("link", "")
            if not is_blocked(link):
                return link

        return ""
