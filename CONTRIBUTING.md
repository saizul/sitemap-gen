# Contributing

Thanks for helping improve sitemap-gen. Bug reports, robots.txt edge cases,
new sitemap extensions and documentation fixes are all welcome. If you are
new to open source, start with one of the [good first issues](#good-first-issues)
below; each is small and points at the files involved.

## Reporting a bug

The most useful bug report is a page that is crawled wrongly: the URL (or
the HTML and response headers, if the site is private), the command you ran,
what the sitemap contained and what you expected. Run with `-v` to include the
request log. Please do not paste cookies or tokens.

## Development setup

You need Python 3.11 or newer.

```console
$ git clone https://github.com/saizul/sitemap-gen.git
$ cd sitemap-gen
$ python -m venv .venv && . .venv/bin/activate
$ pip install -e .[dev]
$ pytest                 # the test suite, no network needed
$ ruff check .           # lint
$ ruff format --check .  # formatting (ruff format . to fix)
```

Try it on the example site:

```console
$ (cd examples/site && python -m http.server 8765 --bind 127.0.0.1 &)
$ sitemap-gen http://127.0.0.1:8765/ -o - --images
```

Build the image:

```console
$ docker build -t sitemap-gen:dev .
$ docker run --rm sitemap-gen:dev --version
```

## Guidelines

- **No network in tests.** Tests crawl a fake site through
  `httpx.MockTransport`; see `tests/fakesite.py` and the existing tests in
  `tests/test_crawler.py`.
- **Politeness is not optional.** Changes must keep robots.txt, the
  concurrency limit, the delay and the same-host rule. Options that weaken
  them (such as ignoring robots.txt) will not be merged.
- **One runtime dependency.** httpx only; parsing uses the standard library.
- **Stable output.** Sitemaps are sorted and gzip output is reproducible; keep
  it that way so users can commit sitemaps and review diffs.
- Every change comes with a test and a line in the `Unreleased` section of
  `CHANGELOG.md`.

## Project layout

```text
src/sitemap_gen/
  crawler.py   CrawlConfig, Crawler: queue, politeness, fetching, decisions
  robots.py    RFC 9309 robots.txt parser
  parser.py    links, canonical, robots meta and images from HTML
  urls.py      URL normalisation and filters
  writer.py    sitemap, sitemap index, splitting and gzip
  cli.py       command-line interface
tests/         pytest suites; fakesite.py is the MockTransport site
examples/      a static example site, a library example, a CI workflow
```

## Good first issues

1. **Retry 429 and 503 once**: in `Crawler._process` in `crawler.py`, wait for
   `Retry-After` (seconds, capped at 60) and retry once. Test it with a
   handler in `tests/test_crawler.py` that fails the first time.
2. **`--report report.json`**: write `result.skipped` and the skipped URLs
   with their reason. Record URLs per reason in `CrawlResult` and add the flag
   in `cli.py`.
3. **`hreflang` alternates**: collect `<link rel="alternate" hreflang>` in
   `parser.py` and write `<xhtml:link>` entries in `writer.py` behind
   `--hreflang`.
4. **`--seed-urls FILE`**: start from a list of URLs (one per line) in
   addition to the start URL. Enqueue them in `Crawler.run`.
5. **Skip more file types**: add missing extensions to `SKIP_EXTENSIONS` in
   `urls.py` with a test in `tests/test_urls.py`.
6. **Respect `<meta http-equiv="refresh">`**: treat an immediate refresh to
   another URL like a redirect in `parser.py` and `crawler.py`.
7. **Progress output**: print `fetched N pages` to stderr every 100 pages
   when stderr is a terminal, in `crawler.py` or `cli.py`.
8. **Video sitemap entries**: collect `<video src>` in `parser.py` and write
   `<video:video>` entries with `--videos`.

## Pull requests

Keep them focused: one fix or feature per pull request. Describe what changed
and how you tested it; the template has a short checklist. CI runs ruff, the
tests on Python 3.11, 3.12 and 3.13, a crawl of `examples/site`, and a Docker
build that crawls the example site served by nginx.
