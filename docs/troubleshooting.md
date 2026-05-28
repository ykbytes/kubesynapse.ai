# KubeSynapse Troubleshooting Guide

**Who is this for:** Anyone operating or developing on KubeSynapse who needs to diagnose and fix common issues quickly.

Each issue follows this pattern: **Symptoms -> Diagnosis -> Fix -> Prevention**

---

## Table of Contents

- [Agent Pod Stuck in Pending](#agent-pod-stuck-in-pending)
- [Agent Pod CrashLoopBackOff](#agent-pod-crashloopbackoff)
- [Gateway 503 Errors](#gateway-503-errors)
- [A2A Delegation Fails](#a2a-delegation-fails)
- [LLM Calls Timeout](#llm-calls-timeout)
- [Web UI Not Loading](#web-ui-not-loading)
- [Settings Page Shows "Failed to Load Providers"](#settings-page-shows-failed-to-load-providers)
- [Database Connection Failures](#database-connection-failures)
- [Workflow Eval Failures](#workflow-eval-failures)
- [Auth and OIDC Issues](#auth-and-oidc-issues)
- [MCP Tool Not Available](#mcp-tool-not-available)
- [Execution Observatory Shows No Data](#execution-observatory-shows-no-data)
- [Workflow Logs Return "No Worker Pod Found"](#workflow-logs-return-no-worker-pod-found)
- [Auth Page Shows Bootstrap When Users Exist](#auth-page-shows-bootstrap-when-users-exist)
- [Web UI Changes Not Visible After Deploy](#web-ui-changes-not-visible-after-deploy)

---

## Agent Pod Stuck in Pending

### Symptoms

- `kubectl get pods` shows agent pod in `Pending` state
- `kubectl describe pod` shows events like `Unschedulable` or `FailedBinding`

### Diagnosis

```bash
kubectl describe pod <agent-pod> -n <namespace>
kubectl get events -n <namespace> --field-selector reason=FailedScheduling
```

Common causes:

| Cause | Event Message |
|-------|---------------|
| **PVC not bound** | `persistentvolumeclaim "state-volume" not found` |
| **Insufficient resources** | `Insufficient cpu` or `Insufficient memory` |
| **Node taints** | `Node(s) had taint {key=value:NoSchedule}` |
| **Missing StorageClass** | `no volume plugin matched name: kubernetes.io/no-provisioner` |

### Fix

**PVC not bound:**

```bash
# Check PVC status
kubectl get pvc -n <namespace>

# If no default StorageClass, set one
kubectl patch storageclass <your-class> -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

# Or specify storageClassName in agent spec
kubectl patch aiagent <name> -n <namespace> --type merge \
  -p '{"spec":{"storageClassName":"standard"}}'
```

**Insufficient resources:**

```bash
# Check node capacity
kubectl describe nodes | grep -A 5 "Allocated resources"

# Reduce agent resource requests or add nodes
kubectl patch aiagent <name> -n <namespace> --type merge \
  -p '{"spec":{"resources":{"requests":{"cpu":"100m","memory":"256Mi"}}}}'
```

**Node taints:**

```bash
# Tolerate the taint in agent spec, or remove taint
kubectl taint nodes <node> <key>:NoSchedule-
```

### Prevention

- Set a default StorageClass before installing KubeSynapse
- Use ResourceQuotas per namespace to reserve headroom
- Label nodes for agent workloads and use node affinity

---

## Agent Pod CrashLoopBackOff

### Symptoms

- Pod status shows `CrashLoopBackOff`
- `kubectl logs` shows repeated restarts

### Diagnosis

```bash
kubectl logs <agent-pod> -n <namespace> --previous
kubectl describe pod <agent-pod> -n <namespace>
```

Common causes:

| Cause | Log Indicator |
|-------|---------------|
| **Missing secrets** | `Secret "litellm-master-key" not found` |
| **Invalid runtime config** | `RuntimeError: Unknown runtime kind "xyz"` |
| **OOMKilled** | `Last State: Terminated, Reason: OOMKilled` |
| **Image pull failure** | `Back-off pulling image "docker.io/..."` |

### Fix

**Missing secrets:**

```bash
# Verify secrets exist
kubectl get secrets -n kubesynapse

# Re-create or update Helm values
helm upgrade KubeSynapse oci://docker.io/kubesynapse/charts/kubesynapse \
  -n kubesynapse -f values.yaml
```

**Invalid runtime config:**

```bash
# Supported runtime kinds are "opencode", "pi", and "mistral-vibe"
kubectl get aiagent <name> -n <namespace> -o jsonpath='{.spec.runtime.kind}'

# Fix if needed
kubectl patch aiagent <name> -n <namespace> --type merge \
  -p '{"spec":{"runtime":{"kind":"opencode"}}}'
```

**OOMKilled:**

```bash
# Increase memory limit
kubectl patch aiagent <name> -n <namespace> --type merge \
  -p '{"spec":{"resources":{"limits":{"memory":"4Gi"}}}}'
```

**Image pull failure:**

```bash
# Verify registry credentials
kubectl get secret regcred -n kubesynapse

# Check image tag exists
kubectl get aiagent <name> -n <namespace> -o yaml | grep image:
```

### Prevention

- Validate agent specs with `agentctl validate` before applying
- Set resource limits based on model context window size
- Use explicit image tags, never `latest`

---

## Gateway 503 Errors

### Symptoms

- API returns `503 Service Unavailable`
- `invoke` or `chat` endpoints fail intermittently

### Diagnosis

```bash
# Check gateway readiness
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway | grep "503"

# Check runtime pod health
kubectl get pods -n <namespace> -l app.kubernetes.io/name=<agent-name>

# Check network policies
kubectl get networkpolicies -n <namespace>
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **Runtime not ready** | Agent pod in `ContainerCreating` or `NotReady` |
| **NetworkPolicy blocking** | `ingress denied` in CNI logs |
| **Gateway resource exhaustion** | Gateway pods at CPU/memory limits |
| **Database unavailable** | `/api/v1/ready` returns `degraded` |

### Fix

**Runtime not ready:**

```bash
# Wait for StatefulSet rollout
kubectl rollout status statefulset <agent-name> -n <namespace>

# If stuck, restart
kubectl rollout restart statefulset <agent-name> -n <namespace>
```

**NetworkPolicy blocking:**

```bash
# Temporarily allow all ingress for debugging
kubectl label networkpolicy -n <namespace> KubeSynapse-deny-ingress disabled=true

# Or add explicit allow rule for gateway
kubectl patch networkpolicy allow-gateway -n <namespace> --type merge \
  -p '{"spec":{"ingress":[{"from":[{"podSelector":{"matchLabels":{"app":"kubesynapse-api-gateway"}}}]}]}}'
```

**Gateway resource exhaustion:**

```bash
# Scale gateway horizontally
kubectl scale deployment kubesynapse-api-gateway -n kubesynapse --replicas=5
```

### Prevention

- Enable startup probes on agent runtimes
- Use PodDisruptionBudgets for gateway and operator
- Configure HPA on gateway before load increases

---

## A2A Delegation Fails

### Symptoms

- `@mention` in chat returns error or no response
- A2A task status stays `pending` or `failed`

### Diagnosis

```bash
# Check allowedTargets policy
kubectl get agentpolicy -n <namespace> -o yaml | grep allowedTargets -A 10

# Verify target agent exists and is running
kubectl get aiagent <target-agent> -n <namespace>
kubectl get pods -n <target-namespace> -l app.kubernetes.io/name=<target-agent>

# Check gateway logs for A2A errors
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway | grep "a2a"
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **Policy denies target** | `A2A target "xyz" not in allowedTargets` |
| **Target agent down** | Agent pod not found or not ready |
| **Namespace mismatch** | Target exists in different namespace without cross-namespace policy |
| **Auth scope issue** | Caller token lacks `operator` role for target namespace |

### Fix

**Policy denies target:**

```bash
# Update policy to allow the target
kubectl patch agentpolicy <policy-name> -n <namespace> --type merge \
  -p '{"spec":{"a2a":{"allowedTargets":[{"name":"security-specialist","namespace":"default"}]}}}'
```

**Target agent down:**

```bash
# Restart target agent
kubectl rollout restart statefulset <target-agent> -n <target-namespace>
```

### Prevention

- Document allowed A2A targets in agent onboarding runbooks
- Use `AgentPolicy` defaults that deny all A2A unless explicitly allowed
- Monitor `KubeSynapse_a2a_failures_total` Prometheus metric

---

## LLM Calls Timeout

### Symptoms

- Agent responds with timeout error after 30-300 seconds
- LiteLLM logs show `ReadTimeout` or `Connection reset`

### Diagnosis

```bash
# Check LiteLLM health
kubectl exec -n kubesynapse deploy/litellm -- curl -s localhost:4000/health/liveliness

# Check model availability
kubectl logs -n kubesynapse deployment/litellm | grep "model"

# Check gateway readiness for downstream dependency errors
curl -s http://localhost:8080/api/v1/ready
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **LiteLLM misconfigured** | `Model not in model_list` |
| **Provider rate limit** | `429 Too Many Requests` from OpenAI/Anthropic |
| **Model deprecated** | `The model gpt-4-xxx does not exist` |
| **Network egress blocked** | NetworkPolicy prevents LiteLLM from reaching provider API |

### Fix

**LiteLLM misconfigured:**

```bash
# Check model list
kubectl get configmap litellm-config -n kubesynapse -o yaml

# Redeploy with correct model names
helm upgrade KubeSynapse ... --set litellm.models='[{"model_name":"gpt-4o","litellm_params":{"model":"openai/gpt-4o"}}]'
```

**Provider rate limit:**

```bash
# Add fallback model in LiteLLM config
# Or increase rate limit tier with provider
```

**Network egress blocked:**

```bash
# Add egress rule for provider APIs
kubectl patch networkpolicy allow-litellm-egress -n kubesynapse --type merge \
  -p '{"spec":{"egress":[{"to":[{"ipBlock":{"cidr":"0.0.0.0/0"}}],"ports":[{"protocol":"TCP","port":443}]}]}}'
```

### Prevention

- Configure LiteLLM with fallback models
- Set reasonable timeout values in agent spec
- Monitor provider rate limits and error rates
- Keep clients on canonical `/api/v1/...` paths for health and invoke calls.
- Prefer the agent's configured model first in fallback ordering; avoid broad
  cross-provider fallback chains that add retries before the real model runs.

### High Invoke Latency For OpenCode Agents

### Symptoms

- Simple agent invokes take 20s to 40s before the first response
- Gateway logs show repeated fallback attempts before the configured model runs
- Runtime logs show repeated retries against OpenCode's synchronous
  `/session/{id}/message` endpoint

### Diagnosis

```bash
# Confirm the UI and clients hit the canonical invoke path
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/api/v1/agents/taskrunner/invoke \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"What is 2+2?","thread_id":"latency-check"}'

# Check whether the gateway is trying multiple fallback models
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway --tail=200 | grep runtime_request_start_model

# Check whether the runtime is still using the broken sync message path
kubectl logs taskrunner-sandbox-0 -c agent-runtime --tail=200 | grep '/session/.*/message'
```

### Fix

- Ensure the Web UI and SDKs call `/api/v1/agents/{name}/invoke` and
  `/api/v1/agents/{name}/invoke/stream` directly.
- Keep the requested model first in the gateway fallback chain.
- Use the OpenCode async prompt path in the runtime for invoke execution,
  including turns with system prompts.

---

## Web UI Not Loading

### Symptoms

- Browser shows blank page or `502 Bad Gateway`
- Console shows CORS errors or chunk load errors

### Diagnosis

```bash
# Check web-ui pod status
kubectl get pods -n kubesynapse -l app.kubernetes.io/name=kubesynapse-web-ui

# Check ingress or port-forward
kubectl get ingress -n kubesynapse
kubectl get svc kubesynapse-web-ui -n kubesynapse

# Check gateway connectivity from UI pod
kubectl exec -n kubesynapse deploy/kubesynapse-web-ui -- curl -s http://kubesynapse-api-gateway:8080/api/v1/health
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **ImagePullBackOff** | `Back-off pulling image` |
| **CORS misconfiguration** | `Access-Control-Allow-Origin` missing |
| **Ingress misconfiguration** | `404` or `502` from ingress controller |
| **API gateway down** | UI cannot reach `/api/v1/health` |

### Fix

**ImagePullBackOff:**

```bash
# Check image tag and pull secrets
kubectl get deployment kubesynapse-web-ui -n kubesynapse -o yaml | grep image:

# If using local registry in Kind, re-load image
kind load docker-image KubeSynapse/web-ui:tag --name KubeSynapse
```

**CORS misconfiguration:**

```bash
# Set correct CORS origin in gateway config
helm upgrade KubeSynapse ... --set apiGateway.corsOrigins='["https://KubeSynapse.example.com"]'
```

**Ingress misconfiguration:**

```bash
# Verify ingress rules
kubectl get ingress kubesynapse -n kubesynapse -o yaml

# Check ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

### Prevention

- Pin web-ui image tags in values files
- Test CORS configuration in staging before production
- Use health-check endpoints in ingress backend rules

---

## Settings Page Shows "Failed to Load Providers"

### Symptoms

- The Settings workspace shows a toast with `Failed to load providers`
- The provider list stays empty even though the gateway and web UI are otherwise reachable
- Direct calls to `/api/v1/providers` return `500 Internal Server Error`

### Diagnosis

```bash
# Confirm the provider registry endpoint that powers Settings
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/providers

# Check the adjacent provider endpoints used by the settings workspace
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/providers/catalog
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/llm/providers

# Inspect gateway logs for router traceback details
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway --tail=200
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **Gateway split-router import drift** | Traceback shows `NameError` for `_provider_registry_response` or another provider helper in `api-gateway/routers/llm.py` |
| **Stale gateway image** | Source includes the provider helper imports but the running deployment still returns `500` |
| **Auth/token mismatch** | Endpoint returns `401` or `403` instead of provider JSON |

### Fix

**Gateway split-router import drift:**

```bash
# Rebuild and redeploy the api-gateway image after restoring the missing imports in api-gateway/routers/llm.py
podman build -t docker.io/kubesynapse/kubesynapse-api-gateway:<tag> -f api-gateway/Dockerfile api-gateway
minikube image load docker.io/kubesynapse/kubesynapse-api-gateway:<tag> -p <profile>
helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse \
  -f deploy/values.kind.yaml \
  --set apiGateway.image.tag=<tag>
```

**Stale gateway image:**

```bash
# Roll the updated gateway deployment and verify the live endpoint before reloading the UI
kubectl rollout status deployment/kubesynapse-api-gateway -n kubesynapse --timeout=300s
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/providers
```

### Prevention

- When extracting gateway routes, re-import every shared helper and request model used by the new router module.
- Verify `/api/v1/providers`, `/api/v1/providers/catalog`, and `/api/v1/llm/providers` after gateway refactors before publishing a new image.
- Prefer fresh image tags for local redeploys so the cluster does not keep serving an older gateway build.

---

## Database Connection Failures

### Symptoms

- Gateway `/api/v1/ready` returns `degraded` with `database: error`
- Login fails with `500 Internal Server Error`
- Audit logs or chat history not persisting

### Diagnosis

```bash
# Check PostgreSQL pod status
kubectl get pods -n kubesynapse -l app.kubernetes.io/name=postgresql

# Check connection from gateway
kubectl exec -n kubesynapse deploy/kubesynapse-api-gateway -- \
  python -c "import psycopg2; conn = psycopg2.connect(host='postgresql', dbname='kubesynapse', user='kubesynapse', password='...'); print('OK')"

# Check gateway logs
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway | grep -i database
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **PostgreSQL not ready** | Pod in `CrashLoopBackOff` or `Pending` |
| **Wrong credentials** | `FATAL: password authentication failed` |
| **Schema version mismatch** | `SchemaVersion mismatch: expected X, got Y` |
| **Connection pool exhausted** | `FATAL: sorry, too many clients already` |

### Fix

**PostgreSQL not ready:**

```bash
# Check PVC and resources
kubectl describe pod postgresql-0 -n kubesynapse

# If PVC issue, see [Agent Pod Stuck in Pending](#agent-pod-stuck-in-pending)
```

**Wrong credentials:**

```bash
# Update secret and restart gateway
kubectl patch secret KubeSynapse-db-credentials -n kubesynapse --type merge \
  -p '{"stringData":{"password":"new-password"}}'
kubectl rollout restart deployment/kubesynapse-api-gateway -n kubesynapse
```

**Schema version mismatch:**

```bash
# Run migration or reset (data loss if resetting)
kubectl exec -n kubesynapse deploy/kubesynapse-api-gateway -- \
  python -c "from auth_store import init_db; init_db()"
```

**Connection pool exhausted:**

```bash
# Increase pool size in gateway config
helm upgrade KubeSynapse ... --set apiGateway.db.poolSize=20
```

### Prevention

- Use external managed PostgreSQL in production
- Monitor connection pool metrics
- Set `pool_recycle` to prevent stale connections

---

## Workflow Eval Failures

### Symptoms

- Workflow or eval status shows `failed` or `timeout`
- Worker Job status is `Error` or `DeadlineExceeded`

### Diagnosis

```bash
# Check worker job logs
kubectl logs -n <namespace> job/<workflow-name>-worker-<id>

# Check artifacts
kubectl get pvc -n <namespace> | grep artifact

# Describe the job for events
kubectl describe job <workflow-name>-worker-<id> -n <namespace>
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **Step dependency failed** | `Previous step "xyz" failed` |
| **Approval gate blocked** | `Waiting for approval: ...` |
| **Resource quota exceeded** | `Forbidden: exceeded quota` |
| **Artifact PVC full** | `no space left on device` |

### Fix

**Step dependency failed:**

```bash
# Inspect the failed step in logs
kubectl logs -n <namespace> job/<workflow-name>-worker-<id> | grep ERROR

# Retry failed steps only
agentctl workflow retry-failed <workflow-name> -n <namespace>
```

**Approval gate blocked:**

```bash
# List pending approvals
kubectl get agentapprovals -n <namespace>

# Approve via API
kubectl patch agentapproval <approval-name> -n <namespace> --type merge \
  -p '{"status":{"decision":"approved","decidedBy":"admin","decidedAt":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","reason":"Approved via CLI"}}'
```

**Resource quota exceeded:**

```bash
# Increase namespace quota
kubectl patch resourcequota <name> -n <namespace> --type merge \
  -p '{"spec":{"hard":{"requests.cpu":"20","requests.memory":"40Gi"}}}'
```

**Artifact PVC full:**

```bash
# Clean old artifacts or expand PVC
kubectl exec -n <namespace> job/<workflow-name>-worker-<id> -- du -sh /artifacts

# Expand PVC (if storage class supports it)
kubectl patch pvc <artifact-pvc> -n <namespace> --type merge \
  -p '{"spec":{"resources":{"requests":{"storage":"10Gi"}}}}'
```

### Prevention

- Set reasonable `activeDeadlineSeconds` on workflows
- Use `requireApproval: true` only on genuinely risky steps
- Monitor artifact PVC usage and set alerts

---

## Auth and OIDC Issues

### Symptoms

- Login redirect fails with `invalid_request`
- JWT validation errors after login
- `401 Unauthorized` on all API calls

### Diagnosis

```bash
# Check auth mode
kubectl get deployment kubesynapse-api-gateway -n kubesynapse -o yaml | grep AUTH_MODE

# Check OIDC config
curl -s http://localhost:8080/api/auth/config

# Verify JWKS endpoint is reachable
kubectl exec -n kubesynapse deploy/kubesynapse-api-gateway -- \
  curl -s <oidc-issuer>/.well-known/openid-configuration | jq .jwks_uri
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **Redirect URI mismatch** | `redirect_uri did not match any configured URIs` |
| **JWKS endpoint unreachable** | `Unable to fetch JWKS` |
| **Clock skew** | `Token not yet valid (nbf)` |
| **Cookie blocked** | `Secure` cookie over HTTP in dev mode |

### Fix

**Redirect URI mismatch:**

```bash
# Update OIDC app registration with exact redirect URI
# Example: https://KubeSynapse.example.com/api/auth/oidc/callback/default
```

**JWKS endpoint unreachable:**

```bash
# Check network egress from gateway
kubectl exec -n kubesynapse deploy/kubesynapse-api-gateway -- \
  curl -I <jwks-url>

# If blocked, update NetworkPolicy or trust bundle
```

**Clock skew:**

```bash
# Sync node clocks
kubectl exec -n kubesynapse deploy/kubesynapse-api-gateway -- date -u
# If skew > 30s, configure NTP on nodes
```

**Cookie blocked:**

```bash
# For local development, disable secure cookies
helm upgrade KubeSynapse ... --set apiGateway.auth.cookieSecure=false
```

### Prevention

- Document exact redirect URIs in IdP configuration
- Use HTTPS in production with `cookieSecure: true`
- Enable JWT `kid` validation and key rotation

---

## MCP Tool Not Available

### Symptoms

- Agent says "I don't have access to that tool"
- MCP sidecar pod not running or not reachable
- `mcp/connections` endpoint shows `unhealthy`

### Diagnosis

```bash
# List MCP sidecars for the agent
kubectl get pods -n <namespace> -l app.kubernetes.io/name=<agent-name>

# Check sidecar logs
kubectl logs -n <namespace> <agent-pod> -c <mcp-sidecar>

# Validate MCP connection via API
curl -X POST http://localhost:8080/api/v1/mcp/connections/<id>/validate
```

Common causes:

| Cause | Indicator |
|-------|-----------|
| **Sidecar not injected** | No extra containers in agent pod |
| **Sidecar crash** | `CrashLoopBackOff` on sidecar container |
| **Connection misconfigured** | `connection refused` or `invalid auth` |
| **Policy blocks MCP server** | `MCP server "xyz" not in allowedMcpServers` |

### Fix

**Sidecar not injected:**

```bash
# Verify agent spec includes mcpConnections
kubectl get aiagent <name> -n <namespace> -o jsonpath='{.spec.mcpConnections}'

# Add connection
kubectl patch aiagent <name> -n <namespace> --type merge \
  -p '{"spec":{"mcpConnections":[{"connectionRef":"github-mcp"}]}}'
```

**Sidecar crash:**

```bash
# Check sidecar resource limits
kubectl describe pod <agent-pod> -n <namespace>

# Increase if OOMKilled
kubectl patch aiagent <name> -n <namespace> --type merge \
  -p '{"spec":{"mcpResources":{"limits":{"memory":"512Mi"}}}}'
```

**Policy blocks MCP server:**

```bash
# Add server to allowed list
kubectl patch agentpolicy <policy-name> -n <namespace> --type merge \
  -p '{"spec":{"allowedMcpServers":["github","kubernetes"]}}'
```

### Prevention

- Validate MCP connections before attaching to agents
- Use `AgentPolicy` to whitelist only required MCP servers
- Monitor sidecar health with liveness probes

---

**Last Updated:** May 3, 2026  
**Platform Version:** 1.0.0

---

## Execution Observatory Shows No Data

### Symptoms

- Execution Observatory shows "No steps recorded" or "0 LLM, 0 tools" for a completed workflow
- Stats show 0/5 steps, "—" duration
- Event timeline is empty

### Diagnosis

```bash
# Check if trace data reached the database
kubectl exec -n kubesynapse deployment/kubesynapse-api-gateway -- python -c "
import psycopg
conn = psycopg.connect('host=kubesynapse-postgresql user=kubesynapse password=<pw> dbname=kubesynapse')
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM execution_traces\")
print('traces:', cur.fetchone()[0])
"

# Check if API gateway received batch requests
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway --tail=30 | grep "/api/traces/batch"
```

Common causes:

| Cause | Diagnosis | Fix |
|---|---|---|
| **Missing shared token** | `DEFAULT_API_GATEWAY_SHARED_TOKEN` env var empty on operator | Set via `kubectl set env` |
| **Network policy blocks worker** | Worker pod cannot reach API gateway on port 8080 | Verify `kubesynapse-allow-worker-gateway-egress` network policy |
| **Operator restarted** | Token lost after helm upgrade | Re-apply token after each upgrade |
| **Old run** | Execution ran before trace pipeline was fixed | Re-run the workflow |

### Fix — Apply Shared Token

```bash
kubectl set env deployment/kubesynapse-operator -n kubesynapse \
  DEFAULT_API_GATEWAY_SHARED_TOKEN='<your-shared-token>'

# Trigger a new workflow run to verify
kubectl patch workflow <name> -n <namespace> --type merge \
  -p '{"status":{"observedGeneration":0}}'
```

### Prevention

- The helm chart template (`charts/kubesynapse/templates/operator-deployment.yaml`) now uses a direct `value:` for `DEFAULT_API_GATEWAY_SHARED_TOKEN` instead of `valueFrom: secretKeyRef` with `optional: true`
- Verify after each helm upgrade: `kubectl get deployment kubesynapse-operator -n kubesynapse -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DEFAULT_API_GATEWAY_SHARED_TOKEN")].value}'`

---

## Workflow Logs Return "No Worker Pod Found"

### Symptoms

- Observatory logs tab shows "No worker pod found for workflow job" or "unavailable"
- Log source shows "archived" instead of "live-worker"
- Worker logs exist in the pod but the API gateway can't find them

### Diagnosis

```bash
# Check the worker pod exists and has logs
kubectl get pods -n kubesynapse -l job-name=<job-name>
kubectl logs -n kubesynapse <pod-name>

# Verify API gateway can list pods in the operator namespace
kubectl exec -n kubesynapse deployment/kubesynapse-api-gateway -- python -c "
from kubernetes import client, config
config.load_incluster_config()
pods = client.CoreV1Api().list_namespaced_pod(namespace='kubesynapse', label_selector='job-name=<job-name>')
print(len(pods.items), 'pods found')
"
```

### Fix

The API gateway was looking up worker pods in the workflow's namespace (e.g., `default`) instead of the operator's namespace (`kubesynapse`). This is fixed in API gateway v15+.

If still seeing the issue, verify the gateway can load in-cluster Kubernetes config:

```bash
kubectl exec -n kubesynapse deployment/kubesynapse-api-gateway -- python -c "
from kubernetes import config; config.load_incluster_config(); print('OK')
"
```

---

## Auth Page Shows Bootstrap When Users Exist

### Symptoms

- Auth page shows "Welcome — create the first admin account" banner
- Tab shows "Create Account" instead of "Sign In"
- Cannot switch to login mode
- Previously created accounts cannot sign in

### Diagnosis

```bash
# Check if users exist in the database
kubectl exec -n kubesynapse deployment/kubesynapse-api-gateway -- python -c "
import psycopg
conn = psycopg.connect('host=kubesynapse-postgresql user=kubesynapse password=<pw> dbname=kubesynapse')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM users')
print('users:', cur.fetchone()[0])
"
```

If the count is 0, the PostgreSQL data was lost. This happens when the kind cluster node restarts (local-path-provisioner data on `tmpfs` is ephemeral).

### Fix

1. **Create a new admin account** using the bootstrap form
2. **For production**: Use a persistent storage class for PostgreSQL (not `standard` / local-path)
3. **For kind development**: Accept that data is ephemeral between Docker Desktop restarts

```bash
# Check PostgreSQL mount type
kubectl exec -n kubesynapse pod/kubesynapse-postgresql-0 -- cat /proc/mounts | grep postgresql/data
# If it shows "tmpfs", storage is NOT persistent
```

---

## Web UI Changes Not Visible After Deploy

### Symptoms

- Deployed new web UI image but old UI still shows
- JS/CSS bundle files unchanged despite new image
- Hard refresh (Ctrl+Shift+R) needed every time

### Diagnosis

The nginx config in the web UI container sets immutable cache headers for `/assets`:

```nginx
add_header Cache-Control "public, immutable";
```

Browsers cache these assets for 1 year. After each deploy, the old cached bundles are served.

### Fix

1. **Hard refresh**: `Ctrl+Shift+R` (Chrome/Edge) or `Cmd+Shift+R` (Mac)
2. **DevTools**: Network tab → "Disable cache" checkbox
3. **Incognito window**: Always loads fresh assets
4. **Cache-busting is automatic**: Each build produces new bundle filenames (e.g., `index-X9sjL0aj.js` → `index-D4b0WUm_.js`), so after hard refresh, the new files load correctly
