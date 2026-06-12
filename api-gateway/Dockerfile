# ── Stage 1: Build stage (compile dependencies, keep image small) ──
FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libldap2-dev libsasl2-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Stage 2: Runtime stage (no build tools, minimal size) ──
FROM python:3.12-slim

# §1.1 — Security hardening: install only runtime libraries, no build tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       libldap2 \
       libsasl2-2 \
       libssl3t64 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# §1.1 — Non-root user with explicit UID/GID
ARG GATEWAY_UID=999
ARG GATEWAY_GID=999

RUN groupadd -r -g ${GATEWAY_GID} gateway && \
    useradd -r -u ${GATEWAY_UID} -g gateway -s /usr/sbin/nologin -d /nonexistent gatewayuser

WORKDIR /app

# Copy installed packages from build stage (no build tools)
COPY --from=builder /root/.local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages/
COPY --from=builder /root/.local/bin /usr/local/bin/

# Copy application code
COPY main.py _core.py constants.py auth_store.py enterprise_auth.py jwt_utils.py \
     auth_middleware.py trace_store.py traces_router.py dependencies.py \
     webhook_security.py structured_logging.py migration_runner.py error_codes.py ./
COPY routers/ ./routers/
COPY services/ ./services/
COPY migrations/ ./migrations/
COPY alembic.ini .

# §1.1 — Proper file ownership and permissions
RUN chown -R gatewayuser:gateway /app && \
    chmod -R 755 /app && \
    chmod -R 644 /app/*.py /app/*.ini

# Prepare volume mount points for temporary data (writable without root)
RUN mkdir -p /tmp/gateway && chown -R gatewayuser:gateway /tmp/gateway

# §1.1 — Security context (non-root, no capabilities)
USER gatewayuser

EXPOSE 8080

# §2.2 — Health check for liveness probe
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; import sys; \
        try: \
            urllib.request.urlopen('http://localhost:8080/health', timeout=3); \
            sys.exit(0); \
        except: sys.exit(1)" || exit 1

# §3.3 — Environment defaults
ENV API_GATEWAY_LOG_LEVEL=INFO
ENV JSON_LOGS=true

# Run with graceful shutdown timeout (SIGTERM → 30s grace period)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
