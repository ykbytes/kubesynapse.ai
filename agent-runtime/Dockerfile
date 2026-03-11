FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

RUN getent group agentgroup >/dev/null || groupadd -r agentgroup \
	&& id -u agentuser >/dev/null 2>&1 || useradd -r -g agentgroup agentuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_logic.py env_utils.py guardrails.py hitl.py opensandbox_tools.py ./
RUN mkdir -p /app/state && chown -R agentuser:agentgroup /app

USER agentuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
	CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ready', timeout=3)"

CMD ["uvicorn", "agent_logic:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
