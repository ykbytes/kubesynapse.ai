FROM node:20-slim AS codex-install

RUN npm install -g @openai/codex && \
    command -v codex >/dev/null && \
    CODEX_BIN=$(which codex) && \
    echo "Codex installed at: $CODEX_BIN"

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git nodejs npm \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=codex-install /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=codex-install /usr/local/bin/codex /usr/local/bin/codex

WORKDIR /app

COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY codex_app_server ./codex_app_server

RUN test -x /usr/local/bin/codex

RUN useradd --uid 1000 --create-home codexuser \
    && mkdir -p /app/state /workspace \
    && chown -R codexuser:codexuser /app /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:/usr/local/bin:$PATH \
    HOME=/app/state/home \
    CODEX_HOME=/app/state/home/.codex \
    XDG_CONFIG_HOME=/app/state/home/.config \
    XDG_DATA_HOME=/app/state/home/.local/share \
    CODEX_BIN=/usr/local/bin/codex \
    CODEX_WORKDIR=/workspace

USER codexuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
