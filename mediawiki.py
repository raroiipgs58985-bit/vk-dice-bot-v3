from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from config import Settings


_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)", re.IGNORECASE)
_RAW_WIKI_URL_RE = re.compile(
    r"https?://wh40k\.lexicanum\.com/wiki/[^\s)\]>]+", re.IGNORECASE
)


@dataclass(frozen=True)
class MediaWikiDiscovery:
    urls: list[str]
    queries_attempted: int
    errors: int
    api_available: bool


class MediaWikiSearcher:
    """Discovers likely article URLs without crawling the whole wiki."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        parsed = urlsplit(settings.site_base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.user_agent,
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
                "Accept-Language": "en,ru;q=0.8",
            }
        )

    def discover(
        self,
        queries: Iterable[str],
        *,
        title_candidates: Iterable[str] = (),
        deep: bool,
        deadline: float | None = None,
    ) -> MediaWikiDiscovery:
        query_limit = (
            self.settings.mediawiki_deep_query_limit
            if deep
            else self.settings.mediawiki_query_limit
        )
        result_limit = (
            self.settings.mediawiki_deep_results_per_query
            if deep
            else self.settings.mediawiki_results_per_query
        )
        article_limit = self.settings.deep_max_pages if deep else self.settings.max_pages

        cleaned = self._clean_queries(queries, query_limit)
        urls: list[str] = []
        seen: set[str] = set()
        errors = 0
        api_available = True
        attempted = 0

        # First try likely exact article titles produced by the language model. This
        # still works when Lexicanum blocks its bot/search endpoints from Render IPs.
        direct_values = self._clean_queries(title_candidates, 12 if deep else 8)
        for title in direct_values:
            url = self._article_url(title)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        for query in cleaned:
            if deadline is not None and time.monotonic() >= deadline:
                break
            attempted += 1
            found: list[str] = []

            if api_available:
                try:
                    found = self._search_api(query, result_limit)
                except (requests.RequestException, ValueError, TypeError, KeyError):
                    errors += 1
                    api_available = False

            if not found:
                try:
                    found = self._search_html(query, result_limit)
                except requests.RequestException:
                    errors += 1

            if not found and self.settings.jina_reader_fallback:
                try:
                    found = self._search_via_jina(query, result_limit)
                except requests.RequestException:
                    errors += 1

            # A short search phrase is also a useful possible MediaWiki title.
            if not found and len(query.split()) <= 7:
                candidate = self._article_url(query)
                if candidate:
                    found = [candidate]

            for url in found:
                if url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= article_limit:
                    return MediaWikiDiscovery(
                        urls=urls,
                        queries_attempted=attempted,
                        errors=errors,
                        api_available=api_available,
                    )

            if self.settings.request_delay_seconds > 0:
                time.sleep(self.settings.request_delay_seconds)

        return MediaWikiDiscovery(
            urls=urls[:article_limit],
            queries_attempted=attempted,
            errors=errors,
            api_available=api_available,
        )

    def _api_candidates(self) -> list[str]:
        candidates = [
            self.settings.resolved_mediawiki_api_url,
            urljoin(self.settings.site_base_url, "/mediawiki/"),
            urljoin(self.settings.site_base_url, "/mediawiki/api.php"),
        ]
        return list(dict.fromkeys(candidates))

    def _search_api(self, query: str, limit: int) -> list[str]:
        last_error: Exception | None = None
        for endpoint in self._api_candidates():
            try:
                response = self.session.get(
                    endpoint,
                    params={
                        "action": "query",
                        "list": "search",
                        "srsearch": query,
                        "srnamespace": "0",
                        "srlimit": str(limit),
                        "srprop": "snippet|titlesnippet",
                        "utf8": "1",
                        "format": "json",
                        "formatversion": "2",
                    },
                    timeout=self.settings.request_timeout_seconds,
                    allow_redirects=True,
                )
                response.raise_for_status()
                payload = response.json()
                raw_results = payload.get("query", {}).get("search", [])
                if not isinstance(raw_results, list):
                    raise ValueError("MediaWiki search response has no result list")
                urls = []
                for item in raw_results:
                    if not isinstance(item, dict):
                        continue
                    url = self._article_url(str(item.get("title", "")).strip())
                    if url:
                        urls.append(url)
                if urls:
                    return list(dict.fromkeys(urls))
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        return []

    def _search_html(self, query: str, limit: int) -> list[str]:
        targets = [
            (
                urljoin(self.settings.site_base_url, "/wiki/Special:Search"),
                {"search": query, "fulltext": "1", "ns0": "1"},
            ),
            (
                urljoin(self.settings.site_base_url, "/mediawiki/index.php"),
                {
                    "title": "Special:Search",
                    "search": query,
                    "fulltext": "Search",
                    "ns0": "1",
                },
            ),
        ]
        last_error: Exception | None = None
        for search_url, params in targets:
            try:
                response = self.session.get(
                    search_url,
                    params=params,
                    timeout=self.settings.request_timeout_seconds,
                    allow_redirects=True,
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                urls = self._extract_html_result_urls(soup, response.url, limit)
                if urls:
                    return urls
            except requests.RequestException as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return []

    def _search_via_jina(self, query: str, limit: int) -> list[str]:
        target = urljoin(self.settings.site_base_url, "/wiki/Special:Search")
        target += "?" + urlencode({"search": query, "fulltext": "1", "ns0": "1"})
        reader_url = "https://r.jina.ai/" + target
        response = self.session.get(
            reader_url,
            headers={"Accept": "text/plain"},
            timeout=self.settings.jina_reader_timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()
        candidates = [*_MARKDOWN_LINK_RE.findall(response.text), *_RAW_WIKI_URL_RE.findall(response.text)]
        urls: list[str] = []
        for value in candidates:
            value = html.unescape(value).rstrip(".,;:")
            if self._is_article_url(value):
                value = self._strip_fragment(value)
                if value not in urls:
                    urls.append(value)
            if len(urls) >= limit:
                break
        return urls

    def _extract_html_result_urls(
        self, soup: BeautifulSoup, response_url: str, limit: int
    ) -> list[str]:
        anchors = soup.select(
            ".mw-search-result-heading a, "
            "ul.mw-search-results li a, "
            ".searchresults a, "
            "a[data-serp-pos]"
        )
        urls: list[str] = []
        for anchor in anchors:
            href = str(anchor.get("href", "")).strip()
            title = str(anchor.get("title", "")).strip()
            url = urljoin(response_url, href) if href else self._article_url(title)
            if not url or not self._is_article_url(url):
                continue
            url = self._strip_fragment(url)
            if url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    def _article_url(self, title: str) -> str | None:
        title = html.unescape(title).strip().strip('"\'')
        if not title or self._is_non_article_title(title):
            return None
        encoded = quote(title.replace(" ", "_"), safe="()'!,:;@+-._~")
        path = self.settings.mediawiki_article_path.format(title=encoded)
        return urljoin(self.origin + "/", path.lstrip("/"))

    def _is_article_url(self, url: str) -> bool:
        parsed = urlsplit(url)
        base = urlsplit(self.settings.site_base_url)
        if parsed.hostname != base.hostname:
            return False
        path = parsed.path.casefold()
        if "/wiki/" not in path:
            return False
        lowered = html.unescape(url).casefold()
        blocked = (
            "special:", "special%3a", "talk:", "talk%3a", "user:",
            "user%3a", "file:", "file%3a", "category:", "category%3a",
            "template:", "template%3a", "help:", "help%3a",
        )
        return not any(value in lowered for value in blocked)

    @staticmethod
    def _is_non_article_title(title: str) -> bool:
        namespace = title.split(":", 1)[0].casefold() if ":" in title else ""
        return namespace in {
            "special", "talk", "user", "user talk", "file", "file talk",
            "category", "category talk", "template", "template talk",
            "help", "help talk", "portal", "portal talk",
        }

    @staticmethod
    def _strip_fragment(url: str) -> str:
        return urlsplit(url)._replace(fragment="").geturl()

    @staticmethod
    def _clean_queries(values: Iterable[str], limit: int) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value).split()).strip()
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            result.append(text[:180])
            if len(result) >= limit:
                break
        return result
