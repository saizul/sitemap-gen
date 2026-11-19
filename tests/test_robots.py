from sitemap_gen.robots import RobotsTxt

UA = "sitemap-gen/0.1 (+https://github.com/saizul/sitemap-gen)"

ROBOTS = """
# Example robots.txt
User-agent: *
Disallow: /private/
Disallow: /*.php$
Disallow: /search
Allow: /private/press/
Crawl-delay: 2

User-agent: sitemap-gen
User-agent: otherbot
Disallow: /drafts
Allow: /drafts/public

Sitemap: https://example.com/sitemap.xml
"""


def test_specific_group_wins_over_star():
    r = RobotsTxt.parse(ROBOTS)
    assert not r.can_fetch(UA, "https://example.com/drafts/x")
    assert r.can_fetch(UA, "https://example.com/drafts/public/y")
    # The * group does not apply to us because a sitemap-gen group exists.
    assert r.can_fetch(UA, "https://example.com/private/x")
    assert r.crawl_delay(UA) is None
    assert r.sitemaps == ["https://example.com/sitemap.xml"]


def test_star_group_longest_match_and_wildcards():
    r = RobotsTxt.parse(ROBOTS)
    ua = "SomeBot/1.0"
    assert not r.can_fetch(ua, "https://example.com/private/x")
    assert r.can_fetch(ua, "https://example.com/private/press/release")
    assert not r.can_fetch(ua, "https://example.com/index.php")
    assert r.can_fetch(ua, "https://example.com/index.php?x=1")
    assert not r.can_fetch(ua, "https://example.com/search?q=1")
    assert not r.can_fetch(ua, "https://example.com/searching")
    assert r.can_fetch(ua, "https://example.com/")
    assert r.can_fetch(ua, "https://example.com/robots.txt")
    assert r.crawl_delay(ua) == 2


def test_allow_wins_ties_and_empty_disallow():
    r = RobotsTxt.parse("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert r.can_fetch(UA, "https://example.com/page")
    r = RobotsTxt.parse("User-agent: *\nDisallow:\n")
    assert r.can_fetch(UA, "https://example.com/anything")


def test_case_insensitive_agents_merged_groups_and_encoding():
    r = RobotsTxt.parse("User-agent: SITEMAP-GEN\nDisallow: /a\n\nUser-agent: sitemap-gen\nDisallow: /%7Eb\n")
    assert not r.can_fetch(UA, "https://example.com/a")
    assert not r.can_fetch(UA, "https://example.com/~b/c")
    assert r.can_fetch(UA, "https://example.com/c")


def test_disallow_all_and_garbage():
    r = RobotsTxt.parse("User-agent: *\nDisallow: /\n")
    assert not r.can_fetch(UA, "https://example.com/")
    assert r.can_fetch(UA, "https://example.com/robots.txt")
    r = RobotsTxt.parse("<html>not a robots file</html>\nDisallow: /x\nCrawl-delay: soon\n")
    assert r.can_fetch(UA, "https://example.com/x")
    assert RobotsTxt.disallowing_all().can_fetch(UA, "https://example.com/") is False
    assert RobotsTxt.allowing_all().can_fetch(UA, "https://example.com/") is True
