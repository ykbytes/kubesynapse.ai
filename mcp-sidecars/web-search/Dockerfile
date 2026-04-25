FROM python:3.11-slim
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY web-search/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY web-search/server.py /app/server.py
COPY web-search/capabilities.json /app/capabilities.json
ENV MCP_LISTEN_PORT=8081
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8081
CMD ["python", "/app/server.py"]
