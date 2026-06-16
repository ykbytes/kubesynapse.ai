# syntax=docker/dockerfile:1.7
# mcp-kubernetes — run kubectl and query cluster resources.
ARG MCP_BASE_TAG=localhost/kubesynapse/mcp-base:dev
FROM ${MCP_BASE_TAG}
LABEL org.opencontainers.image.title="KubeSynapse MCP Kubernetes"
LABEL org.opencontainers.image.description="Kubernetes access sidecar for KubeSynapse agents"
LABEL org.opencontainers.image.source="https://github.com/kubesynapse/kubesynapse"

USER root
# Install kubectl from the upstream release.  Use the stable version link so
# the image stays reproducible at build time.
RUN apk add --no-cache curl \
    && KUBECTL_VERSION=$(curl -fsSL https://dl.k8s.io/release/stable.txt) \
    && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && kubectl version --client \
    && apk del --purge curl \
    && rm -rf /var/cache/apk/* /tmp/*

WORKDIR /app
COPY --chown=mcpuser:mcpuser kubernetes/requirements.txt /app/requirements.txt
COPY --chown=mcpuser:mcpuser kubernetes/requirements.lock /app/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.lock && \
    rm -rf /tmp/*

COPY --chown=mcpuser:mcpuser kubernetes/server.py /app/server.py
COPY --chown=mcpuser:mcpuser kubernetes/capabilities.json /app/capabilities.json

ENV MCP_SERVER_TYPE=kubernetes \
    MCP_LISTEN_PORT=8086 \
    MCP_HEALTH_PORT=8186

USER mcpuser
EXPOSE 8086 8186
CMD ["python", "/app/server.py"]
