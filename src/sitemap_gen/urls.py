"""URL normalisation and filtering."""

from __future__ import annotations

import re
import string
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

# Links to these are never fetched: they are not HTML pages.
_SKIP_EXTENSIONS_TEXT = """
    7z aac apk avi avif bin bmp bz2 css csv dmg doc docx eot epub exe flac gif gz ico ics iso jar jpeg jpg js json
    m4a m4v map mid midi mkv mov mp3 mp4 mpeg mpg msi odp ods odt ogg ogv otf pdf png ppt pptx ps psd rar rss rtf
    svg svgz swf tar tgz tif tiff ttf txt wav webm webmanifest webp wmv woff woff2 xls xlsx xml xz zip
"""
SKIP_EXTENSIONS = frozenset(_SKIP_EXTENSIONS_TEXT.split())

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "ftp:", "file:", "blob:")

DEFAULT_PORTS = {"http": 80, "https": 443}

# Characters that may stay unescaped in each URL part (RFC 3986).
_PATH_SAFE = "/:@!$&'()*+,;=-._~%"
_QUERY_SAFE = "/?:@!$&'()*+,;=-._~%"


_PCT = re.compile(r"%([0-9A-Fa-f]{2})")
_BARE_PCT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")


def _requote(part: str, safe: str) -> str:
    """Normalise percent-encoding: decode unreserved characters, upper-case the
    rest, encode spaces and non-ASCII characters, and keep deliberately escaped
    reserved characters (like ``%2F``) escaped."""
    part = _BARE_PCT.sub("%25", part)

    def fix(m: re.Match[str]) -> str:
        ch = chr(int(m.group(1), 16))
        return ch if ch in _UNRESERVED else "%" + m.group(1).upper()

    return quote(_PCT.sub(fix, part), safe=safe)


def _remove_dot_segments(path: str) -> str:
    out: list[str] = []
    for seg in path.split("/"):
        if seg == "..":
            if len(out) > 1:
                out.pop()
        elif seg != ".":
            out.append(seg)
    result = "/".join(out)
    if path.endswith(("/.", "/..")):
        result += "/"
    if not result.startswith("/"):
        result = "/" + result
    return result


def normalize_url(url: str, base: str | None = None, *, strip_query: bool = False) -> str | None:
    """Resolve ``url`` against ``base`` and normalise it.

    Lower-cases the scheme and host, removes default ports and the fragment,
    resolves ``.`` and ``..`` segments, normalises percent-encoding and gives
    an empty path a ``/``. Returns ``None`` for URLs that are not http(s).
    """
    url = url.strip()
    if not url or url.lower().startswith(SKIP_SCHEMES):
        return None
    try:
        if base is not None:
            url = urljoin(base, url)
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    host = parts.hostname.lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    path = _requote(_remove_dot_segments(parts.path or "/"), _PATH_SAFE)
    query = "" if strip_query else _requote(parts.query, _QUERY_SAFE)
    return urlunsplit((scheme, netloc, path, query, ""))


def host_of(url: str) -> str:
    """``scheme://host[:port]`` of a normalised URL."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def same_site(url: str, origin: str) -> bool:
    """True when ``url`` is on the same scheme, host and port as ``origin``."""
    return host_of(url) == host_of(origin)


def has_skipped_extension(url: str) -> bool:
    path = unquote(urlsplit(url).path)
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1].lower() in SKIP_EXTENSIONS
