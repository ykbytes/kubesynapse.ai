<div align="center">

  <h1>🚀 Kubeminionagents</h1>

  <h3>Kubernetes-native AI agents, packaged as one sleek platform</h3>

  <p>
    Build, deploy, and operate AI agents with a unified control plane, runtimes,
    API gateway, Helm chart, and web console — all from a single repository.
  </p>

  <img src="https://img.shields.io/badge/Kubernetes-Native-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" alt="Kubernetes Native" />
  <img src="https://img.shields.io/badge/Helm-Ready-0F1689?style=for-the-badge&logo=helm&logoColor=white" alt="Helm Ready" />
  <img src="https://img.shields.io/badge/Python-Services-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python Services" />
  <img src="https://img.shields.io/badge/React-Web_UI-61DAFB?style=for-the-badge&logo=react&logoColor=0B1020" alt="React Web UI" />
  <img src="https://img.shields.io/badge/TypeScript-Frontend-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript Frontend" />

</div>

---

## ✨ Why this repo feels different

Kubeminionagents is designed as a **shareable, end-to-end AI agent platform** for Kubernetes:

- 🧠 **AI runtime ready** — supports LangGraph-based, Goose-based, Codex-based, and OpenCode-based execution paths
- 🗂️ **File-backed skills** — agent behavior and capability grants can be versioned as Markdown skill files inside the agent spec
- 🤝 **Delegation built in** — explicit A2A routing and specialist-team orchestration are available through the gateway, CLI, and web UI
- 🛡️ **Platform-first** — operator, policies, tenants, and approvals live with the app stack
- 🌐 **Full product surface** — API gateway and browser UI are included, not bolted on later
- 📦 **Deployment friendly** — Helm chart, deploy overrides, and packaging scripts are built in
- 🔧 **Single source of truth** — control plane, runtimes, docs, and automation move together

## 🎛️ Platform at a glance

| Area | What lives here | Why it matters |
| --- | --- | --- |
| `operator/` | Reconciler and worker image | Manages agent lifecycle inside the cluster |
| `agent-runtime/` | LangGraph-based runtime | Runs agent workflows and execution logic |
| `goose-runtime/` | Goose HTTP adapter runtime | Supports an alternate runtime path |
| `codex-runtime/` | Codex HTTP adapter runtime | Provides Codex-native execution for compatible agents |
| `opencode-runtime/` | OpenCode HTTP adapter runtime | Provides OpenCode sessions, skills, plugins, and MCP-native workflows |
| `api-gateway/` | CRUD, invoke, and streaming endpoints | Exposes the platform to users and clients |
| `web-ui/` | React + TypeScript console | Gives operators and developers a visual control surface |
| `charts/ai-agent-sandbox/` | Full Helm install | Packages the entire platform for deployment |
| `deploy/` | Shareable values overrides | Makes cluster-specific rollout easier |
| `scripts/` + `.github/` | Packaging + CI automation | Keeps build and release workflows repeatable |

## 🚦 What you can do today

- Define `spec.skills.files` to steer runtimes with repo-tracked Markdown skills and scoped capability grants
- Seed Goose agents with per-agent `runtime.goose.configFiles` instead of relying on chart-wide defaults only
- Seed OpenCode agents with per-agent `runtime.opencode.configFiles` to materialize OpenCode agents, plugins, skills, and `opencode.json` fragments per agent
- Route a request to an explicit peer over A2A or launch a sequential or parallel specialist team from the same invoke surface
- Inspect approvals, runtime logs, peer reachability, parsed skill summaries, workflow run history, and system health from the bundled web console
- Manage agents, workflows, evaluations, policies, LLM providers, users, audit logs, and usage reporting through either Kubernetes manifests, the API gateway, the CLI, or the UI
- Use the visual workflow composer with conditional branches, loop steps, execution status overlays, and per-step output inspection
- Persist chat sessions per agent, resume past conversations, and coordinate specialist subagent teams from the same chat workbench
- Export and import workspace bundles, clone existing resources, and use the admin console as the main operational surface

## ⚡ Quick start

### Option A — Deploy from pre-built DockerHub images (fastest)

No build step needed. Pull the published images and deploy with a single Helm command.

**1. Set your LLM API key**

Edit `deploy/values.dockerhub.local.yaml` (or pass `--set`):

```yaml
platformSecrets:
  native:
    openaiApiKey: "sk-your-key"
    apiGatewaySharedToken: "my-secret-bearer-token"
```

**2. Create an image-pull secret (DockerHub rate limits)**

```powershell
kubectl create secret docker-registry dockerhub-regcred `
  --docker-username=YOUR_DOCKERHUB_USERNAME `
  --docker-password=YOUR_DOCKERHUB_TOKEN `
  --docker-email=you@example.com
```

**3. Deploy**

```powershell
helm upgrade --install ai-agent-sandbox .\charts\ai-agent-sandbox `
  -f .\deploy\values.dockerhub.local.yaml
```

**4. Test**

```powershell
kubectl port-forward svc/ai-agent-sandbox-api-gateway 8080:8080
curl http://localhost:8080/api/health
```

---

### Option B — Build and deploy your own images

**1. Build all platform and sidecar images**

```powershell
make docker-build REGISTRY=ghcr.io/your-org VERSION=latest CONTAINER_CLI=docker
```

This target builds the core platform images (operator, agent-runtime, goose-runtime, codex-runtime,
opencode-runtime, api-gateway, web-ui) plus all MCP sidecar images from `./mcp-sidecars`.

**2. Or use the packaging script (builds, tags, and optionally pushes)**

```powershell
.\scripts\package-self-contained.ps1 -Registry ghcr.io/your-org -Version 0.1.0 -ContainerCli docker -Push
```

The script builds every platform image and all 10 bundled MCP sidecars in one pass, generates a
matching `values-generated.yaml` with pinned image references, and optionally pushes everything.

**3. Deploy with a cluster override**

```powershell
# Generic cluster (ingress off, portable defaults)
helm upgrade --install ai-agent-sandbox .\charts\ai-agent-sandbox -f .\deploy\values.cluster.example.yaml

# Local images loaded into Kind/Minikube
helm upgrade --install ai-agent-sandbox .\charts\ai-agent-sandbox -f .\deploy\values.local-images.example.yaml
```

`deploy/values.cluster.example.yaml` is a portable starting point: ingress is off by default, and
class name, host, and annotations stay unset until you supply controller-specific values.

## 🧩 Deployment model

The default chart is intentionally **self-contained**:

- first-party images are configurable through chart values
- platform secrets default to native Kubernetes `Secret` resources
- LiteLLM reads provider keys and the master key from a shared chart-managed secret
- tenant provisioning can mint runtime secrets without requiring External Secrets CRDs
- Redis, Qdrant, NATS, LiteLLM, the API gateway, and the web UI deploy from the same chart
- ingress defaults are portable across clusters: class name, host, and annotations are opt-in, and ingress can be disabled entirely

If you want a managed secret backend instead, set `platformSecrets.mode=external-secrets` and provide a real `operator.clusterSecretStoreName`.

## 🗺️ Documentation map

Jump straight to the guide you need:

| Document | Content |
|---|---|
| **`INSTALL.md`** | Full install guide: DockerHub quick-start, Kind/Minikube dev setup, production deployment, secrets config, first agent, CLI, API reference, observability, troubleshooting |
| **`architecture-overview.md`** | System architecture, CRD model, control/data plane design, security model, MCP execution architecture |
| **`walkthrough.md`** | Implementation narrative: Helm chart foundations, operator reconciliation loop, runtime pipeline, enterprise features |
| **`web-ui/README.md`** | Frontend local dev workflow, console feature map, and admin/workbench coverage |
| **`cli/README.md`** | Full `agentctl` command reference with examples |
| **`docs/upstream-reference-repos.md`** | Optional local research checkouts for Goose, OpenSandbox, and MCP catalog |

## 🧱 Repository boundaries

Tracked in this repository:

- the platform code and deployment assets listed above
- shareable automation for packaging and CI
- documentation needed to install and operate the stack

Intentionally not tracked:

- local reference clones under `tools-repos/`
- the local MCP catalog clone under `mcp-catalog/`
- generated artifacts, caches, and machine-specific config

The platform builds and deploys without those local reference clones. See `docs/upstream-reference-repos.md` if you want to recreate them locally.

## 📌 Notes

- OpenSandbox integration is optional and configured through `agentRuntime.openSandbox.*`
- Shared MCP servers are opt-in by default
- The packaging script defaults to `docker`. Pass `-ContainerCli podman` if you prefer Podman
- Pre-built images are published to `docker.io/yakdhane` and can be used with `deploy/values.dockerhub.local.yaml`
- All chart image defaults use `pullPolicy: IfNotPresent` — images are not re-pulled on every pod restart
- Ingress is disabled by default in the Helm chart. Enable it per-environment with a values override

---

<div align="center">
  <strong>Modern platform. Kubernetes-native workflows. One repository.</strong>
</div>
