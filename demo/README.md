# KubeSynapse Demo Kit

This folder is a video-ready showcase package for KubeSynapse.

It is aimed at the audience that matters most for this product:

- Kubernetes operators
- platform engineers
- DevOps and SRE teams
- cloud architects
- security-minded engineering leaders
- AI workflow enthusiasts who are tired of agent slop

## What This Kit Is Trying To Prove

This is not a "look, a chatbot can do a trick" demo.

The showcase is built to prove five concrete things:

1. KubeSynapse treats agents and workflows as Kubernetes resources, not browser toys.
2. Agents run in isolated runtime sandboxes as singleton `StatefulSet`s with persistent state.
3. Workflows are explicit `AgentWorkflow` DAGs executed by worker `Job`s, with retries and approval gates.
4. Security and operations are first-class: auth, RBAC, policies, approval flows, network isolation, and signed webhooks.
5. The platform is observable: traces, runtime events, workflow history, and deterministic anomaly reporting exist in the shipped codebase.

## Why This Is Not Slop

When recording or presenting, keep returning to these points:

- The control plane is the Kubernetes API plus CRDs, not an opaque SaaS database.
- The API gateway is a real backend boundary for auth, CRUD, invoke routing, webhooks, traces, and UI metadata.
- The operator actively reconciles agents into runtime infrastructure and workflows into jobs.
- Approval gates exist because some actions should pause for humans.
- Runtime events and workflow traces exist because serious operators need evidence, not vibes.
- Webhook automation exists, but it is signed, rate-limited, IP-filterable, and auditable.
- The same platform primitives handle infra operations, architecture decisioning, and creative production handoffs.

## Recommended Showcase Order

Use the scenarios in this order for the best video arc:

1. `platform-release/`
   The strongest developer and platform-engineering story.
   It shows live documentation research, upgrade analysis, file handoff, workflow orchestration, and approval gating.

2. `incident-response/`
   The strongest SRE and DevOps story.
   It shows event-driven automation, signed webhooks, Kubernetes-sidecar tooling, approval before remediation, and crisp status output.

3. `cloud-architecture/`
   The strongest architect and cloud leadership story.
   It shows multi-agent decision support with security and cost review, without pretending architecture choices should be blind-autopiloted.

4. `creative-production/`
   The "this platform is bigger than ops" closer.
   It shows the same workflow, artifact, and approval mechanics applied to a launch-pack production workflow.

## Folder Map

- `video-showcase-script.md`
  Main flagship YouTube and LinkedIn video script.

- `recording-runbook.md`
  Preflight, exact commands, shot order, observability checks, and fallback plan.

- `youtube-linkedin-kit.md`
  Titles, thumbnail copy, video description, chapter markers, pinned comment, and LinkedIn launch copy.

- `skeptic-proof-points.md`
  Objection-handling notes tied back to real repo surfaces.

- `platform-release/`
  Release-readiness bundle for developers, platform engineers, and DevOps teams.

- `incident-response/`
  Event-driven incident bundle for SRE and on-call workflows.

- `cloud-architecture/`
  Architecture-decision bundle for cloud and platform leadership.

- `creative-production/`
  Launch-pack bundle for creative production, technical marketing, and demo ops.

## Prerequisites

These demos assume the repo's current local path:

1. Deploy KubeSynapse locally.
   Preferred path: `scripts/deploy-kind.ps1`.

2. Port-forward the gateway and UI.

```bash
kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080
kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 3000:80
```

3. Log in and export a token for `agentctl` and `curl`.

```bash
agentctl --gateway http://localhost:8080 auth login -u admin -p "<your-password>"
export AGENT_GATEWAY_TOKEN="<token-from-login-output>"
```

PowerShell:

```powershell
agentctl --gateway http://localhost:8080 auth login -u admin -p "<your-password>"
$env:AGENT_GATEWAY_TOKEN = "<token-from-login-output>"
```

4. Configure at least one working model provider in the gateway settings.

5. For the release-readiness demo, confirm outbound access to `https://mcp.context7.com/mcp`.

## Quick Start

Apply the bundles you want to record:

```bash
kubectl apply -f demo/platform-release/bundle.yaml
kubectl apply -f demo/incident-response/bundle.yaml
kubectl apply -f demo/cloud-architecture/bundle.yaml
kubectl apply -f demo/creative-production/bundle.yaml
```

Trigger the manual workflows:

```bash
agentctl --gateway http://localhost:8080 workflows trigger ingress-upgrade-release-readiness
agentctl --gateway http://localhost:8080 workflows trigger multi-cluster-platform-decision
agentctl --gateway http://localhost:8080 workflows trigger conference-launch-pack
```

Trigger the event-driven workflow via signed webhook:

```bash
./demo/incident-response/send-signed-webhook.sh
```

## On-Camera Proof Points To Keep Surfacing

- `kubectl get aiagents,agentworkflows,agentapprovals -n default`
- `kubectl get statefulsets,jobs,pods -n default`
- Web UI agent list, workflow runs, approvals, and Execution Observatory
- `GET /api/v1/traces/executions`, `/timeline`, and `/runtime-summary`
- Signed webhook flow for incident automation
- Human approval before the risky step actually runs

## One-Line Positioning

Use this line early in the video:

`If your AI agent cannot be described, secured, approved, observed, and operated like the rest of your Kubernetes platform, it is still a prototype.`
