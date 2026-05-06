import httpx, json, time

test_events = [
    {
        "event_type": "execution_started",
        "execution_id": "test-exec-001",
        "timestamp": time.time(),
        "payload": {
            "namespace": "default",
            "workflow_name": "test-workflow",
            "agent_name": "test-agent",
            "run_id": "test-run-001",
        }
    }
]
r = httpx.post("http://localhost:8080/api/traces/batch",
    json={"events": test_events},
    headers={"Authorization": "Bearer 2qB-iqjVK3DoyI_juHwe6jqughlQhGkm_cNLbmjja4071LkpyTVMSiSFqY8ClWcN"})
print("Batch Status:", r.status_code)
print("Batch Response:", r.text)

r2 = httpx.get("http://localhost:8080/api/traces/executions?namespace=default&limit=50",
    headers={"Authorization": "Bearer 2qB-iqjVK3DoyI_juHwe6jqughlQhGkm_cNLbmjja4071LkpyTVMSiSFqY8ClWcN"})
d = json.loads(r2.text)
print("Total executions:", d.get("total"))
for i in d.get("items", []):
    print("  ID:", i["id"], "| status:", i["status"], "| steps:", i["step_count"])
