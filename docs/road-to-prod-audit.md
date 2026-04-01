# Road to Production: Architecture Audit & Competitive Readiness Blueprint

> **Scope**: Full-depth audit of the `kubesynth` agent orchestration platform — operator, runtimes, API gateway, Helm chart, and supporting infrastructure — with actionable rewrites and standards alignment for production-grade credibility.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Weaknesses — Operator & Engine](#2-architecture-weaknesses--operator--engine)
3. [Architecture Weaknesses — Agent Runtimes](#3-architecture-weaknesses--agent-runtimes)
4. [Architecture Weaknesses — API Gateway](#4-architecture-weaknesses--api-gateway)
5. [Architecture Weaknesses — Helm & Deployment](#5-architecture-weaknesses--helm--deployment)
6. [Architecture Weaknesses — Data Layer](#6-architecture-weaknesses--data-layer)
7. [Cross-Cutting Concerns](#7-cross-cutting-concerns)
8. [Standards Adoption Roadmap](#8-standards-adoption-roadmap)
9. [Competitive Landscape Analysis](#9-competitive-landscape-analysis)
10. [Re-Architecture Plan: The Operator](#10-re-architecture-plan-the-operator)
11. [Re-Architecture Plan: The Runtime Layer](#11-re-architecture-plan-the-runtime-layer)
12. [Re-Architecture Plan: The Control Plane](#12-re-architecture-plan-the-control-plane)
13. [Re-Architecture Plan: Observability Stack](#13-re-architecture-plan-observability-stack)
14. [Re-Architecture Plan: Security Hardening](#14-re-architecture-plan-security-hardening)
15. [Re-Architecture Plan: Testing & CI/CD](#15-re-architecture-plan-testing--cicd)
16. [Migration Strategy](#16-migration-strategy)
17. [Priority Ordering](#17-priority-ordering)
18. [Appendix: Critic Flashpoints](#18-appendix-critic-flashpoints)

---

## 1. Executive Summary

The platform implements a Kubernetes-native agent orchestration system with custom CRDs, a Kopf-based Python operator, multiple runtime adapters (LangGraph, OpenCode, Goose, Codex), a FastAPI gateway, and a React web UI. The idea is strong — Kubernetes as the control plane for AI agents is the right bet. The execution, however, has accumulated significant technical debt that would not survive scrutiny from infrastructure-minded critics or enterprise buyers.

**Verdict**: The core primitives (CRDs, workflow DAG engine, runtime abstraction) are sound. The implementation needs surgical rewrites in 6 areas to be defensible.

### Critical Findings

| Severity | Count | Category |
|----------|-------|----------|
| **P0 — Ship-blocking** | 12 | Architectural deficiencies that will cause incidents at scale |
| **P1 — Credibility** | 18 | Patterns that signal prototype-grade code to reviewers |
| **P2 — Competitiveness** | 14 | Missing industry standards that competitors already implement |

---

## 2. Architecture Weaknesses — Operator & Engine

### 2.1 — Monolith Operator File (P0)

**File**: `operator/main.py` — 3,900+ lines, single Python file.

**Problem**: This is the #1 thing that will get you roasted. A single file containing 14 Kopf handlers for 6 CRDs, all resource provisioning logic, environment variable management, worker job creation, and reconciliation utilities is not defensible. No operator in the CNCF ecosystem ships like this.

**Impact**: 
- Untestable in isolation — you cannot test the AIAgent reconciler without loading the entire module
- Merge conflicts on every PR
- Cognitive load makes bugs hide (the `build_pod_template_spec` function alone handles 4 runtime kinds)
- No separation between "what the operator decides" and "what the operator does to Kubernetes"

**Fix**: Decompose into a layered architecture:
```
operator/
  controllers/
    agent_controller.py       # AIAgent reconciler
    workflow_controller.py    # AgentWorkflow reconciler  
    eval_controller.py        # AgentEval reconciler
    policy_controller.py      # AgentPolicy reconciler
    tenant_controller.py      # AgentTenant reconciler
    approval_controller.py    # AgentApproval field handler
  builders/
    statefulset_builder.py    # Pod template construction
    job_builder.py            # Worker job manifests
    network_policy_builder.py # NetworkPolicy generation
    secret_builder.py         # Secret provisioning
  services/
    runtime_registry.py       # Runtime kind → image/config mapping
    artifact_service.py       # Artifact PVC lifecycle
    state_service.py          # State store abstraction
  config.py                   # All env-var loading, validated at startup
  errors.py                   # Structured error taxonomy
  main.py                     # Entry point, Kopf startup, handler registration
```

### 2.2 — Kopf Framework Limitations (P1)

**Problem**: Kopf is a legitimate Python operator framework, but it has known production limitations:
- **No native leader election** — Kopf's peering mechanism is a CRD-based coordination that assumes well-behaved peers, not Byzantine fault tolerance. The `OPERATOR_PEERING_NAME` setting is the extent of HA support.
- **GIL-bound** — The Global Interpreter Lock means all Kopf reconciliation runs in a single process. Under heavy CRD churn (50+ agents, 20+ concurrent workflows), this becomes a bottleneck.
- **No watch bookmark/resumption guarantees** — Kopf restarts re-list all resources, causing thundering herd on operator restarts with many CRDs.
- **No built-in rate limiting** for reconciliation — a noisy CRD (rapid spec updates) will starve other reconciliations.
- **Community size** — Kopf has ~1.8k GitHub stars. Compare: Operator SDK (Go) has 7k+, Kubebuilder has 8k+. Ecosystem tooling, documentation, and battle-testing are smaller.

**Recommendation**: This is NOT a "rewrite in Go" recommendation. Kopf is viable for production *if* you mitigate:
1. Add explicit work queues per CRD kind with concurrency limits (Kopf supports `@kopf.on.create(..., param=...)` but you should add semaphore-based throttling)
2. Implement Kubernetes Lease-based leader election as a startup guard (not just peering)
3. Add circuit breakers around Kubernetes API calls from the operator itself (you have this for agent runtimes but not for your own k8s client calls)
4. Set `settings.watching.server_timeout` and `settings.watching.client_timeout` to prevent long-poll stalls

**Alternative**: If you plan to go to market against Argo Workflows, LangGraph Cloud, or CrewAI Enterprise — consider rewriting the operator in Go with `controller-runtime`. The signal this sends to infrastructure teams is worth the effort. Python operators are perceived as "glue code" by the Kubernetes community.

### 2.3 — Worker Job Coupling (P1)

**Problem**: The worker (`worker.py`) imports from the same `utils.py` and `state_store.py` as the operator but runs as a separate Kubernetes Job. The coupling is tight — any change to the operator image (even an operator-only bug fix) requires rebuilding the worker image because they share the same Docker image.

**Impact**:
- Cannot independently version or roll back workers vs. the operator
- A bug in the operator's reconciliation code means redeploying all in-flight workers
- The worker's `main()` dispatches on `WORKER_KIND` env var — this is fragile (typo in Helm values = silent failure)

**Fix**:
- Separate the worker into its own module/image: `operator-worker/`
- Share only a versioned contract (protobuf/JSON schema for the artifact format, worker env contract)
- Add a version handshake: worker checks `OPERATOR_SCHEMA_VERSION` env var and refuses to run if incompatible

### 2.4 — Artifact Storage Architecture (P0)

**Problem**: Workflow and eval results are stored as JSON files on PVCs mounted to worker Jobs. This is the single biggest scalability limitation.

**Issues**:
- **PVC lifecycle** — Each workflow/eval run creates a PVC (`worker_artifact_pvc_name`). At scale, you accumulate hundreds of PVCs that are never garbage-collected (TTL on Jobs doesn't clean PVCs).
- **No retention policy** — Artifacts grow unbounded. There is no `ARTIFACT_RETENTION_DAYS` or `MAX_ARTIFACTS_PER_WORKFLOW`.
- **Access after Job completion** — To read artifacts, you need to mount the PVC to another pod. The API gateway cannot serve artifacts directly without this indirection.
- **No indexing** — Finding "all failed runs for workflow X in the last 24 hours" requires listing PVCs, mounting them, and reading JSON files.
- **Journal (NDJSON) append-only log** — Good pattern, but file-based NDJSON on a PVC has no rotation, no compaction, no search.

**Fix**: Migrate to a proper artifact backend:
1. **Short-term**: Use the existing PostgreSQL for structured run metadata (you already have `state_store.py` doing this!). Make it the primary source, not a "mirror".
2. **Medium-term**: Store artifact payloads in object storage (S3/MinIO/GCS) with PostgreSQL as the index. The journal becomes a proper event stream (NATS JetStream, which you already deploy but don't use for this).
3. **Long-term**: PVCs remain only for agent workspace state (the working directory). Run results flow through the event bus.

### 2.5 — Dual Source of Truth (P0)

**Problem**: `state_store.py` mirrors workflow/eval state to PostgreSQL, but the CRD `.status` subresource is also updated. The code explicitly calls both `patch_custom_status()` AND `safe_record_workflow_state()`. When they disagree (and they will, because the DB write can succeed while the CRD patch hits a 409 conflict), you have split-brain state.

**Current code** in `worker.py`:
```python
patch_workflow_status(...)  # Patches CRD status
safe_record_workflow_state(...)  # Writes to PostgreSQL
```

**Fix**: Choose one primary source of truth:
- **CRD status** for Kubernetes-native consumers (kubectl, other controllers)
- **PostgreSQL** for the API gateway, UI, and historical queries
- Make the DB write *derived from* the CRD status via a separate reconciliation loop (watch CRD status changes → update DB), not by the worker writing to both. This is the standard "status projection" pattern.

### 2.6 — No Idempotency Guarantees (P0)

**Problem**: The workflow worker's `run_workflow_worker()` loads the artifact, checks if `generation` matches, then proceeds. But there's no distributed lock. If the operator re-enqueues a workflow (the `workflow_should_requeue` timer fires), a second worker Job can start while the first is still running. Both will race on the same artifact PVC.

**Fix**:
1. Add a Kubernetes Lease per workflow run: `{workflow_name}-gen-{generation}` — worker acquires before starting, releases on completion
2. Use optimistic concurrency on the CRD status: include `resourceVersion` in status patches and retry on 409
3. Add a `runId` uniqueness check: if the DB already has a `running` record with a different `runId` for the same workflow+generation, refuse to start

### 2.7 — Thread-Based Parallel Step Execution (P1)

**Problem**: The worker executes frontier steps in parallel using `ThreadPoolExecutor`. For I/O-bound HTTP calls to agent runtimes, this works. But:
- No concurrency limit per tenant — a 20-step fan-out will spawn 20 threads, each calling an agent runtime, potentially overwhelming the cluster
- No back-pressure — if the thread pool is full, new waves queue silently
- Thread crash handling is basic — a `RuntimeError` in one thread doesn't cancel siblings

**Fix**:
- Add a configurable `MAX_PARALLEL_STEPS` (default: 4) with per-tenant overrides from the AgentTenant CRD
- Use `concurrent.futures.wait(return_when=FIRST_EXCEPTION)` to fail fast when a sibling fails
- Add step-level timeout enforcement independent of the HTTP timeout (a step can time out even if the HTTP call succeeds but the agent is stuck in a loop)

### 2.8 — SHA-1 Usage (P2)

**Problem**: `hashlib.sha1()` is used for thread ID generation, run ID generation, and resource name hashing throughout `utils.py` and `worker.py`. SHA-1 is cryptographically broken and its use signals "didn't think about security" even when the use case is non-cryptographic.

**Fix**: Replace all `sha1` calls with `sha256` (and take the first N hex chars for the same truncation). Zero functional impact, removes a CVE scanner finding.

### 2.9 — No Structured Error Codes (P1)

**Problem**: Errors bubble up as string messages in `RuntimeError`, `ValueError`, and `kopf.PermanentError`. The API gateway, UI, and worker all have to pattern-match on error text to determine the failure type.

**Fix**: Define an error taxonomy:
```python
class OperatorError:
    code: str       # e.g., "AGENT_RUNTIME_TIMEOUT", "WORKFLOW_CYCLE_DETECTED"
    severity: str   # "permanent" | "transient" 
    message: str
    metadata: dict  # step_name, agent_ref, etc.
```
Emit these in CRD status `.conditions[]` using the standard Kubernetes condition format:
```yaml
conditions:
  - type: RuntimeReady
    status: "False"
    reason: AgentRuntimeTimeout
    message: "Agent 'builder' did not become ready within 180s"
    lastTransitionTime: "2026-03-21T19:15:00Z"
```

### 2.10 — Missing CRD Status Conditions (P0)

**Problem**: The CRDs use a custom `phase` field ("queued", "running", "completed", "failed") but do not implement standard Kubernetes `conditions[]`. This means:
- `kubectl wait --for=condition=Ready` doesn't work
- Standard Kubernetes tooling (Argo CD health checks, Flux Kustomize, kstatus) cannot determine resource health
- No transition timestamps per condition

**Fix**: Add `.status.conditions[]` to all CRDs following the [Kubernetes API conventions](https://github.com/kubernetes/community/blob/master/contributors/dml/sig-architecture/api-conventions.md#typical-status-properties):
- `Ready` — resource is fully reconciled
- `Progressing` — resource is being provisioned/executed  
- `Degraded` — resource is partially functional
- Retain `phase` for backward compat but derive it from conditions

---

## 3. Architecture Weaknesses — Agent Runtimes

### 3.1 — God File: agent_logic.py (P0)

**File**: `agent-runtime/agent_logic.py` — 4,000+ lines, single Python file.

**Problem**: This is worse than the operator because it mixes:
- LangGraph state machine definition
- Tool schema generation
- Tool execution (sandbox, local shell, MCP, A2A, subagent, file edit, search)
- Workspace scanning
- Doom loop detection
- Cost tracking
- Streaming event generation
- Policy enforcement
- Skill file materialization
- Fuzzy matching for file edits
- Session management

**Impact**: This file is the brain of the entire system. A bug anywhere in it takes down all agent operations. It cannot be tested at the function level because helper functions depend on module-level globals (`RUNTIME`, `SKILL_RUNTIME_CONFIG`, etc.).

**Fix**: Split into focused modules:
```
agent-runtime/
  core/
    state.py            # LangGraph state definition
    graph.py            # Graph construction and node wiring
    supervisor.py       # Supervisor prompt building, tool schema
    session.py          # Session lifecycle, checkpoint management
  tools/
    registry.py         # Tool discovery and schema generation
    sandbox.py          # OpenSandbox tool execution
    local_shell.py      # Local command execution  
    mcp.py              # MCP server invocations
    a2a.py              # Agent-to-Agent delegation
    file_edit.py        # Edit with fuzzy matching, batch read
    search.py           # Code search, grep
    subagent.py         # Subagent team coordination
  autonomy/
    loop.py             # Autonomous action loop
    doom_detection.py   # Doom loop pattern matching
    replanning.py       # Adaptive re-planning logic
    verification.py     # Auto-verify, auto-lint, auto-test
  policy/
    enforcement.py      # Policy loading, model resolution
    cost_tracking.py    # Token counting, cost calculation
    guardrails.py       # Input/output guardrails
  workspace/
    scanner.py          # Project type detection
    profile.py          # Workspace profile (lint/test commands)
  config.py             # All constants, env vars
  main.py               # FastAPI app, routes, startup
```

### 3.2 — SQLite for LangGraph Checkpointing (P0)

**Problem**: `SqliteSaver` is used for LangGraph checkpoint persistence. SQLite is single-writer, file-locked, and local to the pod. This means:
- **No horizontal scaling** — You cannot run 2 replicas of the same agent runtime (the StatefulSet has `replicas: 1` for good reason)
- **Checkpoint loss on pod eviction** — If the PVC is lost, all conversation history is gone
- **No cross-agent checkpoint sharing** — Subagent delegation cannot share checkpoints

**Fix**:
- Replace with PostgreSQL-backed checkpointing: `langgraph-checkpoint-postgres` (official LangGraph package)
- Use the existing PostgreSQL instance with a dedicated `agent_checkpoints` schema
- This unlocks horizontal scaling: multiple pods can serve the same agent, routing by thread_id

### 3.3 — Module-Level Global State (P1)

**Problem**: `agent_logic.py` initializes dozens of globals at import time:
```python
RUNTIME: dict = {}
SKILL_RUNTIME_CONFIG: dict = {}
CONFIGURED_ALLOWED_MODELS: frozenset[str] = frozenset(...)
```
These are mutated during request processing (`RUNTIME["local_tool_inventory"] = metadata`), making the module implicitly stateful. Test isolation is impossible without monkeypatching.

**Fix**: Replace with a `RuntimeContext` dataclass passed through the LangGraph state or FastAPI dependency injection:
```python
@dataclass
class RuntimeContext:
    allowed_models: frozenset[str]
    skill_config: SkillConfig
    tool_inventory: ToolInventory
    workspace_profile: WorkspaceProfile | None
```

### 3.4 — Cost Tracking is Hardcoded (P2)

**Problem**: `_MODEL_COST_PER_MILLION` dictionary in `agent_logic.py` hardcodes per-token costs for models. These prices change monthly. This is a maintenance burden and will always be wrong.

**Fix**: 
- Query LiteLLM's `/model/info` endpoint at startup for model pricing (LiteLLM maintains cost tables)
- Fall back to a configurable JSON env var `AGENT_MODEL_COSTS_JSON` for overrides
- Remove the hardcoded table entirely

### 3.5 — OpenCode Runtime Process Management (P1)

**Problem**: `opencode-runtime/main.py` manages the OpenCode CLI as a subprocess:
- Starts the process at container startup
- Polls `/ready` endpoint for health
- Uses file-based JSON for session mapping

This is fragile:
- If the subprocess dies, the runtime container stays "healthy" (FastAPI is still up) but all invocations fail
- No process restart logic — a crash requires pod restart
- The session registry uses `threading.Lock` + file writes — a crash between `lock.release()` and `file.write()` corrupts the mapping

**Fix**:
- Add a process supervisor (e.g., a health-check background task that restarts the subprocess on death)
- Move session registry to Redis (you already deploy Redis) 
- Implement a liveness probe that checks both FastAPI health AND subprocess health

### 3.6 — No Runtime Contract Versioning (P1)

**Problem**: The operator invokes agent runtimes via HTTP at `/invoke` and `/invoke/stream`. The request/response schema is implicitly defined by Pydantic models in each runtime. There's no shared contract — the LangGraph runtime's `InvokeRequest` has different fields than OpenCode's `InvokeRequest`.

**Impact**: A change to the operator's invoke payload can break a runtime that hasn't been updated. Different runtime kinds silently ignore unknown fields.

**Fix**:
- Define an `AgentRuntimeContract` as a versioned JSON Schema or Protobuf definition:
  ```
  contracts/
    v1alpha1/
      invoke_request.json
      invoke_response.json
      stream_event.json
      health_response.json
  ```
- Each runtime declares which contract version it implements via a `/info` endpoint
- The operator checks contract compatibility before first invocation

---

## 4. Architecture Weaknesses — API Gateway

### 4.1 — Authentication Tightly Coupled (P1)

**Problem**: `api-gateway/main.py` handles REST API routing, Kubernetes proxying, AND authentication (local users, OIDC, SAML, LDAP, JWT token management, session management, rate limiting). `auth_store.py` adds SQLAlchemy models for users, sessions, audit logs, usage tracking, workflow runs, and chat sessions.

**Impact**: The gateway is a God service. Authentication changes risk breaking API routing. The auth database schema (users, sessions, audit logs) is mixed with domain data (workflow runs, chat sessions, usage stats).

**Fix**: Extract authentication into a sidecar or separate service:
```
auth-service/           # Standalone authentication service
  main.py               # OIDC, SAML, LDAP, local auth
  models.py             # User, Session, AuditLog models
  jwt_utils.py          # Token generation/validation
api-gateway/            # Thin routing proxy
  main.py               # Route requests, validate JWT
  proxy.py              # K8s API proxying
```
The gateway validates JWTs but delegates authentication flows to the auth service.

### 4.2 — No API Versioning (P0)

**Problem**: All endpoints are at `/api/v1/...` but there's no mechanism for versioned API evolution. Adding a v2 endpoint requires modifying the single `main.py`. Breaking changes to existing endpoints will break all clients simultaneously.

**Fix**: 
- Implement proper API versioning via URL prefix routing:
  ```python
  v1_router = APIRouter(prefix="/api/v1")
  v2_router = APIRouter(prefix="/api/v2")
  ```
- Add API deprecation headers (`Sunset`, `Deprecation`)
- Publish OpenAPI schemas per version with breaking change detection in CI

### 4.3 — No Request Tracing (P1)

**Problem**: There's no `X-Request-Id` generation or propagation. When a workflow invocation traverses API Gateway → Operator → Worker → Agent Runtime → MCP Sidecar, there's no correlation ID linking the traces.

**Fix**: 
- Generate `X-Request-Id` at the gateway (or accept from client)
- Propagate through all internal HTTP calls
- Store in CRD annotations and log entries
- Wire into OpenTelemetry trace context (W3C Trace Context standard)

### 4.4 — No Rate Limiting (P1)

**Problem**: Beyond login attempt rate limiting, there are no request rate limits. A single user can:
- Create hundreds of agents
- Trigger unlimited concurrent workflow runs
- Make unlimited invoke calls

**Fix**: Implement tiered rate limiting:
- Per-user: `X requests/minute` for invoke, `Y creates/hour` for resources
- Per-tenant: Aggregate limits from AgentTenant CRD quotas
- Global: Cluster-wide circuit breaker (total in-flight invoke calls)
- Use Redis (already deployed) as the rate limiter backend

---

## 5. Architecture Weaknesses — Helm & Deployment

### 5.1 — Monolithic Chart (P1)

**Problem**: A single `kubesynth` chart deploys the entire platform: PostgreSQL, Redis, Qdrant, NATS, LiteLLM, Operator, API Gateway, Web UI, CRDs, RBAC, NetworkPolicies. This is ~26 templates in one chart.

**Impact**:
- Cannot upgrade infrastructure components (PostgreSQL) separately from the application (operator)
- Cannot deploy just the CRDs for a GitOps workflow (CRDs must be applied before the operator, but Helm doesn't guarantee ordering)
- External users wants to bring their own PostgreSQL/Redis — they can't because the chart assumes it deploys them

**Fix**: Split into sub-charts:
```
charts/
  ai-agent-platform/          # Umbrella chart
    Chart.yaml                 # dependencies on sub-charts
    values.yaml
  ai-agent-crds/               # CRD-only chart (install first)
    templates/
      aiagent-crd.yaml
      agentworkflow-crd.yaml
      ...
  ai-agent-operator/           # Operator + RBAC
    templates/
  ai-agent-gateway/            # API Gateway + Web UI
    templates/
  ai-agent-infra/              # PostgreSQL, Redis, Qdrant, NATS, LiteLLM
    # OR: use Bitnami sub-charts
```

### 5.2 — No CRD Lifecycle Management (P0)

**Problem**: CRDs are embedded in Helm templates. Helm has a well-known issue: `helm uninstall` deletes CRDs, which deletes ALL custom resources in the cluster. This is a **data loss risk**.

**Fix**:
- Move CRDs to a separate chart with `helm.sh/resource-policy: keep` annotations
- Or use a pre-install/pre-upgrade Job that applies CRDs via `kubectl apply`
- Add CRD conversion webhooks for version migration (you'll eventually need `v1alpha2` → `v1beta1`)

### 5.3 — Hardcoded Image References (P2)

**Problem**: Default image references use `ghcr.io/your-org/...` placeholders. The operator itself has `RUNTIME_IMAGE = os.getenv("AGENT_RUNTIME_IMAGE", "ghcr.io/your-org/ai-agent-runtime:latest")`. Using `:latest` tags is an anti-pattern.

**Fix**: 
- Pin all images to SHA digests in production values
- Add image digest verification in the operator (reject `:latest` in production namespaces)
- Implement a `values.schema.json` for the Helm chart with required image fields

### 5.4 — No Helm Schema Validation (P2)

**Problem**: `values.yaml` has no `values.schema.json`. Users can pass invalid values (wrong types, missing required fields) and Helm will silently render broken manifests.

**Fix**: Add comprehensive JSON schema validation for all value fields.

---

## 6. Architecture Weaknesses — Data Layer

### 6.1 — No Schema Migrations (P0)

**Problem**: `state_store.py` uses `Base.metadata.create_all(bind=ENGINE)` to "migrate" the database. This creates tables that don't exist but **never alters existing tables**. If you add a column to `WorkflowRun`, existing deployments break.

**Fix**: 
- Add Alembic for database migrations
- Generate migration files for every schema change
- Run migrations as an init container before the operator starts
- Add a schema version table and refuse to start on version mismatch

### 6.2 — No Connection Pooling Configuration (P1)

**Problem**: SQLAlchemy engine is created with `pool_pre_ping=True` but no pool size configuration. The default pool size is 5 connections. Under load (many concurrent workflow saves), this becomes a bottleneck.

**Fix**:
```python
ENGINE = create_engine(
    DATABASE_URL,
    pool_size=int(os.getenv("DATABASE_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DATABASE_MAX_OVERFLOW", "20")),
    pool_timeout=int(os.getenv("DATABASE_POOL_TIMEOUT", "30")),
    pool_recycle=int(os.getenv("DATABASE_POOL_RECYCLE", "1800")),
    pool_pre_ping=True,
)
```

### 6.3 — PostgreSQL as Single Point of Failure (P1)

**Problem**: Single-replica PostgreSQL StatefulSet with no replication, no automated backups, no failover.

**Fix**:
- For production: Use CloudNativePG operator or Zalando Postgres Operator for HA PostgreSQL
- Add automated WAL-based backups to object storage
- Configure PgBouncer as a connection pooler in front of PostgreSQL

### 6.4 — NATS Deployed but Unused (P2)

**Problem**: NATS is deployed in the Helm chart and the architecture doc mentions it for "future A2A coordination", but no component publishes to or subscribes from NATS. It's consuming cluster resources for nothing.

**Fix**: Either:
- Remove NATS from the default deployment (add as optional)
- OR implement it for its intended purpose: workflow event streaming, agent-to-agent messaging, and run log aggregation

---

## 7. Cross-Cutting Concerns

### 7.1 — Observability Gap (P0)

**Current state**:
- `OTEL_EXPORTER_OTLP_ENDPOINT` is accepted as an env var but never used to create actual spans in the operator or worker
- The agent runtime has `opentelemetry` imports and a `TracerProvider` setup, but spans are not propagated to the operator/gateway/worker
- No metrics beyond Prometheus `/metrics` on the API Gateway (via `prometheus_fastapi_instrumentator`)
- No distributed tracing — a request touching 5 services produces 5 independent log streams
- Structured JSON logging exists but with no correlation ID linking them

**Fix**: See [Section 13 — Observability Stack](#13-re-architecture-plan-observability-stack).

### 7.2 — No Graceful Shutdown (P1)

**Problem**: 
- The operator has no `@kopf.on.cleanup()` handler to drain in-flight reconciliations
- The agent runtime has no signal handler — `SIGTERM` during an autonomous action loop leaves the LLM call hanging and the checkpoint in an inconsistent state
- The worker doesn't handle `SIGTERM` — Kubernetes sends SIGTERM, but the worker could be mid-write to the artifact JSON file

**Fix**: Add graceful shutdown to every component:
- Operator: `@kopf.on.cleanup()` — stop accepting new reconciliations, wait for in-flight ones
- Agent runtime: Signal handler → set shutdown flag → finish current action → save checkpoint → exit
- Worker: Signal handler → save current progress → patch CRD status to "interrupted" → exit non-zero (so the Job retries)

### 7.3 — Secret Management (P1)

**Problem**: 
- LiteLLM API keys are stored in a Kubernetes Secret referenced by env var — acceptable
- But the `LITELLM_API_KEY` is passed as a plain-text environment variable to every agent runtime pod. If any agent runtime is compromised, the attacker gets the master LiteLLM key.
- Docker Hub PAT is stored in a `dockerconfigjson` Secret — fine, but the conversation history shows it was passed as a CLI argument (`docker login -p <PAT>`), which is logged in shell history

**Fix**:
- Use per-agent LiteLLM API keys with scoped permissions instead of the master key
- Implement Kubernetes Secret Store CSI driver integration for cloud-managed secrets
- Never pass secrets as CLI arguments — use `--password-stdin`

### 7.4 — No Multi-Tenancy Enforcement (P1)

**Problem**: `AgentTenant` CRD exists but enforcement is incomplete:
- No Kubernetes admission webhook validates that agents are created in authorized namespaces
- No network isolation between tenants (NetworkPolicies are per-agent, not per-tenant)
- No resource quotas are applied to tenant namespaces
- The API gateway does namespace filtering but doesn't enforce tenant boundaries at the Kubernetes level

**Fix**:
- Add a ValidatingWebhookConfiguration that enforces:
  - Agents can only be created in namespaces owned by a tenant
  - Resource counts respect tenant quotas
  - Model access respects tenant-level allowed models
- Apply `ResourceQuota` and `LimitRange` per tenant namespace
- Add tenant-scoped NetworkPolicies that prevent cross-tenant traffic

---

## 8. Standards Adoption Roadmap

### 8.1 — Google A2A Protocol (Priority: HIGH)

**What**: Google's [Agent-to-Agent (A2A) protocol](https://google.github.io/A2A/) is an emerging standard for inter-agent communication. It defines discovery (Agent Cards), task lifecycle, and streaming.

**Current gap**: The platform implements custom A2A delegation logic in `agent_logic.py` using direct HTTP calls with a custom payload format. This is incompatible with any external A2A implementation.

**Adoption plan**:
1. Implement the A2A Agent Card spec as a sidecar endpoint on each agent runtime
2. Replace the custom `execute_a2a_call()` with A2A client that speaks the standard protocol
3. Expose agent discovery via `.well-known/agent.json`
4. Support both push (webhook) and pull (polling) notification modes

### 8.2 — Model Context Protocol (MCP) — Latest Spec (Priority: HIGH)

**What**: Anthropic's [MCP](https://modelcontextprotocol.io/) is the emerging standard for LLM ↔ tool communication.

**Current state**: The platform has MCP sidecar implementations, but they implement a custom `/tools/{tool_name}` endpoint, not the standard MCP JSON-RPC protocol over stdio or SSE transport.

**Adoption plan**:
1. Update MCP sidecars to implement the official MCP server SDK (stdio transport for local, SSE for remote)
2. Agent runtimes should use the official MCP client SDK
3. Support MCP resource protocol (not just tools) — enables agents to read K8s resources, files, etc. as MCP resources
4. Implement MCP sampling for controlled LLM invocations through the MCP channel

### 8.3 — OpenTelemetry (Priority: HIGH)

**What**: OTEL is the CNCF standard for traces, metrics, and logs.

**Current state**: The agent runtime imports OTEL packages but the operator/gateway/worker don't. No trace context propagation exists.

**Adoption plan**:
1. Add `opentelemetry-instrumentation-fastapi` to API gateway and runtimes
2. Instrument the operator with spans per reconciliation cycle
3. Propagate W3C `traceparent` header through all internal HTTP calls
4. Export to any OTLP-compatible backend (Jaeger, Tempo, Datadog)
5. Define semantic conventions for agent operations:
   - `agent.invoke` — span per runtime invocation
   - `workflow.step` — span per step execution
   - `tool.call` — span per tool execution
   - `llm.completion` — span per LLM call (via LiteLLM callbacks)

### 8.4 — CloudEvents (Priority: MEDIUM)

**What**: [CloudEvents](https://cloudevents.io/) is a CNCF specification for describing events in a common way.

**Current gap**: The journal system (`append_journal_event`) writes custom NDJSON events. These are not consumable by external event-driven systems.

**Adoption plan**:
1. Wrap journal events in CloudEvents format
2. Publish to NATS JetStream as the event bus
3. Support webhook subscriptions for external consumers
4. Event types: `ai.agent.invoked`, `ai.workflow.step.completed`, `ai.eval.case.passed`, `ai.approval.requested`

### 8.5 — Kubernetes Gateway API (Priority: MEDIUM)

**What**: The [Gateway API](https://gateway-api.sigs.k8s.io/) is the successor to Ingress for Kubernetes traffic management.

**Current gap**: No ingress/gateway configuration in the Helm chart. Users manually port-forward.

**Adoption plan**:
1. Add optional HTTPRoute resources for the API gateway and web UI
2. Support GRPCRoute for future gRPC transport (efficient for streaming)
3. Support BackendTLSPolicy for mTLS between gateway and services

### 8.6 — OCI Artifacts for Agent Packaging (Priority: LOW)

**What**: Use OCI registries to package and distribute agent definitions (CRD YAML + skills + config files) as versioned artifacts.

**Benefit**: Enables `agentctl push myagent:v1.2.0` and `agentctl pull myagent:v1.2.0` for agent marketplace/registry workflows.

### 8.7 — OpenAPI 3.1 + JSON Schema for CRDs (Priority: MEDIUM)

**Current gap**: CRD templates have basic `openAPIV3Schema` validation but many fields are `x-kubernetes-preserve-unknown-fields: true`, which disables validation. The `spec.steps[].execution` field accepts any object.

**Fix**: Define comprehensive JSON Schema for all CRD fields. Use `kubebuilder` markers or manual schema definitions. This enables:
- `kubectl explain aiagent.spec.steps[].execution`
- IDE autocompletion for CRD YAML
- Server-side validation rejects malformed CRDs before the operator sees them

### 8.8 — LangChain/LangSmith Tracing Compatibility (Priority: LOW)

If targeting the LangChain ecosystem, add optional LangSmith trace export via `LANGCHAIN_TRACING_V2=true`. This allows users with existing LangSmith dashboards to trace agent operations without re-tooling.

---

## 9. Competitive Landscape Analysis

| Feature | This Platform | LangGraph Cloud | CrewAI | Argo + Agents | Bee Agent Framework |
|---------|--------------|-----------------|--------|---------------|---------------------|
| K8s-native CRDs | ✅ | ❌ (SaaS) | ❌ | ✅ | ❌ |
| Multi-runtime | ✅ (4 runtimes) | ❌ (LangGraph only) | ❌ | ✅ (containers) | ❌ |
| Workflow DAG | ✅ | ✅ | ✅ (sequential/hierarchical) | ✅ | ❌ |
| A2A delegation | ✅ (custom) | ❌ | ✅ (built-in) | ❌ | ❌ |
| HITL approval | ✅ | ✅ | ❌ | ✅ | ❌ |
| MCP integration | ✅ (custom) | ❌ | ❌ | ❌ | ✅ |
| Multi-tenancy | Partial | ✅ (SaaS) | ❌ | Namespace-based | ❌ |
| Observability | Weak | ✅ (LangSmith) | ❌ | ✅ (Argo UI) | ❌ |
| Self-hosted | ✅ | ❌ | ✅ | ✅ | ✅ |
| Enterprise auth | ✅ (OIDC/SAML/LDAP) | SaaS SSO | ❌ | OIDC | ❌ |
| Schema migrations | ❌ | ✅ | N/A | ✅ | N/A |
| Horizontal scaling | ❌ (SQLite checkpoint) | ✅ | ❌ | ✅ | ❌ |

**Differentiators to lean into**:
1. Self-hosted + K8s-native — the only real option for regulated industries
2. Multi-runtime — not locked into LangChain/LangGraph
3. Enterprise auth built-in — OIDC/SAML/LDAP is hard; you have it
4. MCP ecosystem — if you adopt the standard properly, you're ahead

**Weaknesses vs. competitors**:
1. LangGraph Cloud has observability (LangSmith) — you don't
2. Argo Workflows has battle-tested DAG execution — yours is bespoke
3. CrewAI has simpler DX — your YAML CRDs are verbose
4. Everyone scales horizontally — you can't (SQLite)

---

## 10. Re-Architecture Plan: The Operator

### 10.1 — Target Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    OPERATOR PROCESS                          │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ Agent Controller  │  │ Policy Controller │                 │
│  │ • create/update   │  │ • create/update   │                 │
│  │ • delete/resume   │  │ • validate        │                 │
│  └────────┬─────────┘  └──────────────────┘                 │
│           │                                                  │
│  ┌────────▼─────────┐  ┌──────────────────┐                 │
│  │ StatefulSet       │  │ Workflow          │                 │
│  │ Builder           │  │ Controller        │                 │
│  │ • pod template    │  │ • enqueue job     │                 │
│  │ • env injection   │  │ • watchdog timer  │                 │
│  │ • sidecar merge   │  │ • requeue stale   │                 │
│  └──────────────────┘  └────────┬─────────┘                 │
│                                 │                            │
│  ┌──────────────────┐  ┌────────▼─────────┐                 │
│  │ Tenant Controller │  │ Job Builder       │                 │
│  │ • namespace setup │  │ • worker manifest │                 │
│  │ • quota enforce   │  │ • PVC lifecycle   │                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                              │
│  ┌──────────────────────────────────────────┐                │
│  │ Shared Services Layer                     │                │
│  │ • config.py (validated env loading)       │                │
│  │ • errors.py (structured error taxonomy)   │                │
│  │ • state_service.py (DB abstraction)       │                │
│  │ • runtime_registry.py (kind → config)     │                │
│  │ • metrics.py (Prometheus counters)        │                │
│  └──────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────┘
```

### 10.2 — Configuration Overhaul

Replace scattered `os.getenv()` calls with a validated configuration object loaded once at startup:

```python
@dataclass(frozen=True)
class OperatorConfig:
    """Immutable, validated configuration loaded once at startup."""
    operator_namespace: str
    litellm_svc: str
    secret_name: str
    runtime_images: RuntimeImageConfig
    worker_config: WorkerConfig
    agent_defaults: AgentDefaultsConfig
    
    @classmethod
    def from_environment(cls) -> "OperatorConfig":
        """Load and validate all configuration from environment."""
        # Validate ALL required vars upfront — fail fast if misconfigured
        ...
```

### 10.3 — Reconciliation Pattern

Each controller should follow this pattern:

```python
class AgentController:
    def __init__(self, config: OperatorConfig, state: StateService, metrics: MetricsCollector):
        self.config = config
        self.state = state
        self.metrics = metrics
    
    def reconcile_create(self, spec: dict, meta: dict, namespace: str, name: str, **kwargs):
        """Idempotent create/update for AIAgent resources."""
        with self.metrics.reconcile_timer("aiagent", "create"):
            desired_state = self._build_desired_state(spec, meta, namespace, name)
            current_state = self._fetch_current_state(namespace, name)
            actions = self._diff(desired_state, current_state)
            for action in actions:
                action.execute()
            self._update_status(namespace, name, desired_state)
```

Key principles:
1. **Desired state computation** is pure (testable without Kubernetes)
2. **Current state fetch** is isolated
3. **Diff** produces an explicit action list (auditable)
4. **Execution** is the only side-effecting step

---

## 11. Re-Architecture Plan: The Runtime Layer

### 11.1 — Unified Runtime Interface

Define a formal interface that all runtimes implement:

```python
class AgentRuntime(Protocol):
    """Contract that all agent runtimes must implement."""
    
    async def invoke(self, request: InvokeRequest) -> InvokeResponse: ...
    async def invoke_stream(self, request: InvokeRequest) -> AsyncIterator[StreamEvent]: ...
    async def cancel(self, session_id: str) -> CancelResponse: ...
    async def health(self) -> HealthResponse: ...
    async def info(self) -> RuntimeInfo: ...  # capabilities, contract version
```

Publish this as a pip-installable `agent-runtime-contract` package.

### 11.2 — Checkpoint Migration

Replace SQLite with PostgreSQL for all runtimes:

```python
# Before (per-pod SQLite)
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("sqlite:///app/state/agent.db")

# After (shared PostgreSQL)
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(os.getenv("CHECKPOINT_DATABASE_URL"))
```

### 11.3 — Tool Plugin Architecture

Replace the monolithic tool execution with a plugin registry:

```python
class ToolPlugin(Protocol):
    name: str
    schema: dict[str, Any]
    
    async def execute(self, args: dict, context: ToolContext) -> ToolResult: ...
    
class ToolRegistry:
    def __init__(self):
        self._plugins: dict[str, ToolPlugin] = {}
    
    def register(self, plugin: ToolPlugin) -> None: ...
    def discover(self, context: RuntimeContext) -> list[ToolSchema]: ...
    async def execute(self, tool_name: str, args: dict, context: ToolContext) -> ToolResult: ...
```

This enables:
- Third-party tool plugins without modifying core code
- Per-agent tool restrictions via policy
- Tool execution metrics and tracing per-plugin

---

## 12. Re-Architecture Plan: The Control Plane

### 12.1 — Event-Driven Architecture

Current: Operator polls, worker writes files, gateway reads CRD status.
Target: Event-driven with NATS JetStream as the backbone.

```
AIAgent CRD change
  → Kopf handler publishes CloudEvent to NATS
    → Operator reconciler subscribes, provisions resources
    → Status projector subscribes, updates PostgreSQL
    → Webhook service subscribes, notifies external systems

Workflow step completion
  → Worker publishes CloudEvent to NATS
    → Status projector updates CRD status + PostgreSQL
    → API Gateway server-sent events push to UI
    → Audit service records the event
```

### 12.2 — NATS JetStream Integration

Replace the file-based journal with NATS JetStream:

```
Streams:
  AGENT_EVENTS      — all agent lifecycle events
  WORKFLOW_EVENTS    — step start/complete/fail events
  EVAL_EVENTS        — eval case results
  APPROVAL_EVENTS    — approval request/response  
  AUDIT_EVENTS       — user actions, API calls

Consumers:
  status-projector   — updates PostgreSQL from events
  crd-patcher        — updates CRD status from events
  webhook-relay      — forwards events to external webhooks
  ui-sse-bridge      — converts events to SSE for Web UI
```

### 12.3 — API Gateway as Thin Proxy

Reduce the gateway to:
1. JWT validation
2. Request routing (to agent runtimes, operator API, auth service)
3. SSE bridge (subscribe to NATS, stream events to clients)
4. Rate limiting (Redis-backed)

All business logic moves to dedicated services.

---

## 13. Re-Architecture Plan: Observability Stack

### 13.1 — Distributed Tracing

Every HTTP call between components must propagate `traceparent`:

```
Client → API Gateway → Operator → Worker → Agent Runtime → LLM
  |         |              |          |           |           |
  ├─ span ──┤              |          |           |           |
  |         ├──── span ────┤          |           |           |
  |         |              ├── span ──┤           |           |
  |         |              |          ├── span ───┤           |
  |         |              |          |           ├── span ───┤
  └─────────────── trace ────────────────────────────────────┘
```

Implementation per component:
- **API Gateway**: `opentelemetry-instrumentation-fastapi` auto-instruments routes
- **Operator**: Manual spans via `tracer.start_as_current_span("reconcile_agent")`
- **Worker**: Spans per workflow step, per invoke call
- **Agent Runtime**: Spans per LLM call, per tool execution, per autonomy step
- **MCP Sidecars**: `opentelemetry-instrumentation-httpx` for outbound calls

### 13.2 — Metrics

Define platform-specific Prometheus metrics:

```
# Operator
operator_reconcile_total{crd_kind, action, status}           # Counter
operator_reconcile_duration_seconds{crd_kind, action}        # Histogram
operator_active_agents{namespace}                             # Gauge
operator_active_workflows{namespace, phase}                   # Gauge

# Agent Runtime  
agent_invoke_total{agent_name, model, status}                 # Counter
agent_invoke_duration_seconds{agent_name, model}              # Histogram
agent_tokens_total{agent_name, model, direction}              # Counter (input/output tokens)
agent_cost_usd_total{agent_name, model}                       # Counter
agent_tool_calls_total{agent_name, tool_name, status}         # Counter
agent_doom_loop_detections_total{agent_name}                  # Counter
agent_autonomy_steps_total{agent_name, outcome}               # Counter

# Workflow
workflow_step_duration_seconds{workflow, step, agent, status} # Histogram
workflow_completion_total{workflow, status}                    # Counter
workflow_approval_wait_seconds{workflow, step}                 # Histogram

# API Gateway
gateway_request_total{method, path, status}                   # Counter
gateway_request_duration_seconds{method, path}                # Histogram
gateway_auth_attempts_total{method, status}                   # Counter
```

### 13.3 — Structured Logging Standard

Adopt a consistent log format across all components:

```json
{
  "timestamp": "2026-03-21T19:15:00.000Z",
  "level": "INFO",
  "logger": "operator.agent-controller",
  "message": "Agent runtime provisioned",
  "trace_id": "abc123",
  "span_id": "def456",
  "attributes": {
    "k8s.namespace": "team-alpha",
    "k8s.resource.kind": "AIAgent",
    "k8s.resource.name": "code-builder",
    "agent.runtime_kind": "opencode",
    "agent.model": "gpt-4.1",
    "reconcile.action": "create",
    "reconcile.duration_ms": 1250
  }
}
```

---

## 14. Re-Architecture Plan: Security Hardening

### 14.1 — Agent Sandbox Isolation

Current: Agents run with `allowPrivilegeEscalation: false` and `readOnlyRootFilesystem: true`. Good start.

**Missing**:
- **Seccomp profiles** — No `securityContext.seccompProfile`. Add `RuntimeDefault` at minimum.
- **AppArmor** — No annotations for AppArmor confinement
- **gVisor/Kata** — No RuntimeClass support for hardware-level isolation. Agents execute arbitrary code via tool calling; this is a sandbox escape risk.
- **Network egress controls** — NetworkPolicies restrict inter-pod traffic but don't limit outbound internet access. An agent with `bash` tool access can `curl` external services.
- **Filesystem quotas** — PVC sizes are configurable but no per-agent ephemeral storage limits

**Fix**:
1. Add optional `RuntimeClassName` field to AIAgent CRD for gVisor/Kata sandboxing
2. Default to `Restricted` Pod Security Standard (PSS)
3. Add configurable egress NetworkPolicy: default-deny with explicit allow-list for LiteLLM, MCP hub, and user-specified domains
4. Implement ephemeral storage limits: `resources.limits.ephemeral-storage`

### 14.2 — Secret Rotation

**Problem**: LiteLLM API key, MCP bearer token, and Docker registry credentials are static. No rotation mechanism.

**Fix**:
- Integrate with External Secrets Operator (already partially implemented) for automated rotation
- Add a `SecretRotation` CRD or annotation that triggers key regeneration on a schedule
- Agent runtimes should re-read secrets at runtime (not just at pod start) via a sidecar or inotify watch on mounted Secret volumes

### 14.3 — Audit Trail

**Problem**: `auth_store.py` has `record_audit_log()` for API gateway auth events, but there's no audit trail for:
- Who created/deleted an agent
- Who approved a workflow step
- What model was invoked and with what prompt
- Which tool calls an agent executed

**Fix**: Implement comprehensive audit logging at three levels:
1. **Control plane** — All CRD mutations (Kubernetes audit log + operator-emitted CloudEvents)
2. **Data plane** — All invoke calls, tool executions, and LLM requests (agent runtime emitted)
3. **User plane** — All API gateway requests with user identity

Store in PostgreSQL `audit_events` table with 90-day default retention.

### 14.4 — Prompt Injection Defense

**Problem**: The workflow engine injects user-provided text (workflow `input`, step `prompt`, previous step output) directly into prompts sent to agents. There's no sanitization or structural separation between instructions and data.

**Fix**:
1. Use structured message formats instead of string concatenation: instructions as `system` role, user input as `user` role
2. Add optional prompt injection detection (via LLM-based classification or regex patterns for common prompt injection markers)
3. Mark all user-provided content with explicit delimiters (`<user_input>...</user_input>`)
4. For high-security deployments, enable a "prompt firewall" guardrail that rejects suspicious inputs

---

## 15. Re-Architecture Plan: Testing & CI/CD

### 15.1 — Current Test Coverage

Existing test files show incomplete coverage:
- `operator/tests/test_main.py` — operator controller tests
- `operator/tests/test_worker_opencode.py` — OpenCode worker tests
- `operator/tests/test_workflow_utils.py` — workflow DAG validation
- `operator/tests/test_state_store.py` — state persistence
- `agent-runtime/tests/test_agent_logic.py` — agent logic tests
- `api-gateway/tests/test_main.py` — API endpoint tests

**Missing**:
- No integration tests (real K8s cluster, real CRD lifecycle)
- No end-to-end tests (create agent → invoke → check response)
- No chaos tests (kill operator mid-reconciliation, kill agent mid-invoke)
- No performance tests (how many concurrent workflows before degradation?)
- No security tests (CRD injection, RBAC bypass, NetworkPolicy enforcement)

### 15.2 — Testing Strategy

```
Unit Tests (80% of test suite)
  ├─ Pure functions: DAG validation, prompt rendering, thread ID building
  ├─ Builder tests: StatefulSet builder produces correct manifests
  ├─ Policy enforcement: allowed models, guardrails, rate limits
  └─ Tool execution: mock LLM responses, verify tool call chains

Integration Tests (15% of test suite)
  ├─ Operator + K8s: create AIAgent CRD → verify StatefulSet exists (kind cluster)
  ├─ Worker + Runtime: invoke agent → verify response (mock LLM)
  ├─ Gateway + Auth: login → get token → invoke agent → check RBAC
  └─ State Store: write workflow state → read back → verify consistency

End-to-End Tests (5% of test suite)
  ├─ Full workflow: create agent → create workflow → wait completion → verify artifacts
  ├─ HITL flow: trigger approval → approve → verify continuation
  ├─ Multi-agent: agent A delegates to agent B → verify A receives B's output
  └─ Failure recovery: kill worker mid-execution → verify requeue and resume
```

### 15.3 — CI Pipeline

```yaml
# .github/workflows/ci.yml
stages:
  lint:
    - ruff check (Python linting)
    - mypy --strict (type checking — currently missing entirely)
    - helm lint (chart validation)
    - kubeconform (CRD schema validation)
    
  unit-test:
    - pytest operator/tests/ --cov=operator --cov-fail-under=80
    - pytest agent-runtime/tests/ --cov=agent_logic --cov-fail-under=80
    - pytest api-gateway/tests/ --cov=main --cov-fail-under=80
    
  integration-test:
    - kind create cluster
    - helm install kubesynth
    - pytest tests/integration/ --timeout=300
    
  security:
    - trivy image scan (all container images)
    - checkov scan (Helm templates, Dockerfiles)
    - bandit scan (Python security)
    - gitleaks (secret detection)
    
  build:
    - docker build + tag + push (all images)
    - helm package + push (chart to OCI registry)
```

### 15.4 — Type Checking

**Critical gap**: No `mypy` or `pyright` type checking is configured. The codebase uses type hints extensively (a good sign) but they're never verified. This means:
- Type annotations may be incorrect
- Refactoring can silently break type contracts
- IDE autocompletion may suggest wrong types

**Fix**: Add `pyproject.toml` with:
```toml
[tool.mypy]
strict = true
plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]
exclude = ["tests/"]
```

---

## 16. Migration Strategy

> **Status note (March 24, 2026)**: Only items explicitly marked ✅ below have been
> completed. All other items remain TODO. Do not add checkmarks without verifying
> the implementation exists in the codebase.

### Phase 1: Foundation (Weeks 1-3)

**Goal**: Fix ship-blocking issues without changing architecture.

1. ✅ Add Alembic database migrations — `operator/alembic.ini` + `operator/migrations/` exist
2. ✅ Split `operator/main.py` into controller modules — `operator/controllers/`, `builders/`, `services/` exist
3. ☐ Split `agent-runtime/agent_logic.py` into modules — still monolithic (~5,800 lines)
4. ☐ Replace SHA-1 with SHA-256 — 5 `hashlib.sha1()` calls remain
5. ☐ Add `status.conditions[]` to all CRDs — only custom `phase` exists
6. ☐ Add structured error codes to operator and worker — `errors.py` exists but bare exceptions still used
7. ☐ Add graceful shutdown handlers to all components
8. ☐ Add `mypy` strict mode to CI — only flake8 in CI currently
9. ☐ Add Kubernetes Lease-based leader election

### Phase 2: Scalability (Weeks 4-6)

**Goal**: Remove horizontal scaling barriers.

1. ☐ Replace SQLite checkpointing with PostgreSQL — still uses `SqliteSaver`
2. ☐ Make PostgreSQL the primary state store (not a mirror)
3. ☐ Add connection pooling configuration
4. ☐ Add per-tenant concurrency limits for parallel step execution
5. ☐ Add artifact retention policy and garbage collection
6. ☐ Implement idempotency guards (Lease-based locking for workers)
7. ☐ Move OpenCode session registry to Redis

### Phase 3: Standards (Weeks 7-10)

**Goal**: Adopt industry standards for interoperability.

1. ☐ Implement OpenTelemetry distributed tracing — `tracing.py` skeleton exists, not wired end-to-end
2. ☐ Define and publish runtime contract (JSON Schema)
3. ☐ Add proper A2A protocol support (Agent Cards, task lifecycle)
4. ☐ Upgrade MCP sidecars to official MCP SDK
5. ☐ Add CloudEvents for event streaming
6. ☐ Integrate NATS JetStream for event bus
7. ☐ Add API versioning to gateway

### Phase 4: Security & Compliance (Weeks 11-13)

**Goal**: Enterprise security posture.

1. ☐ Add ValidatingWebhookConfiguration for tenant enforcement
2. ☐ Implement comprehensive audit logging
3. ☐ Add seccomp profiles and PSS enforcement
4. ☐ Per-agent LiteLLM API key scoping
5. ☐ Egress NetworkPolicy allow-listing
6. ☐ Prompt injection detection guardrail
7. ☐ Secret rotation via External Secrets Operator

### Phase 5: Polish (Weeks 14-16)

**Goal**: Production readiness signoff.

1. ☐ Split Helm chart into sub-charts
2. ☐ Add Helm `values.schema.json`
3. ☐ Performance benchmarks and published limits
4. ☐ Chaos testing (operator restart, node failure, OOM)
5. ☐ End-to-end test suite
6. ☐ Operational runbook document
7. ☐ CRD conversion webhook for future version migration

---

## 17. Priority Ordering

### Tier 1 — Will get roasted immediately
| # | Issue | Fix Effort | Risk if Ignored |
|---|-------|-----------|-----------------|
| 1 | Main.py 3900-line monolith | 3 days | "This is prototype code" — ✅ DONE (operator split into controllers/, builders/, services/) |
| 2 | agent_logic.py ~5,800-line monolith | 3 days | "Unmaintainable" — still monolithic |
| 3 | No database migrations | 1 day | Data loss on upgrade |
| 4 | SQLite checkpointing | 2 days | Cannot scale past 1 replica |
| 5 | Dual source of truth (CRD + DB) | 2 days | Split-brain state |
| 6 | No distributed tracing | 3 days | "You can't debug this in production" |
| 7 | No CRD status conditions | 1 day | Breaks kubectl, Argo CD, Flux |
| 8 | No idempotency on workflow workers | 1 day | Duplicate executions |
| 9 | No graceful shutdown | 1 day | Data corruption on pod eviction |
| 10 | No type checking (mypy) | 0.5 days | "No CI quality gates" |

### Tier 2 — Will get questioned by enterprise buyers
| # | Issue | Fix Effort |
|---|-------|-----------|
| 11 | No API versioning | 1 day |
| 12 | No rate limiting | 2 days |
| 13 | No multi-tenancy enforcement | 3 days |
| 14 | No A2A standard protocol | 3 days |
| 15 | No MCP standard compliance | 2 days |
| 16 | No audit trail for agent actions | 2 days |
| 17 | No secret rotation | 2 days |
| 18 | No artifact garbage collection | 1 day |

### Tier 3 — Competitive differentiators
| # | Issue | Fix Effort |
|---|-------|-----------|
| 19 | Event-driven architecture (NATS) | 5 days |
| 20 | Helm sub-chart split | 2 days |
| 21 | OCI artifact packaging | 3 days |
| 22 | gVisor/Kata sandbox support | 2 days |
| 23 | CloudEvents event bus | 2 days |
| 24 | CRD conversion webhooks | 3 days |

---

## 18. Appendix: Critic Flashpoints

These are the specific lines of code and patterns that a senior infrastructure engineer, CNCF reviewer, or competing vendor would immediately flag:

### 18.1 — "Why is your operator a single 3,900-line Python file?"

**File**: `operator/main.py`

**Their argument**: "Every serious Kubernetes operator uses controller-runtime (Go) or at minimum has separated controllers per CRD. A single file with 14 handlers, 400+ lines of env var loading, and inline StatefulSet construction is a maintenance nightmare. No code review process should have allowed this."

**Your defense**: "We're refactoring into a controller-per-CRD architecture with dedicated builder classes. The monolith was a pragmatic choice during rapid prototyping but is not the target architecture."

### 18.2 — "SQLite in a StatefulSet? Tell me you don't scale."

**File**: `agent-runtime/agent_logic.py` — `SqliteSaver`

**Their argument**: "LangGraph's SqliteSaver is documented as 'development only'. You're running it in an enterprise product. Pod eviction loses all conversation history. You can't even run 2 replicas."

**Your defense**: "PostgreSQL-backed checkpointing is being deployed. The SQLite backend was a stepping stone."

### 18.3 — "Your artifact storage is JSON files on PVCs — this is not 2016."

**File**: `operator/worker.py` — `write_artifact()`, `load_artifact()`

**Their argument**: "Every workflow engine stores execution results in a database with proper indexing. You're writing JSON files to PVCs, with no retention, no garbage collection, no indexing, and no way to query 'show me all failed runs this week' without mounting every PVC."

**Your defense**: "Artifact metadata is now stored in PostgreSQL. PVC-backed JSON is being phased to the journal/archive role. We chose PVCs initially for simplicity and resilience to database outages."

### 18.4 — "No mypy, no types, no tests — what's your quality bar?"

**File**: No `pyproject.toml` with mypy config, no CI evidence

**Their argument**: "You have 12,000+ lines of Python with type hints that are never checked. Your test suite covers basic happy paths. No integration tests, no chaos tests, no security tests. This ships to enterprise customers?"

**Your defense**: "mypy strict mode and expanded test coverage are in our Phase 1 roadmap. CRD schema validation and integration tests using kind clusters are being added."

### 18.5 — "You deploy NATS but don't use it."

**File**: Helm chart templates include `nats-deployment.yaml`

**Their argument**: "Why are you burning cluster resources on a message bus that nothing publishes to or subscribes from? This is either dead code or abandoned feature work."

**Your defense**: "NATS is being integrated as the event bus for workflow streaming, audit events, and A2A agent communication. The infrastructure was pre-provisioned for the Phase 3 event-driven architecture."

### 18.6 — "Custom A2A protocol instead of Google's standard?"

**File**: `agent-runtime/agent_logic.py` — `execute_a2a_call()`

**Their argument**: "Google published the A2A protocol spec for exactly this use case. You rolled your own incompatible protocol. No one outside your platform can participate in A2A delegation."

**Your defense**: "We're adopting the A2A standard with Agent Cards and standard task lifecycle. Our custom protocol pre-dates the Google spec and is being migrated."

### 18.7 — "Your CRDs break kubectl wait and GitOps health checks."

**File**: CRD templates — no `.status.conditions[]`

**Their argument**: "Standard Kubernetes controllers report health via `status.conditions[]`. Your CRDs use only a custom `phase` field. This means Argo CD can't detect if a deployment is healthy, `kubectl wait --for=condition=Ready` doesn't work, and any standard tooling that relies on conditions is broken."

**Your defense**: "Standard conditions are being added to all CRDs as a backward-compatible addition."

### 18.8 — "Where are your database migrations?"

**File**: `operator/state_store.py` — `Base.metadata.create_all(bind=ENGINE)`

**Their argument**: "create_all() is for test databases. In production, you need versioned migrations. What happens when you add a column? Rename a table? Your existing data?"

**Your defense**: "Alembic migrations are being integrated with the operator deployment as an init container."

---

## Closing Note

The fundamental idea — Kubernetes as the orchestration layer for autonomous AI agents — is compelling and increasingly validated by the market. The CRD model (AIAgent, AgentWorkflow, AgentPolicy, AgentTenant, AgentApproval, AgentEval) is well-designed and covers the domain comprehensively. The multi-runtime approach (LangGraph, OpenCode, Goose, Codex) is a genuine differentiator.

What separates this from a competitive production system is execution discipline: modular code, standard protocols, proper state management, observability, and the test/CI rigor that makes teams trust the system under load.

The issues identified here are fixable — none require a ground-up rewrite. The 16-week phased plan prioritizes the changes that have the highest visibility to critics and the highest impact on reliability. Focus on Phase 1 (modularization + database fixes) first. Everything else follows from having a maintainable, testable codebase.
