# Multi-stage build for minimal image size and attack surface
FROM python:3.11-slim AS builder

WORKDIR /tmp/build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.11-slim

# §6.5 — Security hardening: non-root, no capabilities, read-only filesystem
ARG OPERATOR_UID=999
ARG OPERATOR_GID=37

RUN set -eux; \
    getent group operator >/dev/null || groupadd -r -g "${OPERATOR_GID}" operator; \
    getent passwd operator >/dev/null || useradd -r -u "${OPERATOR_UID}" -g operator -s /usr/sbin/nologin -d /nonexistent operator

# Install runtime dependencies only (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy python packages from builder
COPY --from=builder /root/.local /usr/local

# Copy operator code
COPY main.py worker.py utils.py state_store.py config.py reconcile.py tracing.py \
     trace_client.py runtime_events.py circuit_breaker.py alembic.ini ./
COPY controllers/ ./controllers/
COPY builders/ ./builders/
COPY services/ ./services/
COPY migrations/ ./migrations/

# Set proper file ownership and permissions
RUN chown -R operator:operator /app && \
    chmod -R 755 /app && \
    chmod -R 644 /app/*.py /app/*.ini

USER operator

# Health check via stdlib to keep the runtime image minimal.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1

# Set environment defaults
ENV OPERATOR_LOG_LEVEL=INFO
ENV JSON_LOGS=true
ENV OTEL_EXPORTER_OTLP_INSECURE=true

# Run Kopf with verbose logging and health server
CMD ["kopf", "run", "/app/main.py", "--verbose", \
     "--liveness=http://0.0.0.0:8080/healthz"]
