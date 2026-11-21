"""Command line interface: ``sitemap-gen https://example.com -o sitemap.xml``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx

from sitemap_gen._version import __version__
from sitemap_gen.crawler import DEFAULT_USER_AGENT, CrawlConfig, Crawler, CrawlResult
from sitemap_gen.writer import MAX_BYTES, MAX_URLS, SitemapEntry, plan_files, write_sitemaps


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _non_negative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def _non_negative_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sitemap-gen",
        description="Crawl a website politely and write sitemap.xml (with a sitemap index when needed).",
        epilog="Example: sitemap-gen https://example.com -o sitemap.xml --lastmod --images --gzip",
    )
    p.add_argument("url", help="start URL; only pages on the same scheme, host and port are crawled")
    p.add_argument("-o", "--output", default="sitemap.xml", help="output file, or - for stdout (default: %(default)s)")
    crawl = p.add_argument_group("crawling")
    crawl.add_argument(
        "--max-pages", type=_positive_int, default=10_000, help="pages to fetch at most (default: %(default)s)"
    )
    crawl.add_argument(
        "--max-depth", type=_non_negative_int, default=None, help="clicks from the start URL (default: no limit)"
    )
    crawl.add_argument(
        "-c", "--concurrency", type=_positive_int, default=4, help="parallel requests (default: %(default)s, max 64)"
    )
    crawl.add_argument(
        "--delay",
        type=_non_negative_float,
        default=0.0,
        help="minimum seconds between requests; a larger robots.txt Crawl-delay wins (default: %(default)s)",
    )
    crawl.add_argument(
        "--timeout", type=_non_negative_float, default=15.0, help="seconds per request (default: %(default)s)"
    )
    crawl.add_argument(
        "--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header; its first word is matched in robots.txt"
    )
    crawl.add_argument(
        "--include", action="append", default=[], metavar="REGEX", help="only crawl URLs matching this (repeatable)"
    )
    crawl.add_argument(
        "--exclude", action="append", default=[], metavar="REGEX", help="never crawl URLs matching this (repeatable)"
    )
    crawl.add_argument("--strip-query", action="store_true", help="drop ?query strings from URLs")
    crawl.add_argument("--follow-nofollow", action="store_true", help='also follow links marked rel="nofollow"')
    out = p.add_argument_group("output")
    out.add_argument("--lastmod", action="store_true", help="add <lastmod> from the Last-Modified response header")
    out.add_argument("--images", action="store_true", help="add <image:image> entries (image sitemap extension)")
    out.add_argument(
        "--hreflang",
        action="store_true",
        help='add <xhtml:link rel="alternate" hreflang> entries from each page\'s alternate links',
    )
    out.add_argument("--gzip", action="store_true", help="write .xml.gz files")
    out.add_argument(
        "--base-url",
        help="public URL of the directory the sitemap files are served from, used in the sitemap index "
        "(default: the site root)",
    )
    out.add_argument(
        "--max-urls-per-file",
        type=_positive_int,
        default=MAX_URLS,
        help=f"split into a sitemap index above this many URLs (default and maximum: {MAX_URLS})",
    )
    p.add_argument("-q", "--quiet", action="store_true", help="only print errors")
    p.add_argument("-v", "--verbose", action="store_true", help="log every request")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _summary(result: CrawlResult, written: Sequence[str]) -> str:
    lines = [f"Crawled {result.fetched} pages on {result.origin}; {len(result.pages)} URLs in the sitemap."]
    if result.crawl_delay:
        lines.append(f"Honoured robots.txt Crawl-delay: {result.crawl_delay:g}s.")
    if result.skipped:
        skipped = ", ".join(f"{k}={v}" for k, v in sorted(result.skipped.items()))
        lines.append(f"Skipped: {skipped}.")
    if written:
        lines.append("Wrote " + ", ".join(written) + ".")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.ERROR if args.quiet else logging.WARNING
    logging.basicConfig(level=level, format="sitemap-gen: %(message)s", stream=sys.stderr, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.max_urls_per_file > MAX_URLS:
        parser.error(f"--max-urls-per-file cannot be more than {MAX_URLS}")
    if args.output == "-" and args.gzip:
        parser.error("--gzip cannot write to stdout")
    if args.timeout <= 0:
        parser.error("--timeout must be more than 0")
    try:
        config = CrawlConfig(
            start_url=args.url,
            max_pages=args.max_pages,
            max_depth=args.max_depth,
            concurrency=args.concurrency,
            delay=args.delay,
            timeout=args.timeout,
            user_agent=args.user_agent,
            lastmod=args.lastmod,
            images=args.images,
            hreflang=args.hreflang,
            include=args.include,
            exclude=args.exclude,
            strip_query=args.strip_query,
            follow_nofollow=args.follow_nofollow,
        )
        crawler = Crawler(config, transport=transport)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        result = asyncio.run(crawler.run())
    except KeyboardInterrupt:
        print("sitemap-gen: interrupted", file=sys.stderr)
        return 130

    if not result.pages:
        print(_summary(result, []), file=sys.stderr)
        print("sitemap-gen: no indexable pages found; nothing written", file=sys.stderr)
        return 1

    entries = [SitemapEntry(p.url, p.lastmod, p.images, p.alternates) for p in result.sorted_pages()]
    base_url = args.base_url or result.origin + "/"
    now = datetime.now(UTC).replace(microsecond=0)
    if args.output == "-":
        files = plan_files(
            entries,
            Path("sitemap.xml"),
            base_url=base_url,
            images=args.images,
            hreflang=args.hreflang,
            max_urls=args.max_urls_per_file,
        )
        if len(files) > 1:
            print("sitemap-gen: too many URLs for one sitemap; use -o FILE to write an index", file=sys.stderr)
            return 1
        sys.stdout.buffer.write(files[0].content)
        sys.stdout.flush()
        written: list[str] = []
    else:
        paths = write_sitemaps(
            entries,
            args.output,
            base_url=base_url,
            gzip=args.gzip,
            images=args.images,
            hreflang=args.hreflang,
            max_urls=args.max_urls_per_file,
            max_bytes=MAX_BYTES,
            now=now,
        )
        written = [str(p) for p in paths]
    if not args.quiet:
        print(_summary(result, written), file=sys.stderr)
    return 0
