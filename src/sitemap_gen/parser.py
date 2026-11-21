"""Extract links, the canonical URL, hreflang alternates, robots directives and images from HTML."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

# Names of <meta> tags whose content holds robots directives for us.
ROBOTS_META_NAMES = frozenset({"robots"})


@dataclass
class PageInfo:
    links: list[str] = field(default_factory=list)
    nofollow_links: list[str] = field(default_factory=list)
    canonical: str | None = None
    base: str | None = None
    noindex: bool = False
    nofollow: bool = False
    images: list[str] = field(default_factory=list)
    alternates: list[tuple[str, str]] = field(default_factory=list)
    """``(hreflang, href)`` pairs from ``<link rel="alternate" hreflang="..." href="...">``."""


def parse_robots_directives(value: str) -> set[str]:
    """``"noindex, NoFollow"`` → ``{"noindex", "nofollow"}``. ``none`` means both."""
    directives = set()
    for part in value.split(","):
        token = part.strip().lower()
        # X-Robots-Tag may be prefixed with a user agent: "otherbot: noindex".
        if ":" in token:
            continue
        if token == "none":
            directives.update({"noindex", "nofollow"})
        elif token:
            directives.add(token)
    return directives


class _Extractor(HTMLParser):
    def __init__(self, robots_meta_names: frozenset[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.info = PageInfo()
        self.robots_meta_names = robots_meta_names

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("a", "area"):
            href = a.get("href", "").strip()
            if href:
                rel = set(a.get("rel", "").lower().split())
                (self.info.nofollow_links if "nofollow" in rel else self.info.links).append(href)
        elif tag == "link":
            rel = set(a.get("rel", "").lower().split())
            href = a.get("href", "").strip()
            if "canonical" in rel and href and self.info.canonical is None:
                self.info.canonical = href
            hreflang = a.get("hreflang", "").strip()
            if "alternate" in rel and href and hreflang:
                self.info.alternates.append((hreflang, href))
        elif tag == "base":
            href = a.get("href", "").strip()
            if href and self.info.base is None:
                self.info.base = href
        elif tag == "meta":
            name = a.get("name", "").strip().lower()
            if name in self.robots_meta_names:
                d = parse_robots_directives(a.get("content", ""))
                self.info.noindex |= "noindex" in d
                self.info.nofollow |= "nofollow" in d
        elif tag == "img":
            src = a.get("src", "").strip()
            if src and not src.lower().startswith("data:"):
                self.info.images.append(src)

    handle_startendtag = handle_starttag


def parse_html(html: str, *, user_agent_token: str = "sitemap-gen") -> PageInfo:
    """Parse an HTML document. Robots meta tags named ``robots`` or after our
    user agent token (e.g. ``<meta name="sitemap-gen" content="noindex">``) apply."""
    parser = _Extractor(ROBOTS_META_NAMES | {user_agent_token.lower()})
    try:
        parser.feed(html)
        parser.close()
    except AssertionError:  # pragma: no cover - html.parser is very forgiving
        pass
    return parser.info
