FROM python:3.11-slim
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY messaging/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/base/mcp_base.py
COPY messaging/server.py /app/server.py
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8087
CMD ["python", "/app/server.py"]
