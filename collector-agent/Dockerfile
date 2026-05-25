FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl procps iproute2 net-tools dnsutils sysstat lsof \
    && rm -rf /var/lib/apt/lists/*

# Install kubectl
RUN curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && chmod +x kubectl && mv kubectl /usr/local/bin/

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY collector.py /app/collector.py
COPY scripts/ /app/scripts/

RUN useradd -u 1000 -m collector || true
USER 1000

EXPOSE 9100
ENV COLLECTOR_PORT=9100
CMD ["python", "/app/collector.py"]
