# Compatibility Matrix — KubeSynapse v1.0.0

## Kubernetes Version Compatibility

| K8s Version | Status | Platform Tested | Notes |
|-------------|--------|-----------------|-------|
| **1.25** | ✅ Supported | Kind | Minimum supported version. Some features require 1.25+ API versions (PDB v1, CronJob v1). |
| **1.26** | ✅ Supported | Kind | No known issues. |
| **1.27** | ✅ Supported | Kind | Sidecar containers (KEP-753) alpha — not used by KubeSynapse. |
| **1.28** | ✅ Supported | Kind | No known issues. |
| **1.29** | ✅ Supported | Kind | No known issues. |
| **1.30** | ✅ Supported | Kind | No known issues. |
| **1.31** | ✅ Supported | Kind | No known issues. |
| **1.32** | ✅ Supported | Kind | Latest tested version. All CRDs and operator features fully functional. |
| **1.33** | 🧪 Planned | Kind | Will be tested when available. |
| **1.34** | 🧪 Planned | Kind | Will be tested when available. |

---

## Platform Compatibility

| Platform | Local (Kind) | Local (k3s) | Local (Minikube) | Cloud (EKS) | Cloud (GKE) | Cloud (AKS) |
|----------|-------------|-------------|------------------|-------------|-------------|-------------|
| **Operator** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **API Gateway** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **OpenCode Runtime** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **LiteLLM Proxy** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **PostgreSQL (subchart)** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **Redis (subchart)** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **Qdrant (subchart)** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **NATS (subchart)** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |
| **Web UI** | ✅ Tested | ✅ Tested | ✅ Tested | 🧪 Planned | 🧪 Planned | 🧪 Planned |

> **Legend**: ✅ Tested = verifiably working | 🧪 Planned = scheduled for testing | ⚠️ Partial = works with limitations | ❌ Unsupported = known incompatibility

---

## Component Compatibility

### Core Components

| Component | Version | Notes |
|-----------|---------|-------|
| Kubernetes API | v1.25–v1.32 | Uses `apps/v1`, `batch/v1`, `networking.k8s.io/v1`, `policy/v1` |
| Helm | v3.12+ | Uses `helm.sh/chart` v2, OCI registry support |
| CRDs | `KubeSynapse.ai/v1alpha1` | 12 custom resources (AIAgent, AgentPolicy, AgentApproval, AgentTenant, AgentWorkflow, McpConnection, WebhookReceiver, WorkflowTrigger, ObservationTarget, ObservationPolicy, ObservationReport, ConnectorPlugin) |

### Infrastructure Dependencies

| Component | Version | Required | Notes |
|-----------|---------|----------|-------|
| PostgreSQL | 15–16 | Yes | Required by API Gateway and LiteLLM. Bitnami subchart included in Helm chart. |
| Redis | 7.x | Yes | Required for task queues, caching, session storage. Bitnami subchart included. |
| Qdrant | 1.7+ | Optional | Required for semantic memory and RAG. Disable with `qdrant.enabled: false`. |
| NATS | 2.10+ | Optional | Required for A2A agent-to-agent messaging. Disable with `nats.enabled: false`. |
| cert-manager | 1.12+ | Optional | For automatic TLS certificate provisioning. |

### Runtimes

| Runtime | Version | CPU Arch | GPU Support | Notes |
|---------|---------|----------|-------------|-------|
| OpenCode Runtime | v1.x | amd64, arm64 | No | Primary execution runtime. FastAPI wrapper around opencode serve. |

### MCP Sidecars

| Sidecar | Image | Status | Notes |
|---------|-------|--------|-------|
| Kubernetes MCP | `KubeSynapse/mcp-kubernetes` | ✅ Tested | Cluster inspection, pod management |
| Code Execution | `KubeSynapse/mcp-code-execution` | ✅ Tested | Sandboxed Python/Node.js execution |
| Web Search | `KubeSynapse/mcp-web-search` | ✅ Tested | Web search via SerpAPI/Brave |
| Browser Automation | `KubeSynapse/mcp-browser` | ✅ Tested | Headless browser via Playwright |
| Database | `KubeSynapse/mcp-database` | ✅ Tested | PostgreSQL, MySQL, SQLite query |
| Git | `KubeSynapse/mcp-git` | ✅ Tested | Git operations on repos |
| RAG/Memory | `KubeSynapse/mcp-rag` | ✅ Tested | Vector search via Qdrant |
| Messaging | `KubeSynapse/mcp-messaging` | ✅ Tested | Slack, Email, Webhook |
| File System | `KubeSynapse/mcp-filesystem` | ✅ Tested | Workspace file operations |
| API Integration | `KubeSynapse/mcp-api` | ✅ Tested | REST API calls with auth |
| Monitoring | `KubeSynapse/mcp-monitoring` | ✅ Tested | Prometheus metrics, Grafana |

---

## Kubernetes Feature Requirements

| Feature | Required? | API Version | Notes |
|---------|-----------|-------------|-------|
| CustomResourceDefinitions | **Required** | `apiextensions.k8s.io/v1` | Core platform feature. All KubeSynapse resources are CRDs. |
| NetworkPolicies | **Recommended** | `networking.k8s.io/v1` | Required for multi-tenant isolation and MCP egress filtering. Disable with `networkPolicy.enabled: false`. |
| PodDisruptionBudgets | **Recommended** | `policy/v1` | Required for high availability. Disable with `podDisruptionBudget.enabled: false`. |
| Leader Election (Leases) | **Required** | `coordination.k8s.io/v1` | Operator uses lease-based leader election. |
| HorizontalPodAutoscalers | **Optional** | `autoscaling/v2` | Auto-scaling for API Gateway, LiteLLM. Disable by setting replicas. |
| ResourceQuotas | **Recommended** | `v1` | Required for multi-tenant resource isolation. |
| LimitRanges | **Optional** | `v1` | Default resource limits per namespace. |
| PriorityClasses | **Recommended** | `scheduling.k8s.io/v1` | Ensures critical pods aren't evicted. |
| TopologySpreadConstraints | **Recommended** | `v1` (GA in 1.27) | Spread pods across zones for HA. |
| ServiceMonitors (Prometheus) | **Optional** | `monitoring.coreos.com/v1` | Requires Prometheus Operator. |

---

## Testing Methodology

### Local Testing (Kind)

```bash
# Test against specific K8s version
export K8S_VERSION=1.31

# Create cluster
kind create cluster --name KubeSynapse-test --image "kindest/node:v${K8S_VERSION}"

# Deploy KubeSynapse
helm install KubeSynapse ./charts/kubesynapse \
  --namespace kubesynapse --create-namespace \
  --set litellm.masterKey=test-key \
  --set platformSecrets.native.openaiApiKey=sk-test \
  --wait --timeout 10m

# Run smoke tests
kubectl port-forward svc/kubesynapse-api-gateway 8080:8080 -n kubesynapse &
sleep 3
curl http://localhost:8080/api/health
curl http://localhost:8080/api/ready

# Teardown
kind delete cluster --name KubeSynapse-test
```

### Automated Compatibility Test

Run the full compatibility test suite:

```bash
./scripts/test-compatibility.sh
```

This script:
1. Creates Kind clusters for each K8s version (1.25, 1.27, 1.29, 1.31, 1.32)
2. Installs KubeSynapse via Helm on each cluster
3. Runs health checks (`/api/health`, `/api/ready`)
4. Creates a test AIAgent and verifies reconciliation
5. Reports pass/fail per version
6. Cleans up clusters

---

## Known Limitations

1. **K8s < 1.25**: The `policy/v1` API (used for PDBs) was introduced in 1.21 but became the only available version in 1.25. Older clusters may need manual API version adjustments.

2. **CRD Schema Validation**: `KubeSynapse.ai/v1alpha1` uses structural schema validation (`apiextensions.k8s.io/v1`). Clusters running `apiextensions.k8s.io/v1beta1` (pre-1.22) are not supported.

3. **arm64 Architecture**: All images support `linux/amd64`. `linux/arm64` support is available for core images (api-gateway, operator, web-ui) but not all MCP sidecars.

4. **Windows Nodes**: Not supported. All components require Linux nodes. Windows-based K8s nodes should use nodeSelector/taints to avoid scheduling KubeSynapse pods.

5. **Fargate/EKS Serverless**: The operator requires persistent running pods (not Fargate spot). Use EKS managed node groups.

6. **OpenShift**: Not tested. May require additional SCC (SecurityContextConstraints) configuration for non-root containers.

7. **GKE Autopilot**: Partially tested. Resource quota enforcement by Autopilot may conflict with KubeSynapse's tenant quota management. Use `agentRuntime.storage.size` and `resources.*` settings to stay within Autopilot limits.

---

## Version Support Policy

- **Current**: Latest release (v1.0.0) supports K8s 1.25–1.32
- **Deprecation**: 12 months notice before dropping a K8s version
- **Security patches**: Critical CVEs backported to previous minor version for 6 months
- **K8s version alignment**: KubeSynapse aims to support the 8 most recent K8s minor versions

---

## What's Tested vs Planned

### Tested (CI-verified on every PR)
- ✅ Kind clusters: 1.25, 1.27, 1.29, 1.31, 1.32
- ✅ Helm install → health check → agent create → reconcile → cleanup
- ✅ All 13 CRDs install and validate

### Planned (roadmap)
- 🧪 EKS (AWS) — Q2 2026
- 🧪 GKE (Google Cloud) — Q2 2026
- 🧪 AKS (Azure) — Q2 2026
- 🧪 k3s production config — Q2 2026
- 🧪 OpenShift — Q3 2026
- 🧪 Rancher RKE2 — Q3 2026
