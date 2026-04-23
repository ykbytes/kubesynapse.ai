# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] - robustness-hardening branch

### Added
- SaaS landing page with honest capability claims (`web-ui/src/components/LandingPage.tsx`)
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
