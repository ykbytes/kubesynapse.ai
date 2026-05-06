import httpx, json, time

TOKEN = "Bearer 2qB-iqjVK3DoyI_juHwe6jqughlQhGkm_cNLbmjja4071LkpyTVMSiSFqY8ClWcN"
HEADERS = {"Authorization": TOKEN}
BASE = "http://localhost:8080"

# Send a comprehensive test batch
events = [
    {
        "event_type": "execution_started",
        "execution_id": "test-exec-full",
        "timestamp": time.time(),
        "payload": {
            "namespace": "default",
            "workflow_name": "test-full",
            "agent_name": "test-agent",
            "run_id": "test-run-full",
        }
    },
    {
        "event_type": "step_started",
        "execution_id": "test-exec-full",
        "step_id": "step-001",
        "timestamp": time.time(),
        "payload": {
            "step_name": "brainstorm",
            "step_type": "agent",
            "step_index": 0,
        }
    },
    {
        "event_type": "llm_call_completed",
        "execution_id": "test-exec-full",
        "step_id": "step-001",
        "timestamp": time.time(),
        "payload": {
            "model": "mistral/devstral-small",
            "provider": "mistral",
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "cost_usd": 0.001,
            "latency_ms": 1500,
            "prompt_preview": "You are a brainstormer...",
            "response_preview": "Here are 3 ideas...",
        }
    },
    {
        "event_type": "step_completed",
        "execution_id": "test-exec-full",
        "step_id": "step-001",
        "timestamp": time.time(),
        "payload": {
            "status": "completed",
            "outputs": {"angles": ["a", "b", "c"]},
        }
    },
    {
        "event_type": "execution_completed",
        "execution_id": "test-exec-full",
        "timestamp": time.time(),
        "payload": {
            "outputs": {"result": "success"},
            "metrics": {
                "total_steps": 1,
                "completed_steps": 1,
                "failed_steps": 0,
            }
        }
    },
]

r = httpx.post(f"{BASE}/api/traces/batch", json={"events": events}, headers=HEADERS)
print("Batch Status:", r.status_code)
print("Batch Response:", r.text)

# Now fetch the execution detail
r2 = httpx.get(f"{BASE}/api/traces/executions/test-exec-full", headers=HEADERS)
print("\nExecution Detail:")
d = json.loads(r2.text)
print(json.dumps(d, indent=2))

# Cleanup
httpx.delete(f"{BASE}/api/traces/executions/test-exec-full", headers=HEADERS)
