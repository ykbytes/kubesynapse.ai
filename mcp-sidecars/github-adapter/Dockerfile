FROM python:3.11-slim

WORKDIR /app

COPY github-adapter/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY github-adapter/server.py /app/server.py
COPY github-adapter/capabilities.json /app/capabilities.json

RUN useradd -u 1000 -m mcpuser || true
USER 1000

EXPOSE 8000
ENV PYTHONUNBUFFERED=1
ENV MCP_LISTEN_ADDR=0.0.0.0:8000

CMD ["python", "/app/server.py"]