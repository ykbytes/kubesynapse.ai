# Video Showcase Script

This is the flagship script for the main public video.

Recommended runtime: 8 to 10 minutes.

## Tone

Keep the tone sharp, technical, and grounded.

- Do not say AGI.
- Do not say the platform replaces engineers.
- Do not promise autonomous production changes without approvals.
- Do say that KubeSynapse makes AI agents operable inside the same Kubernetes discipline teams already trust.

## Working Title

`Kubernetes-Native AI Agents That Ops Teams Might Actually Trust`

## Cold Open

### Voiceover

`If your AI agent lives in a notebook, has no approval boundary, no trace history, no network isolation, and no idea how to survive a restart, it is not ready for your platform. KubeSynapse takes a different approach. Agents and workflows are Kubernetes resources. They get runtimes, policies, approvals, observability, and operational boundaries.`

### Visuals

- Fast cut: a toy chat window
- Cut to `kubectl get aiagents,agentworkflows`
- Cut to `kubectl get statefulsets,jobs,pods`
- Cut to the architecture diagram
- Cut to the UI showing workflows and traces

### Lower Third

`CRD-driven AI agent infrastructure for Kubernetes`

## 0:00 To 0:50 - The Problem

### Voiceover

`Most agent frameworks solve the prototype problem. They do not solve the platform problem. Platform teams need clear boundaries: who can call what, what runs where, what gets persisted, what gets approved, and how you debug a run after it fails at 2 AM.`

`That is where most AI demos collapse. They skip policy. They skip runtime isolation. They skip workflow state. They skip traceability. They skip security controls around inbound automation. They look impressive for 30 seconds and then fall apart the moment an operator asks real questions.`

### Visuals

- Show `README.md` architecture section briefly
- Show `kubectl get crd | findstr kubesynapse.ai`
- Show UI with agents, workflows, approvals, traces

## 0:50 To 1:35 - Architecture Truth

### Voiceover

`Here is the architectural bet. The control plane source of truth is Kubernetes plus CRDs. The gateway is the public edge and application backend. The operator reconciles agents into isolated runtime StatefulSets and workflows into worker Jobs. The observability layer records workflow traces and semantic runtime events. And if a step is risky, it can stop and wait for a human approval.`

`This matters because it means the system fits how platform teams already operate. Desired state is declarative. Runtime infrastructure is materialized. Execution history is queryable. And security boundaries are visible instead of implied.`

### Visuals

- Open `docs/kubesynapse-architecture.mmd` or the refreshed draw.io asset
- Highlight CRDs, gateway, operator, runtimes, jobs, observatory, security overlays

## 1:35 To 3:20 - Demo 1: Release Readiness For Platform Teams

### Setup On Screen

```bash
kubectl apply -f demo/platform-release/bundle.yaml
agentctl --gateway http://localhost:8080 workflows trigger ingress-upgrade-release-readiness
```

### Voiceover

`First use case: a platform-engineering change review. In this bundle, a release researcher uses the Context7 remote MCP path to pull current documentation, writes a structured upgrade brief, hands that result to a release architect, and then pauses at an approval gate before the final operator brief is produced.`

`This is the kind of AI workflow that teams actually need: not "ship blindly," but "gather the evidence, analyze the blast radius, and package a human-reviewable change plan."`

### Visuals

- Show `kubectl get aiagents -n default`
- Show `kubectl get pods -n default`
- Show workflow run in UI
- Show generated approval resource
- Approve it live

### Approval Moment

```bash
kubectl get agentapprovals -n default
agentctl --gateway http://localhost:8080 runs approve <approval-name> --reason "Reviewed live on camera"
```

### Proof Point Callout

`The important thing here is not the words in the brief. It is the structure around the work: scoped tooling, file-based handoff, workflow state, and a human gate before the platform emits the final change package.`

## 3:20 To 5:20 - Demo 2: Event-Driven Incident Response

### Setup On Screen

```bash
kubectl apply -f demo/incident-response/bundle.yaml
./demo/incident-response/send-signed-webhook.sh
```

### Voiceover

`Second use case: SRE and incident response. This one matters because it attacks the skepticism directly. We are not asking you to trust a free-running agent. We are showing a signed webhook entering the gateway, being validated with HMAC and timestamp checks, matching a workflow trigger, and launching a controlled incident workflow.`

`The triage agent can inspect the cluster. The remediation step is approval-gated. The status writer turns the result into a clean incident update. This is closer to how real on-call automation should look: evidence first, smallest safe action, explicit approval for the risky step, and a traceable execution record after the fact.`

### Visuals

- Show receiver and trigger CRDs
- Show the signed webhook helper script
- Show workflow creation after webhook invocation
- Show triage output
- Pause at approval
- Approve remediation
- Show final incident update

### Lower Third

`Signed webhook -> validated trigger -> approval-gated remediation`

## 5:20 To 6:40 - Demo 3: Cloud Architecture Decision Flow

### Setup On Screen

```bash
kubectl apply -f demo/cloud-architecture/bundle.yaml
agentctl --gateway http://localhost:8080 workflows trigger multi-cluster-platform-decision
```

### Voiceover

`Third use case: architecture work. This is where a lot of AI demos become useless because they jump straight to final answers with no review boundaries. Here, the workflow splits the work into roles: platform architecture, security review, FinOps and operational tradeoffs, and finally a decision memo that still pauses for approval before it becomes the recommendation package.`

`That matters because cloud design is not just about generating diagrams. It is about exposing tradeoffs: isolation, identity, secrets, failover, team cognitive load, and cost shape. The workflow structure forces those concerns into separate stages.`

### Visuals

- Show workflow DAG
- Show artifacts being written in workspace
- Show final memo stage waiting for approval

## 6:40 To 7:35 - Demo 4: Creative Production Without Losing Discipline

### Setup On Screen

```bash
kubectl apply -f demo/creative-production/bundle.yaml
agentctl --gateway http://localhost:8080 workflows trigger conference-launch-pack
```

### Voiceover

`Last use case: creative production. Same platform, different domain. A creative director produces the concept brief. A show-run producer turns it into a run-of-show and technical checklist. A launch-copy editor produces operator-grade YouTube and LinkedIn copy. Then the final pack pauses for approval.`

`Why show this? Because the platform is not only for cluster firefighting. It is for any workflow where you need isolated workspaces, staged execution, artifact handoff, and reviewable outputs.`

### Visuals

- Open generated launch-pack files
- Show the approval gate and final artifacts

## 7:35 To 8:35 - Why Skeptical Engineers Should Care

### Voiceover

`The point is not that an LLM can type text. The point is that KubeSynapse gives platform teams the missing operating model.`

`Agents are resources. Runtimes are isolated. Workflows are explicit. Risky steps can pause. Incoming automation is signed and filtered. Runs leave evidence. And the same platform supports developers, SREs, architects, and even production workflows that need structured handoff.`

`That is a much better story than "trust the agent." It is "put the agent inside infrastructure you can reason about."`

## 8:35 To End - Close And CTA

### Voiceover

`If you want to see AI agents treated like the rest of your platform, not like magic tabs in a browser, look at KubeSynapse. The repo, manifests, and demo kit are all open. Start with the CRDs, the workflows, and the traces. Then decide if this looks like slop, or like infrastructure.`

### On Screen

- GitHub repo
- `demo/` folder
- architecture diagram
- UI traces view
- final call to star, try, and share

## Lines Worth Repeating

- `Kubernetes is the source of truth, not the prompt.`
- `Do not trust the agent. Operate the agent.`
- `Approval gates are a feature, not a failure mode.`
- `If the run leaves no evidence, it did not happen.`

## Lines To Avoid

- `fully autonomous platform team`
- `replaces SREs`
- `no more humans in the loop`
- `self-healing AGI for Kubernetes`

## Suggested B-Roll

- `kubectl get aiagents,agentworkflows,agentapprovals -n default`
- `kubectl get statefulsets,jobs,pods -n default`
- workflow status transitions in the UI
- approval resource appearing and being approved
- trace timeline and runtime summary APIs
- signed webhook helper script firing the incident workflow
