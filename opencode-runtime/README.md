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
- **Trace Extraction** — Final invoke results include extracted `tool_calls`
  used by the Execution Observatory, with individual tool outputs capped at
  40,000 characters before they are forwarded to the operator and gateway.

## Invoke Behavior

- KubeSynapse uses the async OpenCode prompt path for normal invoke execution.
- This avoids the slower and less reliable synchronous `/session/{id}/message`
  path inside OpenCode.
- In practice this reduces taskrunner-style invokes from the prior 30s to 40s
  range down into the single-digit seconds when the model and session are
  healthy.

## Observatory Payload Notes

- The runtime is the primary source of `tool_result` data shown in the Web UI's
  Execution Observatory.
- Tool call status events emitted during execution do not include full
  `tool_result` payloads; those are reconstructed from the runtime's final
  response payload and forwarded by the operator.
- Tool outputs are truncated with an ellipsis only when they exceed the current
  40,000-character cap, which keeps JSON payloads large enough for practical
  inspection without allowing unbounded trace storage growth.

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
