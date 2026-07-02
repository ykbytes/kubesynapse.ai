"""Checkout API — intentionally broken for incident auto-triage demo.

This app simulates a payment checkout endpoint with a memory leak.
Each /checkout request appends ~10MB to a global list that is never freed.
With a 64Mi memory limit, the pod gets OOMKilled after ~6 requests.
"""

import gc
import os
import time
from datetime import datetime, timezone

from flask import Flask, jsonify

app = Flask(__name__)

# Intentional memory leak — never freed
_memory_leak: list[bytes] = []
_request_count = 0
_start_time = datetime.now(timezone.utc)


@app.route("/health")
def health():
    """Health endpoint — always returns 200 even while leaking."""
    return jsonify({"status": "ok", "requests": _request_count}), 200


@app.route("/checkout", methods=["POST"])
def checkout():
    """Process a checkout request — leaks ~10MB each call."""
    global _request_count
    _request_count += 1

    # Allocate 10MB and intentionally never free it
    chunk = b"\x00" * (10 * 1024 * 1024)
    _memory_leak.append(chunk)

    leaked_mb = len(_memory_leak) * 10
    gc.collect()  # Force GC but the list reference keeps it alive

    return jsonify({
        "status": "success",
        "order_id": f"ORD-{_request_count:06d}",
        "requests_processed": _request_count,
        "leaked_memory_mb": leaked_mb,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


@app.route("/metrics")
def metrics():
    """Prometheus-style metrics endpoint."""
    leaked_mb = len(_memory_leak) * 10
    uptime = (datetime.now(timezone.utc) - _start_time).total_seconds()
    return (
        f"# HELP checkout_requests_total Total checkout requests processed\n"
        f"# TYPE checkout_requests_total counter\n"
        f"checkout_requests_total {_request_count}\n"
        f"# HELP checkout_leaked_memory_bytes Memory leaked in bytes\n"
        f"# TYPE checkout_leaked_memory_bytes gauge\n"
        f"checkout_leaked_memory_bytes {leaked_mb * 1024 * 1024}\n"
        f"# HELP checkout_uptime_seconds Uptime in seconds\n"
        f"# TYPE checkout_uptime_seconds gauge\n"
        f"checkout_uptime_seconds {uptime}\n"
    ), 200, {"Content-Type": "text/plain"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
