#!/usr/bin/env python3
"""Operator Reconciliation Benchmark.

Measures operator reconcile latency (P50, P95, P99) by creating and
timing synthetic CRD resources against a live kubesynapse operator.

Usage:
    python benchmarks/bench-reconcile.py --namespace kubesynapse --count 100
    python benchmarks/bench-reconcile.py --namespace kubesynapse --count 50 --timeout 300
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────

DEFAULT_NAMESPACE = "kubesynapse"
DEFAULT_COUNT = 50
DEFAULT_TIMEOUT = 300  # seconds
RECONCILE_TIMEOUT = 60  # seconds per agent

# ── Helpers ────────────────────────────────────────────────────────

def run_kubectl(args: list[str], timeout: int = 30) -> str:
    """Run kubectl and return stdout, raise on failure."""
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubectl failed: {result.stderr.strip()}")
    return result.stdout.strip()


def wait_for_agent_ready(name: str, namespace: str) -> float:
    """Wait for an agent to be ready, return reconcile duration in seconds."""
    start = time.monotonic()
    deadline = start + RECONCILE_TIMEOUT

    while time.monotonic() < deadline:
        try:
            output = run_kubectl([
                "get", "statefulset", name,
                "-n", namespace,
                "-o", "jsonpath={.status.readyReplicas}",
            ])
            if output == "1":
                return time.monotonic() - start
        except RuntimeError:
            pass
        time.sleep(0.5)

    raise TimeoutError(f"Agent {name} did not become ready within {RECONCILE_TIMEOUT}s")


def create_test_agent(index: int, namespace: str) -> str:
    """Create a test AIAgent CRD and return its name."""
    name = f"bench-agent-{index:04d}"
    manifest = {
        "apiVersion": "agents.kubesynapse.ai/v1",
        "kind": "AIAgent",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "spec": {
            "policyRef": "default-bench-policy",
            "replicas": 1,
            "resources": {
                "requests": {"cpu": "50m", "memory": "64Mi"},
                "limits": {"cpu": "200m", "memory": "128Mi"},
            },
            "config": {"contextWindow": 4096, "sessionTimeout": 600},
        },
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(manifest, f)
        tmp_path = f.name

    try:
        run_kubectl(["apply", "-f", tmp_path])
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return name


def delete_test_agent(name: str, namespace: str) -> None:
    """Delete a test AIAgent CRD."""
    import contextlib
    with contextlib.suppress(RuntimeError):
        run_kubectl(["delete", "aiagent", name, "-n", namespace, "--ignore-not-found=true"])


# ── Main ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark operator reconciliation latency")
    parser.add_argument(
        "--namespace", default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})"
    )
    parser.add_argument(
        "--count", type=int, default=DEFAULT_COUNT,
        help=f"Number of agents to create and reconcile (default: {DEFAULT_COUNT})"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Total test timeout in seconds (default: {DEFAULT_TIMEOUT})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned actions without executing"
    )
    args = parser.parse_args()

    print("=== kubesynapse Operator Reconciliation Benchmark ===")
    print(f"Namespace: {args.namespace}")
    print(f"Agent count: {args.count}")
    print(f"Timeout: {args.timeout}s")
    print()

    if args.dry_run:
        print("[DRY RUN] Would create and reconcile {args.count} agents.")
        return

    # Verify operator is running
    try:
        run_kubectl([
            "get", "pods", "-n", args.namespace,
            "-l", "app.kubernetes.io/component=operator",
            "--field-selector", "status.phase=Running",
            "-o", "name",
        ])
    except RuntimeError:
        print("ERROR: Operator pod not found. Is kubesynapse deployed?", file=sys.stderr)
        sys.exit(1)

    latencies: list[float] = []
    created: list[str] = []

    print(f"Creating {args.count} agents...")

    for i in range(args.count):
        name = create_test_agent(i, args.namespace)
        created.append(name)
        if (i + 1) % 10 == 0:
            print(f"  Created {i + 1}/{args.count} agents")

    print("\nMeasuring reconciliation latency...")

    deadline = time.monotonic() + args.timeout
    for i, name in enumerate(created):
        if time.monotonic() > deadline:
            print(f"  TIMEOUT: Only reconciled {i}/{args.count} agents")
            break
        try:
            latency = wait_for_agent_ready(name, args.namespace)
            latencies.append(latency)
        except TimeoutError:
            print(f"  WARNING: Agent {name} did not reconcile in time")
            latencies.append(RECONCILE_TIMEOUT)
        if (i + 1) % 10 == 0:
            print(f"  Reconciled {i + 1}/{args.count} agents")

    # Cleanup
    print(f"\nCleaning up {len(created)} agents...")
    for name in created:
        delete_test_agent(name, args.namespace)

    # Results
    if not latencies:
        print("\nERROR: No reconciliation latencies recorded.", file=sys.stderr)
        sys.exit(1)

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)

    print("\n=== Results ===")
    print(f"Count:    {len(latencies)}")
    print(f"P50:      {p50:.2f}s")
    print(f"P95:      {p95:.2f}s")
    print(f"P99:      {p99:.2f}s")
    print(f"Mean:     {statistics.mean(latencies):.2f}s")
    print(f"Min:      {min(latencies):.2f}s")
    print(f"Max:      {max(latencies):.2f}s")
    print()

    # Baseline assertion (informational)
    if p95 <= 30:
        print("✅ P95 reconciliation under 30s — meets baseline target.")
    else:
        print(f"⚠️  P95 reconciliation ({p95:.2f}s) exceeds 30s baseline. Investigate.")

    # Export JSON for CI
    results = {
        "test": "operator-reconciliation",
        "count": len(latencies),
        "p50": round(p50, 3),
        "p95": round(p95, 3),
        "p99": round(p99, 3),
        "mean": round(statistics.mean(latencies), 3),
        "min": round(min(latencies), 3),
        "max": round(max(latencies), 3),
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
