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

- 🧠 **AI runtime ready** — supports LangGraph-based and Goose-based execution paths
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
| `api-gateway/` | CRUD, invoke, and streaming endpoints | Exposes the platform to users and clients |
| `web-ui/` | React + TypeScript console | Gives operators and developers a visual control surface |
| `charts/ai-agent-sandbox/` | Full Helm install | Packages the entire platform for deployment |
| `deploy/` | Shareable values overrides | Makes cluster-specific rollout easier |
| `scripts/` + `.github/` | Packaging + CI automation | Keeps build and release workflows repeatable |

## ⚡ Quick start

### 1) Build the first-party images

```powershell
make docker-build REGISTRY=ghcr.io/your-org VERSION=latest
```

### 2) Or package a self-contained chart bundle

```powershell
.\scripts\package-self-contained.ps1 -Registry ghcr.io/your-org -ContainerCli podman -Version 0.1.0
```

### 3) Deploy with a cluster override

```powershell
helm upgrade --install ai-agent-sandbox .\charts\ai-agent-sandbox -f .\deploy\values.cluster.example.yaml
```

### 4) For local image testing, start here

```powershell
.\deploy\values.local-images.example.yaml
```

## 🧩 Deployment model

The default chart is intentionally **self-contained**:

- first-party images are configurable through chart values
- platform secrets default to native Kubernetes `Secret` resources
- LiteLLM reads provider keys and the master key from a shared chart-managed secret
- tenant provisioning can mint runtime secrets without requiring External Secrets CRDs
- Redis, Qdrant, NATS, LiteLLM, the API gateway, and the web UI deploy from the same chart

If you want a managed secret backend instead, set `platformSecrets.mode=external-secrets` and provide a real `operator.clusterSecretStoreName`.

## 🗺️ Documentation map

Jump straight to the guide you need:

- **`INSTALL.md`** — install steps, operations, and usage
- **`architecture-overview.md`** — system architecture and design decisions
- **`walkthrough.md`** — implementation narrative and flow
- **`docs/upstream-reference-repos.md`** — optional local research checkouts

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
- The packaging script assumes `helm` plus either `podman` or another compatible container CLI are available

---

<div align="center">
  <strong>Modern platform. Kubernetes-native workflows. One repository.</strong>
</div>
