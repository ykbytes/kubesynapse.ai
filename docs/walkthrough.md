# KubeSynapse Implementation Walkthrough

This document is a current implementation walkthrough of the platform that exists in this repository today. It replaces the earlier multi-runtime narrative with the actual OpenCode-first architecture, current operator model, and the new observability surfaces now shipped in the chart and UI.

## Platform Snapshot

As of April 2026, the shipped platform is centered on these paths:

- `AIAgent`, `AgentPolicy`, `AgentWorkflow`, `AgentEval`, `AgentApproval`, and `AgentTenant` remain the core control-plane CRDs
- `ConnectorPlugin`, `ObservationTarget`, `ObservationPolicy`, and `ObservationReport` extend the control plane with an observability model
- the runtime surface is now OpenCode-only: `runtime.kind: opencode`
- the operator provisions singleton runtime sandboxes and worker Jobs from Kubernetes resources instead of maintaining an external workflow service
- the gateway owns auth, CRUD, invoke, session persistence, memory persistence, and MCP connection management
- the web UI exposes agents, chat, workflows, evaluations, MCP management, intelligence, and observability

## 1. Helm Chart Foundation

The platform chart in `charts/KubeSynapse` is still the entry point for the full stack, but the scope has grown beyond the original sandbox core.

What the chart installs now:

- the control-plane CRDs for agents, policies, workflows, evals, approvals, tenants, and observability
- the operator deployment and worker configuration
- the API gateway, web UI, LiteLLM, Redis, Qdrant, NATS, and PostgreSQL
- the shared MCP hub namespace and hub-server deployment model
- a collector DaemonSet path for cluster intelligence gathering

Important current chart characteristics:

- OpenCode is the only runtime the CRD allows
- bundled MCP sidecars are still defined in values for per-agent local tools
- the chart includes both shared MCP hub servers and structured MCP connection support
- local Kind refresh is now a first-class path through `scripts/deploy-ai-sandbox-kind.ps1` and `deploy/values.ai-sandbox.kind-local.yaml`

## 2. Operator and Reconciliation Model

The operator has moved to a more modular controller layout under `operator/controllers`, `operator/builders`, and `operator/services`.

Current responsibilities:

- reconcile `AIAgent` resources into singleton StatefulSets, Services, service accounts, and runtime wiring
- queue worker Jobs for `AgentWorkflow` and `AgentEval` execution
- project compact workflow and eval state back into CRD status while keeping detailed artifacts on PVC-backed JSON files
- reconcile approval decisions so waiting workflows resume or fail deterministically
- conditionally register optional controllers when their CRDs are installed
- reconcile the observability CRDs when `observationtargets.kubesynapse.ai` exists

Notable implementation changes relative to the old docs:

- the controller package now loads optional controllers dynamically based on installed CRDs
- observability is implemented in `operator/controllers/observation_controller.py`
- workflow execution state is more artifact-oriented than before, with status holding summaries and references instead of full payload blobs

## 3. Runtime Path: OpenCode Only

The old LangGraph, Goose, and Codex runtime paths are no longer the active architecture described by this repository. The supported runtime is now the OpenCode runtime under `opencode-runtime/`.

What the runtime does today:

- exposes `/invoke`, `/invoke/stream`, `/health`, and `/ready`
- assembles system prompt, project context, skills, and OpenCode config files from the agent spec
- manages bounded concurrency and resumable sessions
- performs HITL approval preflight before execution when required
- supports structured outputs, multi-turn autonomy, working directories, and tool-call capture
- persists runtime state locally on PVC-backed storage
- sanitizes secrets before tool inputs and outputs are surfaced back to users

Key runtime design points:

- `spec.runtime.opencode.configFiles` is the supported per-agent config injection model
- skill files and config files are both materialized into the runtime workspace
- direct A2A delegation is validated through policy and gateway reachability data
- runtime memory and session behavior are now part of the gateway and runtime contract, not just an internal checkpoint mechanism

## 4. API Gateway Surface

The gateway in `api-gateway/main.py` has expanded beyond simple agent CRUD and invoke routing.

Current responsibilities include:

- bearer-token, local-auth, LDAP, OIDC, and SAML integration points through the auth stack
- bootstrap admin creation and Postgres-backed auth/session state
- agent, workflow, eval, approval, policy, and admin endpoints
- chat session persistence and memory APIs
- MCP connection CRUD and runtime-preview shaping for the UI
- observability and intelligence-facing API surfaces used by the modern web UI

This means the gateway is now both the public invoke edge and the platform application backend.

## 5. Web UI Scope

The web UI is no longer just a simple agent invoke console.

Current major surfaces:

- agent management with file-backed skills and OpenCode config editing
- chat workbench with streaming, sessions, tool calls, artifacts, and explicit A2A routing
- workflow management and composer with run history and execution-state views
- eval management and result inspection
- provider-centric settings and admin views
- MCP registry and connection management
- intelligence and observability dashboards

The observability dashboard now understands:

- connectors
- observation targets
- observation policies
- observation reports

This is backed by the new CRDs and controller, not just mock UI state.

## 6. MCP Model

The MCP story has become more structured.

There are now two main patterns:

1. Per-agent sidecars declared on the agent spec for localhost-only tool access.
2. Shared MCP hub servers plus structured MCP connection records managed through the gateway and shown in the UI.

The bundled tool sidecars still cover:

- code execution
- web search
- documents
- browser
- database
- git
- GitHub adapter
- Kubernetes
- messaging
- RAG

The repository also includes an MCP collector sidecar that can talk to deployed collector agents.

## 7. Observability Module

The observability work is no longer only a proposal. The current codebase includes:

- new CRDs for `ConnectorPlugin`, `ObservationTarget`, `ObservationPolicy`, and `ObservationReport`
- a controller that synthesizes status and report data for targets and policies
- a collector agent image intended to run as a DaemonSet and gather read-only cluster intelligence
- example manifests that intentionally produce visible reports in the UI
- UI panels for viewing and editing the observability resources

Current practical model:

- a connector describes how telemetry is collected
- a target describes what is being watched
- a policy describes how telemetry should be interpreted
- a report is the resulting visible status artifact

The current implementation intentionally includes demo-driven report generation so the end-to-end flow is visible before a full external telemetry backend is wired in.

## 8. Deployment and Operations Paths

There are now three real ways operators use this repository:

1. Deploy published images with Helm and values overrides.
2. Build core images and the bundled MCP sidecars locally using the `Makefile`.
3. Refresh the existing local Kind release with `scripts/deploy-ai-sandbox-kind.ps1`.

Operationally important files:

- `deploy/values.dockerhub.local.yaml`
- `deploy/values.cluster.example.yaml`
- `deploy/values.ai-sandbox.kind-local.yaml`
- `scripts/deploy-ai-sandbox-kind.ps1`
- `scripts/observability-smoke-test.ps1`

## 9. What Changed from the Older Walkthrough

The earlier walkthrough was no longer accurate in several important ways.

It described or implied:

- `agent-runtime/` as the main runtime path
- LangGraph as the primary execution engine
- Goose and Codex runtimes as current platform runtimes
- the pre-observability product surface

The current code instead reflects:

- `opencode-runtime/` as the supported runtime path
- gateway-managed auth, sessions, memory, and MCP connections
- worker-artifact-first workflow and eval execution
- observability CRDs, collector support, and related UI views

## 10. Recommended Companion Docs

For more precise detail, read these alongside this walkthrough:

- `docs/architecture-overview.md` for the up-to-date system model
- `docs/observability-explained.md` for the practical observability flow
- `docs/deployment-readme.md` for current deployment entry points
- `web-ui/README.md` for the console feature map
- `cli/README.md` for the current `agentctl` command surface