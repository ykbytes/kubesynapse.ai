# KubeSynapse Deployment Guide

## Quick Start (Kind + Helm)

The most repeatable local path in this repository is the checked-in Kind helper script. The manual Helm flow below is still useful, but the PowerShell helper is the preferred first stop for local development.

```bash
kind create cluster

# Build core platform images
docker build -t localhost/kubesynapse/kubesynapse-api-gateway:dev api-gateway/
docker build -t localhost/kubesynapse/kubesynapse-operator:dev operator/
docker build -t localhost/kubesynapse/kubesynapse-web-ui:dev web-ui/
docker build -t localhost/kubesynapse/kubesynapse-opencode-rt:dev opencode-runtime/

# Build LiteLLM (pinned version required by the chart)
docker build -f deploy/litellm/Dockerfile -t docker.io/litellm/litellm:v1.82.3-stable deploy/litellm

# Build MCP sidecars (optional — only needed if agents use mcpSidecars or mcpServers)
# Use `make docker-build REGISTRY=localhost/kubesynapse VERSION=dev` to build all 10 in one pass,
# or build individually:
# docker build -t localhost/kubesynapse/mcp-code-exec:dev -f mcp-sidecars/code-exec/Dockerfile mcp-sidecars
# docker build -t localhost/kubesynapse/mcp-web-search:dev -f mcp-sidecars/web-search/Dockerfile mcp-sidecars
# ... (see deploy/values.local-images.example.yaml for the full list)

# Load into Kind
kind load docker-image localhost/kubesynapse/kubesynapse-api-gateway:dev
kind load docker-image localhost/kubesynapse/kubesynapse-operator:dev
kind load docker-image localhost/kubesynapse/kubesynapse-web-ui:dev
kind load docker-image localhost/kubesynapse/kubesynapse-opencode-rt:dev
kind load docker-image docker.io/litellm/litellm:v1.82.3-stable
# Load MCP sidecars if you built them:
# kind load docker-image localhost/kubesynapse/mcp-code-exec:dev
# ...

# Generate secrets
export LITELLM_KEY=$(openssl rand -hex 16)
export API_TOKEN=$(openssl rand -hex 32)
export DB_PASS=$(openssl rand -hex 16)
export JWT_SECRET=$(openssl rand -hex 32)

# Install
helm install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse --create-namespace \
  -f deploy/values.local-images.example.yaml \
  -f deploy/values.kind.quickstart.yaml \
  --set-file skillsCatalog.catalogJson=catalog/skills-catalog.json \
  --set platformSecrets.native.litellmMasterKey="$LITELLM_KEY" \
  --set platformSecrets.native.apiGatewaySharedToken="$API_TOKEN" \
  --set platformSecrets.native.databasePassword="$DB_PASS" \
  --set platformSecrets.native.jwtSecret="$JWT_SECRET" \
  --wait --timeout 3m

# Connect
kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080
kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 3000:80
```

For a cleaner local loop on Windows and for repeatable upgrades, prefer:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"
```

This helper is the preferred local quickstart because it keeps the chart overlays,
local image tags, and same-host `/api` UI routing aligned with the current repo.

> **MCP sidecars:** The quickstart above installs without MCP sidecars (the sample
> agents in `examples/` don't use them). If your agents reference sidecars via
> `spec.mcpSidecars`, build the matching images first — see the Kind Development
> Loop section below, or use `make docker-build REGISTRY=localhost/kubesynapse VERSION=dev`.

### Services

| Service | URL | Description |
|---------|-----|-------------|
| API Gateway | http://localhost:8080 | FastAPI backend |
| Web UI | http://localhost:3000 | React frontend |
| LiteLLM | http://localhost:4000 | Model proxy |
| OpenCode RT | In-cluster service | Default agent runtime for checked-in examples |
| MCP Sidecars | Per-agent localhost | 10 bundled sidecars (code exec, web search, browser, etc.) — optional, only if agents use `spec.mcpSidecars` |
| Postgres | localhost:5432 | State + trace database |
| Redis | localhost:6379 | Cache / sessions |
| NATS | in-cluster | Shared messaging service |
| Qdrant | in-cluster | Vector DB |

---

## Building Images

```bash
# Build all images
make docker-build

# Build specific images
make docker-build-gateway
make docker-build-operator
make docker-build-ui
make docker-build-opencode-runtime

# Build with custom registry/tag
REGISTRY=ghcr.io/myorg VERSION=v1.2.3 make docker-build
```

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes 1.28+
- Helm 3.13+
- kubectl configured

### Install

```bash
# Create namespace and install
kubectl create namespace kubesynapse
make k8s-install

# Or with custom values
NAMESPACE=prod VALUES_FILE=./deploy/values.production.yaml make k8s-install
```

### Upgrade

```bash
make k8s-upgrade
```

### Uninstall

```bash
make k8s-uninstall
```

### Port Forwarding

```bash
make k8s-port-forward
```

---

## Kind Development Loop

For local development with [Kind](https://kind.sigs.k8s.io/):

Recommended local loop on Windows and for repeatable upgrades:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"
```

The script creates or reuses the `kind-kubesynapse-dev` context, builds the required
platform images and the pinned LiteLLM image, loads them into Kind, applies the local
image override plus `deploy/values.kind.quickstart.yaml`, injects the skills catalog,
and reconciles the persisted PostgreSQL password on repeat upgrades.

If you want admission-time policy protection in local clusters, enable the optional
Gatekeeper sub-chart in an extra values file and pass it during `helm upgrade`:

```yaml
gatekeeper:
  enabled: true
  enforcementAction: warn
```

`warn` is a good local default while iterating on `AgentPolicy.spec.sealed` and
`spec.toolPolicy.adminToolCeiling`; switch to `deny` once the policy set is stable.

It also restarts the core deployments after Helm succeeds. That restart matters when
you keep reusing the same local `:dev` image tag, because `kind load docker-image`
alone does not change the Kubernetes image string.

Manual equivalent:

```bash
make docker-build REGISTRY=localhost/kubesynapse VERSION=dev
docker build -f deploy/litellm/Dockerfile -t docker.io/litellm/litellm:v1.82.3-stable deploy/litellm
kind load docker-image localhost/kubesynapse/kubesynapse-operator:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-api-gateway:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-web-ui:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-opencode-rt:dev --name kubesynapse-dev
kind load docker-image docker.io/litellm/litellm:v1.82.3-stable --name kubesynapse-dev

# Load MCP sidecars if you built them (make docker-build includes all 10 by default):
kind load docker-image localhost/kubesynapse/mcp-code-exec:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-web-search:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-documents:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-browser:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-database:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-git:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-github-adapter:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-kubernetes:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-messaging:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/mcp-rag:dev --name kubesynapse-dev

helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace \
  -f deploy/values.local-images.example.yaml \
  -f deploy/values.kind.quickstart.yaml \
  --set-file skillsCatalog.catalogJson=catalog/skills-catalog.json
```

See `deploy/values.local-images.example.yaml` for the full local-image registry and
tag overrides. `deploy/values.kind.quickstart.yaml` is the recommended single-node Kind
overlay because it disables optional MCP Hub and system-agent workloads.

If your agents use `spec.mcpSidecars`, you must build and load the corresponding MCP
sidecar images. The Makefile builds all 10 in one pass (`make docker-build`), and
`values.local-images.example.yaml` maps all of them to localhost tags. The sample
agents in `examples/` do not use MCP sidecars, so a basic quickstart works without them.

The extra `--set-file` keeps the `Catalog > Skills` tab populated in local clusters. Without it, the chart defaults the browsable Skills catalog to an empty list.

If your cluster cannot pull `localhost/kubesynapse/*:dev` images directly,
push them to a reachable registry or load them into the cluster runtime before
running the Helm install.

If you are doing the manual loop with unchanged image tags, explicitly restart the
deployments you touched after `kind load docker-image`, for example:

```bash
kubectl rollout restart deployment/kubesynapse-api-gateway -n kubesynapse --context kind-kubesynapse-dev
kubectl rollout restart deployment/kubesynapse-operator -n kubesynapse --context kind-kubesynapse-dev
kubectl rollout restart deployment/kubesynapse-web-ui -n kubesynapse --context kind-kubesynapse-dev
```

## Chart Packaging

```bash
helm lint ./charts/kubesynapse
helm package ./charts/kubesynapse -d ./dist
```

---

## Configuration

### Helm Values

See `deploy/values.*.yaml` for environment-specific examples:

- `values.dev.yaml` — local development
- `values.staging.yaml` — staging environment
- `values.production.yaml` — production hardening

### Key Helm Values

```yaml
image:
  registry: docker.io/kubesynapse
  tag: v1.0.0

apiGateway:
  auth:
    mode: hybrid
    localAuthEnabled: true
    bootstrapAdminUsername: admin
  replicaCount: 2

operator:
  workerTraceEnabled: true
  workerTraceBatchSize: 50

postgresql:
  enabled: true

ingress:
  enabled: true
  host: kubesynapse.example.com
```

### Alpha Runtimes (Pi & Mistral Vibe)

> **Warning:** Pi and Mistral Vibe runtimes are in alpha and not recommended for production workloads.

The Pi runtime is **opt-in per agent**. Create agents with `spec.runtime.kind: pi` to launch the Pi runtime.

```yaml
piRuntime:
  image:
    repository: localhost/kubesynapse/kubesynapse-pi-rt
    tag: dev
```

Mistral Vibe is also **opt-in per agent**. Configure its runtime image defaults through `mistralVibeRuntime` and create agents with `spec.runtime.kind: mistral-vibe`.

```yaml
mistralVibeRuntime:
  image:
    repository: docker.io/kubesynapse/kubesynapse-vibe-rt
    tag: v2.1.0-run-intelligence
```

Create agents with `spec.runtime.kind: mistral-vibe` to launch the Mistral-backed runtime bridge.

### LiteLLM Database Bootstrap

LiteLLM schema initialization is automatic in the Helm chart.

- The deployment runs `prisma db push` in an init container before LiteLLM starts.
- You should not need to manually exec into the pod to initialize the database.
- If LiteLLM still fails on first boot, check PostgreSQL readiness and NetworkPolicies first.

---

## Production Checklist

- [ ] Change `API_GATEWAY_SHARED_TOKEN` to a strong random value
- [ ] Configure TLS/ingress with cert-manager
- [ ] Set up external PostgreSQL (Cloud SQL, RDS, etc.)
- [ ] Configure backup for PostgreSQL and trace storage
- [ ] Set resource limits and requests
- [ ] Enable PodDisruptionBudgets
- [ ] Configure NetworkPolicies
- [ ] Set up Prometheus/Grafana monitoring
- [ ] Configure log aggregation (Fluent Bit / Vector)
- [ ] Run security scan: `make lint` + `bandit`
- [ ] Enable OIDC or SAML for auth
- [ ] Set up alerts for critical paths

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker logs kubesynapse-api-gateway
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway

# Check health
curl http://localhost:8080/api/v1/health
curl http://localhost:8080/api/v1/ready
```

### Database connection issues

```bash
# Test Postgres connectivity
docker exec -it kubesynapse-postgres psql -U kubesynapse -d kubesynapse -c "SELECT 1"

# Check gateway logs and Postgres readiness first
kubectl logs -n kubesynapse deployment/kubesynapse-api-gateway
kubectl get pods -n kubesynapse
```

### Trace storage issues

```bash
# Verify the gateway trace endpoints and the backing tables
curl http://localhost:8080/api/v1/traces/executions
```

---

## Monitoring

Prometheus rules and Grafana dashboards are in `deploy/prometheus/` and `deploy/grafana/`.

```bash
# Apply Prometheus rules
kubectl apply -f deploy/prometheus/rules.yaml

# Import Grafana dashboard
kubectl create configmap grafana-dashboard-kubesynapse \
  --from-file=deploy/grafana/dashboard.json \
  -n monitoring
```
