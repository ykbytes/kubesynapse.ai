import urllib.request, json, time

thread_id = 'latency-test-001'
url = 'http://localhost:8080/api/v1/agents/taskrunner/invoke'
body = json.dumps({'thread_id': thread_id, 'prompt': 'What is 2+2? Answer with just the number.', 'stream': False}).encode()
headers = {'Content-Type': 'application/json', 'X-API-Key': 'kubesynapse-local-dev', 'Authorization': 'Bearer kubesynapse-local-dev'}

req = urllib.request.Request(url, data=body, headers=headers)
start = time.time()
try:
    resp = urllib.request.urlopen(req, timeout=180)
    elapsed = time.time() - start
    data = resp.read().decode()
    result = json.loads(data)
    print(f'STATUS: {resp.status}')
    print(f'LATENCY: {elapsed:.2f}s')
    print(f'RESPONSE_STATUS: {result.get("status", "unknown")}')
    print(f'MODEL: {result.get("model", "unknown")}')
    print(f'RESPONSE_LENGTH: {len(result.get("response", ""))}')
    print(f'WARNINGS: {result.get("warnings", [])}')
    print(f'ARTIFACTS: {len(result.get("artifacts", []))}')
    print(f'TOOL_CALLS: {len(result.get("tool_calls", []))}')
    meta = result.get('metadata') or {}
    if meta:
        print(f'CONTEXT_BUDGET: {meta.get("context_budget", {})}')
        print(f'TASK_STATUS: {meta.get("task_status", "unknown")}')
        print(f'TASK_TYPE: {meta.get("task_type", "unknown")}')
    print(f'RESPONSE_PREVIEW: {result.get("response", "")[:300]}')
except Exception as e:
    elapsed = time.time() - start
    print(f'ERROR after {elapsed:.2f}s: {e}')