# BeatForge — Mobile DAW Agent Workflow

A multi-step AI agent workflow that builds **BeatForge**, a mobile step
sequencer, drum machine, and synthesizer app using React Native + Expo.

## Architecture

```
Step 1: Plan          → Architecture doc, types, package.json, app config
Step 2: Build         → All source files (engine, stores, components, navigation)
Step 3: Enhance       → Polish, animations, visual feedback, bug fixes
Step 4: Finalize      → App Store prep, accessibility, documentation
```

All steps share workspace via `sessionGroup: dev-session`, so each step
builds on files created by the previous one.

## Tech Stack

- **React Native 0.76+** with Expo SDK 52
- **TypeScript** (strict mode)
- **react-native-audio-api** for Web Audio API on mobile
- **Zustand** for state management
- **expo-router** for file-based navigation
- **react-native-reanimated** for 60fps animations
- **EAS Build** for App Store / Play Store submissions

## Files

| File | Description |
|------|-------------|
| `project-context.yaml` | ConfigMap with product spec, tech stack, constraints |
| `daw-agent.yaml` | AIAgent with 5 embedded skills (planning, RN patterns, audio, app store, refinement) |
| `workflow.yaml` | 4-step pipeline: plan → build → enhance → finalize |
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
npx expo start
```

## Build for App Store

```bash
npx eas build --platform ios
npx eas build --platform android
```

See the generated `APPSTORE.md` in the workspace for the full submission guide.
