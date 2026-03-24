# NOTE: v1.0.18 tag was removed from ghcr.io/block/goose.
# Using :latest until a stable versioned tag is published again.
FROM ghcr.io/block/goose:latest

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py .

RUN mkdir -p /app/state /workspace \
    && chown -R goose:goose /app /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/app/state/home \
    XDG_CONFIG_HOME=/app/state/home/.config \
    XDG_DATA_HOME=/app/state/home/.local/share \
    GOOSE_BIN=/usr/local/bin/goose \
    GOOSE_WORKDIR=/workspace

USER goose

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]