# Kubeminionagents

Kubeminionagents is a Kubernetes-native AI agent platform packaged as a single shareable repository.

It combines the control plane, runtimes, API surface, web console, Helm chart, deployment examples, and packaging automation in one place.

## Repository Scope

Tracked in this repository:

- `operator/` for the reconciler and worker image
- `agent-runtime/` for the LangGraph-based runtime
- `goose-runtime/` for the Goose HTTP adapter runtime
- `api-gateway/` for CRUD, invoke, and streaming endpoints
- `web-ui/` for the browser console
- `charts/ai-agent-sandbox/` for the full platform install
- `deploy/` for shareable deployment override examples
- `scripts/` and `.github/` for packaging and CI automation

Intentionally not tracked:

- local reference clones under `tools-repos/`
- the local MCP catalog clone under `mcp-catalog/`
- generated artifacts, caches, and machine-specific config

The platform builds and deploys without those local reference clones. See `docs/upstream-reference-repos.md` if you want to recreate them locally.

## Quick Start

Build the first-party images:

```powershell
make docker-build REGISTRY=ghcr.io/your-org VERSION=latest
```

Or generate a packaged chart bundle:

```powershell
.\scripts\package-self-contained.ps1 -Registry ghcr.io/your-org -ContainerCli podman -Version 0.1.0
```

Deploy with a cluster override:

```powershell
helm upgrade --install ai-agent-sandbox .\charts\ai-agent-sandbox -f .\deploy\values.cluster.example.yaml
```

For local cluster image testing, start from:

```powershell
.\deploy\values.local-images.example.yaml
```

## Deployment Model

The default chart path is self-contained:

- first-party images are configurable from values
- platform secrets default to native Kubernetes `Secret` resources
- LiteLLM reads provider keys and the master key from a shared chart-managed secret
- tenant provisioning can mint runtime secrets without requiring External Secrets CRDs
- Redis, Qdrant, NATS, LiteLLM, API gateway, and the web UI deploy from the same chart

If you want managed secret backends instead, set `platformSecrets.mode=external-secrets` and provide a real `operator.clusterSecretStoreName`.

## Docs

- `INSTALL.md` for install, operations, and usage
- `architecture-overview.md` for the system-level design
- `walkthrough.md` for the implementation narrative
- `docs/upstream-reference-repos.md` for optional local research checkouts

## Notes

- OpenSandbox integration remains optional and is configured through `agentRuntime.openSandbox.*`.
- Shared MCP servers are opt-in by default.
- The packaging script assumes `helm` plus either `podman` or another compatible container CLI are available.