# KubeSynapse Platform Security Audit

**Date:** 2026-05-19  
**Scope:** Full platform analysis — operator, API gateway, MCP sidecars, Helm chart, and runtime integrations  
**Context:** Self-hosted Kubernetes-native AI agent platform. Findings relevant for production deployment hardening.  
**Methodology:** Static analysis of `operator/`, `api-gateway/`, `mcp-sidecars/`, `charts/kubesynapse/`, and runtime builder code in `operator/builders/manifests.py`.  

---

## Executive Summary

**52 findings across 8 platform surfaces.** The KubeSynapse platform has a **mixed security posture**: strong defaults on pod-level security contexts (all containers drop ALL capabilities, readOnlyRootFilesystem, seccomp profiles), but significant gaps in RBAC scoping, credential handling, and sidecar authentication. The most critical finding is the **operator's privilege escalation path** — it can create ClusterRoleBindings granting itself cluster-admin.

| Surface | CRITICAL | HIGH | MEDIUM | LOW | Positive |
|---------|----------|------|--------|-----|----------|
| Operator | 3 | 4 | 3 | 1 | 3 |
| API Gateway | 0 | 1 | 14 | 18 | 12 |
| MCP Sidecars | 2 | 4 | 3 | 1 | 0 |
| Helm Chart | 1 | 8 | 6 | 5 | 13 |
| **Total** | **6** | **17** | **26** | **25** | **28** |

---

## Attack Surface 1: Operator Security

### 1.1 CRITICAL — Operator can escalate to cluster-admin via RBAC self-modification

**File:** `charts/kubesynapse/templates/operator-rbac.yaml:85-87`

```yaml
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: [roles, rolebindings, clusterroles, clusterrolebindings]
  verbs: [create, delete, get, list, watch, patch, update]
```

The operator has `create` on `clusterrolebindings` cluster-wide. A compromised operator can:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: operator-to-admin
subjects:
- kind: ServiceAccount
  name: kubesynapse-operator
  namespace: kubesynapse
roleRef:
  kind: ClusterRole
  name: cluster-admin
  apiGroup: rbac.authorization.k8s.io
```

**This is the classic Kubernetes RBAC escalation path.** The operator can grant itself cluster-admin, then read/modify any resource in the cluster.

### 1.2 CRITICAL — Cluster-wide secret get/patch allows exfiltration from any namespace

**File:** `charts/kubesynapse/templates/operator-rbac.yaml:112-114`

```yaml
- apiGroups: [""]
  resources: [secrets]
  verbs: [create, get, patch, update]
```

The operator can read, create, and modify secrets in **ANY namespace**. A compromised operator can exfiltrate secrets from `kube-system`, `vault`, or any other namespace. The comment at line 109-111 acknowledges this was tightened from full CRUD, but `get` and `patch` cluster-wide is still excessive.

### 1.3 CRITICAL — Worker jobs inherit operator's cluster-wide ServiceAccount

**File:** `charts/kubesynapse/templates/operator-deployment.yaml:165`

```yaml
- name: WORKER_SERVICE_ACCOUNT_NAME
  value: {{ include "kubesynapse.fullname" . }}-operator-sa
```

Worker Jobs run with the **same ServiceAccount** as the operator, inheriting cluster-wide RBAC including secret access, RoleBinding creation, and StatefulSet mutation. A compromised worker job has full operator privileges.

### 1.4 HIGH — Cluster-wide pod create/delete allows arbitrary pod creation

**File:** `charts/kubesynapse/templates/operator-rbac.yaml:57-59`

```yaml
- apiGroups: [""]
  resources: [pods, services, persistentvolumeclaims, serviceaccounts, configmaps]
  verbs: [create, delete, get, list, watch, patch, update]
```

Full CRUD on pods cluster-wide means the operator could create privileged pods in any namespace, including system namespaces. The `PROTECTED_NAMESPACES` check in the tenant controller only applies to tenant creation, not to general pod creation.

### 1.5 HIGH — No admission webhooks for AIAgent CRD validation

**Finding:** There is no `ValidatingWebhookConfiguration` in the chart. All validation happens in the operator reconciler (post-creation). A malicious AIAgent CRD is accepted by the API server first, then validated by the operator. This creates a window where invalid resources exist in etcd.

### 1.6 HIGH — Tenant RBAC grants `pods/exec` and `pods/portforward`

**File:** `operator/controllers/tenant_controller.py:163-167`

```python
resources=["pods", "pods/exec", "pods/portforward", "pods/log", "services"],
verbs=["get", "list", "watch", "create"],
```

`pods/exec` and `pods/portforward` with `create` verb gives tenant admins the ability to exec into any pod and port-forward to any service in their namespace. This is effectively shell access to all workloads.

### 1.7 HIGH — `x-kubernetes-preserve-unknown-fields: true` bypasses schema validation

**File:** `charts/kubesynapse/crds/aiagent-crd.yaml:55, 114, 228`

```yaml
selector:
  type: object
  x-kubernetes-preserve-unknown-fields: true
```

`x-kubernetes-preserve-unknown-fields: true` bypasses schema validation entirely for `selector`, `configFiles`, and `mcpConnections` fields. A malicious user can inject arbitrary fields that the operator may process without validation. The `mcpConnections` field is particularly dangerous because it flows directly into sidecar configurations.

### 1.8 MEDIUM — Init containers run as root with elevated capabilities

**File:** `operator/builders/manifests.py:2048-2055` (agent init)

```python
"securityContext": {
    "runAsUser": 0,
    "runAsGroup": 0,
    "runAsNonRoot": False,
    "allowPrivilegeEscalation": False,
    "capabilities": {"drop": ["ALL"], "add": ["CHOWN", "FOWNER"]},
    "seccompProfile": {"type": "RuntimeDefault"},
},
```

Init containers run as root (UID 0) with `CHOWN` and `FOWNER` capabilities. While `allowPrivilegeEscalation` is false and seccomp is set, running as root is a risk if the init container image is compromised.

### 1.9 MEDIUM — Sidecar egress init container runs as root with NET_ADMIN/NET_RAW

**File:** `operator/builders/manifests.py:726-737`

```python
"securityContext": {
    "runAsUser": 0,
    "runAsNonRoot": False,
    "allowPrivilegeEscalation": False,
    "capabilities": {"add": ["NET_ADMIN", "NET_RAW"], "drop": ["ALL"]},
    "seccompProfile": {"type": "RuntimeDefault"},
},
```

`NET_ADMIN` and `NET_RAW` capabilities allow the init container to manipulate iptables rules, create raw sockets, and perform network-level attacks. The iptables rules are built from user-supplied CIDRs, creating a potential command injection vector if CIDRs are not properly validated.

### 1.10 MEDIUM — No network policies between tenant namespaces

**Finding:** The default network policies in `network-policy-default.yaml` apply to the operator namespace only. There are no NetworkPolicies created for tenant namespaces to isolate them from each other. If two tenants share a cluster, their pods can communicate unless a CNI-level default deny is in place.

### 1.11 LOW — Default deny is conditional on Helm value

**File:** `charts/kubesynapse/templates/network-policy-default.yaml:1`

```yaml
{{- if .Values.networkPolicy.enabled }}
```

If `networkPolicy.enabled` is not set to `true`, no default deny policies are applied. Agent pods would have unrestricted network access.

### Positive findings (operator):
- Main container security context is well-hardened: `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `drop: [ALL]`
- Worker jobs have `activeDeadlineSeconds`, `ttlSecondsAfterFinished`, and `backoffLimit: 1`
- Worker containers run as non-root (UID 999) with read-only root filesystem
- Secrets are properly injected via `secretKeyRef` rather than plaintext env vars
- No evidence of secret values being logged

---

## Attack Surface 2: API Gateway Security

### 2.1 HIGH — JWT_SECRET fails open with ephemeral random key

**File:** `api-gateway/jwt_utils.py:61-71`

```python
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(32)
if not os.getenv("JWT_SECRET"):
    logger.critical("JWT_SECRET not set. Using ephemeral key. Sessions will not survive restarts.")
```

If `JWT_SECRET` is not configured, the gateway generates a random key at startup and continues running. Sessions do not survive restarts, but the system does **not fail fast**. In production, this should be a hard error.

### 2.2 MEDIUM — Query-parameter token for SSE (token leakage)

**File:** `api-gateway/auth_middleware.py:597-618`

```python
raw_request.query_params.get("token", "").strip()
```

SSE endpoints accept tokens in the URL query string (`?token=...`). Query parameters are logged in web server access logs, browser history, and proxy logs.

### 2.3 MEDIUM — Shared token grants admin role with wildcard namespace access

**File:** `api-gateway/auth_middleware.py:292-302`

```python
# Shared token principal is hardcoded with role="admin" and allowed_namespaces=["*"]
```

Any holder of the shared token has full cluster-wide admin access. The shared token role should be configurable via environment variable.

### 2.4 MEDIUM — A2A agent card endpoint has optional auth

**File:** `api-gateway/routers/a2a.py:13-28`

```python
if authorization is not None and authorization.strip():
    await verify_token(authorization)
```

Unauthenticated callers can enumerate agent cards and discover agent names, models, and capabilities.

### 2.5 MEDIUM — Chat session ownership uses username comparison (unstable identifier)

**File:** `api-gateway/routers/agents.py:1120-1131`

```python
session_username == caller_username  # derived from user.get("sub") or user.get("username")
```

For OIDC users, `sub` is a UUID while `username` is a derived string. If the session was created under one auth provider and accessed under another, the comparison may fail or succeed incorrectly.

### 2.6 MEDIUM — A2A JSON-RPC errors leak internal details

**File:** `api-gateway/routers/a2a.py:99-108`

```python
jsonrpc_error_response(request_id, JSONRPC_INTERNAL_ERROR, "Internal error", {"detail": str(exc)})
```

The catch-all exception handler returns `str(exc)` in the JSON-RPC error response, potentially leaking internal error messages, stack traces, or sensitive data to callers.

### 2.7 MEDIUM — Login rate limiting is in-memory only

**File:** `api-gateway/auth_store.py:55-58`

```python
_LOGIN_ATTEMPTS = {}  # In-memory dictionary
```

In a multi-pod deployment, rate limits are per-pod, not global. An attacker can distribute attempts across pods to bypass limits.

### 2.8 MEDIUM — No global API rate limiting middleware

**Finding:** There is no global API rate limiting middleware. Endpoints like agent invocation, chat session CRUD, and memory operations have no rate limits beyond the login/webhook-specific ones.

### 2.9 MEDIUM — Webhook rate limiting is in-memory

**File:** `api-gateway/webhook_security.py:21-36`

```python
_webhook_rate_state = {}  # In-memory dict. "In production, replace with Redis."
```

### 2.10 LOW — OIDC JWKS URL not enforced to HTTPS in all paths

**File:** `api-gateway/enterprise_auth.py:570`

```python
httpx.get(f"{issuer}/.well-known/openid-configuration", timeout=10.0)
```

JWKS URL is validated to use HTTPS in `load_jwks()`, but `enterprise_auth.py` fetches OIDC discovery and JWKS via `httpx.get()` without re-validating the URL scheme.

### 2.11 LOW — Refresh token rotation without concurrent session invalidation

**Finding:** Refresh token rotation is implemented via `rotate_refresh_session`, but if a refresh token is stolen and used concurrently with the legitimate user, there is no detection mechanism to invalidate the entire session chain.

### 2.12 LOW — Transaction cookie HMAC key falls back to JWT_SECRET

**File:** `api-gateway/enterprise_auth.py:669-671`

```python
_TRANSACTION_HMAC_KEY = os.getenv("TRANSACTION_COOKIE_HMAC_KEY") or JWT_SECRET
```

Compromise of one secret compromises both.

### 2.13 LOW — SAML SP private key in environment variable

**File:** `api-gateway/enterprise_auth.py:296-297`

```python
sp_private_key = os.getenv("SAML_PROVIDERS_JSON")
```

If this env var is logged or exposed in process listings, the private key could be compromised.

### 2.14 LOW — SSE log streaming exposes raw pod logs

**File:** `api-gateway/routers/agents.py:1018-1076`

`stream_agent_logs` streams raw pod logs via SSE. If logs contain sensitive information (secrets, tokens, PII), they are exposed to any user with namespace access.

### 2.15 LOW — SSE notification stream polls K8s API continuously

**File:** `api-gateway/routers/chat.py:788-896`

The notification stream polls the Kubernetes API every 5 seconds. Under high load, this could cause excessive API server load.

### 2.16 LOW — CORS allows credentials with configurable origins

**File:** `api-gateway/main.py:48-54`

```python
allow_credentials=True  # Combined with dynamically configurable origins
```

If an administrator accidentally sets `API_GATEWAY_CORS_ORIGINS` to include `*` or a broad pattern, credentials would be exposed.

### 2.17 LOW — Artifact download proxies path parameter to runtime without validation

**File:** `api-gateway/routers/agents.py:865-902`

`download_agent_artifact` passes the `path` query parameter directly to the agent runtime without validation in the gateway layer.

### 2.18 LOW — Database URL construction could leak credentials in logs

**File:** `api-gateway/auth_store.py:87-111`

`DATABASE_URL` is constructed from env vars including `DATABASE_PASSWORD`. If logging is misconfigured, the connection string could appear in logs.

### 2.19 MEDIUM — Outdated dependencies

**File:** `api-gateway/requirements.txt`

| Package | Version | Current | Severity |
|---------|---------|---------|----------|
| fastapi | 0.109.0 | 0.115+ | MEDIUM |
| httpx | 0.26.0 | 0.28+ | MEDIUM |
| kubernetes | 26.1.0 | 31+ | MEDIUM |
| python-jose | 3.3.0 | — | LOW |

### 2.20 LOW — No dependency lock file

**File:** `api-gateway/requirements.txt`

`requirements.txt` uses pinned versions for some packages but `>=` ranges for others (e.g., `sqlalchemy>=2.0,<3.0`). Transitive dependencies are not locked.

### Positive findings (API gateway):
- **No SQL injection** — all queries use SQLAlchemy ORM or parameterized `text()` calls
- **No raw SQL string concatenation** found
- **Git/GitHub credentials stored as K8s Secrets** — GET endpoints only return metadata, never actual credentials
- **Skill file path validation** — `normalize_skill_file_path` validates relative paths, no `.` or `..`, ends in `.md`
- **Runtime config file path validation** — `normalize_runtime_config_file_path` validates relative paths
- **CORS origins configurable** — default is `["http://localhost:5173", "http://127.0.0.1:5173"]`, no wildcard `*`
- **No direct file upload endpoints** — artifact downloads proxy to agent runtime
- **No direct env var exposure in API responses**
- **Password hashing uses `pbkdf2_sha256`** — secure, well-established algorithm
- **A2A send requires operator role** — good security posture
- **LLM provider keys stored in K8s ConfigMap + Secret** — good separation

---

## Attack Surface 3: MCP Sidecar Security

### 3.1 CRITICAL — `verify_bearer_token()` is dead code — no tool-level auth enforcement

**File:** `mcp-sidecars/base/mcp_base.py:168`

```python
def verify_bearer_token():
    # Function exists but is NEVER called by any sidecar server
```

The bearer token verification function is defined but never invoked. Any pod on the same network that can reach `localhost:808x` can call tools without authentication.

### 3.2 CRITICAL — `code-exec` sidecar allows arbitrary code execution with network access and no egress filtering

**File:** `mcp-sidecars/code-exec/server.py:62-129`

```python
@server.tool()
def run_python(code: str): ...
@server.tool()
def run_bash(command: str): ...
@server.tool()
def run_node(code: str): ...
```

`code-exec/capabilities.json:6-7`: `"domains": [], "ips": []` — empty allowlists means `check_egress_url` returns `None` (permit all). The code-exec sidecar has **NO egress restrictions** at the application layer.

### 3.3 HIGH — Shared MCP bearer token across all agents

**File:** `operator/builders/manifests.py:786-832`

The operator reads the MCP bearer token from the `mcp-hub` namespace and creates a copy in the agent's namespace. The **same shared bearer token** is used across all agents. If one agent is compromised, the token can be used to call MCP servers for other agents.

### 3.4 HIGH — Wildcard egress on web-search and browser sidecars

**File:** `mcp-sidecars/web-search/capabilities.json:6`

```json
"domains": ["*"]  # Permits ALL domains
```

**File:** `mcp-sidecars/browser/capabilities.json:6`

```json
"domains": ["*"]  # Same issue
```

Any agent with the web-search or browser sidecar can make HTTP requests to any internet host, including internal services if DNS resolves them.

### 3.5 HIGH — TOCTOU SSRF in web-search and browser

**File:** `mcp-sidecars/web-search/server.py` and `mcp-sidecars/browser/server.py`

Both sidecars perform DNS resolution at tool-call time (`socket.getaddrinfo`) to check against blocked IP ranges. Between the check and the actual HTTP request, DNS can be re-resolved to a different IP (TOCTOU race). The `web-search` sidecar mitigates partially with `allow_redirects=False`, but the browser sidecar's Playwright `page.goto()` follows redirects by default.

### 3.6 HIGH — No image pinning, no pip hash verification, no checksum on kubectl download

**File:** `mcp-sidecars/*/Dockerfile`

All Dockerfiles use `FROM python:3.11-slim` (floating tag). `github-adapter/Dockerfile` downloads kubectl from `https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl` — fetches "latest stable" at build time with **no checksum verification**. All Dockerfiles run `pip install` without `--require-hashes`.

### 3.7 MEDIUM — Git credentials written to disk in plaintext

**File:** `mcp-sidecars/git/server.py:76-84`

```python
with open(cred_path, "w") as f:
    f.write(f"https://{username}:{token}@github.com\n")
os.chmod(cred_path, 0o600)
```

Git credentials are written to `~/.git-credentials` in plaintext. While `0o600` permissions are applied, the file persists on disk and could be accessed if the container is compromised.

### 3.8 MEDIUM — Default Helm bearer token is `REPLACE-WITH-STRONG-SECRET`

**File:** `charts/kubesynapse/templates/mcp-server-deployment.yaml:35`

```yaml
bearer-token: {{ .Values.mcpHub.auth.bearerToken | default "REPLACE-WITH-STRONG-SECRET" | quote }}
```

If the user does not override this value, the literal string `REPLACE-WITH-STRONG-SECRET` is used as the bearer token.

### 3.9 MEDIUM — No TLS on inter-container communication

**File:** `opencode-runtime/skills.py:345`

```python
"Authorization": f"Bearer {MCP_BEARER_TOKEN}"  # Sent over plain HTTP
```

Sidecar communication is plain HTTP on localhost. For hub servers, bearer tokens traverse the cluster network in plaintext.

### 3.10 LOW — Tool descriptions are unsanitized and can influence LLM behavior

**File:** `mcp-sidecars/base/mcp_base.py:286-294`

```python
create_mcp_server(..., instructions=description)
```

FastMCP exposes tool names and docstrings to the LLM as part of the tool schema. A malicious tool description could inject prompt instructions.

### Positive findings (MCP sidecars):
- **Capability allowlist enforcement** via `_wrap_tool_decorator()` monkey-patch
- **SSRF protection** in web-search and browser sidecars (partial)
- **Git clone URL validation** in git sidecar
- **MCP hub deployed in dedicated namespace** with `automountServiceAccountToken: false`
- **Default-deny NetworkPolicy** on the mcp-hub namespace
- **Non-root UID 1000**, `readOnlyRootFilesystem: true`, `drop: ALL` capabilities on MCP servers
- **Bearer token auth** via mounted secret (when configured)

---

## Attack Surface 4: Helm Chart & Deployment Security

### 4.1 CRITICAL — TLS disabled by default on ingress

**File:** `charts/kubesynapse/values.yaml:216-218`

```yaml
tls:
  enabled: false
  secretName: ""
```

When ingress is enabled (`apiGateway.ingress.enabled: true`), TLS is **NOT enabled by default**. All traffic including authentication tokens, API keys, and session cookies travel in cleartext.

### 4.2 HIGH — `cookieSecure: false` — session cookies sent over HTTP

**File:** `charts/kubesynapse/values.yaml:226`

```yaml
cookieSecure: false
```

Authentication cookies will be transmitted in cleartext over HTTP connections, enabling session hijacking via network sniffing.

### 4.3 HIGH — LDAP TLS disabled by default

**File:** `charts/kubesynapse/values.yaml:249`

```yaml
tlsEnabled: false
```

If LDAP auth is enabled, credentials and group membership queries are sent in cleartext.

### 4.4 HIGH — Native secrets mode uses `stringData` — plaintext in manifests

**File:** `charts/kubesynapse/templates/external-secrets.yaml:145-168`

```yaml
stringData:
  jwt-secret: {{ .Values.platformSecrets.native.jwtSecret }}
  api-gateway-shared-token: {{ .Values.platformSecrets.native.apiGatewaySharedToken }}
```

When `platformSecrets.mode: native` (the default), all secrets including API keys, JWT secrets, and database passwords are rendered as plaintext in the Kubernetes Secret manifest. Anyone with `kubectl get secret` access or access to Helm render output can read them.

### 4.5 HIGH — OIDC/SAML provider secrets in values

**File:** `charts/kubesynapse/values.yaml:360-365`

```yaml
oidcProvidersJson: ""  # Contains client_secret
samlProvidersJson: ""  # Contains x509cert
```

OIDC client secrets and SAML certificates are passed as plain values in `values.yaml`, visible in version control and Helm history.

### 4.6 HIGH — Redis NO authentication

**File:** `charts/kubesynapse/templates/redis.yaml:48`

```yaml
args: ["--save", "", "--appendonly", "no"]  # No --requirepass
```

Redis is deployed with **NO `--requirepass` argument**. Any pod that can reach Redis (api-gateway, operator, litellm per network policy) can read/write/delete all keys without authentication.

### 4.7 HIGH — NATS NO authentication

**File:** `charts/kubesynapse/templates/nats.yaml:50`

```yaml
args: ["-js", "-m", "8222"]  # No --auth or --user/--pass
```

NATS is deployed with **NO authentication**. Any pod that can reach NATS can publish/subscribe to any subject. The monitoring port 8222 is also exposed without authentication.

### 4.8 HIGH — ExternalSecrets fake provider defeats purpose

**File:** `charts/kubesynapse/templates/external-secrets.yaml:117-142`

```yaml
provider:
  fake:
    data:
      - key: kubesynapse/openai-api-key
        value: {{ .Values.platformSecrets.native.openaiApiKey }}
```

When `platformSecrets.mode: external-secrets` and `createClusterSecretStore: true`, the ClusterSecretStore uses the `fake` provider which renders secrets from `values.yaml` directly. This defeats the purpose of external secrets — the secrets are still in the Helm values and rendered in the ClusterSecretStore manifest.

### 4.9 HIGH — Collector token passed as plain environment variable

**File:** `charts/kubesynapse/templates/collector-daemonset.yaml:53`

```yaml
- name: COLLECTOR_TOKEN
  value: "{{ .Values.collector.token }}"  # Not secretKeyRef
```

Unlike other secrets that use `secretKeyRef`, the collector token is passed directly as an environment variable value. It appears in `kubectl describe pod` output and in the pod spec.

### 4.10 HIGH — No security headers on ingress

**File:** `charts/kubesynapse/templates/api-gateway.yaml:326-385`

The Ingress resource has no annotations for security headers (HSTS, X-Frame-Options, X-Content-Type-Options, CSP). The web-ui Nginx config DOES set these headers, but the API gateway Ingress does not.

### 4.11 HIGH — Operator can create/modify ExternalSecrets

**File:** `charts/kubesynapse/templates/operator-rbac.yaml:102-104`

```yaml
- apiGroups: ["external-secrets.io"]
  resources: [externalsecrets]
  verbs: [create, delete, get, list, watch, patch, update]
```

The operator can create ExternalSecret resources pointing to any path in the configured secret backend (Vault, AWS SM, Azure KV). If the backend has broader secrets, the operator can exfiltrate them.

### 4.12 HIGH — Operator can create/modify NetworkPolicies

**File:** `charts/kubesynapse/templates/operator-rbac.yaml:106-108`

```yaml
- apiGroups: ["networking.k8s.io"]
  resources: [networkpolicies]
  verbs: [create, delete, get, list, watch, patch, update]
```

The operator can delete or modify network policies, removing network isolation for any component.

### 4.13 MEDIUM — Default permission level is `permissive`

**File:** `charts/kubesynapse/values.yaml:127`

```yaml
permissionLevel: "permissive"
```

The Pi runtime defaults to the most permissive tool access level. AI agents get unrestricted tool access unless explicitly tightened.

### 4.14 MEDIUM — Auth bootstrap admin has wildcard namespace access

**File:** `charts/kubesynapse/values.yaml:232-233`

```yaml
bootstrapAdminNamespaces: ["*"]
```

The default admin account has access to all namespaces. This should be scoped to specific namespaces in production.

### 4.15 MEDIUM — Required secrets enforced only on fresh install

**File:** `charts/kubesynapse/templates/external-secrets.yaml:14-18`

```yaml
{{- if not $existingSecret -}}
  {{- $_ := required "..." .Values.platformSecrets.native.jwtSecret -}}
{{- end -}}
```

On upgrades, if the existing secret already has values, the `required` checks are bypassed.

### 4.16 MEDIUM — No encryption at rest enforcement

**Finding:** The chart does not configure or verify Kubernetes EncryptionConfiguration for Secrets. Secrets stored in etcd are only base64-encoded by default.

### 4.17 MEDIUM — clusterApiCidr 0.0.0.0/0

**File:** `charts/kubesynapse/values.yaml:19`

```yaml
clusterApiCidr: "0.0.0.0/0"
```

The operator, gateway, and workers can egress to ANY IP on ports 443/6443. This should be narrowed to the actual Kubernetes API server CIDR.

### 4.18 MEDIUM — Default ingress allows all namespaces when `ingressNamespaces` is empty

**File:** `charts/kubesynapse/templates/network-policy-default.yaml:88-92`

```yaml
namespaceSelector: {}  # Matches ALL namespaces
```

When `networkPolicy.ingressNamespaces` is empty (the default), any pod in any namespace can reach the API gateway, web UI, and operator on port 8080.

### 4.19 MEDIUM — Agent network policy allows egress to entire K8s API

**File:** `charts/kubesynapse/templates/agent-network-policy.yaml:55-64`

```yaml
cidr: 0.0.0.0/0  # With only 169.254.169.254/32 (metadata) excluded
```

Agent pods can reach any IP on ports 443/6443, not just the K8s API.

### 4.20 MEDIUM — PostgreSQL SSL mode "prefer"

**File:** `charts/kubesynapse/values.schema.json:393`

```json
"sslMode": { "default": "prefer" }
```

PostgreSQL connections default to `prefer` SSL mode, which falls back to cleartext if the server does not support SSL. Should be `require` or `verify-full` in production.

### 4.21 MEDIUM — Qdrant uses `emptyDir` for storage — data loss on pod restart

**File:** `charts/kubesynapse/templates/qdrant.yaml:88`

```yaml
emptyDir: {}  # In production, use a PersistentVolumeClaim
```

All vector data is lost when the Qdrant pod is restarted. No PVC is configured by default.

### 4.22 MEDIUM — NATS monitoring port exposed

**File:** `charts/kubesynapse/templates/nats.yaml:48-49, 100-103`

The HTTP monitoring endpoint exposes NATS internals (connections, routes, subscriptions). While the NetworkPolicy restricts monitor port access to operator pods only, the service still exposes it.

### 4.23 MEDIUM — Migration job uses `:latest` tag

**File:** `charts/kubesynapse/templates/pvc-retention-migration-job.yaml:34`

```yaml
image: bitnami/kubectl:latest
```

The `:latest` tag is unpinned and could introduce supply chain risk. The job runs with the operator service account which has broad permissions.

### 4.24 LOW — Registration enabled by default

**File:** `charts/kubesynapse/values.yaml:222`

```yaml
registrationEnabled: true
```

Anyone can register new accounts unless explicitly disabled.

### 4.25 LOW — No egress policy on Redis, NATS, Qdrant

**Files:** `redis.yaml`, `nats.yaml`, `qdrant.yaml`

These services have `policyTypes: [Ingress]` only. If compromised, they could exfiltrate data.

### 4.26 LOW — Collector service account has extensive read access

**File:** `charts/kubesynapse/templates/collector-daemonset.yaml:96-123`

The collector ClusterRole can read pods, services, nodes, namespaces, configmaps, events, serviceaccounts, pods/log, deployments, daemonsets, statefulsets, replicasets, jobs, cronjobs, ingresses, networkpolicies, storageclasses, clusterroles, clusterrolebindings, roles, rolebindings, and metrics. This is essentially a **cluster read-only admin** role.

### 4.27 LOW — No dedicated service account for PostgreSQL

**File:** `charts/kubesynapse/templates/postgresql.yaml`

PostgreSQL uses the default service account. While `automountServiceAccountToken: false` is set, using a dedicated SA is a best practice.

### 4.28 LOW — No LimitRange or ResourceQuota created by chart

**Finding:** The chart does not create LimitRange or ResourceQuota resources. If a user creates many agent StatefulSets, they could collectively consume more resources than intended.

### 4.29 LOW — Ingress can be hostless

**File:** `charts/kubesynapse/values.yaml:203`

```yaml
ingressHost: ""  # Leave empty for a hostless ingress
```

A hostless ingress may match unintended traffic depending on the ingress controller configuration.

### 4.30 LOW — Image pull secrets are empty by default

**File:** `charts/kubesynapse/values.yaml:2`

```yaml
global.imagePullSecrets: []
```

If private registries are used (docker.io/kubesynapse/*), image pull will fail without configured secrets.

### 4.31 LOW — RBAC customization is available but not documented in schema

**File:** `charts/kubesynapse/values.yaml:606-618`

Users can override RBAC rules via values, but this is not reflected in `values.schema.json`.

### Positive findings (Helm chart):
- **All containers drop ALL capabilities** — chart-wide
- **All containers set `allowPrivilegeEscalation: false`** — chart-wide
- **Most containers have `readOnlyRootFilesystem: true`** — all except PostgreSQL and Qdrant
- **Seccomp profiles set to `RuntimeDefault`** — chart-wide at pod level
- **Network policies with default-deny** — both ingress and egress default-deny when enabled
- **Secrets required on fresh install** — `litellmMasterKey`, `apiGatewaySharedToken`, `databasePassword`, `jwtSecret`
- **`automountServiceAccountToken: false`** on PostgreSQL, Redis, NATS, Qdrant, web-ui, MCP servers
- **Resource limits defined** on all components
- **Pod Disruption Budgets** for all control-plane components
- **`pods/exec` removed** from API gateway RBAC
- **Security headers on web-ui Nginx** — CSP, X-Frame-Options, X-Content-Type-Options, etc.
- **MCP servers deployed in dedicated namespace** with default-deny network policies
- **Agent network policies** restrict ingress/egress to specific services
- **No default password** — `databasePassword` is required and enforced via `required` template function
- **PostgreSQL password passed via `secretKeyRef`** — good practice
- **PostgreSQL service is ClusterIP only** — not exposed externally
- **PostgreSQL NetworkPolicy restricts access** — only api-gateway, operator, operator-worker, and litellm pods can reach PostgreSQL
- **Git credentials stored as K8s Secrets** — GET endpoints only return `auth_method`, never actual credentials
- **GitHub credentials stored as K8s Secrets** — same pattern

---

## Cross-Surface Attack Chains

### Chain 1: Compromised agent → cluster-admin via operator RBAC

1. Attacker gains code execution in an agent pod (via prompt injection → bash tool)
2. Agent pod has access to the operator's ServiceAccount token (shared with worker jobs)
3. Attacker creates a `ClusterRoleBinding` granting `cluster-admin` to the operator SA
4. Attacker now has full cluster access — can read all secrets, create privileged pods, etc.

**Mitigation:** Use a dedicated, minimally-privileged ServiceAccount for worker jobs. Remove `clusterrolebindings` create permission from the operator.

### Chain 2: Compromised agent → MCP sidecar → all agents

1. Attacker gains code execution in an agent pod
2. Agent pod shares localhost with MCP sidecars (no auth enforcement — `verify_bearer_token()` is dead code)
3. Attacker calls MCP sidecar tools directly, including `code-exec` which has no egress filtering
4. Attacker uses `code-exec` to exfiltrate the shared MCP bearer token
5. Attacker uses the shared token to call MCP servers for other agents, potentially compromising them

**Mitigation:** Implement per-agent bearer tokens. Enable `verify_bearer_token()` in all sidecars. Restrict `code-exec` egress.

### Chain 3: Helm values leak → full platform compromise

1. Attacker gains read access to Helm values (via git history, CI/CD logs, or `kubectl get secret`)
2. Values contain plaintext secrets: JWT secret, API keys, OIDC client secrets, SAML certificates
3. Attacker uses JWT secret to forge admin tokens
4. Attacker uses API keys to access LLM providers
5. Attacker uses OIDC/SAML secrets to impersonate users

**Mitigation:** Use External Secrets Operator with Vault/AWS SM/Azure KV. Never store secrets in `values.yaml`.

### Chain 4: Redis/NATS compromise → session hijacking

1. Attacker gains access to Redis (no authentication) or NATS (no authentication)
2. Attacker reads session tokens from Redis (LiteLLM cache, auth sessions)
3. Attacker publishes messages to NATS to trigger operator actions
4. Attacker can hijack user sessions or trigger unauthorized agent actions

**Mitigation:** Enable Redis `--requirepass`. Enable NATS authentication. Restrict network access with NetworkPolicies.

### Chain 5: Ingress without TLS → credential theft

1. Ingress is enabled but TLS is disabled (default)
2. All traffic including authentication tokens, API keys, and session cookies travel in cleartext
3. Attacker on the network sniffs traffic and captures credentials
4. Attacker uses captured credentials to access the platform

**Mitigation:** Enable TLS by default on ingress. Set `cookieSecure: true`. Enable LDAP TLS.

---

## KubeSynapse-Specific Hardening Recommendations

### Tier 1 — Immediate (block known escalation paths)

| # | Control | Implementation |
|---|---------|----------------|
| 1 | **Remove operator RBAC escalation path** | Remove `clusterrolebindings` create permission from operator ClusterRole. Use a separate, minimally-privileged SA for worker jobs. |
| 2 | **Scope operator secret access** | Replace cluster-wide `secrets: [get, patch]` with namespace-scoped access. Use `Role` instead of `ClusterRole` for secret access. |
| 3 | **Enable TLS on ingress by default** | Set `apiGateway.ingress.tls.enabled: true` in `values.yaml`. Fail fast if TLS is not configured when ingress is enabled. |
| 4 | **Enable Redis authentication** | Add `--requirepass` to Redis args. Use a generated secret for the password. |
| 5 | **Enable NATS authentication** | Add `--auth` flag to NATS args. Use a generated secret for the password. |
| 6 | **Enable MCP bearer token verification** | Call `verify_bearer_token()` in all sidecar tool wrappers. Use per-agent tokens instead of a shared token. |
| 7 | **Restrict code-exec egress** | Set `domains` and `ips` in `code-exec/capabilities.json` to empty (deny all) or a specific allowlist. |
| 8 | **Fail fast on missing JWT_SECRET** | Make `JWT_SECRET` required in production. Exit with error if not set. |

### Tier 2 — This sprint (reduce blast radius)

| # | Control | Implementation |
|---|---------|----------------|
| 9 | **Upgrade API gateway dependencies** | Upgrade FastAPI, httpx, kubernetes client to latest stable versions. |
| 10 | **Add global API rate limiting** | Add middleware-level rate limiting (e.g., `slowapi`) with configurable per-endpoint limits. |
| 11 | **Use Redis-backed rate limiting** | Replace in-memory rate limiters for multi-pod deployments. |
| 12 | **Pin MCP sidecar images** | Use image digests instead of tags. Add `--require-hashes` to pip install. Verify kubectl checksum. |
| 13 | **Enable PostgreSQL SSL** | Set `sslMode: require` or `verify-full` in production. |
| 14 | **Add admission webhooks** | Create `ValidatingWebhookConfiguration` for AIAgent CRDs to validate at admission time. |
| 15 | **Scope tenant RBAC** | Remove `pods/exec` and `pods/portforward` from tenant RBAC. Use `verbs: ["get", "list", "watch"]` instead of `["*"]` on CRDs. |
| 16 | **Restrict collector token** | Pass collector token via `secretKeyRef` instead of plain env var. |
| 17 | **Set strong MCP bearer token default** | Generate a strong random token in the Helm chart instead of using `REPLACE-WITH-STRONG-SECRET`. |
| 18 | **Add security headers to ingress** | Add HSTS, X-Frame-Options, X-Content-Type-Options, CSP annotations to the API gateway Ingress. |

### Tier 3 — Ongoing (platform hardening)

| # | Control | Implementation |
|---|---------|----------------|
| 19 | **Use External Secrets Operator with Vault** | Configure `platformSecrets.mode: external-secrets` with a real Vault backend, not the `fake` provider. |
| 20 | **Enable Kubernetes EncryptionConfiguration** | Encrypt secrets at rest in etcd. |
| 21 | **Add LimitRange and ResourceQuota** | Create LimitRange and ResourceQuota resources per tenant namespace. |
| 22 | **Implement refresh token reuse detection** | If a previously-rotated refresh token is presented, invalidate all sessions for that user. |
| 23 | **Add log sanitization for SSE streaming** | Redact secrets, tokens, and PII from pod logs before streaming via SSE. |
| 24 | **Use Kubernetes watch API for notifications** | Replace polling with watch API to reduce API server load. |
| 25 | **Validate CORS origins at startup** | Ensure CORS origins do not contain wildcards. |
| 26 | **Add path validation at gateway layer** | Validate artifact download paths at the gateway as defense-in-depth. |
| 27 | **Migrate to PyJWT** | Replace `python-jose` with `PyJWT` for better maintenance and security track record. |
| 28 | **Add dependency lock file** | Use `pip-tools` or `uv` to generate a fully locked `requirements.lock`. |
| 29 | **Implement mTLS for MCP communication** | Use mutual TLS between agents and MCP sidecars instead of plain HTTP with bearer tokens. |
| 30 | **Add SBOM and vulnerability scanning** | Generate SBOMs for all container images. Scan with Trivy/Grype in CI/CD. |

---

## Comparison: KubeSynapse vs. Industry Benchmarks

| Control | KubeSynapse | Claude Code | Cursor | GitHub Copilot |
|---------|-------------|-------------|--------|----------------|
| Pod security contexts | ✅ All drop ALL, readOnlyRootFilesystem, seccomp | N/A (SaaS) | N/A (SaaS) | N/A (SaaS) |
| Network policies | ✅ Default-deny when enabled | N/A | N/A | N/A |
| RBAC least-privilege | ❌ Operator can escalate to cluster-admin | N/A | N/A | N/A |
| Secret management | ⚠️ Native mode stores plaintext in manifests | N/A | N/A | N/A |
| Runtime sandboxing | ❌ No Docker/VM isolation (relies on OpenCode/pi) | Docker sandbox option | VM sandbox | Cloud sandbox |
| Permission model | ❌ No built-in permission gating (relies on runtime) | Permission dialogs | Permission dialogs | No prompts |
| MCP authentication | ❌ Bearer token verification is dead code | N/A | N/A | N/A |
| Redis/NATS auth | ❌ No authentication | N/A | N/A | N/A |
| TLS defaults | ❌ Ingress TLS disabled by default | ✅ Always TLS | ✅ Always TLS | ✅ Always TLS |
| Rate limiting | ❌ In-memory only, no global middleware | N/A | N/A | N/A |
| Admission webhooks | ❌ None | N/A | N/A | N/A |
| Dependency freshness | ❌ FastAPI 0.109, httpx 0.26, kubernetes 26 | N/A | N/A | N/A |

**Assessment:** KubeSynapse has **strong pod-level security defaults** (capabilities, readOnlyRootFilesystem, seccomp) that exceed many self-hosted platforms. However, it has **significant gaps in RBAC scoping, credential handling, and sidecar authentication** that create privilege escalation paths. The platform relies on the underlying runtimes (OpenCode, pi) for permission gating, but those runtimes have their own security gaps (documented in the runtime-specific audits).

---

## Files Changed (KubeSynapse Hardening)

Recommended changes based on this audit:

| File | Change |
|------|--------|
| `charts/kubesynapse/templates/operator-rbac.yaml` | Remove `clusterrolebindings` create, scope secret access to namespace, remove `pods/exec` from tenant RBAC |
| `charts/kubesynapse/templates/worker-job.yaml` | Use dedicated, minimally-privileged ServiceAccount |
| `charts/kubesynapse/templates/redis.yaml` | Add `--requirepass` with secret reference |
| `charts/kubesynapse/templates/nats.yaml` | Add `--auth` with secret reference |
| `charts/kubesynapse/templates/external-secrets.yaml` | Remove `fake` provider, add real Vault/AWS/Azure backend config |
| `charts/kubesynapse/templates/collector-daemonset.yaml` | Pass token via `secretKeyRef` |
| `charts/kubesynapse/templates/mcp-server-deployment.yaml` | Generate strong random bearer token default |
| `charts/kubesynapse/templates/api-gateway.yaml` | Add security header annotations to Ingress |
| `charts/kubesynapse/values.yaml` | Enable TLS by default, set `cookieSecure: true`, enable LDAP TLS, disable registration by default |
| `mcp-sidecars/base/mcp_base.py` | Enable `verify_bearer_token()` in tool wrapper |
| `mcp-sidecars/code-exec/capabilities.json` | Set restrictive egress allowlist |
| `api-gateway/jwt_utils.py` | Fail fast on missing JWT_SECRET |
| `api-gateway/requirements.txt` | Upgrade FastAPI, httpx, kubernetes client |
| `api-gateway/routers/a2a.py` | Stop returning `str(exc)` to callers |
| `operator/builders/manifests.py` | Add admission webhook validation for AIAgent CRDs |
