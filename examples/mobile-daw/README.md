# BeatForge — Mobile DAW Agent Workflow

A multi-step AI agent workflow that builds **BeatForge**, a mobile step
sequencer, drum machine, and synthesizer app using React Native + Expo.

## Architecture

```
Step 0: Tooling       → package.json, tsconfig, ESLint, Prettier, Jest, WAV generation
Step 1: Foundation    → Types, constants, engine singletons, Zustand stores, wiring hook
Step 2: Implement     → All UI components (10+) and screens (7), full dark theme
Step 3: Polish        → Integration trace, unit tests, verification gates, App Store docs
```

All steps share workspace via `sessionGroup: dev-session`, so each step
builds on files created by the previous one. Steps pass structured handoff
state via `/workspace/.workflow-state.json`.

## Tech Stack

- **React Native 0.76+** with Expo SDK 52
- **TypeScript** (strict mode — no `any`, no `.d.ts` shims)
- **expo-av** for audio sample playback (NOT react-native-audio-api)
- **Zustand 5** for state management (named import: `import { create }`)
- **expo-router** for file-based tab navigation
- **react-native-reanimated 3** for 60fps animations
- **react-native-gesture-handler** for touch interactions
- **EAS Build** for App Store / Play Store submissions

## Key Design Decisions

- **10 Known Failure Modes**: The agent definition includes detailed wrong→right
  code patterns covering Metro dynamic require, Zustand v5 imports, Reanimated
  hooks-in-map, stale gesture props, and more. These prevent bugs that recur
  in every build.
- **Drift-Correcting Clock**: The sequencer uses `performance.now()` with
  lookahead scheduling instead of naive `setInterval` (which drifts).
- **Static Require Maps**: All audio assets use compile-time `require()` calls
  to work correctly with Metro bundler in production.
- **Engine↔Store Wiring**: Every store action that affects audio must call the
  corresponding engine method. `loadProject()` syncs both stores AND engines.
- **12 Verification Gates**: The polish step runs automated checks for TypeScript,
  ESLint, file counts, no `any`, no shims, correct imports, engine wiring,
  valid WAV files, and passing tests.

## Files

| File | Description |
|------|-------------|
| `project-context.yaml` | ConfigMap with product spec, failure modes, data models, wiring contract |
| `daw-agent.yaml` | AIAgent with 6 embedded skills (pitfalls, audio engine, wiring, types, RN quality, verification) |
| `workflow.yaml` | 4-step pipeline: tooling → foundation → implement → polish |
| `deploy.ps1` | PowerShell deployment script |

## Deploy

```powershell
cd examples/mobile-daw
.\deploy.ps1
```

Or manually:

```bash
kubectl apply -f project-context.yaml
kubectl apply -f daw-agent.yaml
# Wait for agent pod to be ready
kubectl apply -f workflow.yaml
```

## Monitor

- **Web UI**: http://localhost:3000
- **API**: http://localhost:8080

```bash
kubectl get agentworkflow mobile-daw -w
kubectl logs -f -l agent-name=daw-agent
```

## After Completion

Download the generated code from the web UI (Download All ZIP button)
or copy from the agent pod:

```bash
kubectl cp default/daw-agent-sandbox-0:/workspace ./beatforge-app
cd beatforge-app
npm install
node scripts/generate-samples.js   # Generate WAV sample files
npx expo start
```

## Build for App Store

```bash
npx eas build --platform ios --profile production
npx eas build --platform android --profile production
```

See the generated `APPSTORE.md` in the workspace for the full submission guide.
