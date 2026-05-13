# KubeSynapse Deployment Guide

## Quick Start (Docker Compose)

The fastest way to run KubeSynapse locally:

```bash
# Start the full stack
docker compose up -d

# Or use Make
make compose-up

# View status
make compose-status

# View logs
make compose-logs

# Stop
make compose-down
```

### Services

| Service | URL | Description |
|---------|-----|-------------|
| API Gateway | http://localhost:8080 | FastAPI backend |
| Web UI | http://localhost:3000 | React frontend |
| LiteLLM | http://localhost:4000 | Model proxy |
| OpenCode RT | http://localhost:8081 | Default local agent runtime profile |
| Postgres | localhost:5432 | State + trace database |
| Redis | localhost:6379 | Cache / sessions |
| NATS | localhost:4222 | Message bus |
| Qdrant | localhost:6333 | Vector DB |

The default local compose profile exposes the OpenCode runtime only. Pi and Mistral Vibe remain supported in Kubernetes and are selected per agent through `spec.runtime.kind`.

### Default Credentials

- **Shared Token**: `dev-shared-token-change-in-production`
- **Postgres**: `kubesynapse` / `kubesynapse-dev-password`

⚠️ **Change these before exposing to the internet.**

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

helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace \
  -f deploy/values.local-images.example.yaml \
  -f deploy/values.kind.quickstart.yaml \
  --set-file skillsCatalog.catalogJson=catalog/skills-catalog.json
```

See `deploy/values.local-images.example.yaml` for the full local-image registry and
tag overrides. `deploy/values.kind.quickstart.yaml` is the recommended single-node Kind
overlay because it disables optional MCP Hub and system-agent workloads.

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

### Docker Compose

Edit `docker-compose.yml` or create a `.env` file:

```env
API_GATEWAY_SHARED_TOKEN=your-secure-token-here
DATABASE_URL=postgresql+psycopg://user:pass@postgres:5432/db
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Helm Values

See `deploy/values.*.yaml` for environment-specific examples:

- `values.dev.yaml` — local development
- `values.staging.yaml` — staging environment
- `values.production.yaml` — production hardening

### Key Helm Values

```yaml
image:
  registry: docker.io/kubesynapse
  tag: v2.1.0-run-intelligence

apiGateway:
  sharedToken: "change-me"
  authMode: "shared_token"
  replicas: 2

operator:
  workerTraceEnabled: true
  workerTraceBatchSize: 50

database:
  enabled: true
  url: "postgresql://..."

ingress:
  enabled: true
  host: kubesynapse.example.com
```

### Pi Runtime Deployment

The Pi runtime is **opt-in per agent**. The chart exposes Pi image and default model settings through `piRuntime`:

```yaml
piRuntime:
  model: "anthropic/claude-sonnet-4-20250514"
  thinkingLevel: "medium"
```

Create agents with `spec.runtime.kind: pi` to launch the Pi runtime.

### Mistral Vibe Runtime Deployment

Mistral Vibe is also **opt-in per agent**. Configure its runtime image defaults through `mistralVibeRuntime`:

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

# Check migration status
kubectl exec -n kubesynapse deployment/kubesynapse-api-gateway -- alembic current
```

### Trace storage issues

```bash
# Check trace directory
docker exec kubesynapse-api-gateway ls -la /app/state/traces

# Verify trace tables exist
docker exec -it kubesynapse-postgres psql -U kubesynapse -c "\dt workflow_*"
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
