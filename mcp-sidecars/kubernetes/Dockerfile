FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY base/requirements-base.txt /app/requirements-base.txt
COPY kubernetes/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements-base.txt -r requirements.txt
COPY base/mcp_base.py /app/base/mcp_base.py
COPY kubernetes/server.py /app/server.py
RUN useradd -u 1000 -m mcpuser || true
USER 1000
EXPOSE 8086
CMD ["python", "/app/server.py"]
