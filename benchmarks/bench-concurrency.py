#!/usr/bin/env python3
"""Concurrent Agent Limit Benchmark.

Creates N agents simultaneously and measures the operator's ability
to reconcile them all within acceptable time bounds.

Usage:
    python benchmarks/bench-concurrency.py --namespace kubesynapse --agents 100
    python benchmarks/bench-concurrency.py --agents 200 --batch-size 20
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
DEFAULT_AGENTS = 100
DEFAULT_BATCH_SIZE = 25
RECONCILE_TIMEOUT = 120  # seconds per batch
TOTAL_TIMEOUT = 600  # seconds total

# ── Helpers ────────────────────────────────────────────────────────

def run_kubectl(args: list[str], timeout: int = 30) -> str:
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubectl failed: {result.stderr.strip()}")
    return result.stdout.strip()


def create_batch(names: list[str], namespace: str) -> None:
    """Create a batch of AIAgent CRDs."""
    manifests = []
    for name in names:
        manifests.append({
            "apiVersion": "agents.kubesynapse.ai/v1",
            "kind": "AIAgent",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "policyRef": "default-bench-policy",
                "replicas": 1,
                "resources": {
                    "requests": {"cpu": "50m", "memory": "64Mi"},
                    "limits": {"cpu": "200m", "memory": "128Mi"},
                },
                "config": {"contextWindow": 4096, "sessionTimeout": 600},
            },
        })

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        # Write as YAML-style multi-doc or JSON list
        json.dump({"apiVersion": "v1", "kind": "List", "items": manifests}, f)
        tmp_path = f.name

    try:
        run_kubectl(["apply", "-f", tmp_path])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def count_ready_agents(names: list[str], namespace: str) -> int:
    """Count how many agents have Running pods."""
    try:
        output = run_kubectl([
            "get", "pods", "-n", namespace,
            "-l", "app.kubernetes.io/managed-by=kubesynapse-operator",
            "--field-selector", "status.phase=Running",
            "-o", "json",
        ])
        pods = json.loads(output).get("items", [])
        pod_names = {p["metadata"]["name"] for p in pods}
        # Check which of our agents have running pods
        ready = 0
        for name in names:
            if any(name in pn for pn in pod_names):
                ready += 1
        return ready
    except (RuntimeError, json.JSONDecodeError):
        return 0


def delete_batch(names: list[str], namespace: str) -> None:
    """Delete a batch of agents."""
    for name in names:
        import contextlib
        with contextlib.suppress(RuntimeError):
            run_kubectl([
                "delete", "aiagent", name, "-n", namespace,
                "--ignore-not-found=true",
            ], timeout=10)


# ── Main ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark concurrent agent reconciliation")
    parser.add_argument(
        "--namespace", default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})"
    )
    parser.add_argument(
        "--agents", type=int, default=DEFAULT_AGENTS,
        help=f"Total number of agents to create (default: {DEFAULT_AGENTS})"
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Agents per batch (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    total_agents = args.agents
    batch_size = args.batch_size
    all_names = [f"bench-conc-{i:04d}" for i in range(total_agents)]

    print("=== kubesynapse Concurrent Agent Limit Benchmark ===")
    print(f"Total agents:  {total_agents}")
    print(f"Batch size:    {batch_size}")
    print(f"Batches:       {(total_agents + batch_size - 1) // batch_size}")
    print()

    if args.dry_run:
        print("[DRY RUN] Would create {total_agents} agents in batches of {batch_size}.")
        return

    # Verify operator
    try:
        run_kubectl([
            "get", "pods", "-n", args.namespace,
            "-l", "app.kubernetes.io/component=operator",
            "--field-selector", "status.phase=Running",
        ])
    except RuntimeError:
        print("ERROR: Operator pod not found.", file=sys.stderr)
        sys.exit(1)

    batch_results: list[dict] = []

    for batch_num in range(0, total_agents, batch_size):
        batch_names = all_names[batch_num:batch_num + batch_size]
        batch_idx = batch_num // batch_size + 1
        total_batches = (total_agents + batch_size - 1) // batch_size

        print(f"Batch {batch_idx}/{total_batches}: Creating {len(batch_names)} agents...")
        batch_start = time.monotonic()

        create_batch(batch_names, args.namespace)

        # Wait for reconciliation
        deadline = batch_start + RECONCILE_TIMEOUT
        last_ready = 0
        while time.monotonic() < deadline:
            ready = count_ready_agents(batch_names, args.namespace)
            if ready >= len(batch_names):
                break
            if ready != last_ready:
                print(f"  {ready}/{len(batch_names)} ready...")
                last_ready = ready
            time.sleep(2)

        batch_duration = time.monotonic() - batch_start
        ready_count = count_ready_agents(batch_names, args.namespace)
        success = ready_count >= len(batch_names)

        batch_results.append({
            "batch": batch_idx,
            "agents": len(batch_names),
            "ready": ready_count,
            "duration_s": round(batch_duration, 2),
            "success": success,
        })

        status = "✅" if success else f"⚠️ ({ready_count}/{len(batch_names)})"
        print(f"  Done: {status} in {batch_duration:.1f}s\n")

    # Cleanup all
    print(f"Cleaning up {total_agents} agents...")
    for i in range(0, total_agents, batch_size):
        delete_batch(all_names[i:i + batch_size], args.namespace)

    # Summary
    durations = [b["duration_s"] for b in batch_results]
    successful = sum(1 for b in batch_results if b["success"])

    print("\n=== Results ===")
    print(f"Batches:        {len(batch_results)}")
    print(f"Successful:     {successful}/{len(batch_results)}")
    print(f"Total duration: {sum(durations):.1f}s")
    print(f"P50 per batch:  {statistics.median(durations):.1f}s")
    print(f"Max per batch:  {max(durations):.1f}s")
    print()

    if successful == len(batch_results) and statistics.median(durations) <= 30:
        print(f"✅ {total_agents} agents reconciled — median batch under 30s.")
    else:
        print("⚠️  Results may need investigation. Check operator logs.")

    # Export
    report = {
        "test": "concurrent-agent-limit",
        "total_agents": total_agents,
        "batch_size": batch_size,
        "batches": len(batch_results),
        "batches_successful": successful,
        "total_duration_s": round(sum(durations), 1),
        "median_batch_duration_s": round(statistics.median(durations), 1),
        "max_batch_duration_s": round(max(durations), 1),
        "details": batch_results,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
