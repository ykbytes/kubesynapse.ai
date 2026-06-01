# KubeSynapse Architecture Overview

This document describes the architecture that the repository currently implements. It focuses on the active runtime path, the current control-plane model, and the observability capabilities that now exist in code.

For the canonical diagram source, see [`docs/kubesynapse-architecture.mmd`](kubesynapse-architecture.mmd). The older [`docs/kubesynth-architectureold.drawio`](kubesynth-architectureold.drawio) file is retained as a legacy reference and should not be treated as the source of truth.

## 1. System Summary

KubeSynapse is a Kubernetes-native AI agent platform built around these ideas:

- represent agents, workflows, policies, approvals, tenants, and observability resources as Kubernetes custom resources
- reconcile desired state with a Python operator and background worker Jobs
- run each agent as an isolated singleton StatefulSet backed by one of the supported runtime adapters
- route model calls through LiteLLM and optional retrieval through Qdrant
- expose the platform through a FastAPI gateway, a React web UI, and the `agentctl` CLI

The platform uses OpenCode as its production runtime (`runtime.kind: opencode`). Two additional runtimes — Pi (`runtime.kind: pi`) and Mistral Vibe (`runtime.kind: mistral-vibe`) — are available in alpha but not recommended for production workloads.

## 2. Top-Level Architecture

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'fontSize': '14px' }}}%%
flowchart TB
    UI["🖥️ Web UI"]:::client
    CLI["⌨️ agentctl CLI"]:::client
    EXT["🔗 External Apps & Webhooks"]:::client
    GH["🐙 Git Repositories"]:::external
    IDP["🔐 Identity Providers"]:::external

    GW("⚡ API Gateway
    FastAPI · Auth · CRUD · Invoke · SSE"):::gateway

    K8S{{"☸️ Kubernetes API
    12 CRDs"}}:::k8s

    OP("🔧 Operator
    Kopf reconcile loop
    StatefulSets · Jobs · PVCs"):::operator

    SEC["🛡️ Security Baseline
    Immutable config · NetworkPolicy
    Credential proxy · Audit trail"]:::security

    OC("🤖 OpenCode Runtime
    Per-agent StatefulSet
    Sessions · stream · local memory"):::runtime

    JOB("📦 Workflow Jobs
    Artifact-driven execution
    Summary status projection"):::worker

    MCP("🔌 MCP Access
    10 tool sidecars + collector
    Per-agent or shared hub"):::sidecar

    PVC[("💾 Runtime PVC
    Workspace · sessions · checkpoints")]:::storage

    ART[("📁 Workflow artifacts
    PVCs · logs")]:::storage

    LLM("🧪 LiteLLM
    Model proxy
    Provider abstraction"):::shared

    PG[("🗄️ PostgreSQL
    Auth · durable memory · traces")]:::shared

    REDIS[("⚡ Redis
    Gateway cache · LiteLLM cache")]:::shared

    QDRANT[("🔍 Qdrant
    Optional semantic retrieval")]:::shared

    NATS("📡 NATS
    Configured async extension point"):::shared

    TRACE("📊 Execution Observatory
    Timeline APIs · trace store"):::intel

    SIGNAL("🚨 Signal Watch
    SQL anomaly detection"):::intel

    SYS("🧪 System Agents
    AI-powered explanations"):::intel

    UI -->|"HTTPS /api/*"| GW
    CLI -->|"REST + SSE"| GW
    EXT -->|"Webhooks · A2A"| GW
    GH -.->|"Git clone / repo access"| OC

    GW -->|"CRUD (CustomObjectsApi)"| K8S
    GW -->|"SQLAlchemy — auth, memory, traces"| PG
    GW -->|"Agent + session cache"| REDIS
    GW -.->|"Provider/admin APIs"| LLM
    GW -.->|"Configured async ext."| NATS
    GW -->|"OIDC / SAML / LDAP"| IDP

    K8S -->|"Watch CRDs (Kopf)"| OP

    OP ==>|"Provision StatefulSet + PVC"| OC
    OP -->|"Create worker Job"| JOB
    OP -.->|"Inject immutable config"| SEC

    OC -->|"localhost or hub transport"| MCP
    OC -->|"Workspace + checkpoints"| PVC
    OC -->|"HTTPS /v1/chat/completions"| LLM
    OC -->|"Vector search when enabled"| QDRANT

    JOB -->|"Artifacts + logs"| ART
    LLM -->|"Response cache"| REDIS

    OC -.->|"POST runtime-events"| TRACE
    JOB -.->|"POST runtime-events"| TRACE

    TRACE -->|"SQL anomaly queries"| SIGNAL
    SIGNAL -.->|"Invokes for explanation"| SYS

    classDef client fill:#1a2332,stroke:#326CE5,stroke-width:2px,color:#7baaf7
    classDef external fill:#1a1a2e,stroke:#555,stroke-width:1px,color:#888
    classDef gateway fill:#1a1a3e,stroke:#7c3aed,stroke-width:3px,color:#c4b5fd
    classDef k8s fill:#0d2137,stroke:#326CE5,stroke-width:3px,color:#93c5fd
    classDef operator fill:#1a2332,stroke:#f59e0b,stroke-width:2px,color:#fcd34d
    classDef runtime fill:#0d3320,stroke:#10b981,stroke-width:2px,color:#6ee7b7
    classDef worker fill:#1a2332,stroke:#6366f1,stroke-width:2px,color:#a5b4fc
    classDef sidecar fill:#1a2332,stroke:#ec4899,stroke-width:2px,color:#f9a8d4
    classDef storage fill:#1a2332,stroke:#14b8a6,stroke-width:2px,color:#99f6e4
    classDef shared fill:#1a1a2e,stroke:#64748b,stroke-width:2px,color:#94a3b8
    classDef intel fill:#2d1b4e,stroke:#a855f7,stroke-width:2px,color:#d8b4fe
    classDef security fill:#1a2e1a,stroke:#22c55e,stroke-width:3px,color:#86efac
```

### What the diagram shows

- **Clients** (blue) — Web UI, CLI, and external apps hit the gateway via HTTPS; Git repositories and identity providers are external systems used by the runtime and gateway
- **Control Plane** (blue/purple/amber) — The gateway handles auth, CRUD, invoke routing, durable memory, traces, and provider/admin APIs; the operator watches 12 CRDs and reconciles them into real Kubernetes workloads
- **Security** (green) — The hardened baseline includes immutable runtime config, credential isolation, network policy, and audit propagation into runtime pods
- **Execution Plane** (green/pink/teal) — OpenCode runs as the production runtime in isolated StatefulSets; workflow Jobs persist detailed evidence as artifacts and logs; MCP access can come from 10 bundled tool sidecars, the separate collector sidecar, or shared hub services
- **Shared Services** (gray) — The primary model-call path is runtime -> LiteLLM -> provider; PostgreSQL stores auth, durable memory, and traces; Redis backs gateway and LiteLLM caching; Qdrant supports optional semantic retrieval; NATS remains a configured async extension point
- **Run Intelligence** (purple) — Worker execution traces and runtime semantic events flow into the gateway, the Execution Observatory renders enriched step and tool detail, Signal Watch runs SQL anomaly detection, and system agents are invoked for AI-powered explanations

## 3. Control Plane

### Kubernetes API and CRDs

The Kubernetes API remains the control-plane source of truth. The chart installs 12 CRDs. Core resources include:

| CRD | Scope | Purpose |
| --- | --- | --- |
| `AIAgent` | Namespaced | Defines an agent model, system prompt, policy reference, MCP integrations, and storage |
| `AgentPolicy` | Namespaced | Defines input guardrails, output guardrails, per-request token caps, and allowed models |
| `AgentApproval` | Namespaced | Represents human approval requests for high-risk actions |
| `AgentWorkflow` | Namespaced | Defines multi-step agent DAGs with dependencies and optional approval gates |
| `AgentTenant` | Cluster | Defines namespace isolation, quotas, allowed models, and tenant admins |
| `McpConnection` | Namespaced | Declares reusable MCP connection records for remote, hub, or sidecar transport |
| `WebhookReceiver` | Namespaced | Declares signed inbound webhook receivers |
| `WorkflowTrigger` | Namespaced | Declares event-driven workflow triggers |
| `ConnectorPlugin` | Namespaced | Declares how observability data is collected |
| `ObservationTarget` | Namespaced | Declares what is being observed |
| `ObservationPolicy` | Namespaced | Declares how collected telemetry is evaluated |
| `ObservationReport` | Namespaced | Stores the resulting health or anomaly output |

### Operator responsibilities

The Python operator is the reconciliation core.

Current responsibilities include:

- reconciling agents into runtime StatefulSets, Services, PVCs, ConfigMaps, and policies
- reconciling workflows into worker Jobs
- tracking workflow status from artifacts and logs
- managing approval-state transitions
- reconciling observability resources when the observability CRDs are present

The operator is not just a bootstrap layer. It is the active control-plane engine for the product.

## 4. Application And Execution Plane

### API Gateway

The API gateway is now a substantial backend service, not just a thin router.

Current responsibilities include:

- authentication and session handling
- namespace-aware authorization
- CRUD endpoints for agents, workflows, policies, approvals, MCP connections, and observability resources
- invoke routing to runtime sandboxes
- workflow trigger endpoints
- runtime metadata and validation endpoints used by the UI
- managed sign-in and local-auth flows in current deployments

### Runtime sandboxes

Each agent runs in an isolated sandbox. The production runtime is OpenCode.

An OpenCode agent sandbox typically contains:

- the OpenCode runtime process
- runtime-generated config and context files
- optional MCP sidecars
- a persistent state volume
- policy and approval enforcement hooks

> **Alpha runtimes:** Pi (`pi-runtime/`) and Mistral Vibe (`vibe-runtime/`) are available as alpha runtimes but are not recommended for production use. They follow the same runtime API contract but have limited hardening and test coverage.

### Worker Jobs

Workflows rely on short-lived worker Jobs plus artifact persistence rather than trying to project every execution detail directly into CRD status.

That means:

- CRD status carries summary state
- detailed execution evidence lives in worker artifacts and logs
- the gateway and UI read from both Kubernetes state and artifact-derived state

## 5. Run Intelligence Layer

The Run Intelligence Layer extends the Execution Observatory with semantic event indexing, deterministic anomaly detection, and AI-powered analysis.

### Components

| Component | Location | Purpose |
|---|---|---|
| `runtime_events.py` | Each runtime + worker | Emits structured events to the API gateway |
| `trace_store.py` | API gateway | Stores execution traces and semantic runtime events in PostgreSQL |
| `signal_watch.py` | Operator controller | Periodic SQL-based anomaly detection |
| `traces_router.py` | API gateway | Timeline, query, and summary APIs |
| `system-agents.yaml` | Helm chart | Predefined AIAgent CRs for analysis |

### Event Flow

1. **Execution tracing**: The operator worker batches step, LLM, and tool execution events to `POST /api/v1/traces/batch`
2. **Semantic events**: The OpenCode runtime and the operator worker emit runtime events via their `runtime_events` module (alpha runtimes also emit events when used)
3. **Ingestion**: Execution traces and semantic events are POSTed to the gateway on their respective trace endpoints
4. **Storage**: The API gateway stores execution detail in `execution_traces` and semantic events in `runtime_run_events`
5. **Detection**: The signal watch controller runs SQL checks every 60 seconds
6. **Reporting**: Anomalies create `ObservationReport` CRs with severity classification
7. **Analysis**: System agents can be invoked for AI-powered explanations

### System Agents

Three predefined agents provide AI-powered analysis:

- **ks-run-inspector** — investigates failed runs and produces root-cause summaries
- **ks-signal-summarizer** — converts raw anomaly signals to human-readable incident briefs
- **ks-spend-reviewer** — reviews cost/token anomalies and recommends optimizations

These agents are invoked on triggers (failures, thresholds) rather than running continuously. Deterministic SQL/rule checks fire first; LLM agents are only invoked for explanation/escalation.

## 6. Shared Services

The default chart values currently wire these core shared services and extension workloads:

- LiteLLM for model proxying and provider abstraction
- PostgreSQL for auth, chat sessions, durable memory, audit, and traces
- Redis for gateway caches and LiteLLM response caching
- Qdrant for optional semantic retrieval
- NATS as a configured async extension point
- the MCP hub namespace and selected shared MCP services
- the collector DaemonSet path when enabled

## 7. MCP Architecture

The current platform uses two MCP access patterns:

- per-agent tool sidecars for tools that should stay tightly scoped to one runtime
- a separate per-agent `collector` sidecar used for intelligence and observability workflows
- shared MCP hub services plus structured connection records managed through the gateway

The `AIAgent` contract now includes connection-oriented MCP metadata, and the UI uses gateway-provided validation and runtime preview information to present attachable MCP connections.

## 8. Workflow Execution

### AgentWorkflow

`AgentWorkflow` still defines DAG-style execution, but the current operational model is:

1. the workflow exists as a CRD object and user-facing definition
2. the operator or gateway triggers execution
3. a worker Job performs the orchestration work
4. step-level detail is persisted as artifacts and logs
5. summary state is projected back into workflow status and the UI

## 9. Observability Architecture

The observability module is implemented in the current repository.

Current behavior includes:

- the chart installs observability CRDs
- the operator registers `observation_controller` when those CRDs are present
- the controller synthesizes target, policy, connector, and report status
- the web UI presents observability dashboards and editors for connectors, targets, and policies
- the repository includes a collector agent image and a separate MCP collector sidecar for cluster intelligence workflows

The current implementation uses demo-friendly report generation so operators can make the observability flow visible without wiring a full external telemetry backend first.

## 10. Security Model

Security is enforced across several layers:

- **Runtime Isolation** — Plugin auto-discovery disabled by default (`OPENCODE_DISABLE_DEFAULT_PLUGINS=true`). No dynamic code execution from config files.
- **Immutable Security Baseline** — Hardened ConfigMap mounted at `/etc/kubesynapse/opencode.json` enforces `plugin: []`, restrictive permissions, and blocked external skills. Admin overrides apply at runtime.
- **Traffic Enforcement** — Admin-controlled provider routing forces all LLM traffic through audited proxy. Provider redirect attacks blocked via `OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON`.
- **Model Governance** — Global model allowlist via `OPENCODE_ADMIN_MODEL_OVERRIDE_JSON`. Complements `AgentPolicy.allowedModels` with runtime-level enforcement.
- **Request Tracing** — `x-request-id` propagated through gateway → operator → runtime → OpenCode subprocess. Structured JSON logging across all services.
- gateway authentication and namespace-aware authorization with structured error responses
- dedicated service accounts and RBAC for operator and runtimes
- network isolation for runtime pods and MCP access
- non-root runtime pods with restricted security contexts
- optional gVisor support through `enableGVisor`
- policy-driven input and output guardrails, tool controls, and A2A restrictions
- secret handling through native chart secrets or External Secrets integration
- daily garbage collection CronJob for audit log retention and session cleanup
- PostgreSQL backup CronJob (enable with `backup.enabled: true`)

## 11. Most Important Current Truths

If you need the shortest possible architectural summary, these are the points that matter most:

1. The production in-tree runtime is OpenCode. Pi and Mistral Vibe are available in alpha.
2. The gateway is now a substantive application backend, not just a thin router.
3. Workflow detail lives in worker artifacts more than CRD status.
4. MCP is both sidecar-based and connection-driven.
5. Observability is implemented through CRDs, controller logic, UI views, collector support, and trace-backed run intelligence.
6. The Run Intelligence Layer provides semantic event indexing, deterministic anomaly detection, and AI-powered analysis across all runtimes.
7. Explicit A2A delegation exists today, while NATS remains an extension point for deeper async coordination later.
8. Agent runtimes are hardened by default with plugin isolation, immutable config, traffic enforcement, and model governance.
