# Memory System Architecture

## Overview

The agent memory system is **not** a vector database. It is a **JSONL flat-file store** backed by a Kubernetes Persistent Volume Claim (PVC). Memory entries are plain JSON objects appended to `.jsonl` files on disk, recalled by reading the last N lines, and injected into the LLM system prompt as plain text. There is no embedding, no similarity search, and no external database — just append-only log files with atomic pruning.

---

## High-Level Flow

```mermaid
flowchart TD
    subgraph Invocation["Agent Invocation (invoke.py)"]
        A[New request arrives] --> B{Thread has memory?}
        B -- Yes --> C[Check for handoff entry]
        C -- Handoff found --> D["build_handoff_resumption_prompt()"]
        C -- No handoff --> E["build_memory_context(thread_id)"]
        B -- No --> F["recall_workspace_memory(limit=5)"]

        D --> G["format_memory_context()"]
        E --> G
        F --> G

        G --> H["Inject into system prompt<br/>via combine_system_prompt()"]
        H --> I[LLM generates response]
        I --> J["build_task_summary_entry()"]
        J --> K["save_memory(thread_id, entry)"]
        J --> L["save_workspace_memory(entry)"]
    end

    subgraph Storage["JSONL Storage (PVC)"]
        K --> M["threads/{thread_id}.jsonl"]
        L --> N["workspace.jsonl"]
    end
```

---

## Two-Tier Architecture

The system has **two tiers** of memory, stored as separate JSONL files:

```mermaid
flowchart LR
    subgraph Workspace["Workspace Memory (shared)"]
        W["workspace.jsonl<br/>──────────────<br/>Max 50 entries<br/>Shared across all threads<br/>Codebase insights, patterns"]
    end

    subgraph Thread["Thread Memory (per-thread)"]
        T["threads/{id}.jsonl<br/>──────────────<br/>Max 100 entries<br/>Scoped to one conversation<br/>Task summaries, decisions, errors"]
    end

    Workspace -.->|"recalled first<br/>(general context)"| Combine["build_memory_context()"]
    Thread -.->|"recalled second<br/>(specific context)"| Combine
```

| Tier | File | Max Entries | Scope | Purpose |
|------|------|-------------|-------|---------|
| **Workspace** | `workspace.jsonl` | 50 | All threads | Codebase structure, recurring patterns, tech stack info |
| **Thread** | `threads/{thread_id}.jsonl` | 100 | Single thread | Task summaries, decisions, errors, handoffs |

When composing context, `build_memory_context()` returns **workspace entries first** (general knowledge), then **thread entries** (specific to the conversation).

---

## Entry Types

There are **6 valid entry types**:

| Type | Purpose |
|------|---------|
| `task_summary` | Summary of completed work: prompt, status, artifacts, tools used, todos |
| `decision` | A key decision made during a session (e.g. "chose X over Y because Z") |
| `error_pattern` | An error that was encountered and how it was resolved |
| `codebase_insight` | Structural knowledge about the codebase (tech stack, conventions) |
| `file_map` | Key files and their roles in the project |
| `handoff` | Full context dump when a session exhausts its token budget |

Every entry is a JSON object with at least `type`, `content`, and an auto-set `timestamp`:

```json
{
  "type": "task_summary",
  "content": {
    "prompt_summary": "Fix the workspace persistence bug...",
    "status": "completed",
    "artifacts": ["operator/builders/manifests.py"],
    "tools_used": ["read_file", "grep_search", "run_in_terminal"],
    "completed": ["Mount PVC with subPath"],
    "remaining": [],
    "response_excerpt": "Changed all 4 runtime types..."
  },
  "timestamp": 1718900000.0
}
```

---

## Storage & Persistence Layer

```mermaid
flowchart TB
    subgraph K8s["Kubernetes Pod (agent sandbox)"]
        subgraph Container["opencode-runtime"]
            SM["SessionMemory<br/>(Python singleton)"]
            SM -->|"_append()"| FS["Filesystem<br/>/home/opencodeuser/.local/share/<br/>opencode-runtime/memory/"]
        end
        FS --> PVC
    end

    subgraph PVC["PVC: state-volume"]
        direction TB
        WS["workspace.jsonl"]
        TH["threads/<br/>  ├── abc123.jsonl<br/>  ├── def456.jsonl<br/>  └── ..."]
    end
```

- **Base directory**: `$XDG_DATA_HOME/opencode-runtime/memory/` (overridable via `OPENCODE_MEMORY_DIR`)
- **Kubernetes volume**: The `state-volume` PVC is mounted at `/workspace` with subPath, and the memory directory lives on the same PVC — so **memory survives pod restarts**
- **Thread ID sanitization**: Thread IDs are cleaned to `[a-zA-Z0-9_-]`, truncated to 64 chars

### Atomic Writes & Pruning

Writes use a **threading.Lock** for per-process thread safety. Pruning is **crash-safe** via atomic file replacement:

```mermaid
sequenceDiagram
    participant Caller
    participant SessionMemory
    participant Filesystem

    Caller->>SessionMemory: save_memory(thread_id, entry)
    SessionMemory->>SessionMemory: Acquire lock
    SessionMemory->>Filesystem: Append JSON line to .jsonl
    SessionMemory->>Filesystem: Read all lines, count entries

    alt entries > max_entries
        SessionMemory->>Filesystem: Write pruned entries to .tmp file
        SessionMemory->>Filesystem: os.replace(.tmp → .jsonl) [atomic]
    end

    SessionMemory->>SessionMemory: Release lock
    SessionMemory-->>Caller: True
```

This ensures that if the pod crashes mid-prune, the original file is untouched — `os.replace()` is an atomic filesystem operation.

---

## Recall & Injection into LLM

When a new request arrives, memory is loaded and injected into the system prompt:

```mermaid
sequenceDiagram
    participant User
    participant invoke.py
    participant SessionMemory
    participant prompts.py
    participant LLM

    User->>invoke.py: Send message (thread_id)

    alt Thread has memory
        invoke.py->>SessionMemory: get_handoff_memory(thread_id)
        alt Handoff entry exists
            SessionMemory-->>invoke.py: handoff dict
            invoke.py->>prompts.py: build_handoff_resumption_prompt(handoff)
        else No handoff
            invoke.py->>SessionMemory: build_memory_context(thread_id)
            SessionMemory-->>invoke.py: [workspace + thread entries]
            invoke.py->>prompts.py: format_memory_context(entries)
        end
    else New thread (no thread memory)
        invoke.py->>SessionMemory: recall_workspace_memory(limit=5)
        SessionMemory-->>invoke.py: [workspace entries]
        invoke.py->>prompts.py: format_memory_context(entries)
    end

    prompts.py-->>invoke.py: Memory text block
    invoke.py->>invoke.py: combine_system_prompt(base, memory_text, ...)
    invoke.py->>LLM: System prompt + user message
    LLM-->>invoke.py: Response

    invoke.py->>invoke.py: build_task_summary_entry(prompt, response, ...)
    invoke.py->>SessionMemory: save_memory(thread_id, summary)
    invoke.py->>SessionMemory: save_workspace_memory(summary)
```

The formatted memory text looks like this in the system prompt:

```
PRIOR SESSION MEMORY (context carried from previous sessions):
- [codebase_insight] This project uses FastAPI with a Helm-based deployment...
- [task_summary] {"prompt_summary": "Fix workspace persistence...", "status": "completed", ...}
- [error_pattern] PVC mount was emptyDir — changed to subPath: workspace
```

---

## Handoff Mechanism (Context Exhaustion)

When the LLM's token budget is nearly exhausted, a **handoff entry** is saved instead of a normal task summary. This captures the full state needed to resume in a new session:

```mermaid
flowchart TD
    A[Session running] --> B{Token budget exhausted?}
    B -- No --> C[Normal save: task_summary]
    B -- Yes --> D["build_handoff_entry()"]
    D --> E["Save handoff to thread JSONL"]

    E --> F[New session starts]
    F --> G["get_handoff_memory(thread_id)"]
    G --> H["build_handoff_resumption_prompt()"]
    H --> I["System prompt includes:<br/>RESUMING FROM PRIOR SESSION<br/>• Original task<br/>• Progress summary<br/>• Completed todos<br/>• Remaining todos<br/>• Modified files"]
```

A handoff entry captures:
- `original_prompt` (up to 1000 chars)
- `summary` of progress (up to 2000 chars)
- `todos` — completed and pending (up to 30)
- `artifacts` — files created/modified (up to 30)
- `context_budget` — token usage stats

---

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `OPENCODE_MEMORY_ENABLED` | `true` | Enable/disable the memory system |
| `OPENCODE_MEMORY_DIR` | `$XDG_DATA_HOME/opencode-runtime/memory` | Base directory for memory files |
| `MEMORY_MAX_THREAD_ENTRIES` | `100` | Max entries per thread JSONL file |
| `MEMORY_MAX_WORKSPACE_ENTRIES` | `50` | Max entries in workspace.jsonl |

---

## Key Design Decisions

1. **JSONL over a database**: Simple, no dependencies, human-readable, easy to debug. `cat workspace.jsonl` shows everything.
2. **No vector search**: Memory is injected as plain text into the system prompt — the LLM itself decides what's relevant. This avoids embedding model dependencies and keeps the system self-contained.
3. **Two tiers**: Workspace memory provides cross-thread continuity (the agent "remembers" the codebase); thread memory provides session-specific context.
4. **Atomic pruning**: `tempfile` + `os.replace()` ensures no data loss on crash.
5. **Bounded size**: Hard caps on entries (100 thread, 50 workspace) prevent unbounded growth that would blow up the system prompt.
6. **Handoff for continuity**: When tokens run out, a structured handoff entry preserves enough state for the next session to pick up exactly where it left off.
