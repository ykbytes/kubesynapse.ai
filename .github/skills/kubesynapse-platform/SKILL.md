# KubeSynapse Platform Operations

## When to Apply

Use this skill when operating inside the KubeSynapse Kubernetes AI platform — deploying resources, debugging agents, managing workflows, or interacting with the KubeSynapse control plane.

## Environment Awareness

You are running inside a Kubernetes pod managed by KubeSynapse. Key environment variables:

- `KubeSynapse_AGENT_NAME` — your agent identity
- `KubeSynapse_NAMESPACE` — your namespace scope
- `KubeSynapse_API_GATEWAY_URL` — internal API gateway endpoint
- `A2A_OUTBOUND_TARGETS` — JSON list of peer agents you can invoke
- `OPENCODE_MCP_CONNECTIONS_JSON` — available MCP servers
- `GIT_REPO_URL` — shared git repository (if configured)

## Rules

### 1. Namespace Scoping
- You are scoped to `KubeSynapse_NAMESPACE`. Cross-namespace operations require explicit namespace references.
- Never assume you have cluster-admin privileges. Check RBAC before attempting writes.

### 2. Resource Discovery
- To discover KubeSynapse CRDs in your namespace: `kubectl get aiagents,agentworkflows,agentpolicies,mcpconnections -n $KubeSynapse_NAMESPACE`
- To check operator health: `kubectl get pods -n kubesynapse -l app.kubernetes.io/component=operator`
- To view agent logs: `kubectl logs -n $KubeSynapse_NAMESPACE <pod-name> -f`

### 3. A2A Communication
- Use `@agentname` to invoke peer agents. Only invoke agents listed in `A2A_OUTBOUND_TARGETS`.
- Always include full context in A2A messages: file paths, error messages, task scope.
- A2A sessions are stateless — peers don't remember previous conversations.

### 4. MCP Server Usage
- Run `opencode mcp list` to discover available MCP servers.
- Prefer MCP servers over bash hacks for external integrations.
- If an MCP server is unavailable, fall back to bash with explicit error reporting.

### 5. Session Continuity
- Save important context to the memory tool with type='checkpoint' after major milestones.
- Check memory first when you don't recall previous conversation context.
- Your todowrite plan survives compaction — keep it updated as your primary state.

### 6. Error Handling
- Report FULL error messages, not summaries.
- Include your diagnosis and attempted fixes.
- For K8s API errors, include the resource kind, name, namespace, and verb.

## Common Operations

### Check Agent Status
```bash
kubectl get aiagent <name> -n $KubeSynapse_NAMESPACE -o yaml
```

### Check Workflow Status
```bash
kubectl get agentworkflow <name> -n $KubeSynapse_NAMESPACE -o jsonpath='{.status.phase}'
```

### View Operator Logs
```bash
kubectl logs -n kubesynapse -l app.kubernetes.io/component=operator --tail=100
```

### List MCP Connections
```bash
kubectl get mcpconnection -n $KubeSynapse_NAMESPACE
```

## Anti-Patterns

- Don't assume kubectl is available — check first with `which kubectl`.
- Don't silently swallow errors from `kubectl` or API calls.
- Don't invoke A2A targets that aren't in your configured outbound list.
- Don't modify resources in other namespaces without explicit user confirmation.
