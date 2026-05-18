<p align="center">
  <picture>
    <source media="(prefers-color-scheme: light)">
    <img alt="KubeSynapse" src="https://img.shields.io/badge/KubeSynapse-Kubernetes--native%20AI%20Agent%20Platform-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" height="48">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/ykbytes/kubesynapse.ai/stargazers"><img src="https://img.shields.io/github/stars/ykbytes/kubesynapse.ai?style=flat&color=326CE5" alt="Stars"></a>
  <a href="https://github.com/ykbytes/kubesynapse.ai/blob/main/LICENSE"><img src="https://img.shields.io/github/license/ykbytes/kubesynapse.ai?style=flat&color=326CE5" alt="Apache 2.0"></a>
  <a href="https://github.com/ykbytes/kubesynapse.ai/releases"><img src="https://img.shields.io/github/v/release/ykbytes/kubesynapse.ai?style=flat&color=326CE5" alt="Release"></a>
  <a href="https://kubernetes.io/"><img src="https://img.shields.io/badge/Kubernetes-native-326CE5?style=flat&logo=kubernetes" alt="Kubernetes native"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11+-326CE5?style=flat&logo=python" alt="Python 3.11+"></a>
  <a href="https://react.dev/"><img src="https://img.shields.io/badge/React-18-326CE5?style=flat&logo=react" alt="React 18"></a>
</p>

<br>

# KubeSynapse

**Ship AI agents the same way you ship everything else — as Kubernetes resources.**

KubeSynapse is an open-source, Kubernetes-native platform that turns AI agents into first-class cluster citizens. Define agents, workflows, policies, and observability targets as CRDs. The operator materializes them into runtime pods. The gateway handles auth, invoke routing, streaming, and traces. The web console gives you a real-time dashboard over everything.

No local-only toy frameworks. No vendor lock-in. Just your cluster, your models, your rules.

---

## Why KubeSynapse?

| Need | How KubeSynapse Solves It |
|---|---|
| **Lifecycle management** | Agents are CRDs — create, update, scale, and delete with `kubectl`. The operator handles StatefulSet provisioning, PVCs, and health checks. |
| **Security & compliance** | Policy CRDs enforce model allowlists, tool restrictions, MCP access, rate limits, and memory rules. RBAC integrates with your existing OIDC provider. |
| **Multi-agent coordination** | Workflow CRDs define multi-step pipelines with agents, reviews, loops, and conditional branching. Worker Jobs execute them with full artifact capture. |
| **Observability** | Built-in trace store captures every LLM call, tool invocation, and step execution. Signal watch detects anomalies. System agents investigate automatically. |
| **No vendor lock-in** | Bring your own models via LiteLLM (OpenAI, Anthropic, OpenRouter, Mistral, and 100+ providers). BYO runtimes with the standard Runtime API. |
| **Team-ready** | Multi-tenancy via AgentTenant CRDs. A2A protocol for agent-to-agent communication. Shared MCP hub for tool discovery. |

---

## Quick Start

### Prerequisites

- [Kind](https://kind.sigs.k8s.io/) or any Kubernetes cluster + [Helm](https://helm.sh/) 3.x
- 8 GB RAM, 4 CPUs

### Local Kind Deployment

```bash
# Create a local Kind cluster (skip if you have one)
kind create cluster

# Build and load images (or use pre-built from GHCR)
docker build -t kubesynapse/kubesynapse-api-gateway:latest api-gateway/
docker build -t kubesynapse/kubesynapse-operator:latest operator/
docker build -t kubesynapse/kubesynapse-web-ui:latest web-ui/
kind load docker-image kubesynapse/kubesynapse-api-gateway:latest kubesynapse/kubesynapse-operator:latest kubesynapse/kubesynapse-web-ui:latest

# Generate secrets (keep these safe in production)
export LITELLM_KEY=$(openssl rand -hex 16)
export API_TOKEN=$(openssl rand -hex 32)
export DB_PASS=$(openssl rand -hex 16)
export JWT_SECRET=$(openssl rand -hex 32)

# Install
helm install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse --create-namespace \
  --values deploy/values.kind.quickstart.yaml \
  --set global.imagePullPolicy=Never \
  --set platformSecrets.native.litellmMasterKey="$LITELLM_KEY" \
  --set platformSecrets.native.apiGatewaySharedToken="$API_TOKEN" \
  --set platformSecrets.native.databasePassword="$DB_PASS" \
  --set platformSecrets.native.jwtSecret="$JWT_SECRET" \
  --wait --timeout 3m

# Connect
kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 3000:80
# Open http://localhost:3000
```

### Deploy Your First Agent

```bash
kubectl apply -f examples/sample-policy.yaml
kubectl apply -f examples/sample-agent.yaml

# Watch it come to life
kubectl get aiagents -w
kubectl get pods -l app=ai-agent
```

---

## What's Inside

```
kubesynapse/
├── api-gateway/        FastAPI backend — auth, CRUD, invoke, SSE, A2A, traces
├── operator/           Kopf controllers — reconcile CRDs into pods and jobs
├── opencode-runtime/   Default agent runtime (OpenCode-powered)
├── pi-runtime/         Alternative runtime bridge (Pi-powered)
├── vibe-runtime/       Mistral-backed runtime bridge
├── web-ui/             React 18 + Vite console with live agent dashboard
├── mcp-sidecars/       10+ bundled MCP tools (git, web, db, k8s, etc.)
├── cli/                Python CLI (`agentctl`)
├── charts/             Helm chart with 12 CRDs, control plane, and shared services
├── deploy/             Environment overlays (Kind, staging, production)
├── examples/           Sample CRDs, workflows, and demo bundles
└── docs/               Architecture, API reference, operator guide, troubleshooting
```

---

## Features

### Agent Lifecycle
- **CRD-native:** `AIAgent` resources become StatefulSets with PVCs, env vars, and health probes
- **Multiple runtimes:** OpenCode (default), Pi, Mistral Vibe — swap with one field
- **Skills & MCP:** Attach skill files and MCP tool connections via the CRD spec
- **A2A protocol:** Agents discover and invoke peers via JSON-RPC with NetworkPolicy enforcement
- **Git integration:** Clone repos, manage credentials, auto-checkout on startup

### Security & Policy
- **Policy CRDs:** 22+ fields covering model allowlists, tool restrictions, rate limits, MCP access, memory rules, and approval requirements
- **Hybrid auth:** Shared token, OIDC PKCE, JWT rotation, brute-force protection — all in one middleware stack
- **Network policies:** Per-component isolation policies generated by the Helm chart
- **Enterprise auth:** SAML and LDAP support with session management

### Workflow Engine
- **DAG-based pipelines:** Define sequential and parallel steps with dependency edges
- **Step types:** Agent invocation, review/eval, loop iteration, conditional branching
- **Artifact capture:** Every run produces structured artifacts on persistent volumes
- **Retry & resume:** Failed steps retry; long workflows resume from checkpoints
- **Webhook triggers:** Kick off workflows from external events with signature verification

### Observability & Intelligence
- **Trace store:** Every LLM call, tool invocation, and step execution recorded with timestamps
- **Execution observatory:** Compare runs side-by-side, inspect logs, replay timelines
- **Signal watch:** Automated anomaly detection across traces
- **System agents:** Built-in diagnostic agents investigate issues autonomously
- **Observation CRDs:** Define collection targets, policies, and generate structured reports

### Console
- **Real-time dashboard:** Live agent status, resource usage, workflow progress
- **Agent composer:** YAML-aware editor with template wizard and validation
- **Workflow designer:** Visual DAG editor with step configuration
- **Chat interface:** Interact with agents directly from the browser with SSE streaming
- **Documentation panel:** Built-in CRD reference, API docs, and architecture guide
- **Dark theme:** High-contrast design with keyboard navigation and screen reader support

### Tooling
- **CLI (`agentctl`):** Rich terminal UI for managing agents, workflows, policies, and users
- **Python SDK:** Programmatic access to all 100+ API endpoints
- **TypeScript SDK:** Type-safe client for Node.js and browser applications

---

## Architecture

```mermaid
flowchart LR
    subgraph Clients[Clients]
        UI[Web UI]
        CLI[CLI and SDKs]
        EXT[External apps]
    end

    subgraph Control[Control Plane]
        GW[API Gateway\nauth, CRUD, invoke,\nSSE, A2A, traces]
        K8S[Kubernetes API + CRDs]
        OP[Operator\nreconcile engine]
    end

    subgraph Execute[Execution Plane]
        RT[Per-agent runtimes\nOpenCode / Pi / Vibe]
        JOB[Worker Jobs\nworkflow execution]
        PVC[State + artifact PVCs]
        SIDE[MCP sidecars]
        HUB[MCP hub]
    end

    subgraph Shared[Shared Services]
        LLM[LiteLLM]
        PG[PostgreSQL]
        REDIS[Redis]
        QDRANT[Qdrant]
        NATS[NATS]
    end

    subgraph Intelligence[Run Intelligence]
        TRACE[Trace store + API]
        SIGNAL[Signal watch]
        SYS[System agents]
        COL[Collector]
    end

    UI -->|same-host /api| GW
    CLI --> GW
    EXT -->|REST, SSE, A2A| GW
    GW -->|CRUD| K8S
    OP -->|watch, reconcile| K8S
    OP -->|provision| RT
    OP -->|trigger| JOB
    RT --> LLM
    RT --> REDIS
    RT --> QDRANT
    GW --> PG
    RT -. localhost .-> SIDE
    RT -. shared .-> HUB
    RT -. events .-> TRACE
    JOB -. events .-> TRACE
    TRACE --> SIGNAL
    SIGNAL --> SYS
    COL --> GW
```

**12 CRDs** drive the platform: `AIAgent`, `AgentPolicy`, `AgentWorkflow`, `AgentApproval`, `AgentTenant`, `McpConnection`, `WebhookReceiver`, `WorkflowTrigger`, `ObservationTarget`, `ObservationPolicy`, `ObservationReport`, `ConnectorPlugin`.

**100+ API endpoints** across 10 router groups: agents, workflows, policies, chat, auth, admin, LLM, A2A, observability, webhooks.

For deeper architecture docs, see [docs/architecture-overview.md](docs/architecture-overview.md) and [docs/architecture.md](docs/architecture.md).

---

## Documentation

| Topic | Link |
|---|---|
| Architecture overview | [docs/architecture-overview.md](docs/architecture-overview.md) |
| Full architecture reference | [docs/architecture.md](docs/architecture.md) |
| Configuration reference | [docs/configuration-reference.md](docs/configuration-reference.md) |
| Runtime API spec | [docs/runtime-api-spec.md](docs/runtime-api-spec.md) |
| Deployment guide | [deploy/README.md](deploy/README.md) |
| Helm chart guide | [charts/kubesynapse/README.md](charts/kubesynapse/README.md) |
| API gateway guide | [api-gateway/README.md](api-gateway/README.md) |
| Operator guide | [operator/README.md](operator/README.md) |
| Web UI guide | [web-ui/README.md](web-ui/README.md) |
| CLI guide | [cli/README.md](cli/README.md) |
| Getting started | [docs/getting-started.md](docs/getting-started.md) |
| Troubleshooting | [docs/troubleshooting.md](docs/troubleshooting.md) |
| FAQ | [docs/faq.md](docs/faq.md) |

---

## Development

```bash
# Run tests
make test

# Lint (Python + Helm)
make lint
make helm-lint

# Build web UI
make ui-build

# Targeted checks
cd api-gateway && python -m pytest tests/ -v
cd operator && python -m pytest tests/ -v
cd web-ui && npm run build

# Build all images
make docker-build
```

> **Windows users:** The root Makefile uses POSIX shell. Use Git Bash, WSL, or run component commands directly. See [INSTALL.md](INSTALL.md) for platform-specific guidance.

---

## Contributing

KubeSynapse is Apache 2.0 licensed and welcomes contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [AGENTS.md](AGENTS.md) for repo context used by AI coding agents.

---

## License

[Apache License 2.0](LICENSE) — use it, modify it, ship it.
