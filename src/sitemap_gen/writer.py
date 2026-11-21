"""Write sitemaps (sitemaps.org protocol 0.9) and sitemap index files."""

from __future__ import annotations

import gzip as gzip_module
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
XHTML_NS = "http://www.w3.org/1999/xhtml"

MAX_URLS = 50_000
"""Protocol limit: URLs per sitemap file."""
MAX_BYTES = 50 * 1024 * 1024
"""Protocol limit: 50 MiB per sitemap file, uncompressed."""


@dataclass
class SitemapEntry:
    loc: str
    lastmod: datetime | None = None
    images: Sequence[str] = field(default_factory=tuple)
    alternates: Sequence[tuple[str, str]] = field(default_factory=tuple)
    """``(hreflang, url)`` pairs written as ``<xhtml:link rel="alternate">`` with ``hreflang=True``."""


@dataclass
class SitemapFile:
    name: str
    content: bytes
    """Uncompressed XML."""
    urls: int


def xml_escape(text: str) -> str:
    """Entity-escape a value as the sitemap protocol requires."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
    )


def w3c_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _header(images: bool, hreflang: bool = False) -> bytes:
    ns = f' xmlns="{SITEMAP_NS}"'
    if hreflang:
        ns += f' xmlns:xhtml="{XHTML_NS}"'
    if images:
        ns += f' xmlns:image="{IMAGE_NS}"'
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset{ns}>\n'.encode()


_FOOTER = b"</urlset>\n"


def _entry(entry: SitemapEntry, images: bool, hreflang: bool = False) -> bytes:
    lines = ["  <url>", f"    <loc>{xml_escape(entry.loc)}</loc>"]
    if entry.lastmod is not None:
        lines.append(f"    <lastmod>{w3c_datetime(entry.lastmod)}</lastmod>")
    if hreflang:
        for lang, href in entry.alternates:
            lines.append(f'    <xhtml:link rel="alternate" hreflang="{xml_escape(lang)}" href="{xml_escape(href)}"/>')
    if images:
        for img in entry.images:
            lines += ["    <image:image>", f"      <image:loc>{xml_escape(img)}</image:loc>", "    </image:image>"]
    lines.append("  </url>")
    return ("\n".join(lines) + "\n").encode()


def build_sitemaps(
    entries: Iterable[SitemapEntry],
    *,
    images: bool = False,
    hreflang: bool = False,
    max_urls: int = MAX_URLS,
    max_bytes: int = MAX_BYTES,
) -> list[bytes]:
    """Render entries into as many ``<urlset>`` documents as the limits require."""
    if not 1 <= max_urls <= MAX_URLS:
        raise ValueError(f"max_urls must be between 1 and {MAX_URLS}")
    if not 1024 <= max_bytes <= MAX_BYTES:
        raise ValueError(f"max_bytes must be between 1024 and {MAX_BYTES}")
    header = _header(images, hreflang)
    fixed = len(header) + len(_FOOTER)
    docs: list[bytes] = []
    chunk: list[bytes] = []
    size = fixed
    for entry in entries:
        data = _entry(entry, images, hreflang)
        if fixed + len(data) > max_bytes:
            raise ValueError(f"a single entry is larger than {max_bytes} bytes: {entry.loc[:100]}")
        if chunk and (len(chunk) >= max_urls or size + len(data) > max_bytes):
            docs.append(header + b"".join(chunk) + _FOOTER)
            chunk, size = [], fixed
        chunk.append(data)
        size += len(data)
    if chunk or not docs:
        docs.append(header + b"".join(chunk) + _FOOTER)
    return docs


def build_index(locations: Iterable[str], lastmod: datetime | None = None) -> bytes:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<sitemapindex xmlns="{SITEMAP_NS}">']
    for loc in locations:
        lines += ["  <sitemap>", f"    <loc>{xml_escape(loc)}</loc>"]
        if lastmod is not None:
            lines.append(f"    <lastmod>{w3c_datetime(lastmod)}</lastmod>")
        lines.append("  </sitemap>")
    lines.append("</sitemapindex>")
    return ("\n".join(lines) + "\n").encode()


def _child_name(output: Path, n: int, gzip: bool) -> str:
    name = output.name
    if name.endswith(".gz"):
        name = name[:-3]
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, "xml"
    return f"{stem}-{n}.{ext}" + (".gz" if gzip else "")


def plan_files(
    entries: Iterable[SitemapEntry],
    output: Path,
    *,
    base_url: str,
    gzip: bool = False,
    images: bool = False,
    hreflang: bool = False,
    max_urls: int = MAX_URLS,
    max_bytes: int = MAX_BYTES,
    now: datetime | None = None,
) -> list[SitemapFile]:
    """Decide the files to write. One file when everything fits; otherwise
    numbered sitemaps plus an index at ``output`` that points to them under
    ``base_url``."""
    entries = list(entries)
    docs = build_sitemaps(entries, images=images, hreflang=hreflang, max_urls=max_urls, max_bytes=max_bytes)
    out_name = output.name
    if gzip and not out_name.endswith(".gz"):
        out_name += ".gz"
    if len(docs) == 1:
        return [SitemapFile(out_name, docs[0], len(entries))]
    files: list[SitemapFile] = []
    counts = [doc.count(b"<url>") for doc in docs]
    for n, (doc, count) in enumerate(zip(docs, counts, strict=True), start=1):
        files.append(SitemapFile(_child_name(output, n, gzip), doc, count))
    base = base_url.rstrip("/") + "/"
    index = build_index((base + f.name for f in files), lastmod=now)
    return [SitemapFile(out_name, index, 0), *files]


def write_sitemaps(
    entries: Iterable[SitemapEntry],
    output: str | Path,
    *,
    base_url: str,
    gzip: bool = False,
    images: bool = False,
    hreflang: bool = False,
    max_urls: int = MAX_URLS,
    max_bytes: int = MAX_BYTES,
    now: datetime | None = None,
) -> list[Path]:
    """Write the sitemap (or index and sitemaps) and return the paths written."""
    output = Path(output)
    files = plan_files(
        entries,
        output,
        base_url=base_url,
        gzip=gzip,
        images=images,
        hreflang=hreflang,
        max_urls=max_urls,
        max_bytes=max_bytes,
        now=now,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    written = []
    for f in files:
        path = output.parent / f.name
        data = gzip_module.compress(f.content, mtime=0) if gzip else f.content
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        written.append(path)
    return written
