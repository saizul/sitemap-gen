# sitemap-gen

[![CI](https://github.com/saizul/sitemap-gen/actions/workflows/ci.yml/badge.svg)](https://github.com/saizul/sitemap-gen/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/saizul/sitemap-gen)](https://github.com/saizul/sitemap-gen/releases)
[![Container image](https://img.shields.io/badge/ghcr.io-saizul%2Fsitemap--gen-blue?logo=docker)](https://github.com/saizul/sitemap-gen/pkgs/container/sitemap-gen)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Crawl your website politely and get a correct `sitemap.xml` in one command.

```console
$ docker run --rm ghcr.io/saizul/sitemap-gen https://example.com -o - > sitemap.xml
```

Most sitemap generators either need a CMS plugin or crawl like a bot from
2005: they ignore robots.txt, hammer the server, and list redirects,
duplicates and `noindex` pages that search engines then report as errors.
sitemap-gen only lists the pages you actually want indexed:

- **Polite**: respects robots.txt (RFC 9309, with `*` and `$` wildcards and
  longest-match rules) and its `Crawl-delay`, limits concurrency, and only
  follows links on the same scheme, host and port.
- **Clean output**: only `200 OK` HTML pages. Redirects are followed and
  replaced by their target; `noindex` pages (meta tag or `X-Robots-Tag`
  header) and pages whose `rel=canonical` points elsewhere are left out, and
  the canonical URL is crawled instead.
- **Protocol limits handled**: splits into numbered sitemaps plus a sitemap
  index at 50,000 URLs or 50 MB, writes `.xml.gz` with `--gzip`.
- **Extras**: `<lastmod>` from the `Last-Modified` header, image sitemap
  entries (`<image:image>`) for every `<img>` on a page, and `hreflang`
  alternates (`<xhtml:link>`) for multilingual sites.
- **Small**: async Python on [httpx](https://www.python-httpx.org/) and the
  standard library HTML parser. One dependency, no browser.

## Contents

- [Quick start](#quick-start)
- [Usage](#usage)
- [What ends up in the sitemap](#what-ends-up-in-the-sitemap)
- [Output files](#output-files)
- [Library use](#library-use)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

## Quick start

With Docker (images for `linux/amd64` and `linux/arm64`):

```console
$ docker run --rm ghcr.io/saizul/sitemap-gen https://example.com -o - > sitemap.xml
$ docker run --rm -v "$PWD:/out" -u "$(id -u)" ghcr.io/saizul/sitemap-gen \
    https://example.com -o sitemap.xml --lastmod --images --gzip
```

The image works in `/out`, so mount the directory you want the files in
there; `-u "$(id -u)"` makes the files belong to you.

With Python 3.11 or newer:

```console
$ pipx install git+https://github.com/saizul/sitemap-gen.git
$ sitemap-gen https://example.com -o sitemap.xml
Crawled 7 pages on https://example.com; 5 URLs in the sitemap.
Skipped: canonical=1, extension=1, noindex=1, robots=1.
Wrote sitemap.xml.
```

The summary goes to stderr, so `-o -` gives you clean XML on stdout.

## Usage

```text
sitemap-gen URL [-o FILE] [options]
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-o, --output FILE` | `sitemap.xml` | Output file, or `-` for stdout. With an index, this is the index file. |
| `--max-pages N` | 10000 | Stop after fetching N pages. |
| `--max-depth N` | no limit | Follow links at most N clicks from the start URL (`0` = only the start page). |
| `-c, --concurrency N` | 4 | Parallel requests (1 to 64). |
| `--delay SECONDS` | 0 | Minimum time between two requests. A larger robots.txt `Crawl-delay` wins (capped at 60 s). |
| `--timeout SECONDS` | 15 | Per request. |
| `--user-agent TEXT` | `sitemap-gen/0.1.0 (+https://github.com/saizul/sitemap-gen)` | Its first word (`sitemap-gen`) is the token matched against robots.txt groups. |
| `--include REGEX` | | Only crawl URLs matching this. Repeatable. |
| `--exclude REGEX` | | Never crawl URLs matching this. Repeatable. |
| `--strip-query` | off | Drop `?query` strings (tracking parameters, sort orders). |
| `--follow-nofollow` | off | Also follow `rel="nofollow"` links. |
| `--lastmod` | off | Add `<lastmod>` from each page's `Last-Modified` header. |
| `--images` | off | Add `<image:image>` entries for the page's `<img src>` (up to 1,000 per page). |
| `--hreflang` | off | Add `<xhtml:link rel="alternate" hreflang>` entries from each page's `<link rel="alternate" hreflang>` tags (up to 500 per page), and crawl the same-site language versions they point to. |
| `--gzip` | off | Write `.xml.gz` files. |
| `--base-url URL` | site root | Where the sitemap files will be served, for the `<loc>` entries of a sitemap index. |
| `--max-urls-per-file N` | 50000 | Split into an index sooner than the protocol limit. |
| `-q`, `-v` | | Only errors / log every request. |

Exit codes: `0` sitemap written, `1` no indexable page found (nothing is
written), `2` usage error.

Examples:

```console
# A big site, gently: two requests at a time, at most one per second
$ sitemap-gen https://example.com -c 2 --delay 1 --gzip -o public/sitemap.xml

# Only the blog, without tag pages and tracking parameters
$ sitemap-gen https://example.com/blog/ --include '/blog/' --exclude '/tag/' --strip-query

# Image sitemap with last-modified dates, written to stdout
$ sitemap-gen https://example.com --images --lastmod -o - > sitemap.xml

# A multilingual site: list every language version of each page
$ sitemap-gen https://example.com --hreflang -o sitemap.xml
```

A nightly GitHub Actions workflow that commits the result is in
[`examples/github-workflow.yml`](examples/github-workflow.yml).

## What ends up in the sitemap

Every URL is normalised first: lower-case scheme and host, no default port,
no `#fragment`, `.` and `..` resolved, percent-encoding normalised (and with
`--strip-query`, no query string).

| Situation | Fetched? | In the sitemap? | Shown as |
| --- | --- | --- | --- |
| `200` HTML page | yes | yes | |
| Disallowed by robots.txt | no | no | `robots` |
| Link to another host, scheme or port | no | no | (not counted) |
| Link ending in `.pdf`, `.jpg`, `.zip`, `.css`, ... | no | no | `extension` |
| Matches `--exclude` / misses `--include` | no | no | `excluded` |
| Deeper than `--max-depth` | no | no | `max-depth` |
| Beyond `--max-pages` | no | no | `max-pages` |
| Redirect | yes | the target, if it is on the same site | `offsite-redirect` otherwise |
| Not HTML (`Content-Type`) | yes | no | `non-html` |
| `404`, `500`, ... | yes | no | `http-404`, ... |
| `<meta name="robots" content="noindex">` or `X-Robots-Tag: noindex` | yes | no, but its links are followed | `noindex` |
| `nofollow` (meta or header) | yes | yes, but its links are not followed | |
| `rel="canonical"` to another URL | yes | no; the canonical URL is crawled instead | `canonical` |
| Larger than 5 MB, timeout, connection error | yes | no | `too-large`, `error` |

Robots meta tags named `robots` or `sitemap-gen` count; tags for other bots
(`googlebot`, ...) do not. If robots.txt is missing (`4xx`) everything may be
crawled; if it returns `5xx` or cannot be fetched, nothing is crawled, as RFC
9309 requires. URLs are listed by depth, then alphabetically, so the output
only changes when the site does.

## Output files

Up to 50,000 URLs and 50 MB (uncompressed), you get one file:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc>https://example.com/blog/hello.html</loc>
    <lastmod>2026-11-19T04:28:10+00:00</lastmod>
    <image:image>
      <image:loc>https://example.com/images/hello.jpg</image:loc>
    </image:image>
  </url>
</urlset>
```

With `--hreflang`, each `<url>` also lists the language versions the page
declares, as [Google documents](https://developers.google.com/search/docs/specialty/international/localized-versions#sitemap):

```xml
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>https://example.com/en/</loc>
    <xhtml:link rel="alternate" hreflang="en" href="https://example.com/en/"/>
    <xhtml:link rel="alternate" hreflang="bn" href="https://example.com/bn/"/>
    <xhtml:link rel="alternate" hreflang="x-default" href="https://example.com/"/>
  </url>
</urlset>
```

Alternates are written as the page declares them (resolved to absolute URLs,
other domains included). Values that are not a language tag or `x-default`
and repeated languages are dropped. Alternates on the same site are crawled
too, so language versions that are only linked through `hreflang` still end
up in the sitemap.

Above either limit, `-o sitemap.xml` becomes a sitemap index and the URLs go
into `sitemap-1.xml`, `sitemap-2.xml`, ... next to it. The index points to
`<base-url>/sitemap-1.xml`, so upload all files to the same directory (the
site root by default) and submit only the index. With `--gzip` every file is
compressed (`sitemap.xml.gz`, `sitemap-1.xml.gz`, ...); gzip output is
byte-for-byte reproducible.

## Library use

```python
import asyncio

from sitemap_gen import CrawlConfig, SitemapEntry, crawl, write_sitemaps

result = asyncio.run(crawl(CrawlConfig("https://example.com", concurrency=2, lastmod=True)))
print(len(result.pages), dict(result.skipped))
entries = [SitemapEntry(p.url, p.lastmod, p.images, p.alternates) for p in result.sorted_pages()]
write_sitemaps(entries, "sitemap.xml", base_url=result.origin + "/")
```

`crawl()` accepts an httpx transport (`crawl(config, transport=...)`), which
is how the test suite crawls a fake site with `httpx.MockTransport`. The
robots.txt parser is usable on its own:

```python
from sitemap_gen import RobotsTxt

robots = RobotsTxt.parse(open("robots.txt").read())
robots.can_fetch("mybot/1.0", "https://example.com/private/page")
```

## FAQ

**Does it run JavaScript?** No. It reads the HTML your server sends. If your
links only appear after JavaScript runs, search engines have the same
problem; render on the server or generate the sitemap from your CMS.

**Can I crawl sites I do not own?** Technically yes, it obeys robots.txt.
But a sitemap is for your own site; please only crawl other people's sites
with permission, and keep `--concurrency` low and `--delay` up.

**Why is a page missing?** Run with `-v` to see every request and the
summary line for the reason: most often a `noindex` tag, a canonical URL that
points to another page, or a robots.txt rule.

**Why are `changefreq` and `priority` not supported?** Google and Bing
ignore them. `lastmod` is the only optional field they use, and only when it
is accurate, so it is opt-in and comes from your server's `Last-Modified`.

**`www.example.com` and `example.com`?** They are different hosts. Start
from the one you use; if the start URL redirects (`http` to `https`, apex to
`www`), the crawl follows and stays on the new host.

**Is it fast?** It is deliberately not aggressive. With the defaults (4
parallel requests, no delay) a typical server answers a few hundred pages a
minute; raise `--concurrency` on your own infrastructure.

## Roadmap

Ideas, several are good first issues (see [CONTRIBUTING.md](CONTRIBUTING.md)):

- [ ] Retry `429` and `503` responses once, honouring `Retry-After`
- [ ] Seed the crawl from an existing sitemap or a URL list (`--seed-urls`)
- [ ] A JSON report of skipped URLs and reasons (`--report report.json`)
- [ ] Video sitemap entries for `<video>` and YouTube embeds
- [ ] `--same-domain` to include subdomains

## Contributing

Bug reports with a reproducible page (HTML and headers) are the most useful
contribution. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the setup, the check
commands and beginner-friendly issues. By taking part you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md). Security problems: see
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © Saizul Amin
