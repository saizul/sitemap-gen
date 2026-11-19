"""Use sitemap-gen as a library: crawl, inspect the result, write the files.

python examples/crawl.py https://example.com
"""

import asyncio
import sys

from sitemap_gen import CrawlConfig, SitemapEntry, crawl, write_sitemaps


async def main(url: str) -> None:
    result = await crawl(CrawlConfig(url, max_pages=500, concurrency=2, delay=0.5, lastmod=True))
    print(f"{len(result.pages)} indexable pages, skipped: {dict(result.skipped)}")
    entries = [SitemapEntry(p.url, p.lastmod) for p in result.sorted_pages()]
    for path in write_sitemaps(entries, "sitemap.xml", base_url=result.origin + "/"):
        print("wrote", path)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "https://example.com"))
