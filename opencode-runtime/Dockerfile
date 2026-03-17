FROM node:20-slim AS opencode-install

RUN npm install -g opencode-ai && \
    command -v opencode >/dev/null && \
    OPENCODE_BIN=$(which opencode) && \
    echo "OpenCode installed at: $OPENCODE_BIN"

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git nodejs npm curl unzip ca-certificates \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=opencode-install /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=opencode-install /usr/local/bin/opencode /usr/local/bin/opencode

RUN curl -fsSL https://bun.sh/install | bash \
    && mv /root/.bun /opt/bun \
    && ln -sf /opt/bun/bin/bun /usr/local/bin/bun

WORKDIR /app

COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY hitl.py .

RUN test -x /usr/local/bin/opencode && test -x /usr/local/bin/bun

RUN useradd --uid 1000 --create-home opencodeuser \
    && mkdir -p /app/state /workspace \
    && chown -R opencodeuser:opencodeuser /app /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:/usr/local/bin:$PATH \
    HOME=/app/state/home \
    XDG_CONFIG_HOME=/app/state/home/.config \
    XDG_DATA_HOME=/app/state/home/.local/share \
    OPENCODE_CONFIG_DIR=/app/state/home/.config/opencode-profile \
    OPENCODE_BIN=/usr/local/bin/opencode \
    OPENCODE_WORKDIR=/workspace

USER opencodeuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]