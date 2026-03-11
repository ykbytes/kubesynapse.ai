FROM python:3.11-slim

RUN getent group gateway >/dev/null || groupadd -r gateway \
	&& id -u gatewayuser >/dev/null 2>&1 || useradd -r -g gateway gatewayuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
RUN chown -R gatewayuser:gateway /app

USER gatewayuser
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
