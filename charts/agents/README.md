# Pre-built Agent Charts

This directory contains starter Helm charts that install a single `AIAgent`
custom resource for common roles:

- `k8s-agent`
- `code-reviewer`
- `devops-agent`

Each chart exposes the main `AIAgent` fields through `values.yaml`, including:

- `agent.model`
- `agent.policyRef`
- `agent.runtime`
- `agent.storage`
- `agent.enableGVisor`
- `agent.skills`
- `agent.mcpServers`
- `agent.mcpSidecars`
- `agent.gitConfig`
- `agent.githubConfig`
- `agent.a2a`
- `agent.allowedNamespaces`

## Install examples

```bash
helm install k8s-agent ./charts/agents/k8s-agent -n default
helm install code-reviewer ./charts/agents/code-reviewer -n default
helm install devops-agent ./charts/agents/devops-agent -n default
```

## Override examples

```bash
helm install code-reviewer ./charts/agents/code-reviewer \
  -n default \
  --set agent.policyRef=strict-enterprise-policy \
  --set agent.model=gpt-4
```

```bash
helm install k8s-agent ./charts/agents/k8s-agent \
  -n tenant-a \
  --set agent.allowedNamespaces.from=All
```

Use `helm template` first if you want to inspect the generated `AIAgent`
manifest before applying it.
