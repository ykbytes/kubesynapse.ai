# KubeSynapse Deep-Dive Analysis

**Date:** 2026-04-23
**Branch:** `preprod`
**Repository:** `ykbytes/kubesynapse.ai`

---

## 1. What Is KubeSynapse?

KubeSynapse is a **Kubernetes-native AI agent platform**. It treats AI agents as first-class Kubernetes resources, providing a complete control plane to build, deploy, govern, and observe AI agents inside a cluster.

**Core Philosophy:**
- **OpenCode-first runtime** — The only supported agent runtime is `opencode` (an AI CLI/server).
- **Everything is a CRD** — Agents, workflows, policies, approvals, evaluations, and tenants are all Kubernetes Custom Resources.
- **File-backed configuration** — Skills, system prompts, and OpenCode config files are versioned directly in manifests.
- **Governance by default** — Policies, HITL (human-in-the-loop), A2A routing, and guardrails are built-in, not bolted on.

---

## 2. High-Level Architecture

The platform has a **control plane / data plane** split:

```
+------------------------------- CONTROL PLANE -------------------------------+
|  +-----------+  +--------------+  +---------------------+                  |
|  | Operator  |  | API Gateway  |  | Web UI (React+Vite) |                  |
|  | (Kopf)    |  | (FastAPI)    |  |                     |                  |
|  +-----------+  +--------------+  +---------------------+                  |
|       |                |                                                   |
|       v                v                                                   |
|    Kubernetes API (etcd) — CRD Source of Truth                             |
|    PostgreSQL — Operational Data (auth, chat, usage)                       |
+-----------------------------------------------------------------------------+
                              |
+------------------------------- DATA PLANE ----------------------------------+
|  +----------------+    +-----------+    +-----------+                      |
|  | Agent Runtime  |<-->|  MCP Hub  |<-->|  LiteLLM  |                      |
|  | (OpenCode)     |    | (sidecars)|    |  (proxy)  |                      |
|  +----------------+    +-----------+    +-----------+                      |
|         ^                                                                   |
|    A2A (Agent-to-Agent) over internal gateway                              |
+-----------------------------------------------------------------------------+
```

---

## 3. Component Deep Dive

### 3.1 Operator (`operator/`)

**Framework:** Kopf (Kubernetes Operator Pythonic Framework)

**Role:** The brain of the platform. Watches CRDs and reconciles them into real Kubernetes resources.

**Entrypoint:** `main.py` — sets up logging, kubeconfig, imports controllers (auto-register Kopf handlers), initializes SQL state DB, starts OpenTelemetry tracing.

**Core Modules:**
| Module | Purpose |
|--------|---------|
| `main.py` | Bootstraps operator and lifecycle hooks |
| `config.py` | ~260 lines of typed env-var config |
| `reconcile.py` | Shared reconciliation with retry logic, error classification (`PermanentError` vs `TemporaryError`), K8s status conditions |
| `state_store.py` | SQLAlchemy ORM for `WorkflowRun`, `EvalRun`, `AgentSession`, `ChatSession`, `ChatMessage` |
| `worker.py` | **~3,500 lines.** Workflow/eval execution engine. Runs as ephemeral K8s Jobs |
| `utils.py` | Prompt templating, DAG validation, execution wave computation, runtime HTTP invocation |
| `errors.py` | Machine-readable error taxonomy |
| `services/k8s.py` | K8s API interaction — idempotent `ensure_*`, worker job enqueue/cancel |
| `builders/translator.py` | **Translator pattern:** pure `translate_agent()` returns `AgentOutputs` with every manifest |
| `builders/manifests.py` | Low-level manifest constructors |
| `controllers/*.py` | One controller per CRD |

**CRD Controllers:**
- **`agent_controller.py`** — Reconciles `AIAgent` → StatefulSet + Service + NetworkPolicies + Secrets. Resolves policies/tenants, validates models, prunes orphans.
- **`workflow_controller.py`** — Reconciles `AgentWorkflow` → worker Job. Watchdog timer (30s) detects stale jobs and auto-requeues. Supports cancellation.
- **`approval_controller.py`** — Watches `AgentApproval.status.decision`. On approval: re-enqueues workflow. On denial: marks failed.
- **`eval_controller.py`** — Reconciles `AgentEval` → worker Job. Supports cron scheduling with `croniter`.
- **`tenant_controller.py`** — Reconciles `AgentTenant` → Namespace + ResourceQuota + LimitRange + RBAC.
- **`policy_controller.py`** — Pure validation for `AgentPolicy`.
- **`observation_controller.py`** — Demo-mode observability CRD reconciliation.
- **`status_projection.py`** — Mirrors CRD status changes into PostgreSQL.

**Worker Job Engine (`worker.py`):**
The worker is **not** a thread inside the operator — it is a separate Kubernetes Job. This isolates workflow execution from operator health.

The worker:
1. Acquires a K8s Lease for idempotency
2. Computes topological **execution waves** for parallel step execution
3. Handles step types:
   - **`agent`** — HTTP invoke to agent runtime with retries, verification gates, JSON contract checking, HITL
   - **`loop`** — Iterative dev-loop with circuit breaker and progress checklist
   - **`conditional`** — Safe expression evaluation against previous step output
   - **`review`** — Invokes reviewer agent; raises `ReviewRejectedError` on rejection
4. Writes artifact JSON to PVC and patches CRD status

---

### 3.2 API Gateway (`api-gateway/`)

**Framework:** FastAPI (monolithic, ~13,200 lines in `main.py`)

**Role:** Single REST API and A2A facade. Translates HTTP calls to K8s CRD operations and proxies agent invocations.

**Key Design:** No sub-routers — everything mounted directly on `app`.

**Auth (`auth_middleware.py`, `jwt_utils.py`, `enterprise_auth.py`, `auth_store.py`):**
Supports 6 modes: `shared_token`, `local`, `oidc`, `auto`, `hybrid`, `enterprise`.
- **Shared token:** `API_GATEWAY_SHARED_TOKEN` with `hmac.compare_digest`
- **Local JWT:** HS256 tokens, httpOnly refresh cookies, 30s revocation grace
- **OIDC:** Async JWKS fetching (5-min cache), group claim extraction
- **SAML:** `python3-saml` integration
- **LDAP:** Bind/search/re-bind with group-to-role mapping

**Storage:** Dual strategy:
1. **K8s CRDs** — Source of truth
2. **PostgreSQL** — Operational data via SQLAlchemy:
   - Users, sessions, audit logs, usage/cost tracking
   - Chat sessions and messages
   - Memory records (episodic/procedural with scoring/promotion)
   - Workflow run history and log archives
   - Intelligence collectors, tasks, schedules, alerts

**Invoke Pipeline:**
- `POST /api/agents/{name}/invoke` — Synchronous
- `POST /api/agents/{name}/invoke/stream` — SSE streaming with keepalive comments (15s)

Before forwarding to runtime, enriches prompt with:
1. **Promoted memory** from SQL (ranked by token overlap + recency + score)
2. **A2A collaboration note** — Discovers outbound peers, injects instructions
3. **Intelligence context** — Auto-injects collector results
4. **Factory mode** — Mode-specific system notes

**A2A (Agent-to-Agent):**
- `POST /a2a/{assistant_id}` — JSON-RPC 2.0 dispatcher (`message/send`, `message/stream`, `tasks/get`)
- `GET /.well-known/agent-card.json` — AgentCard discovery
- In-memory task store with TTL (1 hour)
- Peer discovery checks `allowedTargets`, `allowedCallers`, pod `running` status

---

### 3.3 OpenCode Runtime (`opencode-runtime/`)

**Framework:** FastAPI Python service wrapping a Node.js/Bun subprocess (`opencode serve`)

**Role:** The actual AI agent container. Every `AIAgent` CRD becomes a StatefulSet running this runtime.

**Architecture:**
- Python sidecar exposes HTTP on port `8080`
- OpenCode subprocess runs on `127.0.0.1:4096`
- Supervisor thread auto-restarts subprocess if it dies

**Key Files:**
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, lifespan, routes |
| `invoke.py` | **Core multi-turn autonomous loop** (~1,300 lines) |
| `opencode_client.py` | HTTP client to local OpenCode server |
| `session.py` | Thread-safe registry `thread_id` → `session_id` |
| `memory.py` | Cross-session JSONL memory persistence |
| `skills.py` | Materializes skill files, builds `opencode.json` config |
| `hitl.py` | K8s `AgentApproval` CRD gating |
| `sanitize_secrets.py` | Redacts secrets from outputs |
| `workspace.py` | Pre-computed workspace snapshotting |

**The Invoke Pipeline (`invoke.py`):**
1. Validates request (rejects direct `tool_name`, `mcp_server`, `sandbox_session`)
2. HITL gate — creates K8s `AgentApproval` if required
3. Session resolution — `thread_id` → OpenCode `session_id`
4. **System prompt assembly** from 10 sources:
   - Autonomy rules (17 rules)
   - Default system prompt
   - User-provided system prompt
   - Workspace snapshot
   - Memory context
   - Skills content
   - Task-type classification
   - Output format instructions
   - Team context
5. **Autonomous multi-turn loop** (up to 50 turns):
   - Sends prompt to OpenCode server
   - Polls for response / streams SSE
   - Detects completion, context overflow, errors
   - **Compaction:** At 75% context usage, calls `/summarize` and injects recovery prompt
   - **Error classification:** Structured output, auth, API, etc. with tailored retry prompts
6. Post-processing: extracts artifacts, tool calls, todos; redacts secrets; persists memory

**MCP Sidecar Discovery:**
- Reads `OPENCODE_MCP_SIDECARS_JSON` (localhost sidecars)
- Reads `OPENCODE_MCP_CONNECTIONS_JSON` (structured connections)
- Generates `opencode.json` with MCP server definitions
- OpenCode server invokes MCP tools natively; Python runtime observes results

---

### 3.4 Web UI (`web-ui/`)

**Stack:** React 18, TypeScript, Vite, Tailwind CSS v4, Radix UI primitives, Framer Motion, Monaco Editor, XYFlow

**Architecture:**
- **Lazy-loaded components** — Every panel via `React.lazy()`
- **Context providers:** `ConnectionContext`, `WorkspaceContext`, `ChatContext`, `ThemeContext`, `NotificationContext`

**Views:**
| View | Component |
|------|-----------|
| `agents` | `AgentManagementPanel`, `CreateAgentPanel` |
| `chat` | `ChatSessionPanel`, `ChatWorkbench`, `TeamView` |
| `workflows` / `composer` | `WorkflowManager`, `WorkflowComposer` (XYFlow DAG editor) |
| `evals` | `EvalManager` |
| `catalog` | `SkillsCatalogPanel` |
| `policies` | `PolicyEditor` |
| `intelligence` | `IntelligenceDashboard` |
| `mcp` | `McpManagementPanel` |
| `settings` | `SettingsPanel` |
| `admin` | `AdminPanel`, `AuditLogPanel`, `UsageDashboard`, `HealthDashboard` |

**Key UI Patterns:**
- Inspector Drawer — Right-side panel for resource details, spec, status, approvals
- Command Palette — Global keyboard-driven navigation
- Onboarding Tour — First-time user guidance
- Chat Workbench — Streaming, artifact preview, file explorer, todo list, A2A picker, OpenCode settings

---

### 3.5 CLI (`cli/agentctl.py`)

**Stack:** Python, `typer`, `httpx`, `rich`, `PyYAML`

**Design:** Single-file CLI with sub-command groups.

**Key Features:**
- Auto-detects resource kind from YAML/JSON files (`apply` command)
- Supports K8s CRD manifests and direct API payloads (snake_case / camelCase)
- Rich formatted tables and JSON output (`--json`)
- SSE streaming for `invoke --stream` and `logs --follow`
- A2A discovery (`agents discover`)
- OpenCode config file patching (`--opencode-config-file`, `--opencode-config-text`)

---

### 3.6 Helm Chart (`charts/kubesynapse/`)

**Full platform chart** deploying:
- Operator (2 replicas)
- API Gateway
- Web UI (nginx)
- LiteLLM proxy
- PostgreSQL, Redis, Qdrant, NATS
- MCP Hub (shared MCP servers)
- Collector Agent DaemonSet
- Skills Catalog ConfigMap

**Key Values:**
- `agentRuntime.hitl.mode: enforce`
- `apiGateway.auth.mode: hybrid`
- `platformSecrets.mode: native` (also supports ExternalSecrets/Vault)
- `mcpHub.namespace: mcp-hub`

---

### 3.7 MCP Sidecars (`mcp-sidecars/`)

Bundled tool containers (11 types):
`code-exec`, `web-search`, `documents`, `browser`, `database`, `git`, `github-adapter`, `kubernetes`, `messaging`, `rag`, `collector`

Each is a separate Docker image, running as sidecars in agent pods or shared services in MCP Hub.

---

## 4. CRD Model (Group: `KubeSynapse.ai/v1alpha1`)

| CRD | Purpose | Reconciled To |
|-----|---------|---------------|
| `AIAgent` | Agent definition | StatefulSet + Service + NetworkPolicies + Secrets |
| `AgentWorkflow` | Multi-step DAG | Worker Job (ephemeral) |
| `AgentEval` | Evaluation test suite | Worker Job (scheduled/manual) |
| `AgentPolicy` | Guardrails and constraints | Validation only |
| `AgentApproval` | HITL decision gate | Watched by approval controller |
| `AgentTenant` | Multi-tenancy | Namespace + ResourceQuota + LimitRange + RBAC |
| `ObservationTarget` | Observability target | Synthetic reports (demo) |
| `ObservationPolicy` | Observability policy | Validation |
| `ObservationReport` | Generated findings | Created by observation controller |
| `ConnectorPlugin` | Observability connector | Status updates |

---

## 5. Security Model

**Network Segmentation:**
- **MCP NetworkPolicy:** Egress restricted to allowed MCP server types
- **A2A Egress NetworkPolicy:** Egress restricted to explicit `allowedTargets`
- **A2A Ingress NetworkPolicy:** Ingress restricted to explicit `allowedCallers`
- Baseline rules: DNS, API gateway, LiteLLM, Qdrant, HTTPS, OTEL

**Pod Security:**
- `runAsNonRoot: True`, UID 1000
- `readOnlyRootFilesystem: True`
- `allowPrivilegeEscalation: False`
- `capabilities: drop: ["ALL"]`
- Worker jobs: UID 999/GID 37

**Auth & RBAC:**
- Per-tenant ServiceAccount, Role, RoleBinding
- ClusterRoleBinding for runtime access
- Cross-namespace reference validation (`Same` / `All` / `Selector`)
- Secret redaction from tool outputs

**HITL:**
- `requireApproval: true` on workflow steps → `AgentApproval` CRD
- Three modes: `enforce`, `dry-run`, `disabled`
- Policy-level `a2a.requireHitl` injects `A2A_REQUIRE_HITL` env var

---

## 6. Key Design Patterns

1. **Translator Pattern (`builders/translator.py`)** — Pure function from `AIAgent` spec to complete manifest bundle. Deterministic and testable.
2. **Controller-per-CRD** — Clean separation; optional controllers load only if CRD exists.
3. **Worker-as-Job** — Workflow/eval execution isolated in ephemeral K8s Jobs.
4. **Dual Storage** — CRDs for source of truth, SQL for operational querying.
5. **Gateway Enrichment** — Single point where memory, A2A context, and intelligence are injected.
6. **File-backed Config** — Skills and OpenCode configs stored as container files, not fetched externally.

---

## 7. Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Orchestration | Kubernetes, Kopf, Helm |
| Backend | Python 3.11+, FastAPI, SQLAlchemy, Alembic, Pydantic |
| AI Runtime | OpenCode (Node.js/Bun), LiteLLM proxy |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS v4, Radix UI |
| CLI | Typer, Rich, httpx |
| Database | PostgreSQL (primary), SQLite (fallback), Qdrant (vectors) |
| Message Bus | NATS, Redis |
| Auth | JWT (HS256), OIDC, SAML, LDAP, shared tokens |
| Observability | OpenTelemetry, Prometheus |
| Tooling | Ruff, mypy (strict), pytest |

---

## 8. Notable Quality Decisions

- Strict mypy (`disallow_untyped_defs`, `strict = true`)
- Ruff linting with security rules (`flake8-bandit`)
- Monorepo with `Makefile`
- Versioned images in Helm values
- Namespace protection (`kube-system`, `default` refused)
- Circuit breakers in loop steps and supervisor restart limits
- Verification gates with concrete pass/fail criteria

---

## 9. Quick Wins for OSS Popularity & Production Readiness

### 9.1 Developer Experience (Immediate)

1. **Docker Compose for Local Dev**
   - Not every dev has a K8s cluster. A `docker-compose.yml` that spins up gateway + operator (in mock mode) + postgres + UI would dramatically lower the barrier to entry.

2. **Better Onboarding in Web UI**
   - The `OnboardingTour` exists but could be enhanced with interactive walkthroughs for first agent creation.
   - Add a "Quick Start" wizard that creates a sample agent + workflow in one click.

3. **CLI Auto-Completion**
   - `agentctl` already uses `typer`. Generate shell completions and document them.

4. **Pre-commit Hooks**
   - Add `.pre-commit-config.yaml` with `ruff`, `mypy`, and `helm-lint`.

5. **GitHub Issue/PR Templates**
   - Standardize bug reports, feature requests, and PR descriptions.

### 9.2 UI/UX Polish (Quick Wins)

6. **Dark/Light Theme Polish**
   - The `ThemeProvider` exists. Audit contrast ratios, ensure all components respect `dark`/`light` classes.

7. **Mobile Responsiveness**
   - `MobileNav` exists but some views (Chat, Workflow Composer) may need touch optimizations.

8. **Loading States & Skeletons**
   - Replace generic spinners with content-aware skeleton screens.

9. **Toast Notifications for Async Actions**
   - `sonner` is imported. Ensure all CRUD operations show success/error toasts.

10. **Keyboard Shortcuts Documentation**
    - The Command Palette exists. Add a cheatsheet modal (`?` key).

### 9.3 Production Hardening

11. **Health Checks & Readiness Probes**
    - Gateway has `/api/health`. Add liveness/readiness probes to all chart components.

12. **Graceful Shutdown**
    - Operator handles `SIGTERM`. Verify gateway and runtime also drain connections.

13. **Database Connection Pooling**
    - `auth_store.py` uses `pool_pre_ping=True`. Document recommended pool sizes for production.

14. **Secrets Rotation**
    - The chart supports ExternalSecrets. Document a Vault/External Secrets Operator setup guide.

15. **Pod Disruption Budgets**
    - Add PDBs for operator, gateway, and LiteLLM.

### 9.4 Observability & Debugging

16. **Structured Logging Everywhere**
    - Operator uses JSON logging. Ensure gateway and runtime also emit structured logs.

17. **OpenTelemetry Traces End-to-End**
    - Trace a request from UI → Gateway → Runtime → OpenCode → LiteLLM.

18. **Workflow Run Visualization**
    - The UI has `ExecutionTimeline`. Add a DAG visualization for completed runs.

19. **Agent Log Search**
    - `agentctl logs` fetches raw logs. Add grep/filter in UI.

### 9.5 Community & Marketing

20. **Awesome README with GIFs**
    - Current README is good. Add a 60-second demo GIF of creating an agent and running a workflow.

21. **Architecture Diagrams**
    - Mermaid diagrams in `docs/architecture-overview.md` for data flow, auth flow, A2A flow.

22. **Contributing Guide with Dev Container**
    - Add `.devcontainer/` for VS Code + GitHub Codespaces.

23. **YouTube / Loom Demo**
    - A 5-minute "KubeSynapse in 5 minutes" video drives adoption more than docs.

24. **Project Communication Surface**
    - Link the README to GitHub Issues, pull requests, and the maintainer contact email.

25. **Benchmarks & Comparisons**
    - Compare startup time, resource usage vs. similar tools (e.g., LangFlow, Dify on K8s).

### 9.6 DevOps-Specific Quick Wins

26. **`agentctl` Homebrew / apt / scoop Packages**
    - Make installation one command instead of `pip install -e`.

27. **Terraform Provider**
    - DevOps engineers love Terraform. A provider for `KubeSynapse_ai_agent`, `KubeSynapse_ai_workflow` would be huge.

28. **GitOps Integration**
    - Document ArgoCD/Flux patterns for managing KubeSynapse CRDs.

29. **Cost Attribution**
    - `UsageRecord` tracks tokens. Add per-tenant, per-workflow cost dashboards.

30. **kubectl Plugin**
    - `kubectl KubeSynapse get agents` — wraps `agentctl` as a kubectl plugin.

---

## 10. Most Complex Files to Study

| File | Lines | Why It Matters |
|------|-------|----------------|
| `operator/worker.py` | ~3,500 | Workflow execution engine with DAG, parallelism, HITL, circuit breakers |
| `operator/builders/translator.py` | ~400 | Translator pattern — pure spec-to-manifest computation |
| `api-gateway/main.py` | ~13,200 | Monolithic gateway: A2A, streaming, CRUD, auth, intelligence |
| `opencode-runtime/invoke.py` | ~1,300 | Autonomous multi-turn loop with compaction and error recovery |
| `web-ui/src/App.tsx` | ~952 | UI orchestration shell connecting all panels |
| `cli/agentctl.py` | ~2,500 | Single-file comprehensive CLI |

---

*Generated by deep codebase analysis on the `preprod` branch.*
