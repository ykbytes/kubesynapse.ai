<div align="center">

  <h1>Kubeminionagents</h1>

  <h3>Kubernetes-native AI agents, packaged as one sleek platform</h3>

  <p>
    Build, deploy, and operate AI agents with a unified control plane, runtimes,
    API gateway, Helm chart, and web console &mdash; all from a single repository.
  </p>

  <img src="https://img.shields.io/badge/Kubernetes-Native-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="Kubernetes Native" />
  <img src="https://img.shields.io/badge/Helm-Ready-0F1689?style=for-the-badge&logo=helm&logoColor=white" alt="Helm Ready" />
  <img src="https://img.shields.io/badge/Python-Services-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python Services" />
  <img src="https://img.shields.io/badge/React-Web_UI-61DAFB?style=for-the-badge&logo=react&logoColor=0B1020" alt="React Web UI" />
  <img src="https://img.shields.io/badge/TypeScript-Frontend-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript Frontend" />

</div>

---

## Why this repo

Kubeminionagents is a **shareable, end-to-end AI agent platform** for Kubernetes:

- **AI runtime ready** &mdash; supports LangGraph, Goose, Codex, and OpenCode execution paths
- **File-backed skills** &mdash; agent behavior and capability grants versioned as Markdown skill files
- **Delegation built in** &mdash; A2A routing and specialist-team orchestration via gateway, CLI, and web UI
- **Platform-first** &mdash; operator, policies, tenants, and approvals live with the app stack
- **Full product surface** &mdash; API gateway and browser UI included, not bolted on later
- **Deployment friendly** &mdash; Helm chart, deploy overrides, and packaging scripts built in

## Repository layout

```
kubemininions/
├── operator/            # K8s operator &mdash; reconciler and worker
├── agent-runtime/       # LangGraph-based agent runtime
├── goose-runtime/       # Goose HTTP adapter runtime
├── codex-runtime/       # Codex HTTP adapter runtime
├── opencode-runtime/    # OpenCode HTTP adapter runtime
├── api-gateway/         # FastAPI gateway &mdash; CRUD, invoke, streaming
├── web-ui/              # React + TypeScript console
├── mcp-sidecars/        # 10 MCP tool sidecar images
│   ├── base/            #   shared base module and requirements
│   ├── browser/         #   headless browser automation
│   ├── code-exec/       #   sandboxed code execution
│   ├── database/        #   database query tools
│   ├── documents/       #   document processing
│   ├── git/             #   git operations
│   ├── github-adapter/  #   GitHub API adapter
│   ├── kubernetes/      #   kubectl / K8s API tools
│   ├── messaging/       #   messaging (Slack, etc.)
│   ├── rag/             #   retrieval-augmented generation
│   └── web-search/      #   web search tools
├── charts/              # Helm charts
│   ├── agents/          #   agent CRD templates
│   └── ai-agent-sandbox/#   full platform chart
├── catalog/             # Agent templates and skills catalog
├── cli/                 # agentctl CLI tool
├── deploy/              # Helm values overrides per environment
├── docs/                # Architecture, deployment, and design docs
├── examples/            # Sample YAML manifests and scripts
├── scripts/             # Build, packaging, and lint scripts
├── tests/               # Cross-cutting integration tests
├── .github/             # CI workflows and agent prompts
├── Makefile             # Build, test, lint, deploy orchestration
├── pyproject.toml       # Python project config
└── README.md            # This file
```

## Quick start

### Option A &mdash; Deploy from pre-built DockerHub images (fastest)

**1. Set your LLM API key**

Edit `deploy/values.dockerhub.local.yaml` (or pass `--set`):

```yaml
platformSecrets:
  native:
    openaiApiKey: "sk-your-key"
    apiGatewaySharedToken: "my-secret-bearer-token"
```

**2. Create an image-pull secret (DockerHub rate limits)**

```bash
kubectl create secret docker-registry dockerhub-regcred \
  --docker-username=YOUR_DOCKERHUB_USERNAME \
  --docker-password=YOUR_DOCKERHUB_TOKEN \
  --docker-email=you@example.com
```

**3. Deploy**

```bash
helm upgrade --install ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f ./deploy/values.dockerhub.local.yaml
```

**4. Verify**

```bash
kubectl port-forward svc/ai-agent-sandbox-api-gateway 8080:8080
curl http://localhost:8080/api/health
```

---

### Option B &mdash; Build and deploy your own images

**1. Build all platform and sidecar images**

```bash
make docker-build REGISTRY=ghcr.io/your-org VERSION=latest CONTAINER_CLI=docker
```

**2. Or use the packaging script**

```bash
./scripts/package-self-contained.ps1 -Registry ghcr.io/your-org -Version 0.1.0 -Push
```

**3. Deploy**

```bash
helm upgrade --install ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f ./deploy/values.cluster.example.yaml
```

## Documentation

| Document | Content |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Full install guide: prerequisites, dev setup, production deployment, secrets, troubleshooting |
| [`docs/architecture-overview.md`](docs/architecture-overview.md) | System architecture, CRD model, control/data plane design, security model |
| [`docs/walkthrough.md`](docs/walkthrough.md) | Implementation narrative and design decisions |
| [`docs/execution-plan.md`](docs/execution-plan.md) | Phased project execution plan and progress tracker |
| [`web-ui/README.md`](web-ui/README.md) | Frontend local dev workflow and feature map |
| [`cli/README.md`](cli/README.md) | Full `agentctl` command reference |
| [`docs/upstream-reference-repos.md`](docs/upstream-reference-repos.md) | Optional local research checkouts |

## Make targets

```
make docker-build    # Build all 17 container images
make docker-push     # Push all images to registry
make test            # Run unit tests across all services
make lint            # Run flake8 across all Python services
make helm-lint       # Lint the Helm chart
make helm-package    # Package the Helm chart
make deploy          # Install/upgrade via Helm
make deploy-sample   # Apply sample agent, tenant, and policy
make clean           # Remove build artifacts and images
```

## Notes

- Pre-built images are published to `docker.io/yakdhane`
- The packaging script defaults to `docker`; pass `-ContainerCli podman` for Podman
- Ingress is disabled by default in the Helm chart; enable per-environment with values overrides
- All chart image defaults use `pullPolicy: IfNotPresent`

---

<div align="center">
  <strong>Modern platform. Kubernetes-native workflows. One repository.</strong>
</div>
