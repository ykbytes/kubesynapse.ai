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
- When the chart-managed PostgreSQL instance is enabled, LiteLLM targets the dedicated `litellm` database created by the chart so Prisma sync does not modify gateway auth/session tables.
- System agent `AIAgent` resources are created in a post-install/post-upgrade hook, so first installs do not need `systemAgents.enabled=false`.
- Local and air-gapped installs must preload `docker.io/litellm/litellm:v1.82.3-stable` alongside the platform images.
- You should not need to run manual database bootstrap commands after a normal Helm deploy.

## Runtime Support

- `opencode` is the default and production runtime, used by all checked-in examples.
- `pi` and `mistral-vibe` are available in alpha but not recommended for production workloads. They remain wired through the chart values and operator deployment.

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
| `apiGateway.auth.accessTokenTtlSeconds` | Access token lifetime in seconds | `3600` (1 hour) |
| `apiGateway.auditRetentionDays` | Days to keep audit logs before auto-purge | `90` |
| `opencodeRuntime.immutableConfig` | Mount hardened immutable config (disable for dev) | `true` |
| `opencodeRuntime.securityLevel` | Permission preset: permissive, standard, strict | `permissive` |
| `opencodeRuntime.permissionOverrides` | Per-tool permission overrides on top of preset | `{}` |
| `opencodeRuntime.permissionFloor` | Hard floor that no policy can weaken | `{}` |
| `opencodeRuntime.admin` | Admin-controlled env vars (security overrides) | `{OPENCODE_DISABLE_DEFAULT_PLUGINS: "true"}` |
| `gatekeeper.enabled` | Install OPA Gatekeeper as sub-chart | `false` |
| `gatekeeper.enforcementAction` | Enforcement mode: deny, warn, dryrun | `deny` |
| `backup.enabled` | Enable PostgreSQL backup CronJob | `false` |
| `gc.enabled` | Enable daily garbage collection CronJob | `true` |
| `gc.schedule` | GC CronJob schedule (cron format) | `0 3 * * *` |
| `skillsCatalog.catalogJson` | JSON payload served to the `Catalog > Skills` UI tab | `[]` |
| `mcpHub.enabled` | Enable the shared MCP hub namespace and server pool | `true` |
| `ingress.enabled` | Enable Ingress resource | `false` |
| `ingress.host` | Primary ingress host | `kubesynapse.local` |

## Security Hardening

The OpenCode runtime ships hardened by default across four defense layers:

| Layer | Mechanism | Env Var |
|-------|-----------|---------|
| Runtime Isolation | Plugin auto-discovery disabled | `OPENCODE_DISABLE_DEFAULT_PLUGINS: "true"` |
| Immutable Baseline | Hardened ConfigMap at `/etc/kubesynapse/opencode.json` | `opencodeRuntime.immutableConfig: true` |
| Traffic Enforcement | Force all LLM traffic through audited proxy | `OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON` |
| Model Governance | Global model allowlist at runtime | `OPENCODE_ADMIN_MODEL_OVERRIDE_JSON` |

Admin overrides are configured under `opencodeRuntime.admin` and are injected
into every agent runtime pod. These override user-provided env vars and
cannot be circumvented by agent CRDs.

```yaml
opencodeRuntime:
  admin:
    OPENCODE_DISABLE_DEFAULT_PLUGINS: "true"
    # OPENCODE_ADMIN_MODEL_OVERRIDE_JSON: '["gpt-4o","gpt-4o-mini"]'
    # OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON: '{"litellm":{"options":{"baseURL":"http://litellm:4000/v1"}}}'
```

### Security Level Presets

The immutable ConfigMap supports three security presets that control the
baseline permission configuration for all OpenCode runtime pods:

| Level | `bash` | `edit` | `write` | `webfetch` | Use Case |
|-------|--------|--------|---------|------------|----------|
| `permissive` (default) | allow | allow | allow | allow | Trusted environments, backward compatible |
| `standard` | ask | allow | allow | allow | Shared clusters, recommended for teams |
| `strict` | deny | ask | ask | ask | Maximum lockdown, code review only |

```yaml
opencodeRuntime:
  securityLevel: "standard"
  # Override specific permissions on top of the preset:
  permissionOverrides:
    external_directory: "deny"
  # Hard floor that no policy can weaken:
  permissionFloor:
    bash: "deny"
```

### OPA Gatekeeper Integration

The chart can optionally install OPA Gatekeeper as a sub-chart dependency to
provide admission-level policy enforcement. When enabled, four
ConstraintTemplates are deployed:

| Constraint | Purpose |
|-----------|---------|
| `KubeSynapseRequirePolicyRef` | Every AIAgent must reference a valid AgentPolicy |
| `KubeSynapseProtectSealedPolicy` | Sealed policies cannot be modified or deleted |
| `KubeSynapseValidateToolPatterns` | Validates `adminToolCeiling` values and tool patterns |
| `KubeSynapsePreventPolicyOrphan` | Policies referenced by live agents cannot be deleted |

Enable Gatekeeper:

```yaml
gatekeeper:
  enabled: true
  enforcementAction: "deny"  # or "warn" or "dryrun"
```

### Admin Tool Ceiling

Each AgentPolicy can define an `adminToolCeiling` under `spec.toolPolicy`
that caps the maximum permission level for specific tools. Even if the
immutable config says "allow", the ceiling reduces it:

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentPolicy
metadata:
  name: restricted-policy
spec:
  toolPolicy:
    adminToolCeiling:
      bash: "deny"
      external_directory: "deny"
      webfetch: "ask"
```

The operator injects the ceiling as `OPENCODE_ADMIN_PERMISSION_CEILING_JSON`
into the agent pod. The runtime reads this at startup to cap permissions.

### Policy Seal

Setting `spec.sealed: true` on an AgentPolicy makes it immutable. When
Gatekeeper is enabled, the `KubeSynapseProtectSealedPolicy` constraint
blocks all UPDATE and DELETE operations on sealed policies at admission time.

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentPolicy
metadata:
  name: production-lockdown
spec:
  sealed: true
  toolPolicy:
    adminToolCeiling:
      bash: "deny"
```

### Runtime Attestation

The operator computes a SHA-256 hash of each resolved policy spec and
annotates the agent pod with `kubesynapse.ai/policy-hash`. The gateway
can verify this hash in healthz responses to ensure agents are running
with their expected policy configuration.

## Garbage Collection

The chart deploys a daily GC CronJob (`kubesynapse-gc`) that:

- Purges audit logs older than `apiGateway.auditRetentionDays` (default 90 days)
- Cleans expired sessions
- Runs daily at 3am UTC (after the backup window)

Disable with `gc.enabled: false`.

## Backup

A PostgreSQL backup CronJob is available. Enable for production:

```yaml
backup:
  enabled: true
  schedule: "0 2 * * *"
  retentionCount: 7
  backend: "pvc"  # or "s3"
```

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
