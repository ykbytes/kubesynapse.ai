# Ableton Live Web — 10-Step Agent Workflow

This example deploys a **single-agent, 10-step workflow** that builds a
professional browser-based Digital Audio Workstation inspired by Ableton Live 11.

## Agent

| Agent | Model | Runtime |
|-------|-------|---------|
| `ableton-daw-agent` | copilot-gpt-5.4 | OpenCode (build, 6 embedded skills) |

The single agent carries 6 inline skills: known-pitfalls, audio-engine,
ui-layout, integration-wiring, strict-types, and verification-gates.

## Workflow Pipeline

```
scaffold → types-and-stores → audio-engine → layout-and-transport
→ arrangement-view → session-view → mixer-and-effects → instruments
→ integration → verify-and-polish
```

All 10 steps share a workspace via `sessionGroup: dev-session`, so each
step builds on files created by the previous one. Each step prompt uses
`##` markdown headers that auto-seed plan progress in the UI.

| # | Step | Focus | maxTurns |
|---|------|-------|----------|
| 0 | scaffold | package.json, tsconfig, Vite, Tailwind, pnpm install | 5 |
| 1 | types-and-stores | TypeScript interfaces, 5 Zustand stores | 10 |
| 2 | audio-engine | Tone.js engine, ChannelStrip, effects, synth, drums | 12 |
| 3 | layout-and-transport | CSS Grid shell, TransportBar, Sidebar | 10 |
| 4 | arrangement-view | Multi-track timeline, track lanes, playhead | 12 |
| 5 | session-view | Clip launcher grid, scene triggers | 10 |
| 6 | mixer-and-effects | Faders, pan knobs, VU meters, effects rack | 12 |
| 7 | instruments | Piano roll, synth panel, drum pads, waveform | 12 |
| 8 | integration | Wire stores→engine, keyboard shortcuts, hooks | 14 |
| 9 | verify-and-polish | tsc, vite build, UI polish, README | 14 |

## Tech Stack (Generated App)

- React 18 + Vite 5 + TypeScript strict
- Tone.js 15 for Web Audio scheduling and synthesis
- Zustand 5 for state management
- Tailwind CSS 3 with Ableton-inspired dark theme

## Prerequisites

1. A running KubeSynapse cluster with the operator deployed.
2. LLM model `copilot-gpt-5.4` configured in LiteLLM.
3. MCP sidecar `code-exec` available.

## Deploy

```powershell
./deploy.ps1 -Namespace default
```

Manual:

```bash
kubectl apply -f project-context.yaml
kubectl apply -f daw-agent.yaml
kubectl apply -f workflow.yaml
kubectl get agentworkflows ableton-live-web -w
```

## Monitor

```bash
kubectl get agentworkflows ableton-live-web -o yaml
kubectl logs -l agent-name=ableton-daw-agent -c agent-runtime -f
```

## Customization

- **Model**: Change `spec.model` in `daw-agent.yaml`.
- **Steps**: Adjust `maxTurns` or `timeoutSeconds` per step in `workflow.yaml`.
- **Features**: Edit step prompts to add/remove features.
