# Airspace API: FastAPI on uvicorn, installed with uv.
# Build context: server/

ARG PYTHON_IMAGE=python:3.12.15-slim-trixie

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first, so source edits reuse this layer.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Flask at a pinned commit (BSD-3-Clause, licence kept): the real repo pre-flight and the playground run on.
FROM ${PYTHON_IMAGE} AS flask
ARG FLASK_COMMIT=d086db856be187255b8ec61ef409357393020f32
ADD https://github.com/pallets/flask/archive/${FLASK_COMMIT}.tar.gz /tmp/flask.tar.gz
RUN mkdir /flask && tar -xzf /tmp/flask.tar.gz -C /flask --strip-components=1

FROM ${PYTHON_IMAGE} AS runtime
RUN groupadd --system --gid 10001 airspace \
 && useradd --system --uid 10001 --gid airspace --create-home --home-dir /home/airspace airspace

COPY --from=build /app/.venv /app/.venv
# The demo repository the deployed Tower shows: indexed on start by the entrypoint.
COPY --chown=airspace:airspace tests/fixtures/blog /data/repo
COPY --from=flask --chown=airspace:airspace /flask /data/flask
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# A recording of a real run, played by Tower when no agents are flying.
COPY demo /app/demo

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FALKORDB_HOST=falkordb \
    FALKORDB_PORT=6379 \
    AIRSPACE_ROOT=/data/repo \
    AIRSPACE_REPLAY=/app/demo/replay.json \
    AIRSPACE_PLAYGROUND_REPO=/data/repo \
    AIRSPACE_FLASK_REPO=/data/flask \
    AIRSPACE_PUBLIC_DEMO=1 \
    AIRSPACE_FORWARDED_IPS=*

USER airspace
WORKDIR /data/repo
EXPOSE 8787

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["airspace", "serve", "--root", "/data/repo", "--host", "0.0.0.0", "--port", "8787"]
