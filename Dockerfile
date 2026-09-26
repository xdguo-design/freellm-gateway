# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS web
WORKDIR /src

COPY web/package.json web/package-lock.json ./web/
RUN npm ci --prefix web --no-audit --no-fund

COPY web ./web
COPY freellm_gateway ./freellm_gateway
RUN npm run build --prefix web


FROM python:3.12-slim AS wheel
WORKDIR /src

COPY pyproject.toml ./
COPY freellm_gateway ./freellm_gateway
COPY --from=web /src/freellm_gateway/static/admin ./freellm_gateway/static/admin

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip wheel . --wheel-dir /wheels


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FREELLM_GATEWAY_HOST=0.0.0.0 \
    FREELLM_GATEWAY_PORT=8765 \
    FREELLM_GATEWAY_DB=/data/gateway.sqlite3 \
    FREELLM_GATEWAY_CATALOG_OUTPUT=/data/catalog-export.json \
    FREELLM_GATEWAY_CONNECTION_LOG=/data/gateway-connections.jsonl \
    FREELLM_GATEWAY_SECRETS_FILE=/data/provider-secrets.json \
    FREELLM_GATEWAY_REQUIRE_EXPLICIT_TOKENS=1

RUN groupadd --gid 10001 freellm \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin freellm

COPY --from=wheel /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels freellm-gateway \
    && rm -rf /wheels \
    && mkdir -p /data \
    && chown -R freellm:freellm /data

USER freellm
WORKDIR /home/freellm

VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.getenv('PORT',os.getenv('FREELLM_GATEWAY_PORT','8765')); urllib.request.urlopen(f'http://127.0.0.1:{p}/health/ready', timeout=3).read()"

CMD ["python", "-m", "freellm_gateway", "run", "--skip-web-build"]
