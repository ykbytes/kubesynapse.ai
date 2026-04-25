FROM python:3.11-slim
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY documents/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY documents/server.py /app/server.py
COPY documents/capabilities.json /app/capabilities.json
ENV MCP_LISTEN_PORT=8092
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8092
CMD ["python", "/app/server.py"]
