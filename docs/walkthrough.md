# AI Agent Sandbox — Implementation Walkthrough

This document narrates the implementation journey of the AI Agent Sandbox platform. It covers the core scaffolding decisions, enterprise feature phases, and the current production-ready state of the platform.

---

## Platform Status (March 2026)

All P0 and P1 roadmap items from the original plan have been implemented and are deployed as pre-built images on DockerHub (`docker.io/yakdhane`). The platform also ships with the major console-side P2 upgrades already delivered: command palette, mobile shell, onboarding tour, clone/export-import flows, and the admin health dashboard. The platform ships as a single self-contained Helm chart covering 7 platform services + 10 bundled MCP sidecars.

**Deploy in one command:**
```bash
helm upgrade --install ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f ./deploy/values.dockerhub.local.yaml
```

See [INSTALL.md](../INSTALL.md) for the full installation guide.

---

## Phase 1 — Helm Chart Foundation (`charts/ai-agent-sandbox/`)

- Created standard `Chart.yaml` and `values.yaml` with portable defaults (`pullPolicy: IfNotPresent`, ingress disabled by default).
- Added **LiteLLM Gateway** Deployment, Service, ConfigMap, and Secrets to centralize LLM routing, authentication, and authorization across all runtimes.
- Drafted the `AIAgent` Custom Resource Definition (CRD) — agents are defined and versioned as Kubernetes manifests.
- Added a strict `NetworkPolicy` to ensure agent pods are fully isolated and can only egress to the AI Gateway and declared MCP servers.
- Added a generic, opt-in **MCP server deployment template** for real upstream images.
- Added `AgentPolicy`, `AgentTenant`, `AgentWorkflow`, `AgentEval`, and `AgentApproval` CRDs.

---

## Phase 2 — Control Plane: Kubernetes Operator (`operator/`)

- **Python/Kopf-based** operator that watches all six CRDs and reconciles them into running infrastructure.
- Reconciliation loop (`operator/main.py`) provisions namespaces, StatefulSets, Services, PVCs, RBAC, NetworkPolicies, and worker Jobs per agent.
- Worker Jobs (`operator/worker.py`) execute workflow DAG steps and evaluation test suites in short-lived Kubernetes Jobs.
- State store (`operator/state_store.py`) tracks workflow run state, step outputs, and approval gates.

---

## Phase 3 — Data Plane: Agent Runtime (`agent-runtime/`)

- Secure Dockerfile: non-root user (`agentuser`), read-only filesystem, all Linux capabilities dropped.
- `agent_logic.py` — LangGraph `StateGraph` with durable `SqliteSaver` checkpoints. If a pod crashes, the agent resumes from its last checkpoint on restart.
- Full guardrails pipeline: prompt injection detection, PII masking, blocked pattern matching, per-request input/output token caps.
- Human-in-the-Loop (HITL) approval mechanism: agent pauses execution and creates an `AgentApproval` CR; webhook notifications are optional.
- RAG pipeline: Qdrant vector database integration via LangGraph retrieval nodes.
- OpenTelemetry tracing: agent exports token/span metrics to a standard OTLP endpoint (Jaeger, Prometheus, Grafana).

---

## Phase 4 — Additional Runtimes

### Goose Runtime (`goose-runtime/`)
- HTTP adapter that wraps the Goose CLI for agents using `runtime.kind: goose`.
- Supports per-agent `spec.runtime.goose.configFiles` to pre-seed native Goose config files (`config.yaml`, prompt templates, recipes) before `goose run` is invoked.
- Chart-wide Goose defaults set via `GOOSE_RUNTIME_CONFIG_FILES_JSON`; per-agent files merge over those by relative path.
- Exposes a `/debug/goose-info` endpoint for inspecting the effective Goose configuration without entering the container.

### Codex Runtime (`codex-runtime/`)
- HTTP adapter for Codex-native agent execution.
- Powers the Spec Kit example pipeline (`examples/speckit-agents.yaml`): 5-agent spec writing → scrum review → planning → task generation → implementation chain.

### OpenCode Runtime (`opencode-runtime/`)
- HTTP adapter for OpenCode sessions, agents, plugins, and MCP-native workflows.
- Per-agent `spec.runtime.opencode.configFiles` pre-seeds `opencode.json`, agent profiles under `agents/`, and Markdown skills under `skills/` before `opencode serve` starts.
- Chart-wide defaults via `OPENCODE_RUNTIME_CONFIG_FILES_JSON`; per-agent files merge over those.

---

## Phase 5 — Enterprise Enhancements

### Security & Zero-Trust MCP
- Operator injects robust Container Security Contexts: all capabilities dropped, read-only file systems, privilege escalation blocked.
- `enableGVisor` flag on `AIAgent` triggers `runsc` runtime class for kernel-level sandbox isolation.
- **Sidecar-based MCP servers**: tools run as sidecar containers in the agent pod, communicating securely over `localhost` — no cluster-network exposure.
- MCP `NetworkPolicy` default-deny + controlled ingress per the 3-tier model described in `architecture-overview.md`.

### Multi-Tenancy & Namespace Isolation
- `AgentTenant` CRD with auto-provisioned `ResourceQuota`, `LimitRange`, namespaced `ServiceAccount`, RBAC, and runtime secrets per tenant.
- Teams cannot see each other's agents; all API operations are scoped by namespace.

### Secrets Management
- `platformSecrets.mode: native` for development (chart-managed Kubernetes `Secret` objects).
- `platformSecrets.mode: external-secrets` for production — integrates with HashiCorp Vault, Azure Key Vault, AWS Secrets Manager via External Secrets Operator.

### Agent-to-Agent (A2A) Delegation
- Explicit A2A routing via `spec.a2a.allowedCallers` on the receiving agent.
- Specialist-team orchestration: `agentctl invoke --subagent` or `--subagents-file` launches parallel or sequential sub-task teams.
- `AgentWorkflow` CRD for DAG-based multi-agent pipelines with approval gates, artifact snapshots, and append-only execution journals.
- Workflow intelligence features: verification gates (`verify`), review steps (`type: review`), project context injection (`contextRef`), wave-based parallel execution, and next-action suggestions.

### Workflow Intelligence

The `AgentWorkflow` CRD supports several intelligence features that improve execution quality and trust:

- **Verification gates** — Any step can include a `verify` field. After the step completes, the operator sends a verification prompt to the same agent and marks the step as failed if verification does not pass.
- **Review steps** — Steps with `type: review` auto-construct a review prompt from `reviewCriteria` and the previous step output. The reviewing agent returns APPROVED or REJECTED with structured findings.
- **Context injection** — The workflow-level `contextRef` field references a ConfigMap in the same namespace. Its `context` key is prepended to every step prompt as a `[Project Context]` block, providing consistent project rules to all agents.
- **Wave execution** — The operator computes dependency-aware execution waves via `compute_execution_waves()`. Steps in the same wave run in parallel via `ThreadPoolExecutor`, while waves execute sequentially.
- **Next-action suggestions** — The API endpoint `GET /api/v1/agents/{ns}/{name}/next-action` recommends the next thing to do based on workflow state (retry failed step, run evaluation, deploy, etc.). The web UI renders this as a suggestion card.

### API Gateway (`api-gateway/`)
- FastAPI service exposing CRUD, invoke, and SSE streaming endpoints for all CRD types.
- Dual auth: shared bearer token (development) or OIDC JWT (production via `apiGateway.auth.mode: oidc`).
- Enterprise auth store with per-user roles, namespace scoping, and password management (`api-gateway/enterprise_auth.py`).

### Web UI (`web-ui/`)
- React + TypeScript + Vite console built with Tailwind CSS.
- Full feature set: agent discovery, chat invoke with SSE streaming, session persistence, A2A routing, specialist-team orchestration, skill/config editors, workflow and evaluation management, approval decisions, runtime log inspection, policy/admin operations, provider settings management, notifications, and health visibility.
- Deployed as part of the Helm chart when `webUi.enabled: true`.

### CLI (`cli/agentctl.py`)
- Python CLI built on Typer + Rich with colored tables, streaming response rendering, and JSON output mode for scripting.
- Full command coverage: agents, workflows, evals, approvals, policies, auth, admin, credentials, skills, tools.
- File-based commands accept both Kubernetes CRD manifests and direct API payload docs.

### MCP Sidecars (`mcp-sidecars/`)
- 10 production-ready MCP sidecar images bundled in the repository:
  `code-exec`, `web-search`, `documents`, `browser`, `database`, `git`, `kubernetes`, `messaging`, `rag`, `github-adapter`.
- Each sidecar has its own `Dockerfile` and is built+published as `docker.io/yakdhane/mcp-<name>`.
- Chart configures them via `mcpToolSidecars.*` values; agents opt in via `spec.mcpSidecars`.

---

## Platform Feature Matrix (Current State)

| Feature | Status | Notes |
|---|---|---|
| AIAgent CRD | ✅ Implemented | StatefulSet, Service, PVC, NetworkPolicy per agent |
| AgentPolicy CRD | ✅ Implemented | Input/output guardrails, model allow-list |
| AgentTenant CRD | ✅ Implemented | Namespace isolation, resource quotas |
| AgentWorkflow CRD | ✅ Implemented | DAG executor with approval gates, artifact journals, verify/review/contextRef/waves |
| AgentEval CRD | ✅ Implemented | Scheduled test suites with quality thresholds |
| AgentApproval CRD | ✅ Implemented | Async HITL approval with optional webhook |
| LangGraph runtime | ✅ Implemented | Durable SQLite checkpoints, OTel tracing |
| Goose runtime | ✅ Implemented | Per-agent config files, debug endpoint |
| Codex runtime | ✅ Implemented | Spec Kit pipeline example |
| OpenCode runtime | ✅ Implemented | Per-agent config files, plugin/agent pre-seeding |
| LiteLLM model proxy | ✅ Implemented | Redis-backed semantic cache, multi-provider routing |
| Qdrant RAG | ✅ Implemented | Vector retrieval in agent execution loop |
| MCP sidecars (10) | ✅ Implemented | All published to DockerHub |
| API Gateway | ✅ Implemented | REST+SSE, bearer + OIDC auth |
| Web UI | ✅ Implemented | Full workflow + approval + evaluation management |
| CLI (agentctl) | ✅ Implemented | Full CRD coverage, streaming, JSON mode |
| Helm chart | ✅ Implemented | Self-contained, portable, ingress opt-in |
| DockerHub images | ✅ Published | `docker.io/yakdhane/*` — ready to deploy |
| External Secrets Operator | ✅ Supported | `platformSecrets.mode: external-secrets` |
| gVisor support | ✅ Supported | `enableGVisor: true` on AIAgent |
| A2A delegation | ✅ Implemented | `allowedCallers`, specialist teams |
| Skills catalog | ✅ Implemented | File-backed SKILL.md with capability grants |
| OpenSandbox | ✅ Integrated | `agentRuntime.openSandbox.*` in values |

---

## Remaining Roadmap

### 🟢 P2 — Polish & Scale

| Feature | Notes |
|---|---|
| **GitOps / ArgoCD integration** | Store AIAgent manifests in Git, auto-sync via ArgoCD or FluxCD |
| **KEDA event-driven scaling** | Scale agent pods on request queue depth (beyond built-in HPA) |
| **Agent marketplace / template registry** | Versioned, shareable agent configs as OCI artifacts or Helm sub-charts |
| **Distributed token/cost budgets** | Cross-namespace token caps and cost attribution (chargeback/showback) |
| **Cross-region state replication** | PV snapshot backups for SQLite checkpoint data, DR runbooks |
| **Istio / service-mesh support** | mTLS between all platform components, traffic policies |
| **Full e2e CI pipeline** | Kind cluster spin-up in GitHub Actions, integration test suite against all CRDs |