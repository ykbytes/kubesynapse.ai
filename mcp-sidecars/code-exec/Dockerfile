FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends bash nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY code-exec/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY code-exec/server.py /app/server.py
ENV MCP_LISTEN_PORT=8082
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8082
CMD ["python", "/app/server.py"]
