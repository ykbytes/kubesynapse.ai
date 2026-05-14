# Road-to-Prod Execution Plan

> **Branch**: `robustness-hardening` | **Baseline**: March 22, 2026 | **Updated**: March 24, 2026  
> **Source of truth**: `road-to-prod-audit.md` (§2–§18)

---

## Current State Assessment

> **Note**: This table reflects the state as of March 24, 2026. Items marked ✅ DONE
> have been completed on the `robustness-hardening` branch.

| Component | File(s) | Status | Key Debt |
|-----------|---------|--------|----------|
| Operator | `operator/` — modularized into `controllers/` (7), `builders/` (3), `services/` (1), `config.py`, `errors.py`, `reconcile.py`, `tracing.py` | ✅ Split done | Dual writes (CRD + DB), no idempotency lock, no SIGTERM handler, `sha1()` calls remain |
| Worker | `operator/worker.py` | — | Dual writes, no idempotency lock, no SIGTERM handler |
| Utils | `operator/utils.py` | — | 3 `sha1()` calls (`build_thread_id`, `build_workflow_run_id`, `build_eval_run_id`) |
| State Store | `operator/state_store.py` | ✅ Alembic added | `alembic.ini` + `migrations/` exist; connection pooling still missing |
| Agent Logic | `agent-runtime/agent_logic.py` | Still monolithic | `SqliteSaver`, 5 mutable globals, 2 `sha1()` calls, hardcoded model costs |
| API Gateway | `api-gateway/main.py` | — | Auth coupled with routing, no API versioning |
| CI | `.github/workflows/ci.yaml` | — | flake8 only (no mypy, no ruff, no security scanning) |
| Helm Chart | `charts/kubesynapse/` | — | Monolithic, no `values.schema.json`, CRDs in templates |
| CRDs | 6 CRD templates | — | No `.status.conditions[]`, custom `phase` only |
| Tests | `operator/tests/` (5), `agent-runtime/tests/` (2), `tests/` (cross-cutting) | — | No integration tests, no coverage thresholds |

---

## Phase 1 — Foundation (12 items)

### 1.1 — Split `operator/main.py` (§2.1) ⏱ P0 — ✅ DONE

**Status**: Completed on `robustness-hardening` branch.

**Goal**: Decompose monolith into controller-per-CRD architecture.

**Actual structure** (as implemented):
```
operator/
  main.py                  # Entry point + Kopf startup
  config.py                # OperatorConfig dataclass, validated env loading
  errors.py                # OperatorError taxonomy, structured error codes
  reconcile.py             # Shared reconciliation helpers
  tracing.py               # OpenTelemetry tracing setup
  utils.py                 # Shared utilities
  worker.py                # Workflow & eval execution in Jobs
  state_store.py           # SQLAlchemy models and DB init
  alembic.ini              # Alembic configuration
  controllers/
    __init__.py
    agent.py               # AIAgent create/update/resume/delete
    workflow.py             # AgentWorkflow handlers
    policy.py              # AgentPolicy handlers
    tenant.py              # AgentTenant handlers
    approval.py            # AgentApproval handlers
    status_projection.py   # CRD → DB status projection
  builders/
    __init__.py
    helpers.py             # Shared builder utilities
    manifests.py           # StatefulSet, Job, PVC, Service manifests
    translator.py          # CRD spec → K8s manifest translation
  services/
    __init__.py
    k8s.py                 # K8s API interaction (ensure_*, patch_custom_status)
  migrations/
    env.py                 # Alembic environment config
    script.py.mako         # Migration template
    versions/
      001_initial.py       # Initial schema migration
  tests/                   # 5 test files
```

**What was planned vs. what was done**: The modularization followed the planned structure closely. Minor naming differences (e.g., `agent.py` instead of `agent_controller.py`, `k8s.py` instead of `k8s_service.py`) but the architectural intent is the same. `reconcile.py` and `tracing.py` were added as bonus modules not in the original plan.

---

### 1.2 — Split `agent-runtime/agent_logic.py` (§3.1) ⏱ P0 — TODO

**Status**: Not started. `agent_logic.py` remains a monolith. Only `memory/` directory has been extracted so far.

**Goal**: Decompose ~5,800-line monolith into focused modules.

**Target structure**:
```
agent-runtime/
  agent_logic.py          # Reduced to: FastAPI app, routes, runtime init (~200 lines)
  core/
    __init__.py
    graph.py              # LangGraph state machine definition, supervisor_node, autonomous loop
    context.py            # RuntimeContext dataclass (replaces RUNTIME global dict)
    models.py             # Pydantic models (InvokeRequest, InvokeResponse, StreamEvent, etc.)
    config.py             # All agent-level env loading (~30 os.getenv calls) into frozen dataclass
  tools/
    __init__.py
    registry.py           # discover_local_tool_inventory, tool schema generation, tool routing
    sandbox.py            # Sandbox tool execution with retry (opensandbox integration)
    mcp_client.py         # MCP server discovery, tool enumeration, invocation
    a2a_client.py         # A2A delegation with circuit breaker, peer resolution
    file_edit.py          # File editing with fuzzy match, edit history, auto-lint
    search.py             # Workspace search, RAG, code search
    shell.py              # Local shell command execution, allowlist enforcement
  streaming/
    __init__.py
    events.py             # StreamEvent types, event construction
    sse.py                # SSE response generation, async iteration
  policies/
    __init__.py
    guardrails.py         # Move from standalone guardrails.py, or import it
    cost.py               # _MODEL_COST_PER_MILLION, _calculate_cost_usd, token budget enforcement
    doom_loop.py          # Action fingerprint hashing, doom loop detection
  workspace/
    __init__.py
    scanner.py            # Workspace profile detection, directory scanning
    skills.py             # Skill file loading, skill runtime config assembly
```

**Execution steps**:
1. Create `core/config.py` — extract all `os.getenv()` calls into `AgentConfig` frozen dataclass
2. Create `core/context.py` — define `RuntimeContext` dataclass to replace mutable `RUNTIME` dict
3. Create `core/models.py` — extract all Pydantic request/response models
4. Create `policies/cost.py` — extract `_MODEL_COST_PER_MILLION` and `_calculate_cost_usd`
5. Create `policies/doom_loop.py` — extract doom loop detection logic
6. Create `tools/registry.py` — extract tool discovery and schema generation
7. Create `tools/` modules — extract each tool category
8. Create `streaming/` modules — extract SSE/event logic
9. Create `workspace/` modules — extract workspace scanning and skills
10. Create `core/graph.py` — extract LangGraph graph definition (the hardest move — has most cross-references)
11. Reduce `agent_logic.py` to FastAPI app + routes + `initialize_runtime()`
12. Run `python -m py_compile` on every new file
13. Run `python -m pytest agent-runtime/tests/ -v`

---

### 1.3 — Add Alembic Database Migrations (§6.1) ⏱ P0 — ✅ DONE

**Status**: Completed on `robustness-hardening` branch. Files exist: `operator/alembic.ini`, `operator/migrations/env.py`, `operator/migrations/script.py.mako`, `operator/migrations/versions/001_initial.py`.

**Original plan** (retained for reference):

**Steps**:
1. Create `operator/alembic/` directory with `env.py`, `alembic.ini`
2. Generate initial migration from existing models (`WorkflowRun`, `ChatSession`, `ChatMessage`)
3. Replace `init_database()` to run `alembic upgrade head` instead of `create_all()`
4. Add migration init container to `charts/kubesynapse/templates/operator-deployment.yaml`
5. Add schema version check on operator startup (refuse to start if migration is behind)
6. Test: create DB, run migration, verify tables match current schema

---

### 1.4 — Replace SQLite with PostgreSQL Checkpointing (§3.2) ⏱ P0

**Current**:
- `agent_logic.py` line 29: `from langgraph.checkpoint.sqlite import SqliteSaver`
- `agent_logic.py` line 5699-5704: `sqlite3.connect()` → `SqliteSaver(connection)` → `memory.setup()`

**Steps**:
1. Add `langgraph-checkpoint-postgres` to `agent-runtime/requirements.txt`
2. Replace `SqliteSaver` import with `PostgresSaver` from `langgraph.checkpoint.postgres`
3. Replace `sqlite3.connect()` initialization with `PostgresSaver.from_conn_string(CHECKPOINT_DATABASE_URL)`
4. Add `CHECKPOINT_DATABASE_URL` env var to agent runtime StatefulSet (from operator config)
5. Add `agent_checkpoints` schema to PostgreSQL init script
6. Update Helm chart: add `CHECKPOINT_DATABASE_URL` env injection
7. Test: invoke agent → verify checkpoint in PostgreSQL → restart pod → verify history persists

---

### 1.5 — Fix Dual Source of Truth (§2.5) ⏱ P0

**Current**: `worker.py` calls both `patch_workflow_status()` (CRD) AND `safe_record_workflow_state()` (PostgreSQL) in sequence.

**Steps**:
1. Create `operator/services/status_projector.py` — a Kopf field watcher that watches `.status` changes on workflow CRDs and writes to PostgreSQL
2. Remove `safe_record_workflow_state()` calls from `worker.py`
3. Worker now only patches CRD status (single source of truth for active state)
4. The projector asynchronously syncs CRD status → PostgreSQL (for gateway/UI queries)
5. Handle 409 conflicts in worker status patches with retry
6. Test: run workflow → verify CRD status updated → verify PostgreSQL eventually consistent

---

### 1.6 — Add Distributed Tracing Skeleton (§7.1, §8.3) ⏱ P0

**Steps**:
1. Create `operator/tracing.py` — `init_tracing()` function, tracer factory
2. Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp` to all `requirements.txt`
3. Add `opentelemetry-instrumentation-fastapi` to gateway and agent-runtime
4. Wrap each Kopf handler in `tracer.start_as_current_span("reconcile_{kind}")` 
5. Propagate `traceparent` header in worker HTTP calls to agent runtimes
6. Propagate `traceparent` in gateway HTTP calls to operator/runtimes
7. Configuration: `OTEL_EXPORTER_OTLP_ENDPOINT` env var (already partially exists)
8. Test: verify spans are created (mock exporter), verify traceparent propagation

---

### 1.7 — Add `.status.conditions[]` to All CRDs (§2.10) ⏱ P0

**Current**: All 6 CRDs use custom `phase` field only. No `conditions[]` array.

**Steps per CRD** (aiagent, agentworkflow, agentpolicy, agenttenant, agentapproval):
1. Add `conditions` array to `.status` in CRD `openAPIV3Schema`:
   ```yaml
   conditions:
     type: array
     items:
       type: object
       properties:
         type: { type: string }
         status: { type: string, enum: ["True", "False", "Unknown"] }
         lastTransitionTime: { type: string, format: date-time }
         reason: { type: string }
         message: { type: string }
   ```
2. Condition types per CRD:
   - **AIAgent**: `Ready`, `Progressing`, `RuntimeAvailable`, `Degraded`
   - **AgentWorkflow**: `Ready`, `Progressing`, `StepFailed`, `ApprovalPending`
   - **AgentPolicy**: `Ready`
   - **AgentTenant**: `Ready`, `NamespaceProvisioned`
   - **AgentApproval**: `Decided`, `Expired`
3. Add helper function `set_condition(status_dict, condition_type, value, reason, message)` in `operator/services/k8s_service.py`
4. Update all Kopf handlers to set conditions alongside phase
5. Retain `phase` for backward compat (derive from conditions)
6. Test: `kubectl get aiagent -o jsonpath='{.status.conditions}'` returns valid conditions

---

### 1.8 — Add Idempotency Guards (§2.6) ⏱ P0

**Steps**:
1. Add Kubernetes Lease creation per workflow run: `{workflow_name}-gen-{generation}` 
2. Worker acquires Lease before starting, releases on completion
3. Add `resourceVersion` to CRD status patches for optimistic concurrency
4. Retry on 409 (Conflict) with backoff
5. Add `runId` uniqueness check: if DB has a `running` record with different `runId` for same workflow+generation, refuse to start
6. Test: simulate double-enqueue → verify only one worker runs

---

### 1.9 — Add Graceful Shutdown (§7.2) ⏱ P0

**Steps**:
1. **Operator**: Add `@kopf.on.cleanup()` handler — stop accepting new reconciliations, wait for in-flight
2. **Agent Runtime**: Add SIGTERM signal handler → set shutdown flag → finish current LLM call → save checkpoint → exit
3. **Worker**: Add SIGTERM handler → save current progress to artifact → patch CRD status to "interrupted" → exit non-zero (so Job retries)
4. Test: send SIGTERM during processing → verify clean state persisted

---

### 1.10 — Add `mypy --strict` to CI (§15.4) ⏱ P1

**Steps**:
1. Create `pyproject.toml` at repo root:
   ```toml
   [tool.mypy]
   strict = true
   plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]
   exclude = ["tests/", "web-ui/", "cli/"]
   
   [tool.ruff]
   line-length = 120
   target-version = "py311"
   ```
2. Add `mypy`, `ruff` to CI lint stage
3. Add `types-pyyaml`, `types-croniter`, `types-httpx` stubs
4. Fix type errors incrementally (expected: many — triage by severity)
5. Set initial `--warn-return-any` and `--disallow-untyped-defs` as stepping stones before full `--strict`

---

### 1.11 — Replace SHA-1 with SHA-256 (§2.8) ⏱ P2

**Exact locations** (5 total):
1. `operator/main.py` line 726: `hashlib.sha1()` in `hashed_resource_name()` → `hashlib.sha256()`
2. `operator/utils.py` line 75: `hashlib.sha1()` in `build_thread_id()` → `hashlib.sha256()`
3. `operator/utils.py` line 91: `hashlib.sha1()` in `build_workflow_run_id()` → `hashlib.sha256()`
4. `operator/utils.py` line 99: `hashlib.sha1()` in `build_eval_run_id()` → `hashlib.sha256()`
5. `agent-runtime/agent_logic.py` line 409: `hashlib.sha1()` in `build_thread_id()` → `hashlib.sha256()`

**Note**: All use truncated hex digests (`:10` or `:8`), so SHA-256 is a drop-in replacement. Same output format, different hash.

**Steps**:
1. Replace all 5 calls
2. Run full test suite — verify no tests depend on specific hash values
3. Add grep CI check: `grep -rn "sha1" operator/ agent-runtime/ && exit 1` to prevent regression

---

### 1.12 — Add Structured Error Codes (§2.9) ⏱ P1

**Steps**:
1. Define in `operator/errors.py`:
   ```python
   class OperatorError(Exception):
       code: str       # "AGENT_RUNTIME_TIMEOUT", "WORKFLOW_CYCLE_DETECTED", etc.
       severity: str   # "fatal", "transient", "warning"
       message: str
       metadata: dict  # step_name, agent_ref, etc.
   ```
2. Subclasses: `AgentProvisionError`, `WorkflowExecutionError`, `EvalExecutionError`, `PolicyViolationError`
3. Replace bare `RuntimeError`/`ValueError` raises in controllers with typed errors
4. Emit error codes in CRD `.status.conditions[].reason` field
5. Test: trigger known failure → verify error code in CRD status

---

## Phase 2 — Scalability (5 items)

### 2.1 — PostgreSQL as Primary State Store (§2.5, §6) — P0
- Make `state_store.py` the authoritative store for historical queries
- CRD status remains authoritative for active/current state
- Gateway reads from PostgreSQL, not from CRD status
- Add `workflow_runs`, `eval_runs` indices for time-range queries

### 2.2 — Connection Pooling Configuration (§6.2) — P1
- Add `pool_size=10`, `max_overflow=20`, `pool_timeout=30`, `pool_recycle=3600` to `create_engine()`
- Make configurable via env vars: `DATABASE_POOL_SIZE`, etc.
- Add connection pool metrics (active, idle, overflow)

### 2.3 — Per-Tenant Concurrency Limits (§2.7) — P1
- Add `MAX_PARALLEL_STEPS` (default: 4) to `AgentTenant` CRD spec
- Worker reads tenant config before step execution
- Use semaphore in `ThreadPoolExecutor` to enforce limit
- Add `concurrent.futures.wait(return_when=FIRST_EXCEPTION)` for fail-fast

### 2.4 — Artifact Retention Policy (§2.4) — P1
- Add `ARTIFACT_RETENTION_DAYS` (default: 30) config
- Add CronJob or Kopf timer that deletes old PVCs and DB records
- Add `MAX_ARTIFACTS_PER_WORKFLOW` config
- Index artifacts by creation time for efficient GC queries

### 2.5 — OpenCode Session Registry to Redis (§3.5) — P1
- Replace `threading.Lock` + file-based JSON registry 
- Use Redis hash: `opencode:sessions:{agent_name}` → session mapping
- Add process health check background task (restart subprocess on death)
- Liveness probe checks both FastAPI + subprocess

---

## Phase 3 — Standards (7 items)

### 3.1 — OpenTelemetry Full Implementation (§8.3) — P1
- Add semantic conventions: `agent.invoke`, `workflow.step`, `tool.call`, `llm.completion`
- Add Prometheus metrics (counters, histograms per §13.2)
- Add LiteLLM callback for per-LLM-call spans
- Export to OTLP-compatible backend

### 3.2 — Versioned Runtime Contract (§3.6) — P1
- Define `AgentRuntimeContract` v1 as JSON Schema
- Each runtime exposes `/info` endpoint with contract version
- Operator checks compatibility before first invoke
- Publish as pip-installable `agent-runtime-contract` package

### 3.3 — A2A Protocol Standard (§8.1) — P1
- Implement Agent Cards (`/.well-known/agent.json`) on each runtime
- Replace custom `execute_a2a_call()` with A2A standard client
- Support push/pull notification modes
- Add A2A task lifecycle (created, running, completed, failed)

### 3.4 — MCP SDK Upgrade (§8.2) — P1
- Replace custom `/tools/{tool_name}` with official MCP server SDK
- Use official MCP client SDK in agent runtimes
- Support MCP resource protocol (not just tools)
- Transport: stdio for local, SSE for remote

### 3.5 — CloudEvents (§8.4) — P2
- Wrap journal events in CloudEvents envelope
- Event types: `ai.agent.invoked`, `ai.workflow.step.completed`, etc.
- Publish to NATS JetStream

### 3.6 — NATS JetStream Integration (§12.2) — P2
- Create streams: `AGENT_EVENTS`, `WORKFLOW_EVENTS`, `EVAL_EVENTS`, `AUDIT_EVENTS`
- Create consumers: `status-projector`, `crd-patcher`, `ui-sse-bridge`
- Replace file-based journal with NATS publishing

### 3.7 — API Versioning (§4.2) — P1
- Add `app_v1 = APIRouter(prefix="/api/v1")`, `app_v2 = APIRouter(prefix="/api/v2")`
- Add `Sunset` and `Deprecation` headers for v1 deprecation
- Publish OpenAPI schemas per version

---

## Phase 4 — Security & Compliance (7 items)

### 4.1 — ValidatingWebhookConfiguration (§7.4) — P1
### 4.2 — Comprehensive Audit Logging (§14.3) — P1
### 4.3 — Seccomp + Pod Security Standards (§14.1) — P1
### 4.4 — Per-Agent LiteLLM API Key Scoping (§7.3) — P1
### 4.5 — Egress NetworkPolicy Allow-listing (§14.1) — P2
### 4.6 — Prompt Injection Detection (§14.4) — P2
### 4.7 — Secret Rotation via ESO (§14.2) — P2

---

## Phase 5 — Polish (6 items)

### 5.1 — Helm Sub-Charts (§5.1) — P1
### 5.2 — values.schema.json (§5.4) — P2
### 5.3 — Performance Benchmarks (§15) — P2
### 5.4 — Chaos Testing (§15) — P2
### 5.5 — End-to-End Test Suite (§15.2) — P1
### 5.6 — CRD Conversion Webhooks (§5.2) — P2

---

## Recommended Execution Order

The order below maximizes unblocking and minimizes risk:

| Step | Item | Why This Order |
|------|------|----------------|
| **1** | §1.11 — SHA-1 → SHA-256 | Smallest change, builds confidence, instant CVE fix |
| **2** | §1.10 — Add pyproject.toml + mypy | Establishes quality gate before big refactors |
| **3** | §1.12 — Structured error codes | Creates `errors.py` needed by all controllers |
| **4** | §1.1a — `operator/config.py` | Extract env vars; all controllers depend on this |
| **5** | §1.1b — `operator/builders/` | Extract pure functions first (testable, no side effects) |
| **6** | §1.1c — `operator/services/` | Extract K8s interaction layer |
| **7** | §1.1d — `operator/controllers/` | Wire handlers to builders + services |
| **8** | §1.1e — Reduce `operator/main.py` | Final: entry point only |
| **9** | §1.7 — CRD status conditions | Needed before any status projection work |
| **10** | §1.9 — Graceful shutdown | Small, independent, high impact |
| **11** | §1.3 — Alembic migrations | Needed before PostgreSQL checkpoint migration |
| **12** | §1.4 — PostgreSQL checkpointing | Unblocks horizontal scaling |
| **13** | §1.5 — Fix dual source of truth | Depends on conditions + Alembic being done |
| **14** | §1.8 — Idempotency guards | Depends on dual-source fix |
| **15** | §1.6 — Distributed tracing | Cross-cutting, add after structure stabilizes |
| **16** | §1.2 — Split agent_logic.py | Largest item, do after operator is stable |
| **17+** | Phase 2–5 | Sequential by phase |

---

## Verification Protocol

After **every** change:
1. `python -m py_compile <changed_files>` — syntax check
2. `python -m pytest operator/tests/ agent-runtime/tests/ api-gateway/tests/ -v` — existing tests
3. `git diff --stat` — review scope of change
4. Confirm: no new `sha1()`, no new unvalidated `os.getenv()`, no new mutable globals
