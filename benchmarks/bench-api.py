#!/usr/bin/env python3
"""API Gateway Throughput Benchmark.

Measures requests/sec, latency distribution, and error rate against
the kubesynapse API gateway using concurrent HTTP clients.

Usage:
    python benchmarks/bench-api.py --url http://localhost:8080 --concurrency 10 --duration 30
    python benchmarks/bench-api.py --url https://kubesynapse.example.com --token $TOKEN
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
import urllib.request
from typing import Any

# ── Helpers ────────────────────────────────────────────────────────

def make_request(
    url: str,
    endpoint: str,
    token: str | None = None,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 10,
) -> tuple[float, int, bool]:
    """Make a single HTTP request, return (latency_seconds, status_code, success)."""
    full_url = f"{url.rstrip('/')}{endpoint}"
    req = urllib.request.Request(full_url, method=method)  # noqa: S310

    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")

    if body:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
        req.data = data

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            _ = resp.read()
            status = resp.status
            success = 200 <= status < 300
    except urllib.error.HTTPError as e:
        status = e.code
        success = False
    except Exception:
        status = 0
        success = False

    latency = time.monotonic() - start
    return (latency, status, success)


def run_worker(
    worker_id: int,
    url: str,
    endpoints: list[str],
    token: str | None,
    duration: float,
    results: list[tuple[float, int, bool]],
) -> None:
    """Worker thread: hammer the API for the given duration."""
    deadline = time.monotonic() + duration
    idx = 0
    while time.monotonic() < deadline:
        endpoint = endpoints[idx % len(endpoints)]
        idx += 1
        latency, status, success = make_request(url, endpoint, token)
        results.append((latency, status, success))


# ── Main ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark API gateway throughput")
    parser.add_argument(
        "--url", default="http://localhost:8080",
        help="API gateway base URL (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--concurrency", type=int, default=10,
        help="Number of concurrent workers (default: 10)"
    )
    parser.add_argument(
        "--duration", type=int, default=30,
        help="Test duration in seconds (default: 30)"
    )
    parser.add_argument(
        "--token", default=None,
        help="Bearer token for authenticated endpoints"
    )
    args = parser.parse_args()

    # Endpoints to test (mix of read-heavy and authenticated)
    endpoints = [
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/agents",
    ]

    print("=== kubesynapse API Gateway Benchmark ===")
    print(f"URL:         {args.url}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Duration:    {args.duration}s")
    print(f"Endpoints:   {', '.join(endpoints)}")
    print()

    # Warmup
    print("Warming up...")
    for ep in endpoints:
        make_request(args.url, ep, args.token, timeout=5)
    print("Warmup complete.\n")

    # Run benchmark
    results: list[tuple[float, int, bool]] = []
    start = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = []
        for i in range(args.concurrency):
            f = pool.submit(
                run_worker, i, args.url, endpoints, args.token, args.duration, results
            )
            futures.append(f)

        # Progress indicator
        while time.monotonic() - start < args.duration:
            elapsed = time.monotonic() - start
            reqs = len(results)
            rps = reqs / elapsed if elapsed > 0 else 0
            print(f"\r  Running... {reqs} requests, {rps:.0f} req/s", end="")
            time.sleep(1)

        concurrent.futures.wait(futures)

    elapsed = time.monotonic() - start
    print(f"\r  Complete: {len(results)} requests in {elapsed:.1f}s         ")

    # Results
    if not results:
        print("\nERROR: No requests completed.", file=sys.stderr)
        sys.exit(1)

    latencies = [r[0] for r in results]
    successes = [r for r in results if r[2]]
    errors = [r for r in results if not r[2]]

    latencies.sort()
    rps = len(results) / elapsed

    def pct(data: list[float], n: int) -> float:
        if len(data) < n:
            return max(data) if data else 0
        return statistics.quantiles(data, n=n)[n - 1]

    p50 = statistics.median(latencies)
    p95 = pct(latencies, 20) if len(latencies) >= 20 else max(latencies)
    p99 = pct(latencies, 100) if len(latencies) >= 100 else max(latencies)

    print("\n=== Results ===")
    print(f"Total requests:  {len(results)}")
    print(f"Duration:        {elapsed:.1f}s")
    print(f"Throughput:      {rps:.0f} req/s")
    print(f"Success rate:    {len(successes) / len(results) * 100:.1f}%")
    print(f"Error count:     {len(errors)}")
    print()
    print(f"P50 latency:     {p50 * 1000:.1f}ms")
    print(f"P95 latency:     {p95 * 1000:.1f}ms")
    print(f"P99 latency:     {p99 * 1000:.1f}ms")
    print(f"Mean latency:    {statistics.mean(latencies) * 1000:.1f}ms")
    print()

    # Export JSON for CI
    report: dict[str, Any] = {
        "test": "api-gateway-throughput",
        "url": args.url,
        "concurrency": args.concurrency,
        "duration_seconds": round(elapsed, 1),
        "total_requests": len(results),
        "throughput_rps": round(rps, 1),
        "success_rate_pct": round(len(successes) / len(results) * 100, 1),
        "error_count": len(errors),
        "latency_p50_ms": round(p50 * 1000, 1),
        "latency_p95_ms": round(p95 * 1000, 1),
        "latency_p99_ms": round(p99 * 1000, 1),
        "latency_mean_ms": round(statistics.mean(latencies) * 1000, 1),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
