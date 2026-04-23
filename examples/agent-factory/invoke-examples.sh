#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:18080}"
TOKEN="${TOKEN:-minikube-dev-shared-token}"
NS="${NS:-default}"

echo "== Example 1: Ask the factory for an app-delivery bundle, but do not deploy =="
curl -sS \
  -X POST "${API_BASE}/api/agents/kubesynth-factory/invoke?namespace=${NS}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "factory_mode": "governed-bundle",
  "prompt": "Create an internal release-readiness web app for engineering managers. Produce the planning agents, implementation workflow, exact manifests, a verification runbook, final artifact checklist, and the generated workflow that could build and validate the app after approval, but do not deploy anything yet."
}
JSON

echo
echo "== Example 2: Ask for a report or book workflow without running it =="
curl -sS \
  -X POST "${API_BASE}/api/agents/kubesynth-factory/invoke?namespace=${NS}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "factory_mode": "governed-bundle",
  "prompt": "Create a practitioner handbook on operating KubeSynth in enterprise clusters. Produce the chapter plan, research workflow, editorial QA design, exact manifests, and generated workflow that could draft and review the handbook after approval, but do not run anything yet."
}
JSON

echo
echo "== Example 3: Ask for a presentation workflow without deploying it =="
curl -sS \
  -X POST "${API_BASE}/api/agents/kubesynth-factory/invoke?namespace=${NS}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "factory_mode": "governed-bundle",
  "prompt": "Create a board-level product strategy presentation with a slide storyline, speaker notes, visual asset plan, rehearsal checklist, exact manifests, and the workflow that could assemble and verify the deck package after approval."
}
JSON

echo
echo "== Example 4: Trigger the fully autonomous deploy-and-run path =="
curl -sS \
  -X POST "${API_BASE}/api/workflows/kubesynth-factory-pipeline/trigger?namespace=${NS}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "factory_mode": "fully-autonomous",
  "input": "Create a customer-support triage application for this platform. After the reviewed bundle is ready, deploy it, smoke-test it, then run the generated workflow that builds and verifies the app once I approve each step."
}
JSON

echo
echo "== Example 5: Approve a pending deployment or workflow-run step =="
echo "Replace <approval-name> with the AgentApproval created for either the deploy-bundle step or the run-generated-workflow step."
curl -sS \
  -X PATCH "${API_BASE}/api/approvals/<approval-name>?namespace=${NS}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"decision":"approved","reason":"Proceed with this reviewed factory step exactly as designed."}'

echo
echo "Use the web UI approval drawer or 'kubectl get agentapprovals -n ${NS}' to find the approval name."