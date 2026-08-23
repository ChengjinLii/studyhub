from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from studyhub_agent.guardrails.web_security import AddressResolver, WebSecurityPolicy


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True, slots=True)
class WebFetchResult:
    url: str
    title: str
    content: str
    content_type: str
    redirects: tuple[str, ...] = ()

    @property
    def response_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


class WebSearchProvider(Protocol):
    async def search(self, query: str, *, limit: int) -> list[WebSearchResult]: ...


class WebFetchProvider(Protocol):
    async def fetch(self, url: str) -> WebFetchResult | None: ...


class FixtureWebSearchProvider:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self._records = records

    @classmethod
    def from_json(cls, path: str | Path) -> FixtureWebSearchProvider:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    async def search(self, query: str, *, limit: int) -> list[WebSearchResult]:
        terms = {term.casefold() for term in query.split() if term.strip()}
        scored: list[tuple[int, WebSearchResult]] = []
        for record in self._records:
            searchable = f"{record['title']} {record['snippet']} {' '.join(record.get('keywords', []))}".casefold()
            score = sum(term in searchable for term in terms)
            if score:
                scored.append(
                    (
                        score,
                        WebSearchResult(
                            title=str(record["title"]),
                            url=str(record["url"]),
                            snippet=str(record["snippet"]),
                        ),
                    )
                )
        return [item for _, item in sorted(scored, key=lambda row: (-row[0], row[1].url))[:limit]]


class FixtureWebFetchProvider:
    def __init__(self, pages: list[WebFetchResult]) -> None:
        self._pages = {page.url: page for page in pages}

    @classmethod
    def from_json(cls, path: str | Path) -> FixtureWebFetchProvider:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([WebFetchResult(**{**value, "redirects": tuple(value.get("redirects", []))}) for value in values])

    async def fetch(self, url: str) -> WebFetchResult | None:
        return self._pages.get(url)


class GuardedWebProviders:
    def __init__(
        self,
        *,
        search_provider: WebSearchProvider,
        fetch_provider: WebFetchProvider,
        policy: WebSecurityPolicy,
        resolver: AddressResolver,
    ) -> None:
        self.search_provider = search_provider
        self.fetch_provider = fetch_provider
        self.policy = policy
        self.resolver = resolver

    async def search(self, query: str, *, limit: int) -> list[dict[str, object]]:
        results = await self.search_provider.search(query, limit=limit)
        return [asdict(result) for result in results if self._is_safe(result.url)]

    async def fetch(self, url: str) -> dict[str, object] | None:
        self.policy.validate_url(url, resolver=self.resolver)
        result = await self.fetch_provider.fetch(url)
        if result is None:
            return None
        for redirect in result.redirects:
            self.policy.validate_url(redirect, resolver=self.resolver)
        self.policy.validate_response(
            content_type=result.content_type,
            response_bytes=result.response_bytes,
            redirects=len(result.redirects),
        )
        return asdict(result)

    def _is_safe(self, url: str) -> bool:
        try:
            self.policy.validate_url(url, resolver=self.resolver)
        except ValueError:
            return False
        return True
