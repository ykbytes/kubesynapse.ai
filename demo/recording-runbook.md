# Recording Runbook

This runbook is designed to keep the recording crisp, reproducible, and honest.

## Goal

Record one strong flagship video that proves KubeSynapse is:

- Kubernetes-native
- policy-aware
- approval-capable
- observable
- useful for real engineering workflows

## Window Layout

Keep these visible during recording:

1. Browser: Web UI at `http://localhost:3000`
2. Browser: API docs or trace endpoints at `http://localhost:8080/api/v1/docs`
3. Terminal A: port-forward and status checks
4. Terminal B: `kubectl get` watchers
5. Terminal C: `agentctl`, `curl`, and webhook helpers

## Preflight Checklist

- Cluster is up and healthy
- Gateway and UI are reachable
- At least one model provider is configured and working
- `agentctl` is installed from `./cli`
- `AGENT_GATEWAY_TOKEN` is exported
- The incident webhook bundle was applied before the webhook helper is run
- If recording the Context7 release demo, outbound access to `https://mcp.context7.com/mcp` works

## Boot Sequence

### Deploy The Platform

Preferred local path:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"
```

### Port-Forward

```bash
kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080
kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 3000:80
```

### Log In

```bash
agentctl --gateway-url http://localhost:8080 auth login -u admin -p "<your-password>"
export AGENT_GATEWAY_TOKEN="<token-from-login-output>"
```

PowerShell:

```powershell
agentctl --gateway-url http://localhost:8080 auth login -u admin -p "<your-password>"
$env:AGENT_GATEWAY_TOKEN = "<token-from-login-output>"
```

## Apply The Demo Bundles

```bash
kubectl apply -f demo/platform-release/bundle.yaml
kubectl apply -f demo/incident-response/bundle.yaml
kubectl apply -f demo/cloud-architecture/bundle.yaml
kubectl apply -f demo/creative-production/bundle.yaml
```

## Watcher Commands

Run these in a dedicated terminal before recording the workflows:

```bash
kubectl get aiagents,agentworkflows,agentapprovals -n default -w
```

And in another:

```bash
kubectl get statefulsets,jobs,pods -n default -w
```

## Shot Order

### Shot 1: Show The Platform Footprint

Commands:

```bash
kubectl get aiagents,agentworkflows,agentapprovals -n default
kubectl get statefulsets,jobs,pods -n default
curl http://localhost:8080/api/v1/health
```

What to say:

- agents and workflows are resources in the cluster
- agents reconcile into runtime `StatefulSet`s
- workflows reconcile into worker `Job`s

### Shot 2: Release Readiness Workflow

Trigger:

```bash
agentctl --gateway-url http://localhost:8080 workflows trigger ingress-upgrade-release-readiness
```

What to show:

- workflow starts in UI
- runtime pods already exist for agents
- files get written in the workspace
- approval appears before the final operator brief step

Approve:

```bash
kubectl get agentapprovals -n default
agentctl --gateway-url http://localhost:8080 approvals approve <approval-name> --reason "Reviewed live on camera"
```

### Shot 3: Event-Driven Incident Workflow

Trigger via signed webhook:

```bash
./demo/incident-response/send-signed-webhook.sh
```

PowerShell:

```powershell
./demo/incident-response/send-signed-webhook.ps1
```

What to show:

- `WebhookReceiver` and `WorkflowTrigger` CRs already exist
- webhook call succeeds with a signed request
- workflow launches after trigger match
- remediation step pauses for approval

Approve:

```bash
kubectl get agentapprovals -n default
agentctl --gateway-url http://localhost:8080 approvals approve <approval-name> --reason "Approved incident stabilization"
```

### Shot 4: Cloud Architecture Workflow

Trigger:

```bash
agentctl --gateway-url http://localhost:8080 workflows trigger multi-cluster-platform-decision
```

What to show:

- structured stage boundaries
- architecture, security, and FinOps separated into roles
- final memo pauses for approval instead of pretending the answer should auto-ship

### Shot 5: Creative Production Workflow

Trigger:

```bash
agentctl --gateway-url http://localhost:8080 workflows trigger conference-launch-pack
```

What to show:

- same platform mechanics applied outside pure ops work
- artifact handoff across stages
- final launch pack approval gate

## Observability Checks

Use these after each workflow to prove the run left evidence.

List executions:

```bash
curl -H "Authorization: Bearer $AGENT_GATEWAY_TOKEN" \
  "http://localhost:8080/api/v1/traces/executions?namespace=default"
```

Inspect a timeline:

```bash
curl -H "Authorization: Bearer $AGENT_GATEWAY_TOKEN" \
  "http://localhost:8080/api/v1/traces/<execution-id>/timeline"
```

Inspect runtime summary:

```bash
curl -H "Authorization: Bearer $AGENT_GATEWAY_TOKEN" \
  "http://localhost:8080/api/v1/traces/<execution-id>/runtime-summary"
```

What to say:

- the platform stores workflow execution detail
- runtimes and workers emit semantic runtime events
- operators can inspect timeline and summary instead of guessing

## UI Beats Worth Capturing

- agent catalog
- workflow list and run detail
- pending approval appearing
- approval resolving after decision
- Execution Observatory or trace views

## Fallback Plan

If one scenario has provider or MCP trouble during recording:

1. Keep the architecture and release-readiness intro.
2. Prioritize `incident-response/` because it proves signed inbound automation, approval gates, and operations value fast.
3. Use `cloud-architecture/` if a safer non-MCP workflow is needed.
4. Keep `creative-production/` as the closer only if time allows.

## Editing Notes

- Keep the pace high.
- Cut dead time while workflows run.
- Use overlays to label CRDs, approvals, and traces.
- Do not hide approval pauses; they are a selling point.
- Do not overdub claims that the platform did not literally demonstrate.
