# KubeSynapse Helm Chart

Main platform Helm chart for deploying KubeSynapse on Kubernetes.

## Installation

```bash
helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace
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

## Key Values

| Path | Description | Default |
|------|-------------|---------|
| `image.registry` | Container image registry | `docker.io/kubesynapse` |
| `image.tag` | Image tag for all components | `v1.0.0` |
| `apiGateway.sharedToken` | Bearer token for dev/test auth | `change-me` |
| `apiGateway.authMode` | `shared_token`, `oidc`, or `saml` | `shared_token` |
| `apiGateway.replicas` | Gateway replica count | `2` |
| `operator.workerTraceEnabled` | Enable worker trace shipping | `true` |
| `operator.workerTraceBatchSize` | Trace batch size before flush | `50` |
| `database.enabled` | Deploy Postgres sub-chart | `true` |
| `database.url` | External Postgres URL (optional) | `""` |
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
