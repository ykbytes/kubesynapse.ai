# KubeSynapse Pi Runtime

Node.js HTTP bridge that wraps `pi --mode rpc` for the KubeSynapse agent runtime.

## Purpose

The Pi runtime connects KubeSynapse agents to the [Pi](https://pi.ai) model
backend. It exposes an Express server that translates HTTP calls into Pi RPC
commands and returns structured responses suitable for workflow steps and chat.

## Runtime Role

`pi` is the supported alternative runtime in KubeSynapse. It stays wired through the CRD, gateway, operator, Helm chart, CLI, and UI as the second in-tree runtime kind beside `opencode`.

## Architecture

- **`pi_bridge.js`** — Express server with the Pi RPC client, artifact endpoints,
  model timeout handling, and a health check.
- **Extensions** — `extensions/KubeSynapse-artifacts/index.ts` injects artifact
  context into Pi sessions so generated files are tracked and downloadable.

## Artifact APIs

The bridge exposes three endpoints for retrieving generated files:

| Endpoint | Description |
|----------|-------------|
| `GET /artifacts/list` | List files in the agent workspace |
| `GET /artifacts/download` | Download a single file by path |
| `GET /artifacts/zip` | Download the entire workspace as a ZIP archive |

## Model Timeout

The `MODEL_TIMEOUT_MS` environment variable controls how long the bridge waits
for a Pi RPC response. Default is **120 seconds**.

If a call exceeds the timeout, the bridge aborts the request and returns
**HTTP 504 Gateway Timeout**. This mitigates intermittent hangs from the free-tier
model (`minimax-m2.5-free`) without leaving orphaned connections.

## Known Issues

- **Free-tier model hangs** — `minimax-m2.5-free` can become unresponsive under
  load. The timeout + automatic retry in the caller layer keeps workflows from
  stalling indefinitely.
- **Session state deadlock** — Pi session state is stored on a PVC. If a pod
  restarts and resumes an old session, Pi may deadlock. **Wipe the session
  directory between pod restarts** until Pi adds a clean-session flag.

## Docker Build

```bash
docker build -t kubesynapse-pi-rt:v0.2.13 .
```

Current deployed image:

```bash
docker pull docker.io/kubesynapse/kubesynapse-pi-rt:v0.2.13
```

## Session Persistence

The runtime expects a PVC mounted at `/app/session`. Always clear this directory
when the pod is recreated to avoid stale session locks.

## Current Status

Supported. Pi remains part of the active runtime matrix and shares the same gateway, operator, and UI surfaces as OpenCode agents.
