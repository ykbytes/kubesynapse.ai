# Skeptic Proof Points

Use this when someone says the demo is just another AI toy.

## Objection: "This is just a prompt wrapper"

Answer:

- Agents are `AIAgent` CRDs.
- Workflows are `AgentWorkflow` CRDs.
- The operator reconciles agents into runtime `StatefulSet`s and workflows into worker `Job`s.

What to show:

- `kubectl get aiagents,agentworkflows -n default`
- `kubectl get statefulsets,jobs -n default`

Repo evidence:

- `charts/kubesynapse/crds/aiagent-crd.yaml`
- `charts/kubesynapse/crds/agentworkflow-crd.yaml`
- `operator/builders/manifests.py`
- `operator/services/k8s.py`

## Objection: "You cannot trust agents in production"

Answer:

- KubeSynapse does not ask you to trust them blindly.
- It gives you policies, approval gates, auth boundaries, RBAC, and runtime isolation.

What to show:

- `AgentPolicy` manifests in the demo bundles
- pending `AgentApproval` resources
- the approval step pause before risky execution

Repo evidence:

- `charts/kubesynapse/crds/agentpolicy-crd.yaml`
- `charts/kubesynapse/crds/agentapproval-crd.yaml`
- `api-gateway/routers/admin.py`
- `operator/controllers/approval_controller.py`

## Objection: "If something goes wrong, you cannot debug it"

Answer:

- Workflow traces and semantic runtime events are ingested and queryable.
- Runs have timelines and summaries.
- `signal_watch` creates deterministic anomaly reports instead of pretending an LLM is the only detector.

What to show:

- `/api/v1/traces/executions`
- `/api/v1/traces/<execution-id>/timeline`
- `/api/v1/traces/<execution-id>/runtime-summary`

Repo evidence:

- `api-gateway/traces_router.py`
- `api-gateway/trace_store.py`
- `operator/runtime_events.py`
- `operator/trace_client.py`
- `operator/controllers/signal_watch.py`

## Objection: "Inbound automation is a security nightmare"

Answer:

- Webhook intake is not a blind POST.
- The gateway validates HMAC signatures, timestamps, IP allowlists, rate limits, and payload limits before matching triggers.

What to show:

- `WebhookReceiver` and `WorkflowTrigger` CRs
- the signed webhook helper script
- a successful trigger launch after validation

Repo evidence:

- `charts/kubesynapse/crds/webhookreceiver-crd.yaml`
- `charts/kubesynapse/crds/workflowtrigger-crd.yaml`
- `api-gateway/routers/webhooks.py`
- `api-gateway/auth_middleware.py`
- `api-gateway/webhook_security.py`

## Objection: "Agents will roam across the cluster"

Answer:

- Each agent gets its own runtime sandbox.
- The operator builds per-agent `NetworkPolicy` resources.
- Pod security contexts are hardened.

What to show:

- the runtime `StatefulSet`
- generated `NetworkPolicy` resources
- security overlays in the architecture diagram

Repo evidence:

- `operator/builders/manifests.py`
- `charts/kubesynapse/templates/operator-rbac.yaml`
- `charts/kubesynapse/values.yaml`

## Objection: "This is only for coding agents"

Answer:

- The same platform mechanics work for release engineering, incident response, architecture review, and creative production.
- The demos in this folder intentionally cross those boundaries.

What to show:

- the four scenario folders in `demo/`
- the workflow differences between ops, architecture, and creative work

Repo evidence:

- `examples/context7-demo-agents.yaml`
- `examples/context7-demo-workflow.yaml`
- `examples/cluster-ops-agents.yaml`
- `examples/ableton-live-web/`
- `examples/jupiter8-web-synth-bundle.yaml`

## Phrases That Land Well

- `Operate the agent, do not just prompt the agent.`
- `Approval gates are not friction. They are control points.`
- `If a run leaves no evidence, it is not production-ready.`
- `Kubernetes is the source of truth, not the chat transcript.`
