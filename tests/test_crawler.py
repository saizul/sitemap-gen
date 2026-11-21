import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from fakesite import FakeSite, Resource, html
from sitemap_gen.crawler import CrawlConfig, Crawler, crawl

ROOT = "https://example.com"


def run(config: CrawlConfig, site: FakeSite, **kwargs):
    return asyncio.run(Crawler(config, transport=site.transport, **kwargs).run())


def urls(result):
    return [p.url for p in result.sorted_pages()]


def build_site(site: FakeSite) -> FakeSite:
    site.add(
        f"{ROOT}/robots.txt", Resource("User-agent: *\nDisallow: /private\n", headers={"content-type": "text/plain"})
    )
    site.add(
        f"{ROOT}/",
        html(
            """
            <a href="/about">About</a>
            <a href="/blog/">Blog</a>
            <a href="https://other.example/">External</a>
            <a href="mailto:hello@example.com">Mail</a>
            <a href="/files/brochure.pdf">PDF</a>
            <a href="/private/area">Private</a>
            <a href="/old">Old</a>
            <a href="/noindex">Noindex</a>
            <a href="/dup">Duplicate</a>
            <a href="/api/data">API</a>
            <a href="/missing">Missing</a>
            <a href="/sponsored" rel="nofollow">Sponsored</a>
            <a href="/about#team">About again</a>
            """
        ),
    )
    site.add(f"{ROOT}/about", html('<a href="/">Home</a>'))
    site.add(f"{ROOT}/blog/", html('<a href="post-1">Post 1</a> <a href="./post-2?ref=list">Post 2</a>'))
    site.add(f"{ROOT}/blog/post-1", html("<p>one</p>"))
    site.add(f"{ROOT}/blog/post-2?ref=list", html("<p>two</p>"))
    site.redirect(f"{ROOT}/old", f"{ROOT}/new")
    site.add(f"{ROOT}/new", html("<p>new</p>"))
    site.add(f"{ROOT}/noindex", html('<a href="/hidden-gem">gem</a>', '<meta name="robots" content="noindex">'))
    site.add(f"{ROOT}/hidden-gem", html("<p>found through a noindex page</p>"))
    site.add(f"{ROOT}/dup", html("<p>dup</p>", f'<link rel="canonical" href="{ROOT}/about">'))
    site.add(f"{ROOT}/api/data", Resource('{"a": 1}', headers={"content-type": "application/json"}))
    site.add(f"{ROOT}/sponsored", html("<p>should not be crawled</p>"))
    site.add(f"{ROOT}/private/area", html("<p>secret</p>"))
    return site


def test_full_crawl(site):
    build_site(site)
    result = run(CrawlConfig(f"{ROOT}/"), site)
    assert urls(result) == [
        f"{ROOT}/",
        f"{ROOT}/about",
        f"{ROOT}/blog/",
        f"{ROOT}/new",
        f"{ROOT}/blog/post-1",
        f"{ROOT}/blog/post-2?ref=list",
        f"{ROOT}/hidden-gem",
    ]
    assert result.skipped["robots"] == 1
    assert result.skipped["noindex"] == 1
    assert result.skipped["canonical"] == 1
    assert result.skipped["non-html"] == 1
    assert result.skipped["http-404"] == 1
    assert result.skipped["extension"] == 1
    requested = site.paths()
    for never in ("/private/area", "/files/brochure.pdf", "/sponsored"):
        assert never not in requested
    assert all(r.url.host == "example.com" for r in site.requests)
    assert requested.count("/about") == 1
    assert requested.count("/robots.txt") == 1
    assert all(r.headers["user-agent"].startswith("sitemap-gen/") for r in site.requests)


def test_follow_nofollow_option(site):
    build_site(site)
    result = run(CrawlConfig(f"{ROOT}/", follow_nofollow=True), site)
    assert f"{ROOT}/sponsored" in urls(result)


def test_meta_and_header_nofollow_and_noindex(site):
    site.add(f"{ROOT}/", html('<a href="/a">a</a>', '<meta name="robots" content="nofollow">'))
    site.add(f"{ROOT}/a", html("a"))
    result = run(CrawlConfig(f"{ROOT}/"), site)
    assert urls(result) == [f"{ROOT}/"]
    assert "/a" not in site.paths()

    site2 = FakeSite()
    page = html('<a href="/b">b</a>')
    page.headers["x-robots-tag"] = "noindex"
    site2.add(f"{ROOT}/", page).add(f"{ROOT}/b", html("b"))
    result = run(CrawlConfig(f"{ROOT}/"), site2)
    assert urls(result) == [f"{ROOT}/b"]


def test_max_depth_and_max_pages(site):
    site.add(f"{ROOT}/", html('<a href="/1">1</a>'))
    for i in range(1, 6):
        site.add(f"{ROOT}/{i}", html(f'<a href="/{i + 1}">next</a>'))
    result = run(CrawlConfig(f"{ROOT}/", max_depth=2), site)
    assert urls(result) == [f"{ROOT}/", f"{ROOT}/1", f"{ROOT}/2"]
    assert result.skipped["max-depth"] == 1
    result = run(CrawlConfig(f"{ROOT}/", max_pages=4), site)
    assert len(result.pages) == 4
    assert result.fetched == 4
    result = run(CrawlConfig(f"{ROOT}/", max_depth=0), site)
    assert urls(result) == [f"{ROOT}/"]


def test_include_exclude_and_strip_query(site):
    site.add(
        f"{ROOT}/",
        html('<a href="/blog/a?utm_source=x">a</a><a href="/shop/b">b</a><a href="/blog/tag/x">t</a>'),
    )
    site.add(f"{ROOT}/blog/a", html("a"))
    site.add(f"{ROOT}/blog/a?utm_source=x", html("a with query"))
    site.add(f"{ROOT}/shop/b", html("b"))
    site.add(f"{ROOT}/blog/tag/x", html("t"))
    result = run(CrawlConfig(f"{ROOT}/", include=[r"/blog/"], exclude=[r"/tag/"], strip_query=True), site)
    assert urls(result) == [f"{ROOT}/", f"{ROOT}/blog/a"]
    assert result.skipped["excluded"] == 2


def test_robots_unavailable_allows_and_unreachable_disallows(site):
    site.add(f"{ROOT}/", html('<a href="/a">a</a>')).add(f"{ROOT}/a", html("a"))
    assert len(run(CrawlConfig(f"{ROOT}/"), site).pages) == 2  # robots.txt is a 404

    site.add(f"{ROOT}/robots.txt", Resource("down", 503))
    result = run(CrawlConfig(f"{ROOT}/"), site)
    assert result.pages == []
    assert result.skipped["robots"] == 1

    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    site.add(f"{ROOT}/robots.txt", boom)
    assert run(CrawlConfig(f"{ROOT}/"), site).pages == []


def test_crawl_delay_is_honoured(site):
    site.add(f"{ROOT}/robots.txt", Resource("User-agent: *\nCrawl-delay: 5\n"))
    site.add(f"{ROOT}/", html('<a href="/a">a</a><a href="/b">b</a>'))
    site.add(f"{ROOT}/a", html("a")).add(f"{ROOT}/b", html("b"))
    now = [1000.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    result = run(CrawlConfig(f"{ROOT}/", concurrency=4, delay=1), site, sleep=fake_sleep, clock=lambda: now[0])
    assert len(result.pages) == 3
    assert result.crawl_delay == 5
    assert sleeps == [5, 5]


def test_concurrency_limit():
    in_flight = 0
    peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        if request.url.path == "/":
            links = "".join(f'<a href="/p{i}">p</a>' for i in range(20))
            return httpx.Response(200, headers={"content-type": "text/html"}, text=links)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="leaf")

    result = asyncio.run(crawl(CrawlConfig(f"{ROOT}/", concurrency=3), transport=httpx.MockTransport(handler)))
    assert len(result.pages) == 21
    assert 1 < peak <= 3


def test_lastmod_and_images(site):
    page = html(
        '<img src="/img/a.jpg"><img src="https://cdn.example.net/b.png"><img src="/img/a.jpg"><a href="/x">x</a>'
    )
    page.headers["last-modified"] = "Wed, 21 Oct 2025 07:28:00 GMT"
    site.add(f"{ROOT}/", page).add(f"{ROOT}/x", html("x"))
    site.add(f"{ROOT}/x", Resource("<p>x</p>", headers={"content-type": "text/html", "last-modified": "garbage"}))
    result = run(CrawlConfig(f"{ROOT}/", lastmod=True, images=True), site)
    home, x = result.sorted_pages()
    assert home.lastmod == datetime(2025, 10, 21, 7, 28, tzinfo=UTC)
    assert home.images == [f"{ROOT}/img/a.jpg", "https://cdn.example.net/b.png"]
    assert x.lastmod is None
    assert run(CrawlConfig(f"{ROOT}/"), site).sorted_pages()[0].lastmod is None


def test_start_redirect_adopts_new_origin(site):
    site.redirect("http://example.com/", f"{ROOT}/")
    site.add(f"{ROOT}/", html('<a href="/a">a</a><a href="http://example.com/b">old scheme</a>'))
    site.add(f"{ROOT}/a", html("a"))
    result = run(CrawlConfig("http://example.com"), site)
    assert result.origin == ROOT
    assert urls(result) == [f"{ROOT}/", f"{ROOT}/a"]


def test_offsite_redirects_canonical_and_base(site):
    site.add(
        f"{ROOT}/",
        html('<a href="/go">go</a><a href="/elsewhere">x</a><a href="rel">rel</a>', '<base href="/docs/">'),
    )
    site.redirect(f"{ROOT}/go", "https://other.example/landing")
    site.add(f"{ROOT}/elsewhere", html("x", '<link rel="canonical" href="https://other.example/x">'))
    site.add(f"{ROOT}/docs/rel", html("resolved against base"))
    result = run(CrawlConfig(f"{ROOT}/"), site)
    assert urls(result) == [f"{ROOT}/", f"{ROOT}/docs/rel"]
    assert result.skipped["offsite-redirect"] == 1
    assert result.skipped["canonical"] == 1


def test_errors_large_pages_and_charsets(site):
    def broken(request):
        raise httpx.ReadTimeout("slow", request=request)

    site.add(f"{ROOT}/", html('<a href="/slow">s</a><a href="/big">b</a><a href="/latin">l</a>'))
    site.add(f"{ROOT}/slow", broken)
    site.add(f"{ROOT}/big", Resource("x" * 5000, headers={"content-type": "text/html"}))
    site.add(
        f"{ROOT}/latin",
        Resource('<a href="/caf\xe9">c</a>'.encode("latin-1"), headers={"content-type": "text/html; charset=latin-1"}),
    )
    site.add(f"{ROOT}/caf%C3%A9", html("cafe"))
    cfg = CrawlConfig(f"{ROOT}/", max_page_bytes=1000)
    result = run(cfg, site)
    assert urls(result) == [f"{ROOT}/", f"{ROOT}/latin", f"{ROOT}/caf%C3%A9"]
    assert result.skipped["error"] == 1
    assert result.skipped["too-large"] == 1
    assert result.errors[0][0] == f"{ROOT}/slow"


@pytest.mark.parametrize(
    "kwargs",
    [{"max_pages": 0}, {"max_depth": -1}, {"concurrency": 0}, {"concurrency": 100}, {"delay": -1}, {"include": ["("]}],
)
def test_config_validation(kwargs):
    with pytest.raises(ValueError):
        CrawlConfig(f"{ROOT}/", **kwargs)


def test_rejects_non_http_start():
    with pytest.raises(ValueError):
        Crawler(CrawlConfig("ftp://example.com/"))


def test_hreflang_alternates_are_collected_and_crawled(site):
    head = (
        '<link rel="alternate" hreflang="en" href="/">'
        '<link rel="alternate" hreflang="bn" href="/bn/">'
        '<link rel="alternate" hreflang="EN" href="/duplicate-language">'
        '<link rel="alternate" hreflang="not a tag" href="/bad">'
        '<link rel="alternate" hreflang="fr" href="https://example.fr/">'
        '<link rel="alternate" hreflang="x-default" href="/">'
    )
    site.add(f"{ROOT}/", html("<p>home</p>", head))
    site.add(f"{ROOT}/bn/", html("<p>bangla</p>", head))
    result = run(CrawlConfig(f"{ROOT}/", hreflang=True), site)
    assert urls(result) == [f"{ROOT}/", f"{ROOT}/bn/"]
    expected = [("en", f"{ROOT}/"), ("bn", f"{ROOT}/bn/"), ("fr", "https://example.fr/"), ("x-default", f"{ROOT}/")]
    assert [p.alternates for p in result.sorted_pages()] == [expected, expected]
    assert "/bad" not in site.paths() and "/duplicate-language" not in site.paths()


def test_hreflang_is_off_by_default(site):
    site.add(f"{ROOT}/", html("<p>home</p>", '<link rel="alternate" hreflang="bn" href="/bn/">'))
    site.add(f"{ROOT}/bn/", html("<p>bangla</p>"))
    result = run(CrawlConfig(f"{ROOT}/"), site)
    assert urls(result) == [f"{ROOT}/"]
    assert result.pages[0].alternates == []
