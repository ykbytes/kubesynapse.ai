FROM python:3.11-slim

RUN getent group operator >/dev/null || groupadd -r -g 37 operator \
	&& id -u operator >/dev/null 2>&1 || useradd -r -u 999 -g operator -ms /bin/bash operator

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py mock_entrypoint.py worker.py utils.py state_store.py config.py errors.py reconcile.py tracing.py trace_client.py runtime_events.py circuit_breaker.py alembic.ini ./
COPY controllers/ ./controllers/
COPY builders/ ./builders/
COPY services/ ./services/
COPY migrations/ ./migrations/

RUN chown -R operator:operator /app
USER operator

CMD ["kopf", "run", "/app/main.py", "--verbose", "--liveness=http://0.0.0.0:8080/healthz"]
