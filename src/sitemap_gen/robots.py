"""A small robots.txt parser that follows RFC 9309.

Python's ``urllib.robotparser`` does not support the ``*`` and ``$``
wildcards or longest-match precedence, which most large sites rely on, so
this module implements the standard directly:

- Groups are chosen by the product token of the user agent (case
  insensitive); several groups for the same agent are merged; ``*`` is the
  fallback.
- The most specific (longest) matching rule wins; on a tie ``Allow`` wins.
- ``*`` matches any sequence of characters and a trailing ``$`` anchors the
  end of the URL.
- ``/robots.txt`` itself is always allowed.

``Crawl-delay`` is not part of RFC 9309, but it is widely used, so it is read
too and the crawler honours it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_PCT = re.compile(r"%([0-9A-Fa-f]{2})")


def _canonical_path(text: str) -> str:
    # Compare paths with unreserved characters decoded and escapes upper-cased,
    # so "/%7Euser" and "/~user" match each other.
    def fix(m: re.Match[str]) -> str:
        ch = chr(int(m.group(1), 16))
        return ch if (ch.isascii() and (ch.isalnum() or ch in "-._~")) else "%" + m.group(1).upper()

    return _PCT.sub(fix, text)


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @classmethod
    def make(cls, allow: bool, pattern: str) -> Rule:
        pattern = _canonical_path(pattern)
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        return cls(allow, pattern, re.compile(regex + ("$" if anchored else ""), re.DOTALL))

    def matches(self, path: str) -> bool:
        return self.regex.match(path) is not None


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass
class RobotsTxt:
    """Parsed robots.txt rules for one site."""

    groups: list[_Group] = field(default_factory=list)
    allow_all: bool = False
    disallow_all: bool = False
    sitemaps: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> RobotsTxt:
        robots = cls()
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    robots.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key == "sitemap":
                if value:
                    robots.sitemaps.append(value)
            elif current is None:
                continue
            elif key in ("allow", "disallow"):
                if value:  # An empty Disallow means "allow everything".
                    current.rules.append(Rule.make(key == "allow", value))
            elif key == "crawl-delay":
                try:
                    delay = float(value)
                except ValueError:
                    continue
                if delay >= 0:
                    current.crawl_delay = delay
        return robots

    @classmethod
    def allowing_all(cls) -> RobotsTxt:
        return cls(allow_all=True)

    @classmethod
    def disallowing_all(cls) -> RobotsTxt:
        return cls(disallow_all=True)

    def _groups_for(self, user_agent: str) -> list[_Group]:
        token = user_agent.split("/", 1)[0].strip().lower()
        exact = [g for g in self.groups if token in g.agents]
        if exact:
            return exact
        return [g for g in self.groups if "*" in g.agents]

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.allow_all:
            return True
        parts = urlsplit(url)
        path = parts.path or "/"
        if path == "/robots.txt":
            return True
        if self.disallow_all:
            return False
        target = _canonical_path(path + (f"?{parts.query}" if parts.query else ""))
        best: Rule | None = None
        for group in self._groups_for(user_agent):
            for rule in group.rules:
                if not rule.matches(target):
                    continue
                if (
                    best is None
                    or len(rule.pattern) > len(best.pattern)
                    or (len(rule.pattern) == len(best.pattern) and rule.allow and not best.allow)
                ):
                    best = rule
        return best is None or best.allow

    def crawl_delay(self, user_agent: str) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(user_agent) if g.crawl_delay is not None]
        return max(delays) if delays else None


__all__ = ["RobotsTxt", "Rule"]
