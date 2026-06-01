# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] - Sprint 10 (Observatory Pipeline Hardening & UI Fixes)

### Added
- **Token Breakdown**:
  - Full token breakdown (prompt, completion, cache_read, cache_write, reasoning) propagated end-to-end from OpenCode runtime through operator/gateway into LLMCallRecord and WorkflowExecution
  - `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` columns added to `runtime_run_events` table
  - Observatory UI Token Breakdown panel with stacked bar, cache hit ratio, and quality flags
- **Tool Call Duration**:
  - Per-tool `duration_ms` extracted from OpenCode's native `state.time.start`/`state.time.end` timestamps in `extract_tool_calls_from_messages()`
  - Duration propagated through operator worker and gateway direct-invoke handler into `ToolCallRecord.duration_ms`
  - Observatory Tool Mix chart now shows real per-tool wall-clock time
- **Policy Enforcement**:
  - Added optional OPA Gatekeeper sub-chart integration with admission constraints for required policy references, sealed policy protection, tool-pattern validation, and policy orphan prevention
  - Added `AgentPolicy.spec.sealed` and `AgentPolicy.spec.toolPolicy.adminToolCeiling`
  - Added operator-side policy attestation via `KUBESYNAPSE_POLICY_HASH` and runtime env injection for `OPENCODE_ADMIN_PERMISSION_CEILING_JSON`
- **Observatory UI**:
  - Added Prism-based JSON syntax highlighting for tool arguments and results
  - Added diff-aware rendering for patch-style tool payloads
  - Added expandable tool call rows with icon mapping, ArgsCard field extraction, and ResultBlock auto-detection
  - Added run-level insight charts to the Overview tab: Recent Run Trend (duration sparkline across the workflow's last runs), Step Contribution (share bars), Step Variability (min/median/max range per step with current-run marker), Tool Mix (time-weighted MCP tool usage with failure counts), Model Efficiency (token-vs-latency scatter, bubble by cost), and Quality Flags strip (warning/error events, tool failures, longest quiet gap, missing token data). Pure CSS, no charting library added; derives from payloads already fetched for the Observatory.

### Changed
- **OpenCode Runtime**:
  - Increased extracted tool-result payload limit from `2000` to `40000` characters before forwarding trace data to the operator and gateway
- **Documentation**:
  - Updated repo docs and in-app docs to reflect the current Observatory workspace, trace payload fields, Gatekeeper-backed policy enforcement, and OpenCode runtime behavior

### Fixed
- **Trace Pipeline**:
  - Fixed 0-tokens issue: operator worker and gateway were reading flat `metadata.prompt_tokens` instead of nested `metadata.tokens.input/output/reasoning/cache_read/cache_write`
  - Fixed runtime `_sync_emit` omitting `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` from event envelopes
  - Fixed gateway `_upsert_from_event` missing handler for `llm.call` event type (LLM calls from runtime events were silently dropped)
  - Fixed direct-invoke gateway handler assigning overall execution latency to every tool call instead of per-tool duration
  - Fixed direct-invoke tool call field name mismatch: gateway now accepts both runtime format (`tool`/`input`/`output`) and legacy format (`name`/`args`/`result`)
  - Fixed `DEFAULT_API_GATEWAY_SHARED_TOKEN` not propagating to worker jobs (workers couldn't auth to `/api/traces/batch`)
  - Changed helm chart from `valueFrom: secretKeyRef` (optional) to direct `value:` for reliable token injection
  - Fixed worker log endpoint looking up pods in workflow namespace instead of operator namespace (`kubesynapse`)
  - Fixed `execution_id` missing from step, LLM call, and tool call records stored in `execution_traces` DB
  - Fixed `latency_ms` not computed for steps — now calculated from `started_at` → `completed_at`
  - Fixed per-step LLM/tool counts showing 0 — `_execution_trace_to_dict` now joins by `step_id`
  - Fixed `step_index` hardcoded to 0 — worker no longer sends explicit index, backend auto-increments from `len(steps)`
  - Fixed LLM calls not recorded for pi-runtime when metadata is not a dict
- **Observatory UI**:
  - Fixed tabs (Steps, Logs, Insights, Compare) not scrollable — added `flex-1 overflow-y-auto`
  - Fixed observatory sidebar list not rendering in AppSidebar
  - Made tool/LLM call parsers defensive against missing `execution_id` (old data compatibility)
  - Fixed malformed or truncated JSON results falling back to plain text when the runtime output was missing closing braces
- **Auth Page**:
  - Tab now shows "Create Account" during bootstrap instead of misleading "Sign In"
  - Hidden broken "Sign in instead" toggle when no users exist (bootstrap mode)
  - Restored "Open Console" button on local LandingPage (showLogin prop)

## [Unreleased] - Sprint 9 (Pi Runtime & Live Observability)

### Added
- **Pi Runtime Integration**:
  - New `runtime.kind: "pi"` support alongside `opencode`
  - Pi bridge (`pi-runtime/pi_bridge.js`) implements HTTP bridge for Pi RPC mode
  - Artifact API endpoints (`/artifacts/list`, `/artifacts/download`, `/artifacts/zip`) added to pi-runtime
  - Model timeout mechanism (`MODEL_TIMEOUT_MS=120s`) with auto-abort and retry
- **Deployment Hardening**:
  - LiteLLM database bootstrap is now automatic via Helm init container running `prisma db push`
  - Operator dependency egress policy added for PostgreSQL, Redis, NATS, LiteLLM, and Qdrant
  - Operator Kubernetes API egress policy fixed to avoid blocking private-cluster API access
  - LiteLLM isolation policy now includes egress to PostgreSQL, Redis, and DNS
- **Workflow Engine Improvements**:
  - Fixed workflow controller enqueue bug (`GROUP`, `VERSION`, `WORKFLOW_PLURAL`)
  - Fixed worker artifact PVC creation (skip cross-namespace `ownerReferences`)
  - Fixed streamed response reconstruction (backfill missing completed.response / tool_calls from stream events)
  - Fixed stream truncation bug (prefer accumulated `response.delta` text)
  - Added autoRetry for recoverable failures
  - Radically slimmed context ConfigMaps to prevent model hangs
- **Live Observability UI**:
  - ExecutionObservatory with trace inspection, StepInspector, LLMCallViewer, TracePlayer, ExecutionTimeline, ExecutionDiffView
  - Live Activity Stream with step-level status transitions
  - Workflow file browser with ZIP download restoration
  - Agent live reasoning log design (terminal-style SSE events, filter chips, copy/download, stall detection)
- **Resource & Reliability**:
  - Boosted agent sandbox resources (builder limits: 4 CPU / 8Gi)
  - Increased step timeouts (`scaffold-project` 3600s, `build-synth-core` 5400s, etc.)
  - Wipe Pi session PVC between restarts to clear stale sessions

### Verification
- `npm run build` — 0 TypeScript errors
- `helm lint --strict` — passes
- `ruff check` — 0 errors
- Operator tests pass

---

## [1.0.0] - 2026-04-27 — Sprint 8 (Final)

### Added
- **Vulnerability Scanning Pipeline** (`.github/workflows/security-scan.yaml`):
  - Trivy container image scanning for all 4 images (api-gateway, operator, opencode-runtime, web-ui) with SARIF upload to GitHub Security
  - Trivy filesystem scanning with SARIF upload
  - kube-linter for Helm/K8s best practices (privileged containers, privilege escalation, read-only root FS, run-as-non-root, capabilities, sensitive host mounts, anti-affinity, RBAC)
  - checkov for IaC security scanning (Helm charts + rendered K8s manifests)
  - npm audit for both web-ui and TypeScript SDK
  - pip-audit extended to cover cli/ dependencies
  - Bandit SAST with SARIF format and GitHub Security integration
  - CRITICAL vulnerabilities block on all scans
  - Secret detection via TruffleHog with verified credential scanning
- **RBAC Audit & Matrix** (`docs/rbac-matrix.md`):
  - Comprehensive documentation of all 5 ServiceAccounts (operator, api-gateway, agent-runtime, collector, litellm)
  - Detailed permission matrix with justification for every API group/resource/verb
  - Least-privilege audit checklist (13 checks, all PASS)
  - Verification commands for cluster operators
  - Identified: no `pods/exec`, no cluster-wide secret list on gateway, agent runtime cannot mutate platform CRDs
- **Secrets Management Guide** (`docs/secrets-management.md`):
  - 3 full integration paths: External Secrets Operator (AWS/GCP/Azure), Vault CSI Provider (HashiCorp Vault), Sealed Secrets (Bitnami)
  - Each path: prerequisites, step-by-step installation, configuration snippets, verification commands
  - Comparison table across all 3 approaches
  - KubeSynapse-specific secret reference (8 secret keys with component mapping)
  - Security best practices section
- **Artifact Distribution**:
  - Docker Hub publishing in release workflow: `KubeSynapse/operator`, `KubeSynapse/api-gateway`, `KubeSynapse/opencode-runtime`, `KubeSynapse/web-ui` (with `:latest` tags)
  - Helm OCI pushed to both GHCR and Docker Hub (`oci://docker.io/kubesynapse/charts/KubeSynapse`)
  - Python SDK renamed to `kubesynapse-sdk` for `pip install kubesynapse-sdk`
  - TypeScript SDK renamed to `@kubesynapse/sdk` for `npm install @kubesynapse/sdk`
  - CLI renamed to `kubesynapse-cli` for `pip install kubesynapse-cli`
  - README updated with install instructions for pip, npm, Homebrew, and Helm OCI
- **Compatibility Matrix** (`COMPATIBILITY.md`):
  - Test matrix covering K8s 1.25–1.34 (Kind), with planned EKS/GKE/AKS columns
  - Component compatibility table (8 core components, 11 MCP sidecars)
  - Kubernetes feature requirements reference
  - Automated compatibility test script (`scripts/test-compatibility.sh`) — creates Kind clusters across versions, deploys KubeSynapse, runs smoke tests, cleans up
  - Known limitations documented (OpenShift, GKE Autopilot, arm64, Fargate, Windows)
- **Accessibility (WCAG 2.1 AA)**:
  - `SkipToContent` component — skip-to-main-content link, first focusable element on every page
  - `AriaLiveRegion` component — dual-region (polite `role="status"` + assertive `role="alert"`) with `announceToScreenReader()` utility
  - `FocusTrap` component — keyboard trap for modals/dialogs/drawers with Escape handling
  - `ConfirmDialog` enhanced: `aria-labelledby`, `aria-describedby`, `aria-label` on buttons, decorative icon `aria-hidden`
  - `<main id="main-content" tabIndex={-1}>` for skip link target
  - Color contrast verified: `text-foreground` on `bg-background` = 12.3:1 (WCAG AA requires 4.5:1)
  - Accessibility audit report (`docs/accessibility-report.md`) — full WCAG 2.1 AA compliance matrix with 50 success criteria
- **Security Documentation** (`SECURITY.md`):
  - Accepted vulnerabilities section: pip-audit accepted risks (2 entries), Trivy container accepted risks (2 entries), kube-linter accepted risks (2 entries), Bandit accepted risks (2 entries)
  - Quarterly review cadence defined
  - Escalation process for new CRITICAL CVEs

### Changed
- `clients/python/setup.py` — package renamed from `kubesynapse-client` to `kubesynapse-sdk`
- `clients/typescript/package.json` — package renamed from `@KubeSynapse/client` to `@kubesynapse/sdk`
- `cli/pyproject.toml` — package renamed from `agentctl` to `kubesynapse-cli`
- `web-ui/src/App.tsx` — integrates SkipToContent and AriaLiveRegion at app root; main element gets `id="main-content"`
- `.github/workflows/release.yaml` — extended for dual-registry (GHCR + Docker Hub) with cosign signing on both, `:latest` tags on Docker Hub, Helm OCI push to both registries
- `README.md` — added pip/npm/Homebrew install instructions, Helm OCI one-liner install

### Verification
- `npm run build` — ✅ 0 TypeScript errors (4608 modules)
- `helm lint --strict` — ✅ passes
- `ruff check` — ✅ 0 errors on all new code
- All 6 a11y components built successfully
- Release workflow validated for dual-registry push

---

## [Unreleased] - Sprint 7

### Added
- **CI/CD Release Automation**: `.github/workflows/release-please.yaml` — Google release-please action with conventional commit detection, auto-versioning, and auto-CHANGELOG generation (`release-please-config.json`, `.release-please-manifest.json`)
- **Supply Chain Integrity**: `.github/workflows/supply-chain.yaml` — per-push SBOM generation (Syft SPDX + CycloneDX), Trivy vulnerability scanning with SARIF upload to GitHub Security, Cosign keyless image signing with OIDC, and build provenance attestation
- **Grafana Dashboards** (3 new):
  - `deploy/grafana/dashboards/agent-overview.json` — Agent health, pod status, memory/CPU, CRD reconciliation rates
  - `deploy/grafana/dashboards/workflow-execution.json` — Workflow runs, step duration P50/P95, worker queue depth, failure rates
  - `deploy/grafana/dashboards/llm-usage.json` — Token rate by model, cost rate ($/hr), latency P50/P95/P99 per model, provider error rates, LiteLLM health
- **Prometheus Alert Rules** (4 new): Agent pod down (critical), workflow failure rate > 5%, API error rate > 1%, LiteLLM unhealthy, step timeout rate > 10%
- **Performance Benchmarks**: `benchmarks/` directory with 3 reproducible benchmark scripts (`bench-reconcile.py`, `bench-api.py`, `bench-concurrency.py`) and comprehensive README with baseline targets, CI integration, and JSON export format
- **Landing Page v2.0**: Animated cluster visualization in hero (floating agent pods + K8s control plane + SVG connection lines), live GitHub stars counter (fetched from GitHub API), 4-column comparison matrix (KubeSynapse vs LangChain vs CrewAI vs Kubiya) with 12 capability rows, system-preference dark mode detection (already existed but enhanced)
- **Blog Posts** (3): `docs/blog/what-is-KubeSynapse.md` — "Why Kubernetes is the Right Platform for AI Agents", `docs/blog/KubeSynapse-vs-alternatives.md` — full comparison with detailed feature matrix, `docs/blog/building-first-agent.md` — "Build a DevOps Agent in 5 Minutes" tutorial with copy-pasteable YAML
- **Video Content Plan**: `docs/videos.md` — 5-video series outline (product overview 3min, governance 8min, workflows 8min, observability 6min, community 4min) with scripts, visual assets, recording tools, and publishing strategy
- **Python SDK**: `clients/python/` — async `KubeSynapseClient` (httpx + Pydantic v2) with 15 API methods covering health, agents, workflows, policies, and traces; `SyncKubeSynapseClient` wrapper; `setup.py` with PyPI-ready config; full type annotations and docstrings
- **TypeScript SDK**: `clients/typescript/` — `KubeSynapseClient` class with full type coverage, 15 API methods, AbortController timeouts, error handling; exports all request/response types; React/Next.js usage example
- **Community Infrastructure**: `docs/community.md` — Community page with Slack/Discord links, meeting schedule, contributor path (4 levels), Good First Issue criteria; `docs/contributor-program.md` — 4 recognition tiers (Bronze/Silver/Gold/Platinum), swag, conference sponsorship, nomination process; Good First Issue template (`.github/ISSUE_TEMPLATE/good_first_issue.md`)
- **Good First Issue** label criteria added to `CONTRIBUTING.md`

### Changed
- `web-ui/src/components/LandingPage.tsx` — Added `AnimatedCluster` component (floating pod visualization), `GitHubStars` component (live star count from GitHub API), replaced generic "Other Platforms" comparison with 4-column matrix (KubeSynapse vs LangChain vs CrewAI vs Kubiya)
- `deploy/prometheus/rules.yaml` — Expanded from 8 to 13 alert rules with Sprint 7 additions
- `CONTRIBUTING.md` — Added Good First Issue criteria section

### Verification
- `npm run build` — ✅ 0 TypeScript errors (4606 modules)
- `helm lint --strict` — ✅ passes (0 failures)
- `ruff check` — ✅ 0 errors on all new code (benchmarks/, clients/)
- `ruff check --fix` — ✅ auto-fixes applied, all clean

### Added
- Production-grade SaaS landing page with animated particle background, typewriter hero, scroll parallax, and tabbed macOS terminal showcasing complete AIAgent/AgentWorkflow YAML examples (`web-ui/src/components/LandingPage.tsx`)
- `api-gateway/constants.py` — extracted 90+ constants (env vars, A2A protocol, runtime limits, factory modes, validation patterns)
- `api-gateway/utils.py` — extracted 10 utility functions with full type annotations (`now_iso`, `normalize_json_object`, `normalize_subagent_strategy`, etc.)
- Helm production hardening toggles (`podDisruptionBudget.enabled`, `networkPolicy.enabled`)
- PodDisruptionBudgets for API Gateway, Operator, LiteLLM, and PostgreSQL with verified selectors
- Startup probes for web-ui, nats, redis, postgresql, qdrant, and collector DaemonSet
- NetworkPolicy templates with default deny ingress/egress, DNS egress, and per-component allow rules (`templates/network-policy-default.yaml`)
- Security contexts for collector DaemonSet (`allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities: drop: [ALL]`)
- `.bandit.yaml` with K8s-appropriate skips (B104/B108 for container networking and /tmp mounts)
- `.github/workflows/security-scan.yaml` for automated bandit + trivy scanning
- `.pre-commit-config.yaml` with ruff, mypy, and helm-lint hooks
- `.devcontainer/devcontainer.json` for VS Code remote containers
- GitHub issue templates (bug report, feature request) and PR template
- `CODE_OF_CONDUCT.md`

### Security
- Fixed 12 vulnerabilities in `api-gateway/auth_middleware.py` (CVSS up to 9.8):
  - OIDC default `audience` changed from empty string to `KubeSynapse-gateway`
  - Enforced HTTPS for OIDC endpoints via URL scheme validation
  - Added `Secure`, `HttpOnly`, `SameSite=Lax` flags to auth cookies
  - Made Bearer token parsing case-insensitive
  - Fixed `X-Forwarded-For` to use last proxy IP instead of first
  - Added `kid` validation before JWK signature verification
  - Replaced global `asyncio.Lock()` with lazy initialization
  - Fixed namespace default from `["*"]` to `[]` (breaking security fix)
  - Added 15s sleep to pod lifecycle preStop hooks
  - Wrapped `verify_refresh_token` in `try/except` with `safe_record_audit`
  - Fixed `verify_password` to return `False` on exception instead of raising
  - Rate-limit auth endpoints (login, register, password reset)

### Added — Sprint 2 (Stories 1-6)
- **Memory System Overhaul** (`opencode-runtime/memory/`):
  - 5-tier retention: EPHEMERAL, SESSION, WORKSPACE, LONG_TERM, PERMANENT
  - Pluggable provider architecture: Builtin (JSONL), Semantic (Qdrant vector DB)
  - Entity extraction for user profiles and project context (inspired by Hermes Agent)
  - Context fencing with `<memory-context>` tags to prevent model hallucination
  - Time-decay relevance scoring and automatic pruning
  - 15 new environment variables for memory configuration
- **Test Infrastructure**:
  - `api-gateway/tests/conftest.py` — FastAPI TestClient fixtures with mocked auth, K8s, DB
  - `api-gateway/tests/test_smoke.py` — 8 smoke tests (health, ready, auth, CRUD, metrics)
  - `operator/tests/conftest.py` — Mock K8s API fixtures, sample specs
  - `operator/tests/test_smoke.py` — 8 smoke tests (error classification, config, validation)
  - `Makefile` targets: `test-gateway`, `test-operator` with `pytest-cov`
  - CI workflow updated to run tests with coverage and upload artifacts
- **Static Analysis Baseline**:
  - `ruff check` passes with **0 errors** across all Python code (was 281)
  - `helm lint --strict` passes with JSON Schema validation
  - Added `per-file-ignores` in `pyproject.toml` for intentional patterns
- **Configuration Hardening**:
  - `charts/kubesynapse/values.schema.json` — comprehensive JSON Schema for Helm values
  - `docs/configuration-reference.md` — documents every env var and Helm value
  - `deploy/values.dev.yaml`, `values.staging.yaml`, `values.production.yaml`
- **Database & Migration Safety**:
  - PostgreSQL connection pool tuning: `pool_size`, `max_overflow`, `pool_recycle`, `pool_timeout`
  - `statement_timeout` configured for PostgreSQL connections
  - `/api/health/db` endpoint returning 200/503 based on DB connectivity
  - `SchemaVersion` model and `_verify_schema_version()` for migration integrity
  - N+1 query eliminated in `record_memory_items()` via batched lookup
- **API Contract Validation**:
  - `RateLimitMiddleware` — token bucket per IP, configurable RPS/burst
  - `RequestSizeLimitMiddleware` — rejects bodies >10MB
  - `ErrorResponse` Pydantic model with standardized error schema
  - Descriptions added to 8 key Pydantic models (InvokeRequest, CreateAgentRequest, etc.)
- **Authentication Hardening**:
  - `jwt_utils.py` rewritten for multiple active keys with `kid` rotation
  - JWT key rotation via `rotate_jwt_key()` with grace period for old tokens
  - Explicit rejection of JWT `none` algorithm
  - `PasswordResetToken` model and password reset flow (`/api/auth/forgot-password`, `/api/auth/reset-password`)
  - Exponential backoff for brute-force protection
  - Structured audit logging: `audit_login_success`, `audit_login_failure`
- **Helm Production Hardening**:
  - PodDisruptionBudgets for 4 components
  - Startup probes for 6 components
  - Security contexts (runAsNonRoot, readOnlyRootFilesystem, drop ALL)
  - 10 NetworkPolicy templates (default deny + per-component allows)

### Changed
- `README.md` completely rewritten with Mermaid architecture diagram, Quick Start, feature comparison table, and real-world use cases
- LandingPage switched from dark theme to light/white theme for better readability
- Makefile lint target migrated from flake8 to ruff + bandit
- `.github/workflows/ci.yaml` now triggers on `preprod` branch in addition to `main`
- `pyproject.toml` updated with `constants` in `known-first-party` isort list
- Resource requests/limits tuned to sensible production defaults across all Helm components
- Collector DaemonSet hardened with container securityContext, startupProbe, and `/tmp` emptyDir mount

### Fixed
- All 36 ruff lint issues in `api-gateway/main.py` reduced to 0 (import sorting, bare except clauses, en-dash characters, nested with statements, false-positive S105 suppressions)
- `api-gateway/main.py` import block reorganized with `constants` and `utils` as first-party modules
- B904 violations fixed by adding `from None` to HTTPException conversions in date parsing
- S110 violations fixed by replacing bare `pass` with `logger.warning(..., exc_info=True)`
- RUF003 en-dash characters replaced with hyphens in comments

### Removed
- 15+ junk/temporary files from repository root
- Fake integration claims from landing page

---

## [Unreleased] - Deployment & Docker

### Added
- **Docker & Deployment Infrastructure**:
  - `docker-compose.yml` — full local stack (Postgres 16, Redis 7, NATS 2, Qdrant 1.7, API Gateway, Operator, Web UI, OpenCode RT, LiteLLM proxy)
  - `deploy/litellm-config.yaml` — model routing config for OpenAI, Anthropic
  - `scripts/deploy-docker.sh` — Docker Compose lifecycle helper (up/down/build/logs/status/health/push)
  - `scripts/deploy-k8s.sh` — Helm-based K8s deployment helper (install/upgrade/uninstall/status/logs/port-forward)
  - `scripts/verify-docker-builds.sh` — validates all Dockerfiles build successfully
  - `deploy/README.md` — comprehensive deployment guide with quick start, troubleshooting, production checklist
  - Makefile targets: `compose-up`, `compose-down`, `compose-build`, `compose-logs`, `compose-status`, `k8s-install`, `k8s-upgrade`, `k8s-uninstall`, `k8s-status`, `k8s-logs`, `k8s-port-forward`
- **Dockerfile updates**:
  - `api-gateway/Dockerfile` — includes `trace_store.py`, `traces_router.py`
  - `operator/Dockerfile` — includes `trace_client.py`, `circuit_breaker.py`
  - `opencode-runtime/Dockerfile` — includes `memory/` package
  - `.dockerignore` files expanded (IDE files, venv, logs, OS files)

## [Unreleased] - Execution Observatory

### Added
- **Execution Observatory** — end-to-end workflow trace inspection and replay:
  - `api-gateway/trace_store.py` — hybrid SQL+JSONL+filesystem trace storage with 4 models (WorkflowExecution, StepExecution, LLMCallRecord, ToolCallRecord) and 20 event types
  - `api-gateway/traces_router.py` — FastAPI router with 8 endpoints: list, detail, summary, step detail, events, delete, JSON export, and self-contained HTML report
  - `operator/trace_client.py` — batched, asynchronous HTTP trace reporter with graceful degradation (fire-and-forget, thread-safe, auto-flush)
  - `operator/worker.py` — wired trace emission for workflow start/end, step start/end, LLM calls, and tool calls via thread-local context
  - `web-ui/src/components/ExecutionObservatory.tsx` — full workspace panel with execution list, filters, and tabbed detail view
  - `web-ui/src/components/observatory/` — 5 sub-components: TracePlayer (play/pause/seek), StepInspector (Sheet drawer), LLMCallViewer (prompt/response dialog), ExecutionTimeline (vertical, color-coded), ExecutionDiffView (side-by-side comparison)
  - Integrated "Observatory" into App.tsx routing, AppSidebar.tsx navigation, and lib/api.ts helpers
  - Added `ExecutionListItem` and `ExecutionListResponse` TypeScript types
  - 11 unit tests for `TraceClient` batching, flush, and failure handling (`operator/tests/test_trace_client.py`)
  - Trace endpoint smoke tests added to `api-gateway/tests/test_smoke.py`

### Fixed
- `web-ui` TypeScript build errors in new Observatory components (import paths, unused variables, type mismatches, `fractionalSecondDigits` compatibility)
- `operator/trace_client.py` removed unused `json` import (ruff F401)
- `operator/worker.py` replaced `try/except/pass` with `hasattr` checks for trace context cleanup (ruff SIM105)

## [0.1.0] - 2026-03-19

### Added
- Initial platform release
- 5 core CRDs: AIAgent, AgentPolicy, AgentApproval, AgentTenant, AgentWorkflow
- Kopf-based Kubernetes operator
- LangGraph agent runtime with guardrails, HITL approval, and RAG
- Goose runtime adapter
- FastAPI API gateway with hybrid auth (shared token + OIDC)
- React + TypeScript web console
- Helm chart (`charts/kubesynapse/`)
- CLI tool (`agentctl`) built on Typer + Rich
- MCP sidecar architecture with 3-tier execution model
- Pre-built images published to `docker.io/kubesynapse`
