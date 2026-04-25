FROM node:20-slim AS opencode-install

RUN npm install -g opencode-ai && \
    cd /usr/local/lib/node_modules/opencode-ai && \
    npm install opencode-linux-x64 opencode-linux-x64-baseline 2>/dev/null || true && \
    command -v opencode >/dev/null && \
    opencode --version && \
    echo "OpenCode installed and verified"

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git nodejs npm curl unzip ca-certificates \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=opencode-install /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=opencode-install /usr/local/bin/opencode /usr/local/bin/opencode
# The wrapper uses fs.realpathSync(__filename) to find .opencode next to itself;
# after COPY (not symlink), scriptDir resolves to /usr/local/bin/ instead of the
# original node_modules path, so copy the cached binary there too.
COPY --from=opencode-install /usr/local/lib/node_modules/opencode-ai/bin/.opencode /usr/local/bin/.opencode

RUN BUN_VERSION="1.1.45" \
    && curl -fsSL https://bun.sh/install | bash -s "bun-v${BUN_VERSION}" \
    && mv /root/.bun /opt/bun \
    && ln -sf /opt/bun/bin/bun /usr/local/bin/bun

WORKDIR /app

COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py hitl.py config.py tracing.py utils.py prompts.py models.py session.py skills.py opencode_client.py analysis.py invoke.py supervisor.py workspace.py sanitize_secrets.py ./
COPY memory/ ./memory/

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