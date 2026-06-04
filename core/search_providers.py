import os
from dotenv import load_dotenv
import requests
from ddgs import DDGS

load_dotenv()

SPAM_DOMAINS = ["xnxx", "xhamster", "xvideo", "pornhat", "sexvid", "porn", "xxx", "xvideos"]


class BaseSearchProvider:
    name = "base"

    def search(self, queries: list[str]) -> list[dict]:
        raise NotImplementedError


class DuckDuckGoProvider(BaseSearchProvider):
    name = "duckduckgo"

    def search(self, queries: list[str]) -> list[dict]:
        all_results = []
        for query in queries:
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=5):
                    link = r.get("href") or ""
                    if any(d in link.lower() for d in SPAM_DOMAINS):
                        continue
                    results.append({
                        "title": r.get("title", ""),
                        "link": link,
                        "snippet": r.get("body", ""),
                    })
            all_results.append({"query": query, "results": results})
        return all_results


class TavilyProvider(BaseSearchProvider):
    name = "tavily"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("Tavily_key", "")

    def search(self, queries: list[str]) -> list[dict]:
        all_results = []
        for query in queries:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 8,
                },
                timeout=30,
            )
            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append({
                    "title": r.get("title", ""),
                    "link": r.get("url", ""),
                    "snippet": r.get("content", ""),
                })
            all_results.append({"query": query, "results": results})
        return all_results


class SerpApiProvider(BaseSearchProvider):
    name = "serpapi"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("SERPAPI_KEY", "")

    def search(self, queries: list[str]) -> list[dict]:
        all_results = []
        for query in queries:
            resp = requests.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": self.api_key,
                    "engine": "google",
                    "num": 8,
                },
                timeout=30,
            )
            data = resp.json()
            results = []
            for r in data.get("organic_results", []):
                results.append({
                    "title": r.get("title", ""),
                    "link": r.get("link", ""),
                    "snippet": r.get("snippet", ""),
                })
            all_results.append({"query": query, "results": results})
        return all_results


PROVIDER_MAP = {
    "duckduckgo": DuckDuckGoProvider,
    "tavily": TavilyProvider,
    "serpapi": SerpApiProvider,
}


def create_provider(name: str = None):
    name = name or os.getenv("SEARCH_PROVIDER", "duckduckgo")
    cls = PROVIDER_MAP.get(name)
    if not cls:
        raise ValueError(f"Unknown provider '{name}'. Options: {list(PROVIDER_MAP.keys())}")
    return cls()
