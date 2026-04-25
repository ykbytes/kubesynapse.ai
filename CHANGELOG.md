# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] - robustness-hardening branch

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
  - OIDC default `audience` changed from empty string to `kubesynth-gateway`
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
  - `charts/kubesynth/values.schema.json` — comprehensive JSON Schema for Helm values
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
- 75+ lines of duplicated constant and utility definitions from `api-gateway/main.py`
- Unused `Code2` import from LandingPage.tsx
- Legacy flake8 references from Makefile
- OpenCode runtime adapter (`opencode-runtime/`)
- Codex runtime adapter (`codex-runtime/`)
- Alembic database migrations for operator (`operator/alembic.ini`, `operator/migrations/`)
- Operator modularized into `controllers/`, `builders/`, `services/`
- `operator/config.py`, `errors.py`, `reconcile.py`, `tracing.py` modules
- 10 MCP sidecar images under `mcp-sidecars/`
- Agent Helm sub-charts (`charts/agents/`)
- Agent templates and skills catalog (`catalog/`)
- `scripts/` directory for build, packaging, and lint scripts
- `tests/` directory for cross-cutting integration tests
- `docs/` directory consolidating all documentation
- Apache 2.0 LICENSE
- CONTRIBUTING.md and SECURITY.md
- CHANGELOG.md (this file)

### Changed
- Repository reorganized: docs moved to `docs/`, tests to `tests/`, scripts to `scripts/`
- README.md rewritten to reflect current state
- .gitignore updated for all project languages
- .gitignore now excludes transient local gateway state under `api-gateway/.local/` and ad-hoc `.pytest-*.txt` result captures
- Makefile updated with all 17 container image targets
- Goose runtime base image updated from removed `v1.0.18` tag to `latest`
- Documentation updated to remove 33 false completion checkmarks in road-to-prod-audit.md
- execution-plan.md updated to reflect operator modularization as DONE
- architecture-overview.md updated with all 4 runtimes and complete directory map
- INSTALL.md corrected to show 7 platform + 10 sidecar images (17 total)
- Kubernetes version requirement updated to 1.25+ across all docs
- INSTALL.md and `web-ui/README.md` now document the current local browser-QA flow: Vite dev on `5173`, gateway on `8080`, preview on `4173`, and local-auth + SQLite bootstrap for self-contained UI testing
- The desktop web-ui shell now uses an elastic sidebar width instead of a fixed wide MCP/resource column on narrow desktop panes

### Removed
- 15+ junk/temporary files from repository root
- Fake integration claims from landing page

### Fixed
- Broken relative link in `docs/walkthrough.md` (INSTALL.md path)
- CLI framework incorrectly documented as "Click" (actually Typer + Rich)
- Stale file path references in `docs/deployment-readme.md`

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
  - `api-gateway/Dockerfile` — includes `trace_store.py`, `traces_router.py`, `constants.py`, `utils.py`
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
- 6 CRDs: AIAgent, AgentPolicy, AgentApproval, AgentTenant, AgentWorkflow, AgentEval
- Kopf-based Kubernetes operator
- LangGraph agent runtime with guardrails, HITL approval, and RAG
- Goose runtime adapter
- FastAPI API gateway with hybrid auth (shared token + OIDC)
- React + TypeScript web console
- Helm chart (`charts/kubesynth/`)
- CLI tool (`agentctl`) built on Typer + Rich
- MCP sidecar architecture with 3-tier execution model
- Pre-built images published to `docker.io/yakdhane`
