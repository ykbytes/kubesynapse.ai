FROM python:3.11-slim
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY rag/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY rag/server.py /app/server.py
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8088
CMD ["python", "/app/server.py"]
