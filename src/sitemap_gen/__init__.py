"""Crawl a website politely and write sitemap.xml files."""

from sitemap_gen._version import __version__
from sitemap_gen.crawler import CrawlConfig, Crawler, CrawlResult, Page, crawl
from sitemap_gen.robots import RobotsTxt
from sitemap_gen.urls import normalize_url
from sitemap_gen.writer import SitemapEntry, SitemapFile, build_sitemaps, write_sitemaps

__all__ = [
    "CrawlConfig",
    "CrawlResult",
    "Crawler",
    "Page",
    "RobotsTxt",
    "SitemapEntry",
    "SitemapFile",
    "__version__",
    "build_sitemaps",
    "crawl",
    "normalize_url",
    "write_sitemaps",
]
