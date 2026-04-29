# MCP Server Usage Guide

## When to Apply

Use this skill when you need to interact with external systems (databases, APIs, search engines, cloud providers) through MCP (Model Context Protocol) servers.

## Discovery

Always discover available MCP servers before starting work:

```bash
opencode mcp list
```

Or check the environment variable:
```bash
echo $OPENCODE_MCP_CONNECTIONS_JSON | python -m json.tool
```

## Rules

### 1. Prefer MCP Over Bash
- If an MCP server can do the task, use it instead of bash commands.
- MCP servers have pre-configured auth, retry logic, and structured outputs.
- Bash commands for external APIs are fragile and insecure.

### 2. Check Server Health
Before relying on an MCP server:
```bash
opencode mcp status <server-name>
```

### 3. Handle Unavailability Gracefully
If an MCP server is unavailable:
1. Report it clearly: "MCP server X is unavailable, falling back to Y"
2. Use bash fallback only if necessary
3. Document the fallback in your todowrite plan

### 4. Common MCP Servers

| Server | Purpose | Example Usage |
|--------|---------|---------------|
| tavily-search | Web search | Find latest docs, research topics |
| postgres | Database queries | Query application database |
| kubernetes | K8s operations | List pods, check resources |
| github | GitHub API | Create issues, PRs, comments |
| slack | Slack messaging | Send notifications |

### 5. Parameter Passing
- Pass parameters as structured objects, not strings
- Include timeouts for long-running operations
- Handle pagination for list operations

### 6. Error Handling
- MCP errors include structured error codes
- Don't retry on authentication errors — report them
- Do retry on transient errors with exponential backoff

## Session Continuity with MCP

MCP server connections persist within your session but not across restarts. To maintain continuity:
- Save query results to memory if needed later
- Document which MCP servers you used and for what
- Re-discover servers after session restart

## Anti-Patterns

- Don't hardcode MCP server names — discover them dynamically.
- Don't assume all MCP servers are always available.
- Don't use MCP for tasks better suited to native tools (file ops, bash).
- Don't leak sensitive data through MCP logs.
