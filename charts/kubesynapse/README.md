# KubeSynapse Helm Chart

Main platform Helm chart for deploying KubeSynapse on Kubernetes.

## Installation

```bash
helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace
```

## Local Kind Quickstart

For repeatable local installs on Windows, use the checked-in PowerShell helper:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
	-ClusterName kubesynapse-dev `
	-Namespace kubesynapse `
	-ReleaseName kubesynapse `
	-AdminPassword "KubesynapseAdmin9!"
```

The script builds and loads the local platform images, applies both
`deploy/values.local-images.example.yaml` and `deploy/values.kind.quickstart.yaml`,
syncs the persisted PostgreSQL password on repeat upgrades, injects the checked-in
skills catalog, and restarts the core deployments so unchanged `:dev` image tags are
picked up reliably.

The default quickstart admin username is `admin`. The helper prints the effective
username, password, and port-forward commands when the install or upgrade completes.

If the local `:dev` images already exist and you only want to reload them into Kind
and run the Helm upgrade, add `-SkipBuild`:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
	-ClusterName kubesynapse-dev `
	-Namespace kubesynapse `
	-ReleaseName kubesynapse `
	-AdminPassword "KubesynapseAdmin9!" `
	-SkipBuild
```

Post-upgrade verification:

```bash
kubectl get deploy,pods -n kubesynapse
kubectl port-forward svc/kubesynapse-api-gateway -n kubesynapse 8080:8080
curl http://127.0.0.1:8080/api/v1/health
kubectl port-forward svc/kubesynapse-web-ui -n kubesynapse 3000:80
```

The chart leaves the browsable Skills catalog empty unless you provide catalog JSON. To populate the `Catalog > Skills` tab during install or upgrade, pass the checked-in catalog file:

```bash
helm upgrade --install kubesynapse ./charts/kubesynapse \
	-n kubesynapse \
	--create-namespace \
	--set-file skillsCatalog.catalogJson=catalog/skills-catalog.json
```

## Bootstrap Behavior

- LiteLLM schema initialization is automatic.
- The chart runs `prisma db push` in a LiteLLM init container during install and upgrade.
- System agent `AIAgent` resources are created in a post-install/post-upgrade hook, so first installs do not need `systemAgents.enabled=false`.
- Local and air-gapped installs must preload `docker.io/litellm/litellm:v1.82.3-stable` alongside the platform images.
- You should not need to run manual database bootstrap commands after a normal Helm deploy.

## Runtime Support

- `opencode` is the default runtime kind exposed by the chart and the path used by the checked-in examples.
- `pi` remains the supported alternative runtime kind and is wired through the chart values and operator deployment.
- `mistral-vibe` remains a supported runtime kind and is wired through the chart values and operator deployment.

## Default Memory Policy

When `memoryPolicy.enabled=true`, the chart creates a post-install/post-upgrade
`AgentPolicy` named `default-memory-policy` with these defaults:

- `autoPromote: true`
- `maxInjectedMemories: 8`
- `maxInjectedChars: 2400`
- `allowedMemoryTypes: []`

Agents that explicitly reference that policy get those recall defaults. Agents with no
`policyRef` still use the gateway's built-in fallback behavior, but the chart-managed
policy is the preferred shared default for durable recall.

## MCP Hub Behavior

`mcpHub.enabled` now gates the shared MCP hub namespace, network policies, and shared
server deployments. This matters for single-node Kind installs because the recommended
`deploy/values.kind.quickstart.yaml` overlay disables the MCP hub entirely.

Structured remote MCP connections do not require the shared hub bearer token unless the
connection actually uses hub transport or explicitly references `MCP_BEARER_TOKEN`.

## Key Values

| Path | Description | Default |
|------|-------------|---------|
| `image.registry` | Container image registry | `docker.io/kubesynapse` |
| `image.tag` | Image tag for all components | `v1.0.0` |
| `apiGateway.sharedToken` | Bearer token for dev/test auth | `change-me` |
| `apiGateway.authMode` | `shared_token`, `oidc`, or `saml` | `shared_token` |
| `skillsCatalog.catalogJson` | JSON payload served to the `Catalog > Skills` UI tab | `[]` |
| `apiGateway.replicas` | Gateway replica count | `2` |
| `operator.workerTraceEnabled` | Enable worker trace shipping | `true` |
| `operator.workerTraceBatchSize` | Trace batch size before flush | `50` |
| `database.enabled` | Deploy Postgres sub-chart | `true` |
| `database.url` | External Postgres URL (optional) | `""` |
| `memoryPolicy.enabled` | Create the chart-managed default memory `AgentPolicy` | `true` |
| `memoryPolicy.autoPromote` | Auto-promote runtime memory candidates persisted by the gateway | `true` |
| `memoryPolicy.maxInjectedMemories` | Max recalled memories injected into prompts | `8` |
| `memoryPolicy.maxInjectedChars` | Max characters injected for recalled memory context | `2400` |
| `mcpHub.enabled` | Enable the shared MCP hub namespace and server pool | `true` |
| `ingress.enabled` | Enable Ingress resource | `false` |
| `ingress.host` | Primary ingress host | `kubesynapse.local` |
| `agentRuntime.pi.enabled` | Opt-in to deploy the Pi runtime sidecar | `false` |

## Production Hardening

Toggle these values for production clusters:

- `podDisruptionBudget.enabled` — Ensure minimum availability during node drains.
- `networkPolicy.enabled` — Restrict pod-to-pod traffic to known ports.
- `horizontalPodAutoscaler.enabled` — Scale gateway and operator based on CPU.
- `certManager.enabled` — Automatically provision TLS certificates via cert-manager.

## Values Files

| File | Environment |
|------|-------------|
| `values.dev.yaml` | Local development (Kind / Docker Desktop) |
| `values.staging.yaml` | Staging with external DB and OIDC |
| `values.production.yaml` | Production hardening, PDB, NetworkPolicy, HPA |

## Upgrading

```bash
helm upgrade kubesynapse ./charts/kubesynapse -n kubesynapse -f values.production.yaml
```

## Uninstall

```bash
helm uninstall kubesynapse -n kubesynapse
```
