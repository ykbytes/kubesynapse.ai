# Production Deployment Guide

## Kubemininions AI Agent Sandbox - Enterprise Deployment

This guide ensures the kubemininions platform is ready for production deployment on any Kubernetes cluster.

### Pre-Deployment Verification Checklist

#### ✅ Image Versions
- [x] All images have explicit versioned tags (no `latest` or `main-latest` tags)
- [x] Image registry: `docker.io/yakdhane/*` 
- [x] Current web-ui tag: `deploy-20260319-172000`
- [x] All Python services use multi-stage builds where applicable
- [x] No build tools or package managers in final runtime images

#### ✅ Deployment Configuration
- [x] `deploy/values.dockerhub.local.yaml` contains all production image references
- [x] No hardcoded cluster-specific values in Helm chart
- [x] No environment-specific secrets baked into images
- [x] Image pull policy set to `IfNotPresent` for faster deployments

#### ✅ Web UI & Frontend
- [x] Chat layout fixed to properly fit screen (no overflow scrolling)
- [x] React hooks violations resolved (error #310 fixed)
- [x] Collapsible config panel implemented
- [x] Session naming working correctly ("New Chat" format)
- [x] TypeScript builds with zero errors

#### ✅ Core Features Verified
- [x] Gateway authentication: hybrid mode operational
- [x] Admin credentials: `admin` / `minikube-dev-admin-password` (customize before deployment)
- [x] Agent management: pdfcreator and researcher agents running
- [x] Operator reconciliation loop functional
- [x] Workflow execution capabilities verified
- [x] API endpoints responding with 200 status codes

#### ✅ Security & Hardening
- [x] Operator pod security context configured (runAsUser: 999, runAsGroup: 37)
- [x] No root containers
- [x] JWT token-based API authentication enabled
- [x] Namespace isolation enforced

#### ✅ Persistent State
- [x] SQLite auth database properly initialized
- [x] CRD storage via Kubernetes etcd
- [x] Artifact mounting configured for operators

### Deployment Steps for Production

#### 1. Prerequisites
```bash
# Ensure you have:
- Kubernetes cluster (1.24+)
- kubectl configured
- Helm 3.10+
- Docker registry credentials (if using private registry)
```

#### 2. Prepare Configuration

**Update image registry (if not using docker.io/yakdhane):**
```bash
# Edit deploy/values.dockerhub.local.yaml
# Change all repository values from docker.io/yakdhane/* to your registry
# Ensure all images are tagged with explicit versions
```

**Update credentials:**
```bash
# In values file, update:
authBootstrapAdminPassword: "<your-secure-password>"
litellmMasterKey: "<your-master-key>"
jwtSecret: "<your-jwt-secret>"
databasePassword: "<your-db-password>"
```

#### 3. Create Namespace & Secrets
```bash
# Create namespace
kubectl create namespace ai-platform

# Create image pull secret (if using private registry)
kubectl create secret docker-registry dockerhub-regcred \
  --docker-server=docker.io \
  --docker-username=<username> \
  --docker-password=<password> \
  -n ai-platform
```

#### 4. Deploy Helm Chart
```bash
# Deploy with production values
helm install ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f deploy/values.dockerhub.local.yaml \
  -n ai-platform

# Or update existing deployment
helm upgrade ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f deploy/values.dockerhub.local.yaml \
  -n ai-platform
```

#### 5. Verify Deployment
```bash
# Check all pods are running
kubectl get pods -n ai-platform

# Check operator reconciliation
kubectl logs -n ai-platform deployment/ai-agent-sandbox-operator

# Verify gateway is healthy
kubectl get svc -n ai-platform ai-agent-sandbox-api-gateway

# Test API
curl -X GET http://<gateway-service>/api/health
```

#### 6. Smoke Tests
```bash
# 1. Login API
curl -X POST http://<gateway-ip:port>/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<password>"}'

# 2. List agents
curl -X GET http://<gateway-ip:port>/api/agents?namespace=default \
  -H "Authorization: Bearer <token>"

# 3. Access web UI
# Navigate to http://<web-ui-service>/
# Login with admin credentials
# Verify chat interface loads without errors
```

### Production Readiness Checklist

| Item | Status | Notes |
|------|--------|-------|
| Image tags versioned | ✅ | deploy-20260319-172000 format |
| No `latest` tags | ✅ | All images have explicit versions |
| Helm chart cluster-agnostic | ✅ | No hardcoded values |
| Secrets externalized | ✅ | Provided via values file |
| Web UI layout fixed | ✅ | Chat fits screen properly |
| React errors resolved | ✅ | Error #310 fixed |
| API tests passing | ✅ | 200 responses verified |
| Database persistence ready | ✅ | SQLite or external DB-ready |
| TLS ready | ⚠️ | Configure ingress for TLS |
| Monitoring/logging | ⚠️ | Consider ELK or Prometheus integration |
| High availability | ⚠️ | Scale replicas in values file |
| Auto-scaling | ⚠️ | Can be added via HPA or KEDA |

### Scaling for Production

**Increase replicas:**
```yaml
# charts/ai-agent-sandbox/values.yaml
operator:
  replicaCount: 3  # High availability

apiGateway:
  replicas: 3      # Load balance auth

webUi:
  replicas: 2      # Multiple UI instances
```

**Resource limits:**
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"
    cpu: "1000m"
```

### Observability & Monitoring

**Recommended additions:**
- Prometheus for metrics collection
- Grafana dashboards for visualization
- ELK stack or Loki for log aggregation
- Jaeger for distributed tracing

### Support & Troubleshooting

**Pod not starting?**
- Check resource limits: `kubectl describe pod <pod-name> -n ai-platform`
- Review logs: `kubectl logs -n ai-platform <pod-name>`
- Verify image pull: `kubectl get events -n ai-platform`

**API returning 401?**
- Verify JWT secret is set correctly
- Check token hasn't expired
- Confirm user exists in auth database

**Chat interface not loading?**
- Clear browser cache
- Check web-ui pod logs
- Verify API gateway is accessible

### Maintenance

**Regular tasks:**
```bash
# Backup database
kubectl exec -n ai-platform <api-gateway-pod> -- \
  sh -c 'cp /data/auth.db /backups/auth.db'

# Check operator logs
kubectl logs -n ai-platform deployment/ai-agent-sandbox-operator -f

# Monitor resource usage
kubectl top nodes
kubectl top pods -n ai-platform
```

**Updates and rollbacks:**
```bash
# Update image version in values file
helm upgrade ai-agent-sandbox ./charts/ai-agent-sandbox \
  -f deploy/values.dockerhub.local.yaml

# Rollback if needed
helm rollback ai-agent-sandbox -n ai-platform
```

---

**Last Updated:** March 19, 2026
**Platform Version:** 1.0.0  
**Chart Version:** 0.1.0
