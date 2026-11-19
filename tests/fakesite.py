"""A fake website served through httpx.MockTransport. No network is used."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx


@dataclass
class Resource:
    body: bytes | str = b""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


def html(body: str, head: str = "") -> Resource:
    return Resource(
        f"<!doctype html><html><head>{head}</head><body>{body}</body></html>",
        200,
        {"content-type": "text/html; charset=utf-8"},
    )


@dataclass
class FakeSite:
    """Maps full URLs to resources and records every request."""

    resources: dict[str, Resource | Callable[[httpx.Request], httpx.Response]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)

    def add(self, url: str, resource: Resource | Callable[[httpx.Request], httpx.Response]) -> FakeSite:
        self.resources[url] = resource
        return self

    def redirect(self, url: str, to: str, status: int = 301) -> FakeSite:
        return self.add(url, Resource(b"", status, {"location": to}))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        res = self.resources.get(str(request.url))
        if res is None:
            return httpx.Response(404, headers={"content-type": "text/html"}, content=b"not found")
        if callable(res):
            return res(request)
        content = res.body.encode() if isinstance(res.body, str) else res.body
        return httpx.Response(res.status, headers=res.headers, content=content)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]
