# KubeSynapse Python SDK

`kubesynapse-sdk` — async-first Python client for the KubeSynapse API Gateway.

## Installation

```bash
pip install kubesynapse-sdk
```

## Async Client

```python
from KubeSynapse import KubeSynapseClient

client = KubeSynapseClient(
    base_url="http://localhost:8080",
    token="dev-shared-token-change-in-production",
)

# Health check
await client.health()

# Agents CRUD
agents = await client.list_agents()
agent = await client.get_agent("my-agent")
await client.create_agent({...})
await client.update_agent("my-agent", {...})
await client.delete_agent("my-agent")

# Workflows
workflows = await client.list_workflows()
await client.trigger_workflow("my-workflow", {"input": "data"})

# Evaluations
evals = await client.list_evals()
await client.run_eval("my-eval")

# Policies
policies = await client.list_policies()

# Invoke
response = await client.invoke("my-agent", "Explain Kubernetes")
async for delta in client.stream("my-agent", "Build a REST API"):
    print(delta, end="")

# Execution Observatory
executions = await client.list_executions()
execution = await client.get_execution("run-id")
```

## Sync Wrapper

```python
from KubeSynapse import SyncKubeSynapseClient

client = SyncKubeSynapseClient(base_url="http://localhost:8080", token="...")
print(client.health())
print(client.invoke("my-agent", "Hello"))
```

## Usage Example

```python
import asyncio
from KubeSynapse import KubeSynapseClient

async def main():
    client = KubeSynapseClient(base_url="http://localhost:8080")
    agent = await client.create_agent({
        "name": "research-assistant",
        "model": "gpt-4",
        "system_prompt": "You are a research assistant."
    })
    response = await client.invoke("research-assistant", "What is Kubernetes?")
    print(response)

asyncio.run(main())
```

For full API documentation see the [API Gateway README](../api-gateway/README.md).
