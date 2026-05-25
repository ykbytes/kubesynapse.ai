FROM python:3.11-slim
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY database/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY database/server.py /app/server.py
COPY database/capabilities.json /app/capabilities.json
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8084
CMD ["python", "/app/server.py"]
