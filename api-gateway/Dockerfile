FROM python:3.11-slim

RUN apt-get update \
	&& apt-get install -y --no-install-recommends gcc libldap2-dev libsasl2-dev libssl-dev \
	&& rm -rf /var/lib/apt/lists/*

RUN getent group gateway >/dev/null || groupadd -r gateway \
	&& id -u gatewayuser >/dev/null 2>&1 || useradd -r -g gateway gatewayuser
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py auth_store.py enterprise_auth.py jwt_utils.py auth_middleware.py ./
RUN chown -R gatewayuser:gateway /app

USER gatewayuser
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
