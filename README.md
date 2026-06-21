# KubeSynapse

KubeSynapse is a self-hosted platform for running AI agents and agentic workflows as Kubernetes resources. Agents, workflows, policies, tool connections, approvals, and execution traces are managed through CRDs and reconciled by the platform operator.

The platform is designed for teams that want agent workloads to follow the same operational model as the rest of their infrastructure: declarative manifests, isolated runtimes, auditable execution, policy controls, and cluster-native deployment.

## What You Can Do

- Define agents and workflows with Kubernetes manifests.
- Run agents in isolated OpenCode runtime pods with persistent workspaces.
- Orchestrate multi-step workflows with dependencies, retries, approvals, and run history.
- Inspect every workflow run through the Observatory: steps, logs, LLM calls, tool calls, artifacts, token usage, and timing.
- Use the Optimization ROI Lab to create copied candidate workflows, compare them against baselines, and promote only verified improvements.
- Attach MCP connections and runtime tools with namespace-scoped credentials.
- Govern execution with auth, RBAC-aware APIs, network policies, audit logs, and approval gates.

## Quickstart: Local Kind Cluster

Prerequisites: Docker, kind, kubectl, Helm, and PowerShell 7 on Windows.

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "ChangeMeStrong9!"
```

Port-forward the API gateway and UI:

```powershell
kubectl port-forward svc/kubesynapse-api-gateway -n kubesynapse 8080:8080
kubectl port-forward svc/kubesynapse-web-ui -n kubesynapse 3000:80
```

Open the console:

```powershell
Start-Process http://localhost:3000
```

Log in with:

- Username: `admin`
- Password: the value passed to `-AdminPassword`

Configure model provider credentials from the UI under Settings, or patch the platform secret for local development:

```powershell
$key = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("sk-your-provider-key"))
kubectl patch secret kubesynapse-llm-api-keys -n kubesynapse `
  --patch "{`"data`":{`"OPENAI_API_KEY`":`"$key`"}}"
```

Apply a sample policy and agent:

```powershell
kubectl apply -f examples/sample-policy.yaml
kubectl apply -f examples/sample-agent.yaml
```

## Helm Install

```bash
helm upgrade --install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse \
  --create-namespace \
  --set platformSecrets.native.litellmMasterKey="$(openssl rand -hex 32)" \
  --set platformSecrets.native.apiGatewaySharedToken="$(openssl rand -hex 32)" \
  --set platformSecrets.native.databasePassword="$(openssl rand -hex 16)" \
  --set platformSecrets.native.jwtSecret="$(openssl rand -hex 32)" \
  --set platformSecrets.native.authBootstrapAdminPassword="ChangeMeStrong9!"
```

Add provider credentials through the UI or chart values before invoking agents.

## Architecture

KubeSynapse has four main runtime layers:

| Layer | Responsibility |
| --- | --- |
| Web UI | Operations console for agents, workflows, observability, optimization, catalog, incidents, and administration. |
| API gateway | Auth, REST/SSE APIs, CRD access, trace ingestion, chat/session state, workflow history, optimization records, and audit logging. |
| Operator | Watches CRDs, provisions agent runtimes, creates workflow worker jobs, manages policies, and reports status back to Kubernetes. |
| OpenCode runtime | Executes agent sessions, emits runtime events, persists workspace state, and calls model providers through the configured gateway path. |

Shared services include PostgreSQL for durable platform data, Redis for cache/session support, NATS for async messaging, and optional vector storage for semantic memory.

## Core CRDs

| Kind | Purpose |
| --- | --- |
| `AIAgent` | Agent model, prompt, runtime, tools, MCP connections, and policy reference. |
| `AgentWorkflow` | Multi-step workflow definition with dependencies, approvals, retries, and step contracts. |
| `AgentPolicy` | Guardrails, runtime constraints, tool ceilings, and outbound access rules. |
| `AgentApproval` | Human approval records for gated actions. |
| `McpConnection` | Saved MCP connection metadata and credential binding. |
| `WebhookReceiver` | Signed inbound webhook configuration. |
| `WorkflowTrigger` | Trigger state and workflow dispatch lineage. |
| `AgentIncident` | Incident lifecycle records and remediation workflow links. |

Additional observability and tenant CRDs are installed by the Helm chart.

## Security Model

KubeSynapse is built around copied, auditable, least-privilege execution:

- Agent runtimes run as non-root containers with constrained filesystem and pod security settings.
- Runtime and gateway secrets are separated; JWT signing uses a dedicated secret.
- Model provider keys are injected through Kubernetes secrets, not stored in manifests.
- MCP credentials are namespace-scoped and attached explicitly.
- Network policies can restrict agent egress by namespace and workload.
- Workflow optimization never edits the source workflow in place; it creates candidate manifests and requires approval before apply or trial runs.
- Promotion requires preserved workflow topology, namespace safety, no secret expansion, approval, and verified trial evidence.

See [`docs/architecture-overview.md`](docs/architecture-overview.md) and [`docs/secrets-management.md`](docs/secrets-management.md) for deployment guidance.

## Optimization ROI Lab

The Optimization ROI Lab uses historical workflow runs to identify cost and latency bottlenecks, generate a copied candidate workflow, and compare it against the baseline.

The workflow is:

1. Select baseline traces.
2. Generate an optimized candidate manifest bundle.
3. Review side-by-side manifest differences.
4. Approve and run candidate trials.
5. Compare baseline versus candidate tokens, wall-clock time, tool calls, cost, and quality status.
6. Promote only after the proof gate passes.

Candidates preserve workflow topology and source model selection in v1. Prompt, context, timeout, caching, and tool-use guidance can be optimized without removing required behavior.

## CLI

Install the CLI in editable mode:

```bash
pip install -e ./cli
```

Login and use the local gateway:

```bash
agentctl --gateway http://localhost:8080 auth login -u admin -p "ChangeMeStrong9!"
agentctl agents list
agentctl workflows list
agentctl observatory traces --limit 10
```

See [`cli/README.md`](cli/README.md) for the full command reference.

## Repository Map

| Path | Contents |
| --- | --- |
| [`api-gateway/`](api-gateway/) | FastAPI gateway, auth, APIs, trace ingestion, optimization records. |
| [`operator/`](operator/) | Kubernetes operator, manifest builders, workflow orchestration. |
| [`opencode-runtime/`](opencode-runtime/) | Default agent runtime. |
| [`web-ui/`](web-ui/) | React and Vite operations console. |
| [`mcp-sidecars/`](mcp-sidecars/) | Bundled MCP sidecars. |
| [`cli/`](cli/) | `agentctl` command-line client. |
| [`charts/kubesynapse/`](charts/kubesynapse/) | Helm chart and CRDs. |
| [`examples/`](examples/) | Sample policies, agents, workflows, and demos. |
| [`docs/`](docs/) | Architecture, configuration, operations, and API documentation. |

## Development

Run targeted tests from each component:

```bash
python -m pytest api-gateway/tests -q
python -m pytest operator/tests -q
cd web-ui && npm run build
```

Build local development images:

```bash
docker build -t localhost/kubesynapse/kubesynapse-api-gateway:dev api-gateway
docker build -t localhost/kubesynapse/kubesynapse-operator:dev operator
docker build -t localhost/kubesynapse/kubesynapse-web-ui:dev web-ui
docker build -t localhost/kubesynapse/kubesynapse-opencode-rt:dev opencode-runtime
```

Load images into kind:

```bash
kind load docker-image localhost/kubesynapse/kubesynapse-api-gateway:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-operator:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-web-ui:dev --name kubesynapse-dev
kind load docker-image localhost/kubesynapse/kubesynapse-opencode-rt:dev --name kubesynapse-dev
```

## Documentation

- [`docs/getting-started.md`](docs/getting-started.md)
- [`docs/architecture-overview.md`](docs/architecture-overview.md)
- [`docs/runtime-api-spec.md`](docs/runtime-api-spec.md)
- [`docs/observability-explained.md`](docs/observability-explained.md)
- [`docs/configuration-reference.md`](docs/configuration-reference.md)
- [`docs/operator-guide.md`](docs/operator-guide.md)
- [`docs/api-reference.md`](docs/api-reference.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)

## License

KubeSynapse is licensed under the [Apache License 2.0](LICENSE).
