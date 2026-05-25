<p align="center">
  <picture>
    <img alt="KubeSynapse" src="https://img.shields.io/badge/KubeSynapse-Kubernetes--native%20AI%20operations%20platform-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" height="48">
  </picture>
</p>

<h1 align="center">KubeSynapse</h1>

<p align="center">
  <strong>Ship AI agents the same way you ship everything else — as Kubernetes resources.</strong>
</p>

<p align="center">
  <a href="https://github.com/ykbytes/kubesynapse.ai/stargazers"><img src="https://img.shields.io/github/stars/ykbytes/kubesynapse.ai?style=flat&color=326CE5" alt="Stars"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/ykbytes/kubesynapse.ai?style=flat&color=326CE5" alt="Apache 2.0"></a>
  <a href="https://github.com/ykbytes/kubesynapse.ai/releases"><img src="https://img.shields.io/github/v/release/ykbytes/kubesynapse.ai?style=flat&color=326CE5" alt="Release"></a>
  <a href="https://kubernetes.io/"><img src="https://img.shields.io/badge/Kubernetes-native-326CE5?style=flat&logo=kubernetes" alt="Kubernetes native"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%2B-326CE5?style=flat&logo=python" alt="Python 3.11+"></a>
  <a href="https://react.dev/"><img src="https://img.shields.io/badge/React-18-326CE5?style=flat&logo=react" alt="React 18"></a>
</p>

<p align="center">
  <a href="#-quickstart">Quickstart</a>
  &nbsp;|&nbsp;
  <a href="#-features">Features</a>
  &nbsp;|&nbsp;
  <a href="#-architecture">Architecture</a>
  &nbsp;|&nbsp;
  <a href="#-cli">CLI</a>
  &nbsp;|&nbsp;
  <a href="#-docs">Docs</a>
</p>

<br>

KubeSynapse is an open-source, self-hosted AI agent platform that runs entirely inside your Kubernetes cluster. Agents, workflows, policies, tool integrations, and observability are all Kubernetes CRDs — reconciled into isolated `StatefulSets`, worker `Jobs`, and live dashboards by the platform operator.

**No local-only toy frameworks. No mandatory SaaS control plane. Just your cluster, your models, your rules.**

<br>

---

## ⚡ Quickstart

### Kind (local, under 5 minutes)

```powershell
# 1. Deploy the platform (sets admin password)
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev -Namespace kubesynapse -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"

# 2. Port-forward the gateway and UI (run each in a separate terminal)
kubectl port-forward svc/kubesynapse-api-gateway -n kubesynapse 8080:8080
kubectl port-forward svc/kubesynapse-web-ui -n kubesynapse 3000:80

# 3. Configure an LLM API key (required before invoking agents)
#    Open the UI → Settings → Providers, or set via kubectl:
#    (PowerShell)
kubectl patch secret kubesynapse-llm-api-keys -n kubesynapse `
  --patch "{`"data`":{`"OPENAI_API_KEY`":`"$([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('sk-your-key')))`"}}"
#    (bash)
#    kubectl patch secret kubesynapse-llm-api-keys -n kubesynapse -p '{"data":{"OPENAI_API_KEY":"'$(echo -n 'sk-your-key' | base64)'"}}'

# 4. Deploy the sample policy and agent
kubectl apply -f examples/sample-policy.yaml
kubectl apply -f examples/sample-agent.yaml

# 5. Open the UI and log in
open http://localhost:3000
```

### Default Credentials

After install, log in with:
- **Username:** `admin`
- **Password:** The value you passed to `-AdminPassword` (e.g., `KubesynapseAdmin9!`)

Forgot your password? The deploy script prints it on success. You can also retrieve it:

```bash
kubectl get secret kubesynapse-platform-secrets -n kubesynapse \
  -o jsonpath='{.data.AUTH_BOOTSTRAP_ADMIN_PASSWORD}' | base64 -d
```

### Helm (any cluster)

```bash
helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace \
  --set platformSecrets.native.litellmMasterKey=$(openssl rand -hex 32) \
  --set platformSecrets.native.apiGatewaySharedToken=$(openssl rand -hex 32) \
  --set platformSecrets.native.databasePassword=$(openssl rand -hex 16) \
  --set platformSecrets.native.jwtSecret=$(openssl rand -hex 32) \
  --set platformSecrets.native.authBootstrapAdminPassword="YourStrongPassword!" \
  --set platformSecrets.native.openaiApiKey="sk-your-openai-key"
```

After install, log in at `http://<your-cluster>:8080` with username `admin` and the password you set above.

> **Note:** Local auth requires a password of at least 8 characters. Include an LLM API key (`openaiApiKey` or `openrouterApiKey`) or agents won't be able to invoke models.

<br>

---

## 🚀 Features

### Define agents as code

Describe your AI agent in a YAML manifest — model, system prompt, tools, and policy — and `kubectl apply` it. The operator provisions an isolated `StatefulSet` with persistent storage, network policies, and optional MCP sidecars. No manual pod management.

### Hardened by default

Agent runtimes ship with defense-in-depth across four layers:

- **Runtime Isolation** — Plugin auto-discovery disabled. No dynamic code execution from config files.
- **Immutable Baseline** — Hardened security policy enforced at the config layer. Agents cannot relax restrictions.
- **Traffic Enforcement** — All model calls routed through audited proxy. Provider redirect attacks prevented.
- **Full Audit Trail** — Request tracing with `x-request-id` propagation. Structured JSON logs ready for your SIEM.

[Learn more about the security model →](docs/architecture-overview.md#10-security-model)

- 12 CRDs model every platform concern: agents, workflows, policies, approvals, tenants, MCP connections, webhooks, and observability targets
- OpenCode runtime for production workloads (Pi and Mistral Vibe available in alpha)
- Model calls proxy through LiteLLM with cost tracking and fallback
- Persistent workspace state on PVC with session checkpointing

### Orchestrate multi-step workflows

Define DAGs of agent steps with dependencies, approval gates, retries, timeouts, and conditional branching. The operator topologically sorts steps and dispatches them in parallel waves through worker Jobs.

- Step types: `agent`, `loop`, `conditional`, `review`
- Human-in-the-loop approval gates pause execution until a human approves
- Loop steps with circuit breakers and exit conditions
- Auto-retry with configurable failure classes

### Chat, collaborate, and observe

A full web console with chat workbench, workflow composer, and execution observatory. Stream agent responses in real-time via SSE. Trace every LLM call, tool invocation, and token spent.

- Chat Workbench with saved sessions and memory-backed continuity
- Workflow Composer with visual DAG editing and live execution state
- Execution Observatory: timeline, step detail, LLM/tool call inspection, HTML/JSON export
- System agents auto-analyze failures, anomalies, and cost spikes

### Secure and govern

Security is built in, not bolted on. Every layer — network, container, token, and policy — is enforced by default.

- Constant-time token comparison, argon2id password hashing
- Per-agent network policies (deny-all egress, explicit allows)
- Non-root runtimes with read-only root filesystem and dropped capabilities
- Rate limiting on login and agent invocation
- Audit logging with structured errors and correlation IDs

### Operate with a single CLI

`agentctl` covers every platform operation. Manage agents, trigger workflows, stream logs, query observatory data, and administer users — all from the terminal.

- 82 commands across 13 command groups
- Tab-completion for bash, zsh, fish, and PowerShell
- Live Kind cluster smoke tests with real resource validation
- Streaming invoke, live events, and interactive chat sessions

### Run in production

Schema changes use Alembic migrations, not ad-hoc `CREATE TABLE` calls. Backups are automated via CronJob. Logs are structured JSON with standard fields for aggregation.

- Alembic-powered database migrations with auto-generated baseline
- PostgreSQL backup CronJob with PVC and S3 support, retention cleanup, documented restore
- Structured JSON logging (`component`, `namespace`, `agent_name`, `request_id`, `duration_ms`)
- Correlation IDs flow through invoke, logs, and error responses

<details>
<summary><strong>The 12 CRDs installed by the chart</strong></summary>

| Kind | Purpose |
| --- | --- |
| `AIAgent` | Agent definition and runtime configuration |
| `AgentPolicy` | Guardrails, MCP/tool policy, memory, outbound A2A policy |
| `AgentApproval` | Human approval records for gated actions |
| `AgentWorkflow` | Multi-step workflow DAGs |
| `AgentTenant` | Namespace isolation and tenant metadata |
| `McpConnection` | Saved MCP connection definitions |
| `WebhookReceiver` | Signed inbound webhook configuration |
| `WorkflowTrigger` | Trigger metadata and history for workflow integrations |
| `ConnectorPlugin` | Observability connector definition |
| `ObservationTarget` | Observability target definition |
| `ObservationPolicy` | Observability evaluation policy |
| `ObservationReport` | Observability report output |

</details>

### Bundled MCP Sidecars

`code-exec` · `web-search` · `browser-automation` · `database` · `git` · `github` · `kubernetes-ops` · `messaging` · `rag` · `documents`

### UI Surfaces

**Chat Workbench** — direct agent interaction, SSE streaming, saved sessions, memory-backed continuity. **Team View** — explicit agent-to-agent collaboration. **Workflow Composer** — visual DAG editing, run history, inline approvals. **Execution Observatory** — execution lists, timelines, step inspection, LLM/tool calls, HTML/JSON export. **Catalog** — MCP registry and skills. **Intelligence** — observability resources and collector-driven flows.

<br>

---

## 🏗 Architecture

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'fontSize': '13px' }}}%%
flowchart TB
    UI["🖥️ Web UI"]:::c
    CLI["⌨️ agentctl"]:::c
    EXT["🔗 External Apps"]:::c

    GW("⚡ API Gateway
    FastAPI · Auth · CRUD · SSE"):::g

    K8S{{"☸️ Kubernetes API
    12 CRDs"}}:::k

    OP("🔧 Operator
    Reconcile · Provision"):::o

    SEC["🛡️ Security Layers
    Plugin Isolation · NetworkPolicy"]:::sec

    OC("🤖 OpenCode Runtime
    StatefulSet · Sessions · Stream"):::r
    JOB("📦 Workflow Jobs
    DAG step execution"):::w

    MCP("🔌 MCP Sidecars
    10 bundled"):::s
    PVC[("💾 State PVC")]:::d

    LLM("🧪 LiteLLM
    Model proxy"):::shared
    PG[("🗄️ Postgres
    Auth · Memory · Traces")]:::shared
    REDIS[("⚡ Redis
    Cache · Sessions")]:::shared
    QDRANT[("🔍 Qdrant
    Semantic memory")]:::shared
    NATS("📡 NATS
    Async messaging"):::shared

    TRACE("📊 Observatory
    Trace store · Timeline"):::intel
    SIGNAL("🚨 Signal Watch
    Anomaly detection"):::intel
    SYS("🧪 System Agents
    Auto-analysis"):::intel

    UI -->|"HTTPS /api/*"| GW
    CLI -->|"REST + SSE"| GW
    EXT -->|"Webhooks"| GW
    GW -->|"CRUD (CustomObjectsApi)"| K8S
    GW -->|"SQLAlchemy"| PG
    GW -->|"Agent cache"| REDIS
    K8S -->|"Watch CRDs (Kopf)"| OP
    OP ==>|"Provisions StatefulSet"| OC
    OP -->|"Creates worker Job"| JOB
    OP -.->|"Immutable config"| SEC
    OC -->|"localhost sidecar"| MCP
    OC -->|"Workspace · Checkpoints"| PVC
    OC -->|"HTTPS /v1/chat/completions"| LLM
    OC -->|"Vector search"| QDRANT
    LLM -->|"Response cache"| REDIS
    OC -.->|"POST runtime-events"| TRACE
    JOB -.->|"POST runtime-events"| TRACE
    TRACE -->|"SQL anomaly queries"| SIGNAL
    SIGNAL -.->|"Invokes for analysis"| SYS

    classDef c fill:#1a2332,stroke:#326CE5,stroke-width:2px,color:#7baaf7
    classDef g fill:#1a1a3e,stroke:#7c3aed,stroke-width:3px,color:#c4b5fd
    classDef k fill:#0d2137,stroke:#326CE5,stroke-width:3px,color:#93c5fd
    classDef o fill:#1a2332,stroke:#f59e0b,stroke-width:2px,color:#fcd34d
    classDef r fill:#0d3320,stroke:#10b981,stroke-width:2px,color:#6ee7b7
    classDef w fill:#1a2332,stroke:#6366f1,stroke-width:2px,color:#a5b4fc
    classDef s fill:#1a2332,stroke:#ec4899,stroke-width:2px,color:#f9a8d4
    classDef d fill:#1a2332,stroke:#14b8a6,stroke-width:2px,color:#99f6e4
    classDef shared fill:#1a1a2e,stroke:#64748b,stroke-width:2px,color:#94a3b8
    classDef intel fill:#2d1b4e,stroke:#a855f7,stroke-width:2px,color:#d8b4fe
    classDef sec fill:#1a2e1a,stroke:#22c55e,stroke-width:3px,color:#86efac
```
> **Layers:** 🔵 Clients → 🟣 Gateway → 🔵 K8s API → 🟡 Operator → 🟢 Runtimes → ⚫ Shared Services → 🟣 Intelligence → 🟢 Security
>
> **Data flow:** The gateway reads/writes CRDs via the Kubernetes API and persists app state to Postgres + Redis. The operator watches CRDs and provisions isolated StatefulSets. Each runtime streams responses via SSE, calls models through LiteLLM, and emits trace events to the Observatory. Signal Watch runs SQL anomaly detection and invokes system agents for AI-powered analysis.

<br>

---

## 💻 CLI — `agentctl`

```bash
pip install -e ./cli
```

`agentctl` is the command-line interface to KubeSynapse. It covers every platform operation:

### Shell completion (tab-autocomplete)

**Install once, use everywhere:**

```bash
# bash (~/.bashrc)
eval "$(agentctl completion bash)"

# zsh (~/.zshrc)
eval "$(agentctl completion zsh)"

# fish
agentctl completion fish > ~/.config/fish/completions/agentctl.fish

# PowerShell ($PROFILE)
agentctl completion pwsh | Out-String | Invoke-Expression
```

After installing, tab-completion works for all commands, subcommands, and options:

```
agentctl <TAB>          -> health, apply, invoke, logs, agents, workflows, chat...
agentctl agents <TAB>   -> list, show, create, update, delete, invoke, logs...
agentctl --<TAB>        -> --gateway, --profile, --namespace, --output, --token...
```

### Quick workflow

```bash
# Login and configure (use the same password you set at deploy time)
agentctl --gateway-url http://localhost:8080 auth login -u admin -p "<password>"
export AGENT_GATEWAY_TOKEN="<token-from-login-output>"
export AGENT_GATEWAY_URL="http://localhost:8080"

# CRUD
agentctl agents list
agentctl agents show research-assistant

# Invoke (streaming)
agentctl agents invoke research-assistant "What is Kubernetes?" --stream

# Create a new agent from YAML
agentctl agents create -f examples/sample-opencode-agent.yaml

# Workflows
agentctl workflows list
agentctl workflows trigger feature-pipeline
agentctl workflows status feature-pipeline

# Observatory
agentctl observatory metrics --window 24h
agentctl observatory traces --limit 10
agentctl observatory alerts --all

# Admin
agentctl admin users
agentctl admin user-create --username dev --password "Str0ngPass!" --role operator
```

PowerShell note: use `$env:AGENT_GATEWAY_TOKEN="<token>"` instead of `export`.

Read [`cli/README.md`](cli/README.md) for the full command surface.

<br>

---

## 📁 Repo Map

| Path | What it contains |
| --- | --- |
| [`api-gateway/`](api-gateway/) | FastAPI backend: auth, CRUD, invoke, chat, A2A, webhooks, observability |
| [`operator/`](operator/) | Kopf operator, manifest builders, worker orchestration, trace emission |
| [`opencode-runtime/`](opencode-runtime/) | Default AI agent runtime |
| [`pi-runtime/`](pi-runtime/) | Pi runtime bridge (alpha) |
| [`vibe-runtime/`](vibe-runtime/) | Mistral Vibe runtime bridge (alpha) |
| [`web-ui/`](web-ui/) | React 18 + Vite + Tailwind v4 console |
| [`mcp-sidecars/`](mcp-sidecars/) | Bundled MCP sidecars (10 tools) |
| [`cli/`](cli/) | `agentctl` CLI with shell completion |
| [`charts/kubesynapse/`](charts/kubesynapse/) | Main Helm chart (12 CRDs) |
| [`deploy/`](deploy/) | Environment overlays and deployment notes |
| [`examples/`](examples/) | Sample CRDs, workflows, and demo bundles |
| [`docs/`](docs/) | Architecture, runtime contract, operations, walkthrough |

<br>

---

## 📚 Docs & Guides

| Topic | Link |
| --- | --- |
| Current architecture overview | [`docs/architecture-overview.md`](docs/architecture-overview.md) |
| Full architecture reference | [`docs/architecture.md`](docs/architecture.md) |
| Current implementation walkthrough | [`docs/walkthrough.md`](docs/walkthrough.md) |
| Runtime API contract | [`docs/runtime-api-spec.md`](docs/runtime-api-spec.md) |
| Execution Observatory & run intelligence | [`docs/observability-explained.md`](docs/observability-explained.md) |
| Getting started guide | [`docs/getting-started.md`](docs/getting-started.md) |
| Installation & operations | [`INSTALL.md`](INSTALL.md) |
| Helm chart guide | [`charts/kubesynapse/README.md`](charts/kubesynapse/README.md) |
| Deployment guide | [`deploy/README.md`](deploy/README.md) |
| API reference | [`docs/api-reference.md`](docs/api-reference.md) |
| Troubleshooting | [`docs/troubleshooting.md`](docs/troubleshooting.md) |

<br>

---

## 🔧 Development

```bash
# All tests
make test

# Linting
make lint          # Ruff + mypy
make helm-lint     # Helm validation

# UI build
make ui-build

# Component tests
cd api-gateway && python -m pytest tests/ -v
cd operator && python -m pytest tests/ -v
cd cli && python -m pytest tests/ -v -q
cd web-ui && npm run build
```

Windows note: the root `Makefile` uses POSIX shell constructs. Use Git Bash, WSL, or invoke component commands directly in PowerShell.

### Local Kind development

```bash
# Build and load images (use :dev tag matching values.local-images.example.yaml)
docker build -t localhost/kubesynapse/kubesynapse-api-gateway:dev api-gateway/
docker build -t localhost/kubesynapse/kubesynapse-operator:dev operator/
docker build -t localhost/kubesynapse/kubesynapse-web-ui:dev web-ui/
docker build -t localhost/kubesynapse/kubesynapse-opencode-rt:dev opencode-runtime/
kind load docker-image localhost/kubesynapse/kubesynapse-api-gateway:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-operator:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-web-ui:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-opencode-rt:dev --name kubesynapse-dev
kubectl rollout restart deployment/kubesynapse-api-gateway -n kubesynapse
kubectl rollout restart deployment/kubesynapse-operator -n kubesynapse
kubectl rollout restart deployment/kubesynapse-web-ui -n kubesynapse

### CLI tests against live Kind

```bash
agentctl --profile kind health
agentctl --profile kind agents list
agentctl --profile kind agents invoke cli-e2e-agent "Reply with: smoke ok"
cd cli && python -m pytest tests/ -v -q
```

<br>

---

## 🤝 Contributing

KubeSynapse is Apache 2.0 licensed and welcomes contributions.

- Start with [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Repo-specific agent guidance in [`AGENTS.md`](AGENTS.md)
- Security disclosures: [`SECURITY.md`](SECURITY.md)

<br>

## 📄 License

[Apache License 2.0](LICENSE)
