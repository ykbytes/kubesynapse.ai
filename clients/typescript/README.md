# KubeSynapse TypeScript SDK

`@kubesynapse/sdk` — fully typed TypeScript client for the KubeSynapse API Gateway.

## Installation

```bash
npm install @kubesynapse/sdk
```

## Client

```typescript
import { KubeSynapseClient } from "@kubesynapse/sdk";

const client = new KubeSynapseClient({
  baseURL: "http://localhost:8080",
  token: "dev-shared-token-change-in-production",
});

// Health
await client.health();

// Agents CRUD
const agents = await client.listAgents();
const agent = await client.getAgent("my-agent");
await client.createAgent({...});
await client.updateAgent("my-agent", {...});
await client.deleteAgent("my-agent");

// Workflows
const workflows = await client.listWorkflows();
await client.triggerWorkflow("my-workflow", { input: "data" });

// Policies
const policies = await client.listPolicies();

// Invoke
const response = await client.invoke("my-agent", "Explain Kubernetes");
for await (const delta of client.stream("my-agent", "Build a REST API")) {
  process.stdout.write(delta);
}

// Traces
const executions = await client.listExecutions();
const execution = await client.getExecution("run-id");
```

## Timeouts & Error Handling

All methods accept an optional `AbortController` signal:

```typescript
const controller = new AbortController();
setTimeout(() => controller.abort(), 5000);
await client.invoke("my-agent", "Hello", { signal: controller.signal });
```

Errors surface as `KubeSynapseError` with `status`, `code`, and `message` fields.

## React / Next.js Example

```tsx
"use client";
import { KubeSynapseClient } from "@kubesynapse/sdk";
import { useEffect, useState } from "react";

export default function AgentChat() {
  const [reply, setReply] = useState("");
  const client = new KubeSynapseClient({ baseURL: "/api" });

  useEffect(() => {
    client.stream("my-agent", "Hello").then(async (stream) => {
      for await (const delta of stream) {
        setReply((prev) => prev + delta);
      }
    });
  }, []);

  return <pre>{reply}</pre>;
}
```

For full API documentation see the [API Gateway README](../api-gateway/README.md).
