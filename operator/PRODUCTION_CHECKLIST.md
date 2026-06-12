"""Production Operator Checklist and Operational Runbook.

Complete verification steps to ensure KubeSynapse operator meets production
readiness requirements from the hardening audit.
"""

# ============================================================================
# SECTION 1: Pre-Deployment Verification (§1 - Security)
# ============================================================================

## 1.1 Container Security (§1.1)
- [ ] Dockerfile uses non-root user (operator:999)
- [ ] Verify: `docker run --rm -it kubesynapse-operator:latest id`
  Expected: uid=999(operator) gid=999(operator) groups=999(operator)
- [ ] Dockerfile is multi-stage build (builder + runtime)
- [ ] Verify: `docker inspect kubesynapse-operator:latest | grep -i size`
  Expected: Image size < 500MB (slim base + minimal runtime deps)

## 1.2 Environment Variable Audit (§1.2)
- [ ] DATABASE_PASSWORD NOT in deployment env vars (uses secretKeyRef)
- [ ] Verify: `kubectl get deployment -n kubesynapse -o yaml | grep -i password`
  Expected: No plaintext password found (only secretKeyRef)
- [ ] All sensitive values use `valueFrom: secretKeyRef`
- [ ] Database credentials secret exists: `kubectl get secret -n kubesynapse kubesynapse-db-credentials`

## 1.3 RBAC Configuration (§1.3)
- [ ] ClusterRole created: `kubectl get clusterrole kubesynapse-operator`
- [ ] Role contains only necessary permissions (not cluster-admin)
- [ ] Verify limited scope: `kubectl get clusterrole kubesynapse-operator -o yaml`
  Expected: Resources limited to kubesynapse.ai group + core K8s resources needed
- [ ] ClusterRoleBinding exists and binds to correct service account
- [ ] Test RBAC enforcement: Create test manifest with forbidden resource access
  Expected: Forbidden error after reconciliation

## 1.4 Input Validation (§1.4)
- [ ] validation.py module present in operator/ folder
- [ ] Verify: `python -c "from operator.validation import validate_resource_name"`
  Expected: Import successful, no errors
- [ ] constants.py module present with all magic values extracted
- [ ] Test validation: Deploy agent with invalid name "invalid-name!"
  Expected: CRD validation error, not operator crash

## 1.5 Network Policies (§1.5)
- [ ] NetworkPolicy deployed: `kubectl get networkpolicy -n kubesynapse`
- [ ] Operator can reach PostgreSQL:
  Test: `kubectl port-forward svc/kubesynapse-postgresql -n kubesynapse 5432:5432`
  Then: `psql -h localhost -U kubesynapse -d kubesynapse`
- [ ] Operator can reach Kubernetes API: `kubectl top nodes` from operator pod
- [ ] Operator cannot reach other namespaces:
  Test: Deploy dummy pod in different namespace, verify no connectivity

# ============================================================================
# SECTION 2: Pre-Deployment Verification (§2 - Reliability)
# ============================================================================

## 2.1 Graceful Shutdown (§2.1)
- [ ] _handle_shutdown_signal() present in main.py
- [ ] SIGTERM/SIGINT signal handlers registered
- [ ] Test shutdown:
  1. `kubectl port-forward -n kubesynapse pod/kubesynapse-operator-xxx 8080:8080 &`
  2. `curl http://localhost:8080/healthz`  → Should return 200 with `"ready": true`
  3. `kubectl delete pod -n kubesynapse kubesynapse-operator-xxx`
  4. `curl http://localhost:8080/healthz` → Should return 503 briefly during shutdown
  5. Pod restarts: `kubectl get pods -n kubesynapse -w`

## 2.2 Health Check Endpoint (§2.2)
- [ ] /healthz endpoint implemented in main.py
- [ ] Health check server runs on port 8080
- [ ] Test endpoint:
  1. `kubectl port-forward -n kubesynapse svc/kubesynapse-operator 8080:8080`
  2. `curl http://localhost:8080/healthz | jq .`
  Expected response: `{"status": "ok", "ready": true}`
- [ ] Deployment includes liveness/readiness probes for /healthz
- [ ] Verify probes: `kubectl get deployment -n kubesynapse -o yaml | grep -A 20 livenessProbe`

## 2.3 Database Connection Pool (§2.3)
- [ ] Enhanced pool configuration in state_store.py:
  - pool_size: 15 ✓
  - max_overflow: 30 ✓
  - pool_timeout: 30 ✓
  - pool_recycle: 1800 ✓
  - Connection timeout: 10s ✓
- [ ] Test pool under load:
  1. Scale workers: `kubectl scale deployment kubesynapse-worker -n kubesynapse --replicas=10`
  2. Monitor operator logs: `kubectl logs -n kubesynapse -f -l app=kubesynapse-operator`
  3. Expected: No connection pool errors, no timeouts
  4. Scale back: `kubectl scale deployment kubesynapse-worker -n kubesynapse --replicas=1`

## 2.4 Error Classification (§2.4)
- [ ] Enhanced classify_reconcile_error() in reconcile.py
- [ ] Handles OperationalError and SQLAlchemyError
- [ ] Handles CircuitBreakerOpen with 60s backoff
- [ ] Implements transient DB keyword detection
- [ ] Test error classification:
  1. Stop PostgreSQL: `kubectl delete pod -n kubesynapse kubesynapse-postgresql-0`
  2. Trigger agent reconciliation (create/update agent)
  3. Operator logs should show: "transient DB error" + exponential backoff
  4. Expected outcome: Operator retries with increasing delays (30s, 60s, 120s...)
  5. Restart PostgreSQL when ready
  6. Operator should eventually succeed

## 2.5 Request Context Propagation (§2.5)
- [ ] REQUEST_ID context variable defined in main.py
- [ ] StructuredFormatter adds request_id to all logs
- [ ] Test structured logging:
  1. `kubectl logs -n kubesynapse -f -l app=kubesynapse-operator | grep request_id`
  2. Expected output: Every log line includes `[request_id]` field
  3. All logs for same request should share same request_id

# ============================================================================
# SECTION 3: Deployment Verification
# ============================================================================

## 3.1 Pod Deployment Status
- [ ] Operator pod running: `kubectl get pod -n kubesynapse -l app=kubesynapse-operator`
  Expected: 1/1 Running
- [ ] No warnings/errors: `kubectl describe pod -n kubesynapse -l app=kubesynapse-operator`
- [ ] Resource limits applied: `kubectl get pod -n kubesynapse -o yaml | grep -A 5 resources`
  Expected: requests (cpu: 200m, memory: 512Mi), limits (cpu: 1000m, memory: 2Gi)

## 3.2 Security Context Verification
- [ ] Pod runs as non-root:
  `kubectl exec -n kubesynapse -it $(kubectl get pod -n kubesynapse -l app=kubesynapse-operator -o jsonpath='{.items[0].metadata.name}') -- id`
  Expected: uid=999(operator) gid=999(operator)
- [ ] No privileged capabilities:
  `kubectl get pod -n kubesynapse -o jsonpath='{.items[0].spec.securityContext}'`
  Expected: allowPrivilegeEscalation=false, capabilities.drop=[ALL]
- [ ] Read-only filesystem:
  Test: `kubectl exec -n kubesynapse ... -- touch /app/test`
  Expected: Read-only file system error

## 3.3 Database Connectivity
- [ ] Operator successfully connects to PostgreSQL
- [ ] Verify in logs: `kubectl logs -n kubesynapse -l app=kubesynapse-operator | grep -i "database"` | head -5
  Expected: Connection established message (or "database ready" equivalent)
- [ ] Query database directly:
  `kubectl exec -n kubesynapse postgresql-0 -- psql -U kubesynapse -d kubesynapse -c "SELECT COUNT(*) FROM workflow_runs;"`
  Expected: Query succeeds, returns count

## 3.4 RBAC Permissions Test
- [ ] Can read CRDs: `kubectl get aiagents -n kubesynapse`
  Expected: List of agents (empty if none exist)
- [ ] Can create test agent:
  ```yaml
  apiVersion: kubesynapse.ai/v1alpha1
  kind: AIAgent
  metadata:
    name: test-agent
    namespace: kubesynapse
  spec:
    replicas: 1
    image: alpine:latest
  ```
  Expected: Agent created and reconciled
- [ ] RBAC properly restricts: Try `kubectl create namespace test-rbac`
  Expected: Succeeds (operator doesn't need to create namespaces)

## 3.5 Health Check Verification
- [ ] Port-forward health check:
  `kubectl port-forward -n kubesynapse svc/kubesynapse-operator 8080:8080 &`
- [ ] Query endpoint: `curl http://localhost:8080/healthz`
  Expected: HTTP 200 with JSON body
- [ ] Probe success rate: `kubectl get deployment -n kubesynapse -o jsonpath='{.items[0].status}' | jq .conditions`
  Expected: All conditions ready, no failed probes

# ============================================================================
# SECTION 4: Performance & Scalability Checks
# ============================================================================

## 4.1 Reconciliation Performance
- [ ] Measure reconciliation time:
  1. Create 10 agents: `for i in {1..10}; do kubectl apply -f agent-$i.yaml; done`
  2. Monitor: `kubectl logs -n kubesynapse -f -l app=kubesynapse-operator | grep duration`
  3. Expected: Reconciliation < 5 seconds per agent
- [ ] No memory leaks over time:
  1. Run operator for 1 hour with steady workflow creation
  2. `kubectl top pod -n kubesynapse -l app=kubesynapse-operator --containers`
  3. Expected: Memory usage stable (±10%), no continuous growth

## 4.2 Concurrent Reconciliation
- [ ] Create agents concurrently:
  `for i in {1..20}; do kubectl apply -f agent-concurrent-$i.yaml & done; wait`
- [ ] All reconcile successfully:
  `kubectl get aiagents -n kubesynapse -o jsonpath='{.items[*].status.phase}'`
  Expected: All agents reach 'ready' phase
- [ ] No dropped events: `kubectl get events -n kubesynapse --sort-by='.lastTimestamp' | tail -20`
  Expected: Reconciliation events for all agents present

## 4.3 Resource Utilization
- [ ] CPU usage under normal load: `kubectl top pod -n kubesynapse -l app=kubesynapse-operator --containers`
  Expected: < 100m (well below 1000m limit)
- [ ] Memory usage under normal load:
  Expected: < 512Mi (request) and < 1Gi (typical)
- [ ] Disk usage: `kubectl exec -n kubesynapse operator-pod -- du -sh /tmp /home/operator`
  Expected: < 100Mi each

# ============================================================================
# SECTION 5: Observability & Monitoring Setup
# ============================================================================

## 5.1 Structured Logging Verification
- [ ] Enable JSON logs: `export JSON_LOGS=true` in deployment
- [ ] Verify JSON output:
  `kubectl logs -n kubesynapse -l app=kubesynapse-operator | head -1 | jq .`
  Expected: Valid JSON with fields: timestamp, level, logger, message, request_id
- [ ] Log aggregation test:
  Forward logs to your centralized logging (ELK, Loki, etc.)
  Expected: Logs parse successfully, all fields indexed

## 5.2 Trace/Tracing Setup (Optional but Recommended)
- [ ] OpenTelemetry collector deployed: `kubectl get deployment -n kubesynapse otel-collector`
- [ ] Environment variable set: `export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`
- [ ] Traces flowing: Check OTEL collector logs
  Expected: Incoming spans for kubesynapse-operator service

## 5.3 Prometheus Metrics (Future)
- [ ] When metrics endpoint implemented, verify ServiceMonitor:
  `kubectl get servicemonitor -n kubesynapse kubesynapse-operator`
- [ ] Verify scrape job:
  `kubectl port-forward -n kubesynapse svc/kubesynapse-operator 8080:8080`
  `curl http://localhost:8080/metrics | head -20`
- [ ] Expected metrics: kubesynapse_operator_reconciliation_total, kubesynapse_operator_reconciliation_duration_seconds

# ============================================================================
# SECTION 6: Operational Procedures
# ============================================================================

## 6.1 Graceful Operator Updates
```bash
# 1. Build new image
docker build -t kubesynapse-operator:v0.2.1 .
docker push your-registry/kubesynapse-operator:v0.2.1

# 2. Update deployment image
kubectl set image deployment/kubesynapse-operator \
  -n kubesynapse \
  operator=your-registry/kubesynapse-operator:v0.2.1

# 3. Monitor rollout
kubectl rollout status deployment/kubesynapse-operator -n kubesynapse --timeout=5m

# 4. Verify health
kubectl port-forward svc/kubesynapse-operator 8080:8080 -n kubesynapse
curl http://localhost:8080/healthz
```

## 6.2 Emergency Operator Restart
```bash
# Delete pod to trigger immediate restart (not recommended for active workflows)
kubectl delete pod -n kubesynapse -l app=kubesynapse-operator

# Monitor restart
kubectl get pods -n kubesynapse -l app=kubesynapse-operator -w

# Verify recovery
kubectl logs -n kubesynapse -l app=kubesynapse-operator --tail=50
```

## 6.3 Database Troubleshooting
```bash
# Check PostgreSQL status
kubectl get statefulset -n kubesynapse kubesynapse-postgresql
kubectl describe pod -n kubesynapse kubesynapse-postgresql-0

# Access PostgreSQL
kubectl exec -n kubesynapse postgresql-0 -- psql -U kubesynapse -d kubesynapse
  → SELECT COUNT(*) FROM workflow_runs;
  → SELECT COUNT(*) FROM agent_sessions;

# Backup database
kubectl exec -n kubesynapse postgresql-0 -- pg_dump -U kubesynapse kubesynapse > backup.sql
```

## 6.4 Debugging Reconciliation Failures
```bash
# Increase log verbosity
kubectl set env deployment/kubesynapse-operator \
  -n kubesynapse \
  OPERATOR_LOG_LEVEL=DEBUG

# Follow logs in real-time
kubectl logs -n kubesynapse -f -l app=kubesynapse-operator

# Search for specific errors
kubectl logs -n kubesynapse -l app=kubesynapse-operator | grep -i "error\|failed\|warning"

# Check resource status
kubectl describe aiagent test-agent -n kubesynapse  # Shows conditions and events
kubectl get aiagent test-agent -n kubesynapse -o yaml | grep -A 20 "status:"
```

# ============================================================================
# SECTION 7: Rollback Procedures
# ============================================================================

## 7.1 If New Deployment Fails
```bash
# 1. Check rollout status
kubectl rollout status deployment/kubesynapse-operator -n kubesynapse

# 2. Rollback to previous version
kubectl rollout undo deployment/kubesynapse-operator -n kubesynapse

# 3. Monitor rollback
kubectl rollout status deployment/kubesynapse-operator -n kubesynapse --timeout=5m

# 4. Verify health
kubectl port-forward svc/kubesynapse-operator 8080:8080 -n kubesynapse
curl http://localhost:8080/healthz
```

## 7.2 Database Recovery
```bash
# List available backups
ls -la *.sql

# Restore from backup
kubectl exec -n kubesynapse postgresql-0 -- psql -U kubesynapse -d kubesynapse < backup.sql

# Verify restore
kubectl exec -n kubesynapse postgresql-0 -- psql -U kubesynapse -d kubesynapse -c "SELECT COUNT(*) FROM workflow_runs;"
```

# ============================================================================
# SECTION 8: Regular Maintenance
# ============================================================================

## 8.1 Weekly Checks
- [ ] Operator pod restarts: `kubectl get pod -n kubesynapse -l app=kubesynapse-operator -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}'`
  Expected: 0 (no unexpected restarts)
- [ ] Log volume: `kubectl logs -n kubesynapse -l app=kubesynapse-operator --timestamps | wc -l`
  Expected: Normal rate (not excessive)
- [ ] Error rate in logs: `kubectl logs -n kubesynapse -l app=kubesynapse-operator | grep -c -i error`
  Expected: < 1% of total log lines

## 8.2 Monthly Tasks
- [ ] Review and rotate secrets (database password, API keys)
- [ ] Update operator to latest patch version
- [ ] Database maintenance: `VACUUM ANALYZE` on PostgreSQL
- [ ] Review RBAC permissions against actual usage patterns
- [ ] Test graceful shutdown procedure

## 8.3 Quarterly Tasks
- [ ] Security audit: Update SecurityContext with latest best practices
- [ ] Capacity planning: Analyze growth, plan for increased replicas if needed
- [ ] Disaster recovery drill: Test full backup/restore procedure
- [ ] Documentation review: Ensure runbooks match current deployment

# ============================================================================
# SECTION 9: Success Criteria
# ============================================================================

Operator is production-ready when:

Security ✓
- [ ] Running as non-root (uid 999)
- [ ] No plaintext credentials in environment or logs
- [ ] RBAC limited to necessary permissions
- [ ] NetworkPolicy in place and tested
- [ ] Input validation prevents injection/DoS

Reliability ✓
- [ ] Health check endpoint responds at /healthz
- [ ] Graceful shutdown on SIGTERM (verified by test)
- [ ] Database connection pool properly sized
- [ ] Error classification correct (transient vs permanent)
- [ ] Reconciliation succeeds consistently

Observability ✓
- [ ] All logs in structured JSON format
- [ ] Request IDs correlate related log entries
- [ ] Health check accessible for monitoring
- [ ] Database metrics available (or Prometheus when implemented)
- [ ] Tracing spans exported to collector (when configured)

Performance ✓
- [ ] Single agent reconciliation < 5 seconds
- [ ] Memory stable (no leaks over time)
- [ ] CPU < 100m under normal load
- [ ] Handles 20+ concurrent reconciliations

Documentation ✓
- [ ] Deployment manifest complete and tested
- [ ] RBAC policies documented
- [ ] Troubleshooting guide present (this file)
- [ ] Emergency procedures documented

---

**Document Version:** 0.2.0  
**Last Updated:** June 12, 2026  
**Maintainer:** KubeSynapse Operator Team  
**Status:** Production Checklist Active
