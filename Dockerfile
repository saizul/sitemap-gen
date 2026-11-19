FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . \
    && useradd --system --uid 10001 --home-dir /out app \
    && mkdir -p /out \
    && chown app /out \
    && rm -rf /app/build
USER app
WORKDIR /out
ENTRYPOINT ["sitemap-gen"]
CMD ["--help"]
