# k8s-agent

Installs a Kubernetes-focused `AIAgent` tuned for cluster inspection,
manifest analysis, and safe operational guidance.

The default values attach the `kubernetes` MCP sidecar, so the agent can
inspect live cluster state immediately after install instead of falling back to
prompt-only guidance.

```bash
helm install k8s-agent ./charts/agents/k8s-agent -n default
```
