# Custom LiteLLM image built on Debian (not Wolfi) so Prisma query engine works.
# The official litellm/litellm-database image uses Wolfi Linux which ships glibc
# incompatible with Prisma's pre-built Debian query-engine binary, causing
# "NotConnectedError: Not connected to the query engine" at startup.
#
# This Dockerfile installs litellm[proxy] on python:3.12-slim-bookworm where
# Prisma generates and runs natively.
#
# The pod runs as UID 1000 (runAsNonRoot: true), so all caches must be
# owned by 1000:1000.  The Prisma engine cache is baked into the image at
# /home/litellm/.cache — do NOT mount an emptyDir over it.

FROM python:3.12-slim-bookworm AS builder

# System deps for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install litellm with proxy extras (includes prisma, uvicorn, fastapi, etc.)
RUN pip install --no-cache-dir 'litellm[proxy,extra_proxy]==1.82.3'

# Generate Prisma client using litellm's embedded schema
RUN python -m prisma generate \
    --schema=/usr/local/lib/python3.12/site-packages/litellm/proxy/schema.prisma

# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libatomic1 && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user matching the K8s securityContext (UID/GID 1000)
RUN groupadd -g 1000 litellm && \
    useradd -u 1000 -g litellm -m -d /home/litellm -s /bin/bash litellm

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy Prisma engine cache to the non-root user's home.
# Only copy debian-openssl-3.0.x engines (the platform we run on).
COPY --from=builder --chown=1000:1000 /root/.cache/prisma-python /home/litellm/.cache/prisma-python
COPY --from=builder --chown=1000:1000 /root/.cache/prisma /home/litellm/.cache/prisma

# Ensure the home dir is fully owned by litellm
RUN chown -R 1000:1000 /home/litellm

WORKDIR /app
RUN chown 1000:1000 /app

# Switch to non-root user
USER 1000

ENV HOME=/home/litellm

EXPOSE 4000

ENTRYPOINT ["litellm"]
CMD ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]
