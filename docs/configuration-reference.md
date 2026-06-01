# Configuration Reference

This document describes every environment variable, Helm value, and configuration option available in KubeSynapse.

Supported runtime kinds are `opencode`, `pi`, and `mistral-vibe`.

## Table of Contents

- [Environment Variables](#environment-variables)
  - [API Gateway](#api-gateway)
  - [Operator](#operator)
  - [OpenCode Runtime](#opencode-runtime)
- [Helm Values](#helm-values)
- [Examples](#examples)

---

## Environment Variables

### API Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `API_GATEWAY_AUTH_MODE` | `shared_token` | Authentication mode: `shared_token`, `jwt`, `oidc`, `ldap`, `saml`, `hybrid` |
| `API_GATEWAY_SHARED_TOKEN` | *(required)* | Shared secret token when auth_mode is `shared_token` |
| `API_GATEWAY_JWT_SECRET` | `""` | JWT signing secret or path to private key |
| `API_GATEWAY_JWT_PUBLIC_KEY_CONFIGMAP` | `""` | ConfigMap containing JWT public key |
| `API_GATEWAY_OIDC_ISSUER` | `""` | OIDC issuer URL |
| `API_GATEWAY_OIDC_AUDIENCE` | `""` | OIDC audience/client ID |
| `API_GATEWAY_OIDC_JWKS_URL` | `""` | OIDC JWKS endpoint URL |
| `API_GATEWAY_LDAP_SERVER_URL` | `""` | LDAP server URL |
| `API_GATEWAY_LDAP_BIND_DN` | `""` | LDAP bind DN |
| `API_GATEWAY_COOKIE_SECURE` | `false` | Set `Secure` flag on cookies |
| `API_GATEWAY_COOKIE_SAMESITE` | `lax` | Cookie SameSite attribute |
| `DATABASE_HOST` | `""` | PostgreSQL host |
| `DATABASE_PORT` | `5432` | PostgreSQL port |
| `DATABASE_NAME` | `KubeSynapse` | Database name |
| `DATABASE_USER` | `""` | Database user |
| `DATABASE_PASSWORD` | `""` | Database password |
| `DATABASE_SSL_MODE` | `prefer` | SSL mode for PostgreSQL |
| `DATABASE_SQLITE_PATH` | `/tmp/KubeSynapse-gateway.db` | SQLite fallback path |

Gateway-side durable recall is policy-driven rather than controlled by dedicated memory environment variables.
Use `AgentPolicy.spec.memoryPolicy` or the chart-level `memoryPolicy.*` defaults to tune recall injection.
The `OPENCODE_MEMORY_*` variables documented below apply only to the runtime-local OpenCode memory layer.

### Operator

| Variable | Default | Description |
|----------|---------|-------------|
| `OPERATOR_NAMESPACE` | `ai-platform` | Namespace where operator runs |
| `OPERATOR_VERSION` | *(from image)* | Operator version tag |
| `API_PORT` | `8080` | Operator API port |
| `API_GATEWAY_INTERNAL_URL` | `http://api-gateway:8080` | Internal API gateway URL |
| `LITELLM_SVC` | `http://litellm:4000` | LiteLLM service URL |
| `OPERATOR_PEERING_NAME` | `""` | Multi-cluster peering name |
| `AGENT_RUNTIME_TIMEOUT_SECONDS` | `360` | Agent runtime timeout |
| `WORKER_ACTIVE_DEADLINE_SECONDS` | `14400` | Worker job active deadline |
| `WORKER_TTL_SECONDS_AFTER_FINISHED` | `3600` | Worker job TTL after completion |
| `WORKFLOW_POLL_SECONDS` | `30` | Workflow status poll interval |
| `WORKFLOW_QUEUE_STALE_SECONDS` | `300` | Workflow queue staleness threshold |
| `WORKFLOW_RUNNING_STALE_SECONDS` | `1800` | Running workflow staleness threshold |
| `AGENT_CPU_REQUEST` | `100m` | Agent container CPU request |
| `AGENT_CPU_LIMIT` | `1` | Agent container CPU limit |
| `AGENT_MEMORY_REQUEST` | `256Mi` | Agent container memory request |
| `AGENT_MEMORY_LIMIT` | `1Gi` | Agent container memory limit |
| `WORKER_CPU_REQUEST` | `100m` | Worker container CPU request |
| `WORKER_CPU_LIMIT` | `500m` | Worker container CPU limit |
| `WORKER_MEMORY_REQUEST` | `128Mi` | Worker container memory request |
| `WORKER_MEMORY_LIMIT` | `512Mi` | Worker container memory limit |
| `WORKER_ARTIFACT_SIZE` | `2Gi` | Worker artifact PVC size |
| `WORKER_ARTIFACT_STORAGE_CLASS` | `""` | Storage class for artifact PVC |
| `MCP_HUB_NAMESPACE` | `ai-platform` | Namespace for MCP hub resources |
| `MCP_AUTH_SECRET_NAME` | `mcp-auth` | Secret name for MCP auth |
| `SECRET_PROVISIONING_MODE` | `native` | Secret provisioning: `native` or `external-secrets` |
| `CLUSTER_SECRET_STORE` | `""` | External Secrets cluster store name |
| `A2A_ALLOWED_CALLERS_ENV` | `A2A_ALLOWED_CALLERS_JSON` | Env var for A2A allowed callers |
| `A2A_ALLOWED_TARGETS_ENV` | `A2A_ALLOWED_TARGETS_JSON` | Env var for A2A allowed targets |
| `A2A_REQUIRE_HITL_ENV` | `A2A_REQUIRE_HITL` | Env var for A2A HITL requirement |
| `A2A_DEFAULT_TIMEOUT_SECONDS` | `60` | A2A call default timeout |
| `A2A_MAX_TIMEOUT_SECONDS_ENV` | `A2A_MAX_TIMEOUT_SECONDS` | Env var for A2A max timeout |
| `HITL_NOTIFICATION_WEBHOOK_URL` | `""` | HITL notification webhook URL |
| `AGENT_HITL_MODE` | `enforce` | Default HITL mode: `enforce`, `audit`, `disabled` |
| `ORPHAN_PRUNING_ENABLED` | `true` | Enable orphan resource pruning |
| `OTEL_ENDPOINT` | `""` | OpenTelemetry collector endpoint |
| `SIGNAL_WATCH_INTERVAL_SEC` | `60` | Signal watch anomaly detection interval |
| `SIGNAL_WATCH_WINDOW_MINUTES` | `15` | Anomaly detection time window |
| `SIGNAL_WATCH_FAILURE_RATE` | `0.3` | Failure rate threshold (0.0-1.0) |
| `SIGNAL_WATCH_ERROR_COUNT` | `3` | Minimum error count to trigger |
| `SIGNAL_WATCH_COST_MULTIPLIER` | `3.0` | Cost outlier multiplier |
| `SIGNAL_WATCH_TOKEN_MULTIPLIER` | `3.0` | Token spike multiplier |
| `SIGNAL_WATCH_STUCK_MULTIPLIER` | `2.0` | Stuck run duration multiplier |
| `SIGNAL_WATCH_SYSTEM_NS` | `kubesynapse-system` | System agents namespace |

### Runtime Event Emission (All Runtimes)

| Variable | Default | Description |
|---|---|---|
| `RUNTIME_EVENTS_QUEUE_SIZE` | `500` | Max events in queue before dropping |
| `RUNTIME_EVENTS_BATCH_SIZE` | `50` | Events per batch flush |
| `RUNTIME_EVENTS_FLUSH_INTERVAL` | `2.0` | Flush interval (seconds) |
| `RUNTIME_EVENTS_HTTP_TIMEOUT` | `10.0` | HTTP request timeout (seconds) |

### OpenCode Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENCODE_SERVER_HOST` | `localhost` | OpenCode server host |
| `OPENCODE_SERVER_PORT` | `3000` | OpenCode server port |
| `OPENCODE_BIN` | `opencode` | OpenCode binary name |
| `OPENCODE_WORKDIR` | `/app/state` | Working directory for runtime |
| `AGENT_NAME` | `opencode-agent` | Service/agent name |
| `AGENT_NAMESPACE` | `default` | Kubernetes namespace |
| `OPENCODE_MAX_PROMPT_CHARS` | `256000` | Maximum prompt characters |
| `OPENCODE_MAX_THREAD_ID_CHARS` | `128` | Maximum thread ID length |
| `OPENCODE_MAX_MODEL_CHARS` | `256` | Maximum model name length |
| `OPENCODE_MAX_SYSTEM_PROMPT_CHARS` | `64000` | Maximum system prompt length |
| `OPENCODE_MAX_TEAM_CONTEXT_CHARS` | `32000` | Maximum team context length |
| `OPENCODE_HTTP_TIMEOUT_SECONDS` | `300` | HTTP timeout |
| `OPENCODE_AGENT_STEPS` | `128` | Default agent steps limit |
| `OPENCODE_MODEL_CONTEXT_LIMIT` | `256000` | Model context window limit |
| `OPENCODE_MODEL_OUTPUT_LIMIT` | `16384` | Model output token limit |
| `OPENCODE_MEMORY_ENABLED` | `true` | Enable memory system |
| `OPENCODE_MEMORY_MAX_THREAD_ENTRIES` | `100` | Max thread memory entries |
| `OPENCODE_MEMORY_MAX_WORKSPACE_ENTRIES` | `50` | Max workspace memory entries |
| `OPENCODE_MEMORY_DIR` | `~/.local/share/opencode-runtime/memory` | Memory directory |
| `OPENCODE_MEMORY_DEFAULT_RETENTION` | `session` | Default retention tier |
| `OPENCODE_MEMORY_CONTEXT_FENCING` | `true` | Enable memory context fencing |
| `OPENCODE_MEMORY_CONTEXT_MAX_TOKENS` | `2048` | Max memory context tokens |
| `OPENCODE_MEMORY_PRUNE_INTERVAL_HOURS` | `24` | Memory prune interval |
| `OPENCODE_MEMORY_ENTITY_EXTRACTION` | `true` | Enable entity extraction |
| `OPENCODE_MEMORY_SEMANTIC_ENABLED` | `false` | Enable the optional Qdrant semantic-memory provider |
| `OPENCODE_MEMORY_QDRANT_URL` | `http://localhost:6333` | Qdrant URL |
| `OPENCODE_MEMORY_QDRANT_COLLECTION` | `KUBESYNAPSE_memory` | Qdrant collection name |
| `OPENCODE_MEMORY_QDRANT_DIMENSION` | `768` | Embedding dimension |
| `OPENCODE_MEMORY_QDRANT_TIMEOUT` | `5.0` | Qdrant connection timeout |
| `OPENCODE_MEMORY_RELEVANCE_DECAY_HOURS` | `168` | Memory relevance decay (hours) |
| `OPENCODE_MEMORY_MIN_RELEVANCE_SCORE` | `0.3` | Minimum relevance score |

OpenCode also emits execution trace data consumed by the Execution Observatory. The
runtime currently caps extracted tool output forwarded in `tool_calls` at 40,000
characters so large results remain inspectable without creating unbounded trace rows.

---

## Helm Values

See [`values.schema.json`](../charts/kubesynapse/values.schema.json) for the complete JSON Schema.

### Key Sections

- `global` — Cluster name and image pull secrets
- `podDisruptionBudget` — HA settings
- `networkPolicy` — Network security
- `litellm` — LLM proxy configuration
- `agentRuntime` — Agent resource limits and HITL
- `opencodeRuntime` — Default OpenCode runtime image, provider, and memory settings
- `piRuntime` — Pi runtime image, provider, and bridge defaults (alpha)
- `operator` — Controller and worker settings
- `autoscaling` — HPA configuration
- `apiGateway` — Gateway replicas, auth, DB
- `webUi` — Frontend settings
- `ingress` — Ingress rules and TLS
- `memoryPolicy` — Chart-managed default durable-recall policy rendered as an `AgentPolicy`
- `platformSecrets` — Secret management mode
- `skillsCatalog` — Skills catalog JSON
- `intelligence` — Metrics and alerting
- `systemAgents` — Run Intelligence Layer system agents

### Memory Policy Defaults

The Helm chart can render a default `AgentPolicy` for durable recall:

```yaml
memoryPolicy:
  enabled: true
  name: "default-memory-policy"
  namespace: "default"
  autoPromote: true
  maxInjectedMemories: 8
  maxInjectedChars: 2400
  allowedMemoryTypes: []
```

These values control gateway-side recall injection for agents that reference the policy.
They are separate from the runtime-local `OPENCODE_MEMORY_*` settings, which still govern
the JSONL and optional semantic-memory layer inside the OpenCode runtime.

### Security & Policy Values

The Helm chart also exposes the main OpenCode hardening and policy-admission settings:

```yaml
opencodeRuntime:
  immutableConfig: true
  securityLevel: permissive
  permissionOverrides: {}
  permissionFloor: {}
  admin:
    OPENCODE_DISABLE_DEFAULT_PLUGINS: "true"

gatekeeper:
  enabled: false
  enforcementAction: deny
```

- `opencodeRuntime.securityLevel` controls the baseline permission preset. `permissive`
  remains the default for backward compatibility.
- `opencodeRuntime.permissionOverrides` layers explicit per-tool overrides on top of the preset.
- `opencodeRuntime.permissionFloor` defines a hard floor that policy resolution cannot weaken.
- `gatekeeper.enabled` installs OPA Gatekeeper as a sub-chart dependency.
- `gatekeeper.enforcementAction` switches the admission constraints between `deny`, `warn`, and `dryrun`.

At the CRD level, `AgentPolicy.spec.sealed` makes a policy immutable and
`AgentPolicy.spec.toolPolicy.adminToolCeiling` caps the maximum permission for named tools.
The operator resolves that ceiling into `OPENCODE_ADMIN_PERMISSION_CEILING_JSON` for each
runtime pod.

---

## Examples

### Development (Minimal)

```yaml
# values-dev.yaml
global:
  clusterName: "dev"

podDisruptionBudget:
  enabled: false

networkPolicy:
  enabled: false

litellm:
  enabled: true
  masterKey: "dev-litellm-key"
  resources:
    requests:
      cpu: "100m"
      memory: "512Mi"

agentRuntime:
  hitl:
    mode: disabled

operator:
  replicaCount: 1
  stateDbEnabled: false

apiGateway:
  replicaCount: 1
  auth:
    mode: shared_token
    sharedToken: "your-shared-token-here"
  db:
    host: ""
    password: ""

webUi:
  enabled: true

postgresql:
  enabled: true

platformSecrets:
  mode: native
  native:
    litellmMasterKey: "dev-litellm-key"
    apiGatewaySharedToken: "your-shared-token-here"
```

### Staging

```yaml
# values-staging.yaml
global:
  clusterName: "staging"

podDisruptionBudget:
  enabled: true

networkPolicy:
  enabled: true
  ingressNamespaces: ["ingress-nginx"]
  clusterApiCidr: "10.0.0.0/8"

litellm:
  enabled: true
  replicaCount: 1
  resources:
    requests:
      cpu: "200m"
      memory: "1Gi"

agentRuntime:
  hitl:
    mode: audit
    notificationWebhookUrl: "https://hooks.staging.example.com/hitl"

operator:
  replicaCount: 1
  runtimeTimeoutSeconds: 600
  workerActiveDeadlineSeconds: 7200

apiGateway:
  replicaCount: 2
  auth:
    mode: jwt
    jwt:
      secretName: "jwt-signing-key"
  db:
    host: "postgres.staging.svc.cluster.local"
    sslMode: "require"

ingress:
  enabled: true
  className: "nginx"
  hosts:
    - host: "staging.KubeSynapse.example.com"
      paths:
        - path: /
          pathType: Prefix
          service: webui
          port: 80

platformSecrets:
  mode: native
  native:
    litellmMasterKey: "staging-litellm-key"
    openaiApiKey: "staging-openai-key"
    dbPassword: "staging-db-password"
    apiGatewaySharedToken: "staging-shared-token"
```

### Production

```yaml
# values-production.yaml
global:
  clusterName: "production"
  imagePullSecrets:
    - name: "regcred"

podDisruptionBudget:
  enabled: true

networkPolicy:
  enabled: true
  ingressNamespaces: ["ingress-nginx", "monitoring"]
  clusterApiCidr: "10.0.0.0/8"

litellm:
  enabled: true
  replicaCount: 3
  resources:
    requests:
      cpu: "500m"
      memory: "2Gi"
    limits:
      cpu: "4"
      memory: "8Gi"

agentRuntime:
  storage:
    size: 10Gi
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "4"
      memory: "8Gi"
  hitl:
    mode: enforce
    notificationWebhookUrl: "https://hooks.production.example.com/hitl"

runtimeServiceAccount:
  name: "KubeSynapse-agent-runtime"

opencodeRuntime:
  limits:
    maxPromptChars: 256000
    modelContextLimit: 256000
    modelOutputLimit: 32768

operator:
  replicaCount: 3
  runtimeTimeoutSeconds: 360
  workerActiveDeadlineSeconds: 14400
  workerTtlSecondsAfterFinished: 3600
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "4Gi"
  workerResources:
    requests:
      cpu: "500m"
      memory: "512Mi"
    limits:
      cpu: "2"
      memory: "2Gi"
  workerArtifacts:
    size: 10Gi
    storageClassName: "fast-ssd"
  stateDbEnabled: true

autoscaling:
  enabled: true
  apiGateway:
    minReplicas: 3
    maxReplicas: 20
  litellm:
    minReplicas: 2
    maxReplicas: 10

apiGateway:
  enabled: true
  replicaCount: 3
  ingressClassName: "nginx"
  ingressHost: "KubeSynapse.example.com"
  tls:
    enabled: true
    secretName: "KubeSynapse-tls"
  auth:
    mode: oidc
    jwt:
      secretName: "jwt-signing-key"
    oidcIssuer: "https://auth.example.com"
    oidcAudience: "KubeSynapse"
    cookieSecure: true
    cookieSameSite: strict
  db:
    host: "postgres.production.svc.cluster.local"
    port: 5432
    name: "KubeSynapse"
    user: "KubeSynapse"
    sslMode: "verify-full"
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "4"
      memory: "4Gi"

webUi:
  enabled: true
  replicaCount: 3

ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  hosts:
    - host: "KubeSynapse.example.com"
      paths:
        - path: /
          pathType: Prefix
          service: webui
          port: 80
        - path: /api
          pathType: Prefix
          service: api-gateway
          port: 8080
  tls:
    - secretName: "KubeSynapse-tls"
      hosts:
        - "KubeSynapse.example.com"

platformSecrets:
  mode: external-secrets
  externalSecrets:
    clusterSecretStoreName: "vault-backend"

intelligence:
  enabled: true
  prometheusRetention: "30d"

systemAgents:
  enabled: true
  namespace: "kubesynapse-system"
  defaultModel: "gpt-4"
  defaultRuntime: "opencode"
  runInspector:
    enabled: true
    triggers:
      minFailureRate: 0.3
      minErrorCount: 3
  signalSummarizer:
    enabled: true
    triggers:
      maxSignalAgeMinutes: 30
  spendReviewer:
    enabled: true
    triggers:
      costThresholdUsd: 10.0
      tokenSpikeMultiplier: 3.0
```

---

## Validation

Validate your values against the schema:

```bash
helm lint ./charts/kubesynapse --strict
```

Or validate a custom values file:

```bash
helm lint ./charts/kubesynapse -f values-production.yaml --strict
```
