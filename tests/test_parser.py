from sitemap_gen.parser import parse_html, parse_robots_directives


def test_extracts_links_canonical_base_and_images():
    info = parse_html(
        """<html><head>
        <base href="/root/">
        <link rel="Canonical" href="https://example.com/a">
        <link rel="stylesheet" href="/style.css">
        <meta name="description" content="noindex is not a robots tag here">
        </head><body>
        <a href="/one">One</a> <a href='two'>Two</a> <a>no href</a>
        <a href="/secret" rel="nofollow noopener">Hidden</a>
        <map><area href="/map-area"></map>
        <img src="/img/a.jpg" alt="A"><img src="data:image/png;base64,xx"><img src="  ">
        </body></html>"""
    )
    assert info.links == ["/one", "two", "/map-area"]
    assert info.nofollow_links == ["/secret"]
    assert info.canonical == "https://example.com/a"
    assert info.base == "/root/"
    assert info.images == ["/img/a.jpg"]
    assert not info.noindex
    assert not info.nofollow


def test_robots_meta():
    info = parse_html('<meta name="ROBOTS" content="NoIndex, follow">')
    assert info.noindex
    assert not info.nofollow
    info = parse_html('<meta name="robots" content="none">')
    assert info.noindex and info.nofollow
    info = parse_html('<meta name="sitemap-gen" content="nofollow">', user_agent_token="sitemap-gen")
    assert info.nofollow and not info.noindex
    info = parse_html('<meta name="otherbot" content="noindex">')
    assert not info.noindex


def test_directive_parsing():
    assert parse_robots_directives("noindex, NOFOLLOW") == {"noindex", "nofollow"}
    assert parse_robots_directives("none") == {"noindex", "nofollow"}
    assert parse_robots_directives("otherbot: noindex") == set()
    assert parse_robots_directives("") == set()


def test_broken_html_does_not_crash():
    info = parse_html("<a href='/ok'>ok<a href=/unquoted>x</a><div <<<>")
    assert "/ok" in info.links
    assert "/unquoted" in info.links


def test_extracts_hreflang_alternates():
    info = parse_html(
        """
        <link rel="alternate" hreflang="en" href="/en/">
        <link rel="Alternate" hreflang="bn-BD" href="https://example.com/bn/">
        <link rel="alternate" hreflang="x-default" href="/" />
        <link rel="alternate" type="application/rss+xml" href="/feed.xml">
        <link rel="alternate" hreflang="de" href="">
        """
    )
    assert info.alternates == [("en", "/en/"), ("bn-BD", "https://example.com/bn/"), ("x-default", "/")]
