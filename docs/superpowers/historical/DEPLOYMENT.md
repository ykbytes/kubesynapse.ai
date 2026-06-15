# Operator Reliability Deployment Guide

## Changes Summary

This deployment includes 10 reliability improvements to the KubeSynapse operator:

### 1. ConfigMap Sync Verification
- SHA-256 hash comparison detects drift between source and mirrored ConfigMaps
- Skips sync if data matches, reducing unnecessary updates
- Adds `kubesynapse.ai/config-hash` and `kubesynapse.ai/synced-at` annotations

### 2. Status Condition Projection
- Patches AIAgent status with `phase`, `conditions[]`, `observedGeneration`, `error`
- Surfaces reconciliation errors in CRD status instead of hiding behind 502s
- Conditions: Ready, Progressing, Degraded, RuntimeHealthy

### 3. Pre-flight Dependency Validation
- Blocks StatefulSet creation if ConfigMaps, Secrets, or ServiceAccount missing
- Sets status to `Failed` with `DependenciesMissing` condition

### 4. Resource Quota Validation
- Checks CPU/memory/pod quotas before creation
- Warns if limits may be exceeded

### 5. Kubernetes Event Recording
- Records events on AIAgent resource visible via `kubectl describe aiagent`
- Events: ReconcileStarted, ReconcileSucceeded, DependenciesMissing, StatefulSetCreated, OrphansPruned

### 6. StatefulSet Revision Tracking
- Computes spec hash, detects changes for rolling restarts
- Logs revision events when spec changes

### 7. Runtime Health Monitoring
- 60s timer checks pod readiness, container statuses
- Detects: CrashLoopBackOff, OOMKilled, ImagePullBackOff, high restart counts

### 8. Credential Proxy Health
- Verifies credential-proxy sidecar is running and ready
- Reports proxy health in status conditions

### 9. API Gateway Connectivity
- Verifies gateway is reachable from operator
- Reports gateway health in status conditions

### 10. Reconciliation Idempotency
- Post-reconcile verification ensures all desired resources exist
- Logs warnings if resources are missing after reconcile

## Deployment Steps

### Prerequisites
1. Docker Desktop must be running
2. kubectl configured with cluster access

### Step 1: Build Operator Image
```bash
cd C:\Users\ahmed\OneDrive\Desktop\repos\agentproject\kubesyn\kubesynapse.ai
docker build -t kubesynapse/kubesynapse-operator:latest ./operator
```

### Step 2: Load Image into Kind (if using Kind)
```bash
kind load docker-image kubesynapse/kubesynapse-operator:latest --name kubesynapse
```

### Step 3: Deploy Updated Operator
```bash
helm upgrade --install kubesynapse ./charts/kubesynapse --namespace kubesynapse --create-namespace --wait --timeout 10m
```

### Step 4: Validate Deployment
```bash
# Check operator pods
kubectl get pods -n kubesynapse -l app=kubesynapse-operator

# Check operator logs
kubectl logs -n kubesynapse -l app=kubesynapse-operator --tail=100

# Check agent status with new conditions
kubectl get aiagent -A
kubectl describe aiagent <agent-name> -n <namespace>
```

### Step 5: Test ConfigMap Sync Verification
```bash
# Delete a ConfigMap to trigger sync verification
kubectl delete configmap kubesynapse-opencode-safe-config -n default

# Watch operator logs for drift detection
kubectl logs -n kubesynapse -l app=kubesynapse-operator --tail=50 -f
```

### Step 6: Validate Status Conditions
```bash
# Check that status conditions are populated
kubectl get aiagent <agent-name> -n <namespace> -o jsonpath='{.status.conditions}'

# Expected output should include:
# - Ready: True/False
# - Progressing: True/False
# - Degraded: True/False
# - RuntimeHealthy: True/False/Unknown
```

## Rollback

If issues occur, rollback to previous operator version:
```bash
helm rollback kubesynapse 1 --namespace kubesynapse
```

## Monitoring

After deployment, monitor:
1. Operator logs for new event recording
2. Agent status conditions for proper projection
3. ConfigMap sync logs for drift detection
4. Health check logs for runtime/proxy/gateway status

## Known Issues

- `test_tenant_isolation.py::test_reconcile_tenant_removes_stale_role_bindings` has a pre-existing module isolation issue unrelated to these changes
- `test_state_store.py` has pre-existing alembic dependency issues
