#!/bin/sh
curl -s -w "\nHTTP_STATUS:%{http_code}\n" http://chat-sandbox.default.svc.cluster.local:8080/invoke \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"prompt":"create the pdf","thread_id":"debug-test-005","require_approval":false,"approval_action":"Workflow creator step chat","caller_agent_name":"creator","caller_agent_namespace":"default","parent_thread_id":"wf-run-test","pre_authorized_actions":[]}'
