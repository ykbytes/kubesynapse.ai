# KubeSynth Architecture

This document is the canonical reference for how KubeSynth is built, how data flows through the system, and how components interact.

**Who is this for:** Platform engineers, SREs, security auditors, and contributors who need to understand the system end-to-end.

---

## Table of Contents

- [System Context](#system-context)
- [Component Overview](#component-overview)
- [Control Plane](#control-plane)
- [Execution Plane](#execution-plane)
- [Data Flow: Chat Request](#data-flow-chat-request)
- [Data Flow: A2A Delegation](#data-flow-a2a-delegation)
- [CRD Relationships](#crd-relationships)
- [Shared Services](#shared-services)
- [Security Layers](#security-layers)

---

## System Context

```mermaid
flowchart TB
    subgraph External["External Systems"]
        LLM[LLM Providers<br/>OpenAI / Anthropic / Azure]
        IdP[Identity Provider<br/>OIDC / SAML / LDAP]
        Git[Git Repositories]
        Registry[Container Registries]
    end

    subgraph Users["Users & Clients"]
        Dev[Platform Engineer]
        Admin[Cluster Admin]
        App[External Application]
        CLI[agentctl CLI]
    end

    subgraph KubeSynth["KubeSynth Platform"]
        GW[API Gateway]
        UI[Web UI]
        OP[Operator]
        RT[Agent Runtimes]
    end

    Dev -->|HTTPS| UI
    Dev -->|kubectl| KubeSynth
    CLI -->|REST| GW
    App -->|A2A JSON-RPC| GW
    GW -->|LLM calls| LLM
    GW -->|Auth| IdP
    RT -->|Git clone| Git
    OP -->|Pull images| Registry
```

**Key interactions:**
- Users manage agents via `kubectl`, Web UI, or REST API
- External apps integrate via A2A JSON-RPC or SSE streams
- LLM calls are routed through LiteLLM for provider abstraction
- Auth is delegated to enterprise IdPs via OIDC, SAML, or LDAP

---

## Component Overview

```mermaid
flowchart LR
    subgraph Control["Control Plane"]
        K8S[Kubernetes API Server]
        CRD[CRDs<br/>kubesynth.ai/v1alpha1]
        OP[Operator<br/>Kopf-based]
        GW[API Gateway<br/>FastAPI]
    end

    subgraph Execution["Execution Plane"]
        RT[OpenCode Runtime<br/>per-agent StatefulSet]
        MCP[MCP Sidecars]
        Worker[Worker Jobs<br/>Workflows & Evals]
    end

    subgraph Shared["Shared Services"]
        LiteLLM[LiteLLM Proxy]
        PG[PostgreSQL]
        Redis[Redis]
        Qdrant[Qdrant]
        NATS[NATS]
    end

    subgraph Observability["Observability"]
        Prom[Prometheus]
        Graf[Grafana]
        OTEL[OpenTelemetry Collector]
    end

    GW -->|CRUD / Watch| K8S
    K8S -->|Stores| CRD
    OP -->|Reconciles| K8S
    OP -->|Manages| RT
    OP -->|Creates| Worker
    RT -->|LLM requests| LiteLLM
    RT -->|Vector search| Qdrant
    RT -->|Cache| Redis
    RT -->|Localhost| MCP
    GW -->|App state| PG
    OTEL -->|Metrics / Traces| Prom
    Prom -->|Visualize| Graf
```

**Design principle:** The control plane never runs user code. Every agent executes in an isolated sandbox in the execution plane.

---

## Control Plane

### Kubernetes API and CRDs

The Kubernetes API is the source of truth. The platform installs 11 CRDs:

| CRD | Scope | Purpose |
|-----|-------|---------|
| `AIAgent` | Namespaced | Agent definition: model, prompt, policy, MCP, storage |
| `AgentPolicy` | Namespaced | Guardrails, token caps, allowed models, A2A rules |
| `AgentApproval` | Namespaced | Human-in-the-loop approval requests |
| `AgentWorkflow` | Namespaced | DAG-based multi-agent pipelines |
| `AgentEval` | Namespaced | Evaluation suites and thresholds |
| `AgentTenant` | Cluster | Namespace isolation, quotas, RBAC |
| `MCPConnection` | Namespaced | Connection-driven tool integrations |
| `ConnectorPlugin` | Namespaced | Observability data collection |
| `ObservationTarget` | Namespaced | What is being observed |
| `ObservationPolicy` | Namespaced | How telemetry is evaluated |
| `ObservationReport` | Namespaced | Resulting health or anomaly output |

### Operator

The Kopf-based Python operator is the active reconciliation engine:

- Reconciles `AIAgent` into StatefulSets, Services, PVCs, ConfigMaps
- Reconciles `AgentWorkflow` and `AgentEval` into worker Jobs
- Tracks workflow and eval status from artifacts and logs
- Manages approval-state transitions
- Reconciles observability resources when CRDs are present

### API Gateway

The FastAPI gateway is a substantive backend service:

- Authentication and session handling (OIDC, SAML, LDAP, JWT, shared token)
- Namespace-aware authorization
- CRUD endpoints for all CRD types
- Invoke routing to runtime sandboxes
- Workflow trigger and streaming endpoints
- A2A JSON-RPC and SSE handling

---

## Execution Plane

### Runtime Sandboxes

Each agent runs as an isolated singleton StatefulSet:

- **OpenCode runtime**: FastAPI wrapper around `opencode serve`
- **Persistent state volume**: Survives pod restarts
- **Optional MCP sidecars**: Bundled tool containers on localhost
- **Policy hooks**: Input/output guardrails enforced at runtime
- **Security context**: Non-root, restricted, optional gVisor

### Worker Jobs

Workflows and evaluations run as short-lived Jobs:

- CRD status carries summary state only
- Detailed execution evidence lives in worker artifacts and logs
- Gateway and UI read from both Kubernetes state and artifacts

---

## Data Flow: Chat Request

```mermaid
sequenceDiagram
    participant U as User / UI
    participant GW as API Gateway
    participant K8S as Kubernetes API
    participant RT as OpenCode Runtime
    participant LLM as LiteLLM / Provider
    participant DB as PostgreSQL

    U->>GW: POST /api/v1/agents/{name}/invoke<br/>{prompt: "Deploy Redis"}
    GW->>GW: Authenticate & authorize
    GW->>K8S: GET AIAgent + AgentPolicy
    K8S-->>GW: Agent spec, policy rules
    GW->>GW: Validate prompt against guardrails
    GW->>DB: Load session memory (optional)
    GW->>RT: POST /invoke {prompt + context}
    RT->>RT: Build system prompt + memory
    RT->>LLM: POST /v1/chat/completions
    LLM-->>RT: Streaming response
    RT-->>GW: Response + metadata
    GW->>DB: Save message history
    GW-->>U: {response, thread_id, status}
```

**Latency targets:**
- Gateway auth + validation: < 50ms
- Runtime prompt construction: < 100ms
- LLM time-to-first-token: provider-dependent
- End-to-end non-streaming: < 5s for typical prompts

---

## Data Flow: A2A Delegation

```mermaid
sequenceDiagram
    participant A as Agent A (onboarding-bot)
    participant GW as API Gateway
    participant K8S as Kubernetes API
    participant B as Agent B (security-specialist)
    participant LLM as LiteLLM

    A->>GW: @security-specialist "Rotate TLS cert"
    GW->>GW: Parse @mention, resolve target
    GW->>K8S: GET AgentPolicy (allowedTargets)
    K8S-->>GW: Policy: security-specialist allowed
    GW->>GW: Create A2A task record
    GW->>B: POST /invoke {delegated prompt}
    B->>B: Build system prompt
    B->>LLM: LLM call
    LLM-->>B: Response
    B-->>GW: {response, status}
    GW->>GW: Update A2A task status
    GW-->>A: Return specialist answer
```

**Key enforcement points:**
- `allowedTargets` in `AgentPolicy` controls which agents can be called
- Namespace boundaries are respected unless explicitly crossed
- A2A tasks are tracked with unique IDs for auditability

---

## CRD Relationships

```mermaid
flowchart TB
    subgraph Agent["Agent Definition"]
        A[AIAgent]
        P[AgentPolicy]
        M[MCPConnection]
    end

    subgraph Governance["Governance"]
        AP[AgentApproval]
        AT[AgentTenant]
    end

    subgraph Automation["Automation"]
        W[AgentWorkflow]
        E[AgentEval]
    end

    subgraph Observability["Observability"]
        OT[ObservationTarget]
        OP[ObservationPolicy]
        OC[ConnectorPlugin]
        OR[ObservationReport]
    end

    A -->|references| P
    A -->|uses| M
    W -->|references| A
    E -->|targets| A
    AP -->|blocks| A
    AT -->|owns namespaces| A
    AT -->|owns namespaces| W
    OT -->|references| OC
    OT -->|references| OP
    OP -->|produces| OR
```

**Cardinality rules:**
- One `AIAgent` references zero or one `AgentPolicy`
- One `AgentWorkflow` references one or more `AIAgent`
- One `AgentTenant` owns one or more namespaces
- One `ObservationTarget` references one `ConnectorPlugin` and one `ObservationPolicy`

---

## Shared Services

| Service | Role | Persistence | Scaling |
|---------|------|-------------|---------|
| **LiteLLM** | LLM routing, rate limiting, key management | Config in PostgreSQL | HPA enabled |
| **PostgreSQL** | Gateway auth, sessions, usage, traces | PVC | Single replica or external |
| **Redis** | Session cache, LiteLLM caching | PVC | Single replica or external |
| **Qdrant** | Vector search for semantic memory | PVC | Single replica or external |
| **NATS** | Async messaging, event bus | JetStream | Cluster mode available |

---

## Security Layers

Security is enforced at multiple levels:

1. **Gateway**: Authentication, namespace-aware RBAC, rate limiting
2. **Control Plane**: Dedicated ServiceAccounts, least-privilege RBAC
3. **Network**: Default-deny NetworkPolicies, per-component egress rules
4. **Runtime**: Non-root containers, restricted seccomp, optional gVisor
5. **Policy**: Input/output guardrails, PII masking, prompt-injection detection
6. **Secrets**: External Secrets Operator, Vault CSI, or Sealed Secrets

See [RBAC Matrix](rbac-matrix.md) and [Secrets Management](secrets-management.md) for deep dives.

---

**Last Updated:** April 27, 2026  
**Platform Version:** 1.0.0
