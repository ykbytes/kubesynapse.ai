# KubeSynth Runtime Platform — Master Roadmap

> **Updated:** 2026-05-07  
> **Status:** Active — Run Intelligence shipped, consistency hardening in progress  
> **Owner:** KubeSynth Scrum Master

---

## Vision

Build the most **reliable, observable, and enterprise-ready** AI agent runtime platform for Kubernetes. Every runtime must be:
- **Interchangeable** — any runtime implements the same API contract
- **Observable** — full trace, metric, and log visibility
- **Secure** — zero hardcoded secrets, RBAC, audit logging
- **Reliable** — graceful degradation, circuit breakers, retry logic
- **Developer-friendly** — OpenAPI spec, SDK, examples, docs

---

## Current State

| Component | Status | Image | Notes |
|-----------|--------|-------|-------|
| opencode-runtime | ✅ Production-ready | `v2.0.0` (480MB) | All 16 endpoints working, opencode-go provider functional |
| pi-runtime | ✅ Production-ready | `v1.x` | All Core + Session + Artifacts + Streaming tiers implemented, SSE taxonomy normalized |
| vibe-runtime | ✅ Production-ready | `v1.x` | All 4 API tiers implemented, /cancel and /abort functional |
| API contract | ✅ Defined | `runtime-api-spec.yaml` + `.md` | OpenAPI 3.0 spec with Core/Session/Artifacts/Streaming tiers |
| Run Intelligence Layer | ⚠️ Shipped with follow-up backlog | — | Core trace store, runtime emission, system agents, signal watch, and analytics APIs landed; follow-up fixes are planned for connector-backed status, signal watch hardening, SDK contract parity, and `llm.call` runtime parity |

---

## Sprint Backlog

### Phase 1: API Contract Enforcement (Stories 1-4)

#### Story 1: Runtime API Contract Validation
- **Goal:** Every runtime passes a conformance test suite
- **DoD:**
  1. `conftest.py` with shared fixtures for all runtimes
  2. Test suite validates all Core tier endpoints
  3. Test suite validates SSE event taxonomy
  4. Test suite validates error response schema
  5. CI runs conformance tests on every runtime build
  6. Test coverage ≥ 90% for runtime API layer
- **Assignee:** kubesynth-bug-hunter
- **Estimated:** 4h

#### Story 2: pi-runtime API Gap Closure ✅ COMPLETE
- **Goal:** pi-runtime implements all Core + Session tier endpoints
- **DoD:**
  1. ✅ `GET /info` returns contract version and runtime metadata
  2. ✅ `GET /capabilities` returns supported tiers and features
  3. ✅ `POST /cancel` is functional (sends abort to pi subprocess)
  4. ✅ `GET /todo`, `GET /question`, `/question/{id}/reply`, `/question/{id}/reject` implemented
  5. ✅ `GET /diff`, `GET /context-budget` implemented
  6. ✅ SSE events normalized to canonical taxonomy (`response.started`, `response.delta`, `response.tool_call`, `response.tool_result`, `question.asked`, `response.completed`, `response.error`)
  7. ✅ `/events` SSE endpoint added for event subscription
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 6h
- **Actual:** 2h

#### Story 3: vibe-runtime API Gap Closure
- **Goal:** vibe-runtime implements all Core + Session + Artifacts tier endpoints
- **DoD:**
  1. `/health` and `/ready` return rich responses (not bare `{"status": "ok"}`)
  2. `GET /info`, `GET /capabilities` implemented
  3. `/cancel` and `/abort` are functional (not no-op stubs)
  4. `GET /artifacts/list`, `/artifacts/download`, `/artifacts/zip` implemented
  5. Session endpoints implemented (`/todo`, `/question/*`, `/diff`, `/context-budget`)
  6. SSE events normalized to canonical taxonomy
  7. All endpoints return proper error responses
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 8h

#### Story 4: OpenAPI Auto-Generation ✅ COMPLETE
- **Goal:** Every runtime serves its OpenAPI spec at `/openapi.json`
- **DoD:**
  1. ✅ `runtime-api-spec.md` converted to YAML spec file
  2. ✅ Each runtime serves `/openapi.json` with its actual endpoints
  3. ✅ Swagger UI available at `/docs` for each runtime (pi-runtime via CDN, FastAPI auto)
  4. ✅ Spec validation in CI (spec matches actual routes)
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 3h
- **Actual:** 1h

### Phase 2: Run Intelligence Layer (Stories 5-10)

#### Story 5: Extend Trace Store With Semantic Event Index ✅ COMPLETE
- **Goal:** Add `runtime_run_events` table to `trace_store.py` for queryable semantic events
- **DoD:**
  1. ✅ `runtime_run_events` table with indexed columns (event_id, execution_id, session_id, event_type, runtime_kind, created_at)
  2. ✅ JSONB payload column for flexible event data
  3. ✅ `init_trace_database()` creates table on startup
  4. ✅ Idempotent upsert on `event_id`
  5. ✅ Retention policy configurable via Helm (default 30 days)
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 3h
- **Actual:** 2h

#### Story 6: Runtime Event Emission ✅ COMPLETE
- **Goal:** All runtimes and workers emit structured events to `/api/v1/traces/runtime-events`
- **DoD:**
  1. ✅ Shared event envelope with `event_id`, `execution_id`, `session_id`, `seq`, `event_type`, `payload`, `duration_ms`, `tokens`, `cost_usd`
  2. ✅ opencode-runtime emits: `run.started`, `tool.started`, `tool.completed`, `run.completed`, `run.failed`
  3. ✅ pi-runtime emits same events mapped from Pi RPC protocol
  4. ✅ vibe-runtime emits same events mapped from Vibe output
  5. ✅ Worker emits workflow step events, approval events, retry events
  6. ✅ A2A router emits `agent.call.started`, `agent.call.completed`, `agent.call.failed`
  7. ✅ Payloads sanitized (no secrets, prompts truncated, hashes stored)
  8. ✅ Bounded async queue with shutdown flush
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 6h
- **Actual:** 4h

#### Story 7: Run Timeline And Replay APIs ✅ COMPLETE
- **Goal:** Queryable timeline and replay APIs under `/api/v1/traces`
- **DoD:**
  1. ✅ `POST /api/v1/traces/runtime-events` — batch ingestion (max 500)
  2. ✅ `GET /api/v1/traces/{execution_id}/timeline` — ordered semantic timeline
  3. ✅ `GET /api/v1/traces/{execution_id}/runtime-summary` — aggregate stats
  4. ✅ `GET /api/v1/traces/runtime-events` — cross-run filtering + pagination
  5. ✅ All endpoints respect namespace auth middleware
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 4h
- **Actual:** 2h

#### Story 8: Helm-Defined System Agents ✅ COMPLETE
- **Goal:** Predefine system AIAgent CRs via Helm chart
- **DoD:**
  1. ✅ `ks-run-inspector` — diagnoses failed runs (invoked on failure or user request)
  2. ✅ `ks-signal-summarizer` — explains detected anomalies (invoked by signal watch)
  3. ✅ `ks-spend-reviewer` — explains cost/token spikes (invoked on threshold or user request)
  4. ✅ System agents configurable via `systemAgents` in values.yaml
  5. ✅ Default model: `gpt-4` (configurable)
  6. ✅ CRDs installed before system agent CRs (templates/system-agents.yaml)
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 4h
- **Actual:** 2h

#### Story 9: Deterministic Signal Watch ✅ COMPLETE
- **Goal:** SQL-based anomaly detection before LLM explanation
- **DoD:**
  1. ✅ Operator controller runs periodic SQL checks (configurable interval, default 60s)
  2. ✅ Detects: high failure rate, error spikes, cost outliers, token spikes, stuck runs
  3. ✅ Creates `ObservationReport` CRD when rule fires
  4. ✅ Configurable thresholds via Helm values / env vars
  5. ✅ Severity classification (low, medium, high, critical)
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 5h
- **Actual:** 3h

#### Story 10: Agent Interaction Graph And Spend Lens ✅ COMPLETE
- **Goal:** Analytics APIs for agent topology and cost visibility
- **DoD:**
  1. ✅ `GET /api/v1/observability/agent-graph` — agent-to-agent dependency graph from A2A events
  2. ✅ `GET /api/v1/observability/spend` — token/cost aggregation by runtime, model, agent, namespace
  3. ✅ Graph includes: call_count, error_count, avg_latency_ms, last_seen
  4. ✅ Spend includes: total_tokens, estimated_cost_usd, runs
  5. ✅ Namespace-scoped filtering
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 3h
- **Actual:** 1.5h

### Phase 2.5: Observability Consistency Hardening (Stories 10.1-10.5)

Implementation details: `docs/observability-remediation-plan.md`

#### Story 10.1: Connector-Backed ObservationTarget Status
- **Goal:** Remove synthetic target health and report generation from the live observability path.
- **DoD:**
  1. `observation_controller.py` splits demo reconciliation from production reconciliation
  2. Production path reads connector or collector status instead of incrementing synthetic counters
  3. `phase`, `connectorHealth`, `lastScrapeTime`, and `metricsCollected` derive from real scrape outcomes
  4. `ObservationReport` creation is based on collector findings or deterministic rule outputs, not demo text
  5. Demo mode remains opt-in and clearly isolated for sample environments only
  6. UI and API responses continue to work without schema regressions
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 6h

#### Story 10.2: Signal Watch Query And Scheduling Hardening
- **Goal:** Make anomaly detection correct, singleton, and resilient to partial failures.
- **DoD:**
  1. Raw SQL helper uses `sqlalchemy.text` instead of `kopf.text`
  2. Workflow spend queries use `workflow_executions.estimated_cost_usd`
  3. Signal watch runs once per leader cycle, not once per labeled `AIAgent`
  4. Each detector runs in its own failure boundary so one broken query does not suppress later checks
  5. `ObservationReport` creation is idempotent or deduplicated per anomaly window
  6. Helm config still controls interval and thresholds without behavior drift
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 5h

#### Story 10.3: Trace SDK Contract Alignment
- **Goal:** Bring Python and TypeScript SDK trace methods back in sync with the gateway.
- **DoD:**
  1. SDKs call `/api/v1/traces/executions` and `/api/v1/traces/executions/{execution_id}`
  2. SDK return types match `ExecutionListResponse` and `ExecutionDetailResponse`
  3. Deprecated `list_traces` and `get_trace` wrappers remain available or server aliases exist during transition
  4. API reference and examples reflect the live contract
  5. Contract tests fail if route or payload shape drifts again
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 4h

#### Story 10.4: Runtime `llm.call` Event Parity
- **Goal:** Emit the same semantic LLM event coverage from direct runtimes that workflow workers already record.
- **DoD:**
  1. OpenCode runtime emits `llm.call` from `/invoke` and `/invoke/stream` when model metadata is available
  2. Pi runtime emits `llm.call` from bridge result and stream paths
  3. Vibe runtime emits `llm.call` from both invoke paths
  4. Event payloads normalize provider, model, token, cost, duration, and prompt/response preview fields
  5. Spend and runtime-summary analytics include direct runtime runs with no worker involvement
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 6h

#### Story 10.5: Observability Contract And Smoke Coverage
- **Goal:** Lock the observability surfaces with tests so these drifts do not recur.
- **DoD:**
  1. Unit tests cover live vs demo observation reconciliation
  2. Signal watch tests cover query schema alignment, per-detector isolation, and duplicate-safe report creation
  3. SDK contract tests validate routes and response envelopes against the gateway
  4. Runtime tests assert `llm.call` emission alongside run and tool events
  5. Smoke script validates timeline, runtime-summary, spend, and signal-watch flows after deploy
- **Assignee:** kubesynth-bug-hunter
- **Estimated:** 5h

### Phase 3: Reliability & Observability (Stories 11-14)

#### Story 11: Distributed Tracing
- **Goal:** Every request traceable end-to-end
- **DoD:**
  1. `X-Trace-Id` header propagated across all runtimes
  2. OpenTelemetry spans for /invoke, /invoke/stream, /cancel
  3. Trace context in all log lines
  4. Jaeger/Zipkin integration
  5. Trace viewer in web UI
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 5h

#### Story 12: Rate Limiting & Quotas
- **Goal:** Prevent abuse and ensure fair usage
- **DoD:**
  1. Per-thread rate limiting (configurable requests/minute)
  2. Per-agent token budget enforcement
  3. Global concurrent session limit
  4. Rate limit headers in responses (`X-RateLimit-*`)
  5. 429 responses with `Retry-After` header
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 4h

#### Story 13: Circuit Breaker & Retry Logic
- **Goal:** Graceful degradation when LLM providers fail
- **DoD:**
  1. Circuit breaker for LLM API calls (open/half-open/closed states)
  2. Exponential backoff with jitter for retries
  3. Fallback model on primary failure
  4. Health check for LLM provider connectivity
  5. Metrics: circuit state, retry count, fallback usage
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 4h

#### Story 14: Audit Logging
- **Goal:** Every action auditable for compliance
- **DoD:**
  1. Structured JSON audit log for all /invoke, /cancel, /question actions
  2. Audit log includes: who, what, when, result, trace_id
  3. Audit log export to external sink (S3, Elasticsearch)
  4. PII redaction in audit logs
  5. Audit log retention policy (configurable)
- **Assignee:** kubesynth-security-guardian
- **Estimated:** 4h

### Phase 4: Security & Compliance (Stories 15-18)

#### Story 15: Authentication Hardening
- **Goal:** Zero-trust runtime access
- **DoD:**
  1. mTLS between operator and runtimes
  2. JWT-based auth for external API access
  3. API key rotation without downtime
  4. IP allowlisting for runtime endpoints
  5. Audit log for all auth events
- **Assignee:** kubesynth-security-guardian
- **Estimated:** 5h

#### Story 16: Secret Management
- **Goal:** Zero hardcoded secrets anywhere
- **DoD:**
  1. All API keys from Kubernetes secrets
  2. Secret rotation via Kubernetes
  3. No secrets in logs, env vars, or config files
  4. Secret scanning in CI (gitleaks, trivy)
  5. Vault integration option
- **Assignee:** kubesynth-security-guardian
- **Estimated:** 3h

#### Story 17: RBAC & Authorization
- **Goal:** Fine-grained access control
- **DoD:**
  1. Role-based access to runtime endpoints
  2. Namespace-scoped permissions
  3. Agent-level permissions (who can invoke which agent)
  4. Audit log for authorization decisions
  5. Default-deny policy
- **Assignee:** kubesynth-security-guardian
- **Estimated:** 4h

#### Story 18: Supply Chain Security
- **Goal:** Trusted runtime images
- **DoD:**
  1. All images signed with cosign
  2. SBOM generated for all images
  3. Image scanning in CI (trivy, grype)
  4. Reproducible builds
  5. Dependency update automation (dependabot)
- **Assignee:** kubesynth-security-guardian
- **Estimated:** 3h

### Phase 5: Developer Experience (Stories 19-22)

#### Story 19: Runtime SDK
- **Goal:** Easy integration for developers
- **DoD:**
  1. Python SDK (`pip install kubesynth-runtime-sdk`)
  2. TypeScript SDK (`npm install @kubesynth/runtime-sdk`)
  3. Auto-generated from OpenAPI spec
  4. Examples for all endpoints
  5. SDK test suite
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 5h

#### Story 20: Runtime Template
- **Goal:** Scaffold new runtimes in 5 minutes
- **DoD:**
  1. `kubesynth init runtime` CLI command
  2. Template with all Core tier endpoints pre-implemented
  3. Dockerfile with multi-stage build
  4. Helm chart for deployment
  5. README with setup instructions
- **Assignee:** kubesynth-backend-refactorer
- **Estimated:** 4h

#### Story 21: Documentation Portal
- **Goal:** Docs so good users never need support
- **DoD:**
  1. API reference (auto-generated from OpenAPI)
  2. Getting started guide (5-minute tutorial)
  3. Runtime development guide
  4. Troubleshooting guide
  5. Architecture diagrams
  6. Video tutorials
- **Assignee:** kubesynth-docs-storyteller
- **Estimated:** 6h

#### Story 22: Demo & Examples
- **Goal:** Show, don't tell
- **DoD:**
  1. Interactive demo environment
  2. Example workflows (code review, bug fix, doc generation)
  3. Example integrations (GitHub, Slack, Jira)
  4. Performance benchmarks
  5. Comparison with alternatives
- **Assignee:** kubesynth-landing-magician
- **Estimated:** 5h

### Phase 6: Production Hardening (Stories 23-26)

#### Story 23: Performance Benchmarking
- **Goal:** Quantified performance guarantees
- **DoD:**
  1. Load testing suite (k6 or Locust)
  2. Benchmark: requests/sec, latency, token throughput
  3. Scale test: 1000 concurrent sessions
  4. Memory/CPU profiling under load
  5. Performance regression tests in CI
- **Assignee:** kubesynth-bug-hunter
- **Estimated:** 5h

#### Story 24: Chaos Engineering
- **Goal:** Prove resilience under failure
- **DoD:**
  1. Chaos tests: LLM provider failure, network partition, pod restart
  2. Graceful degradation verified
  3. Data integrity after failures
  4. Recovery time objectives met
  5. Chaos test automation in CI
- **Assignee:** kubesynth-bug-hunter
- **Estimated:** 4h

#### Story 25: Multi-Cluster Support
- **Goal:** Run across multiple Kubernetes clusters
- **DoD:**
  1. Cross-cluster runtime discovery
  2. Workload distribution across clusters
  3. Cluster failover
  4. Multi-cluster observability
  5. Documentation for multi-cluster setup
- **Assignee:** kubesynth-prod-engineer
- **Estimated:** 6h

#### Story 26: Community & Governance
- **Goal:** Sustainable open-source project
- **DoD:**
  1. `GOVERNANCE.md`
  2. Issue templates (bug, feature, security)
  3. PR template with checklist
  4. DCO (Developer Certificate of Origin)
  5. Security disclosure policy
  6. CNCF Sandbox application
- **Assignee:** kubesynth-docs-storyteller
- **Estimated:** 4h

---

## Agent Definitions

### kubesynth-scrum-master (Me)
**Role:** Autonomous orchestrator for the KubeSynth project  
**Mission:** Manage sprint execution, delegate to specialist agents, verify completion, ensure production-ready deliverables  
**Tools:** task, bash, edit, write, read, glob, grep  
**Working Directory:** `C:\Users\ahmed\OneDrive\Desktop\repos\kubesynth\kubemininions`  
**Model:** qwen3.6-plus (same as all subagents)

### kubesynth-bug-hunter
**Role:** Bug Hunter & QA Specialist  
**Mission:** Debug issues, trace data flows, add regression tests, improve test coverage, ensure code quality  
**Specialties:** pytest, debugging, performance profiling, chaos engineering  
**Model:** qwen3.6-plus

### kubesynth-security-guardian
**Role:** Security Auditor & Hardening Specialist  
**Mission:** Review code for vulnerabilities, fix security issues, enforce auth/secret management, audit compliance  
**Specialties:** OWASP Top 10, CIS benchmarks, mTLS, JWT, RBAC, secret scanning  
**Model:** qwen3.6-plus

### kubesynth-prod-engineer
**Role:** Production Engineer & SRE  
**Mission:** Harden Helm charts, add probes/PDBs, implement circuit breakers, optimize resources, ensure reliability  
**Specialties:** Kubernetes SRE, observability, performance tuning, chaos engineering  
**Model:** qwen3.6-plus

### kubesynth-ui-artist
**Role:** UI/UX Designer  
**Mission:** Create polished React components, ensure accessibility, implement animations, maintain design system  
**Specialties:** React 18, Tailwind CSS v4, Radix UI, Framer Motion, WCAG 2.1 AA  
**Model:** qwen3.6-plus

### kubesynth-backend-refactorer
**Role:** Backend Architect  
**Mission:** Refactor router logic, improve code architecture, implement API contracts, ensure type safety  
**Specialties:** FastAPI, SQLAlchemy, OpenAPI, Python type annotations, code modularization  
**Model:** qwen3.6-plus

### kubesynth-docs-storyteller
**Role:** Documentation Specialist  
**Mission:** Write comprehensive docs, guides, architecture docs, runbooks, GitHub templates  
**Specialties:** Technical writing, markdown, Mermaid diagrams, API documentation  
**Model:** qwen3.6-plus

### kubesynth-landing-magician
**Role:** Landing Page & Marketing Specialist  
**Mission:** Design conversion-optimized pages, create demos, build brand identity  
**Specialties:** Modern SaaS design, scroll animations, brand identity, conversion optimization  
**Model:** qwen3.6-plus

---

## Metrics Dashboard

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Runtime API conformance | 100% | 100% (3/3 runtimes) | ✅ |
| Run Intelligence Layer | 6 phases | Phase 1 in progress | 🟡 |
| Test coverage | ≥ 90% | ~60% | 🟡 |
| Image size (opencode) | < 500MB | 480MB | ✅ |
| Image size (pi) | < 300MB | TBD | ⏳ |
| Image size (vibe) | < 200MB | TBD | ⏳ |
| Security scan | 0 HIGH/CRITICAL | TBD | ⏳ |
| LLM call success rate | ≥ 99.9% | TBD | ⏳ |
| API response p99 latency | < 2s | TBD | ⏳ |
| Uptime | 99.95% | TBD | ⏳ |

---

## Run Intelligence Storage Roadmap

KubeSynapse initially stores run intelligence in PostgreSQL JSONB because it is already deployed and operationally simple. This is sufficient for MVP-scale event indexing, replay, diagnosis, and topology queries.

At higher volume, PostgreSQL should be replaced or complemented by:
- **ClickHouse** for high-volume analytical event queries (columnar, fast aggregations)
- **NATS JetStream or Redpanda** for durable event buffering between runtimes and gateway
- **Object storage** (S3-compatible) for long-term raw trace archives
- **OpenSearch** only if full-text log search becomes a primary requirement

Migration trigger: sustained ingestion above 5k-10k events/sec, retention beyond 30-90 days, or analytics queries regularly scanning millions of events.

---

## Next Actions

1. **Immediate:** Phase 1 — Add `runtime_run_events` table to `trace_store.py`
2. **This sprint:** Phase 2-3 — Runtime event emission + timeline/replay APIs
3. **Next sprint:** Phase 4-5 — Helm system agents + deterministic signal watch
4. **Month 2:** Phase 6 — Agent graph + spend lens APIs
5. **Month 3:** Reliability (Stories 11-14) and security hardening (Stories 15-18)
