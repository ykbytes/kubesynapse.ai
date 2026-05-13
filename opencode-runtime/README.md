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
  `/invoke/stream`, and can fall back to an internal sync invoke when a
  memory-heavy system prompt is already assembled upstream.

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

Stable. This is the default in-tree runtime, with Pi and Mistral Vibe supported
alongside it as additional runtime options.
