# Mistral Vibe Upstream Reference

This document summarizes the official Mistral Vibe upstream runtime surface and documentation so KubeSynapse's `vibe-runtime` can stay aligned with the upstream tool rather than a simplified wrapper mental model.

## Official Sources

- Official repository: https://github.com/mistralai/mistral-vibe
- Package distribution: official PyPI package for `mistral-vibe`
- Main auth and account flow: official Mistral console
- Primary in-repo docs used for grounding:
  - `README.md`
  - `CHANGELOG.md`
  - `CONTRIBUTING.md`
  - `docs/acp-setup.md`
  - `docs/proxy-setup.md`
  - `vibe/core/`
  - `vibe/cli/`
  - `vibe/core/tools/`
  - `vibe/core/skills/`
  - `vibe/core/agents/`
  - `vibe/core/config/`

## Product Shape

Mistral Vibe upstream is primarily a Python CLI and agent-loop system with strong local configuration, agent profiles, built-in tools, MCP, skills, and project trust behavior. KubeSynapse's `vibe-runtime` is an HTTP wrapper over this CLI- and agent-loop-first runtime.

## Primary Execution Surfaces

### CLI and Terminal UX

Upstream Vibe supports:

- interactive chat or coding loop
- programmatic one-shot execution through `--prompt`
- slash commands
- voice mode
- file reference shortcuts
- auto-approval or profile-based approval modes

Grounding takeaway for KubeSynapse:

- the upstream runtime is interactive and agentic by default
- the KubeSynapse wrapper should keep the HTTP contract small and declarative rather than mirroring every CLI affordance

### Agent Loop

The central upstream runtime abstraction is `AgentLoop`.

Important characteristics:

- async-first execution
- streamed assistant events
- tool approval callbacks
- user input callbacks
- session continuation
- middleware pipeline
- token and cost accounting
- optional delegation workflows

Grounding takeaway for KubeSynapse:

- Vibe is event-driven and can support truthful streamed responses.
- The wrapper should continue to treat `invoke/stream` as a first-class path rather than a degraded variant of `invoke`.

## Session and Persistence Model

Upstream Vibe supports:

- resumable sessions
- compact session IDs
- log persistence under user state directories
- scheduled loops
- history files
- session continuation or resume by ID

Grounding takeaway for KubeSynapse:

- Vibe is session-capable upstream.
- KubeSynapse can support session helper endpoints, but only when the adapter can map them honestly from upstream state.

## Models and Provider Surface

Upstream Vibe defaults to Mistral models but is not single-backend in practice.

Documented upstream model or provider modes include:

- Mistral-hosted models
- local llama.cpp mode
- OpenAI-compatible backend configuration
- voice transcription models
- text-to-speech models

Upstream also tracks:

- thinking levels
- token usage
- cost accounting
- model aliases
- provider configuration in TOML settings

Grounding takeaway for KubeSynapse:

- `vibe-runtime` should advertise provider and model metadata clearly.
- model token or cost fields should come from upstream metadata when available.

## Built-in Tools

Major upstream built-in tools include:

- `read_file`
- `write_file`
- `search_replace`
- `bash`
- `grep`
- `todo`
- `ask_user_question`
- `task`
- `webfetch`
- `websearch`
- `skill`

The upstream tool model uses validated input schemas, permission policies, and asynchronous tool execution.

Grounding takeaway for KubeSynapse:

- Vibe is more capable than a simple prompt wrapper.
- KubeSynapse should continue surfacing session and question endpoints for Vibe, even when some current implementations are placeholder-like.

## MCP Integration

Upstream Vibe has formal MCP support.

Key upstream MCP concepts:

- stdio transport
- HTTP or streamable HTTP transport
- startup timeouts
- tool timeouts
- per-server naming
- per-tool disable lists
- optional sampling flows

Grounding takeaway for KubeSynapse:

- Vibe is a valid reference for custom runtimes that need MCP but do not want OpenCode.
- MCP is an optional capability, not a requirement of the KubeSynapse core runtime tier.

## Agent Profiles and Subagents

Upstream Vibe ships multiple built-in agent profiles.

Representative modes include:

- default
- plan
- accept-edits
- auto-approve
- custom agent profiles
- read-only or exploratory subagent roles

Grounding takeaway for KubeSynapse:

- Vibe supports profile-driven tool permissions and should be documented as agent-profile capable.
- the KubeSynapse wrapper can keep exposing one stable runtime contract while still mapping to different upstream profiles.

## Skills System

Vibe upstream supports an agent skills system based on Markdown plus YAML frontmatter.

Important features:

- project, user, and additional skill directories
- declarative metadata
- user-invocable skills
- allowed-tool restrictions
- parsing and discovery logic in the core runtime

Grounding takeaway for KubeSynapse:

- Vibe is a strong reference for custom skill-driven runtimes.
- KubeSynapse-generated skill materialization fits naturally into the upstream model.

## Workspace, Trust, and AGENTS Files

Vibe upstream has explicit concepts for:

- trusted folders
- project-local configuration
- AGENTS.md instructions
- project context gathering
- git status or commit history context

Grounding takeaway for KubeSynapse:

- Vibe is workspace- and project-aware.
- artifact and diff surfaces in the wrapper should be tied to real trusted project state where possible.

## Authentication and Configuration

Upstream Vibe supports:

- `MISTRAL_API_KEY`
- `.env` loading
- setup flows
- project-local `.vibe/config.toml`
- user-level `~/.vibe/config.toml`
- `VIBE_`-prefixed environment overrides

Common config themes include:

- active model
- project context behavior
- session logging
- per-tool permissions
- MCP servers
- connectors
- agent profile definitions

Grounding takeaway for KubeSynapse:

- the KubeSynapse wrapper should keep config translation explicit
- tool permission defaults and model routing should be treated as configuration, not hard-coded behavior

## KubeSynapse-Relevant Mapping

| KubeSynapse Concern | Upstream Vibe Fit | Notes |
| --- | --- | --- |
| `/health` | Strong | Runtime process and session counts are available |
| `/ready` | Moderate to Strong | Can reflect binary and workspace readiness |
| `/info` | Strong | Upstream metadata is rich |
| `/capabilities` | Strong | Tool and profile capabilities are explicit |
| `/invoke` | Strong | Clean wrapper over non-interactive programmatic mode |
| `/invoke/stream` | Strong | Natural fit for the async event loop |
| `/cancel` and `/abort` | Strong | Session status model supports it |
| `/todo` | Moderate | Native upstream concepts exist |
| `/question` | Strong | Ask-user tool is first-class upstream |
| `/diff` | Moderate | Can be derived from workspace changes |
| `/context-budget` | Moderate | Upstream context and compaction data exist |
| Artifacts | Moderate | Workspace support exists, but REST artifact semantics are wrapper-defined |

## What KubeSynapse Should Not Assume

- Vibe upstream is not an HTTP-native runtime.
- Not every CLI convenience belongs in the runtime API.
- Agent profiles and skill behavior should be expressed via config or metadata, not by multiplying HTTP endpoints.
- Artifact, diff, and session helper endpoints remain adapter responsibilities.

## Practical Grounding Rules

When making `vibe-runtime` changes in KubeSynapse, prefer these assumptions:

1. Vibe is agent-loop first and HTTP-wrapper second.
2. The upstream runtime is tool-rich, session-capable, and profile-driven.
3. Skill and AGENTS.md behavior are upstream-native and should stay aligned with that model.
4. Streaming support should remain canonical and event-based.
5. Session helper endpoints should become more truthful over time, not more synthetic.