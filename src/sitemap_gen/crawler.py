"""A polite, asynchronous, same-host crawler built on httpx."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from sitemap_gen._version import __version__
from sitemap_gen.parser import parse_html, parse_robots_directives
from sitemap_gen.robots import RobotsTxt
from sitemap_gen.urls import has_skipped_extension, host_of, normalize_url, same_site

log = logging.getLogger("sitemap_gen")

DEFAULT_USER_AGENT = f"sitemap-gen/{__version__} (+https://github.com/saizul/sitemap-gen)"
HTML_TYPES = ("text/html", "application/xhtml+xml")
MAX_ROBOTS_BYTES = 512 * 1024
MAX_CRAWL_DELAY = 60.0
MAX_IMAGES_PER_PAGE = 1000
MAX_ALTERNATES_PER_PAGE = 500
# A BCP 47 language tag (en, en-GB, zh-Hant-TW, es-419) or x-default, as Google accepts in hreflang.
HREFLANG_RE = re.compile(r"^(?:x-default|[a-z]{2,3}(?:-[a-z0-9]{1,8})*)$", re.IGNORECASE)


@dataclass
class CrawlConfig:
    start_url: str
    max_pages: int = 10_000
    """Stop after fetching this many pages."""
    max_depth: int | None = None
    """Follow links at most this many clicks from the start URL (``None``: no limit)."""
    concurrency: int = 4
    delay: float = 0.0
    """Minimum seconds between two requests. A larger robots.txt Crawl-delay wins."""
    timeout: float = 15.0
    user_agent: str = DEFAULT_USER_AGENT
    lastmod: bool = False
    """Record the Last-Modified response header as <lastmod>."""
    images: bool = False
    """Collect <img> URLs for an image sitemap."""
    hreflang: bool = False
    """Collect <link rel="alternate" hreflang> alternates, and crawl the same-site ones."""
    include: list[str] = field(default_factory=list)
    """Only crawl URLs matching at least one of these regular expressions."""
    exclude: list[str] = field(default_factory=list)
    """Never crawl URLs matching any of these regular expressions."""
    strip_query: bool = False
    follow_nofollow: bool = False
    max_page_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if self.max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if self.max_depth is not None and self.max_depth < 0:
            raise ValueError("max_depth must be 0 or more")
        if not 1 <= self.concurrency <= 64:
            raise ValueError("concurrency must be between 1 and 64")
        if self.delay < 0 or self.timeout <= 0:
            raise ValueError("delay must be >= 0 and timeout > 0")
        for pattern in (*self.include, *self.exclude):
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {pattern!r}: {exc}") from None


@dataclass
class Page:
    url: str
    depth: int
    lastmod: datetime | None = None
    images: list[str] = field(default_factory=list)
    alternates: list[tuple[str, str]] = field(default_factory=list)
    """``(hreflang, url)`` pairs the page declares, when ``CrawlConfig.hreflang`` is on."""


@dataclass
class CrawlResult:
    start_url: str
    origin: str
    pages: list[Page] = field(default_factory=list)
    fetched: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    errors: list[tuple[str, str]] = field(default_factory=list)
    crawl_delay: float = 0.0

    def sorted_pages(self) -> list[Page]:
        """Pages ordered by depth, then URL, so output is stable between runs."""
        return sorted(self.pages, key=lambda p: (p.depth, p.url))


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class Crawler:
    def __init__(
        self,
        config: CrawlConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        start = normalize_url(config.start_url, strip_query=config.strip_query)
        if start is None:
            raise ValueError(f"not an http(s) URL: {config.start_url!r}")
        self.config = config
        self.start = start
        self.result = CrawlResult(start_url=start, origin=host_of(start))
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._include = [re.compile(p) for p in config.include]
        self._exclude = [re.compile(p) for p in config.exclude]
        self._robots: dict[str, RobotsTxt] = {}
        self._seen: set[str] = set()
        self._queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._rate_lock = asyncio.Lock()
        self._next_request_at = 0.0
        self._interval = config.delay

    # -- politeness -----------------------------------------------------------------

    async def _robots_for(self, client: httpx.AsyncClient, origin: str) -> RobotsTxt:
        if origin in self._robots:
            return self._robots[origin]
        url = f"{origin}/robots.txt"
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code == 200:
                    body = b""
                    async for chunk in resp.aiter_bytes():
                        body += chunk
                        if len(body) >= MAX_ROBOTS_BYTES:
                            body = body[:MAX_ROBOTS_BYTES]
                            break
                    robots = RobotsTxt.parse(body.decode("utf-8", errors="replace"))
                elif 400 <= resp.status_code < 500:
                    # RFC 9309 2.3.1.3: "unavailable" means crawling is allowed.
                    robots = RobotsTxt.allowing_all()
                else:
                    # RFC 9309 2.3.1.4: "unreachable" (5xx) means a complete disallow.
                    log.warning("robots.txt at %s returned HTTP %s: not crawling", url, resp.status_code)
                    robots = RobotsTxt.disallowing_all()
        except httpx.HTTPError as exc:
            log.warning("could not fetch %s (%s): not crawling", url, exc)
            robots = RobotsTxt.disallowing_all()
        self._robots[origin] = robots
        delay = robots.crawl_delay(self.config.user_agent)
        if delay:
            delay = min(delay, MAX_CRAWL_DELAY)
            self._interval = max(self._interval, delay)
            self.result.crawl_delay = max(self.result.crawl_delay, delay)
            log.info("robots.txt asks for a crawl delay of %ss", delay)
        return robots

    async def _wait_turn(self) -> None:
        if self._interval <= 0:
            return
        async with self._rate_lock:
            now = self._clock()
            wait = self._next_request_at - now
            if wait > 0:
                await self._sleep(wait)
                now = self._clock()
            self._next_request_at = max(now, self._next_request_at) + self._interval

    # -- queueing -------------------------------------------------------------------

    def _wanted(self, url: str) -> bool:
        if not same_site(url, self.result.origin):
            return False
        if has_skipped_extension(url):
            self.result.skipped["extension"] += 1
            return False
        if self._include and not any(p.search(url) for p in self._include):
            self.result.skipped["excluded"] += 1
            return False
        if any(p.search(url) for p in self._exclude):
            self.result.skipped["excluded"] += 1
            return False
        return True

    def _enqueue(self, url: str, depth: int) -> None:
        if url in self._seen:
            return
        if self.config.max_depth is not None and depth > self.config.max_depth:
            self._seen.add(url)
            self.result.skipped["max-depth"] += 1
            return
        if not self._wanted(url):
            self._seen.add(url)
            return
        self._seen.add(url)
        self._queue.put_nowait((url, depth))

    # -- fetching -------------------------------------------------------------------

    async def _process(self, client: httpx.AsyncClient, url: str, depth: int) -> None:
        cfg = self.config
        result = self.result
        robots = await self._robots_for(client, host_of(url))
        if not robots.can_fetch(cfg.user_agent, url):
            result.skipped["robots"] += 1
            log.debug("robots.txt disallows %s", url)
            return
        if result.fetched >= cfg.max_pages:
            result.skipped["max-pages"] += 1
            return
        result.fetched += 1
        await self._wait_turn()
        log.debug("GET %s", url)
        try:
            async with client.stream("GET", url) as resp:
                final = normalize_url(str(resp.url), strip_query=cfg.strip_query) or url
                if final != url:
                    if depth == 0 and url == self.start and not same_site(final, result.origin):
                        # The start URL redirected (http -> https, apex -> www): adopt the new origin.
                        result.origin = host_of(final)
                    if not same_site(final, result.origin):
                        result.skipped["offsite-redirect"] += 1
                        return
                    if final in self._seen and depth > 0:
                        result.skipped["duplicate"] += 1
                        return
                    self._seen.add(final)
                    final_robots = await self._robots_for(client, host_of(final))
                    if not final_robots.can_fetch(cfg.user_agent, final):
                        result.skipped["robots"] += 1
                        return
                if resp.status_code != 200:
                    result.skipped[f"http-{resp.status_code}"] += 1
                    return
                ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if ctype not in HTML_TYPES:
                    result.skipped["non-html"] += 1
                    return
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > cfg.max_page_bytes:
                        result.skipped["too-large"] += 1
                        return
                encoding = resp.charset_encoding or "utf-8"
                try:
                    html = body.decode(encoding, errors="replace")
                except LookupError:
                    html = body.decode("utf-8", errors="replace")
                header_directives: set[str] = set()
                for value in resp.headers.get_list("x-robots-tag"):
                    header_directives |= parse_robots_directives(value)
                lastmod = _parse_http_date(resp.headers.get("last-modified")) if cfg.lastmod else None
        except httpx.HTTPError as exc:
            result.errors.append((url, f"{type(exc).__name__}: {exc}"))
            result.skipped["error"] += 1
            log.warning("%s: %s", url, exc)
            return

        info = parse_html(html, user_agent_token=cfg.user_agent.split("/", 1)[0])
        base = normalize_url(info.base, final) if info.base else final
        base = base or final
        noindex = info.noindex or "noindex" in header_directives
        nofollow = info.nofollow or "nofollow" in header_directives

        canonical_elsewhere = False
        if info.canonical:
            canonical = normalize_url(info.canonical, base, strip_query=cfg.strip_query)
            if canonical and canonical != final:
                canonical_elsewhere = True
                # The canonical page is the one that belongs in the sitemap.
                self._enqueue(canonical, depth)

        alternates: list[tuple[str, str]] = []
        if cfg.hreflang:
            seen_langs: set[str] = set()
            for lang, href in info.alternates:
                alt = normalize_url(href, base, strip_query=cfg.strip_query)
                key = lang.lower()
                if alt is None or not HREFLANG_RE.match(lang) or key in seen_langs:
                    continue
                seen_langs.add(key)
                alternates.append((lang, alt))
                # Language versions are often only reachable through the alternates.
                self._enqueue(alt, depth + 1)
                if len(alternates) >= MAX_ALTERNATES_PER_PAGE:
                    break

        if not nofollow:
            hrefs = info.links + (info.nofollow_links if cfg.follow_nofollow else [])
            for href in hrefs:
                link = normalize_url(href, base, strip_query=cfg.strip_query)
                if link:
                    self._enqueue(link, depth + 1)

        if noindex:
            result.skipped["noindex"] += 1
            return
        if canonical_elsewhere:
            result.skipped["canonical"] += 1
            return
        images: list[str] = []
        if cfg.images:
            seen_images: set[str] = set()
            for src in info.images:
                img = normalize_url(src, base)
                if img and img not in seen_images:
                    seen_images.add(img)
                    images.append(img)
                    if len(images) >= MAX_IMAGES_PER_PAGE:
                        break
        result.pages.append(Page(url=final, depth=depth, lastmod=lastmod, images=images, alternates=alternates))

    async def _worker(self, client: httpx.AsyncClient) -> None:
        while True:
            url, depth = await self._queue.get()
            try:
                await self._process(client, url, depth)
            except Exception as exc:  # keep crawling; report the page
                self.result.errors.append((url, f"{type(exc).__name__}: {exc}"))
                self.result.skipped["error"] += 1
                log.exception("unexpected error on %s", url)
            finally:
                self._queue.task_done()

    async def run(self) -> CrawlResult:
        cfg = self.config
        limits = httpx.Limits(max_connections=cfg.concurrency, max_keepalive_connections=cfg.concurrency)
        async with httpx.AsyncClient(
            transport=self._transport,
            headers={"User-Agent": cfg.user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"},
            timeout=cfg.timeout,
            follow_redirects=True,
            max_redirects=cfg.max_redirects,
            limits=limits,
        ) as client:
            self._seen.add(self.start)
            self._queue.put_nowait((self.start, 0))
            workers = [asyncio.create_task(self._worker(client)) for _ in range(cfg.concurrency)]
            try:
                await self._queue.join()
            finally:
                for w in workers:
                    w.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
        return self.result


async def crawl(config: CrawlConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> CrawlResult:
    """Crawl a site and return the indexable pages."""
    return await Crawler(config, transport=transport).run()
