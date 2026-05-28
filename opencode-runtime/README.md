# KubeSynapse OpenCode Runtime

FastAPI wrapper around `opencode serve` that hosts OpenCode agents inside
KubeSynapse.

## Purpose

The OpenCode runtime turns OpenCode configuration bundles into long-running
agent pods with session persistence, checkpoint recovery, streamed invoke support,
and runtime-local memory services.

## Runtime Role

`opencode` is the default supported runtime in KubeSynapse. It is the primary path used by the checked-in examples, the CLI and UI OpenCode configuration flows, and the operator's default runtime wiring.

## Features

- **Session Persistence** — Workspace state survives pod restarts via PVC.
- **Checkpoint Recovery** — Automatic snapshotting before long-running tool
  calls so work can resume after eviction or OOM.
- **Runtime-Local Memory** — File-backed thread and workspace memory under
  `OPENCODE_MEMORY_DIR`, plus an optional Qdrant semantic-memory provider.
- **Gateway Memory Hand-off** — Final invoke payloads can emit `metadata.memory`
  candidates which the API gateway persists into PostgreSQL for durable recall.
- **Stream Parity Support** — The runtime supports both `/invoke` and
  `/invoke/stream`, with the primary invoke path using OpenCode's async prompt
  flow even when a system prompt is present.

## Invoke Behavior

- KubeSynapse uses the async OpenCode prompt path for normal invoke execution.
- This avoids the slower and less reliable synchronous `/session/{id}/message`
  path inside OpenCode.
- In practice this reduces taskrunner-style invokes from the prior 30s to 40s
  range down into the single-digit seconds when the model and session are
  healthy.

## Memory Model

KubeSynapse now ships two complementary memory layers:

1. **Runtime-local memory** in the OpenCode pod for handoff, session continuity,
   workspace insights, and optional semantic recall.
2. **Gateway durable memory** in PostgreSQL for promoted cross-session recall,
   ranking, and injection on both sync and streamed agent invokes.

The runtime remains responsible for local JSONL/Qdrant memory behavior, while the
gateway owns durable recall ranking and user-visible persistent-memory behavior.

## Development Setup

```bash
cd opencode-runtime/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The server binds to `0.0.0.0:8081` by default.

## Current Status

Stable. This is the production runtime for KubeSynapse. Pi and Mistral Vibe are
available as alpha runtimes but are not recommended for production use.
