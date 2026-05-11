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
| OpenCode RT | http://localhost:8081 | Agent runtime |
| Postgres | localhost:5432 | State + trace database |
| Redis | localhost:6379 | Cache / sessions |
| NATS | localhost:4222 | Message bus |
| Qdrant | localhost:6333 | Vector DB |

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

```bash
# Build and load images into the Kind cluster
make docker-build REGISTRY=localhost/kubesynapse VERSION=dev
docker build -f deploy/litellm/Dockerfile -t docker.io/litellm/litellm:v1.82.3-stable deploy/litellm
kind load docker-image localhost/kubesynapse/kubesynapse-operator:dev --name desktop
kind load docker-image localhost/kubesynapse/kubesynapse-api-gateway:dev --name desktop
kind load docker-image localhost/kubesynapse/kubesynapse-web-ui:dev --name desktop
kind load docker-image localhost/kubesynapse/kubesynapse-opencode-rt:dev --name desktop
kind load docker-image localhost/kubesynapse/kubesynapse-pi-rt:dev --name desktop
kind load docker-image localhost/kubesynapse/kubesynapse-vibe-rt:dev --name desktop
kind load docker-image docker.io/litellm/litellm:v1.82.3-stable --name desktop

# Deploy with local image values
helm upgrade --install kubesynapse ./charts/kubesynapse -n kubesynapse --create-namespace \
  -f deploy/values.dev.yaml \
  -f deploy/values.local-images.example.yaml
```

See `deploy/values.local-images.example.yaml` for the full local-image registry and
tag overrides.

If your cluster cannot pull `localhost/kubesynapse/*:dev` images directly,
push them to a reachable registry or load them into the cluster runtime before
running the Helm install.

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

The Pi runtime is **opt-in**. Enable it in your values file:

```yaml
agentRuntime:
  pi:
    enabled: true
```

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
curl http://localhost:8080/api/health
curl http://localhost:8080/api/ready
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
