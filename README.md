# KubeSynth

<p align="center">
  <a href="https://github.com/kubesynth/kubesynth/stargazers"><img src="https://img.shields.io/github/stars/kubesynth/kubesynth" alt="GitHub Stars"></a>
  <a href="https://github.com/kubesynth/kubesynth/blob/main/LICENSE"><img src="https://img.shields.io/github/license/kubesynth/kubesynth" alt="License"></a>
  <a href="https://github.com/kubesynth/kubesynth/releases"><img src="https://img.shields.io/github/v/release/kubesynth/kubesynth" alt="Release"></a>
  <a href="https://kubernetes.io/"><img src="https://img.shields.io/badge/Kubernetes-1.25%2B-326CE5" alt="Kubernetes 1.25+"></a>
</p>

**The production-grade, Kubernetes-native AI agent platform.**
Deploy, orchestrate, and govern AI agents using declarative custom resources. KubeSynth unifies an operator-driven control plane, A2A-ready API gateway, OpenCode runtime, and an extensible MCP tool ecosystem into a single Helm install.

---

## Architecture

KubeSynth separates the **control plane** (CRDs, operator, gateway) from the **execution plane** (per-agent runtimes and sidecars).

```mermaid
graph LR
    subgraph "Clients"
        UI[Web UI<br/>React 18 + Vite + Tailwind v4]
        CLI[agentctl CLI<br/>Typer-based]
        EXT[External API Clients]
    end

    subgraph "Control Plane"
        GW[API Gateway<br/>FastAPI monolith<br/>A2A JSON-RPC + SSE]
        K8S[Kubernetes API Server]
        OP[Operator<br/>Kopf-based engine<br/>~3,500-line worker]
        CRD[CRDs: kubesynth.ai/v1alpha1<br/>AIAgent, AgentWorkflow, AgentEval,<br/>AgentPolicy, AgentApproval, AgentTenant]
    end

    subgraph "Execution Plane"
        RT[OpenCode Runtime<br/>FastAPI wrapper<br/>around opencode serve]
        MCP[MCP Sidecars<br/>Bundled tool containers]
    end

    UI -->|HTTP| GW
    CLI -->|HTTP| GW
    EXT -->|A2A JSON-RPC / SSE| GW
    GW -->|CRUD / Watch| K8S
    K8S -->|Stores| CRD
    OP -->|Reconciles| K8S
    OP -->|Manages| RT
    RT -->|Localhost| MCP
```

---

## Quick Start

### Production Install (Helm OCI + Docker Hub)

The fastest path uses pre-built images from Docker Hub. Requires Kubernetes 1.25+, Helm 3.12+, and an LLM API key.

```bash
# 1. Install via Helm OCI (no git clone needed)
helm install kubesynth oci://docker.io/kubesynth/charts/kubesynth \
  --set platformSecrets.native.openaiApiKey="sk-..." \
  --set litellm.masterKey="your-secure-key"

# 2. Verify
kubectl port-forward svc/kubesynth-api-gateway 8080:8080
curl http://localhost:8080/api/health
```

### Install via Python SDK

```bash
pip install kubesynth-sdk
```

```python
from kubesynth import KubeSynthClient

client = KubeSynthClient(base_url="http://localhost:8080")
health = await client.health_check()
print(health)  # {"status": "ok"}
```

### Install via TypeScript SDK

```bash
npm install @kubesynth/sdk
```

```typescript
import { KubeSynthClient } from "@kubesynth/sdk";

const client = new KubeSynthClient({ baseUrl: "http://localhost:8080" });
const agents = await client.listAgents();
console.log(agents);
```

### Install CLI

```bash
pip install kubesynth-cli

agentctl health
agentctl agent list
agentctl workflow create --file my-workflow.yaml
```

### Install via Homebrew (macOS/Linux)

```bash
brew tap kubesynth/tap
brew install kubesynth-cli
```

### Local Development (Kind)

Build locally and load into a Kind cluster. No registry required.

```bash
# 1. Create cluster
kind create cluster --name kubesynth-dev

# 2. Build platform images + MCP sidecars
make docker-build REGISTRY=localhost/kubesynthai VERSION=dev CONTAINER_CLI=docker

# 3. Install
helm upgrade --install kubesynth ./charts/kubesynth \
  -f ./deploy/values.local-images.example.yaml

# 4. Port-forward
kubectl port-forward svc/kubesynth-api-gateway 8080:8080
kubectl port-forward svc/kubesynth-web-ui 3000:80

# 5. Install CLI
pip install ./cli
agentctl health
```

---

## Features

| # | Capability | What it means |
|---|------------|---------------|
| 1 | **Kubernetes-Native Orchestration** | Agents, policies, workflows, and tenants are `kubesynth.ai/v1alpha1` CRDs reconciled by a production Kopf operator. |
| 2 | **A2A Protocol Support** | Native JSON-RPC and Server-Sent Events (SSE) streaming for agent-to-agent delegation and real-time responses. |
| 3 | **OpenCode Runtime** | Purpose-built FastAPI wrapper around `opencode serve` with session persistence and checkpoint recovery. |
| 4 | **MCP Tool Ecosystem** | 11 bundled sidecar containers including code execution, web search, browser automation, database, git, Kubernetes ops, RAG, messaging, and more. |
| 5 | **Policy-Driven Governance** | `AgentPolicy` CRDs enforce input/output guardrails, token caps, PII masking, prompt-injection detection, and allowed model lists. |
| 6 | **Multi-Tenant Isolation** | `AgentTenant` CRDs provision isolated namespaces, resource quotas, RBAC, and network policies per team. |
| 7 | **Workflow Engine** | `AgentWorkflow` CRDs define DAG-based multi-agent pipelines with dependency chains, parallel execution, and human-in-the-loop approval gates. |
| 8 | **Continuous Evaluation** | `AgentEval` CRDs run scheduled test suites measuring relevance, toxicity, latency, and exact-match thresholds against live agents. |

---

## Comparison

| Capability | KubeSynth | LangChain | AutoGen | CrewAI | Dify | LangFlow |
|------------|-----------|-----------|---------|--------|------|----------|
| **Kubernetes Native** | Yes (Operator + CRDs) | No | No | No | Partial | Partial |
| **Self-Hosted** | Yes (Full stack via Helm) | Library only | Partial | Partial | Yes | Yes |
| **Multi-Agent Orchestration** | Yes (CRD-based DAGs) | LangGraph | Code-based | Code-based | Yes | Yes |
| **A2A Protocol (JSON-RPC/SSE)** | Yes (Native gateway) | No | No | No | No | No |
| **MCP Tool Ecosystem** | Yes (11 sidecars) | Requires setup | Requires setup | Requires setup | Limited | Limited |
| **Policy & Governance** | Yes (CRD guardrails) | Manual | Manual | Manual | Basic | Basic |
| **Human-in-the-Loop** | Yes (AgentApproval CRD) | External | External | External | Basic | Basic |
| **Eval Framework** | Yes (Built-in CRD) | External | External | External | Limited | Limited |
| **Primary Model** | Platform | Library | Framework | Framework | Platform | Platform |

---

## Screenshots

> **Dashboard Overview** — Real-time agent status, tenant utilization, and system health.
> ![KubeSynth Dashboard](docs/screenshots/dashboard-overview.png)

> **Agent Workflow Editor** — Visual DAG builder for multi-agent pipelines with approval gates.
> ![Workflow Editor](docs/screenshots/workflow-editor.png)

> **Policy Governance Panel** — Guardrail configuration, blocked patterns, and audit logs.
> ![Policy Panel](docs/screenshots/policy-governance.png)

---

## Contributing

We welcome contributions. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide.

```bash
# Fork, clone, and build
git clone https://github.com/your-username/kubesynth.git
cd kubesynth

# Run the test suite
make test

# Lint Python services
make lint

# Deploy to local Kind
make deploy-ai-sandbox-kind
```

---

## License

KubeSynth is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
