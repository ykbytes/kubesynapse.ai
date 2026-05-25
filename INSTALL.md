# KubeSynapse — Installation, Usage & Operations Guide

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
  - [Architecture](#architecture)
  - [Control Plane](#control-plane)
  - [Data Plane](#data-plane)
  - [Custom Resources](#custom-resources)
  - [Request Flow](#request-flow)
- [Prerequisites](#prerequisites)
- [Quick Start — DockerHub Images](#quick-start--dockerhub-images)
- [Quick Start — Local Development (Kind)](#quick-start--local-development-kind)
- [Production Deployment](#production-deployment)
  - [1. Build Container Images](#1-build-container-images)
  - [2. Push to Registry](#2-push-to-registry)
  - [3. Configure values.yaml](#3-configure-valuesyaml)
  - [4. Install the Helm Chart](#4-install-the-helm-chart)
  - [5. Verify the Installation](#5-verify-the-installation)
- [Configuring Secrets](#configuring-secrets)
  - [Native Secrets (Default)](#native-secrets-default)
  - [External Secrets Operator](#external-secrets-operator)
- [Creating Your First Agent](#creating-your-first-agent)
  - [Step 1 — Create a Tenant](#step-1--create-a-tenant)
  - [Step 2 — Create a Policy](#step-2--create-a-policy)
  - [Step 3 — Deploy an Agent](#step-3--deploy-an-agent)
  - [Step 4 — Invoke the Agent](#step-4--invoke-the-agent)
- [Multi-Agent Workflows](#multi-agent-workflows)
- [Human-in-the-Loop Approvals](#human-in-the-loop-approvals)
- [Using the CLI (agentctl)](#using-the-cli-agentctl)
- [Using the Web UI](#using-the-web-ui)
- [API Reference](#api-reference)
- [MCP Tool Servers](#mcp-tool-servers)
  - [Shared Hub Servers](#shared-hub-servers)
  - [Sidecar Servers](#sidecar-servers)
- [OpenSandbox Integration](#opensandbox-integration)
- [TLS & Ingress](#tls--ingress)
- [Observability](#observability)
- [Scaling & High Availability](#scaling--high-availability)
- [Uninstalling](#uninstalling)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)

---

## Overview

This guide is the detailed install and operations reference for KubeSynapse.

For the most current deployment entry points, prefer these docs first:

- `deploy/README.md` for the current deployment paths
- `docs/architecture-overview.md` for the current platform architecture
- `docs/walkthrough.md` for the current implementation model

**KubeSynapse** is a Kubernetes-native platform for deploying, governing, and orchestrating AI agents at enterprise scale. It lets you define agents, policies, multi-agent workflows, approvals, and observability resources as Kubernetes custom resources while a Python operator reconciles them into running infrastructure.

The production runtime is OpenCode. Pi and Mistral Vibe are available in alpha but not recommended for production workloads. Older references in the repository to LangGraph, Goose, or Codex describe earlier architecture phases rather than the primary runtime paths used by the current code.

Key capabilities:

- **Declarative agent management** via CRDs (`AIAgent`, `AgentPolicy`, `AgentTenant`, `AgentWorkflow`, `AgentApproval`)
- **Per-agent isolation** — each agent runs as its own StatefulSet with a persistent checkpoint volume
- **File-backed skills** — `spec.skills.files` stores Markdown skill documents that steer prompts and grant scoped runtime capabilities
- **Guardrails** — prompt injection detection, PII masking, and per-request token caps
- **Human-in-the-Loop** — async approval gates for high-risk actions
- **Agent-to-agent delegation** — explicit A2A calls with policy-enforced peer discovery through the gateway
- **Multi-agent workflows** — DAG-based pipelines with step dependencies
- **Model gateway** — LiteLLM proxies all LLM calls with caching (Redis) and key management
- **RAG** — Qdrant vector database integration for retrieval-augmented generation
- **MCP tool integration** — shared hub servers and per-agent sidecar tools
- **OpenSandbox** — secure code execution in isolated containers
- **Web UI & CLI** — browser dashboard and `agentctl` command-line tool

---

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Users / CI / Web UI / agentctl CLI                                     │
└───────────────┬─────────────────────────────────────────────────────────┘
                │ HTTPS
                ▼
┌───────────────────────────┐
│  Ingress / LB (optional)  │
│  <host>/api or /api       │
│  <host>/ or /             │ ← Web UI
└───────────┬───────────────┘
            │
            ▼
┌───────────────────────────┐       ┌──────────────────────────┐
│  API Gateway (FastAPI)    │──────▶│  Agent Runtime           │
│  Auth, routing, CRUD      │       │  (StatefulSet per agent) │
│  /api/agents/*/invoke     │       │  OpenCode + Guardrails   │
└───────────┬───────────────┘       │  + HITL + RAG + MCP      │
            │                       └──────┬───────────────────┘
            │                              │
   ┌────────┴────────┐         ┌──────────┼──────────────┐
   ▼                 ▼         ▼          ▼              ▼
┌──────┐  ┌──────────────┐  ┌───────┐ ┌───────┐  ┌──────────┐
│ K8s  │  │  Operator     │  │LiteLLM│ │Qdrant │  │MCP Tools │
│ API  │  │  (Kopf)       │  │Gateway│ │Vector │  │(hub or   │
│      │  │  + Workers    │  │       │ │  DB   │  │ sidecar) │
└──────┘  └──────────────┘  └───┬───┘ └───────┘  └──────────┘
                                │
                         ┌──────┴──────┐
                         ▼             ▼
                    ┌────────┐   ┌──────────┐
                    │ Redis  │   │ External │
                    │ Cache  │   │ LLM APIs │
                    └────────┘   └──────────┘
```

### Control Plane

| Component | What it does |
|-----------|-------------|
| **Operator** (Kopf) | Watches CRDs → creates namespaces, StatefulSets, Services, PVCs, RBAC, NetworkPolicies, and worker Jobs |
| **Worker Jobs** | Execute workflow DAG steps and evaluation test suites in short-lived Kubernetes Jobs with artifact PVCs |
| **Helm Chart** | Installs all CRDs, platform services, RBAC, and operator deployment |

### Data Plane

| Component | What it does |
|-----------|-------------|
| **API Gateway** | Authenticates callers (shared token or OIDC), routes requests to the correct agent runtime, exposes CRUD + invoke + streaming endpoints |
| **Agent Runtime** | Per-agent FastAPI process running the OpenCode execution surface with session persistence, guardrails, HITL approval, RAG retrieval, and MCP tool calls |
| **LiteLLM** | Central model proxy — routes to OpenAI, Anthropic, Azure, etc. with key management and Redis-backed caching |
| **Qdrant** | Vector database for RAG document retrieval |
| **Redis** | Backs LiteLLM response caching |
| **NATS** | Message bus (foundation for future A2A messaging) |

### Custom Resources

| CRD | Scope | Purpose |
|-----|-------|---------|
| `AIAgent` | Namespaced | Define an agent: model, system prompt, policy, MCP tools, storage |
| `AgentPolicy` | Namespaced | Guardrail rules, per-request token caps, allowed models, MCP access control |
| `AgentTenant` | Cluster | Namespace isolation, resource quotas, allowed models, admin users |
| `AgentWorkflow` | Namespaced | Multi-step agent DAGs with dependencies and approval gates |
| `AgentApproval` | Namespaced | Human approval requests created automatically by the runtime |

### Request Flow

1. Client sends `POST /api/v1/agents/{name}/invoke` with a prompt and bearer token
2. API Gateway authenticates the token, resolves the agent's runtime Service
3. Gateway forwards the request to the agent runtime's `/invoke` endpoint
4. Runtime applies **input guardrails** (prompt injection check, blocked patterns, token limits)
5. Runtime checks if **HITL approval** is required → creates an `AgentApproval` CR if needed → pauses
6. Runtime executes the **OpenCode request flow**: system prompt assembly → optional RAG retrieval → LLM/tool loop → output
7. Runtime applies **output guardrails** (PII masking, output patterns, token limits)
8. Response returned to client with the agent's answer, thread ID, and status

---

## Quick Start — DockerHub Images

The fastest way to get running. Pre-built platform and sidecar images are published to `docker.io/kubesynapse`. No build step required.

### Prerequisites

- Kubernetes 1.25+ cluster (Kind, Minikube, Docker Desktop, managed cloud)
- `helm` 3.12+
- `kubectl` configured for your cluster
- An LLM API key (OpenAI, Anthropic, or any LiteLLM-supported provider)

### 1. Copy the example values file

Create a local working copy of the public cluster example:

```bash
cp ./deploy/values.cluster.example.yaml ./deploy/values.cluster.yaml
```

### 2. Optional: create an image-pull secret

If your registry requires authentication, create a pull secret first:

```bash
kubectl create secret docker-registry dockerhub-regcred \
  --docker-username=YOUR_DOCKERHUB_USERNAME \
  --docker-password=YOUR_DOCKERHUB_TOKEN \
  --docker-email=you@example.com
```

### 3. Set your platform secrets

Edit `deploy/values.cluster.yaml` and fill in your keys under `platformSecrets.native`:

```yaml
platformSecrets:
  mode: native
  native:
    openaiApiKey: "sk-your-openai-key"
    anthropicApiKey: ""                  # optional
    litellmMasterKey: "replace-with-a-strong-random-string"
    apiGatewaySharedToken: "my-secure-bearer-token"
```

> **Never commit real keys.** Keep the edited file local, or pass sensitive values through your deployment pipeline.

### 4. Deploy

```bash
helm upgrade --install KubeSynapse ./charts/kubesynapse \
  --namespace kubesynapse \
  --create-namespace \
  -f ./deploy/values.cluster.yaml
```

### 5. Verify pods

```bash
kubectl get pods -w
```

Expected pods once everything is ready:

| Pod prefix | Description |
|---|---|
| `kubesynapse-operator-*` | Operator (2 replicas for HA) |
| `kubesynapse-api-gateway-*` | API Gateway |
| `KubeSynapse-litellm-*` | LiteLLM model proxy |
| `KubeSynapse-redis-*` | Redis cache |
| `KubeSynapse-qdrant-*` | Qdrant vector database |
| `KubeSynapse-nats-*` | NATS message bus |
| `kubesynapse-web-ui-*` | Web dashboard |

### 6. Port-forward and test

```bash
# API Gateway
kubectl port-forward svc/kubesynapse-api-gateway 8080:8080
curl http://localhost:8080/api/v1/health

# Web UI (open in browser)
kubectl port-forward svc/kubesynapse-web-ui 3000:80
# Visit http://localhost:3000
```

### 6. Apply a sample agent

```bash
kubectl apply -f examples/sample-policy.yaml
kubectl apply -f examples/sample-agent.yaml

# Watch operator reconcile it
kubectl logs -l app=operator -f

# Once "research-assistant" StatefulSet is running:
curl -X POST http://localhost:8080/api/v1/agents/research-assistant/invoke \
  -H "Authorization: Bearer my-secure-bearer-token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is Kubernetes?"}'
```

#### Image tag and registry reference

`deploy/values.cluster.example.yaml` pins the published image repositories and tags used by the current public install path.
All default images live under `docker.io/kubesynapse` except LiteLLM:

| Image | Description |
|---|---|
| `kubesynapse/kubesynapse-operator` | Kopf-based operator + worker |
| `kubesynapse/kubesynapse-opencode-rt` | OpenCode HTTP adapter |
| `kubesynapse/kubesynapse-api-gateway` | FastAPI gateway |
| `kubesynapse/kubesynapse-web-ui` | React web console |
| `kubesynapse/mcp-code-exec` | Code execution MCP sidecar |
| `kubesynapse/mcp-web-search` | Web search MCP sidecar |
| `kubesynapse/mcp-documents` | Document processing MCP sidecar |
| `kubesynapse/mcp-browser` | Browser automation MCP sidecar |
| `kubesynapse/mcp-database` | Database query MCP sidecar |
| `kubesynapse/mcp-git` | Git operations MCP sidecar |
| `kubesynapse/mcp-kubernetes` | Kubernetes ops MCP sidecar |
| `kubesynapse/mcp-messaging` | Messaging/NATS MCP sidecar |
| `kubesynapse/mcp-rag` | RAG/Qdrant MCP sidecar |
| `kubesynapse/mcp-github-adapter` | GitHub MCP hub adapter |

---

## Prerequisites

| Requirement | Minimum version | Notes |
|-------------|----------------|-------|
| **Kubernetes cluster** | 1.25+ | Kind, Minikube, Docker Desktop, EKS, AKS, GKE |
| **Helm** | 3.12+ | Package manager for the chart |
| **kubectl** | 1.25+ | Cluster management |
| **Docker** (or Podman) | 20.10+ | Building container images |
| **Container registry** | — | Docker Hub, GHCR, ECR, ACR, or local registry |
| **LLM API key** | — | OpenAI, Anthropic, Azure OpenAI, or any LiteLLM-supported provider |

Optional:

| Requirement | For |
|-------------|-----|
| **Python 3.11+** | Installing the `agentctl` CLI |
| **Node.js 18+** | Building the Web UI |
| **External Secrets Operator** | Production secrets management (Vault, Azure KV, AWS SM) |
| **Ingress controller** | Optional external access via Ingress; any controller works |
| **cert-manager** | Automatic TLS certificates |
| **gVisor (runsc)** | Kernel-level sandbox isolation |

---

## Quick Start — Local Development (Kind)

This guide builds images locally and loads them directly into a Kind cluster (no registry needed).
To skip the build step entirely, see [Quick Start — DockerHub Images](#quick-start--dockerhub-images) above.

Recommended local path on Windows and for repeatable re-installs:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"
```

The script creates or reuses the Kind cluster, builds and loads the required local images,
applies both `deploy/values.local-images.example.yaml` and
`deploy/values.kind.quickstart.yaml`, injects `catalog/skills-catalog.json`, and
reconciles the persisted PostgreSQL password on repeat upgrades so local installs stay
repeatable. Use `-SkipBuild` and/or `-SkipLoad` on subsequent runs when the images are
already present in Docker and Kind.

The manual steps below are still useful when you need to customize the build, load, or
Helm phases individually.

### 1. Create a Kind cluster

```bash
kind create cluster --name kubesynapse-dev
```

### 2. Build the platform images

```bash
# From the repository root (builds the platform images and bundled sidecars)
make docker-build REGISTRY=localhost/kubesynapse VERSION=dev CONTAINER_CLI=docker
# Produces platform images such as:
#   localhost/kubesynapse/kubesynapse-operator:dev
#   localhost/kubesynapse/kubesynapse-opencode-rt:dev
#   localhost/kubesynapse/kubesynapse-api-gateway:dev
#   localhost/kubesynapse/kubesynapse-web-ui:dev
#   localhost/kubesynapse/kubesynapse-pi-rt:dev
#   localhost/kubesynapse/kubesynapse-vibe-rt:dev
#   localhost/kubesynapse/mcp-code-exec:dev
#   localhost/kubesynapse/mcp-web-search:dev
#   localhost/kubesynapse/mcp-documents:dev
#   ... (all 10 mcp-* sidecars)
```

Or build individual components with Docker:

```bash
docker build -t localhost/kubesynapse/kubesynapse-operator:dev ./operator
docker build -t localhost/kubesynapse/kubesynapse-opencode-rt:dev ./opencode-runtime
docker build -t localhost/kubesynapse/kubesynapse-api-gateway:dev ./api-gateway
docker build -t localhost/kubesynapse/kubesynapse-web-ui:dev ./web-ui
```

The bundled MCP sidecars build from sub-directories under `./mcp-sidecars/`, one Dockerfile each.
The Makefile builds all of them in one pass and is the recommended approach.

### 3. Load images into Kind

```bash
mkdir -p dist
docker save -o dist/kubesynapse-operator.tar localhost/kubesynapse/kubesynapse-operator:dev
docker save -o dist/kubesynapse-opencode-rt.tar localhost/kubesynapse/kubesynapse-opencode-rt:dev
docker save -o dist/kubesynapse-api-gateway.tar localhost/kubesynapse/kubesynapse-api-gateway:dev
docker save -o dist/kubesynapse-web-ui.tar localhost/kubesynapse/kubesynapse-web-ui:dev
kind load image-archive dist/kubesynapse-operator.tar --name kubesynapse-dev
kind load image-archive dist/kubesynapse-opencode-rt.tar --name kubesynapse-dev
kind load image-archive dist/kubesynapse-api-gateway.tar --name kubesynapse-dev
kind load image-archive dist/kubesynapse-web-ui.tar --name kubesynapse-dev

docker build -f deploy/litellm/Dockerfile -t docker.io/litellm/litellm:v1.82.3-stable deploy/litellm
kind load docker-image docker.io/litellm/litellm:v1.82.3-stable --name kubesynapse-dev
```

### 4. Set your LLM API key

Edit `charts/kubesynapse/values.yaml`:

```yaml
platformSecrets:
  mode: native
  native:
    openaiApiKey: "sk-your-real-openai-key"            # optional
    openrouterApiKey: "sk-or-your-openrouter-key"      # optional
    anthropicApiKey: "sk-ant-your-anthropic-key"       # optional
    litellmMasterKey: "changeme"
    apiGatewaySharedToken: "my-secret-bearer-token"    # replace with a strong random string
```

  ### 5. Install the Helm chart with the local-image override

```bash
  helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace \
    -f ./deploy/values.local-images.example.yaml \
    -f ./deploy/values.kind.quickstart.yaml \
    --set-file skillsCatalog.catalogJson=./catalog/skills-catalog.json
```

  `deploy/values.local-images.example.yaml` remaps the core platform images to the
  `localhost/kubesynapse/*:dev` tags shown above and keeps LiteLLM pinned to the
  fixed `docker.io/litellm/litellm:v1.82.3-stable` image. Load that LiteLLM image
  into the cluster cache alongside the locally built platform images. Extend it with
  `mcpToolSidecars` entries only if your agents use locally built sidecar images
  instead of the default published ones.

  `deploy/values.kind.quickstart.yaml` disables optional local-only friction points such as
  MCP Hub, system agents, PodDisruptionBudgets, and NetworkPolicies so a single-node Kind
  cluster can converge more reliably.

  If your local cluster cannot pull `localhost/kubesynapse/*:dev` images directly,
  load or push those images into a registry that the cluster nodes can reach before
  running the Helm install.

  ### 6. Verify pods are running

```bash
kubectl get pods -w
```

Expected pods:

| Pod prefix | Description |
|---|---|
| `kubesynapse-operator-*` | Operator (HA pair) |
| `kubesynapse-api-gateway-*` | API Gateway |
| `KubeSynapse-litellm-*` | LiteLLM model proxy |
| `KubeSynapse-redis-*` | Redis cache |
| `KubeSynapse-qdrant-*` | Qdrant vector database |
| `KubeSynapse-nats-*` | NATS message bus |
| `kubesynapse-web-ui-*` | Web dashboard |

### 7. Port-forward and test

```bash
# API Gateway
kubectl port-forward svc/kubesynapse-api-gateway 8080:8080

# Health check
curl http://localhost:8080/api/v1/health

# Web UI
kubectl port-forward svc/kubesynapse-web-ui 3000:80
# Visit http://localhost:3000
```

### 8. Deploy a sample agent

```bash
kubectl apply -f examples/sample-policy.yaml
kubectl apply -f examples/sample-agent.yaml
```

Watch the operator reconcile it:

```bash
kubectl logs -l app=operator -f
```

Once the `research-assistant` StatefulSet is running, invoke it:

```bash
curl -X POST http://localhost:8080/api/v1/agents/research-assistant/invoke \
  -H "Authorization: Bearer my-secret-bearer-token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is Kubernetes?"}'
```

---

## Production Deployment

### 1. Build Container Images

```bash
export REGISTRY=ghcr.io/your-org
export VERSION=1.0.0

docker build -t $REGISTRY/kubesynapse-operator:$VERSION ./operator
docker build -t $REGISTRY/kubesynapse-opencode-rt:$VERSION ./opencode-runtime
docker build -t $REGISTRY/kubesynapse-api-gateway:$VERSION ./api-gateway
docker build -t $REGISTRY/kubesynapse-web-ui:$VERSION ./web-ui
docker build -t $REGISTRY/kubesynapse-pi-rt:$VERSION ./pi-runtime
docker build -t $REGISTRY/kubesynapse-vibe-rt:$VERSION ./vibe-runtime
docker build -t $REGISTRY/litellm:$VERSION -f deploy/litellm/Dockerfile deploy/litellm

# MCP sidecars (one Dockerfile per sidecar under ./mcp-sidecars/)
docker build -t $REGISTRY/mcp-code-exec:$VERSION   -f mcp-sidecars/code-exec/Dockerfile   mcp-sidecars
docker build -t $REGISTRY/mcp-web-search:$VERSION  -f mcp-sidecars/web-search/Dockerfile  mcp-sidecars
docker build -t $REGISTRY/mcp-documents:$VERSION   -f mcp-sidecars/documents/Dockerfile   mcp-sidecars
docker build -t $REGISTRY/mcp-browser:$VERSION     -f mcp-sidecars/browser/Dockerfile     mcp-sidecars
docker build -t $REGISTRY/mcp-database:$VERSION    -f mcp-sidecars/database/Dockerfile    mcp-sidecars
docker build -t $REGISTRY/mcp-git:$VERSION         -f mcp-sidecars/git/Dockerfile         mcp-sidecars
docker build -t $REGISTRY/mcp-kubernetes:$VERSION  -f mcp-sidecars/kubernetes/Dockerfile  mcp-sidecars
docker build -t $REGISTRY/mcp-messaging:$VERSION   -f mcp-sidecars/messaging/Dockerfile   mcp-sidecars
docker build -t $REGISTRY/mcp-rag:$VERSION         -f mcp-sidecars/rag/Dockerfile         mcp-sidecars
docker build -t $REGISTRY/mcp-github-adapter:$VERSION -f mcp-sidecars/github-adapter/Dockerfile mcp-sidecars
```

**Recommended:** Use the packaging script to build all images in one pass:

```bash
# PowerShell (Windows / cross-platform)
.\scripts\package-self-contained.ps1 \
  -Registry $REGISTRY \
  -Version $VERSION \
  -ContainerCli docker \
  -Push
```

This builds the platform images referenced by the chart, the optional Pi and Vibe runtimes, the fixed LiteLLM image, and all bundled MCP sidecars; it generates `kubesynapse-bundle-values.yaml` with pinned image references and optionally pushes everything to the registry.

### 2. Push to Registry

```bash
docker login ghcr.io
docker push $REGISTRY/kubesynapse-operator:$VERSION
docker push $REGISTRY/kubesynapse-opencode-rt:$VERSION
docker push $REGISTRY/kubesynapse-api-gateway:$VERSION
docker push $REGISTRY/kubesynapse-web-ui:$VERSION
docker push $REGISTRY/kubesynapse-pi-rt:$VERSION
docker push $REGISTRY/kubesynapse-vibe-rt:$VERSION
docker push $REGISTRY/litellm:$VERSION
# Push all mcp-* images the same way, or use the -Push flag on the packaging script above
```

Or use the Makefile (builds all platform images + all MCP sidecars and pushes in one call):

```bash
make docker-build docker-push REGISTRY=your-registry.example.com/ai-agents VERSION=1.0.0 CONTAINER_CLI=docker
```

### 3. Configure values.yaml

Create a production values override file (`values-prod.yaml`):

```yaml
# -- Container images --------------------------------------------------------
operator:
  replicaCount: 2
  clusterSecretStoreName: "mycompany-vault-store"
  image:
    repository: ghcr.io/your-org/kubesynapse-operator
    tag: "1.0.0"

opencodeRuntime:
  image:
    repository: ghcr.io/your-org/kubesynapse-opencode-rt
    tag: "1.0.0"
  env:
    OPENCODE_RUNTIME_CONFIG_FILES_JSON:
      opencode.json: |
        {
          "default_agent": "build"
        }
      agents/reviewer.md: |
        ---
        description: Review code conservatively
        mode: subagent
        ---
        Focus on regressions, operational risk, and missing tests.

apiGateway:
  replicaCount: 2
  image:
    repository: ghcr.io/your-org/kubesynapse-api-gateway
    tag: "1.0.0"
  ingress:
    enabled: true
    annotations: {}
  ingressClassName: "nginx"               # set to your controller or leave empty for the default class
  ingressHost: "agents.mycompany.com"
  tls:
    enabled: true
    secretName: "agents-tls"                # cert-manager or manually provisioned
  auth:
    mode: oidc                              # Use OIDC in production
    oidcIssuer: "https://login.mycompany.com"
    oidcAudience: "KubeSynapse"
    oidcJwksUrl: "https://login.mycompany.com/.well-known/jwks.json"

webUi:
  enabled: true
  image:
    repository: ghcr.io/your-org/kubesynapse-web-ui
    tag: "1.0.0"

litellm:
  image:
    repository: ghcr.io/berriai/litellm
    tag: main-latest
  config:
    model_list:
      - model_name: gpt-4
        litellm_params:
          model: openai/gpt-4
          api_key: "os.environ/OPENAI_API_KEY"
      - model_name: claude-3-sonnet
        litellm_params:
          model: anthropic/claude-3-sonnet-20240229
          api_key: "os.environ/ANTHROPIC_API_KEY"

# -- Secrets (use External Secrets in production) ----------------------------
platformSecrets:
  mode: external-secrets
  externalSecrets:
    refreshInterval: 1h
    createClusterSecretStore: false          # You manage the ClusterSecretStore

# -- MCP Hub ----------------------------------------------------------------
mcpHub:
  auth:
    bearerToken: ""                          # Pull from your secret store
    secretName: "mcp-hub-auth-secret"
  servers:
    github:
      enabled: false
      image: "ghcr.io/github/github-mcp-server:latest"
      args:
        - http
      port: 8082
      servicePort: 8000

# -- Telemetry --------------------------------------------------------------
telemetry:
  otlpEndpoint: "http://otel-collector.monitoring:4318"
```

### Google managed sign-in

For Google browser sign-in, keep the gateway in `hybrid` or `oidc` mode, set `apiGateway.publicBaseUrl` to the externally reachable HTTPS URL for the gateway, and publish one OIDC provider entry through `OIDC_PROVIDERS_JSON`. The gateway uses that base URL to derive the callback path `/api/auth/oidc/callback/<provider_id>` when `redirect_uri` is omitted.

Use the checked-in example overlay as a starting point:

```bash
helm upgrade --install KubeSynapse ./charts/kubesynapse \
  -f ./deploy/values.cluster.example.yaml \
  -f ./deploy/values.google-oidc.example.yaml
```

If you use native chart-managed secrets, populate `platformSecrets.native.oidcProvidersJson` with a JSON array like this:

```yaml
apiGateway:
  publicBaseUrl: "https://agents.example.com"
  auth:
    mode: hybrid
    localAuthEnabled: true

platformSecrets:
  mode: native
  native:
    oidcProvidersJson: >-
      [{"id":"google","name":"Google","issuer":"https://accounts.google.com","client_id":"YOUR_GOOGLE_CLIENT_ID","client_secret":"YOUR_GOOGLE_CLIENT_SECRET","scopes":["openid","email","profile"]}]
```

Register this redirect URI in Google Cloud:

```text
https://agents.example.com/api/auth/oidc/callback/google
```

If you use External Secrets instead, store the same JSON array at the secret key backing `KubeSynapse/oidc-providers-json` and keep `apiGateway.publicBaseUrl` aligned with the public gateway URL.

The chart intentionally deploys no shared MCP servers by default. The GitHub
entry above is a real upstream image reference, but the current runtime still
expects an internal `/tools/<tool>` HTTP bridge before agents can invoke a
stock MCP server successfully.

`OPENCODE_RUNTIME_CONFIG_FILES_JSON` does the same for the OpenCode adapter. It
lets the chart preseed native OpenCode files such as `opencode.json`, agent
profiles under `agents/`, plugins under `plugins/`, and Markdown skills under
`skills/` before `opencode serve` starts.

If you publish the bundled sidecars to your own registry, override the
`mcpToolSidecars` entries as well. The chart defaults now point those sidecars
at published `latest` tags, so agents can use the bundled images without extra
chart changes unless you want to pin or relocate them.

### 4. Install the Helm Chart

```bash
# Lint first
helm lint ./charts/kubesynapse -f values-prod.yaml

# Install
helm upgrade --install kubesynapse ./charts/kubesynapse \
  --namespace ai-platform \
  --create-namespace \
  -f values-prod.yaml \
  --set-file skillsCatalog.catalogJson=./catalog/skills-catalog.json
```

If `catalog/skills-catalog.json` exists, include it during Helm installs and upgrades so the API gateway serves the curated skills catalog instead of the chart default empty array.

### 5. Verify the Installation

```bash
# All platform pods running
kubectl get pods -n ai-platform

# CRDs registered
kubectl get crds | grep kubesynapse.ai

# Expected CRDs:
#   aiagents.kubesynapse.ai
#   agentpolicies.kubesynapse.ai
#   agentapprovals.kubesynapse.ai
#   agenttenants.kubesynapse.ai
#   agentworkflows.kubesynapse.ai

# Operator logs healthy
kubectl logs -n ai-platform -l app=operator --tail=50

# API Gateway reachable
kubectl port-forward -n ai-platform svc/kubesynapse-api-gateway 8080:8080
curl http://localhost:8080/api/v1/health
```

---

## Configuring Secrets

### Native Secrets (Default)

For development or simple deployments. Set values directly in `values.yaml`:

```yaml
platformSecrets:
  mode: native
  native:
    openaiApiKey: "sk-..."
    anthropicApiKey: "sk-ant-..."
    litellmMasterKey: ""                    # auto-generated if empty
    apiGatewaySharedToken: "a-strong-random-token"
```

The chart creates a Kubernetes `Secret` object from these values.

### External Secrets Operator

For production. Requires the [External Secrets Operator](https://external-secrets.io/) installed in your cluster.

```yaml
platformSecrets:
  mode: external-secrets
  externalSecrets:
    refreshInterval: 1h
    createClusterSecretStore: true           # Let the chart create a sample store

operator:
  clusterSecretStoreName: "your-vault-store"
```

The chart creates an `ExternalSecret` resource that pulls keys from your secret backend (Vault, Azure Key Vault, AWS Secrets Manager). Configure the `ClusterSecretStore` spec in the template or provide your own.

Expected secret keys in your backend:

| Remote key | Purpose |
|------------|---------|
| `KubeSynapse/openai-api-key` | OpenAI API key |
| `KubeSynapse/anthropic-api-key` | Anthropic API key |
| `KubeSynapse/litellm-master-key` | LiteLLM master key |
| `KubeSynapse/api-gateway-shared-token` | API Gateway bearer token |

---

## Creating Your First Agent

### Step 1 — Create a Tenant

Tenants provide namespace isolation, resource quotas, and model allow-lists.

```yaml
# my-tenant.yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentTenant
metadata:
  name: my-team
spec:
  tenantName: my-team
  namespace: agent-tenant-my-team
  resourceQuota:
    maxCPU: "8"
    maxMemory: "16Gi"
    maxPods: 10
  allowedModels:
    - gpt-4
    - claude-3-sonnet
  adminUsers:
    - alice@mycompany.com
```

```bash
kubectl apply -f my-tenant.yaml
```

The operator will:
1. Create the namespace `agent-tenant-my-team`
2. Apply `ResourceQuota` and `LimitRange`
3. Create a runtime `ServiceAccount` with proper RBAC
4. Create an `ExternalSecret` for the tenant's runtime secrets (LiteLLM key, etc.)

### Step 2 — Create a Policy

Policies define guardrails and access control.

```yaml
# my-policy.yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentPolicy
metadata:
  name: standard-policy
  namespace: agent-tenant-my-team
spec:
  inputGuardrails:
    blockPromptInjection: true
    blockedPatterns:
      - "password|secret|credential"
    maxInputTokens: 4096
  outputGuardrails:
    maskPII: true
    blockedOutputPatterns:
      - "internal-api-key-[a-zA-Z0-9]+"
    maxOutputTokens: 4096
  allowedModels:
    - gpt-4
  allowedMcpServers: []
  mcpRequireHitl: true
```

`spec.budget` is reserved for future distributed enforcement and is rejected by the CRD and operator today. Use `maxInputTokens` and `maxOutputTokens` for currently supported limits.

```bash
kubectl apply -f my-policy.yaml
```

### Step 3 — Deploy an Agent

```yaml
# my-agent.yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: my-assistant
  namespace: agent-tenant-my-team
spec:
  model: gpt-4
  policyRef: standard-policy
  systemPrompt: >
    You are a helpful enterprise assistant. Answer questions clearly
    and concisely. Never fabricate information.
  storage:
    size: 1Gi
  enableGVisor: false
```

```bash
kubectl apply -f my-agent.yaml
```

The operator will create:
- A StatefulSet (`my-assistant-sandbox`) with 1 replica
- A Service (`my-assistant-sandbox`) on port 8080
- A PersistentVolumeClaim for SQLite checkpoints
- A NetworkPolicy restricting egress to LiteLLM and allowed MCP servers
- MCP sidecar containers in the pod (if configured)

Watch the agent come up:

```bash
kubectl get pods -n agent-tenant-my-team -w
kubectl get aiagents -n agent-tenant-my-team
```

#### Optional: attach skill files and A2A caller policy

The `AIAgent` spec can carry versioned skill documents and inbound A2A caller policy directly in the manifest. The operator injects the raw files into the runtime, the gateway returns parsed skill summaries, and the runtimes enforce the grants declared in frontmatter.

```yaml
spec:
  a2a:
    allowedCallers:
      - name: reviewer
        namespace: team-b
  skills:
    files:
      skills/research-brief/SKILL.md: |
        ---
        name: research-brief
        description: Prepare evidence-backed research notes and concise briefings.
        allowedSandboxTools:
          - sandbox.filesystem.read
          - sandbox.filesystem.write
        allowedMcpServers:
          - github
        allowedA2ATargets:
          - name: analysis-agent
            namespace: agent-tenant-my-team
        ---
        Use this skill when the request needs evidence gathering, repository inspection,
        or a handoff to a peer reviewer.
```

Skill files must use relative Markdown paths. The frontmatter is optional, but when present it controls the runtime capability envelope for that skill.

### Step 4 — Invoke the Agent

Via curl:

```bash
curl -X POST http://localhost:8080/api/v1/agents/my-assistant/invoke?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer my-secret-bearer-token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain Kubernetes namespaces in simple terms"}'
```

OpenCode agents also accept OpenCode-native runtime controls through the same payload, for example `system`, `max_turns`, `max_retries`, `no_session`, `working_directory`, `output_format`, and `output_schema`. The `agentctl invoke` command exposes matching flags for the supported fields.

OpenCode agents support the same per-agent pattern through
`spec.runtime.opencode.configFiles`. Those files are merged over chart-wide
`OPENCODE_RUNTIME_CONFIG_FILES_JSON` entries by relative path before the
OpenCode runtime starts.

```yaml
runtime:
  kind: opencode
  opencode:
    configFiles:
      opencode.json:
        default_agent: build
      agents/reviewer.md: |
        ---
        description: Review code conservatively
        mode: subagent
        ---
        Focus on regressions, operational risk, and missing tests.
```

For **streaming responses** (Server-Sent Events):

```bash
curl -N -X POST http://localhost:8080/api/v1/agents/my-assistant/invoke/stream?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer my-secret-bearer-token" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Write a summary of cloud computing trends"}'
```

---

## Multi-Agent Workflows

Define a DAG of agent steps with dependencies:

```yaml
# my-workflow.yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: research-pipeline
  namespace: agent-tenant-my-team
spec:
  description: "Research → Analysis → Report"
  input: "Impact of AI on healthcare"
  messageBus: in-memory
  steps:
    - name: research
      agentRef: research-agent
      prompt: "Research the following topic: {{input}}"
      execution:
        timeoutSeconds: 180
        maxAttempts: 2
        backoffSeconds: 3
    - name: analysis
      agentRef: analysis-agent
      prompt: "Analyze these findings: {{previous_output}}"
      dependsOn:
        - research
    - name: report
      agentRef: report-writer
      prompt: "Write an executive summary: {{previous_output}}"
      dependsOn:
        - analysis
      requireApproval: true    # Human must approve before this step runs
```

```bash
kubectl apply -f my-workflow.yaml
```

If a workflow step invokes an agent through the gateway, the caller identity is the workflow resource itself, not the agent running the previous step. That means every target agent must allow the workflow in `spec.a2a.allowedCallers`.

```yaml
spec:
  a2a:
    allowedCallers:
      - name: research-pipeline
        namespace: agent-tenant-my-team
```

The operator launches a Kubernetes Job that:
1. Validates the whole DAG before execution starts
2. Executes each ready frontier in dependency order and runs independent non-approval steps in parallel
3. Passes step outputs forward in-memory using `{{previous_output}}` and structured placeholders such as `{{research.output.json.summary}}`
4. Pauses at approval gates until a human approves the `AgentApproval` CR
5. Writes both a workflow snapshot JSON file and an append-only NDJSON journal to the artifact PVC
6. Updates the workflow CR status with `runId`, `stepStates`, `journalRef`, progress, and final output

Monitor workflow progress:

```bash
# Status
kubectl get agentworkflow research-pipeline -n agent-tenant-my-team -o yaml

# Worker job logs (jobs run in the operator namespace)
kubectl logs job/wf-research-pipeline -n kubesynapse
```

Via API:

```bash
# Create
curl -X POST http://localhost:8080/api/v1/workflows?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d @my-workflow.yaml

# Status
curl http://localhost:8080/api/v1/workflows/research-pipeline?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer $TOKEN"
```

## Human-in-the-Loop Approvals

When an agent encounters a high-risk action (configured via policy or workflow `requireApproval`), it creates an `AgentApproval` CR and pauses.

List pending approvals:

```bash
kubectl get agentapprovals -n agent-tenant-my-team

# Via API
curl http://localhost:8080/api/v1/approvals/approval-name?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer $TOKEN"
```

Approve or deny:

```bash
# Approve
curl -X PATCH http://localhost:8080/api/v1/approvals/approval-name?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "reason": "Looks good"}'

# Deny
curl -X PATCH http://localhost:8080/api/v1/approvals/approval-name?namespace=agent-tenant-my-team \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"decision": "denied", "reason": "Too risky"}'
```

Optional webhook notifications: set `agentRuntime.hitl.notificationWebhookUrl` in values.yaml to receive POST notifications when approvals are created.

---

## Using the CLI (agentctl)

Install the Python CLI:

```bash
python -m pip install -e ./cli

# Or via Makefile:
make build-cli
```

The CLI is built with **Typer** and **Rich**, so it has colored tables, better help output, streaming response rendering, and JSON mode for scripting.

If you install into a virtual environment, activate it before running `agentctl`. On Windows, the launcher is typically available at `.venv/Scripts/agentctl.exe` until that environment is activated or added to `PATH`.

Configure environment:

```bash
export AGENT_GATEWAY_URL=http://localhost:8080    # or https://agents.mycompany.com
export AGENT_GATEWAY_TOKEN=my-secret-bearer-token
export AGENT_NAMESPACE=agent-tenant-my-team
```

Commands:

```bash
# Check gateway health and effective config
agentctl health
agentctl config

# List resources
agentctl agents list
agentctl workflows list
agentctl policies list

# Show details for a single resource
agentctl agents show my-assistant
agentctl agents discover my-assistant
agentctl approvals show approval-name

# Create, update, or delete resources from JSON/YAML files
agentctl agents create -f examples/sample-agent.yaml
agentctl agents update my-assistant -f updated-agent.yaml
agentctl workflows create -f examples/sample-workflow.yaml

# Invoke an agent with an inline prompt
agentctl invoke my-assistant "What is Kubernetes?"

# Stream a response live
agentctl invoke my-assistant --stream "Summarize the latest deployment status"

# Route a request through a specific peer over A2A
agentctl invoke my-assistant "Ask the reviewer for a second opinion" --a2a-target-agent reviewer --a2a-target-namespace team-b --a2a-timeout-seconds 20

# Invoke an agent interactively (reads from stdin)
agentctl invoke my-assistant

# View agent logs
agentctl logs my-assistant

# Approve or deny human-in-the-loop requests
agentctl approvals approve approval-name --reason "Reviewed by ops"
agentctl approvals deny approval-name --reason "Insufficient evidence"

# Compatibility aliases from the old CLI still work
agentctl get agents
```

The file-based commands accept either full Kubernetes custom resource manifests like `AIAgent` and `AgentWorkflow`, or direct API payload documents in JSON/YAML using snake_case fields.

OpenCode-specific agent updates can also be patched without replacing the full manifest:

```bash
agentctl agents update my-assistant --opencode-config-file opencode.json=.opencode/opencode.json
agentctl agents update my-assistant --opencode-config-text prompts/review.md="Review changes conservatively."
agentctl agents update my-assistant --clear-opencode-config-files
```

---

## Using the Web UI

The Web UI is a React/Vite dashboard deployed as part of the Helm chart when `webUi.enabled: true`.

Access it:

```bash
# Port-forward (local dev)
kubectl port-forward svc/kubesynapse-web-ui 3000:80
# Open http://localhost:3000

# Or via Ingress at the root path (production)
# https://agents.mycompany.com/
```

Features:
- Browse and create agents
- Create and edit agent skill bundles and OpenCode config bundles with structured file editors
- Invoke agents with a chat interface or explicit A2A targets
- View agent status, parsed skill summaries, discovered peers, activity, and logs
- Manage workflows
- Review and act on pending approvals

Operational notes:
- the agent inspector surfaces parsed skill grants, inbound A2A callers, and peer reachability for the selected agent
- OpenCode agents expose the safe chat controls already available through the runtime (`system`, `max_turns`, and workspace-relative `working_directory`), alongside approval retry and gateway-backed inspection workflows
- the UI uses the same bearer token and namespace model as `agentctl`, so it maps cleanly to production ingress and local port-forwarding workflows

For local development of the Web UI:

```bash
cd web-ui
npm install
npm run dev        # Vite dev server at http://localhost:5173
```

For local browser QA with the API gateway:

```powershell
cd api-gateway
$env:API_GATEWAY_AUTH_MODE = "local"
$env:LOCAL_AUTH_ENABLED = "true"
$env:API_GATEWAY_SHARED_TOKEN = "your-shared-token-here"
$env:API_GATEWAY_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
$env:DATABASE_SQLITE_PATH = "C:/path/to/kubesynapse.ai/api-gateway/.local/kubesynapse-gateway.db"
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

Notes:

- `web-ui/.env.example` already points the Vite proxy at `http://127.0.0.1:8080`.
- `npm run dev` uses port `5173`, which matches the gateway's default browser CORS allowlist.
- `npm run preview` uses port `4173`; if you use preview against the local gateway, set `API_GATEWAY_CORS_ORIGINS` to include that origin.
- The local SQLite path is for browser bootstrap and session persistence during QA only; keep `api-gateway/.local/` out of version control.

---

## API Reference

All endpoints are prefixed with `/api` and require an `Authorization: Bearer <token>` header.

### Health & Readiness

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check (always 200) |
| `GET` | `/api/v1/ready` | Readiness check |

### Agents

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/agents?namespace=` | List all agents |
| `POST` | `/api/v1/agents?namespace=` | Create an agent (JSON body with AIAgent spec) |
| `GET` | `/api/v1/agents/{name}?namespace=` | Get agent details |
| `PATCH` | `/api/v1/agents/{name}?namespace=` | Update agent spec |
| `DELETE` | `/api/v1/agents/{name}?namespace=` | Delete an agent |
| `GET` | `/api/v1/agents/{name}/discover?namespace=` | Discover configured A2A peers and reachability |
| `POST` | `/api/v1/agents/{name}/invoke?namespace=` | Invoke agent (JSON: `{"prompt": "...", "thread_id": "..."}`) |
| `POST` | `/api/v1/agents/{name}/invoke/stream?namespace=` | Invoke with SSE streaming |
| `GET` | `/api/v1/agents/{name}/logs?namespace=` | Get agent pod logs |

### Workflows

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/workflows?namespace=` | List workflows |
| `POST` | `/api/v1/workflows?namespace=` | Create a workflow |
| `GET` | `/api/v1/workflows/{name}?namespace=` | Get workflow status |
| `PATCH` | `/api/v1/workflows/{name}?namespace=` | Update workflow |
| `DELETE` | `/api/v1/workflows/{name}?namespace=` | Delete workflow |

### Approvals

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/approvals/{name}?namespace=` | Get approval details |
| `PATCH` | `/api/v1/approvals/{name}?namespace=` | Approve or deny (`{"decision": "approved\|denied", ...}`) |

### Policies

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/policies?namespace=` | List policies |

---

## MCP Tool Servers

The platform supports two tiers of [Model Context Protocol](https://modelcontextprotocol.io/) tool servers.

### Shared Hub Servers

Deployed in the `mcp-hub` namespace, shared across all agents. Agents reference them by type name.

Enable in `values.yaml`:

```yaml
mcpHub:
  namespace: mcp-hub
  auth:
    bearerToken: "strong-random-secret"
  servers:
    github:
      enabled: false
      image: "ghcr.io/github/github-mcp-server:latest"
      args:
        - http
      port: 8082
      servicePort: 8000
```

No shared MCP servers are enabled by default. The GitHub image above is a real upstream example only; agents in this repo still require a compatible HTTP adapter layer before they can call stock MCP endpoints.

Agents reference shared servers in their spec:

```yaml
spec:
  mcpServers:
    - github
```

The operator generates a per-agent `NetworkPolicy` that restricts egress to only the allowed MCP server pods.

### Sidecar Servers

Co-located in the agent pod, communicating over localhost. No network exposure.

```yaml
spec:
  mcpSidecars:
    - name: custom-http-adapter
      image: your-registry.example.com/compatible-mcp-adapter:latest
      port: 8000
```

Sidecar servers are injected as additional containers in the agent's StatefulSet.

---

## OpenSandbox Integration

The runtime integrates with [OpenSandbox](https://github.com/alibaba/OpenSandbox) for secure code execution. Configure in values:

```yaml
agentRuntime:
  openSandbox:
    domain: "opensandbox.internal.mycompany.com"
    protocol: "https"
    requestTimeoutSeconds: 300
    defaultTtlSeconds: 600
    images:
      default: "python:3.11"
      code: "opensandbox/code-interpreter:latest"
      browser: "opensandbox/chrome:latest"
```

When the agent's LLM calls a code-execution tool, the runtime creates an ephemeral OpenSandbox container, executes the code, and returns the result — all within an isolated, time-limited sandbox.

---

## TLS & Ingress

Ingress is enabled by default, but the chart now leaves the ingress class, host,
and annotations empty so it can render on different clusters without assuming a
specific controller. Set the fields below for your environment, use a hostless
Ingress when that fits your cluster, or disable Ingress entirely and expose the
gateway another way.

### Enable ingress with TLS

```yaml
apiGateway:
  ingress:
    enabled: true
    annotations: {}
  ingressClassName: "nginx"
  ingressHost: "agents.mycompany.com"
  tls:
    enabled: true
    secretName: "agents-tls"
```

### With cert-manager

```yaml
apiGateway:
  ingress:
    enabled: true
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt-prod
  ingressClassName: "nginx"
  ingressHost: "agents.mycompany.com"
  tls:
    enabled: true
    secretName: "agents-tls"
```

### Hostless ingress

```yaml
apiGateway:
  ingress:
    enabled: true
    annotations: {}
  ingressClassName: ""
  ingressHost: ""
```

This renders an Ingress without a host, which is useful for local clusters or
controllers that route by IP and path only.

### Disable ingress

```yaml
apiGateway:
  ingress:
    enabled: false
```

Use this when you prefer `kubectl port-forward`, a separate `LoadBalancer`
Service, or another exposure mechanism.

### Manual TLS

```bash
kubectl create secret tls agents-tls \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key \
  -n ai-platform
```

---

## Observability

### OpenTelemetry

The agent runtime exports traces via OTLP. Set the collector endpoint:

```yaml
telemetry:
  otlpEndpoint: "http://otel-collector.monitoring:4318"
```

### Prometheus Metrics

The agent runtime exposes Prometheus metrics at `/metrics` via `prometheus-fastapi-instrumentator`.

### Logging

- **Operator logs**: `kubectl logs -l app=operator`
- **Agent runtime logs**: `kubectl logs -n <tenant-ns> <agent-pod-name>`
- **API Gateway logs**: `kubectl logs -l app=api-gateway`
- **Per-agent logs via API**: `GET /api/v1/agents/{name}/logs?namespace=`

### Execution Observatory and Workflow Runs

Workflow runs write two complementary observability streams:

- `POST /api/traces/batch` stores execution detail, step detail, LLM calls, tool calls, and raw trace events
- `POST /api/v1/traces/runtime-events` stores semantic runtime events for the ordered run timeline and run-intelligence queries

Useful verification endpoints for a completed workflow run:

```bash
curl http://localhost:8080/api/v1/traces/executions?namespace=<tenant-ns>&limit=20 \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/traces/executions/<execution_id> \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/traces/<execution_id>/timeline?limit=200 \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/traces/<execution_id>/runtime-summary \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/traces/runtime-events?namespace=<tenant-ns>&runtime_kind=operator-worker&limit=50 \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/workflows/<workflow-name>/runs?namespace=<tenant-ns> \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/workflows/<workflow-name>/runs/<run_id>/trace?namespace=<tenant-ns> \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:8080/api/v1/workflows/<workflow-name>/logs?namespace=<tenant-ns> \
  -H "Authorization: Bearer $TOKEN"
```

The API gateway self-heals missing trace tables on access and widens `workflow_executions.run_id` to `VARCHAR(128)` on PostgreSQL if an older install still has the shorter column definition.

---

## Scaling & High Availability

### Operator HA

The operator runs 2 replicas by default with Kopf leader election (peering). Only one replica actively reconciles at a time.

```yaml
operator:
  replicaCount: 2
```

### API Gateway & LiteLLM HPA

HorizontalPodAutoscalers are included in the chart:

- API Gateway: scales 1→10 replicas on CPU (70%) and memory (80%)
- LiteLLM: scales 1→5 replicas on CPU (75%)

### PodDisruptionBudgets

PDBs ensure at least 1 replica survives voluntary disruptions (node drains, rolling upgrades) when `replicaCount > 1`.

### Agent Scaling

Each agent runs as a singleton StatefulSet (1 replica) with its own PVC for durable checkpoints. Agents are isolated by design — scale by deploying more agents rather than scaling replicas.

---

## Uninstalling

```bash
# Remove the Helm release
helm uninstall KubeSynapse -n ai-platform

# Remove CRDs (Helm does not delete CRDs on uninstall)
kubectl delete crd aiagents.kubesynapse.ai
kubectl delete crd agentpolicies.kubesynapse.ai
kubectl delete crd agentapprovals.kubesynapse.ai
kubectl delete crd agenttenants.kubesynapse.ai
kubectl delete crd agentworkflows.kubesynapse.ai

# Remove tenant namespaces (created by the operator)
kubectl delete namespace agent-tenant-my-team
# ... repeat for each tenant namespace

# Or use the Makefile shortcut
make undeploy
```

---

## Troubleshooting

### Operator not reconciling

```bash
# Check operator logs
kubectl logs -l app=operator -n ai-platform --tail=100

# Verify CRDs are installed
kubectl get crds | grep kubesynapse.ai

# Verify RBAC
kubectl auth can-i create statefulsets --as=system:serviceaccount:ai-platform:kubesynapse-operator-sa
```

### Agent pod not starting

```bash
# Check the StatefulSet
kubectl get statefulset -n <tenant-ns>
kubectl describe statefulset <agent-name>-sandbox -n <tenant-ns>

# Check events
kubectl get events -n <tenant-ns> --sort-by='.lastTimestamp'

# Check if the runtime image can be pulled
kubectl describe pod <agent-pod-name> -n <tenant-ns>
```

### Agent returns 503 on invoke

The agent runtime is not ready. Check:

```bash
# Runtime pod logs
kubectl logs <agent-pod-name> -n <tenant-ns>

# Readiness probe
kubectl describe pod <agent-pod-name> -n <tenant-ns> | grep -A5 Readiness
```

Common causes:
- LiteLLM service not reachable (check `LITELLM_BASE_URL` env var)
- Invalid LLM API key
- Missing tenant runtime secret

### Workflow stuck in "running"

```bash
# Check the worker Job
kubectl get jobs -n kubesynapse | grep wf-
kubectl logs job/wf-<workflow-name> -n kubesynapse

# Check for pending approvals
kubectl get agentapprovals -n <tenant-ns>
```

If workflow detail is present but the semantic timeline is incomplete, check the worker logs for runtime event delivery:

```bash
kubectl logs job/wf-<workflow-name> -n kubesynapse | grep "Runtime event emitter"
```

Normal completion should include both the startup log and a final `Runtime event emitter stopped (sent=..., dropped=...)` line.

### LiteLLM errors

```bash
kubectl logs -l app=litellm -n ai-platform --tail=50

# Verify the LLM API key secret
kubectl get secret KubeSynapse-llm-api-keys -n ai-platform -o yaml
```

### Helm install fails

```bash
# Lint first
helm lint ./charts/kubesynapse -f values-prod.yaml

# Dry-run to see rendered templates
helm template KubeSynapse ./charts/kubesynapse -f values-prod.yaml | less

# Debug install
helm install KubeSynapse ./charts/kubesynapse -f values-prod.yaml --debug --dry-run
```

---

## Project Structure

```
kubesynapse.ai/
├── INSTALL.md                      ← This file
├── docs/architecture-overview.md   ← Detailed design document
├── Makefile                        ← Build, test, lint, deploy targets
├── scripts/run_lint.py             ← Python lint runner (flake8 + mypy)
│
├── operator/                       ← Kubernetes operator (Python/Kopf)
│   ├── main.py                     ← Entry point and Kopf startup
│   ├── config.py                   ← OperatorConfig dataclass
│   ├── errors.py                   ← Structured error codes
│   ├── reconcile.py                ← Shared reconciliation helpers
│   ├── tracing.py                  ← OpenTelemetry tracing setup
│   ├── worker.py                   ← Workflow & eval execution in Jobs
│   ├── utils.py                    ← Shared utilities
│   ├── state_store.py              ← SQLAlchemy models and DB init
│   ├── alembic.ini                 ← Alembic migration config
│   ├── controllers/                ← Per-CRD reconciliation handlers (7 modules)
│   ├── builders/                   ← K8s manifest construction (3 modules)
│   ├── services/                   ← K8s API interaction layer (1 module)
│   ├── migrations/                 ← Alembic database migrations
│   ├── tests/                      ← Operator unit tests (5 files)
│   ├── Dockerfile
│   └── requirements.txt
│
├── opencode-runtime/               ← Per-agent runtime (Python/FastAPI)
│   ├── main.py                     ← FastAPI app, routes, and lifecycle
│   ├── invoke.py                   ← OpenCode request orchestration and streaming
│   ├── analysis.py                 ← Response parsing and autonomy helpers
│   ├── session.py                  ← Session persistence and recovery
│   ├── skills.py                   ← Skill materialization and config overlay support
│   ├── hitl.py                     ← Human-in-the-loop approval module
│   ├── memory.py                   ← Cross-session memory support
│   ├── tests/                      ← OpenCode runtime tests
│   ├── Dockerfile
│   └── requirements.txt
│
├── api-gateway/                    ← REST API gateway (Python/FastAPI)
│   ├── main.py                     ← Auth, CRUD, invoke, streaming
│   ├── Dockerfile
│   └── requirements.txt
│
├── web-ui/                         ← Web dashboard (React/Vite)
│
├── cli/                            ← agentctl CLI (Python / Typer / Rich)
│   ├── agentctl.py
│   ├── pyproject.toml
│   └── README.md
│
├── charts/kubesynapse/        ← Helm chart
│   ├── Chart.yaml
│   ├── values.yaml                 ← All configuration knobs
│   └── templates/
│       ├── aiagent-crd.yaml        ← CRD definitions
│       ├── agentpolicy-crd.yaml
│       ├── agentapproval-crd.yaml
│       ├── agenttenant-crd.yaml
│       ├── agentworkflow-crd.yaml
│       ├── operator-deployment.yaml
│       ├── operator-rbac.yaml
│       ├── api-gateway.yaml
│       ├── litellm-deployment.yaml
│       ├── litellm-configmap.yaml
│       ├── redis.yaml
│       ├── qdrant.yaml
│       ├── nats.yaml
│       ├── web-ui.yaml
│       ├── external-secrets.yaml
│       ├── agent-network-policy.yaml
│       ├── mcp-server-deployment.yaml
│       ├── hpa.yaml
│       └── pdb.yaml
│
├── examples/                       ← Sample CRD manifests
│   ├── sample-agent.yaml
│   ├── sample-policy.yaml
│   ├── sample-tenant.yaml
│   ├── sample-workflow.yaml
│   └── ...
│
├── docs/                           ← Shareable repo notes and reference setup
└── deploy/                         ← Cluster and local-image example overrides
```

---

## Makefile Quick Reference

```bash
make all                  # lint + test + docker-build + helm-package
make docker-build         # Build platform images and 10 bundled MCP sidecars
make docker-push          # Push platform images and 10 bundled MCP sidecars to REGISTRY
make lint                 # Run flake8 on all Python components
make test                 # Run pytest on all components
make helm-lint            # Lint the Helm chart
make helm-package         # Package chart to dist/
make helm-template        # Render templates to stdout
make deploy               # helm upgrade --install KubeSynapse
make deploy-sample        # Apply sample agent, tenant, and policy
make undeploy             # Uninstall chart + delete CRDs
make build-cli            # Install agentctl into the current Python environment
make ui-install           # npm install for web-ui
make ui-dev               # Start web-ui dev server
make ui-build             # Build web-ui for production
make clean                # Remove build artifacts and images
```

Override registry and version:

```bash
make docker-build docker-push REGISTRY=myregistry.com/ai VERSION=2.0.0
```
