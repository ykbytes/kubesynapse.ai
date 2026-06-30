# KubeSynapse API Reference

**Who is this for:** Developers integrating with KubeSynapse via REST API, A2A JSON-RPC, or SDKs.

**Base URL:** `http://<gateway-host>/api/v1`  
**Current Version:** `v1`  
**Content-Type:** `application/json` (unless noted)

---

## Table of Contents

- [Authentication](#authentication)
- [Health and Readiness](#health-and-readiness)
- [Agents](#agents)
- [Chat Sessions](#chat-sessions)
- [Workflows](#workflows)
- [Optimization ROI Lab](#optimization-roi-lab)
- [Webhooks & Triggers](#webhooks--triggers)
- [MCP Connections](#mcp-connections)
- [Policies](#policies)
- [Approvals](#approvals)
- [Tenants](#tenants)
- [A2A Protocol](#a2a-protocol)
- [Observability](#observability)
- [Incidents](#incidents)
- [Traces](#traces)
- [LLM and Providers](#llm-and-providers)
- [Admin and Usage](#admin-and-usage)
- [Intelligence & Collectors](#intelligence--collectors)
- [Skills Catalog](#skills-catalog)
- [Error Responses](#error-responses)
- [Rate Limiting](#rate-limiting)

---

## Authentication

KubeSynapse supports multiple authentication modes configured at install time.

| Mode | Header / Mechanism | Endpoint Requirement |
|------|--------------------|----------------------|
| **Shared Token** | `Authorization: Shared <token>` | All endpoints |
| **JWT** | `Authorization: Bearer <jwt>` | All endpoints |
| **OIDC** | `Authorization: Bearer <id_token>` | All endpoints |
| **Session Cookie** | `Cookie: session=<cookie>` | Browser-based UI |

### Auth Endpoints

#### `GET /api/v1/auth/config`

Returns current authentication configuration.

**Response:**

```json
{
  "mode": "oidc",
  "oidc_issuer": "https://auth.example.com",
  "oidc_audience": "KubeSynapse",
  "local_auth_enabled": true
}
```

#### `POST /api/v1/auth/register`

Register a local user (when local auth is enabled).

**Request body:**

```json
{
  "username": "alice",
  "password": "secure-password",
  "email": "alice@example.com",
  "display_name": "Alice",
  "role": "operator",
  "allowed_namespaces": ["default", "team-a"]
}
```

#### `POST /api/v1/auth/login`

Authenticate and receive tokens.

**Request body:**

```json
{
  "username": "alice",
  "password": "secure-password"
}
```

**Response:**

```json
{
  "access_token": "eyJ...",
  "refresh_token": "dGh...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

#### `POST /api/v1/auth/refresh`

Refresh an access token.

**Request body:**

```json
{
  "refresh_token": "dGh..."
}
```

#### `POST /api/v1/auth/logout`

Invalidate the current session.

#### `GET /api/v1/auth/me`

Return the current user's profile.

#### `POST /api/v1/auth/change-password`

Change the current user's password.

#### `GET /api/v1/auth/oidc/start/{provider_id}`

Start an OIDC login flow (PKCE) for the given provider.

#### `GET /api/v1/auth/oidc/callback/{provider_id}`

OIDC callback endpoint — handles the authorization code exchange.

#### `GET /api/v1/auth/saml/start/{provider_id}`

Start a SAML SP-initiated login flow.

#### `GET /api/v1/auth/saml/metadata/{provider_id}`

Return SAML SP metadata XML for the given provider.

---

## Health and Readiness

#### `GET /health` (root level, no auth)

Unauthenticated health check used by load balancers and the operator's runtime readiness probe.

**Response:**
```json
{
  "status": "healthy",
  "service": "kubesynapse-api-gateway"
}
```

#### `GET /api/v1/health`

Gateway health check.

**Response:**

```json
{
  "status": "healthy",
  "gateway": "KubeSynapse",
  "auth_mode": "oidc"
}
```

#### `GET /api/v1/ready`

Readiness probe including database connectivity.

**Response (200):**

```json
{
  "status": "ready",
  "gateway": "KubeSynapse",
  "checks": {
    "database": "ok"
  }
}
```

**Response (503) when degraded:**

```json
{
  "status": "degraded",
  "checks": {
    "database": "error"
  }
}
```

#### `GET /api/v1/system/health`

Comprehensive system health across all subsystems.

**Response:**

```json
{
  "status": "healthy",
  "namespace": "default",
  "checks": {
    "database": {"status": "ok"},
    "kubernetes": {"status": "ok"},
    "resources": {
      "agents": {"total": 3, "by_phase": {"running": 3}},
      "workflows": {"total": 1, "by_phase": {"completed": 1}}
    }
  }
}
```

---

## Agents

#### `GET /api/v1/agents`

List agents in a namespace.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `namespace` | string | `default` | Target namespace |

**Response:**

```json
[
  {
    "name": "onboarding-bot",
    "namespace": "default",
    "runtime_kind": "opencode",
    "model": "gpt-4o",
    "status": "running"
  }
]
```

#### `POST /api/v1/agents`

Create a new agent.

**Request body:**

```json
{
  "name": "onboarding-bot",
  "runtime_kind": "opencode",
  "system_prompt": "You are a friendly DevOps onboarding assistant.",
  "model": "gpt-4o",
  "storage_size": "1Gi"
}
```

#### `GET /api/v1/agents/{agent_name}`

Get detailed agent information.

#### `GET /api/v1/agents/{agent_name}/discover`

Discover A2A peers and capabilities for an agent.

#### `PATCH /api/v1/agents/{agent_name}`

Update agent configuration.

**Request body:**

```json
{
  "system_prompt": "Updated prompt...",
  "model": "gpt-4o-mini"
}
```

#### `DELETE /api/v1/agents/{agent_name}`

Delete an agent.

**Response:**

```json
{
  "status": "deleted",
  "kind": "agent",
  "name": "onboarding-bot",
  "namespace": "default"
}
```

#### `POST /api/v1/agents/{agent_name}/clone`

Clone an existing agent.

**Query parameters:**

| Name | Type | Description |
|------|------|-------------|
| `new_name` | string | Optional custom name for the clone |

#### `POST /api/v1/agents/{agent_name}/invoke`

Invoke an agent with a prompt.

**Request body:**

```json
{
  "prompt": "How do I rotate a Kubernetes secret?",
  "thread_id": "",
  "model": "",
  "system": ""
}
```

**Response:**

```json
{
  "response": "To rotate a secret...",
  "status": "completed",
  "thread_id": "abc123...",
  "model": "gpt-4o",
  "policy_name": "default-policy"
}
```

#### `POST /api/v1/agents/{agent_name}/invoke/stream`

Invoke an agent with Server-Sent Events streaming.

**Response:** `text/event-stream` with JSON chunks.

#### `POST /api/v1/agents/{agent_namespace}/{agent_name}/invoke`

Invoke with explicit namespace in path.

#### `POST /api/v1/agents/{agent_name}/git-credentials`

Create git credential secret for an agent.

**Request body:**

```json
{
  "auth_method": "token",
  "token": "ghp_..."
}
```

#### `GET /api/v1/agents/{agent_name}/git-credentials`

Get git credential metadata (no secrets exposed).

#### `DELETE /api/v1/agents/{agent_name}/git-credentials`

Delete git credential secret.

#### `POST /api/v1/agents/{agent_name}/github-credentials`

Create GitHub MCP credential secret.

#### `GET /api/v1/agents/{agent_name}/github-credentials`

Get GitHub credential metadata.

#### `DELETE /api/v1/agents/{agent_name}/github-credentials`

Delete GitHub credential secret.

#### `GET /api/v1/agents/{agent_name}/todo`

Fetch the agent's current todo list (ETag-conditional for polling).

#### `GET /api/v1/agents/{agent_name}/diff`

Get unified diff of pending file changes.

#### `GET /api/v1/agents/{agent_name}/question`

List pending question requests that require user input.

#### `POST /api/v1/agents/{agent_name}/question/{request_id}/reply`

Reply to a pending question request.

#### `POST /api/v1/agents/{agent_name}/question/{request_id}/reject`

Reject a pending question request without answering.

#### `GET /api/v1/agents/{agent_name}/artifacts/list`

List workspace files for the agent.

#### `GET /api/v1/agents/{agent_name}/artifacts/download`

Download a single workspace artifact.

**Query parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `path` | string | *(required)* | File path within the workspace |

#### `GET /api/v1/agents/{agent_name}/artifacts/zip`

Download the full workspace as a ZIP archive.

#### `GET /api/v1/agents/{agent_name}/logs`

Get agent pod logs.

**Query parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `tail` | int | `100` | Number of lines from the tail |

#### `GET /api/v1/agents/{agent_name}/logs/stream`

SSE stream of agent pod logs (follow mode).

#### `GET /api/v1/agents/{agent_name}/memory`

List durable memory records for the agent.

---

## Chat Sessions

Chat sessions are stored in PostgreSQL and owned by the authenticated user.

#### `GET /api/v1/chat-sessions`

List chat sessions for a specific agent.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `agent_name` | string | *(required)* | Agent whose sessions should be listed |
| `namespace` | string | `default` | Target namespace |

#### `POST /api/v1/chat-sessions`

Create a new chat session.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `namespace` | string | `default` | Target namespace |

**Request body:**

```json
{
  "title": "Secret Rotation Help",
  "agent_name": "onboarding-bot"
}
```

#### `GET /api/v1/chat-sessions/{session_id}/messages`

Get messages for a session.

#### `PUT /api/v1/chat-sessions/{session_id}/messages`

Replace the full stored message list for a session.

**Request body:**

```json
{
  "messages": [
    {
      "message_id": "msg-1",
      "role": "user",
      "content": "How do I rotate a secret?",
      "status": "complete"
    },
    {
      "message_id": "msg-2",
      "role": "assistant",
      "content": "Use kubectl create secret ...",
      "status": "complete"
    }
  ]
}
```

#### `PATCH /api/v1/chat-sessions/{session_id}`

Update session metadata.

**Request body:**

```json
{
  "title": "Updated session title"
}
```

#### `DELETE /api/v1/chat-sessions/{session_id}`

Delete a chat session.

#### `PATCH /api/v1/memory/{record_id}`

Update a durable memory record owned by the current user.

**Request body:**

```json
{
  "promoted": true,
  "topic": "repo-convention",
  "content": "Use the repo root Make targets first."
}
```

#### `DELETE /api/v1/memory/{record_id}`

Delete a durable memory record owned by the current user.

---

## Workflows

#### `GET /api/v1/workflows`

List workflows.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `namespace` | string | `default` | Target namespace |

#### `POST /api/v1/workflows`

Create a workflow.

**Request body:**

```json
{
  "name": "deploy-pipeline",
  "steps": [
    {"name": "validate", "agent": "lint-bot", "depends_on": []},
    {"name": "deploy", "agent": "deploy-bot", "depends_on": ["validate"]}
  ]
}
```

#### `GET /api/v1/workflows/{workflow_name}`

Get workflow details.

#### `PATCH /api/v1/workflows/{workflow_name}`

Update a workflow.

#### `DELETE /api/v1/workflows/{workflow_name}`

Delete a workflow.

#### `POST /api/v1/workflows/{workflow_name}/trigger`

Trigger workflow execution.

**Request body:**

```json
{
  "input": {"environment": "staging"}
}
```

#### `POST /api/v1/workflows/{workflow_name}/retry-failed`

Retry failed steps in a workflow.

#### `POST /api/v1/workflows/{workflow_name}/cancel`

Cancel a running workflow.

#### `GET /api/v1/workflows/{workflow_name}/status/stream`

Stream workflow status updates via SSE.

#### `GET /api/v1/workflows/{workflow_name}/activities/stream`

SSE stream of real-time journal events (step transitions, approval requests, retries).

#### `GET /api/v1/workflows/{workflow_name}/runs`

List workflow runs.

#### `GET /api/v1/workflows/{workflow_name}/runs/{run_id}/trace`

Get trace for a specific run.

#### `GET /api/v1/workflows/{workflow_name}/runs/{run_id}/export`

Export run data.

#### `GET /api/v1/workflows/{workflow_name}/logs`

Get workflow logs.

#### `GET /api/v1/workflows/{workflow_name}/logs/stream`

Stream workflow logs.

#### `GET /api/v1/workflows/{workflow_name}/next-action`

Get the next recommended action for a workflow.

---

## MCP Connections

#### `GET /api/v1/mcp/connections`

List MCP connections.

#### `POST /api/v1/mcp/connections`

Create an MCP connection.

**Request body:**

```json
{
  "name": "github-mcp",
  "type": "github",
  "config": {
    "api_url": "https://api.github.com"
  }
}
```

#### `GET /api/v1/mcp/connections/{connection_id}`

Get connection details.

#### `PATCH /api/v1/mcp/connections/{connection_id}`

Update a connection.

#### `DELETE /api/v1/mcp/connections/{connection_id}`

Delete a connection.

#### `POST /api/v1/mcp/connections/{connection_id}/validate`

Validate connection health.

#### `POST /api/v1/mcp/connections/{connection_id}/oauth/start`

Initiate OAuth flow.

#### `GET /api/v1/mcp/connections/{connection_id}/oauth/callback`

OAuth callback handler.

#### `POST /api/v1/mcp/connections/{connection_id}/oauth/refresh`

Refresh OAuth token.

#### `GET /api/v1/mcp/connections/{connection_id}/bindings`

List agents bound to this connection.

#### `GET /api/v1/mcp/registry`

List available MCP servers in the registry.

#### `GET /api/v1/mcp/registry/{server_id}`

Get registry server details.

#### `GET /api/v1/mcp/categories`

List MCP categories.

#### `GET /api/v1/mcp/stats`

Get MCP usage statistics.

#### `GET /api/v1/mcp-hub/servers`

List MCP hub server instances.

#### `GET /api/v1/mcp/profiles`

List curated MCP profiles with resolved connection statuses.

---

## Policies

#### `GET /api/v1/policies`

List policies in a namespace.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `namespace` | string | `default` | Target namespace |

#### `POST /api/v1/policies`

Create a policy.

**Request body:**

```json
{
  "name": "secure-policy",
  "input_guardrails": {
    "block_prompt_injection": true,
    "blocked_patterns": ["password", "secret_key"],
    "max_input_tokens": 4096
  },
  "output_guardrails": {
    "mask_pii": true,
    "max_output_tokens": 4096
  },
  "allowed_models": ["gpt-4o", "gpt-4o-mini"],
  "allowed_mcp_servers": ["github", "kubernetes"],
  "mcp_require_hitl": true
}
```

#### `GET /api/v1/policies/{policy_name}`

Get policy details.

#### `PATCH /api/v1/policies/{policy_name}`

Update a policy.

#### `DELETE /api/v1/policies/{policy_name}`

Delete a policy.

---

## Approvals

#### `GET /api/v1/approvals/{approval_name}`

Get approval request details.

**Response:**

```json
{
  "name": "deploy-prod-001",
  "namespace": "default",
  "decision": "pending",
  "agent_name": "deploy-bot",
  "action": "apply-manifest",
  "requested_at": "2026-04-27T10:00:00Z"
}
```

#### `PATCH /api/v1/approvals/{approval_name}`

Record an approval decision.

**Request body:**

```json
{
  "decision": "approved",
  "reason": "Verified by SRE team"
}
```

## Tenants

Tenants are managed as Kubernetes `AgentTenant` CRDs. The platform does not expose dedicated REST endpoints for tenant CRUD; use `kubectl` or the Kubernetes API directly.

#### Example: Create a tenant

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentTenant
metadata:
  name: team-alpha
spec:
  tenantName: team-alpha
  namespace: team-alpha
  resourceQuota:
    maxCPU: "10"
    maxMemory: "20Gi"
    maxPods: 5
  allowedModels:
    - gpt-4o
    - gpt-4o-mini
  adminUsers:
    - alice@example.com
```

```bash
kubectl apply -f tenant.yaml
```

The admin user flow can also create `AgentTenant` resources automatically. When an admin
creates or updates a non-admin local user through `/api/v1/admin/users`, the gateway reconciles
an `AgentTenant` named `user-<slug>` that targets the user's dedicated namespace.

#### List tenants

```bash
kubectl get agenttenants
```

---

## A2A Protocol

KubeSynapse implements the A2A (Agent-to-Agent) protocol over JSON-RPC 2.0.

### Agent Card

#### `GET /.well-known/agent-card.json`

Retrieve an agent's capability advertisement.

**Query parameters:**

| Name | Type | Description |
|------|------|-------------|
| `assistant_id` | string | Agent name or identifier |
| `namespace` | string | Agent namespace |

### JSON-RPC Endpoint

#### `POST /api/v1/a2a/{assistant_id}`

Send a JSON-RPC message to an agent.

**Headers:**

| Name | Value |
|------|-------|
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <token>` |

**Request body (message/send):**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "How do I rotate a TLS certificate?"}]
    }
  }
}
```

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "task-001",
    "status": "completed",
    "artifacts": [
      {"type": "text", "text": "To rotate a TLS certificate..."}
    ]
  }
}
```

### Supported Methods

| Method | Description |
|--------|-------------|
| `message/send` | Send a message and receive a complete response |
| `message/stream` | Send a message and receive streaming SSE response |
| `tasks/get` | Retrieve task status by ID |

---

## Optimization ROI Lab

Optimization studies use historical workflow traces and source manifests to create a separate candidate bundle. The source `AgentWorkflow` and its agents are never edited. Estimated gains are hypotheses; verified gains come only from candidate trial runs that pass the proof gate.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/optimizations/studies` | Persist a baseline study from selected workflow runs and server-ranked opportunities. |
| `GET` | `/api/v1/optimizations/studies` | List studies, optionally filtered by namespace or workflow. |
| `GET` | `/api/v1/optimizations/studies/{study_id}` | Retrieve a study, candidates, trials, optimizer audit, and proof state. |
| `POST` | `/api/v1/optimizations/studies/{study_id}/candidates/generate` | Generate, validate, and persist a copied candidate manifest bundle. |
| `GET` | `/api/v1/optimizations/candidates/{candidate_id}/manifest` | Download the exact persisted candidate bundle as multi-document YAML. |
| `POST` | `/api/v1/optimizations/candidates/{candidate_id}/approval` | Record the administrator approval decision. |
| `POST` | `/api/v1/optimizations/candidates/{candidate_id}/apply` | Dry-run or apply only the copied candidate resources. |
| `POST` | `/api/v1/optimizations/candidates/{candidate_id}/run` | Trigger a candidate trial and retain its run linkage. |
| `POST` | `/api/v1/optimizations/candidates/{candidate_id}/trials` | Record or link trial evidence. |
| `GET` | `/api/v1/optimizations/studies/{study_id}/comparison` | Return baseline, estimate, candidate, per-step, and per-tool comparisons. |
| `GET` | `/api/v1/optimizations/studies/{study_id}/roi` | Return proof status and measured cost, token, time, and tool-call deltas. |
| `GET` | `/api/v1/optimizations/studies/{study_id}/dataset` | Export the study's redacted replay/evaluation dataset. |
| `POST` | `/api/v1/optimizations/candidates/{candidate_id}/promotion` | Promote a candidate after approval and proof requirements pass. |

Candidate generation accepts a topology mode. Preserve mode keeps step names, order, types, contracts, and agent references. An explicit administrator-approved topology rewrite may consolidate or reorder work only when the request contains a capability-equivalence map and the generated bundle passes contract, privilege, secret, namespace, and output checks.

Each generated candidate stores an observable optimizer trace: runtime status, explicit skill-file load events, reasoning summaries exposed by the runtime, tool activity, artifacts, referenced resources, visible final response, and candidate validation outcome. This audit data does not expose hidden model chain-of-thought.

The manifest download response uses `Content-Type: application/yaml` and `Content-Disposition: attachment`. It is the persisted candidate submitted to validation, not a regenerated preview.

## Webhooks & Triggers

KubeSynapse can react to external events through **WebhookReceiver** and **WorkflowTrigger** CRDs.
External systems POST signed payloads; the gateway validates HMAC signatures, rate limits,
and IP allowlists before creating a trigger execution record. The operator then claims the
record atomically and dispatches to the target workflow or agent.

### Webhook Receivers

#### `GET /api/v1/webhooks`

List webhook receivers.

#### `POST /api/v1/webhooks`

Create a webhook receiver (status 201).

#### `GET /api/v1/webhooks/{name}`

Get a webhook receiver by name.

#### `PUT /api/v1/webhooks/{name}`

Update a webhook receiver.

#### `DELETE /api/v1/webhooks/{name}`

Delete a webhook receiver (status 204).

#### `POST /api/v1/webhooks/{name}/invoke`

Public webhook invocation. Payload must be HMAC-SHA256 signed with the receiver's secret.

**Headers:**
| Name | Description |
|------|-------------|
| `X-kubesynapse-Signature` | HMAC-SHA256 of the body |
| `X-kubesynapse-Timestamp` | Unix timestamp (must be within 5 min of server clock) |

Supported ``namespaced`` variants: `/api/v1/namespaces/{namespace}/webhooks/...`

#### `POST /api/v1/webhooks/{name}/generate-secret`

Generate a new HMAC secret for the webhook receiver.

#### `GET /api/v1/webhooks/{name}/history`

List webhook invocation history.

#### `GET /api/v1/webhooks/events/stream`

SSE stream of real-time webhook events.

### Workflow Triggers

#### `GET /api/v1/workflow-triggers`

List workflow triggers.

#### `POST /api/v1/workflow-triggers`

Create a workflow trigger (status 201).

#### `GET /api/v1/workflow-triggers/{name}`

Get a workflow trigger.

#### `PUT /api/v1/workflow-triggers/{name}`

Update a workflow trigger.

#### `DELETE /api/v1/workflow-triggers/{name}`

Delete a workflow trigger (status 204).

#### `GET /api/v1/workflow-triggers/{name}/history`

List trigger execution history.

### Dispatch & Dead-Letter

#### `GET /api/v1/webhooks/dispatched/pending`

List pending (unclaimed) trigger executions.

#### `POST /api/v1/webhooks/dispatched/{execution_id}/claim`

Atomically claim a pending execution (compare-and-set to queued). Returns 409 if another operator already claimed it.

#### `PATCH /api/v1/webhooks/dispatched/{execution_id}/status`

Update execution status and lineage metadata.

#### `GET /api/v1/webhooks/{name}/dead-letter`

List dead-letter executions for a webhook.

#### `POST /api/v1/webhooks/dead-letter/{execution_id}/replay`

Replay a dead-letter execution (status 202).

---

## Observability

#### `GET /api/v1/observability/overview`

Get observability dashboard overview.

#### `POST /api/v1/observability/targets`

Create an observation target.

#### `GET /api/v1/observability/targets/{name}`

Get target details.

#### `PATCH /api/v1/observability/targets/{name}`

Update a target.

#### `DELETE /api/v1/observability/targets/{name}`

Delete a target.

#### `POST /api/v1/observability/policies`

Create an observation policy.

#### `GET /api/v1/observability/policies/{name}`

Get policy details.

#### `PATCH /api/v1/observability/policies/{name}`

Update a policy.

#### `DELETE /api/v1/observability/policies/{name}`

Delete a policy.

#### `POST /api/v1/observability/connectors`

Create a connector plugin.

#### `GET /api/v1/observability/connectors/{name}`

Get connector details.

#### `PATCH /api/v1/observability/connectors/{name}`

Update a connector.

#### `DELETE /api/v1/observability/connectors/{name}`

Delete a connector.

---

## Incidents

Incidents represent actionable alerts from external monitoring systems (e.g., Alertmanager) or manual
creation. The operator watches incidents and can escalate, acknowledge, resolve, and auto-trigger
remediation workflows. Incidents are backed by the `AgentIncident` CRD.

#### `GET /api/v1/incidents`

List incidents.

**Query parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `namespace` | string | `default` | Target namespace |
| `status` | string | — | Filter by status (firing, acknowledged, resolved, closed) |

#### `POST /api/v1/incidents`

Create a new incident.

**Request body:**
```json
{
  "name": "prod-outage-001",
  "namespace": "default",
  "title": "High CPU on node-3",
  "severity": "critical",
  "source": "alertmanager",
  "assigned_agent": "remediation-bot",
  "escalation_timeout_minutes": 15,
  "workflow_ref": {"name": "auto-remediate", "namespace": "default"}
}
```

#### `GET /api/v1/incidents/{name}`

Get incident details.

#### `PUT /api/v1/incidents/{name}`

Upsert an incident (idempotent create or update). Same `name` returns the same `id` on consecutive calls; `updated_at` changes.

**Request body:**
```json
{
  "namespace": "default",
  "title": "High CPU on node-3",
  "severity": "critical",
  "source": "alertmanager",
  "assigned_agent": "remediation-bot",
  "alertmanager_fingerprint": "abc123..."
}
```

#### `PATCH /api/v1/incidents/{name}`

Update incident status (acknowledge, resolve, close).

**Request body:**
```json
{
  "namespace": "default",
  "status": "resolved",
  "message": "CPU returned to normal levels",
  "workflow_run_id": "wf-run-001"
}
```

#### `POST /api/v1/incidents/{name}/escalate`

Escalate an incident to a higher severity or notify the assigned agent.

#### `GET /api/v1/incidents/{name}/timeline`

Get the full event timeline for an incident (status transitions, escalations, notes).

### Alertmanager Webhook

#### `POST /api/v1/webhooks/alertmanager`

Alertmanager webhook receiver. Accepts the standard Alertmanager v4 webhook payload, creates or
upserts incidents per alert, and resolves incidents when the alert status changes to `resolved`.

When `ALERTMANAGER_WEBHOOK_SECRET` is set on the gateway, requests must carry an
`X-Alertmanager-Signature` header containing a valid HMAC of the request body. The gateway also
rate-limits the endpoint at `INCIDENT_API_RATE_LIMIT_PER_MINUTE` per actor.

---

## Traces

New integrations should use the `executions` resource paths below. Temporary compatibility aliases remain available at `GET /api/v1/traces` and `GET /api/v1/traces/{execution_id}`; they return the same payloads with `Deprecation`, `Sunset`, and `Link` headers so older callers can migrate without a hard break.

#### `GET /api/v1/traces/executions`

List workflow executions.

**Query parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `limit` | int | 50 | Page size |
| `offset` | int | 0 | Offset |
| `namespace` | string | - | Filter by namespace |
| `workflow_name` | string | - | Filter by workflow |

#### `GET /api/v1/traces/executions/{execution_id}`

Get full execution detail.

#### `GET /api/v1/traces/executions/{execution_id}/summary`

Get execution summary.

#### `GET /api/v1/traces/executions/{execution_id}/events`

Get execution events.

#### `GET /api/v1/traces/steps/{step_id}`

Get step detail with LLM and tool calls.

#### `DELETE /api/v1/traces/executions/{execution_id}`

Delete an execution and its trace data.

#### `POST /api/v1/traces/executions/{execution_id}/export/json`

Export execution as JSON.

#### `GET /api/v1/traces/executions/{execution_id}/export/html`

Export execution as self-contained HTML report.

#### `POST /api/v1/traces/batch`

Ingest trace events (internal use by operator/workers).

#### `GET /api/v1/traces/runtime-events`

Query runtime events across runs. Filterable by namespace, event_type, agent, severity, and time range.

#### `POST /api/v1/traces/runtime-events`

Ingest runtime events for the Run Intelligence layer (internal use by operator/workers).

#### `GET /api/v1/traces/{execution_id}/timeline`

Get the ordered semantic event timeline for a specific run.

#### `GET /api/v1/traces/{execution_id}/runtime-summary`

Get a summary of runtime events for a specific run.

#### `GET /api/v1/traces/export`

Export raw trace data.

---

## LLM and Providers

#### `GET /api/v1/llm/health`

LiteLLM proxy health.

#### `GET /api/v1/llm/models`

List configured models.

#### `POST /api/v1/llm/models`

Add a model.

#### `POST /api/v1/llm/models/delete`

Remove a model.

#### `GET /api/v1/llm/keys`

List LiteLLM API keys.

#### `PUT /api/v1/llm/keys`

Create or update a key.

#### `GET /api/v1/llm/providers`

List LiteLLM-backed providers grouped with configured model deployments for the Settings workspace.

#### `GET /api/v1/llm/providers/{provider}/suggestions`

Return model suggestions for a provider.

This endpoint is live-backed for providers with dynamic catalogs:

- `OPENROUTER_API_KEY`
- `OPENCODE_API_KEY`
- `OPENCODE_GO_API_KEY`
- `GITHUB_COPILOT_TOKEN`

Providers that require credentials return no live suggestions until the credential is configured.

#### `GET /api/v1/providers`

List built-in and custom provider configurations for the provider registry shown in Settings.

#### `GET /api/v1/providers/catalog`

Get the flattened provider and model catalog used by provider and model pickers.

#### `PUT /api/v1/providers/{provider_id}/credentials`

Create or update stored credentials for a provider entry.

For the built-in OpenCode providers, the expected secret-backed keys are:

- `OPENCODE_API_KEY` for OpenCode Zen
- `OPENCODE_GO_API_KEY` for OpenCode Go
- `GITHUB_COPILOT_TOKEN` for GitHub Copilot

#### `GET /api/v1/providers/{provider_id}/models`

List model entries configured for a specific provider.

#### `POST /api/v1/providers/custom`

Register a custom OpenAI-compatible provider (status 201).

**Request body:**
```json
{
  "name": "my-local-llm",
  "base_url": "http://ollama.local:11434/v1",
  "api_key": "optional-key",
  "models": ["llama3", "mistral"]
}
```

#### `DELETE /api/v1/providers/custom/{provider_id}`

Remove a custom provider.

#### `POST /api/v1/llm/providers/{provider}/models`

Associate a model with a LiteLLM provider.

#### `POST /api/v1/copilot/auth/device`

Initiate a GitHub Copilot device-code login flow. Returns a verification URI and user code.

#### `POST /api/v1/copilot/auth/poll`

Poll for GitHub Copilot device-flow completion.

#### `GET /api/v1/copilot/auth/status`

Get the current GitHub Copilot authentication status.

---

## Admin and Usage

#### `GET /api/v1/namespaces`

List namespaces accessible to the authenticated user.

#### `GET /api/v1/admin/users`

List local users (admin only).

#### `POST /api/v1/admin/users`

Create a local user (admin only).

**Request body:**

```json
{
  "username": "alice.user",
  "password": "Str0ngP4ssword!",
  "display_name": "Alice",
  "role": "operator",
  "allowed_namespaces": ["team-a"]
}
```

For non-admin roles, `allowed_namespaces` is treated as **additional namespaces**. The gateway
automatically appends the dedicated namespace `user-<slug>` and reconciles a matching `AgentTenant`.
For admin users, namespace access is normalized to `[*]`.

#### `PATCH /api/v1/admin/users/{user_id}`

Update a user (admin only).

Updating a user's role or `allowed_namespaces` also updates the dedicated tenant's `adminUsers`
membership and namespace policy. Demoting a user away from admin removes wildcard namespace access.

#### `GET /api/v1/admin/audit`

Query audit logs (admin only).

**Query parameters:**

| Name | Type | Description |
|------|------|-------------|
| `actor` | string | Filter by actor |
| `action` | string | Filter by action |
| `resource_kind` | string | Filter by resource type |
| `limit` | int | Max results |
| `offset` | int | Pagination offset |

#### `DELETE /api/v1/admin/audit/purge`

Purge old audit logs (admin only).

#### `GET /api/v1/usage/summary`

Get usage summary grouped by agent or model.

#### `GET /api/v1/usage/detail`

Get detailed usage records.

#### `GET /api/v1/export/bundle`

Export namespace resources as YAML bundle.

#### `POST /api/v1/import/bundle`

Import YAML bundle.

---

## Intelligence & Collectors

The Run Intelligence layer collects operational data, runs automated analysis scripts,
and can proactively invoke agents when anomalies are detected.

### Collectors

#### `GET /api/v1/intelligence/collectors`

List registered collectors.

#### `POST /api/v1/intelligence/collectors`

Register a new collector.

#### `DELETE /api/v1/intelligence/collectors/{collector_id}`

Unregister a collector.

#### `POST /api/v1/intelligence/collect`

Trigger an immediate collection task on all registered collectors.

### Tasks

#### `GET /api/v1/intelligence/tasks`

List collection tasks.

#### `GET /api/v1/intelligence/tasks/{task_id}`

Get task details and results.

#### `DELETE /api/v1/intelligence/tasks/{task_id}`

Delete a collection task.

### Schedules

#### `GET /api/v1/intelligence/schedules`

List scheduled collection tasks.

#### `POST /api/v1/intelligence/schedules`

Create a schedule.

**Request body:**
```json
{
  "name": "hourly-error-check",
  "cron": "0 * * * *",
  "collector_id": "prod-collector",
  "builtin": "error-spike-analysis",
  "enabled": true
}
```

#### `PUT /api/v1/intelligence/schedules/{schedule_id}`

Update a schedule.

#### `DELETE /api/v1/intelligence/schedules/{schedule_id}`

Delete a schedule.

### Alert Rules

#### `GET /api/v1/intelligence/alerts`

List alert rules.

#### `POST /api/v1/intelligence/alerts`

Create an alert rule.

#### `PUT /api/v1/intelligence/alerts/{alert_id}`

Update an alert rule.

#### `DELETE /api/v1/intelligence/alerts/{alert_id}`

Delete an alert rule.

#### `GET /api/v1/intelligence/alerts/history`

List alert firing history.

### Prompt Context Injection

#### `POST /api/v1/intelligence/prompt-context`

Fetch the latest intelligence output formatted for system prompt injection. Enables autonomous
agents to consume real-time operational data without manual context assembly.

**Request body:**
```json
{
  "collector_id": "prod-collector",
  "builtin": "error-spike-analysis"
}
```

---

## Skills Catalog

#### `GET /api/v1/skills/catalog`

List available skills in the catalog.

#### `POST /api/v1/skills/catalog/refresh`

Refresh the skills catalog from the configured sources.

#### `GET /api/v1/skills/catalog/{skill_id}`

Get skill details.

#### `GET /api/v1/skills/tools`

List available tools from registered skills.

---

## Error Responses

All errors follow a consistent schema:

```json
{
  "detail": "Human-readable error message",
  "code": "ERROR_CODE",
  "status_code": 400
}
```

### Common Status Codes

| Code | Meaning | Typical Cause |
|------|---------|---------------|
| `400` | Bad Request | Invalid JSON, missing required field |
| `401` | Unauthorized | Missing or invalid token |
| `403` | Forbidden | Insufficient role or namespace access |
| `404` | Not Found | Resource does not exist |
| `409` | Conflict | Resource already exists |
| `422` | Unprocessable Entity | Validation error in spec |
| `429` | Too Many Requests | Rate limit exceeded |
| `502` | Bad Gateway | Kubernetes API or runtime unreachable |
| `503` | Service Unavailable | Gateway not ready, database down |

---

## Rate Limiting

Rate limiting is enforced per client IP using a token-bucket algorithm.

**Response headers:**

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Requests allowed per window |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

**Default limits:**

| Endpoint Type | RPS | Burst |
|---------------|-----|-------|
| General API | 100 | 150 |
| Auth endpoints | 10 | 20 |
| Agent invoke | 50 | 100 |
| A2A JSON-RPC | 50 | 100 |

When exceeded, the API returns `429 Too Many Requests`.

---

**Last Updated:** June 5, 2026  
**Platform Version:** 1.0.0
