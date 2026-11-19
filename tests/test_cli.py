import gzip
import xml.etree.ElementTree as ET

import pytest

from fakesite import FakeSite, Resource, html
from sitemap_gen import __version__
from sitemap_gen.cli import main

ROOT = "https://example.com"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@pytest.fixture
def small_site() -> FakeSite:
    site = FakeSite()
    site.add(f"{ROOT}/robots.txt", Resource("User-agent: *\nDisallow: /admin\n"))
    links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(5))
    site.add(f"{ROOT}/", html(links + '<a href="/admin">admin</a><img src="/logo.png">'))
    for i in range(5):
        page = html(f"page {i}")
        page.headers["last-modified"] = "Tue, 01 Sep 2026 10:00:00 GMT"
        site.add(f"{ROOT}/p{i}", page)
    return site


def locs(path):
    root = ET.parse(path).getroot()
    return [e.text for e in root.iter(f"{{{NS['s']}}}loc")]


def test_writes_sitemap(tmp_path, small_site, capsys):
    out = tmp_path / "sitemap.xml"
    assert main([ROOT, "-o", str(out)], transport=small_site.transport) == 0
    assert locs(out) == [f"{ROOT}/"] + [f"{ROOT}/p{i}" for i in range(5)]
    err = capsys.readouterr().err
    assert "Crawled 6 pages on https://example.com; 6 URLs in the sitemap." in err
    assert "robots=1" in err
    assert f"Wrote {out}" in err


def test_index_split_lastmod_images_gzip(tmp_path, small_site):
    out = tmp_path / "sitemap.xml"
    args = [ROOT, "-o", str(out), "--max-urls-per-file", "4", "--lastmod", "--images", "--gzip"]
    assert main([*args, "--base-url", "https://example.com/maps/", "-q"], transport=small_site.transport) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["sitemap-1.xml.gz", "sitemap-2.xml.gz", "sitemap.xml.gz"]
    index = gzip.decompress((tmp_path / "sitemap.xml.gz").read_bytes()).decode()
    assert "https://example.com/maps/sitemap-1.xml.gz" in index
    first = gzip.decompress((tmp_path / "sitemap-1.xml.gz").read_bytes()).decode()
    assert "<image:loc>https://example.com/logo.png</image:loc>" in first
    assert "<lastmod>2026-09-01T10:00:00+00:00</lastmod>" in first


def test_stdout(small_site, capsysbinary):
    assert main([ROOT, "-o", "-", "--max-depth", "0", "-q"], transport=small_site.transport) == 0
    out = capsysbinary.readouterr().out
    assert out.startswith(b"<?xml")
    assert b"<loc>https://example.com/</loc>" in out
    assert b"/p0" not in out


def test_nothing_indexable_exits_1(tmp_path, capsys):
    site = FakeSite().add(f"{ROOT}/robots.txt", Resource("User-agent: *\nDisallow: /\n"))
    out = tmp_path / "sitemap.xml"
    assert main([ROOT, "-o", str(out)], transport=site.transport) == 1
    assert not out.exists()
    assert "no indexable pages" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["ftp://example.com/"],
        [ROOT, "--max-pages", "0"],
        [ROOT, "--concurrency", "abc"],
        [ROOT, "--max-urls-per-file", "60000"],
        [ROOT, "-o", "-", "--gzip"],
        [ROOT, "--exclude", "("],
        [ROOT, "--timeout", "0"],
    ],
)
def test_usage_errors(args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert "sitemap-gen: error:" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"sitemap-gen {__version__}"
