---
name: kubesynapse-roadmap-handoff
description: 'Create KubeSynapse engineer handoff packets, roadmap breakdowns, observability remediation checklists, and file-by-file subtasks. Use when asked to hand a docs/ROADMAP.md story to another engineer, turn docs/observability-remediation-plan.md into an implementation checklist, map repo ownership for operator/api-gateway/runtimes/SDKs/UI/charts, define validations, or split a roadmap item into PR-sized work.'
argument-hint: 'Which KubeSynapse roadmap story, remediation workstream, or repo task should be turned into an engineer handoff?'
user-invocable: true
disable-model-invocation: false
---

# KubeSynapse Roadmap Handoff

## When to Use

Use this skill when the task is not "implement the fix now" but "hand this cleanly to another engineer first." This skill is for KubeSynapse-specific engineering handoff work tied to the repo roadmap and implementation plans.

Typical triggers:

- "Turn this roadmap item into engineer tasks"
- "Hand this to another engineer"
- "Break docs/observability-remediation-plan.md into file-by-file subtasks"
- "Prepare a PR plan for Story 10.2"
- "Map this KubeSynapse workstream to owning files and validation"
- "Create a checklist from docs/ROADMAP.md"

This skill is general across KubeSynapse roadmap and remediation work, but it is intentionally biased toward the current observability hardening backlog because that is the most detailed and cross-cutting roadmap slice in the repo right now.

## What This Skill Produces

The default output is an engineer-ready handoff packet plus a repo doc artifact, not a vague summary. Unless the user asks for chat-only output, create or update a checked-in handoff file under a path like `docs/engineering-handoffs/<story-or-workstream>-handoff.md` and summarize the result in chat.

A good handoff should contain:

1. The exact roadmap story or implementation slice being handed off
2. The source-of-truth docs and the owning code surfaces
3. File-by-file subtasks with concrete change intent
4. Validation steps scoped to the touched slice
5. Sequencing, compatibility, and rollout notes
6. Open questions, risks, and what must be decided before coding
7. Suggested PR boundaries when the work is too large for one change

Use the [engineer handoff template](./assets/engineer-handoff-template.md) as the default structure.

## KubeSynapse-Specific Mental Model

Do not flatten everything into one generic "observability" bucket. In this repo there are separate surfaces that often move together but are not the same thing:

1. Execution Observatory: execution traces, runtime events, timelines, spend, and run analytics
2. CRD observability: ObservationTarget, ObservationPolicy, ObservationReport, ConnectorPlugin, and their controller logic
3. Workflow log access: log archival, fallback loading, and UI log views

When a story touches one of these surfaces, say so explicitly. When it spans multiple surfaces, split the handoff by owning subsystem instead of producing one mixed checklist.

Use the [repo surface map](./references/repo-surface-map.md) to anchor the handoff to real files in this repository.

## Source-of-Truth Order

Use these sources in this order unless the user says otherwise:

1. The user request and the named story or workstream
2. `docs/ROADMAP.md` for the runtime-platform backlog and story definitions
3. `ROADMAP.md` for top-level release packaging and milestone framing
4. `docs/observability-remediation-plan.md` for the May 2026 observability hardening implementation plan
5. The owning code files that directly control the behavior

If the request names a roadmap story but there is no implementation plan yet, create the handoff from the roadmap story plus the owning code surfaces. If a detailed implementation doc exists, use that doc as the handoff backbone and expand it into file-by-file work.

## Procedure

### 1. Lock the Scope Before Expanding Tasks

Start by naming the exact slice being handed off:

- roadmap story
- workstream
- bug-fix bundle
- one PR slice
- one subsystem only

State the outcome in one sentence. Example: "Story 10.2 hardens signal watch so anomaly detection is schema-correct, singleton, and resilient to partial failures."

If the user gives only a broad area like "observability," reduce it to specific workstreams before writing tasks.

### 2. Read Only the Minimal Source Set

Do not read the whole repo. Read only the docs and owning files required to identify:

1. what behavior is intended
2. where it is currently implemented
3. where the contract or implementation drift lives
4. what validation is realistic in this repo

For the current observability hardening backlog, that usually means:

- `docs/ROADMAP.md`
- `docs/observability-remediation-plan.md`
- a narrow set of operator, gateway, runtime, SDK, chart, or UI files from the repo surface map

### 3. Map the Story to Owning Subsystems

Translate the requested work into subsystem ownership before writing subtasks.

Use this decision logic:

- If the task changes CRD status, timers, report creation, or cluster-side reconciliation, start with `operator/` and chart or CRD templates.
- If the task changes trace routes, timeline or summary behavior, response models, or persistence shape, start with `api-gateway/`.
- If the task changes direct runtime event emission, split work by `opencode-runtime/`, `pi-runtime/`, and `vibe-runtime/` instead of treating them as one blob.
- If the task changes public client behavior, include `clients/python/`, `clients/typescript/`, and the gateway contract together.
- If the task changes surfaced status or analytics views, include the relevant `web-ui/` component only after confirming the backend shape.
- If the task changes runtime or controller behavior that is configured by Helm or CRDs, include `charts/kubesynapse/` and any affected docs.

### 4. Expand Into File-by-File Subtasks

For each affected subsystem, produce explicit tasks with this minimum information:

1. File path
2. Why this file owns part of the behavior
3. Expected code change
4. Compatibility or migration concerns
5. Validation needed after the change

Good subtask wording:

- "Refactor `operator/controllers/signal_watch.py` to extract a pure `run_signal_watch_cycle()` function and replace `kopf.text` with `sqlalchemy.text`."
- "Add deprecated wrapper methods in `clients/python/kubesynapse/client.py` that delegate to new execution-oriented methods without breaking current callers."

Weak subtask wording:

- "Fix observability"
- "Update API"
- "Improve tests"

### 5. Decide the Output Artifact Path

By default, create a repo doc artifact for the handoff.

Preferred path:

1. `docs/engineering-handoffs/<story-or-workstream>-handoff.md`

Fallback path if the user wants the handoff next to an existing planning doc:

1. `docs/<story-or-workstream>-handoff.md`

Use chat-only output only when the user explicitly says not to create files.

### 6. Add Sequencing and PR Slices

If the work spans more than one subsystem, specify the recommended order and where to split PRs.

Default sequencing rules for this repo:

1. Fix correctness and contract drift before UI polish.
2. Land server and operator changes before SDK or UI consumers when contracts are changing.
3. Land runtime event parity only after the analytics or summary surfaces it feeds are understood.
4. Add or extend tests in the same PR as the behavior change unless the repo lacks a nearby test surface and a temporary follow-up is unavoidable.

When the work is large, propose PR slices such as:

1. operator or signal-watch hardening
2. trace API or SDK contract alignment
3. runtime event parity
4. docs and smoke coverage cleanup

### 7. Define Validation Like an Engineer, Not a Planner

Each handoff must end with focused validation steps. Prefer the cheapest falsifiable checks that match the touched slice:

1. narrow unit tests near the owning package
2. focused typecheck, build, or lint for the touched package
3. smoke paths already documented in the repo
4. only then broader build or end-to-end checks

For this repo, always prefer behavior-scoped validation over generic "run all tests" instructions.

### 8. Record Risks, Assumptions, and Open Questions

Every handoff should state:

1. what is known from code inspection
2. what is inferred but not yet validated
3. what could break compatibility
4. what the receiving engineer must confirm before merging

If a missing test surface or runtime constraint is discovered, call it out directly instead of hiding it inside the checklist.

## Special Handling for the Current Observability Hardening Backlog

When the user asks about Story 10.1 through Story 10.5 or the observability remediation plan, treat these workstreams as first-class starting points and favor more detail than you would for a generic roadmap item:

1. Story 10.1: connector-backed ObservationTarget status
2. Story 10.2: signal watch query and scheduling hardening
3. Story 10.3: trace SDK contract alignment
4. Story 10.4: direct-runtime `llm.call` event parity
5. Story 10.5: observability contract and smoke coverage

For each of these, use the repo surface map to turn the workstream into:

1. owning files
2. code-change intent
3. validation steps
4. rollout or compatibility notes
5. suggested PR slices

If `docs/observability-remediation-plan.md` already contains implementation design, do not paraphrase it loosely. Convert it into assignment-grade tasks.

## Output Contract

Unless the user asks for a different shape, produce the handoff doc and chat summary in this order:

1. Scope and target outcome
2. Output artifact path
2. Source docs consulted
3. Subsystem map
4. File-by-file subtask checklist
5. Validation plan
6. Risks and open questions
7. Suggested implementation order

If you create a repo doc artifact, keep the chat response short and point to the created file.

Use concise, operational language. The receiving engineer should be able to start coding from the handoff without re-discovering the same context.

## Completion Criteria

The handoff is complete only when all of these are true:

1. Each task is anchored to real files in this repo
2. The handoff distinguishes design intent from verified current behavior
3. Validation steps are concrete and scoped
4. Cross-cutting dependencies are called out explicitly
5. The output is organized so another engineer can implement it without broad repo exploration first

## Anti-Patterns

- Do not produce generic PM-style bullet lists with no file ownership.
- Do not treat roadmap docs as enough evidence when behavior is controlled elsewhere in code.
- Do not merge operator, gateway, runtime, SDK, chart, and UI work into one undifferentiated checklist.
- Do not say "add tests" without naming the probable test location or the fact that a new test surface may need to be created.
- Do not hand off a multi-PR change without sequencing it.

## Built-In Resources

Use these bundled references while running this skill:

- [Repo surface map](./references/repo-surface-map.md)
- [Engineer handoff template](./assets/engineer-handoff-template.md)

Use these repo docs as source material when relevant:

- `docs/ROADMAP.md`
- `ROADMAP.md`
- `docs/observability-remediation-plan.md`
- `docs/deployment-readme.md`
- `docs/observability-explained.md`

## Example Prompts

- `/kubesynapse-roadmap-handoff Turn Story 10.2 into a file-by-file engineer handoff with tests and PR slices.`
- `/kubesynapse-roadmap-handoff Break docs/observability-remediation-plan.md into task checklists for another backend engineer.`
- `/kubesynapse-roadmap-handoff Map the trace SDK alignment work to concrete files, compatibility notes, and validation steps.`
- `/kubesynapse-roadmap-handoff Prepare a handoff packet for the current observability consistency hardening release.`