"""Mock operator entrypoint for local development without Kubernetes.

Starts the readiness/metrics server and sleeps forever so the container stays
alive for docker-compose health checks and local development.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger("operator.mock")
logging.basicConfig(
    level=os.getenv("OPERATOR_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_READINESS_PORT = int(os.getenv("OPERATOR_READINESS_PORT", "8081"))


class _MockHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for /ready and /metrics probes in mock mode."""

    def do_GET(self) -> None:
        if self.path == "/ready":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        elif self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"# HELP kubesynth_operator_reconcile_total Total reconciliation operations\n"
                b"# TYPE kubesynth_operator_reconcile_total counter\n"
                b"kubesynth_operator_reconcile_total 0\n"
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def _start_server() -> None:
    try:
        with HTTPServer(("0.0.0.0", _READINESS_PORT), _MockHandler) as httpd:
            logger.info("Mock operator readiness server listening on :%d", _READINESS_PORT)
            httpd.serve_forever()
    except Exception as exc:
        logger.warning("Readiness server failed: %s", exc)


threading.Thread(target=_start_server, daemon=True, name="readiness-server").start()
logger.info("KubeSynth operator running in MOCK mode — no Kubernetes cluster required.")

while True:
    time.sleep(3600)
