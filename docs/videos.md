# KubeSynapse Video Content Plan

## Video 1: Product Overview (3 minutes)

### Target Audience
Platform engineers, DevOps leads, CTOs exploring AI agent infrastructure.

### Script Outline

**0:00–0:15 — Hook**
> "You've built amazing AI agents in LangChain. Now you need to run them in production. On Kubernetes. With governance, observability, and multi-tenancy. Meet KubeSynapse."

**0:15–0:45 — The Problem**
- Show: Agent running as a Python script. Process dies. Agent forgets everything.
- Show: Manual monitoring setup. Grafana dashboards with "No data."
- Show: Agent running wild with no tool restrictions. Security team in panic.
- Voiceover: "Most AI agent frameworks solve the development problem, not the production problem."

**0:45–1:30 — The Solution**
- Terminal: `helm install KubeSynapse ./charts/kubesynapse -n kubesynapse --create-namespace`
- Visual: Animated architecture diagram showing all components spinning up (API gateway, operator, LiteLLM, PostgreSQL, Redis, NATS, Qdrant)
- Web UI: Landing page → Dashboard → Agent list → Workflow list
- Voiceover: "One Helm command deploys the full stack. API gateway, Kubernetes operator, LiteLLM proxy, databases — all pre-configured for production."

**1:30–2:15 — Demo: Deploy an Agent**
- Terminal: `kubectl apply -f my-agent.yaml`
- Web UI: Agent appears in dashboard, pod spins up, health turns green
- Terminal: Show StatefulSet with PVC, stable DNS
- Web UI: Define a policy with token limits, tool whitelist, cost cap
- Voiceover: "Agents run as StatefulSets with persistent storage. Policies are enforced by the operator before any LLM call is made."

**2:15–2:45 — Demo: Multi-Agent Workflow**
- Web UI: Create a workflow with 3 steps (triage → remediate → report)
- Terminal: `kubectl get agentworkflow -w` shows state transitions
- Visual: DAG visualization showing step dependencies and status colors
- Web UI: Workflow completes, results displayed
- Voiceover: "Multi-step, multi-agent workflows with retries, timeouts, and approval gates. All driven by Kubernetes CRDs."

**2:45–3:00 — Call to Action**
- Show: GitHub repo URL, star button animation
- Show: Community Discord/Slack link
- Show: Quick Start guide link
- Voiceover: "KubeSynapse is open source, Apache 2.0 licensed. One Helm command to production. Star us on GitHub and join the community."

### Visual Assets Needed
- Animated architecture diagram (Mermaid or custom SVG)
- Terminal recording with realistic typing (use `vhs` or `asciinema`)
- Web UI screen recording (agent creation, workflow execution)
- Grafana dashboard timelapse showing metrics
- GitHub star counter animation

### Recording Tools
- **Terminal:** `vhs` (charmbracelet/vhs) for programmatic terminal recordings
- **UI:** OBS Studio with window capture
- **Voiceover:** Record separately, sync in post-production
- **Editing:** DaVinci Resolve (free) or Descript for AI-assisted editing

---

## Video 2: Deep Dive — Agent Policies & Governance (8 minutes)

### Sections
1. **Why governance matters for AI agents** (1 min)
2. **AgentPolicy CRD walkthrough** (2 min) — token limits, tool whitelist, cost caps, approval gates
3. **Live demo: policy enforcement** (3 min) — agent attempts forbidden action, operator blocks it
4. **Human-in-the-loop approval flow** (2 min) — AgentApproval CRD lifecycle

---

## Video 3: Deep Dive — Multi-Agent Workflows (8 minutes)

### Sections
1. **AgentWorkflow CRD walkthrough** (2 min) — DAG definition, steps, dependencies, retry policies
2. **Live demo: incident response workflow** (3 min) — triage → remediate → report with two agents
3. **Failure recovery** (2 min) — showing retries, circuit breakers, dead-letter queues
4. **Observability** (1 min) — OpenTelemetry traces across all steps

---

## Video 4: Deep Dive — Observability & Cost Tracking (6 minutes)

### Sections
1. **Grafana dashboards tour** (2 min) — agent overview, workflow execution, LLM usage
2. **Prometheus alerts** (1 min) — firing alerts, silence, escalation
3. **Cost tracking live** (2 min) — token usage by model, cost per agent, daily budget alerts
4. **Distributed tracing** (1 min) — Jaeger/Grafana Tempo trace of a complete workflow

---

## Video 5: Community & Contributing (4 minutes)

### Sections
1. **Project architecture tour** (1 min) — component map, tech stack
2. **Setting up dev environment** (1 min) — Kind cluster, Tilt/devspace, hot reload
3. **Contributing your first PR** (1 min) — Good First Issue, PR template, review process
4. **Roadmap & community** (1 min) — upcoming features, CNCF sandbox application, community channels

---

## Production Notes

### Audio
- Use a quality USB microphone (Blue Yeti, Shure MV7, or similar)
- Record in a quiet room with minimal echo
- Normalize audio to -16 LUFS
- Add subtle background music (royalty-free from Epidemic Sound or Uppbeat)

### Visual Style
- Dark theme throughout (matches KubeSynapse brand)
- Consistent color palette: blue (#2563EB), cyan (#06B6D4), slate (#0F172A)
- Use IBM Plex Mono for code, IBM Plex Sans for UI text
- Smooth transitions between terminal and UI views

### Accessibility
- Closed captions (SRT format) for all videos
- Transcript included in video description
- No flashing animations (WCAG compliance)

### Publishing
- Upload to YouTube as unlisted first, review, then publish
- Create a playlist: "KubeSynapse — Kubernetes-Native AI Agents"
- Include links to GitHub, docs, community in video description
- Share on Hacker News, Reddit (r/kubernetes, r/LLMDevs), LinkedIn
