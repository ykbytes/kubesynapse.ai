---
title: "Execution Observatory: Distributed Tracing for AI Agents"
date: "2026-04-25"
author: "KubeSynapse Team"
tags: ["feature", "observability", "traces"]
summary: "Full distributed tracing for every agent invocation and workflow run. Inspect LLM calls, measure step timing, track token usage, and compare executions."
slug: "execution-observatory"
published: true
---

Observability is not optional when AI agents operate inside production infrastructure. Every agent invocation, every LLM call, every tool use must be traceable and auditable.

The **Execution Observatory** brings distributed tracing to KubeSynapse.

## What It Captures

Every execution — whether a single agent invocation or a multi-step workflow — produces an `ExecutionTrace` with:

- **Step-level timing** — how long each workflow step took
- **LLM call details** — model, prompt tokens, completion tokens, latency
- **Tool invocations** — which MCP tools were called, with inputs and outputs
- **Status tracking** — completed, failed, or timed out at each stage
- **Token usage** — aggregate and per-step token consumption

## The Interface

The Observatory provides five tabs:

### Overview
A dashboard view with key execution metrics: total steps, LLM calls, tool calls, tokens, cost, and signal warnings. Shows a step waterfall and anomaly signals detected during the run.

### Steps
A split-pane view: step list on the left, detail inspector on the right. Each step shows its LLM calls (with model, tokens, cost, latency) and tool calls (with expandable rows, icon+color mapping, duration, and status).

### Logs
Worker logs with filter modes (all, activity, errors, tooling), step-scoped filtering, JSON formatting toggle, line-wrap toggle, and fullscreen mode. Live log streaming is available for running workflows.

### Models & Tools
All LLM and tool calls for the execution. Tool calls expand inline to show:
- **ArgsCard** — key-value cards with primary field highlighting (URL, command, filePath, etc.)
- **ResultBlock** — auto-detects JSON for syntax highlighting via Prism, diff/patch content for GitHub-style colored rendering (green/red/purple/blue), or falls back to plain text
- **Truncated JSON handling** — auto-closes truncated JSON by appending missing brackets
- **Tool icons** — distinct icon and color for each tool type (search, bash, read, write, skill, etc.)

### Compare
Side-by-side diff of any two executions. Select from recent runs or paste execution IDs. Shows step-level differences in status, duration, and LLM/tool counts.

## How Traces Are Recorded

Traces are recorded end-to-end by the worker, runtime, and gateway during execution:

1. The operator worker invokes the runtime and accumulates step, LLM, and tool records in memory
2. As steps complete, the worker emits batched trace events to `POST /api/v1/traces/batch`
3. The gateway stores execution detail in PostgreSQL, including `tool_args`, `tool_result`, `duration_ms`, and `started_at`
4. The worker also forwards semantic runtime events into the Run Intelligence store for cross-run analysis

All trace data is stored in PostgreSQL and exposed through the REST API. Tool call results are stored as full JSON objects (`tool_args`, `tool_result`) with `duration_ms` and `started_at` timestamps. The runtime caps individual tool outputs at 40,000 characters to balance storage with meaningful data.

## Roadmap

- **OpenTelemetry export** — push traces to Jaeger, Grafana Tempo, or any OTLP-compatible backend
- **Alerting rules** — trigger notifications when step duration exceeds thresholds
- **Cost tracking** — map token usage to model pricing for budget visibility
- **Trace retention policies** — automatic cleanup of old traces
