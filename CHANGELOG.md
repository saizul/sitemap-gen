# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `--hreflang` (`CrawlConfig(hreflang=True)`): collect each page's
  `<link rel="alternate" hreflang>` tags and write them as
  `<xhtml:link rel="alternate">` entries, as Google documents for
  multilingual sites. Same-site alternates are crawled as well. Invalid
  language tags and repeated languages are dropped; at most 500 per page.
- `SitemapEntry.alternates`, `Page.alternates` and a `hreflang` argument for
  `build_sitemaps()`, `plan_files()` and `write_sitemaps()`.

## [0.1.0] - 2026-11-19

### Added

- Asynchronous same-host crawler on httpx with a concurrency limit, a minimum
  delay between requests, `--max-pages`, `--max-depth`, `--include` and
  `--exclude`.
- robots.txt support following RFC 9309 (wildcards, longest match, merged
  groups, 4xx/5xx handling) and `Crawl-delay`.
- `noindex` and `nofollow` from robots meta tags and the `X-Robots-Tag`
  header, `rel="canonical"` handling, `rel="nofollow"` links, `<base href>`.
- Skips non-HTML responses and links to common file types without fetching
  them.
- Sitemap writer with automatic sitemap index at 50,000 URLs or 50 MB,
  `<lastmod>` from `Last-Modified`, image sitemap entries and reproducible
  gzip output.
- `sitemap-gen` CLI and a Docker image for `linux/amd64` and `linux/arm64`.

[Unreleased]: https://github.com/saizul/sitemap-gen/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/saizul/sitemap-gen/releases/tag/v0.1.0
