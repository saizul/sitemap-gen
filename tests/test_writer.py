import gzip
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sitemap_gen.writer import (
    IMAGE_NS,
    MAX_URLS,
    SITEMAP_NS,
    SitemapEntry,
    build_index,
    build_sitemaps,
    plan_files,
    w3c_datetime,
    write_sitemaps,
    xml_escape,
)

NS = {"s": SITEMAP_NS, "image": IMAGE_NS}


def locs(xml: bytes) -> list[str]:
    root = ET.fromstring(xml)
    return [e.text for e in root.findall("s:url/s:loc", NS)] or [e.text for e in root.findall("s:sitemap/s:loc", NS)]


def entries(n: int) -> list[SitemapEntry]:
    return [SitemapEntry(f"https://example.com/page/{i}") for i in range(n)]


def test_single_sitemap_is_valid_and_escaped():
    [doc] = build_sitemaps(
        [
            SitemapEntry("https://example.com/?a=1&b=<2>", lastmod=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            SitemapEntry("https://example.com/it's"),
        ]
    )
    assert doc.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="')
    assert b"&amp;b=&lt;2&gt;" in doc
    assert b"it&apos;s" in doc
    assert locs(doc) == ["https://example.com/?a=1&b=<2>", "https://example.com/it's"]
    root = ET.fromstring(doc)
    assert root.find("s:url/s:lastmod", NS).text == "2026-01-02T03:04:05+00:00"
    assert b"xmlns:image" not in doc


def test_image_sitemap():
    [doc] = build_sitemaps(
        [SitemapEntry("https://example.com/", images=["https://example.com/a.jpg", "https://cdn.example.net/b.png"])],
        images=True,
    )
    root = ET.fromstring(doc)
    assert [e.text for e in root.findall("s:url/image:image/image:loc", NS)] == [
        "https://example.com/a.jpg",
        "https://cdn.example.net/b.png",
    ]


def test_splits_by_url_count():
    docs = build_sitemaps(entries(5), max_urls=2)
    assert [len(locs(d)) for d in docs] == [2, 2, 1]
    assert [loc for d in docs for loc in locs(d)] == [e.loc for e in entries(5)]


def test_splits_at_the_protocol_limit_of_50000_urls():
    docs = build_sitemaps(entries(MAX_URLS + 1))
    assert [d.count(b"<url>") for d in docs] == [MAX_URLS, 1]


def test_splits_by_size_and_never_exceeds_it():
    docs = build_sitemaps(entries(100), max_bytes=2048)
    assert len(docs) > 1
    assert all(len(d) <= 2048 for d in docs)
    assert sum(len(locs(d)) for d in docs) == 100
    with pytest.raises(ValueError, match="single entry"):
        build_sitemaps([SitemapEntry("https://example.com/" + "a" * 3000)], max_bytes=2048)
    with pytest.raises(ValueError):
        build_sitemaps([], max_urls=MAX_URLS + 1)


def test_empty_input_gives_an_empty_urlset():
    [doc] = build_sitemaps([])
    assert locs(doc) == []


def test_index_and_file_plan(tmp_path):
    files = plan_files(entries(5), tmp_path / "sitemap.xml", base_url="https://example.com", max_urls=2)
    assert [f.name for f in files] == ["sitemap.xml", "sitemap-1.xml", "sitemap-2.xml", "sitemap-3.xml"]
    assert locs(files[0].content) == [
        "https://example.com/sitemap-1.xml",
        "https://example.com/sitemap-2.xml",
        "https://example.com/sitemap-3.xml",
    ]
    assert [f.urls for f in files[1:]] == [2, 2, 1]
    gz = plan_files(entries(3), tmp_path / "maps.xml", base_url="https://example.com/static/", gzip=True, max_urls=2)
    assert [f.name for f in gz] == ["maps.xml.gz", "maps-1.xml.gz", "maps-2.xml.gz"]
    assert locs(gz[0].content)[0] == "https://example.com/static/maps-1.xml.gz"


def test_write_plain_and_gzip(tmp_path):
    [path] = write_sitemaps(entries(3), tmp_path / "out" / "sitemap.xml", base_url="https://example.com/")
    assert path == tmp_path / "out" / "sitemap.xml"
    assert len(locs(path.read_bytes())) == 3

    now = datetime(2026, 11, 19, tzinfo=UTC)
    paths = write_sitemaps(
        entries(3), tmp_path / "sitemap.xml.gz", base_url="https://example.com/", gzip=True, max_urls=2, now=now
    )
    assert [p.name for p in paths] == ["sitemap.xml.gz", "sitemap-1.xml.gz", "sitemap-2.xml.gz"]
    index = gzip.decompress(paths[0].read_bytes())
    assert b"<lastmod>2026-11-19T00:00:00+00:00</lastmod>" in index
    assert len(locs(gzip.decompress(paths[1].read_bytes()))) == 2
    # gzip output is reproducible (no timestamp in the header).
    again = write_sitemaps(entries(3), tmp_path / "again.xml", base_url="https://example.com/", gzip=True)
    assert (
        again[0].read_bytes()
        == write_sitemaps(entries(3), tmp_path / "again2.xml", base_url="x", gzip=True)[0].read_bytes()
    )
    assert not list(tmp_path.glob("*.tmp"))


def test_helpers():
    assert xml_escape("a&b<c>'\"") == "a&amp;b&lt;c&gt;&apos;&quot;"
    assert w3c_datetime(datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=6)))) == "2026-01-01T06:00:00+00:00"
    assert w3c_datetime(datetime(2026, 1, 1)) == "2026-01-01T00:00:00+00:00"
    assert b"<sitemapindex" in build_index(["https://example.com/a.xml"])


XHTML = "{http://www.w3.org/1999/xhtml}link"


def test_hreflang_alternates():
    entry = SitemapEntry(
        "https://example.com/en/",
        alternates=[("en", "https://example.com/en/"), ("bn-BD", "https://example.com/bn/?a=1&b=2")],
    )
    [doc] = build_sitemaps([entry], hreflang=True)
    assert b'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in doc
    assert b'href="https://example.com/bn/?a=1&amp;b=2"' in doc
    root = ET.fromstring(doc)
    links = root.findall(f"s:url/{XHTML}", NS)
    assert [(e.get("rel"), e.get("hreflang"), e.get("href")) for e in links] == [
        ("alternate", "en", "https://example.com/en/"),
        ("alternate", "bn-BD", "https://example.com/bn/?a=1&b=2"),
    ]
    [plain] = build_sitemaps([entry])
    assert b"xhtml" not in plain


def test_hreflang_and_images_together(tmp_path):
    entry = SitemapEntry(
        "https://example.com/", images=["https://example.com/a.png"], alternates=[("en", "https://example.com/")]
    )
    [path] = write_sitemaps(
        [entry], tmp_path / "sitemap.xml", base_url="https://example.com/", images=True, hreflang=True
    )
    root = ET.parse(path).getroot()
    assert root.find(f"s:url/{XHTML}", NS).get("hreflang") == "en"
    assert root.find("s:url/image:image/image:loc", NS).text == "https://example.com/a.png"
