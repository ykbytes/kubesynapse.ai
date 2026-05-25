# OpenCode Upstream Reference

This document summarizes the official OpenCode runtime surface from the upstream repository and documentation so KubeSynapse runtime work can stay grounded in the original product rather than in wrapper assumptions.

## Official Sources

- Official site: https://opencode.ai
- Official docs: https://opencode.ai/docs
- Official repository: https://github.com/anomalyco/opencode
- Primary in-repo docs used for grounding:
  - `README.md`
  - `CONTRIBUTING.md`
  - `SECURITY.md`
  - `AGENTS.md`
  - `packages/opencode/src/`
  - `packages/function/src/`
  - `packages/opencode/src/provider/`
  - `packages/opencode/src/session/`
  - `packages/opencode/src/tool/`
  - `packages/opencode/src/config/`
  - `packages/opencode/src/cli/cmd/`

## Product Shape

OpenCode is not a thin HTTP runtime in upstream form. It is a full coding-agent product with a CLI, TUI, server mode, session store, tool registry, provider abstraction, MCP integration, agent profiles, and cloud sharing backend. KubeSynapse's `opencode-runtime` is therefore an adapter over a much larger platform surface.

## Primary Execution Surfaces

### CLI

OpenCode's main upstream entrypoint is the `opencode` CLI.

Representative command groups from the upstream tree:

- `serve`
- `web`
- `tui`
- `session`
- `run`
- `models`
- `providers`
- `db`
- `import`
- `export`
- `mcp`
- `github`
- `pr`
- `account`
- `upgrade`
- `stats`
- `debug`

This matters for KubeSynapse because the local runtime is effectively driving the upstream server and session surfaces on the user's behalf.

### Headless Server Mode

OpenCode upstream supports a headless server mode for remote or browser-backed usage. That server mode is distinct from the KubeSynapse runtime contract. It exposes upstream-specific session and server endpoints that the local adapter translates into the KubeSynapse runtime API.

Key implications:

- OpenCode already has a session-oriented backend model.
- KubeSynapse should continue to treat OpenCode as session-native.
- The KubeSynapse runtime contract should stay a translation layer, not a fork of the upstream API.

### Cloud Backend and Sharing

Upstream OpenCode also has cloud/backend components for sharing and synchronization. Those are not the same as KubeSynapse APIs and should not leak into the runtime contract.

Relevant upstream capabilities include:

- share creation
- share deletion
- share sync
- polling or websocket subscription for shared state
- support workflows around GitHub and notifications

These are upstream product features, not required capabilities for KubeSynapse custom runtime authors.

## Session Model

OpenCode upstream has a rich session system and persistent data model.

Important concepts present upstream:

- session identifiers and message identifiers
- parent-child session hierarchies
- per-project and per-workspace session grouping
- message tables and part tables
- TODO storage
- compaction and overflow handling
- revert or unrevert state
- instruction tracking
- summary generation

Grounding takeaway for KubeSynapse:

- OpenCode is the most naturally aligned upstream runtime for the KubeSynapse `session` tier.
- The local runtime should expose session helpers as projections of the upstream session store, not synthetic approximations.

## Provider and Model Capabilities

OpenCode upstream has a broad provider abstraction rather than a single-model runtime.

Documented upstream provider families include:

- Anthropic
- OpenAI
- Azure OpenAI
- Google Generative AI
- Google Vertex AI
- Amazon Bedrock
- Mistral
- Groq
- DeepInfra
- Cerebras
- Cohere
- TogetherAI
- Perplexity
- xAI
- OpenRouter
- Vercel AI Gateway
- GitHub Copilot
- GitLab AI
- OpenAI-compatible endpoints
- additional ecosystem providers routed through provider plugins

Model metadata handled upstream includes:

- context limits
- output limits
- tool-call support
- reasoning support
- modality support
- cost metadata
- cache-read and cache-write pricing
- release status and family metadata

Grounding takeaway for KubeSynapse:

- The KubeSynapse `info` and `capabilities` endpoints for OpenCode should advertise the runtime as multi-provider and session-native.
- Wrapper code should avoid baking in one provider assumption unless explicitly configured.

## Tooling Surface

Upstream OpenCode ships a large built-in tool registry. The major categories are:

### File and Search Tools

- read
- write
- edit
- glob
- grep
- apply_patch

### Execution

- shell

The shell tool supports multiple shell environments, timeout control, output truncation, and policy analysis around file access.

### Discovery and External Access

- webfetch
- websearch
- skill

### Planning and Control

- plan
- question
- todo
- todowrite
- task

### Code Intelligence

- LSP-backed tooling where enabled

Grounding takeaway for KubeSynapse:

- `opencode-runtime` should keep reporting a broad native tool surface.
- Capability docs for custom runtimes should not assume every runtime has OpenCode's breadth.

## Agent Model

Upstream OpenCode has built-in agent profiles rather than a single undifferentiated runtime personality.

Common built-ins include:

- `build`
- `plan`
- `general`
- `explore`

Configurable per-agent concerns include:

- model selection
- temperature or sampling choices
- prompt selection
- permission rules
- max steps or iterations
- visibility and routing
- color or UI presentation metadata

Grounding takeaway for KubeSynapse:

- agent metadata is upstream-native in OpenCode
- KubeSynapse can surface agent selection and team-routing behavior for OpenCode without inventing a new agent model

## MCP and Integration Surface

OpenCode upstream supports both local-command and remote-URL MCP configurations.

Important upstream MCP capabilities:

- command-based local MCP servers
- remote MCP URLs
- request headers
- OAuth configuration
- startup enablement
- timeouts
- server management CLI

Grounding takeaway for KubeSynapse:

- OpenCode is the strongest reference implementation for MCP-rich runtimes.
- Custom runtimes do not need to implement MCP to satisfy the KubeSynapse core tier, but if they do, OpenCode is the best upstream example for discovery and routing behavior.

## Memory and Context Handling

Upstream OpenCode has explicit systems for:

- session memory
- message compaction
- overflow handling
- system instruction synthesis
- substitution variables
- revert-safe context management

Grounding takeaway for KubeSynapse:

- OpenCode can support truthful `/context-budget` behavior.
- The local adapter should continue to expose real session-derived context telemetry rather than static placeholder values.

## Workspace and Artifact Handling

Upstream OpenCode is deeply workspace-aware.

Major concepts:

- project-level state
- workspace IDs
- VCS integration
- project configuration
- multi-session histories bound to directories

Grounding takeaway for KubeSynapse:

- artifact endpoints are a natural fit for OpenCode.
- the runtime adapter can safely expose workspace listing, file download, and archive operations as first-class runtime capabilities.

## Configuration and Auth

OpenCode upstream has structured provider configuration and environment handling.

Important config dimensions include:

- provider API keys
- provider base URLs
- model variants
- headers and timeout controls
- prompt caching behavior
- model registry source

The upstream server mode also has optional authentication concerns for remote access.

Grounding takeaway for KubeSynapse:

- The local runtime should keep configuration generation explicit and reproducible.
- KubeSynapse docs for custom runtimes should separate runtime auth from model-provider auth.

## KubeSynapse-Relevant Mapping

How upstream OpenCode maps into the KubeSynapse runtime API:

| KubeSynapse Concern | Upstream OpenCode Fit | Notes |
| --- | --- | --- |
| `/health` | Strong | Can reflect process and session state truthfully |
| `/ready` | Strong | Can verify binary plus server startup |
| `/info` | Strong | Upstream metadata is rich enough to expose contract and provider info |
| `/capabilities` | Strong | Native tool and session capabilities are first-class upstream concepts |
| `/invoke` | Strong | Natural synchronous wrapper over upstream session prompt flow |
| `/invoke/stream` | Strong | OpenCode is stream-native |
| `/cancel` and `/abort` | Strong | Session cancellation is upstream-native |
| `/todo` | Strong | TODO storage exists upstream |
| `/question` | Strong | HITL questions exist upstream |
| `/diff` | Strong | Session diff is naturally derivable |
| `/context-budget` | Strong | Upstream tracks context and overflow explicitly |
| Artifacts | Strong | Workspace-aware by design |

## What KubeSynapse Should Not Assume

- OpenCode's upstream session and cloud APIs are not the KubeSynapse runtime API.
- Not every upstream OpenCode tool or provider should be surfaced automatically unless configured.
- Sharing, account, and cloud backend features are product features, not required runtime contract features.

## Practical Grounding Rules

When making `opencode-runtime` changes in KubeSynapse, prefer these assumptions:

1. OpenCode is session-first, not stateless.
2. OpenCode is multi-provider and multi-agent.
3. The wrapper should expose KubeSynapse contract fields as projections of upstream state whenever possible.
4. Session helpers and context telemetry should remain truthful and not devolve into placeholders.
5. Upstream CLI or server features should only surface through the KubeSynapse runtime API when they map cleanly to the contract.
