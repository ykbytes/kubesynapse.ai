# Pi-Mono Knowledge Base — KubeSynapse Integration

**Generated**: 2026-04-27  
**Source**: https://github.com/badlogic/pi-mono (v0.70.5, 41.5k stars)  
**Related**: https://pi.dev, https://github.com/qualisero/awesome-pi-agent

---

## 1. Project Overview

Pi-mono is a monorepo containing an **AI agent toolkit** built in TypeScript. It is the most popular OSS coding agent (41.5k GitHub stars) with a philosophy of **extreme extensibility** — it intentionally omits conventional "features" (sub-agents, plan mode, todo lists, MCP, background bash) in favor of a powerful extension API so users build exactly what they need.

### Key Principles (relevant to KubeSynapse integration)
1. **"Pi is a harness, not a product"** — designed to be adapted to different workflows
2. **Primitives over features** — core is minimal (~4 tools), capabilities come from extensions
3. **TypeScript-first** — extensions, tools, skills are all TS modules (loaded via jiti, no compilation needed)
4. **Four modes**: Interactive (TUI), Print/JSON, **RPC (JSON protocol over stdin/stdout)**, **SDK (programmatic API)**
5. **No MCP built-in** — but extensions can add it
6. **Skill standard** — follows Agent Skills standard (SKILL.md format)

---

## 2. Package Architecture

```
packages/
├── ai/           — @mariozechner/pi-ai          — Unified LLM API (25+ providers)
├── agent/        — @mariozechner/pi-agent-core   — Agent runtime, tool calling, state mgmt
├── coding-agent/ — @mariozechner/pi-coding-agent — CLI, TUI, extensions, sessions, RPC/SDK
├── tui/          — @mariozechner/pi-tui          — Terminal UI library (differential rendering)
├── web-ui/       — @mariozechner/pi-web-ui       — Web components for chat interfaces
├── pods/         — @mariozechner/pi-pods         — vLLM GPU pod management
└── mom/          — @mariozechner/pi-mom          — Slack bot delegating to pi
```

### Dependency Chain
```
pi-ai (LLM abstraction)
  └── pi-agent-core (tool calling, agent loop, state)
        └── pi-coding-agent (CLI, TUI, extensions, sessions, RPC, SDK)
              ├── pi-tui (terminal rendering)
              ├── pi-web-ui (web components)
              ├── pi-pods (GPU management)
              └── pi-mom (Slack bot)
```

### For KubeSynapse: Primary integration targets
| Package | Integration Purpose |
|---------|-------------------|
| `pi-coding-agent` (RPC mode) | **Agent runtime** — replace OpenCode with pi as the agent engine |
| `pi-ai` | **LLM provider** — unified API for 25+ model providers |
| `pi-agent-core` | **Agent state** — tool calling, message management, agent loop |
| `pi-coding-agent` (SDK) | **Programmatic embedding** — if we want in-process control |
| `pi-tui` | Not needed (KubeSynapse has its own web UI) |

---

## 3. Integration Modes — RPC vs SDK

### RPC Mode (Recommended for KubeSynapse)
- **Protocol**: JSON objects over stdin/stdout, LF-delimited JSONL
- **Language-agnostic**: Any language can spawn a pi subprocess and send/receive JSON
- **Commands**: `prompt`, `steer`, `follow_up`, `abort`, `set_model`, `set_thinking_level`, `get_state`, `get_messages`, `bash`, `compact`, `new_session`, `fork`, `switch_session`, `export_html`, `get_commands`, `set_session_name`
- **Events**: `agent_start`, `agent_end`, `turn_start`, `turn_end`, `message_start`, `message_update`, `message_end`, `tool_execution_start`, `tool_execution_update`, `tool_execution_end`, `queue_update`, `compaction_start`, `compaction_end`, `auto_retry_start`, `auto_retry_end`, `extension_error`
- **Extension UI**: Dialog sub-protocol (`select`, `confirm`, `input`, `editor`) and fire-and-forget (`notify`, `setStatus`, `setWidget`)
- **Session persistence**: JSONL files on disk (tree-structured, id/parentId linking)
- **Startup**: `pi --mode rpc --no-session` (ephemeral) or with sessions

#### RPC Command Flow
```
KubeSynapse API Gateway → Python wrapper → spawn pi --mode rpc → send JSON commands → read JSON events → stream to client
```

#### RPC Protocol Framing Rules (CRITICAL)
- Split records on `\n` ONLY (not `\r\n`, not Unicode separators)
- Strip trailing `\r` if present
- Do NOT use Node `readline` (splits on U+2028/U+2029)

### SDK Mode (Alternative)
```typescript
import { createAgentSession, SessionManager, AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";
const { session } = await createAgentSession({ sessionManager: SessionManager.inMemory(), authStorage, modelRegistry });
await session.prompt("Hello");
session.subscribe((event) => { /* handle events */ });
```
- Requires Node.js in process (not possible from Python backend directly)
- Could be used via a Node.js sidecar process with its own RPC/proxy
- More type-safe, direct access to AgentSession API

---

## 4. KubeSynapse ↔ Pi Architecture Mapping

| KubeSynapse Concept | Pi-Mono Equivalent | Integration Mechanism |
|------------------|-------------------|----------------------|
| `AIAgent` CRD | `AgentSession` + `SessionManager` | Spawn pi RPC subprocess per agent |
| `AgentWorkflow` steps | Sequential `session.prompt()` calls | RPC `prompt` command per step |
| A2A communication | Pi extensions with custom tools | KubeSynapse extension registers A2A tool |
| MCP connections | Pi extensions with sidecar tools | KubeSynapse extension registers MCP tool |
| `systemPrompt` on AIAgent | `SYSTEM.md` / `AGENTS.md` / `--system-prompt` | Inject via RPC or ResourceLoader |
| LLM provider config | `auth.json` + `models.json` + env vars | Provision via operator |
| Agent memory/sessions | Pi `SessionManager` JSONL files | Persistent session storage |
| Operator reconciler | `createAgentSession` SDK | Operator spawns/manages pi processes |
| Web UI chat | RPC events → WebSocket → browser | API gateway proxies pi events |
| Artifacts | File system (pi tools write to disk) | Shared volume mounts |
| Agent permissions | Pi extensions (permission gates) | KubeSynapse permission extension |

---

## 5. Critical Integration Points

### 5.1 Provider & Model Configuration
Pi needs:
- `auth.json` — API keys per provider (or env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)
- `models.json` — custom models (optional)
- Provider selection via `--provider` / `--model` CLI flags or `set_model` RPC command
- 25+ built-in providers: Anthropic, OpenAI, Google, Azure, Bedrock, Mistral, Groq, Cerebras, xAI, OpenRouter, Ollama, Hugging Face, etc.

**KubeSynapse mapping**: The operator already provisions `KubeSynapse_LLM_API_KEYS` secret. We map these to pi's `auth.json` or env vars.

### 5.2 System Prompt & Context Files
Pi's system prompt chain:
```
1. Default system prompt (minimal, ~200 tokens)
2. SYSTEM.md (replaces or appends)
3. AGENTS.md files (from ~/.pi/agent/, parent dirs, cwd)
4. Skills (on-demand via /skill:name)
5. before_agent_start extension handler (can modify)
6. --system-prompt / --append-system-prompt CLI flags
```

**KubeSynapse mapping**: 
- AIAgent.spec.systemPrompt → `--system-prompt` or SYSTEM.md
- AGENTS.md → project context files 
- Skills → can be pre-loaded from ConfigMaps

### 5.3 Tool Set
Pi ships with 7 built-in tools: `read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`

Additional tools via extensions:
- Custom tools via `pi.registerTool()`
- MCP integration (via extension)
- A2A communication (via extension)

**KubeSynapse mapping**:
- Built-in tools → enable/disable per agent via `--tools read,bash,edit,write` or `--no-tools`
- MCP tools → KubeSynapse MCP extension (registers MCP client as tools)
- A2A tools → KubeSynapse A2A extension (registers peer agent invocation as tool)

### 5.4 Session Management
Pi sessions are JSONL files with tree structure:
```
~/.pi/agent/sessions/--<cwd>--/<timestamp>_<uuid>.jsonl
```

Session features:
- **Tree navigation** (`/tree`, `branch()`, `navigateTree()`)
- **Forking** (`/fork`, `fork()`)
- **Compaction** (auto/manual summarization)
- **Labels** (bookmarks in session tree)
- **Custom entries** (extension state persistence)
- **Session info** (display name via `/name`)

**KubeSynapse mapping**:
- Sessions stored on PVC per agent
- Session listing via RPC `get_state` / SDK `SessionManager.list()`
- Fork/new-session for workflow branching
- Session export for audit trails

### 5.5 Pi Extensions (The Key to KubeSynapse Integration)
Extensions are TypeScript modules that run inside pi's process:
```typescript
export default function (pi: ExtensionAPI) {
  pi.registerTool({ name: "my_tool", ... });
  pi.registerCommand("my-cmd", { ... });
  pi.on("tool_call", async (event, ctx) => { ... });
  pi.on("before_agent_start", async (event, ctx) => { ... });
  // ... full event system
}
```

Extension capabilities:
- **Custom tools** (LLM-callable)
- **Commands** (/slash commands)
- **Event handlers** (25+ lifecycle events)
- **Permission gates** (block dangerous operations)
- **Custom UI** (TUI components, status bars)
- **Session persistence** (`pi.appendEntry()`)
- **Provider registration** (`pi.registerProvider()`)
- **Message injection** (`pi.sendMessage()`, `pi.sendUserMessage()`)
- **Compaction customization** (`session_before_compact`)

**KubeSynapse WILL build these extensions**:
1. **`KubeSynapse-a2a`** — A2A agent communication tool
2. **`KubeSynapse-mcp`** — MCP server integration tool  
3. **`KubeSynapse-permissions`** — Permission gating aligned with KubeSynapse policies
4. **`KubeSynapse-artifacts`** — Artifact storage/journal integration
5. **`KubeSynapse-observability`** — Tracing/metrics export from agent runs
6. **`KubeSynapse-session-sync`** — Session state sync with KubeSynapse API gateway

---

## 6. Awesome-Pi-Agent Ecosystem

The `awesome-pi-agent` repository (685 stars) catalogs the pi extension ecosystem. Key resources relevant to KubeSynapse:

### Extensions We Could Reuse
| Extension | Relevance to KubeSynapse |
|-----------|----------------------|
| `mitsuhiko/agent-stuff` — Skills (commit, changelog, GitHub, tmux, Sentry) | GitHub integration, Sentry monitoring |
| `qualisero/rhubarb-pi` — safe-git (approval before dangerous git ops) | Permission gating pattern |
| `gondolin` — Linux micro-VM sandbox with Pi integration | Sandboxed agent execution |
| `nono` — Kernel-enforced capability sandbox (Landlock/Seatbelt) | Security hardening |
| `task-factory` — Queue-first work orchestrator for Pi | Workflow orchestration pattern |
| `pi-dcp` — Dynamic context pruning | Session optimization |
| `opencode-dynamic-context-pruning` — Context optimization | Session optimization |

### Skills We Could Reuse
| Skill | Relevance |
|-------|-----------|
| `badlogic/pi-skills` — brave-search, browser-tools, gmail, calendar | MCP-like capabilities via skills |
| `pi-amplike` — Web search and webpage extraction | Web access for agents |

### Patterns Worth Adopting
- **Pi Packages** — npm/git distribution of extensions+skills+prompts+themes
- **settings.json** — global + project-level configuration merging
- **Extension auto-discovery** — `~/.pi/agent/extensions/`, `.pi/extensions/`
- **Skill progressive disclosure** — on-demand loading, no prompt cache busting

---

## 7. Security Considerations

### Pi's Security Model
- **Extensions run with full system permissions** — can execute arbitrary code
- **No built-in sandbox** — relies on extensions or OS-level isolation
- **Tool call gating** — extensions can block dangerous operations
- **Path protection** — extensions can prevent writes to sensitive files

### KubeSynapse Security Advantages
- **Kubernetes pods as isolation boundary** — each agent runs in its own pod
- **NetworkPolicies** — egress/ingress filtering
- **gVisor/runsc** — optional sandbox for untrusted code execution
- **RBAC** — least-privilege ServiceAccounts
- **PodSecurityStandards** — baseline/restricted profiles
- **Secret management** — no API keys in CRs, only references to Secrets

### Pi-Specific Security Hardening
1. Run pi as non-root user (already done for OpenCode runtime)
2. Mount `readOnlyRootFilesystem: true` where possible
3. Use `pi --no-tools` + selective `--tools read,grep,find` for read-only agents
4. Add KubeSynapse permission extension that checks A2A policies
5. Disable piped stdin mode to prevent prompt injection
6. Use `--no-session` for stateless agents (or encrypt session files at rest)

---

## 8. Resource Requirements

### Pi Process
- **Runtime**: Node.js 20+ (pi is TypeScript/Node)
- **Memory**: ~200MB baseline (Node.js + pi code), grows with session
- **CPU**: ~1 core during LLM response processing
- **Disk**: Session files (JSONL) — typically 100KB–10MB per session
- **Startup time**: ~2-5s (Node.js startup + extension loading)

### Comparison with OpenCode
| Metric | OpenCode (native binary) | Pi (Node.js) |
|--------|--------------------------|--------------|
| Binary size | 146 MB | ~50 MB (npm package) |
| Memory baseline | ~100 MB | ~200 MB |
| Startup time | ~1-3s | ~2-5s |
| Provider support | Limited (depends on binary build) | 25+ built-in |
| Extensibility | Custom (not standardized) | TypeScript extensions API |
| Session format | SQLite | JSONL (tree-structured) |
| Streaming | HTTP SSE | stdin/stdout JSONL |
| Subprocess model | Yes (our wrapper spawns OpenCode) | Yes (RPC mode designed for this) |

---

## 9. Files to Create for Integration

```
kubemininions/
├── pi-runtime/                          # NEW: Pi agent runtime Docker image
│   ├── Dockerfile                       # Node 22 + pi-coding-agent + KubeSynapse extensions
│   ├── package.json                     # Dependencies: pi-coding-agent, pi-ai, pi-agent-core
│   ├── extensions/                      # KubeSynapse-specific pi extensions
│   │   ├── KubeSynapse-a2a/
│   │   │   ├── index.ts                 # A2A communication tool
│   │   │   └── package.json
│   │   ├── KubeSynapse-mcp/
│   │   │   ├── index.ts                 # MCP client integration
│   │   │   └── package.json
│   │   ├── KubeSynapse-permissions/
│   │   │   ├── index.ts                 # Permission gating
│   │   │   └── package.json
│   │   ├── KubeSynapse-artifacts/
│   │   │   ├── index.ts                 # Artifact management
│   │   │   └── package.json
│   │   └── KubeSynapse-observability/
│   │       ├── index.ts                 # Tracing/metrics
│   │       └── package.json
│   └── entrypoint.sh                    # Pi RPC mode startup
├── operator/
│   ├── builders/
│   │   └── manifests.py                 # + pi_runtime_manifest() function
│   └── controllers/
│       └── agent_controller.py          # + pi runtime support
├── charts/kubesynapse/
│   └── templates/
│       └── agent-statefulset.yaml       # + pi runtime variant
└── docs/
    └── pi-mono-knowledge-base.md        # This file
    └── pi-integration-plan.md           # Detailed execution plan
```

---

## 10. Key API Reference (Quick Reference)

### RPC Commands (for Python wrapper to call)
| Command | Purpose | Critical for KubeSynapse |
|---------|---------|----------------------|
| `prompt` | Send user prompt to agent | Yes — workflow step execution |
| `steer` | Queue steering message during streaming | Yes — A2A intervention |
| `follow_up` | Queue follow-up after agent finishes | Yes — multi-step workflows |
| `abort` | Abort current operation | Yes — timeout/error handling |
| `set_model` | Switch LLM model | Yes — per-agent model config |
| `set_thinking_level` | Set reasoning depth | Optional |
| `get_state` | Get session state (streaming, model, etc.) | Yes — status monitoring |
| `get_messages` | Get full conversation | Yes — session sync |
| `bash` | Execute shell command | Yes — pre/post hooks |
| `compact` | Manual context compaction | Yes — session management |
| `new_session` | Start fresh session | Yes — workflow isolation |
| `fork` | Fork from message | Optional — branching |
| `get_commands` | List available skills/templates/commands | Yes — capability discovery |
| `set_session_name` | Name the session | Optional — UI display |

### RPC Events (for Python wrapper to handle)
| Event | Contains | KubeSynapse handler |
|-------|----------|-------------------|
| `message_update` | Streaming text/thinking/toolcall deltas | Proxy to WebSocket → web UI |
| `tool_execution_start` | Tool name, args | Logging, observability |
| `tool_execution_end` | Tool result, error status | Artifact saving, error tracking |
| `agent_start` | (none) | Session state update |
| `agent_end` | All messages | Workflow step completion |
| `turn_start/turn_end` | Turn number, message, tool results | Step progress tracking |
| `compaction_start/end` | Token counts, summary | Session optimization |
| `extension_error` | Extension path, error | Error reporting |

### SessionManager API (for session management)
| Method | Purpose |
|--------|---------|
| `SessionManager.create(cwd, dir?)` | New session |
| `SessionManager.open(path)` | Open existing |
| `SessionManager.continueRecent(cwd)` | Resume latest |
| `SessionManager.list(cwd)` | List project sessions |
| `SessionManager.forkFrom(source, targetCwd)` | Fork session |
| `sm.getEntries()` | All entries |
| `sm.getTree()` | Tree structure |
| `sm.getPath()` | Path to leaf |
| `sm.branch(entryId)` | Navigate tree |
| `sm.buildSessionContext()` | Messages for LLM |
| `sm.appendMessage(msg)` | Add message |
| `sm.appendCompaction(...)` | Add compaction |
| `sm.appendCustomEntry(...)` | Extension state |
