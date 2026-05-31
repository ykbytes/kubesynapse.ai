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

# Copy only runtime libraries needed by python-ldap
RUN apt-get update \
    && apt-get install -y --no-install-recommends libldap2 libsasl2-2 libssl3t64 \
    && rm -rf /var/lib/apt/lists/*

RUN getent group gateway >/dev/null || groupadd -r gateway \
    && id -u gatewayuser >/dev/null 2>&1 || useradd -r -g gateway gatewayuser
WORKDIR /app

# Copy installed packages from build stage
COPY --from=builder /root/.local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages/
COPY --from=builder /root/.local/bin /usr/local/bin/

# Copy application code
COPY main.py _core.py constants.py auth_store.py enterprise_auth.py jwt_utils.py auth_middleware.py trace_store.py traces_router.py dependencies.py webhook_security.py structured_logging.py migration_runner.py error_codes.py ./
COPY routers/ ./routers/
COPY services/ ./services/
COPY migrations/ ./migrations/
COPY alembic.ini .

RUN chown -R gatewayuser:gateway /app

USER gatewayuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
