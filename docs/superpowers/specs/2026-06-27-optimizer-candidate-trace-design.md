# Optimizer Candidate Trace Design

## Goal

Make every optimization candidate explainable from its candidate view. Users must be able to quickly see how the optimizer arrived at the candidate, which observable reasoning summaries and tools were involved, which skills and workflow resources informed it, and what the final candidate decision was.

## Product Boundary

The feature records and displays the optimizer's observable execution trace. It does not claim to expose hidden model chain-of-thought. The trace includes runtime-emitted reasoning summaries, tool calls, status transitions, selected model and agent, referenced skills and resources, final response, fallback state, and candidate validation outcome.

## Data Contract

Each `OptimizationCandidate` gains an `optimizer_trace` object:

- identity: request id, thread id, optimizer agent, model, status
- timing: started, completed, duration
- execution summary: event count, tool count, reasoning-event count, fallback state
- chronological events: status, reasoning, tool, response, warning, error, and completion records
- tool calls and artifacts returned by the runtime
- skills and resources used, derived from the structured optimizer decision record

The gateway sanitizes and bounds the submitted trace before persistence. Candidate reads return the same durable trace after navigation, reload, or gateway restart. Older candidates without this field remain valid and render a clear legacy empty state.

## Capture Flow

The web client starts a trace before opening the optimizer stream. Every meaningful SSE event is normalized immediately with a timestamp, sequence number, kind, title, summary, and bounded payload. The completed invoke response adds final tool calls, artifacts, model, thread id, and response metadata. Fallback generation records the streaming error and fallback decision rather than pretending the optimizer completed normally.

The normalized trace is sent with candidate generation. The gateway redacts secret-like keys and token-like values, limits event and payload sizes, and persists the result on the candidate.

## Candidate Experience

The existing `Agent` workspace tab becomes `Optimizer trace`.

The surface uses:

- a compact summary strip for status, duration, model, events, tools, and skills
- filter chips for all activity, reasoning summaries, tools, decisions, and errors
- a narrow chronological event rail
- a wider inspector for the selected event
- collapsible context sections for skills/resources and the final visible response

The old repeated topology, generation, skills, decision-record, and response cards are consolidated into this single workspace. Candidate selection automatically shows that candidate's persisted trace.

## Security And Reliability

- Never label observable summaries as private chain-of-thought.
- Redact credentials and authorization-like values server-side.
- Bound events, strings, nested depth, tool calls, and artifacts.
- Preserve old API consumers by making `optimizer_trace` optional.
- Do not mutate the source workflow or optimizer runtime contract.
- Persist fallback/error events so failed or degraded generation is auditable.

## Testing

- API tests prove trace persistence, redaction, bounding, and legacy compatibility.
- Frontend contract tests prove candidate parsing, trace capture, filters, timeline/inspector UI, and chain-of-thought-safe wording.
- TypeScript and production builds verify the integrated contract.

