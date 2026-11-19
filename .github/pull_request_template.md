## What does this pull request do?

<!-- One or two sentences. Link the issue: "Closes #123". -->

## Type

- [ ] Crawling or politeness change
- [ ] Sitemap output change
- [ ] Bug fix
- [ ] Documentation

## Checklist

- [ ] Tests added or updated (`pytest` passes; tests use `httpx.MockTransport` and no network)
- [ ] `ruff check . && ruff format --check .` passes
- [ ] robots.txt, the concurrency limit, the delay and the same-host rule still apply
- [ ] README updated for new options or behaviour
- [ ] CHANGELOG.md updated under "Unreleased"
