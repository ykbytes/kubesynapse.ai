# Repository Factory Contract

## Purpose

- This repository contains a governed KubeSynapse factory that creates agents, workflows, policies, context bundles, and deployment-ready automation.
- Treat factory work as systems design, not prompt copywriting.
- A valid manifest is necessary but not sufficient. The factory must produce bundles that save expert time and survive real operational use.

## Factory Mission

- Convert open-ended requests into high-value, production-grade KubeSynapse bundles.
- Prefer bundles that can complete meaningful work end to end with bounded autonomy, explicit approvals for risky actions, and concrete verification evidence.
- Optimize for developer and enterprise leverage: less manual glue work, fewer hidden assumptions, clearer operations.

## Mandatory Working Model

1. Discover the actual objective.
   - Identify the business outcome, deliverables, target users, source systems, constraints, and what "done" means.
   - Capture assumptions explicitly when the request is underspecified.
2. Decompose before generating.
   - Decide whether the work should be a single agent, a multi-agent bundle, or a governed bundle plus workflow.
   - Split responsibilities when trust boundaries, tools, review duties, or deliverable types differ.
3. Design the full operating system.
   - Plan runtime, tools, guardrails, storage, context, review points, verification, and approvals.
   - Prefer least-privilege tool selection and explain why each capability exists.
4. Package a usable bundle.
   - Generate not only manifests, but also supporting deliverables such as runbooks, example requests, evaluation plans, and verification guidance.
5. Verify before claiming value.
   - Check schema fit, cross-resource references, workflow semantics, tool/runtime realism, and artifact completeness.

## Prompt Depth Requirements

- Never generate toy prompts for non-trivial work.
- For any serious agent, the generated system prompt should define:
  - mission and business objective
  - responsibilities and non-responsibilities
  - expected inputs and outputs
  - tool usage rules and decision heuristics
  - workflow or reasoning procedure
  - failure handling and escalation behavior
  - output formatting contract
  - quality bar and completion criteria
- A two-sentence prompt is acceptable only for trivial helpers with no autonomy, no tools, and no workflow responsibility.

## Workflow Design Rules

- Separate planning, review, execution, and verification when they have different risk or quality concerns.
- Use distinct review perspectives when the request is non-trivial:
  - spec review: schema correctness, reference integrity, safety, approval boundaries
  - quality review: prompt depth, tool fit, deliverable completeness, enterprise usefulness
- Use `verify` with concrete pass/fail criteria on important execution steps.
- Use `requireApproval: true` on any deploy, edit-live-resource, destructive, or workflow-trigger action.
- Use `sessionGroup` only when continuity materially improves the result.
- Generated business workflows must represent user-facing automation, never self-deploying manifest wrappers.

## Artifact Contract

- High-value factory output should include:
  - KubeSynapse manifests
  - architecture rationale
  - supporting deliverables and operating notes
  - verification and rollback guidance
  - example invocations or usage scenarios
  - evaluation criteria and follow-up checks
- Do not stop at "here is some YAML" unless the user explicitly asked for YAML only.

## Enterprise Requirements

- Account for environment, compliance, ownership, and scale.
- Capture where relevant:
  - deployment target and namespace boundaries
  - data sensitivity, audit, and approval expectations
  - reliability, latency, cost, and token budget constraints
  - handoff and operational ownership
  - integration surfaces and external systems

## Tooling Rules

- Use OpenCode when the task needs file authoring, artifact generation, deployment logic, or structured review output.
- Prefer specialist agents and A2A handoffs when tasks span distinct skills.
- Choose MCP sidecars intentionally. Every sidecar must have a clear job.
- Avoid generic "tool-rich" bundles when a narrower tool profile is sufficient.

## Anti-Patterns

- Generic one-paragraph system prompts for complex agents
- One monolithic agent for work that clearly needs planning, review, and execution roles
- Bundles with no README/runbook/evaluation guidance
- Workflows with no review or verification discipline
- Tool assumptions that do not match the real runtime
- Approval-gated systems that still imply autonomous live mutation without explicit approval

## Quality Bar

- Generated bundles must be explainable, auditable, and operationally useful.
- The user should gain leverage they would not get from manually writing a few basic prompts in a generic coding assistant.

---

## Agent Team

All agents use the **qwen3.6-plus** model for consistency and quality.

| Agent | Role | Specialties |
|-------|------|-------------|
| `kubesynth-scrum-master` | Autonomous orchestrator | Sprint management, delegation, verification |
| `kubesynth-bug-hunter` | Bug Hunter & QA | pytest, debugging, performance profiling, chaos engineering |
| `kubesynth-security-guardian` | Security Auditor | OWASP, CIS benchmarks, mTLS, JWT, RBAC, secret scanning |
| `kubesynth-prod-engineer` | Production Engineer & SRE | Kubernetes SRE, observability, performance tuning |
| `kubesynth-ui-artist` | UI/UX Designer | React 18, Tailwind CSS v4, Radix UI, Framer Motion, WCAG 2.1 AA |
| `kubesynth-backend-refactorer` | Backend Architect | FastAPI, SQLAlchemy, OpenAPI, Python type annotations |
| `kubesynth-docs-storyteller` | Documentation Specialist | Technical writing, Mermaid diagrams, API documentation |
| `kubesynth-landing-magician` | Landing Page Specialist | Modern SaaS design, scroll animations, conversion optimization |

---

## Runtime API Contract

All runtimes MUST implement the API contract defined in:
- **OpenAPI Spec:** `docs/runtime-api-spec.yaml`
- **Documentation:** `docs/runtime-api-spec.md`

### API Tiers

| Tier | Endpoints | Required For |
|------|-----------|-------------|
| **Core** | `/health`, `/ready`, `/info`, `/capabilities`, `/invoke`, `/invoke/stream`, `/cancel` | All production runtimes |
| **Session** | `/todo`, `/question`, `/question/{id}/reply`, `/question/{id}/reject`, `/diff`, `/context-budget` | Agent runtimes with session management |
| **Artifacts** | `/artifacts/list`, `/artifacts/download`, `/artifacts/zip` | Runtimes with workspace/file access |
| **Streaming** | `/invoke/stream`, `/events` | Runtimes supporting real-time UI |

### SSE Event Taxonomy

All streaming runtimes MUST emit events using this canonical taxonomy:

| Event | Payload | Description |
|-------|---------|-------------|
| `response.started` | `{session_id, model, thread_id}` | Session started |
| `response.delta` | `{text, session_id}` | Incremental text token |
| `response.tool_call` | `{name, args, id, session_id}` | Tool call initiated |
| `response.tool_result` | `{id, result, status, session_id}` | Tool call completed |
| `todo.updated` | `{todos, session_id}` | Todo list changed |
| `question.asked` | `{id, question, options, session_id}` | Human approval required |
| `todo.cleared` | `{session_id}` | Todo list cleared |
| `response.completed` | `{session_id, tokens, status, finish_reason}` | Session completed |
| `response.error` | `{session_id, error, code}` | Session failed |

---

## Roadmap

See `docs/ROADMAP.md` for the complete sprint backlog and timeline.

### Current Priorities

1. **API Contract Enforcement** — All runtimes must pass conformance tests
2. **Reliability & Observability** — Distributed tracing, rate limiting, circuit breakers
3. **Security & Compliance** — mTLS, RBAC, audit logging, secret management
4. **Developer Experience** — SDK, runtime template, documentation portal
5. **Production Hardening** — Performance benchmarking, chaos engineering, multi-cluster
