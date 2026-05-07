# KubeSynapse Runtime Unification Guide

This document ties the upstream runtime products to the local KubeSynapse runtime contract. It is the reference to hand to engineers implementing or onboarding a custom runtime.

## Canonical Contract

The source of truth for the KubeSynapse runtime API is:

- `docs/runtime-api-spec.md`
- `docs/runtime-api-spec.yaml`

Custom runtimes should implement the contract, not the upstream OpenCode, Pi, or Vibe product APIs directly.

## Required Endpoint Tiers

### Core Tier

Every production runtime must implement:

- `GET /health`
- `GET /ready`
- `GET /info`
- `GET /capabilities`
- `POST /invoke`
- `POST /invoke/stream`
- `POST /cancel`

### Session Tier

Implement when the runtime has a durable session model:

- `GET /todo`
- `GET /question`
- `POST /question/{id}/reply`
- `POST /question/{id}/reject`
- `GET /diff`
- `GET /context-budget`

### Artifacts Tier

Implement when the runtime can expose workspace files safely:

- `GET /artifacts/list`
- `GET /artifacts/download`
- `GET /artifacts/zip`

### Streaming Tier

Advertise only when the runtime supports the extra live subscription surface:

- `GET /events`

`POST /invoke/stream` is still part of the core tier.

## Current KubeSynapse Runtime Surface

### OpenCode Runtime

Local adapter: `opencode-runtime/main.py`

Current contract posture:

- core tier: implemented
- session tier: implemented
- artifacts tier: implemented
- streaming tier: not advertised
- compatibility alias: `POST /abort`

Notable local traits:

- truthful session-backed helpers
- provider-flexible
- strongest context-budget and session projection story

### Pi Runtime

Local adapter: `pi-runtime/pi_bridge.js`

Current contract posture:

- core tier: implemented
- session tier: implemented, but some helpers are simplified projections today
- artifacts tier: implemented
- streaming tier: advertised because `GET /events` exists
- upstream compatibility aliases: `/state`, `/prompt`, `/api/*` aliases

Notable local traits:

- bridge over upstream RPC, not an HTTP-native product
- provider, model, and thinking-level are first-class bridge concerns
- Windows local validation will not fully initialize the Pi subprocess because FIFO creation relies on `mkfifo`

### Mistral Vibe Runtime

Local adapter: `vibe-runtime/main.py`

Current contract posture:

- core tier: implemented
- session tier: implemented
- artifacts tier: implemented
- streaming tier: not advertised
- compatibility alias: `POST /abort`

Notable local traits:

- wrapper over CLI or agent-loop behavior
- strong skill, tool, and agent-profile model upstream
- some session helper endpoints remain light projections today

## Unification Rules for Custom Runtime Authors

### Rule 1: Treat Upstream Product APIs as Inputs, Not Standards

If you are adapting an existing product, do not expose its native API shape directly. Map it into the KubeSynapse runtime contract.

Examples:

- OpenCode upstream session APIs are not the runtime API.
- Pi upstream JSONL RPC is not the runtime API.
- Vibe CLI slash commands are not the runtime API.

### Rule 2: `/capabilities` Must Tell the Truth

Do not advertise a tier unless every endpoint and behavior in that tier is actually implemented.

Examples:

- advertise `streaming` only when `GET /events` exists
- advertise `session` only when TODO, question, diff, and context helpers are meaningful
- advertise `artifacts` only when file operations are safe and scoped

### Rule 3: Health and Ready Must Be Machine-Readable

Use normalized status fields:

- `/health`: `healthy` or `unhealthy`
- `/ready`: `ready` or `not_ready`

Return supporting fields like `runtime`, `checks`, `timestamp`, `service`, `namespace`, and any adapter-specific detail needed for operations.

### Rule 4: `info` Is the Contract Declaration

At minimum, return:

- `runtime`
- `contract_version`
- `service`
- `namespace`
- `provider`
- `model`
- `agent`
- `version`

Use `contract_version: v1` for the current KubeSynapse runtime contract.

### Rule 5: Session Helpers Should Be Real Projections When Possible

Prefer:

- real TODO state
- real pending question state
- real diff state
- real context telemetry

Avoid placeholder data except as a temporary bridge step, and document it if you must keep it.

### Rule 6: Streaming Must Use the Canonical SSE Taxonomy

Canonical event names:

- `response.started`
- `response.delta`
- `response.tool_call`
- `response.tool_result`
- `todo.updated`
- `question.asked`
- `todo.cleared`
- `response.completed`
- `response.error`

This is the stable surface for UIs and gateway consumers.

### Rule 7: Keep Observability Runtime-Native

Every runtime should emit:

- run started
- run completed or errored
- `llm.call` with token or cost metadata where available
- tool-call telemetry where available

If upstream provides token or cost metadata, do not drop it in the wrapper.

## Upstream Product Fit Summary

| Concern | OpenCode | Pi Mono | Mistral Vibe |
| --- | --- | --- | --- |
| Native session model | Strong | Strong | Strong |
| Native HTTP surface | Moderate | Weak | Weak |
| Native RPC or event loop | Moderate | Strong | Strong |
| Tool richness | Very strong | Strong | Strong |
| MCP richness | Very strong | Extension-driven | Strong |
| Skill system | Strong | Strong | Strong |
| Best adapter style | session projection | RPC bridge | CLI or agent-loop wrapper |

## Recommended Implementation Checklist for a New Runtime

1. Implement the core tier exactly as documented in `docs/runtime-api-spec.md`.
2. Add a truthful `capabilities.tiers` array.
3. Add `info.contract_version = v1`.
4. Normalize `health` and `ready` status strings.
5. Implement `invoke/stream` using the canonical SSE event taxonomy.
6. Emit runtime observability events for runs, tools, and LLM calls.
7. Add `session` endpoints only when the runtime has enough state to support them honestly.
8. Add `artifacts` endpoints only when workspace access is safe and bounded.
9. Add focused contract tests for the discovery, readiness, and streaming surfaces.
10. Document the upstream product assumptions and adapter boundaries in a checked-in reference doc.

## What Changed Locally in This Pass

The current KubeSynapse repo now aligns its local runtime discovery and readiness contract more closely across the three shipped runtimes:

- OpenCode now reports `contract_version: v1`, normalized health status values, truthful tiers, and an `/abort` alias.
- Vibe now reports truthful tiers and normalized readiness payloads.
- Pi now reports normalized health or ready payloads, truthful runtime metadata, and a launchable CommonJS package mode for the bridge.

That leaves one practical boundary explicit for custom runtime authors:

- upstream product differences are acceptable internally
- the outward KubeSynapse runtime API must remain uniform
