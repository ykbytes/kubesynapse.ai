"""Production API Gateway Checklist and Operational Runbook.

Complete verification steps to ensure KubeSynapse API Gateway meets production
readiness requirements from the hardening audit.
"""

# ============================================================================
# SECTION 1: Pre-Deployment Verification (§1 - Security)
# ============================================================================

## 1.1 Container Security (§1.1)
- [ ] Dockerfile uses non-root user (gatewayuser:999)
- [ ] Verify: `docker run --rm -it kubesynapse-api-gateway:latest id`
  Expected: uid=999(gatewayuser) gid=999(gateway) groups=999(gateway)
- [ ] Dockerfile is multi-stage build (builder + runtime)
- [ ] Verify: `docker inspect kubesynapse-api-gateway:latest | grep -i size`
  Expected: Image size < 600MB (slim base + runtime libs only)

## 1.2 Environment Variable Audit (§1.2)
- [ ] DATABASE_PASSWORD NOT in deployment env vars (uses secretKeyRef)
- [ ] Verify: `kubectl get deployment -n kubesynapse -o yaml | grep -i password`
  Expected: No plaintext password found (only secretKeyRef)
- [ ] All sensitive values use `valueFrom: secretKeyRef`
- [ ] Database credentials secret exists: `kubectl get secret -n kubesynapse kubesynapse-db-credentials`

## 1.3 RBAC Configuration (§1.3)
- [ ] ClusterRole created: `kubectl get clusterrole kubesynapse-api-gateway`
- [ ] Role contains only necessary permissions (read-only for CRDs)
- [ ] Verify limited scope: `kubectl get clusterrole kubesynapse-api-gateway -o yaml`
  Expected: Only read access to kubesynapse.ai resources, configmaps, secrets
- [ ] ClusterRoleBinding exists and binds to correct service account
- [ ] Test RBAC enforcement: Try to create agent via kubectl from gateway pod
  Expected: Forbidden (gateway doesn't have create/update/delete permissions)

## 1.4 Input Validation (§1.4)
- [ ] gateway_validation.py module present in api-gateway/ folder
- [ ] Verify: `python -c "from gateway_validation import validate_resource_name"`
  Expected: Import successful, no errors
- [ ] Test validation (when integrated into routers):
  Deploy agent with invalid name "invalid-name!" or huge JSON payload
  Expected: 422 validation error, not server crash

## 1.5 Network Policies (§1.5)
- [ ] NetworkPolicy deployed: `kubectl get networkpolicy -n kubesynapse`
- [ ] Gateway can reach PostgreSQL:
  Test: `kubectl exec -n kubesynapse pod/kubesynapse-api-gateway-xxx -- nc -zv kubesynapse-postgresql 5432`
  Expected: Connection successful
- [ ] Gateway can reach Redis, NATS, Qdrant, LiteLLM
- [ ] Gateway cannot reach other namespaces:
  Test: Try connecting to pod in different namespace from gateway pod
  Expected: Connection timeout or refused

# ============================================================================
# SECTION 2: Pre-Deployment Verification (§2 - Reliability)
# ============================================================================

## 2.1 Health Check Endpoint (§2.1)
- [ ] /health endpoint implemented in main.py
- [ ] Health check returns readiness state
- [ ] Test endpoint:
  1. `kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080`
  2. `curl http://localhost:8080/health | jq .`
  Expected response: `{"status": "ok", "service": "kubesynapse-api-gateway", "ready": true}`
- [ ] Deployment includes liveness/readiness probes for /health
- [ ] Verify probes: `kubectl get deployment -n kubesynapse -o yaml | grep -A 20 livenessProbe`

## 2.2 Database Connection Pool (§2.2)
- [ ] Enhanced pool configuration in auth_store.py:
  - pool_size: 20 ✓
  - max_overflow: 40 ✓
  - pool_timeout: 30 ✓
  - pool_recycle: 1800 ✓
  - Connection timeout: 10s ✓
- [ ] Verify in logs: `kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway | grep -i "pool\|timeout"`
- [ ] Test pool under load:
  1. Generate concurrent API requests (10+ simultaneous)
  2. Monitor gateway logs: `kubectl logs -n kubesynapse -f -l app=kubesynapse-api-gateway`
  3. Expected: No connection pool errors, no timeouts, all requests succeed

## 2.3 Shutdown State Tracking (§2.3)
- [ ] _GATEWAY_STATE tracking in main.py
- [ ] Test graceful shutdown:
  1. `kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080 &`
  2. `curl http://localhost:8080/health`  → Should return 200 with `"ready": true`
  3. `kubectl delete pod -n kubesynapse kubesynapse-api-gateway-xxx`
  4. Immediately make requests: `for i in {1..5}; do curl -v http://localhost:8080/health; done`
  5. Expected: Some requests return 503, pod restarts cleanly, no lingering connections

# ============================================================================
# SECTION 3: Deployment Verification
# ============================================================================

## 3.1 Pod Deployment Status
- [ ] Gateway pod running: `kubectl get pod -n kubesynapse -l app=kubesynapse-api-gateway`
  Expected: 2/2 Running (2 replicas)
- [ ] No warnings/errors: `kubectl describe pod -n kubesynapse -l app=kubesynapse-api-gateway`
- [ ] Resource limits applied: `kubectl get pod -n kubesynapse -o yaml | grep -A 5 resources`
  Expected: requests (cpu: 500m, memory: 1Gi), limits (cpu: 2000m, memory: 4Gi)

## 3.2 Security Context Verification
- [ ] Pod runs as non-root:
  `kubectl exec -n kubesynapse -it $(kubectl get pod -n kubesynapse -l app=kubesynapse-api-gateway -o jsonpath='{.items[0].metadata.name}') -- id`
  Expected: uid=999(gatewayuser) gid=999(gateway)
- [ ] No privileged capabilities:
  `kubectl get pod -n kubesynapse -o jsonpath='{.items[0].spec.securityContext}'`
  Expected: allowPrivilegeEscalation=false, capabilities.drop=[ALL]
- [ ] Read-only filesystem:
  Test: `kubectl exec -n kubesynapse ... -- touch /app/test`
  Expected: Read-only file system error

## 3.3 Database Connectivity
- [ ] Gateway successfully connects to PostgreSQL
- [ ] Verify in logs: `kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway | grep -i "database"` | head -10
  Expected: Connection established message (or "Auth database initialized" equivalent)
- [ ] Query database directly:
  `kubectl exec -n kubesynapse postgresql-0 -- psql -U kubesynapse -d kubesynapse -c "SELECT COUNT(*) FROM users;"`
  Expected: Query succeeds, returns count

## 3.4 RBAC Permissions Test
- [ ] Can read agents: `kubectl get aiagents -n kubesynapse` (from gateway pod)
  Expected: List of agents (empty if none exist)
- [ ] Can read workflows: `kubectl get agentworkflows -n kubesynapse`
  Expected: List succeeds
- [ ] Cannot create agents (RBAC blocked):
  From gateway pod: `kubectl create aiagent test-agent -n kubesynapse`
  Expected: Forbidden error (gateway doesn't have create permission)

## 3.5 Health Check Verification
- [ ] Port-forward health check:
  `kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080 &`
- [ ] Query endpoint: `curl http://localhost:8080/health`
  Expected: HTTP 200 with JSON body
- [ ] Probe success rate: `kubectl get deployment -n kubesynapse -o jsonpath='{.items[0].status}' | jq .conditions`
  Expected: All conditions ready, no failed probes

# ============================================================================
# SECTION 4: API Functionality Tests
# ============================================================================

## 4.1 Authentication
- [ ] API requires token: `curl -s http://localhost:8080/api/v1/agents | grep -i "unauthorized\|403"`
  Expected: 401/403 error
- [ ] Token accepted: `curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/agents`
  Expected: Success (200 or 401 if token invalid, but not 500 error)

## 4.2 Agent Operations
- [ ] List agents: `curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/agents`
  Expected: 200 OK with agent list
- [ ] Get agent: `curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/agents/agent-name`
  Expected: 200 OK or 404 if not found

## 4.3 Error Handling
- [ ] Invalid input returns structured error:
  `curl -X POST http://localhost:8080/api/v1/agents -d 'invalid json'`
  Expected: 422 with `{"code": "VALIDATION_ERROR", "message": "...", "request_id": "..."}`
- [ ] Not found returns structured error:
  `curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/agents/nonexistent`
  Expected: 404 with ErrorResponse structure

# ============================================================================
# SECTION 5: Performance & Scalability Checks
# ============================================================================

## 5.1 Request Latency
- [ ] Measure response time:
  `time curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/agents | head`
  Expected: < 500ms for simple list operation
- [ ] Under load:
  `for i in {1..100}; do curl -s http://localhost:8080/api/v1/agents & done; wait`
  Expected: All succeed, no connection errors

## 5.2 Concurrent Connections
- [ ] Create 20+ concurrent requests
- [ ] Monitor gateway: `kubectl top pod -n kubesynapse -l app=kubesynapse-api-gateway --containers`
  Expected: CPU stays < 1000m, Memory < 2Gi

## 5.3 Resource Utilization
- [ ] CPU usage under normal load:
  Expected: < 500m (well below 2000m limit)
- [ ] Memory usage under normal load:
  Expected: < 1Gi (request) and < 2Gi typical (well below 4Gi limit)

# ============================================================================
# SECTION 6: Observability & Monitoring Setup
# ============================================================================

## 6.1 Structured Logging Verification
- [ ] Enable structured logging:
  `kubectl set env deployment/kubesynapse-api-gateway -n kubesynapse STRUCTURED_LOGGING=true`
- [ ] Verify JSON output:
  `kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway | head -1 | jq .`
  Expected: Valid JSON with fields: level, logger, message, request_id, timestamp

## 6.2 Request ID Correlation
- [ ] Verify request IDs in logs:
  `kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway | grep "request_id" | head -5`
  Expected: All log entries from same request share same request_id

## 6.3 Metrics Endpoint
- [ ] Prometheus metrics available:
  `curl http://localhost:8080/metrics | head -20`
  Expected: Prometheus format metrics (HELP, TYPE, values)

# ============================================================================
# SECTION 7: Operational Procedures
# ============================================================================

## 7.1 Graceful Deployment Update
```bash
# 1. Build new image
docker build -t kubesynapse-api-gateway:v1.1.0 .
docker push your-registry/kubesynapse-api-gateway:v1.1.0

# 2. Update deployment image
kubectl set image deployment/kubesynapse-api-gateway \
  -n kubesynapse \
  gateway=your-registry/kubesynapse-api-gateway:v1.1.0

# 3. Monitor rollout
kubectl rollout status deployment/kubesynapse-api-gateway -n kubesynapse --timeout=5m

# 4. Verify health
kubectl port-forward svc/kubesynapse-api-gateway 8080:8080 -n kubesynapse
curl http://localhost:8080/health
```

## 7.2 Emergency Gateway Restart
```bash
# Delete pod to trigger immediate restart
kubectl delete pod -n kubesynapse -l app=kubesynapse-api-gateway

# Monitor restart
kubectl get pods -n kubesynapse -l app=kubesynapse-api-gateway -w

# Verify recovery
kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway --tail=50
```

## 7.3 Debugging API Issues
```bash
# Check pod status
kubectl describe pod -n kubesynapse -l app=kubesynapse-api-gateway | head -50

# View logs with errors
kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway | grep -i "error\|failed\|warning"

# Test connectivity to dependencies
kubectl exec -n kubesynapse pod/kubesynapse-api-gateway-xxx -- nc -zv kubesynapse-postgresql 5432
kubectl exec -n kubesynapse pod/kubesynapse-api-gateway-xxx -- nc -zv kubesynapse-redis 6379
kubectl exec -n kubesynapse pod/kubesynapse-api-gateway-xxx -- nc -zv kubesynapse-litellm 4000
```

# ============================================================================
# SECTION 8: Regular Maintenance
# ============================================================================

## 8.1 Weekly Checks
- [ ] Pod restarts: `kubectl get pod -n kubesynapse -l app=kubesynapse-api-gateway -o jsonpath='{.items[*].status.containerStatuses[0].restartCount}'`
  Expected: 0 or only expected restarts (rolling updates)
- [ ] Error rate in logs: `kubectl logs -n kubesynapse -l app=kubesynapse-api-gateway | grep -c -i error`
  Expected: < 1% of total log lines
- [ ] Database connection pool: Check for "connection timeout" errors
  Expected: None

## 8.2 Monthly Tasks
- [ ] Review and rotate secrets (database password, API keys)
- [ ] Update gateway to latest patch version
- [ ] Database maintenance: Vacuum and analyze if needed
- [ ] Review logs for unusual patterns
- [ ] Test graceful shutdown procedure

## 8.3 Quarterly Tasks
- [ ] Security audit: Review RBAC, network policies, security contexts
- [ ] Capacity planning: Analyze growth, plan for scale-up if needed
- [ ] Disaster recovery drill: Full backup/restore test
- [ ] Update documentation based on learnings

# ============================================================================
# SECTION 9: Success Criteria
# ============================================================================

Gateway is production-ready when:

Security ✓
- [ ] Running as non-root (uid 999)
- [ ] No plaintext credentials in environment or logs
- [ ] RBAC limited to necessary permissions (read-only for CRDs)
- [ ] NetworkPolicy in place and tested
- [ ] Input validation prevents injection/DoS

Reliability ✓
- [ ] Health check endpoint responds at /health
- [ ] Graceful shutdown on SIGTERM (verified by test)
- [ ] Database connection pool properly sized
- [ ] Readiness state properly tracked
- [ ] All routes return structured ErrorResponse on error

Operational ✓
- [ ] All logs in structured JSON format (when enabled)
- [ ] Request IDs correlate logs across middleware/routers
- [ ] Health check accessible for Kubernetes probes
- [ ] Database connection pool metrics visible in logs
- [ ] Deployment manifests tested and documented

Performance ✓
- [ ] List/Get API requests < 500ms
- [ ] Memory stable (no leaks over 24h)
- [ ] CPU < 500m under normal load
- [ ] Handles 100+ concurrent requests
- [ ] Connection pool reuse working (not exhausting)

---

**Document Version:** 1.0.0  
**Last Updated:** June 12, 2026  
**Maintainer:** KubeSynapse API Gateway Team  
**Status:** Production Checklist Active
