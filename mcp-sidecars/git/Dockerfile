FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY git/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/mcp_base.py
COPY git/server.py /app/server.py
COPY git/capabilities.json /app/capabilities.json
RUN useradd -u 1000 -m mcpuser || true
RUN mkdir -p /home/mcpuser/.ssh && chmod 700 /home/mcpuser/.ssh && chown 1000:1000 /home/mcpuser/.ssh
USER 1000
EXPOSE 8085
CMD ["python", "/app/server.py"]
