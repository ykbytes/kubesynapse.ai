# Security Audit & Fix Prompt — KubeSynapse AI Agent Sandbox

> **Usage**: Copy this entire prompt into an AI coding assistant session that has access to
> the KubeSynapse workspace. The prompt is designed for maximum accuracy by referencing
> exact file paths, function names, line patterns, and known vulnerability classes specific
> to this codebase.

---

## PROMPT START

You are a senior application security engineer performing a comprehensive security audit
of the **KubeSynapse AI Agent Sandbox** — a Kubernetes-native platform that orchestrates
AI agents with LLM access, tool execution, and multi-tenant isolation. The platform is
deployed on Kubernetes v1.33.0 via Helm.

### Architecture Overview

| Component | Language | Entry Point | Purpose |
|-----------|----------|-------------|---------|
| API Gateway | Python / FastAPI | `api-gateway/main.py` | REST API, auth, proxy to K8s |
| Operator | Python / Kopf | `operator/main.py` | CRD reconciler, creates agent pods |
| Agent Runtime | Python / LangGraph | `agent-runtime/agent_logic.py` | LLM orchestration + tool calls |
| Goose Runtime | Python wrapper | `goose-runtime/main.py` | Alternative agent runtime |
| Codex Runtime | Python wrapper | `codex-runtime/main.py` | OpenAI Codex agent runtime |
| OpenCode Runtime | Node.js/Python | `opencode-runtime/main.py` | OpenCode agent runtime |
| Web UI | React + TypeScript | `web-ui/src/` | SPA frontend (Vite + Tailwind) |
| 9 MCP Sidecars | Python / FastMCP | `mcp-sidecars/*/server.py` | Tool servers (code-exec, browser, git, database, docs, k8s, rag, messaging, web-search) |
| MCP Base | Python | `mcp-sidecars/base/mcp_base.py` | Shared auth + server bootstrap for all sidecars |
| Helm Chart | YAML | `charts/kubesynapse/` | Kubernetes deployment manifests |

### Auth Stack

- **Local auth**: bcrypt passwords in PostgreSQL (`api-gateway/auth_store.py`)
- **JWT**: HS256 tokens, created in `api-gateway/jwt_utils.py`, validated in `verify_token()` dependency
- **OIDC**: Multi-provider, flows in `api-gateway/enterprise_auth.py` (`build_oidc_authorization_request`, `exchange_oidc_code`)
- **SAML**: Multi-provider, flows in `api-gateway/enterprise_auth.py` (`build_saml_authorization_request`, `exchange_saml_response`)
- **LDAP**: Bind-based auth in `enterprise_auth.py` (`authenticate_ldap_user`)
- **MCP Bearer Token**: Shared secret for sidecar auth (`mcp-sidecars/base/mcp_base.py`)
- **A2A (Agent-to-Agent)**: Direct invocation at `POST /a2a/{assistant_id}/invoke`

### Data Flow

```
User → Web UI → API Gateway → K8s API (CRDs)
                    ↓
              Operator watches CRDs → creates StatefulSets
                    ↓
              Agent Pod runs LLM loop
                    ↓
              Agent calls MCP sidecars (code-exec, browser, git, db, etc.)
                    ↓
              MCP sidecars execute actions (subprocess, HTTP, SQL, filesystem)
```

---

## AUDIT SCOPE — Examine every file below and fix all issues found

### 1. Authentication & Authorization Vulnerabilities

**Files to audit**:
- `api-gateway/main.py` — all 54 routes; verify every non-auth route has `Depends(verify_token)`
- `api-gateway/jwt_utils.py` — JWT creation, validation, algorithm, secret handling
- `api-gateway/enterprise_auth.py` — OIDC token validation, SAML assertion handling, LDAP escaping
- `api-gateway/auth_store.py` — password hashing, session management, user enumeration

**Known areas of concern — investigate and fix**:
- [ ] **OIDC ID token validation**: `exchange_oidc_code()` may use `jwt.get_unverified_claims()` to extract claims without verifying the token signature. This allows a malicious OIDC provider or MITM to forge identity tokens. Find where ID token claims are extracted and ensure full signature verification using the provider's JWKS.
- [ ] **OIDC discovery cache**: The OIDC well-known configuration is fetched and cached without a TTL. A poisoned cache entry persists forever. Add a TTL (e.g. 1 hour) to the cached discovery metadata.
- [ ] **OIDC audience validation**: Check if the `aud` claim validation handles both string and list formats correctly. The check may fail silently when `aud` is a list containing the client ID.
- [ ] **A2A endpoint authentication**: `POST /a2a/{assistant_id}/invoke` appears to have NO authentication. Any pod in the cluster can invoke any agent. Add bearer token or mTLS auth.
- [ ] **JWT secret fallback**: If `JWT_SECRET` and `API_GATEWAY_SHARED_TOKEN` are both empty, the code may generate an ephemeral random secret that changes on pod restart, invalidating all tokens. Ensure the gateway refuses to start without a configured secret.
- [ ] **Rate limiting gaps**: Verify rate limiting exists on `/api/auth/login`, `/api/auth/register`. Check if `/api/admin/users` POST/PATCH endpoints are also rate-limited to prevent brute-force user enumeration.
- [ ] **LDAP TLS enforcement**: Check if `authenticate_ldap_user()` enforces TLS/StartTLS. If LDAP_URL uses `ldap://` (not `ldaps://`), credentials may transit in cleartext.
- [ ] **SAML replay protection**: Verify that SAML assertions include and validate `NotOnOrAfter`, `InResponseTo`, and that a replay cache prevents re-use of assertions.
- [ ] **Session fixation**: After successful login (local, OIDC, SAML, LDAP), verify that a new session ID is generated and the old one is invalidated.

### 2. Injection & Input Validation

**Files to audit**:
- `operator/main.py` — CRD spec fields used in pod templates, env vars, labels
- `api-gateway/main.py` — request body/query param handling in all route handlers
- `agent-runtime/agent_logic.py` — LLM response parsing, tool call dispatch
- `agent-runtime/guardrails.py` — guardrail enforcement logic

**Known areas of concern — investigate and fix**:
- [ ] **CRD spec.systemPrompt injection**: The operator passes `spec.systemPrompt` directly into the agent pod's `AGENT_SYSTEM_PROMPT` env var without any sanitization. A malicious tenant could craft a system prompt that instructs the LLM to exfiltrate secrets or bypass guardrails. Add length limits and consider content filtering.
- [ ] **CRD spec.gitConfig.repoUrl injection**: `spec.gitConfig.repoUrl` is passed to `GIT_REPO_URL` env var without URL validation. A malicious URL could cause the git sidecar to clone from internal services, leak credentials via auth URLs, or trigger SSRF. Validate the URL scheme and hostname.
- [ ] **CRD spec.image override**: Check if agent CRD specs can override the container image. If so, a tenant could run arbitrary code. Ensure image fields are either admin-only or validated against an allowlist.
- [ ] **K8s label injection**: When the operator creates pods/services from CRD spec fields (agent name, tenant name), verify they are sanitized via `slugify_name()` or equivalent before use in K8s labels/selectors. Unsanitized labels can break selectors or cause cross-tenant resource matching.
- [ ] **Log injection**: Search for any `logger.info(f"...{user_input}...")` or `logger.error(f"...{request_data}...")` patterns in api-gateway/main.py that could allow log forging via newlines or control characters.
- [ ] **LLM tool call validation**: In `agent-runtime/agent_logic.py`, verify that tool names extracted from LLM responses are validated against the configured tool allowlist before dispatch. An LLM could hallucinate a tool name that maps to an unintended function.

### 3. MCP Sidecar Security (Tool Execution Layer)

**Files to audit**:
- `mcp-sidecars/code-exec/server.py` — arbitrary code execution
- `mcp-sidecars/browser/server.py` — web browsing (SSRF)
- `mcp-sidecars/database/server.py` — SQL execution
- `mcp-sidecars/documents/server.py` — file I/O (path traversal)
- `mcp-sidecars/git/server.py` — git operations + GitHub API
- `mcp-sidecars/kubernetes/server.py` — K8s resource access
- `mcp-sidecars/web-search/server.py` — web search API calls
- `mcp-sidecars/rag/server.py` — vector DB operations
- `mcp-sidecars/messaging/server.py` — NATS messaging
- `mcp-sidecars/base/mcp_base.py` — shared auth

**Known areas of concern — investigate and fix**:
- [ ] **Code-exec sandbox escape**: `run_python()`, `run_bash()`, and `run_node()` in `code-exec/server.py` execute user-supplied code via subprocess. Verify: (a) no network access from the subprocess, (b) filesystem writes are contained, (c) the process cannot read environment variables containing secrets (e.g., via `os.environ` in Python code), (d) resource limits (CPU/memory) are enforced at the process level.
- [ ] **Code-exec environment leak**: Even with output masking, the executed code itself can access `os.environ` before output. Consider running code in a subprocess with a sanitized environment (only passing safe env vars).
- [ ] **Browser sidecar cookie/auth theft**: `browse_url()` navigates to user-supplied URLs. If it runs a real browser, the AI could instruct it to visit an attacker site that steals session cookies or performs drive-by downloads. Verify Playwright/browser is configured with `--no-sandbox` disabled and cookies are isolated.
- [ ] **Database sidecar schema modification**: Verify that even with `_validate_query()` blocking DML/DDL keywords, an attacker cannot bypass via: (a) Unicode homoglyphs, (b) SQL comments (`/**/`), (c) hex-encoded strings, (d) `COPY TO` (PostgreSQL), (e) function calls like `pg_read_file()` or `lo_export()`.
- [ ] **Kubernetes sidecar escalation**: The K8s sidecar reads resources. Verify it cannot: (a) access secrets even via label selectors or field selectors that bypass the blocklist, (b) read `configmaps` that contain secret data, (c) access the K8s service account token mounted in the pod.
- [ ] **MCP auth bypass via direct HTTP**: MCP sidecars listen on localhost ports within the agent pod. Verify that the agent container cannot call sidecar ports directly (bypassing bearer token auth) since they share the same network namespace.
- [ ] **RAG sidecar injection**: Check if RAG queries can inject into the vector DB (Qdrant) to manipulate retrieval results or extract other tenants' data. Verify collection isolation per tenant.
- [ ] **Messaging sidecar NATS scope**: Verify the messaging sidecar cannot subscribe to arbitrary NATS subjects. A malicious agent could eavesdrop on other agents' messages or platform events.

### 4. Kubernetes Cluster Security

**Files to audit**:
- `charts/kubesynapse/templates/operator-rbac.yaml` — RBAC roles
- `charts/kubesynapse/templates/agent-network-policy.yaml` — egress rules
- `charts/kubesynapse/templates/postgresql.yaml` — DB network isolation
- `charts/kubesynapse/templates/litellm-deployment.yaml` — LLM proxy isolation
- `charts/kubesynapse/templates/web-ui.yaml` — frontend pod security
- `charts/kubesynapse/values.yaml` — default configuration
- `operator/main.py` — pod security contexts, volume mounts, init containers

**Known areas of concern — investigate and fix**:
- [ ] **Operator ClusterRole scope**: The operator has cluster-wide permissions. Check if it truly needs ClusterRole or if a namespaced Role would suffice. At minimum, verify secrets access is limited to specific secret names (not all secrets in all namespaces).
- [ ] **Agent pod service account**: Verify each agent pod uses a dedicated service account with minimal permissions, NOT the default service account. Check `automountServiceAccountToken` is false where possible.
- [ ] **Network policy completeness**: Verify that every pod type has a NetworkPolicy. Check for pods that are NOT covered by any policy (e.g., NATS, Redis, Qdrant, operator).
- [ ] **Egress to external internet**: Agent pods can currently reach the K8s API. Check if they can also reach the internet (for LLM API calls via LiteLLM). If yes, this could be used for data exfiltration. Ensure egress is restricted to only LiteLLM, Qdrant, and MCP sidecars.
- [ ] **Cross-namespace attacks**: The operator creates tenant namespaces. Verify that agents in tenant namespaces cannot access resources in `ai-platform` (the control plane namespace) via network policies or RBAC.
- [ ] **PodSecurityStandard enforcement**: Check if a PodSecurity admission controller is enforcing `restricted` or `baseline` standards on agent namespaces. Without this, agents could mount hostPath volumes or use privileged containers.
- [ ] **Resource exhaustion (DoS)**: Verify all pods have resource limits (CPU, memory). Check if ResourceQuotas are set on tenant namespaces. Verify LimitRanges prevent a single agent from consuming all cluster resources.

### 5. Supply Chain & Container Security

**Files to audit**:
- All `*/Dockerfile` (17 total)
- All `*/requirements.txt` and `web-ui/package.json`
- `charts/kubesynapse/values.yaml` — default image tags

**Known areas of concern — investigate and fix**:
- [ ] **Goose runtime image tag**: `goose-runtime/Dockerfile` uses `FROM ghcr.io/block/goose:latest` — a mutable tag. Pin to a specific digest.
- [ ] **OpenCode runtime supply chain**: `opencode-runtime/Dockerfile` downloads and executes `curl -fsSL https://bun.sh/install | bash` at build time. This is a supply chain attack vector. Pin a specific version or use a pre-built bun binary.
- [ ] **Unpinned Python dependencies**: `agent-runtime/requirements.txt` uses wide ranges like `langgraph>=0.2,<1.0` which allows major behavior changes. Pin to exact versions or narrow the range.
- [ ] **No image digest verification**: Helm templates use `image: repo:tag` without digest pinning. An attacker who compromises the registry can swap images. Consider supporting image digests.
- [ ] **Base image CVEs**: All Python containers use `python:3.11-slim`. Check for known CVEs in this base image and consider alternatives (distroless, chainguard).

### 6. Secrets Management

**Files to audit**:
- `charts/kubesynapse/templates/external-secrets.yaml`
- `charts/kubesynapse/values.yaml` — default secret values
- `deploy/values.dockerhub.local.yaml` — deployment secrets
- `api-gateway/jwt_utils.py` — JWT secret handling
- `operator/main.py` — secret creation and propagation

**Known areas of concern — investigate and fix**:
- [ ] **Hardcoded default secrets**: `values.yaml` contains `masterKey: "replace-me-litellm-master-key"`. Ensure Helm install fails or warns loudly if default secrets are not overridden.
- [ ] **Secret rotation**: There is no mechanism to rotate the MCP bearer token, JWT secret, or LiteLLM master key without downtime. Document or implement rotation procedures.
- [ ] **Secret in env vars**: Many secrets are passed as environment variables (`LITELLM_MASTER_KEY`, `MCP_BEARER_TOKEN`, `DATABASE_PASSWORD`). These appear in `kubectl describe pod` output, container runtime inspect, and process listings. Consider using volume-mounted secrets.
- [ ] **Docker Hub PAT in values**: `deploy/values.dockerhub.local.yaml` references `dockerhub-regcred`. Verify the registry credential secret is not committed to git or logged.

### 7. Web UI / Frontend Security

**Files to audit**:
- `web-ui/src/` — all React components
- `web-ui/nginx/` — nginx configuration
- `api-gateway/main.py` — CSP headers, CORS configuration

**Known areas of concern — investigate and fix**:
- [ ] **CORS configuration**: Check if `CORSMiddleware` in `api-gateway/main.py` allows overly broad origins (e.g., `allow_origins=["*"]`). It should only allow the specific web-ui origin.
- [ ] **CSP header completeness**: Verify Content-Security-Policy includes: `default-src 'self'`, `script-src` without `unsafe-inline`/`unsafe-eval`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`.
- [ ] **Markdown/HTML rendering XSS**: The web UI renders agent responses which may contain markdown. Verify all markdown rendering uses a sanitizer (e.g., DOMPurify) and does not allow raw HTML.
- [ ] **WebSocket security**: If the web UI uses WebSocket for streaming, verify the WebSocket upgrade includes origin checking and authentication.
- [ ] **Sourcemap exposure**: Check if production builds include source maps that could reveal application logic.

### 8. Multi-Tenancy Isolation

**Files to audit**:
- `operator/main.py` — tenant namespace creation, RBAC binding
- `api-gateway/main.py` — tenant/namespace-scoped queries
- `api-gateway/auth_store.py` — user-to-namespace mapping

**Known areas of concern — investigate and fix**:
- [ ] **Cross-tenant data access**: When the API gateway queries agents/workflows/evals, verify it always filters by the authenticated user's allowed namespaces. Check every K8s API call for namespace scoping.
- [ ] **Tenant namespace escape**: When the operator creates resources in tenant namespaces, verify it cannot be tricked into creating resources in `kube-system`, `default`, or `ai-platform` via CRD spec manipulation.
- [ ] **Shared MCP sidecar state**: MCP sidecars run as containers within agent pods. If sidecars use local filesystem state (e.g., downloaded files, git clones), verify state is isolated between agent invocations and between tenants.
- [ ] **LiteLLM key isolation**: All agents share the same LiteLLM proxy with the same master key. Verify that one agent cannot see another agent's LLM request history or API keys via the LiteLLM admin API.

---

## OUTPUT FORMAT

For each vulnerability found, report:

```
### [SEVERITY: CRITICAL/HIGH/MEDIUM/LOW] — Title

**File**: `path/to/file.py` (lines X-Y)
**Category**: (e.g., Authentication Bypass, Injection, SSRF, etc.)
**Description**: What the vulnerability is and how it can be exploited.
**Impact**: What an attacker gains.
**Fix**: The exact code change to apply.
```

After reporting all findings, apply the fixes directly to the source files. Prioritize by severity (CRITICAL first). For each fix:
1. Show the exact `oldString → newString` change
2. Verify the fix does not break existing functionality
3. Note if the fix requires a container rebuild or Helm upgrade

---

## PREVIOUSLY FIXED (Skip These)

The following vulnerabilities have already been addressed in revisions 18-19. Do NOT re-report these:

- ✅ XSS in web UI (revision 18)
- ✅ Unsigned cookies → signed HttpOnly cookies (revision 18)
- ✅ SAML CSRF via relay state HMAC (revision 18)
- ✅ Open redirect in auth callbacks (revision 18)
- ✅ Error message information leaking (revision 18)
- ✅ Missing CSP headers (revision 18)
- ✅ Unbounded pagination loops (revision 18)
- ✅ K8s sidecar unrestricted resource access → resource type allowlist (revision 19)
- ✅ Database sidecar SQL injection → SELECT-only + connection string removal (revision 19)
- ✅ Browser sidecar SSRF → IP blocklist + DNS resolution check (revision 19)
- ✅ Documents sidecar path traversal → `_validate_file_path()` (revision 19)
- ✅ Git sidecar `StrictHostKeyChecking=no` → `accept-new` (revision 19)
- ✅ Git sidecar clone URL validation + github_api GET-only (revision 19)
- ✅ MCP base fail-open auth → fail-secure (revision 19)
- ✅ Operator/API Gateway RBAC secrets verb reduction (revision 19)
- ✅ LiteLLM/PostgreSQL/Web-UI pod security contexts (revision 19)
- ✅ Init container privilege escalation + capability drop (revision 19)
- ✅ emptyDir sizeLimit on all volumes (revision 19)
- ✅ Agent network policy K8s API port restriction + metadata IP block (revision 19)
- ✅ PostgreSQL + LiteLLM NetworkPolicy ingress isolation (revision 19)
- ✅ python/pip removed from agent tool allowlist (revision 19)
- ✅ Code-exec output secret masking (revision 19)
- ✅ LiteLLM imagePullPolicy → Always (revision 19)

Focus exclusively on **NEW** vulnerabilities not in the above list.

## PROMPT END
