# KubeSynapse Roadmap

This document outlines the planned evolution of KubeSynapse. Timelines are best-effort estimates and may shift based on community feedback and contributor availability.

---

## Q2 2026 (Current)

### v1.0 — Production Readiness

- [x] Operator reliability: leader election, circuit breakers, graceful shutdown
- [x] API Gateway security hardening: OIDC PKCE, JWT rotation, brute-force protection
- [x] MCP sidecar security: capability model, network egress filtering, resource quotas
- [x] Helm chart production readiness: PDBs, NetworkPolicies, HPA, cert-manager
- [~] API Gateway router split (13k-line monolith → modular routers)
- [~] API versioning (`/api/v1/` prefix with deprecation headers)
- [~] `mypy --strict` zero-error compliance
- [x] Full test suite with smoke tests in CI
- [x] Community governance files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, ROADMAP)
- [x] Helm chart OCI publishing to ghcr.io
- [x] Pi runtime support (dual-runtime alongside OpenCode)

**Target**: April 2026

> **Note**: Pi runtime support shipped as dual-runtime alongside OpenCode. Live observability and artifact APIs completed.

### v1.0.1 — Observability Consistency Hardening



- [ ] Replace demo-only `ObservationTarget` status reconciliation with connector-backed health, scrape, and report state
- [ ] Harden signal watch: use `sqlalchemy.text`, query `estimated_cost_usd`, isolate detector failures, and run the sweep once per leader instead of once per system agent
- [ ] Align Python and TypeScript SDKs to the live `/api/v1/traces/executions` contract and response envelopes
- [ ] Emit semantic `llm.call` runtime events across OpenCode, Pi, and Vibe direct runtime paths
- [ ] Add observability contract tests and smoke coverage for trace APIs, signal watch, and runtime event parity

**Target**: May 2026

---

## Q3 2026

### v1.1 — Multi-Tenant Enterprise

- [ ] Tenant isolation with namespace-scoped CRDs
- [ ] Resource quota enforcement per tenant
- [ ] SSO integration: SAML 2.0, Azure AD, Okta
- [ ] Audit log streaming to external SIEM (Splunk, Elastic)
- [ ] Cost attribution and billing integration
- [ ] Agent marketplace: one-click install from community catalog

### v1.2 — Advanced Agent Orchestration

- [x] Multi-agent workflows with DAG-based composition
- [x] Agent-to-Agent (A2A) protocol: cross-cluster agent communication
- [x] Human-in-the-loop approval workflows
- [x] Agent evaluation framework: automated regression testing
- [x] Prompt versioning and rollback

---

## Q4 2026

### v1.3 — Platform Extensions

- [ ] Custom runtime SDK (Go, Rust, TypeScript runtimes)
- [ ] GitOps-native agent management (Flux/ArgoCD integration)
- [ ] Fleet management: multi-cluster agent coordination
- [ ] BYO-model registry: Ollama, vLLM, local GPU support
- [ ] Agent telemetry and performance analytics dashboard

---

## 2027

### v2.0 — Autonomous Operations

- [ ] Self-healing agent detection and remediation
- [ ] Predictive scaling based on workflow patterns
- [ ] Federated learning for agent improvement across clusters
- [ ] Natural language policy definition
- [ ] CNCF incubation application

---

## How to Influence the Roadmap

The roadmap is community-driven. To propose a feature or reprioritization:

1. Open a [GitHub issue](https://github.com/ykbytes/kubesynapse.ai/issues) describing the proposal and use case
2. Describe the use case and expected impact
3. Discuss with maintainers and the community
4. If consensus is reached, a roadmap item is created

Votes (👍 reactions) on roadmap discussions help maintainers gauge community interest.

## Release Cadence

- **Patch releases** (v1.0.x): As needed for bug fixes and security patches
- **Minor releases** (v1.x.0): Approximately quarterly
- **Major releases** (v2.0.0): Annually, with migration guides

## Disclaimer

This roadmap is aspirational and subject to change. Priorities may shift based on security vulnerabilities, breaking changes in dependencies, or community needs. No items on this roadmap constitute a binding commitment.
