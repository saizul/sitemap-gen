import pytest

from sitemap_gen.urls import has_skipped_extension, normalize_url, same_site


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTP://Example.COM:80/a/./b/../c?x=1#frag", "http://example.com/a/c?x=1"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com:443/", "https://example.com/"),
        ("https://example.com:8443/%7euser/a%2fb", "https://example.com:8443/~user/a%2Fb"),
        ("https://example.com/café menu", "https://example.com/caf%C3%A9%20menu"),
        ("https://example.com/100%", "https://example.com/100%25"),
        ("https://example.com/a/../../b", "https://example.com/b"),
        ("https://example.com/dir/", "https://example.com/dir/"),
        ("https://example.com/?q=a b&x=%41", "https://example.com/?q=a%20b&x=A"),
        ("https://Bücher.example/", "https://xn--bcher-kva.example/"),
    ],
)
def test_normalize(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/x/../y", "https://example.com/y"),
        ("other", "https://example.com/dir/other"),
        ("../up", "https://example.com/up"),
        ("//example.com/proto-relative", "https://example.com/proto-relative"),
        ("?page=2", "https://example.com/dir/page?page=2"),
        ("#top", "https://example.com/dir/page"),
        ("mailto:a@example.com", None),
        ("tel:+8801712345678", None),
        ("javascript:void(0)", None),
        ("ftp://example.com/file", None),
        ("http://[::1", None),
        ("", None),
    ],
)
def test_resolve_relative(href, expected):
    assert normalize_url(href, "https://example.com/dir/page") == expected


def test_strip_query():
    assert normalize_url("https://example.com/a?utm_source=x", strip_query=True) == "https://example.com/a"


def test_same_site_and_extensions():
    assert same_site("https://example.com/a", "https://example.com/")
    assert not same_site("https://www.example.com/a", "https://example.com/")
    assert not same_site("http://example.com/a", "https://example.com/")
    assert not same_site("https://example.com:8443/a", "https://example.com/")
    assert has_skipped_extension("https://example.com/files/report.PDF")
    assert has_skipped_extension("https://example.com/logo.png?v=2")
    assert not has_skipped_extension("https://example.com/blog/post.html")
    assert not has_skipped_extension("https://example.com/v1.2/")
    assert not has_skipped_extension("https://example.com/about")
