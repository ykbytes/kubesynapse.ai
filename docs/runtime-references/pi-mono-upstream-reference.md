# Pi Mono Upstream Reference

This document summarizes the official `pi-mono` upstream runtime surface and documentation so KubeSynapse's Pi bridge stays grounded in upstream reality.

## Official Sources

- Primary site: https://pi.dev
- Official repository: https://github.com/badlogic/pi-mono
- Community: official Discord linked from the upstream README
- Primary in-repo docs used for grounding:
  - `README.md`
  - `CONTRIBUTING.md`
  - `packages/coding-agent/docs/`
  - `packages/coding-agent/examples/`
  - `packages/coding-agent/src/`
  - `packages/ai/src/`

## Product Shape

Pi upstream is not an HTTP runtime by default. It is primarily:

- a CLI agent
- an interactive TUI
- a programmatic SDK surface
- a JSONL RPC mode over stdin or stdout
- an extension-driven coding assistant

KubeSynapse's `pi-runtime` is therefore an HTTP bridge wrapped around an upstream RPC-native agent.

## Primary Execution Surfaces

### CLI

The main upstream entrypoint is the `pi` CLI.

Major CLI dimensions include:

- provider selection
- model selection
- thinking level selection
- text or JSON or RPC execution modes
- session continuation and resumption
- enabling or disabling tools
- extensions and skills loading

Grounding takeaway for KubeSynapse:

- Pi's native execution model is CLI and RPC first, not REST first.
- The KubeSynapse HTTP bridge must remain an adapter rather than a direct reflection of upstream APIs.

### RPC Mode

Pi's most important runtime integration surface is its JSONL RPC protocol.

Core upstream command shapes include:

- `prompt`
- `steer`
- `follow_up`
- `abort`
- `new_session`
- steering or follow-up mode toggles

The upstream event stream is also JSONL and includes lifecycle and tool execution events.

Grounding takeaway for KubeSynapse:

- `pi-runtime/pi_bridge.js` should continue to be treated as a protocol adapter between KubeSynapse HTTP and Pi RPC.
- Session state, cancellations, and streamed deltas all originate from the RPC loop.

## Session Model

Pi upstream has a persistent session model backed by JSONL session trees.

Important concepts:

- file-based session persistence
- message trees with parent IDs
- branching history
- compaction
- session resumption
- explicit session IDs and stored history

Grounding takeaway for KubeSynapse:

- Pi is session-capable upstream, even though the bridge may currently expose simplified helper behavior.
- Future KubeSynapse improvements should prefer real session projections over placeholders for TODOs, diff state, and context budgeting.

## Provider and Model Capabilities

Pi upstream supports a wide provider range, including both subscription-style auth and API-key auth.

Common provider categories surfaced upstream:

- Anthropic
- OpenAI and Codex
- GitHub Copilot
- Azure OpenAI
- Gemini and Vertex
- Mistral
- DeepSeek
- Groq
- Cerebras
- OpenRouter
- OpenAI-compatible local and remote backends
- additional ecosystem providers routed through the upstream AI layer

Pi also supports configurable thinking levels:

- `off`
- `minimal`
- `low`
- `medium`
- `high`
- `xhigh`

Grounding takeaway for KubeSynapse:

- Pi should be documented as a provider-flexible runtime.
- The bridge should keep surfacing `provider`, `model`, and `thinkingLevel` as first-class request or metadata concepts.

## Built-in Tools

Upstream Pi has a narrower built-in tool surface than OpenCode, but it still covers the core coding-agent needs.

Representative built-in tools include:

- `read`
- `bash`
- `write`
- `edit`
- `grep`
- `find`
- `ls`

The tool system is schema-validated and integrated into the agent loop.

Grounding takeaway for KubeSynapse:

- Pi should advertise a smaller native tool set than OpenCode.
- KubeSynapse should not over-claim features Pi does not expose natively.

## Extension System

Pi's biggest differentiator is its extension system.

Upstream extension capabilities include:

- registering custom tools
- registering slash commands
- hooking lifecycle events
- adding UI behaviors
- permission gates for tool execution
- extension state persistence through session entries
- hot reload through the CLI command surface

Grounding takeaway for KubeSynapse:

- Pi is the best upstream reference for extension-driven customization.
- KubeSynapse-side Pi features like artifacts, observability, MCP, git-safety, and A2A are naturally modeled as extensions or bridge helpers around this upstream model.

## Skills, Prompts, and Workspace Context

Pi upstream supports:

- skills discovery from project and user directories
- prompt templates with substitution
- context files
- keybinding customization
- workspace-aware current working directory behavior

Grounding takeaway for KubeSynapse:

- custom runtime authors should understand that Pi's upstream UX is highly file and prompt driven.
- the bridge can stay thin if the surrounding runtime files are materialized consistently.

## Authentication and Configuration

Pi upstream supports:

- auth file storage
- environment variable discovery
- provider auto-detection
- project-local and user-level settings
- configurable config directory layout

Key config themes include:

- default provider
- default model
- default thinking level
- compaction settings
- skills paths
- context files

Grounding takeaway for KubeSynapse:

- the KubeSynapse Pi runtime should keep generating auth and settings files explicitly from cluster configuration.
- API-key injection and base-URL overrides fit the upstream model cleanly.

## Agent Loop Semantics

Pi's upstream runtime behavior centers around an explicit agent loop:

- prompt begins a turn
- model produces deltas and tool calls
- tools execute
- tool results feed the next turn
- the loop ends when the agent resolves the task or is aborted

Grounding takeaway for KubeSynapse:

- Pi's `invoke/stream` behavior should continue to be modeled as a translation of these upstream events into the KubeSynapse canonical SSE taxonomy.

## KubeSynapse-Relevant Mapping

| KubeSynapse Concern | Upstream Pi Fit | Notes |
| --- | --- | --- |
| `/health` | Moderate | Bridge-level, not upstream-native |
| `/ready` | Moderate | Readiness is bridge plus subprocess health |
| `/info` | Strong | Can advertise provider, model, and bridge metadata |
| `/capabilities` | Strong | Good place to reflect tool and extension-backed features |
| `/invoke` | Strong | Natural bridge over RPC `prompt` |
| `/invoke/stream` | Strong | Best-fit projection of JSONL events into SSE |
| `/cancel` and `/abort` | Strong | Upstream abort is native |
| `/todo` | Weak to Moderate | Upstream has session data, but bridge may still project placeholders |
| `/question` | Moderate | Depends on how RPC approval prompts are surfaced |
| `/diff` | Weak to Moderate | Possible, but not a native upstream REST concern |
| `/context-budget` | Moderate | Upstream compaction and context logic exist, but bridge must project them |
| Artifacts | Moderate | More bridge-defined than upstream-defined |

## What KubeSynapse Should Not Assume

- Pi upstream is not an HTTP server product.
- Pi's native protocol is JSONL RPC rather than REST.
- Session helper endpoints in the bridge may need additional work before they fully reflect upstream state.
- Extension and skill systems are upstream-native, but KubeSynapse-specific HTTP helpers are not.

## Practical Grounding Rules

When making `pi-runtime` changes in KubeSynapse, prefer these assumptions:

1. The bridge is an adapter over an RPC-first runtime.
2. Provider and thinking-level controls are legitimate public runtime parameters.
3. Streaming fidelity matters more than inventing a large REST surface.
4. Placeholder session helpers should be treated as debt and replaced with real projections where possible.
5. Extension-backed customization is upstream-native and should remain the primary Pi extensibility story.
