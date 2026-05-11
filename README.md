# KubeSynapse

<p align="center">
  <a href="https://github.com/ykbytes/kubesynapse.ai/stargazers"><img src="https://img.shields.io/github/stars/ykbytes/kubesynapse.ai" alt="GitHub Stars"></a>
  <a href="https://github.com/ykbytes/kubesynapse.ai/blob/main/LICENSE"><img src="https://img.shields.io/github/license/ykbytes/kubesynapse.ai" alt="License"></a>
  <a href="https://github.com/ykbytes/kubesynapse.ai/releases"><img src="https://img.shields.io/github/v/release/ykbytes/kubesynapse.ai" alt="Release"></a>
  <a href="https://kubernetes.io/"><img src="https://img.shields.io/badge/Kubernetes-1.25%2B-326CE5" alt="Kubernetes 1.25+"></a>
</p>

**Kubernetes-native agent orchestration for teams that want a real cluster install.**
Deploy, govern, and operate AI agents with CRDs, an operator-driven control plane, a gateway, and bundled runtime integrations.

---

## Architecture

KubeSynapse separates the **control plane** (CRDs, operator, gateway) from the **execution plane** (per-agent runtimes and sidecars).

```mermaid
flowchart LR
    subgraph Clients
        UI["Web UI\nReact 18 + Vite + Tailwind v4"]
        CLI["agentctl CLI\nTyper-based"]
        EXT["External API Clients"]
    end

    subgraph ControlPlane[Control Plane]
        GW["API Gateway\nFastAPI monolith\nA2A JSON-RPC + SSE"]
        K8S["Kubernetes API Server"]
        OP["Operator\nKopf-based engine\n~3,500-line worker"]
        CRD["CRDs: KubeSynapse.ai/v1alpha1\nAIAgent, AgentWorkflow, AgentEval\nAgentPolicy, AgentApproval, AgentTenant"]
    end

    subgraph ExecutionPlane[Execution Plane]
        RT["OpenCode Runtime STS\nFastAPI wrapper\naround opencode serve"]
        PI["Pi Runtime STS\nNode.js RPC bridge\nHTTP bridge mode"]
        MCP["MCP Sidecars\nBundled tool containers"]
    end

    UI -->|HTTP| GW
    CLI -->|HTTP| GW
    EXT -->|A2A JSON-RPC / SSE| GW
    GW -->|CRUD / Watch| K8S
    K8S -->|Stores| CRD
    OP -->|Reconciles| K8S
    OP -->|Manages| RT
    OP -->|Manages| PI
    RT -->|Localhost| MCP
    PI -->|Localhost| MCP
```

---

## Quick Start

### Cluster Install

Start from the checked-in cluster example and keep your real secrets in a local copy.

```bash
cp ./deploy/values.cluster.example.yaml ./deploy/values.cluster.yaml
# Edit deploy/values.cluster.yaml before installing.

helm upgrade --install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse \
  --create-namespace \
  -f ./deploy/values.cluster.yaml

kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080
curl http://localhost:8080/api/health

kubectl apply -f ./examples/sample-policy.yaml
kubectl apply -f ./examples/sample-agent.yaml
```

The sample agent manifest uses the current CRD shape, including `runtime.kind` and `storage.size`.

### Python SDK

```bash
pip install ./clients/python
```

```python
from KubeSynapse import KubeSynapseClient

client = KubeSynapseClient(base_url="http://localhost:8080")
health = await client.health()
print(health)  # {"status": "ok"}
```

### TypeScript SDK

```bash
npm install ./clients/typescript
```

```typescript
import { KubeSynapseClient } from "@kubesynapse/sdk";

const client = new KubeSynapseClient({ baseURL: "http://localhost:8080" });
const agents = await client.listAgents();
console.log(agents);
```

### CLI

```bash
pip install ./cli

agentctl health
agentctl agent list
agentctl workflow create --file my-workflow.yaml
```

### Local Image Development

Build locally, then push or load those images into the cluster runtime your environment uses.

```bash
# 1. Build platform images + MCP sidecars
make docker-build REGISTRY=localhost/kubesynapse VERSION=dev CONTAINER_CLI=docker

# 2. Make the images reachable from your cluster, then install
helm upgrade --install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse \
  --create-namespace \
  -f ./deploy/values.local-images.example.yaml

# 3. Verify
kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080
kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 3000:80
```

`deploy/values.local-images.example.yaml` assumes `localhost/kubesynapse/*:dev` image names. Adjust it if your cluster reaches a different registry.

---

## Features

| # | Capability | What it means |
|---|------------|---------------|
| 1 | **Kubernetes-Native Orchestration** | Agents, policies, workflows, and tenants are `KubeSynapse.ai/v1alpha1` CRDs reconciled by a Kopf operator. |
| 2 | **A2A Protocol Support** | Native JSON-RPC and Server-Sent Events (SSE) streaming for agent-to-agent delegation and real-time responses. |
| 3 | **Dual Runtime Support** | OpenCode runtime (FastAPI wrapper) AND Pi runtime (Node.js RPC bridge) with session persistence and checkpoint recovery. |
| 4 | **MCP Tool Ecosystem** | 11 bundled sidecar containers including code execution, web search, browser automation, database, git, Kubernetes ops, RAG, messaging, and more. |
| 5 | **Live Agent Observability** | Terminal-style live reasoning logs, execution trace replay, step-level status streaming, and artifact browsing with ZIP download. |
| 6 | **Policy-Driven Governance** | `AgentPolicy` CRDs enforce input/output guardrails, token caps, PII masking, prompt-injection detection, and allowed model lists. |
| 7 | **Multi-Tenant Isolation** | `AgentTenant` CRDs provision isolated namespaces, resource quotas, RBAC, and network policies per team. |
| 8 | **Workflow Engine** | `AgentWorkflow` CRDs define DAG-based multi-agent pipelines with dependency chains, parallel execution, and human-in-the-loop approval gates. |
| 9 | **Continuous Evaluation** | `AgentEval` CRDs run scheduled test suites measuring relevance, toxicity, latency, and exact-match thresholds against live agents. |
| 10 | **Run Intelligence Layer** | Semantic event indexing, deterministic anomaly detection, system agents for root-cause analysis, and analytics APIs for agent topology and spend visibility. |

---

## Comparison

| Capability | KubeSynapse | LangChain | AutoGen | CrewAI | Dify | LangFlow |
|------------|-----------|-----------|---------|--------|------|----------|
| **Kubernetes Native** | Yes (Operator + CRDs) | No | No | No | Partial | Partial |
| **Self-Hosted** | Yes (Full stack via Helm) | Library only | Partial | Partial | Yes | Yes |
| **Multi-Agent Orchestration** | Yes (CRD-based DAGs) | LangGraph | Code-based | Code-based | Yes | Yes |
| **A2A Protocol (JSON-RPC/SSE)** | Yes (Native gateway) | No | No | No | No | No |
| **MCP Tool Ecosystem** | Yes (11 sidecars) | Requires setup | Requires setup | Requires setup | Limited | Limited |
| **Policy & Governance** | Yes (CRD guardrails) | Manual | Manual | Manual | Basic | Basic |
| **Human-in-the-Loop** | Yes (AgentApproval CRD) | External | External | External | Basic | Basic |
| **Eval Framework** | Yes (Built-in CRD) | External | External | External | Limited | Limited |
| **Live Observability & Artifacts** | Yes (trace replay + ZIP) | No | No | No | Limited | Limited |
| **Primary Model** | Platform | Library | Framework | Framework | Platform | Platform |

---

## Screenshots

> **Dashboard Overview** — Real-time agent status, tenant utilization, and system health.
> ![KubeSynapse Dashboard](docs/screenshots/dashboard-overview.png)

> **Agent Workflow Editor** — Visual DAG builder for multi-agent pipelines with approval gates.
> ![Workflow Editor](docs/screenshots/workflow-editor.png)

> **Policy Governance Panel** — Guardrail configuration, blocked patterns, and audit logs.
> ![Policy Panel](docs/screenshots/policy-governance.png)

---

## Contributing

We welcome contributions. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full guide.

```bash
# Fork, clone, and build
git clone https://github.com/your-username/kubesynapse.ai.git
cd kubesynapse.ai

# Run the test suite
make test

# Lint Python services
make lint

# Install with the example cluster values
helm upgrade --install kubesynapse ./charts/kubesynapse -f ./deploy/values.cluster.example.yaml
```

---

## License

KubeSynapse is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
