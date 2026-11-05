"""Website scraper service for extracting company intelligence and contact emails."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List
from urllib.parse import urlparse

import httpx

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
IGNORED_EMAIL_PREFIXES = ("noreply", "no-reply", "donotreply", "example", "sentry", "wix")


@dataclass
class ScrapedWebsiteData:
    url: str
    domain: str
    title: str = ""
    meta_description: str = ""
    headings: List[str] = field(default_factory=list)
    emails_found: List[str] = field(default_factory=list)
    body_excerpt: str = ""
    reachable: bool = False


class _StdlibHTMLParser(HTMLParser):
    """Lightweight HTML parser fallback when BeautifulSoup4 is not installed."""

    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.in_heading = False
        self.in_ignored = False
        self.title_parts: List[str] = []
        self.headings: List[str] = []
        self.meta_description: str = ""
        self.text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg"):
            self.in_ignored = True
        elif t == "title":
            self.in_title = True
        elif t in ("h1", "h2"):
            self.in_heading = True
        elif t == "meta":
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            if attr_dict.get("name", "").lower() == "description":
                self.meta_description = attr_dict.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "svg"):
            self.in_ignored = False
        elif t == "title":
            self.in_title = False
        elif t in ("h1", "h2"):
            self.in_heading = False

    def handle_data(self, data: str) -> None:
        if self.in_ignored:
            return
        stripped = data.strip()
        if not stripped:
            return
        if self.in_title:
            self.title_parts.append(stripped)
        if self.in_heading and len(self.headings) < 8:
            self.headings.append(stripped)
        self.text_parts.append(stripped)


class WebsiteScraper:
    """Scrapes company websites to extract context, value props, and contact emails."""

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            )
        }

    async def scrape_url(self, url: str) -> ScrapedWebsiteData:
        if not url:
            return ScrapedWebsiteData(url="", domain="")

        normalized_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
        parsed = urlparse(normalized_url)
        domain = parsed.netloc.replace("www.", "")

        result = ScrapedWebsiteData(url=normalized_url, domain=domain)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.headers,
            ) as client:
                response = await client.get(normalized_url)
                response.raise_for_status()
                html = response.text
                result.reachable = True
                self._parse_html(html, result)
        except Exception:
            result.reachable = False
        return result

    async def fetch_company_context(self, url: str) -> dict:
        data = await self.scrape_url(url)
        return {
            "url": data.url,
            "domain": data.domain,
            "title": data.title,
            "description": data.meta_description,
            "text_snippet": data.body_excerpt,
            "reachable": data.reachable,
        }

    def _parse_html(self, html: str, result: ScrapedWebsiteData) -> None:
        raw_emails = set(EMAIL_REGEX.findall(html))
        filtered_emails = [
            e.lower()
            for e in raw_emails
            if not e.lower().startswith(IGNORED_EMAIL_PREFIXES)
            and not e.lower().endswith((".png", ".jpg", ".svg", ".webp", ".gif"))
        ]
        result.emails_found = sorted(set(filtered_emails))[:5]

        parser = _StdlibHTMLParser()
        parser.feed(html)
        result.title = " ".join(parser.title_parts)
        result.meta_description = parser.meta_description
        result.headings = parser.headings
        result.body_excerpt = " ".join(parser.text_parts)[:1800]
