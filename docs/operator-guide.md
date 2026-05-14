# KubeSynapse Operator Guide

**Who is this for:** Platform engineers, SREs, and cluster operators responsible for running KubeSynapse in production.

This guide covers monitoring, alerting, scaling, upgrades, backups, troubleshooting, and capacity planning.

---

## Table of Contents

- [Monitoring](#monitoring)
- [Run Intelligence Layer](#run-intelligence-layer)
- [Alerting](#alerting)
- [Scaling](#scaling)
- [Upgrades](#upgrades)
- [Backup and Restore](#backup-and-restore)
- [Troubleshooting the Operator](#troubleshooting-the-operator)
- [Security Maintenance](#security-maintenance)
- [Capacity Planning](#capacity-planning)

---

## Monitoring

### What to Watch

| Metric Category | Key Indicator | Why It Matters |
|-----------------|---------------|----------------|
| **Control Plane** | Operator reconciliation latency | Slow reconciliation = delayed agent provisioning |
| **Control Plane** | CRD watch errors | Losing watch = stale state |
| **Execution Plane** | Agent pod restarts | Runtime instability or OOM |
| **Execution Plane** | Worker job duration | Workflow runs hanging or failing |
| **Gateway** | HTTP request latency P99 | User-facing performance |
| **Gateway** | Auth failure rate | Brute force or IdP issues |
| **LLM** | LiteLLM error rate | Provider outages or misconfiguration |
| **LLM** | Token utilization per agent | Cost control |

### Key Prometheus Queries

**Operator reconciliation rate:**

```promql
rate(KubeSynapse_operator_reconciliations_total[5m])
```

**Agent pod restarts:**

```promql
increase(kube_pod_container_status_restarts_total{namespace=~".*"}[1h])
```

**Gateway P99 latency:**

```promql
histogram_quantile(0.99,
  rate(http_request_duration_seconds_bucket{job="kubesynapse-api-gateway"}[5m])
)
```

**LiteLLM error rate:**

```promql
rate(litellm_request_errors_total[5m])
```

**Active approvals (pending human decision):**

```promql
KubeSynapse_approvals_pending_total{namespace=~".*"}
```

### Grafana Dashboards

The project ships three curated dashboards in `deploy/grafana/dashboards/`:

| Dashboard | File | Purpose |
|-----------|------|---------|
| Agent Overview | `agent-overview.json` | Health, pod status, resource usage, reconciliation rates |
| Workflow Execution | `workflow-execution.json` | Runs, step duration, failure rates, queue depth |
| LLM Usage | `llm-usage.json` | Token rate, cost, latency per model, provider errors |

Import them via ConfigMap or Grafana UI.

---

## Run Intelligence Layer

The Run Intelligence Layer provides semantic event indexing, deterministic anomaly detection, and AI-powered analysis across all runtimes.

### Signal Watch Controller

The operator runs a periodic anomaly detection controller (`controllers/signal_watch.py`) that executes deterministic SQL checks against the `runtime_run_events` and `workflow_executions` tables.

**Schedule:** Every 60 seconds (configurable via `SIGNAL_WATCH_INTERVAL_SEC`)

**Anomaly Checks:**

| Check | SQL Query | Threshold | Default |
|---|---|---|---|
| High failure rate | `failed_steps / total_steps >= threshold` | 30% | `SIGNAL_WATCH_FAILURE_RATE=0.3` |
| Error spikes | `COUNT(*) WHERE severity='error' >= threshold` | 3 errors in 15m | `SIGNAL_WATCH_ERROR_COUNT=3` |
| Cost outliers | `cost_usd / avg_cost >= multiplier` | 3x namespace avg | `SIGNAL_WATCH_COST_MULTIPLIER=3.0` |
| Token spikes | `total_tokens / avg_tokens >= multiplier` | 3x agent avg | `SIGNAL_WATCH_TOKEN_MULTIPLIER=3.0` |
| Stuck runs | `duration_ms / median_ms >= multiplier` | 2x median duration | `SIGNAL_WATCH_STUCK_MULTIPLIER=2.0` |

**Output:** When a check fires, an `ObservationReport` CR is created with:
- Severity classification (low, medium, high, critical)
- Affected execution IDs
- Detailed metrics and timestamps

### System Agents

Three predefined AIAgent CRs provide AI-powered analysis on top of deterministic detection:

| Agent | Purpose | Invoked When |
|---|---|---|
| `ks-run-inspector` | Root-cause analysis of failed runs | Failure rate > 30% or >= 3 errors |
| `ks-signal-summarizer` | Converts anomaly signals to incident briefs | Any anomaly signal fires |
| `ks-spend-reviewer` | Reviews cost/token anomalies | Cost > $10 or tokens > 3x average |

**Configuration:** Set via Helm values under `systemAgents`:

```yaml
systemAgents:
  enabled: true
  namespace: "kubesynapse-system"
  defaultModel: "gpt-4"
  runInspector:
    enabled: true
    triggers:
      minFailureRate: 0.3
      minErrorCount: 3
```

### Troubleshooting

**Signal watch not running:**
```bash
# Check controller is loaded
kubectl logs -l app=kubesynapse-operator -c operator | grep signal-watch

# Verify env vars
kubectl get deployment kubesynapse-operator -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SIGNAL_WATCH_INTERVAL_SEC")].value}'
```

**ObservationReports not created:**
```bash
# Check for SQL errors
kubectl logs -l app=kubesynapse-operator -c operator | grep "signal watch"

# Verify database connectivity
kubectl exec -it deploy/kubesynapse-api-gateway -- python -c "from auth_store import ENGINE; print(ENGINE)"
```

**System agents not invoked:**
```bash
# Check system agent CRs exist
kubectl get aiagents -n kubesynapse-system

# Verify A2A allowed callers
kubectl get aiagent ks-run-inspector -n kubesynapse-system -o jsonpath='{.spec.a2a}'
```

---

## Alerting

### Prometheus Alert Rules

Deploy `deploy/prometheus/rules.yaml` to your Prometheus instance. Key rules:

| Alert | Severity | Meaning | Runbook |
|-------|----------|---------|---------|
| `KubeSynapseAgentPodDown` | Critical | Agent runtime pod not ready for > 5 min | Check pod events, OOM, image pull |
| `KubeSynapseWorkflowFailureRateHigh` | Warning | > 5% workflow steps failing | Inspect worker logs, artifacts |
| `KubeSynapseApiErrorRateHigh` | Critical | Gateway error rate > 1% | Check gateway logs, DB connectivity |
| `KubeSynapseLiteLLMUnhealthy` | Critical | LiteLLM health endpoint failing | Verify provider keys, LiteLLM logs |
| `KubeSynapseStepTimeoutRateHigh` | Warning | > 10% steps timing out | Increase worker deadline, check LLM latency |

### Alertmanager Routing Suggestions

```yaml
route:
  group_by: ['alertname', 'namespace']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'platform-team'
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-platform'
    - match:
        alertname: KubeSynapseLiteLLMUnhealthy
      receiver: 'ml-ops-oncall'
```

---

## Scaling

### Horizontal Scaling

| Component | Scaling Method | Notes |
|-----------|----------------|-------|
| **API Gateway** | HPA on CPU/memory | Stateless; scale to 3+ for HA |
| **Operator** | Static replicas + leader election | Kopf handles leader election; 2-3 replicas safe |
| **LiteLLM** | HPA on request rate | Cache-aware; scale with concurrency |
| **Agent Runtimes** | Per-agent StatefulSet | Each agent is singleton; scale vertically |
| **Web UI** | HPA on CPU | Static content; scale freely |

**Example HPA for Gateway:**

```yaml
# values-production.yaml
autoscaling:
  enabled: true
  apiGateway:
    minReplicas: 3
    maxReplicas: 20
    targetCPUUtilizationPercentage: 70
```

### Vertical Scaling for Agents

Agents are singleton StatefulSets. Increase resources per agent:

```yaml
agentRuntime:
  resources:
    requests:
      cpu: "1"
      memory: "2Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
```

**GPU support:** Set `runtimeClassName: nvidia` in agent spec and ensure GPU nodes are available.

### Tenant Automation and Dedicated User Namespaces

The operator's tenant controller now matters even for admin user CRUD, not just manually created tenant manifests.

Current behavior:

- the API gateway can reconcile a cluster-scoped `AgentTenant` named `user-<slug>` when an admin creates or updates a non-admin local user
- the tenant controller materializes the target namespace, quota objects, limit ranges, and tenant RBAC for that dedicated namespace
- when `adminUsers` membership changes, the controller removes stale tenant-managed RoleBindings instead of leaving orphaned access behind

Operational checks:

```bash
kubectl get agenttenants
kubectl get rolebindings -n user-alice-user
kubectl describe agenttenant user-alice-user
```

If a user namespace is missing after admin user creation, inspect both the gateway logs and the operator logs:

```bash
kubectl logs -n kubesynapse deploy/kubesynapse-api-gateway
kubectl logs -n kubesynapse deploy/kubesynapse-operator
```

---

## Upgrades

### Helm Upgrade Procedure

1. **Review the changelog:**

   ```bash
   curl -sL https://github.com/ykbytes/kubesynapse.ai/releases/latest
   ```

2. **Backup critical state:**

   ```bash
   kubectl exec -n kubesynapse deploy/kubesynapse-api-gateway -- \
     sh -c 'cp /data/auth.db /backups/auth.db.$(date +%s)'
   ```

3. **Upgrade the chart:**

   ```bash
   helm upgrade KubeSynapse oci://docker.io/kubesynapse/charts/kubesynapse \
     -n kubesynapse -f values-production.yaml
   ```

4. **Verify CRD changes:**

   ```bash
   kubectl get crds | grep KubeSynapse
   ```

5. **Smoke test:**

   ```bash
  curl -f http://localhost:8080/api/v1/health
   agentctl health
   ```

### CRD Migration Notes

- Helm does **not** automatically remove old CRD versions
- Before upgrading, check if new CRD fields are required
- If a CRD schema changes, existing resources may need manual patching:

  ```bash
  kubectl patch aiagent old-agent -n default --type merge \
    -p '{"spec":{"newField":"defaultValue"}}'
  ```

- Major version upgrades (e.g., 1.x to 2.x) may require a migration job

---

## Backup and Restore

### What to Backup

| Data | Location | Backup Method | Frequency |
|------|----------|---------------|-----------|
| **Auth database** | Gateway PVC or external PostgreSQL | `pg_dump` or snapshot | Daily |
| **Agent state PVCs** | Per-agent StatefulSet | Velero or CSI snapshot | Daily |
| **CRD manifests** | Kubernetes etcd | `kubectl get` + YAML export | Before upgrades |
| **Worker artifacts** | Artifact PVC | Velero or S3 sync | After each run |
| **Trace data** | Trace storage dir | Filesystem backup | Daily |
| **LiteLLM config** | PostgreSQL | `pg_dump` | Daily |

### Backup Script Example

```bash
#!/bin/bash
NAMESPACE=KubeSynapse
DATE=$(date +%Y%m%d-%H%M%S)

# Auth DB
kubectl exec -n $NAMESPACE deploy/kubesynapse-api-gateway -- \
  sh -c 'sqlite3 /data/auth.db .dump' > auth-db-$DATE.sql

# CRDs
for crd in aiagents agentworkflows agentpolicies agentapprovals agenttenants; do
  kubectl get $crd --all-namespaces -o yaml > $crd-$DATE.yaml
done

# Agent state PVCs (using Velero)
velero backup create KubeSynapse-agents-$DATE \
  --selector app.kubernetes.io/part-of=KubeSynapse
```

### Restore Procedure

1. Restore CRDs first so the operator can reconcile
2. Restore auth database to the gateway
3. Restore agent PVCs so memory and state are preserved
4. Verify agent pods restart and reconnect

---

## Troubleshooting the Operator

### Common Failure Modes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Operator pod CrashLoopBackOff | Missing RBAC permissions | Check ClusterRoleBindings, verify `kubesynapse-operator-sa` |
| Reconciliation stuck | K8s API rate limiting | Increase QPS/burst in operator config, check API server health |
| Agent StatefulSet not created | Invalid agent spec | Check `kubectl describe aiagent`, review validation errors |
| Workflow jobs not spawning | Worker resource quota exceeded | Increase namespace quotas or reduce worker CPU/memory requests |
| Approval not resolving | Operator not watching approvals | Restart operator, check `AgentApproval` CRD is installed |
| Observability reports missing | Observability CRDs not registered | Verify CRDs installed, check operator logs for controller registration |

### Operator Debug Commands

```bash
# Operator logs
kubectl logs -n kubesynapse deployment/kubesynapse-operator -f

# Recent events
kubectl get events -n kubesynapse --sort-by='.lastTimestamp' | tail -20

# Reconciliation latency
kubectl logs -n kubesynapse deployment/kubesynapse-operator | grep "reconcile"

# Leader election status
kubectl get leases -n kubesynapse

# Describe a stuck agent
kubectl describe aiagent my-agent -n default
kubectl describe statefulset my-agent -n default
```

---

## Security Maintenance

### Rotating Secrets

| Secret | Rotation Method | Impact |
|--------|-----------------|--------|
| **JWT signing key** | `kubectl rollout restart deploy/kubesynapse-api-gateway` | Users must re-login |
| **LLM API keys** | Update ExternalSecret or Helm values | No downtime if using External Secrets Operator |
| **Database password** | Update Helm values, restart gateway | Brief DB reconnect |
| **MCP auth tokens** | Rotate `mcp-auth` secret, restart affected agents | Agents restart one by one |

**Automated rotation with External Secrets Operator:**

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: KubeSynapse-litellm-key
  namespace: KubeSynapse
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-backend
  target:
    name: litellm-master-key
  data:
    - secretKey: api-key
      remoteRef:
        key: secret/data/KubeSynapse/litellm
        property: api-key
```

### Updating Policies

When security requirements change:

1. Update `AgentPolicy` CRDs with new guardrails
2. The operator propagates changes to runtime ConfigMaps
3. Runtime pods auto-reload policy without restart (if supported)
4. For immediate effect, restart the agent StatefulSet

---

## Capacity Planning

### Resource Baselines

| Component | Request CPU | Request Memory | Limit CPU | Limit Memory | Typical Pods |
|-----------|-------------|----------------|-----------|--------------|--------------|
| API Gateway | 500m | 1Gi | 4 | 4Gi | 3 |
| Operator | 500m | 1Gi | 2 | 4Gi | 2 |
| LiteLLM | 500m | 2Gi | 4 | 8Gi | 2 |
| PostgreSQL | 500m | 1Gi | 2 | 4Gi | 1 |
| Per-Agent Runtime | 500m | 1Gi | 4 | 8Gi | 1 per agent |
| Worker Job | 500m | 512Mi | 2 | 2Gi | Ephemeral |

### Per-Agent Overhead

Each `AIAgent` creates:

- 1 StatefulSet (1 pod)
- 1 Service
- 1 PVC (default 1Gi, configurable)
- 1 ConfigMap (runtime config)
- Optional: MCP sidecar containers

**Rule of thumb:** Plan for **1 CPU core and 2Gi memory** per active agent, including overhead.

### Storage Planning

| Storage Type | Default Size | Growth Driver |
|--------------|--------------|---------------|
| Agent state PVC | 1Gi per agent | Memory JSONL files, artifacts |
| PostgreSQL | 10Gi | Auth records, usage data, chat history |
| Trace storage | 10Gi | Workflow execution traces |
| Worker artifacts | 2Gi per job | Evaluation outputs, workflow logs |

**Recommendation:** Use a `fast-ssd` StorageClass for PostgreSQL and trace storage to keep query latency low.

### Network Planning

| Traffic Pattern | Bandwidth | Notes |
|-----------------|-----------|-------|
| Gateway to runtime | Low | JSON payloads, typically < 1MB |
| Runtime to LiteLLM | Medium | LLM requests/responses |
| Runtime to Qdrant | Low | Vector queries |
| LiteLLM to providers | High | Streaming tokens, model weights not transferred |

Enable **NetworkPolicy** in production to restrict unnecessary egress.

---

**Last Updated:** April 27, 2026  
**Platform Version:** 1.0.0
