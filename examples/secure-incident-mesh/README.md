# Secure Incident Mesh

Fresh-install-safe multi-agent incident response example for KubeSynapse.

This example is intentionally conservative:
- it uses `litellm/gpt-5-mini`
- it does not assume any pre-created remote MCP connections
- it does not require registry-backed MCP servers such as Grafana, Azure MCP, or Context7
- it applies with `kubectl`, because the current `agentctl runs apply` path does not preserve all of the `AgentPolicy.spec.a2a` and workflow fields this example needs

This example also avoids workflow-level `requireApproval` gates on purpose. During live validation, that path depended on extra runtime conditions that are not reliably present on a fresh install, so this checked-in example focuses on the parts that are reproducible today: CRDs, least-privilege policies, multi-agent workflow execution, `agentctl` discovery/status/logs, and operator-generated `NetworkPolicy` resources.

It still demonstrates the core control-plane features that are reproducible on a fresh install:
- multiple `AIAgent` resources
- least-privilege `AgentPolicy` resources
- inbound `spec.a2a.allowedCallers`
- outbound `AgentPolicy.spec.a2a.allowedTargets`
- operator-generated `NetworkPolicy` resources
- workflow execution via `agentctl workflows status` and `agentctl workflows logs`

## Files

- `context.yaml`: incident context injected into the workflow
- `policies.yaml`: least-privilege agent policies
- `agents.yaml`: four agents with explicit caller allow-lists
- `workflow.yaml`: no-approval workflow

## Apply

```powershell
kubectl apply `
  -f .\examples\secure-incident-mesh\context.yaml `
  -f .\examples\secure-incident-mesh\policies.yaml `
  -f .\examples\secure-incident-mesh\agents.yaml `
  -f .\examples\secure-incident-mesh\workflow.yaml
```

## Port-Forward And Token

```powershell
kubectl port-forward svc/kubesynapse-api-gateway 8080:8080 -n kubesynapse

$TOKEN = [System.Text.Encoding]::UTF8.GetString(
  [Convert]::FromBase64String(
    (kubectl get secret kubesynapse-llm-api-keys -n kubesynapse -o jsonpath='{.data.API_GATEWAY_SHARED_TOKEN}')
  )
)
```

## Validate

```powershell
kubectl get aiagents -n default
kubectl get networkpolicy -n default | findstr secure-

agentctl --token $TOKEN health
agentctl --token $TOKEN agents discover secure-incident-commander

agentctl --token $TOKEN workflows status secure-incident-mesh
agentctl --token $TOKEN workflows logs secure-incident-mesh --tail 20

# Optional: direct agent check
agentctl --token $TOKEN invoke secure-signal-watch "Summarize this incident in four bullets: checkout-api latency spike, p95 3.4s, error rate 18.7%, two OOMKilled restarts."
```

## What This Workflow Does

1. `secure-signal-watch` summarizes the incident evidence from injected context.
2. `secure-remediation-planner` drafts the smallest safe remediation plan.
3. `secure-incident-commander` produces an operator handoff with risk framing.
4. `secure-status-writer` produces the final internal and customer-safe update.

The workflow does not auto-apply a cluster mutation. It produces an operator-ready command and status update instead.
