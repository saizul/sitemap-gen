# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's
private vulnerability reporting ("Report a vulnerability" under the
repository's **Security** tab). You will get an answer within a week.

## Scope

sitemap-gen downloads and parses pages from servers that may not be
trustworthy. Reports in these areas are especially welcome:

- **Escaping the start host.** The crawler must only request URLs on the
  scheme, host and port of the start URL (after its own redirect). A link,
  redirect, `<base>` or canonical URL that makes it request another host,
  a `file:` URL or a local network address it was not pointed at is a bug.
- **XML injection.** Every URL written to a sitemap is entity-escaped. A page
  that can break the XML structure of the output is a bug.
- **Resource exhaustion.** Pages are capped at 5 MB and robots.txt at
  512 KiB, and `--max-pages` bounds the crawl. A response that makes
  sitemap-gen hang or use unbounded memory is a bug.

## Running it safely

The Docker image runs as an unprivileged user. If you run sitemap-gen in a
network with internal services, remember that it fetches whatever start URL
you give it, so do not pass it URLs from untrusted users without your own
allow-list.
