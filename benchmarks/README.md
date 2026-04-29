# KubeSynapse Performance Benchmarks

Reproducible performance benchmarks for the KubeSynapse platform.

## Prerequisites

- A running KubeSynapse installation (operator, API gateway, etc.)
- `kubectl` configured for the cluster
- Python 3.11+

## Benchmarks

### 1. Operator Reconciliation Latency

Measures how long the operator takes to reconcile AIAgent CRDs into running StatefulSets.

```bash
python benchmarks/bench-reconcile.py --namespace kubesynapse --count 100
```

**Metrics:** P50, P95, P99 reconciliation latency (seconds)  
**Baseline target:** P95 under 30 seconds for 100 agents

### 2. API Gateway Throughput

Measures the API gateway's request handling capacity under concurrent load.

```bash
python benchmarks/bench-api.py \
  --url http://localhost:8080 \
  --concurrency 10 \
  --duration 30
```

**Metrics:** requests/sec, P50/P95/P99 latency, success rate  
**Baseline target:** ≥ 500 req/s with < 1% error rate

### 3. Concurrent Agent Limit

Measures the operator's ability to handle large numbers of simultaneous agent creations.

```bash
python benchmarks/bench-concurrency.py --namespace kubesynapse --agents 200 --batch-size 20
```

**Metrics:** batch success rate, median reconciliation time per batch  
**Baseline target:** 200 agents reconciled, median batch under 30s

## Running in CI

All benchmarks accept `--dry-run` for validation without execution:

```bash
python benchmarks/bench-reconcile.py --dry-run
python benchmarks/bench-api.py --dry-run
python benchmarks/bench-concurrency.py --dry-run
```

## Interpreting Results

| Metric | Green | Yellow | Red |
|--------|-------|--------|-----|
| Operator P95 reconcile | < 30s | 30-60s | > 60s |
| API throughput | > 500 req/s | 200-500 req/s | < 200 req/s |
| API P95 latency | < 500ms | 500-2000ms | > 2000ms |
| Concurrent agent success | 100% | ≥ 95% | < 95% |

## Export Format

All benchmarks output a JSON report on stdout for CI integration:

```json
{
  "test": "operator-reconciliation",
  "count": 100,
  "p50": 1.2,
  "p95": 4.8,
  "p99": 12.3
}
```
