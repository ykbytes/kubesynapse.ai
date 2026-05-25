FROM python:3.11-slim

WORKDIR /app

COPY base/requirements-base.txt /app/base-requirements.txt
RUN pip install --no-cache-dir -r base-requirements.txt

COPY collector/requirements.txt /app/collector-requirements.txt
RUN pip install --no-cache-dir -r collector-requirements.txt

COPY base/mcp_base.py /app/mcp_base.py
COPY collector/server.py /app/server.py
COPY collector/capabilities.json /app/capabilities.json

RUN useradd -u 1000 -m mcpuser || true
USER 1000

EXPOSE 8100
ENV MCP_LISTEN_PORT=8100
CMD ["python", "/app/server.py"]
