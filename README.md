<div align="center">

  <h1>KubeSynth</h1>

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

KubeSynth is a **shareable, end-to-end AI agent platform** for Kubernetes:

- **OpenCode-first runtime path** &mdash; the gateway, operator, CLI, and web UI now target a single supported runtime: `runtime.kind: opencode`
- **File-backed skills and config** &mdash; agent behavior, capability grants, and OpenCode config files are versioned directly in manifests
- **Delegation built in** &mdash; explicit A2A routing and policy-enforced peer discovery via gateway, CLI, and web UI
- **Platform-first governance** &mdash; policies, approvals, workflows, evals, tenants, and audit-friendly control-plane resources live with the app stack
- **Integrated observability module** &mdash; connector, target, policy, and report CRDs plus a collector path for cluster intelligence and dashboard visibility
- **Deployment friendly** &mdash; Helm chart, deploy overrides, packaging scripts, and a live Kind redeploy script are built in

## Repository layout

```
kubesynth/
├── operator/            # K8s operator, controller modules, worker job engine
├── opencode-runtime/    # OpenCode runtime service and invoke pipeline
├── api-gateway/         # FastAPI gateway: auth, CRUD, invoke, streaming, chat state
├── web-ui/              # React + TypeScript console
├── mcp-sidecars/        # Bundled MCP tool images + optional collector sidecar
│   ├── base/
│   ├── browser/
│   ├── code-exec/
│   ├── collector/
│   ├── database/
│   ├── documents/
│   ├── git/
│   ├── github-adapter/
│   ├── kubernetes/
│   ├── messaging/
│   ├── rag/
│   └── web-search/
├── collector-agent/     # Read-only cluster intelligence collector DaemonSet image
├── charts/              # Helm charts and CRD templates
├── catalog/             # Agent templates and skills catalog
├── cli/                 # agentctl CLI tool
├── deploy/              # Helm values overrides per environment
├── docs/                # Architecture, deployment, observability, and design docs
├── examples/            # Sample YAML manifests and scripts
├── scripts/             # Build, packaging, deploy, and lint scripts
├── tests/               # Cross-cutting integration tests
├── .github/             # CI workflows and agent prompts
├── Makefile             # Build, test, lint, Helm, and live Kind redeploy targets
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
helm upgrade --install kubesynth ./charts/kubesynth \
  -f ./deploy/values.dockerhub.local.yaml
```

**4. Verify**

```bash
kubectl port-forward svc/kubesynth-api-gateway 8080:8080
curl http://localhost:8080/api/health
```

---

### Option B &mdash; Build and deploy your own images

**1. Build the core platform images and bundled MCP sidecars**

```bash
make docker-build REGISTRY=ghcr.io/your-org VERSION=latest CONTAINER_CLI=docker
```

**2. Or use the packaging script**

```bash
./scripts/package-self-contained.ps1 -Registry ghcr.io/your-org -Version 0.1.0 -Push
```

**3. Deploy**

```bash
helm upgrade --install kubesynth ./charts/kubesynth \
  -f ./deploy/values.cluster.example.yaml
```

To enable managed Google sign-in, fill in [deploy/values.google-oidc.example.yaml](deploy/values.google-oidc.example.yaml) and layer it with an extra `-f` during Helm upgrade.

### Option C &mdash; Refresh the live local Kind release

If you already have the `ai-sandbox` release running in `ai-agent-sandbox`, use the checked-in image override file and redeploy script instead of replaying the broader example values files:

```powershell
pwsh -File ./scripts/deploy-ai-sandbox-kind.ps1 -DryRun
pwsh -File ./scripts/deploy-ai-sandbox-kind.ps1
```

This path uses `--reuse-values --server-side=true --force-conflicts` and only refreshes the image references declared in `deploy/values.ai-sandbox.kind-local.yaml`.

## Documentation

| Document | Content |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Full install guide: prerequisites, dev setup, production deployment, secrets, troubleshooting |
| [`docs/architecture-overview.md`](docs/architecture-overview.md) | System architecture, CRD model, control/data plane design, security model |
| [`docs/walkthrough.md`](docs/walkthrough.md) | Current implementation walkthrough for the OpenCode runtime, gateway, operator, UI, and observability stack |
| [`docs/observability-explained.md`](docs/observability-explained.md) | How the observability CRDs fit together and how to make reports visible in the UI |
| [`docs/aiops-observability-architecture.md`](docs/aiops-observability-architecture.md) | Detailed observability architecture notes and design background |
| [`docs/deployment-readme.md`](docs/deployment-readme.md) | Deployment entry points, validation flow, and local Kind redeploy guidance |
| [`docs/execution-plan.md`](docs/execution-plan.md) | Phased project execution plan and progress tracker |
| [`web-ui/README.md`](web-ui/README.md) | Frontend local dev workflow and feature map |
| [`cli/README.md`](cli/README.md) | Full `agentctl` command reference |
| [`docs/upstream-reference-repos.md`](docs/upstream-reference-repos.md) | Optional local research checkouts |

## Make targets

```
make docker-build                # Build operator, runtime, gateway, UI, and bundled MCP sidecars
make docker-push                 # Push those images to the configured registry
make test                        # Run service and integration tests
make lint                        # Run flake8 across Python services
make helm-lint                   # Lint the Helm chart
make helm-package                # Package the Helm chart
make deploy                      # Install/upgrade via Helm
make deploy-ai-sandbox-kind      # Refresh the live local ai-sandbox release with local images
make deploy-sample               # Apply sample agent, tenant, and policy
make clean                       # Remove build artifacts and images
```

## Notes

- The checked-in chart defaults currently target published images under `docker.io/yakdhane`
- The packaging script defaults to `docker`; pass `-ContainerCli podman` for Podman
- Ingress is disabled by default in the Helm chart; enable it per environment with values overrides
- The platform chart now includes the observability CRDs and the cluster intelligence collector DaemonSet path
- The repository contains an optional MCP collector sidecar and collector-agent image in addition to the default `docker-build` set

---

<div align="center">
  <strong>Modern platform. Kubernetes-native workflows. One repository.</strong>
</div>
