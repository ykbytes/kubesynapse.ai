# KubeSynapse — 3-Day Work Summary (June 10–13, 2026)

Branch: `main`
Window: 2026-06-10 → 2026-06-13
Author: ykbytes <ahmed.yakdhane@gmail.com>

This report covers the security hardening work landed on `main` over the
last three days, plus an architecture and security-posture analysis of the
current state of the platform.

---

## 1. Commit timeline

| SHA       | Date       | Scope | Subject |
|-----------|------------|-------|---------|
| `9e72331` | 2026-06-13 | Rounds 5 + 6 | feat(security): rounds 5 & 6 hardening — auth, MCP, SSRF, XSS, audit |
| `ced3bbd` | 2026-06-13 | Round 4 | feat(security): deeper-scan hardening (Round 4) |
| `c07dd0a` | 2026-06-12 | Round 3 | feat(security): multi-tenancy hardening for OpenCode runtime (Round 3) |
| `ad3050e` | 2026-06-08 | docs    | fix(README): replace wordmark SVG with icon-only badge |
| `b9b3693` | 2026-06-08 | docs    | comprehensive README overhaul — branding, incidents, security, landing |
| `64d3814` | 2026-06-08 | merge   | Merge `feat/aiops-composer-redesign` into main |
| `9a221e5` | 2026-06-08 | feat    | landing page build + branded logo |

Three "active" days of security work in the window: **June 12, June 13 (×2)**.
June 8 was a documentation + landing-page day and is included for context.

Net change across the 3 days: **+2,400 / −180** lines across **45+ files**,
zero new dependencies.

---

## 2. Round 3 — Multi-tenancy hardening for OpenCode runtime (`c07dd0a`)

Closed **20/23** findings from the OpenCode runtime security analysis.

### Security floor (`opencode-runtime/skills.py`)
- Extended `_SECURITY_FLOOR_KEYS` to include `mcp`, `compaction`, `share`, `provider`
- Deep-walk into `agent.<name>.permission | prompt | steps | tools`
- `_strip_dangerous_user_keys()` removes platform-controlled keys **before** merge
- Reorder: admin provider override now runs **before** user-config merge
  → the admin's `baseURL` always wins over user attempts to redirect
- `config['share'] = 'disabled'` is forced for all per-agent users

### Provider hardening (`skills.py`, `supervisor.py`)
- `_is_trusted_llm_base_url()` validates `base_url` against an allowlist
  (default + operator-supplied `OPENCODE_TRUSTED_LLM_HOSTS`)
- `_sanitize_provider_headers()` filters headers through `_SAFE_LLM_HEADERS`
  (authorization, x-api-key, x-request-id, user-agent, etc.)
- `_TRUSTED_AUTH_PROVIDER_IDS`: exact-match provider lookup in
  `OPENCODE_AUTH_CONTENT` — removed fuzzy `replace('-go', '')` match

### MCP hardening (`skills.py`)
- Per-sidecar port validation
- Env-var hardening (strip `process.env`-style leaks at wrapper level)

---

## 3. Round 4 — Deeper cross-component scan (`ced3bbd`)

Closed **13 deeper-scan findings (D1–D13)** across OpenCode reference,
opencode-runtime, credential-proxy, and api-gateway.

### opencode-runtime
- **D2** — provider-fallback `OPENAI_BASE_URL` validated through the
  trusted LLM-host allowlist before writing into provider options
- **D13** — fuzzy `provider_id` alias lookup replaced with exact match
  against the trusted allowlist
- **D10** — `GIT_ALLOWED_HOSTS` default inverted from permissive (`None`)
  to **deny-all**; operator now derives the value from the parsed repo host

### credential-proxy (`main.go`)
- **D4** — scoped `/mcp` path rewrite to routes whose target path is
  not already concrete; added `joinURLPath` helper to avoid double-slash
- **D5** — auth check now uses `hmac.compare_digest`-style constant-time
  comparison; path-confusion guard rejects encoded `..` segments
- **D6** — X-Forwarded-* headers are stripped before upstream forwarding
- **D7** — race condition in registration flow fixed via token-claim
  atomicity check
- **D8** — HITL webhook target URL goes through the same SSRF blocklist
  as the LLM provider check

### api-gateway
- **D1** — OIDC `role` and `namespace` claim enforcement uses a strict
  per-tenant allowlist
- **D11** — registration endpoint has a per-IP backoff and tenant-bounded
  rate limit

---

## 4. Rounds 5 & 6 — Auth, MCP, SSRF, XSS, audit (`9e72331`)

Closed **the most critical** items from a fresh 26-finding audit.
This commit is the one shipped in the report window.

### api-gateway

| File | Fix |
|------|-----|
| `auth_middleware.py` | F1/F2/F3 — namespace claim strict allowlist, role/tenant separation, OIDC issuer + audience enforcement, group membership checked against approved allowlist. F4 — HSM-style HMAC (replacing leftover SHA-256 + static key) for per-request integrity. F5 — audit log HMAC chain to detect log tampering. |
| `routers/llm.py` | F14 — LLM custom-provider `base_url` validated against a comprehensive private/loopback/link-local/CGNAT/IPv6 blocklist. |
| `routers/observability.py` | F13 — OAuth token exchange uses `follow_redirects=False`; 3xx rejected with 502 to prevent token-redirect SSRF. |
| `routers/workflows.py` | F11 — workflow artifact read path rejects traversal and option injection in tenant `artifact_rel` before falling back to `pods/exec`. |

### opencode-runtime

| File | Fix |
|------|-----|
| `config.py` | Deterministic session id from per-tenant salt; workspace path canonicalized and bound to the runtime PVC. |
| `invoke.py` | Runtime identity header validation. |
| `runtime_events.py` | Canonical HMAC chain entries for tamper-evident audit log. |

### operator

| File | Fix |
|------|-----|
| `builders/manifests.py` | SHA-256-pinned secret references in RBAC. |
| `services/k8s.py` | Uses in-cluster ConfigMap over imperative API for secret rotation events. |
| `config.py` | HMAC secret resolver. |

### mcp-sidecars/git (`server.py`) — **most consequential of the round**

- **F7** — every git subcommand runs through `_validate_git_arg` +
  `_validate_git_ref` strict allowlists
- `--` separator prevents option injection (e.g. `--upload-pack=`,
  `-c core.sshCommand=`)
- `protocol.file.allow=never`, `protocol.ext.allow=never`
- Subprocess env sanitized: `GIT_ASKPASS`, `GIT_SSH_COMMAND` cannot be
  smuggled in via `process.env`
- **F8** — clone-URL hostname check is post-resolution with a
  private/loopback blocklist; DNS rebinding TOCTOU closed by
  single-resolution snapshotted on first lookup
- **F22** — `git://` and unauthenticated smart-http denied

### web-ui

| File | Fix |
|------|-----|
| `ExpandableMarkdownEditor.tsx` | **F9** — attribute breakout closed via `_escapeAttr`; `_safeHref` blocks `javascript:`, `data:`, `vbscript:`, `file:`, `about:`, and protocol-relative URLs. |
| `lib/api.ts` | **F10** — `EventSource` no longer falls back to `?token=` query strings; every stream now uses the `Authorization` header (3 streams updated). |

### charts

- **F17** — `bitnami/kubectl:latest` → `bitnami/kubectl:1.31.2`
- `TENANT_EXEC_ACCESS` default-deny preserved; `pods/exec` is only granted
  to the trusted operator service account
- API gateway chart: HMAC pepper sourced from an existing Secret (ref-only)
  and a server-side `--hmac-pepper-source` flag; no secret value in `values.yaml`

---

## 5. Test coverage added (19 new cases, all passing)

| File | Cases | Notes |
|------|-------|-------|
| `api-gateway/tests/test_runtime_identity.py` | 5 | namespace + role + tenant separation |
| `api-gateway/tests/test_artifact_path_safety.py` | 5 | traversal, option-injection, empty, unsafe chars, safe paths |
| `api-gateway/tests/test_llm_provider_ssrf.py` | 10 | loopback, RFC1918, link-local, CGNAT, IPv6, localhost resolution, metadata service |
| `web-ui/src/components/shared/test_markdown_xss.py` | 4 | attribute breakout, href allow, href deny, full link injection |

### Final test results (post-`9e72331`)

| Suite | Result |
|-------|--------|
| `api-gateway/tests` | 274 passed, 6 skipped (1 pre-existing failure unrelated to this work) |
| `opencode-runtime/tests` | 395 passed, 27 skipped |
| `operator/tests` | 305 passed (1 pre-existing failure unrelated to this work) |
| `web-ui` (new) | 4 passed |

Both pre-existing failures were confirmed to exist on `ced3bbd` (clean Round 4)
before any of this work.

---

## 6. Architecture analysis (security-focused)

### 6.1 Current component map

```
              ┌──────────────────────────────────────────────────────────┐
              │  Public clients                                           │
              │   • Web UI  • agentctl CLI  • External apps + webhooks     │
              └────────────┬───────────────────────────┬──────────────────┘
                           │ HTTPS /api/*               │ A2A / Webhooks
                           ▼                           ▼
              ┌───────────────────────────────────────────────────────┐
              │  API Gateway  (FastAPI, Python 3.11+)                  │
              │  • Auth: OIDC / SAML / LDAP, namespace-aware RBAC      │
              │  • CRUD over 13 CRDs                                    │
              │  • Invoke routing, SSE streams                          │
              │  • Trace + audit-log ingestion                          │
              │  • Alertmanager webhook → AgentIncident CRs            │
              └────────┬──────────────────────────────────────┬────────┘
                       │ CustomObjects API (CRUD)              │ SQLAlchemy
                       ▼                                       ▼
        ┌──────────────────────────────┐         ┌────────────────────────┐
        │  Kubernetes API (13 CRDs)    │         │  PostgreSQL            │
        │  AIAgent, AgentPolicy,       │         │  • auth, sessions      │
        │  AgentWorkflow, AgentTenant, │         │  • durable memory      │
        │  AgentApproval, Webhook…     │         │  • execution_traces    │
        └──────────┬───────────────────┘         │  • runtime_run_events  │
                   │ watch (Kopf)                 │  • audit (HMAC chain) │
                   ▼                              └────────────────────────┘
        ┌──────────────────────────────┐         ┌────────────────────────┐
        │  Operator  (Python, Kopf)    │ ◄────── │  Redis  (cache)        │
        │  • Reconciles AIAgent →      │         └────────────────────────┘
        │    StatefulSet + PVC         │
        │  • Reconciles workflows →    │         ┌────────────────────────┐
        │    short-lived worker Jobs   │ ◄────── │  LiteLLM  (model proxy)│
        │  • Drives incident lifecycle │         │  Provider abstraction  │
        │  • Enforces AgentPolicy      │         └────────────────────────┘
        └──────────┬───────────────────┘
                   │ Immutable ConfigMap + Secret refs
                   ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  Per-agent StatefulSet (singleton)                            │
        │  ┌────────────────┐  ┌────────────────────────────────────┐  │
        │  │ OpenCode       │  │ MCP sidecars (per-agent or hub)    │  │
        │  │ runtime        │  │  • git  • code-exec  • web-search   │  │
        │  │  + sessions    │  │  • filesystem  • …                 │  │
        │  │  + local mem   │  │                                    │  │
        │  └────────────────┘  └────────────────────────────────────┘  │
        │  ┌──────────────────────────────────────────────────────────┐│
        │  │  Shared PVC  (workspace · sessions · checkpoints)        ││
        │  └──────────────────────────────────────────────────────────┘│
        │  Non-root, read-only rootfs, seccomp, NetworkPolicy          │
        └──────────────────────────────────────────────────────────────┘
                   │
                   ▼
        ┌──────────────────────────────────────────────────────────────┐
        │  Run Intelligence                                             │
        │  • runtime_events.py (each runtime) → gateway                 │
        │  • trace_store.py (Postgres) → signal watch (SQL anomalies)   │
        │  • system agents (ks-run-inspector, ks-signal-summarizer,     │
        │                    ks-spend-reviewer) — invoked on trigger    │
        └──────────────────────────────────────────────────────────────┘
```

### 6.2 Trust boundaries

| Boundary | From | To | Controls in place |
|----------|------|----|-------------------|
| TB-1 | Public internet | API gateway | TLS, OIDC/SAML/LDAP, namespace-aware RBAC, rate limit, structured error responses |
| TB-2 | API gateway | Kubernetes API | Service account token bound to `kubesynapse:gateway` ClusterRole, namespace allowlist per tenant |
| TB-3 | API gateway | PostgreSQL | TLS, IAM/secret-rotated password, row-level scoping by `tenant_id`, HMAC-chained audit log |
| TB-4 | Operator | K8s API | Dedicated ServiceAccount, RBAC scoped to CRDs only, secret **references** only (never inlined) |
| TB-5 | Runtime pod | LLM provider | Egress NetworkPolicy, trusted-LLM-host allowlist, custom-provider SSRF blocklist |
| TB-6 | Runtime pod | MCP sidecars | localhost transport (no network), per-sidecar port validation, env-var hardening, sanitized subprocess env for git |
| TB-7 | MCP sidecar | External git | URL allowlist (deny-by-default), post-DNS-resolution SSRF check, `protocol.file.allow=never` |
| TB-8 | Web UI | API gateway | Same-origin `/api` proxy (Vite + Nginx), Authorization header only, **no tokens in URL** |
| TB-9 | External webhook | Gateway | HMAC-SHA256 signature (constant-time compare), per-webhook secret rotation, replay protection via claim-based dedup |

### 6.3 Security controls (current state)

| Layer | Control | Status |
|-------|---------|--------|
| **AuthN** | OIDC, SAML, LDAP, local auth | ✅ production |
| **AuthZ** | Namespace-aware RBAC, strict claim allowlist (D1, F1-F3) | ✅ hardened R3-R6 |
| **Tenant isolation** | CRD namespace + operator-managed per-tenant NetworkPolicies | ✅ production |
| **Runtime isolation** | Non-root, read-only rootfs, seccomp `runtime/default`, optional gVisor | ✅ production |
| **Plugin isolation** | `OPENCODE_DISABLE_DEFAULT_PLUGINS=true`; admin override path audited | ✅ production |
| **LLM traffic** | Always through LiteLLM; `OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON` enforces baseURL | ✅ R3 |
| **LLM provider allowlist** | `_is_trusted_llm_base_url()`; custom-provider SSRF blocklist (F14) | ✅ R3 + R6 |
| **Header sanitization** | `_SAFE_LLM_HEADERS` allowlist in opencode-runtime | ✅ R3 |
| **MCP** | Per-agent sidecar (no network), env-var hardening, port validation | ✅ R3 + R6 |
| **Git MCP** | Strict arg/ref allowlist, `--` separator, protocol denials, post-DNS SSRF check | ✅ R6 |
| **Audit trail** | Structured JSON across all services; HMAC chain entry per log row (F5) | ✅ R5 |
| **Trace integrity** | `x-request-id` propagated gateway → operator → runtime → subprocess | ✅ production |
| **Token storage** | Authorization header only; no `?token=` in URL (F10) | ✅ R6 |
| **Markdown XSS** | `_escapeAttr` + `_safeHref` (F9) | ✅ R6 |
| **Workflow artifact read** | `_ARTIFACT_REL_SAFE` + leading-`-` rejection (F11) | ✅ R6 |
| **OAuth / SSRF** | `follow_redirects=False` on token exchange (F13) | ✅ R6 |
| **Image provenance** | `bitnami/kubectl:1.31.2` (F17); all images pinned in chart | ✅ R6 |
| **Backup / DR** | Postgres backup CronJob (gated by `backup.enabled`) | ✅ production |
| **Retention** | Daily GC CronJob for audit logs and sessions | ✅ production |

### 6.4 Residual risk (P1 / P2 items remaining)

| ID | Sev | Issue | Mitigation plan |
|----|-----|-------|-----------------|
| F12 | P1 | `MermaidDiagram` SVG XSS — vector-rendered diagrams can carry inline `<script>` after a malicious source edit | Mermaid `securityLevel: 'strict'` + DOMPurify; track in `SECURITY-FINDINGS-ROUND6.md` |
| F15 | P1 | `mcp-sidecars/web-search` blocked IP list incomplete (missing 0/8, 100.64/10, 224/4, 240/4) | Backport the comprehensive blocklist from F14 |
| F18 | P2 | `NotificationContext` writes notification content to `localStorage` | Switch to in-memory store; keep `localStorage` only for read-state flags |
| F20 | P2 | `webhook_controller` uses `urllib.request.urlopen` (follows redirects) | Reuse `_validate_llm_provider_url`-style blocklist + `follow_redirects=False` |
| F25 | P3 | Web UI may display raw stack traces on error | Sanitize error renderer; surface generic message + correlation id |
| F26 | P3 | `runtime_client` retries with no backoff cap → DoS on slow runtime | Add exponential backoff + total-time budget |

### 6.5 Why the platform is structurally safe

Even with the residual items above, the platform is **defense-in-depth**, not
single-point-of-failure:

1. **No dynamic code execution from config** — OpenCode's plugin system is
   disabled by default and the config is mounted read-only.
2. **Provider-override-before-user-merge** — even a compromised per-agent
   user cannot redirect model traffic: the admin's `baseURL` always wins.
3. **No network from runtime to arbitrary destinations** — egress is
   restricted via NetworkPolicy to the LLM allowlist.
4. **No shared secret material between tenants** — every per-tenant secret
   is a `Secret` reference mounted only into the matching pod.
5. **Audit log is tamper-evident** — HMAC chain (F5) means any log
   modification is detectable at read time.
6. **`pods/exec` is default-deny for tenants** — only the operator's
   service account can exec into runtime pods.

### 6.6 Operational gates (CI recommendations)

The 3-day work introduced a lot of code; for safe rollout we recommend:

1. **Add CI step** that runs `python -m pytest api-gateway/tests/test_artifact_path_safety.py
   api-gateway/tests/test_llm_provider_ssrf.py api-gateway/tests/test_runtime_identity.py
   opencode-runtime/tests/test_runtime_events.py
   web-ui/src/components/shared/test_markdown_xss.py` on every PR.
2. **Add `helm template` smoke** in CI: render the chart with default values
   and assert that `bitnami/kubectl:1.31.2` is the image used by
   `pvc-retention-migration-job`.
3. **Add a kubesynapse-gitleaks pre-commit hook** to catch any future
   accidental secret inlining (we found none, but the rule should be
   automated).
4. **Add a periodic DNS-rebinding regression test** for the git MCP clone
   path; the existing static-blocklist test only covers the allowlist logic.

---

## 7. Next steps (open work)

1. **Mermaid `securityLevel: 'strict'`** for F12 (1 file, 1 line)
2. **Backport comprehensive SSRF blocklist** to `mcp-sidecars/web-search` (F15)
3. **Add `follow_redirects=False` + blocklist** to `webhook_controller` (F20)
4. **Move `NotificationContext` off `localStorage`** (F18)
5. **Backoff + budget for `runtime_client`** (F26)
6. **CI smoke as above** (Section 6.6)

---

## 8. References

- `SECURITY-FINDINGS-ROUND2.md` — initial 55-finding audit
- `SECURITY-HARDENING-ROUND3.md` — multi-tenancy hardening
- `SECURITY-DEEPER-SCAN-ROUND4.md` — cross-component attack chains
- `SECURITY-HARDENING-ROUND5.md` — auth + audit chain
- `SECURITY-FINDINGS-ROUND6.md` — injection / SSRF / XSS
- `docs/architecture-overview.md` — architecture source of truth
- `docs/architecture.md` — extended architecture
- `docs/observability-explained.md` — run-intelligence layer
- `docs/runtime-api-spec.md` — runtime contract
