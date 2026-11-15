FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.4 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# uv installs the project in editable mode, so the package finds web/ and out/ next to src/.
COPY src ./src
COPY web ./web
RUN uv sync --locked \
    && useradd --system --no-create-home earfit \
    && mkdir out && chown earfit out
USER earfit

ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["earfit-web"]
