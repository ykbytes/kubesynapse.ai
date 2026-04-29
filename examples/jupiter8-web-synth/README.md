# Jupiter-8 Web Synth Example

Multi-agent workflow that generates a browser-based Jupiter-8 synthesizer web
application.

## Overview

This bundle demonstrates a planning and implementation split across two agents.
The workflow scaffolds a React + Vite project, builds the synth core with
Tone.js, assembles UI panels, and produces a polished, interactive web app.

## Agents

| Agent | Role | Status |
|-------|------|--------|
| `j8-web-architect` | Planning and specification | Currently unused |
| `j8-web-builder` | Implementation and integration | Active |

## Runtime

- **Runtime**: `pi`
- **Model**: `opencode/minimax-m2.5-free`

## Workflow Steps

1. `scaffold-project` — Create React 18 + Vite + TypeScript boilerplate.
2. `build-synth-core` — Implement oscillator, filter, and envelope engine with
   Tone.js.
3. `build-ui-panels` — Build control panels (ADSR, LFO, preset manager) in
   React.
4. `integrate-and-polish` — Wire UI to audio engine, add styling, and verify
   in-browser.
5. `final-summary` — Generate a README and archive the workspace.

## Generated Tech Stack

- React 18
- Vite
- TypeScript
- Tone.js
- Zustand (state management)
- Tailwind CSS

## Deploy

```bash
kubectl apply -f jupiter8-web-synth-bundle.yaml
```

Or use the helper script on Windows:

```powershell
./jupiter8-web-synth-deploy.ps1
```

## Monitor

Watch the workflow status:

```bash
kubectl get agentworkflows jupiter8-web-synth -w
```

Browse generated artifacts from the Web UI or download them with the CLI:

```bash
agentctl artifacts list j8-web-builder
agentctl artifacts download j8-web-builder dist/index.html
agentctl artifacts zip j8-web-builder
```

## Known Issues

- **Model timeout** — The free-tier model (`minimax-m2.5-free`) can hang for
  longer than 120 s. The Pi runtime aborts stuck calls and the operator retries
  the step automatically.
- **Free-tier reliability** — Intermittent failures are expected under load.
  Retries and checkpointing keep the workflow moving.
