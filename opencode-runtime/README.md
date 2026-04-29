# KubeSynapse OpenCode Runtime

FastAPI wrapper around `opencode serve` that hosts OpenCode agents inside
KubeSynapse.

## Purpose

The OpenCode runtime turns OpenCode configuration bundles into long-running
agent pods with session persistence, checkpoint recovery, and a tiered memory
system.

## Features

- **Session Persistence** — Workspace state survives pod restarts via PVC.
- **Checkpoint Recovery** — Automatic snapshotting before long-running tool
  calls so work can resume after eviction or OOM.
- **Memory System** — 5-tier retention strategy:
  1. Working memory (recent turns)
  2. Short-term summaries (rolling window)
  3. Long-term entity extraction (structured facts)
  4. Semantic memory (Qdrant vector provider)
  5. Archival retention (compressed historical traces)
- **Entity Extraction** — Extracts named entities, decisions, and action items
  from conversations for later retrieval.

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

Stable. Deployed alongside the Pi runtime as an alternative agent backend.
