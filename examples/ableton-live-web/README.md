# Ableton Live Web — Multi-Agent Workflow Example

This example deploys a **3-agent workflow** that collaboratively builds a
browser-based Digital Audio Workstation inspired by Ableton Live.

## Agents

| Agent | Role | Runtime |
|-------|------|---------|
| `ableton-architect` | System design, project scaffolding, integration review | OpenCode (plan) |
| `ableton-backend` | Web Audio engine, Tone.js scheduling, effects pipeline | OpenCode (build) |
| `ableton-frontend` | React UI, Tailwind dark theme, DAW components | OpenCode (build) |

## Workflow DAG

```
design (architect, loop)
   ├──→ backend  (backend-dev, loop)  ──┐
   └──→ frontend (frontend-dev, loop) ──┤
                                        └──→ integration-review (architect, review)
```

- **design**: The architect generates the architecture, TypeScript interfaces,
  Zustand store skeletons, and project scaffold (Vite + React + Tailwind config).
- **backend** / **frontend**: Run **in parallel** — one builds the audio engine
  (`src/engine/`), the other builds the React UI (`src/components/`).
- **integration-review**: The architect reviews the combined output against
  10 acceptance criteria (build, tests, types, conventions).

All coding steps use `type: loop` with `planSource: prompt`, so each agent
generates its own TODO checklist and iterates through it with circuit-breaker
protection.

## Prerequisites

1. A running AI Agent Sandbox cluster with the operator deployed.
2. At least one LLM model configured in LiteLLM (default: `gpt-4`).
3. MCP sidecars available in the catalog: `git`, `code-exec`.

## Deploy

Fast path on Windows:

```powershell
./deploy.ps1 -Namespace default
```

Manual path:

```bash
# 1. Apply the project context ConfigMap
kubectl apply -f project-context.yaml

# 2. Create the three agents
kubectl apply -f architect-agent.yaml
kubectl apply -f backend-agent.yaml
kubectl apply -f frontend-agent.yaml

# 3. Wait for all agent pods to become ready
kubectl wait --for=condition=ready pod -l app=ai-agent --timeout=120s

# 4. Launch the workflow
kubectl apply -f workflow.yaml

# 5. Watch progress
kubectl get agentworkflows ableton-live-web -w
```

## Monitor

```bash
# Check workflow status
kubectl get agentworkflows ableton-live-web -o yaml

# Stream the specific workflow worker job logs
kubectl -n ai-platform logs job/<worker-job-name> -f

# Check individual agent logs
kubectl logs -l agent-name=ableton-architect -f
kubectl logs -l agent-name=ableton-backend -f
kubectl logs -l agent-name=ableton-frontend -f
```

In the web UI workflow view, use the new `Live logs` panel to switch between:

- the workflow worker logs for orchestration issues
- each agent runtime log stream
- filtered views for `OpenCode-focused` and `Errors only`

## Customization

- **Model**: Change `spec.model` in each agent YAML to use a different LLM
  (e.g., `gpt-4o`, `claude-sonnet-4-20250514`).
- **Git**: Add `spec.gitConfig` to each agent to push results to a repository.
- **Loop iterations**: Adjust `loopConfig.maxIterations` for more or fewer
  development cycles (default: 15 for design, 20 for backend/frontend).
- **Timeouts**: Increase `execution.timeoutSeconds` if using slower models.
