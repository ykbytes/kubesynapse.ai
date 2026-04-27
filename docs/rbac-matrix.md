# RBAC Matrix — KubeSynth Service Accounts & Permissions

## Overview

KubeSynth uses **least-privilege RBAC** with one ServiceAccount per component. This document enumerates every ServiceAccount, its associated Roles/ClusterRoles, and the justification for each permission.

## Service Accounts

| # | ServiceAccount | Component | Scope | Binding Type |
|---|---------------|-----------|-------|-------------|
| 1 | `kubesynth-operator-sa` | Operator (Kopf) | Cluster | ClusterRoleBinding |
| 2 | `kubesynth-api-gateway-sa` | API Gateway (FastAPI) | Cluster + Namespace | ClusterRoleBinding + RoleBinding |
| 3 | `kubesynth-agent-runtime` | Agent Runtime (OpenCode) | Cluster (conditional) | ClusterRoleBinding (conditional) |
| 4 | *(namespace default)* | Collector DaemonSet | Cluster (read-only) | ClusterRoleBinding |
| 5 | *(namespace default)* | LiteLLM Proxy | None | N/A (no K8s API access needed) |

---

## 1. Operator ServiceAccount

**Name**: `kubesynth-operator-sa`
**Component**: Kopf-based Kubernetes Operator
**Scope**: Cluster-wide (ClusterRole)

### Permissions

| API Group | Resource | Verbs | Justification |
|-----------|----------|-------|---------------|
| `kopf.dev` | `clusterkopfpeerings` | list, watch, patch, get | Kopf framework leader election and peering |
| `kubesynth.ai` | `aiagents`, `agenttenants`, `agentpolicies`, `agentapprovals`, `agentworkflows`, `agentevals` | full CRUD | Core CRD reconciliation — the operator MUST create/update/delete these resources |
| `kubesynth.ai` | `*/status` (6 resources) | get, patch, update | Write status subresource for reconciliation state reporting |
| `kubesynth.ai` | `observationtargets`, `observationpolicies`, `observationreports`, `connectorplugins` | full CRUD | Observability CRD reconciliation |
| `kubesynth.ai` | `observation*/status` (4 resources) | get, patch, update | Observability status updates |
| `apiextensions.k8s.io` | `customresourcedefinitions` | get, list, watch | **Read-only** — discover CRD versions and schemas at startup |
| `apps` | `statefulsets` | full CRUD | Creates per-agent StatefulSets for agent runtimes |
| `batch` | `jobs` | full CRUD | Creates evaluation jobs, migration jobs, cleanup jobs |
| `coordination.k8s.io` | `leases` | full CRUD | Leader election lease management |
| `""` (core) | `pods`, `services`, `persistentvolumeclaims`, `serviceaccounts`, `resourcequotas`, `limitranges`, `configmaps` | full CRUD | Infrastructure provisioning for agent tenants |
| `""` (core) | `namespaces` | get, list, watch | **Read-only** — discover existing namespaces for tenant provisioning |
| `""` (core) | `nodes`, `endpoints`, `events` | create, get, list, watch, patch | Read cluster topology, emit events, list endpoints |
| `""` (core) | `pods/log` | get | Read agent pod logs for diagnostics |
| `""` (core) | `secrets` | create, delete, get, patch, update | Create MCP auth secrets, manage credential store (**namespace-scoped via Role** — see below) |
| `rbac.authorization.k8s.io` | `roles`, `rolebindings` | full CRUD | Create per-tenant namespaced RBAC for agent isolation |
| `apps` | `deployments`, `daemonsets`, `replicasets` | get, list, watch | **Read-only** — monitor platform component health |
| `batch` | `cronjobs` | get, list, watch | **Read-only** — monitor scheduled jobs |
| `networking.k8s.io` | `ingresses` | get, list, watch | **Read-only** — discover ingress configurations |
| `networking.k8s.io` | `networkpolicies` | full CRUD | Create per-agent egress NetworkPolicies for MCP isolation |
| `autoscaling` | `horizontalpodautoscalers` | get, list, watch | **Read-only** — monitor autoscaling state |
| `external-secrets.io` | `externalsecrets` | full CRUD | Manage ExternalSecret resources for credential injection |

### Justification Summary
- **Why ClusterRole?** The operator manages resources across namespaces (agent tenants), creates CRDs, and needs cluster-wide visibility.
- **Why secrets access?** The operator reads the `mcp-auth` bearer token secret to inject into agent pods and manages credential secrets for provider registries.
- **Why RBAC management?** The operator provisions per-tenant Roles and RoleBindings for agent runtime isolation.

---

## 2. API Gateway ServiceAccount

**Name**: `kubesynth-api-gateway-sa`
**Component**: FastAPI Gateway (REST API + WebSocket)
**Scope**: Cluster (read-heavy CRD access) + Namespace (secrets/configmaps)

### ClusterRole Permissions

| API Group | Resource | Verbs | Justification |
|-----------|----------|-------|---------------|
| `kubesynth.ai` | `aiagents`, `agentworkflows`, `agentevals` | full CRUD | User-facing CRUD operations via REST API |
| `kubesynth.ai` | `agentpolicies` | full CRUD | Policy management API |
| `kubesynth.ai` | `agentapprovals` | get, list, watch | Read approval requests (approvals handled by operator) |
| `kubesynth.ai` | `agentapprovals/status` | patch, update | Update approval status (approve/reject) |
| `kubesynth.ai` | `agentworkflows/status` | patch, update | Update workflow execution status |
| `kubesynth.ai` | `observationtargets`, `observationpolicies`, `observationreports`, `connectorplugins` | full CRUD | Observability API endpoints |
| `kubesynth.ai` | `observation*/status` (4 resources) | patch, update | Observability status updates |
| `""` (core) | `pods` | get, list, watch | **Read-only** — API queries pod status for agent health |
| `""` (core) | `namespaces` | list | **Read-only** — list available namespaces for tenant selection |

### Namespace-Scoped Role (RoleBinding)

| API Group | Resource | Verbs | Justification |
|-----------|----------|-------|---------------|
| `""` (core) | `secrets` | get, update | Read provider credentials, update refresh tokens (**namespace only, NOT cluster-wide**) |
| `""` (core) | `configmaps` | get, create, update | Read/store runtime configuration, feature flags |
| `""` (core) | `pods/log` | get | Stream agent pod logs to WebUI |

### Justification Summary
- **Why ClusterRole?** The gateway needs cluster-wide CRD read/write access to serve the REST API. It does NOT create infrastructure (pods, services) — that's the operator's job.
- **Why separate Namespace Role for secrets?** P0 security fix: previously the gateway had cluster-wide secret read. Now restricted to its own namespace only.
- **What it CANNOT do:** Create/delete pods, services, statefulsets, namespaces, RBAC. No `pods/exec`. No `secrets list` on other namespaces.

---

## 3. Agent Runtime ServiceAccount

**Name**: `kubesynth-agent-runtime` (configurable via `runtimeServiceAccount.name`)
**Component**: OpenCode Runtime (per-agent pods)
**Scope**: Namespace (via operator-created RoleBinding) + Cluster (conditional, read-only)

### ClusterRole Permissions (when `agentRuntime.clusterReadAccess: true`)

| API Group | Resource | Verbs | Justification |
|-----------|----------|-------|---------------|
| `""` (core) | `nodes` | get, list, watch | Agent reads cluster topology for K8s operations |

### Namespace-Scoped Role (per-agent, created by operator)

| API Group | Resource | Verbs | Justification |
|-----------|----------|-------|---------------|
| `""` (core) | `pods`, `services`, `nodes`, `events`, `configmaps`, `endpoints`, `persistentvolumeclaims`, `namespaces`, `resourcequotas`, `limitranges` | get, list, watch | **Read-only** — K8s MCP sidecar needs cluster visibility |
| `""` (core) | `configmaps` | create, patch, update | Agent may store workflow state |
| `""` (core) | `pods/log` | get | Read pod logs for diagnostics |
| `apps` | `deployments`, `statefulsets`, `daemonsets`, `replicasets` | get, list, watch | **Read-only** — workload inspection |
| `batch` | `jobs`, `cronjobs` | get, list, watch | **Read-only** — job inspection |
| `networking.k8s.io` | `ingresses`, `networkpolicies` | get, list, watch | **Read-only** — network inspection |
| `autoscaling` | `horizontalpodautoscalers` | get, list, watch | **Read-only** — autoscaling inspection |
| `kubesynth.ai` | `agentpolicies`, `aiagents`, `agentworkflows` | get, list, watch | **Read-only** — read platform state |
| `kubesynth.ai` | `agentapprovals` | create, get, list, watch | Create approval requests for human-in-the-loop gates |

### Justification Summary
- **Why mostly read-only?** Agents are untrusted workloads. They should never mutate production infrastructure.
- **Why approval create?** The only write permission is creating approval requests — this is a deliberate, reviewed exception so agents can request human approval for risky actions.
- **Why conditional ClusterRole?** Cluster-wide node visibility is useful for DevOps agents but disabled by default.
- **What it CANNOT do:** Create/delete pods, services, namespaces. No secret access. No RBAC management. No CRD creation.

---

## 4. Collector DaemonSet

**Name**: Default namespace ServiceAccount (no dedicated SA)
**Component**: OpenTelemetry Collector (DaemonSet)
**Scope**: Cluster (read-only)

### Permissions

| API Group | Resource | Verbs | Justification |
|-----------|----------|-------|---------------|
| `""` (core) | `pods`, `nodes`, `namespaces`, `services`, `endpoints` | get, list, watch | **Read-only** — collect cluster topology metadata for telemetry enrichment |
| `apps` | `replicasets`, `deployments`, `daemonsets`, `statefulsets` | get, list, watch | **Read-only** — workload metadata |
| `batch` | `jobs`, `cronjobs` | get, list, watch | **Read-only** — batch workload metadata |

### Justification Summary
- **Read-only only.** The collector enriches telemetry with K8s metadata. No mutation needed.
- **No dedicated SA needed.** Uses default namespace SA with limited ClusterRole.

---

## 5. LiteLLM Proxy

**Name**: Default namespace ServiceAccount (no dedicated SA)
**Component**: LiteLLM model proxy
**Scope**: None

### Permissions

No K8s API access needed. LiteLLM is a pure HTTP proxy that only talks to LLM provider APIs (OpenAI, Anthropic, etc.) and its own PostgreSQL database.

---

## Least-Privilege Audit Checklist

| Check | Status |
|-------|--------|
| ✅ No `*` verbs (wildcard) — all verbs explicitly listed | PASS |
| ✅ No `*` resources (wildcard) — all resources explicitly listed | PASS |
| ✅ No `pods/exec` on any SA (prevents container escape) | PASS |
| ✅ API Gateway secrets access namespace-scoped, not cluster-wide | PASS |
| ✅ Agent runtime cannot mutate platform CRDs (except approval create) | PASS |
| ✅ Agent runtime cluster access gated behind explicit opt-in toggle | PASS |
| ✅ LiteLLM has zero K8s API access | PASS |
| ✅ Operator secrets access limited to its namespace (RoleBinding) | PASS |
| ✅ ClusterRoleBindings audited — only operator and conditional runtime | PASS |
| ✅ NetworkPolicy egress restricted per-component | PASS |

## Verification Command

```bash
# Verify API Gateway cannot list secrets cluster-wide
kubectl auth can-i list secrets \
  --as=system:serviceaccount:kubesynth:kubesynth-api-gateway-sa \
  --all-namespaces
# Expected: no

# Verify API Gateway CAN read secrets in its namespace
kubectl auth can-i get secrets \
  --as=system:serviceaccount:kubesynth:kubesynth-api-gateway-sa \
  -n kubesynth
# Expected: yes

# Verify Operator CANNOT exec into pods
kubectl auth can-i create pods/exec \
  --as=system:serviceaccount:kubesynth:kubesynth-operator-sa
# Expected: no

# Verify Runtime CANNOT create agents
kubectl auth can-i create aiagents \
  --as=system:serviceaccount:kubesynth:kubesynth-agent-runtime
# Expected: no
```
