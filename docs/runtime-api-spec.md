# KubeSynth Runtime API Specification v1.0.0

> **Contract Version:** `v1`  
> **Purpose:** Define the minimum API surface every KubeSynth runtime MUST implement to be compatible with the KubeSynapse platform.

## Design Principles

1. **Progressive Enhancement** — All runtimes implement the core set; advanced features are optional but advertised via `/capabilities`.
2. **Idempotent & Safe** — GET endpoints are cacheable with ETag support. POST endpoints are idempotent where possible.
3. **Observable** — Every endpoint returns trace context (`X-Trace-Id`). All errors follow a consistent schema.
4. **Secure** — No credentials in URLs. Token-based auth via `Authorization: Bearer <token>`. Rate-limited by default.
5. **Backward Compatible** — New fields are additive. Breaking changes require a new contract version.

---

## API Tiers

| Tier | Endpoints | Required For |
|------|-----------|-------------|
| **Core** | `/health`, `/ready`, `/info`, `/capabilities`, `/invoke`, `/invoke/stream`, `/cancel` | All production runtimes |
| **Session** | `/todo`, `/question`, `/question/{id}/reply`, `/question/{id}/reject`, `/diff`, `/context-budget` | Agent runtimes with session management |
| **Artifacts** | `/artifacts/list`, `/artifacts/download`, `/artifacts/zip` | Runtimes with workspace/file access |
| **Streaming** | `/invoke/stream`, `/events` | Runtimes supporting real-time UI |

`POST /abort` is a compatibility alias for `POST /cancel`. New integrations should target `/cancel`, but runtime wrappers over existing upstream products may continue to expose `/abort` to avoid breaking existing clients.

---

## OpenAPI 3.0 Specification

```yaml
openapi: "3.0.3"
info:
  title: KubeSynth Runtime API
  description: |
    Standard API contract for KubeSynth agent runtimes.
    Every runtime (opencode, pi, vibe, or custom) MUST implement at least the Core tier.
    Runtimes advertise their supported capabilities via GET /capabilities.
  version: "1.0.0"
  contact:
    name: KubeSynth
    url: https://github.com/anomalyco/opencode
  license:
    name: Apache 2.0

servers:
  - url: http://{runtime-host}:8080
    description: Runtime service endpoint
    variables:
      runtime-host:
        default: localhost
        description: Hostname of the runtime pod

security:
  - BearerAuth: []

tags:
  - name: Health
    description: Liveness and readiness probes
  - name: Discovery
    description: Runtime metadata and capability discovery
  - name: Invocation
    description: Synchronous and asynchronous prompt execution
  - name: Streaming
    description: Server-sent events for real-time interaction
  - name: Session
    description: Session state, todos, questions, and context management
  - name: Artifacts
    description: Workspace file management
  - name: Control
    description: Session cancellation and abort

paths:
  # ── Health & Readiness ──────────────────────────────────────────

  /health:
    get:
      tags: [Health]
      summary: Liveness probe
      description: |
        Returns the current health status of the runtime.
        Used by Kubernetes liveness probes and the operator heartbeat.
        MUST return 200 within 500ms when healthy.
      operationId: getHealth
      responses:
        "200":
          description: Runtime is healthy
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/HealthResponse"
              example:
                status: healthy
                runtime: opencode
                service: code-assistant
                namespace: default
                provider: opencode-go
                agent: build
                sessions:
                  total: 3
                  active: 1
                uptime_seconds: 3600
                timestamp: "2026-05-03T21:45:00Z"
        "503":
          description: Runtime is unhealthy
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/HealthResponse"

  /ready:
    get:
      tags: [Health]
      summary: Readiness probe
      description: |
        Returns whether the runtime is ready to accept requests.
        Used by Kubernetes readiness probes.
        MUST return 200 only when the underlying LLM binary/server is fully initialized.
      operationId: getReady
      responses:
        "200":
          description: Runtime is ready
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ReadyResponse"
        "503":
          description: Runtime is not ready
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ReadyResponse"

  # ── Discovery ───────────────────────────────────────────────────

  /info:
    get:
      tags: [Discovery]
      summary: Runtime metadata
      description: |
        Returns static metadata about the runtime: contract version, runtime type,
        provider, model, and agent configuration.
        Used by the operator to verify compatibility.
      operationId: getInfo
      responses:
        "200":
          description: Runtime metadata
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/InfoResponse"

  /capabilities:
    get:
      tags: [Discovery]
      summary: Capability discovery
      description: |
        Returns the runtime's supported capabilities.
        Clients use this to determine which optional endpoints and features are available.
        The `tiers` field indicates which API tiers are fully implemented.
      operationId: getCapabilities
      responses:
        "200":
          description: Runtime capabilities
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/CapabilitiesResponse"

  # ── Invocation ──────────────────────────────────────────────────

  /invoke:
    post:
      tags: [Invocation]
      summary: Execute a prompt synchronously
      description: |
        Sends a prompt to the agent and waits for completion.
        Returns the full response text, metadata, and any artifacts.
        Maximum wait time is 300 seconds (configurable via `timeout_seconds`).
      operationId: invoke
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/InvokeRequest"
      responses:
        "200":
          description: Prompt completed successfully
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/InvokeResponse"
        "400":
          description: Invalid request
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
        "408":
          description: Request timeout
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
        "429":
          description: Rate limit exceeded
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
        "500":
          description: Internal error
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"

  # ── Streaming ───────────────────────────────────────────────────

  /invoke/stream:
    post:
      tags: [Streaming]
      summary: Execute a prompt with streaming response
      description: |
        Sends a prompt and streams events via Server-Sent Events (SSE).
        Events are typed and include deltas, tool calls, questions, and completion.
        The stream ends with a `response.completed` or `response.error` event.
      operationId: invokeStream
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/InvokeRequest"
      responses:
        "200":
          description: SSE stream started
          content:
            text/event-stream:
              schema:
                type: string
              examples:
                delta:
                  value: |
                    event: response.delta
                    data: {"text": "Hello", "session_id": "ses_abc123"}
                tool_call:
                  value: |
                    event: response.tool_call
                    data: {"name": "bash", "args": {"command": "ls"}, "id": "tc_1"}
                question:
                  value: |
                    event: question.asked
                    data: {"id": "q_1", "question": "Run this command?", "options": ["yes", "no"]}
                completed:
                  value: |
                    event: response.completed
                    data: {"session_id": "ses_abc123", "tokens": {"total": 150}, "status": "completed"}

  # ── Control ─────────────────────────────────────────────────────

  /cancel:
    post:
      tags: [Control]
      summary: Cancel a running session
      description: |
        Aborts the active session for the given thread.
        The runtime should stop the LLM call and return a cancellation response.
        If no session is active, returns 404.
      operationId: cancelSession
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
          description: Logical thread identifier
      responses:
        "200":
          description: Session cancelled
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [cancelled, cancel_failed]
                  session_id:
                    type: string
                  thread_id:
                    type: string
        "404":
          description: No active session for this thread

  /abort:
    post:
      tags: [Control]
      summary: Abort a running session
      description: |
        Compatibility alias for `/cancel`.
        New integrations should use `/cancel`, but runtimes may expose `/abort`
        when wrapping upstream products that already use abort terminology.
      operationId: abortSession
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
          description: Logical thread identifier
      responses:
        "200":
          description: Session aborted
        "404":
          description: No active session for this thread

  # ── Session ─────────────────────────────────────────────────────

  /todo:
    get:
      tags: [Session]
      summary: Get session todo/task list
      description: |
        Returns the current todo list for a session.
        Supports conditional requests via ETag for efficient polling.
      operationId: getTodo
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Todo list
          headers:
            ETag:
              schema:
                type: string
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/TodoResponse"
        "304":
          description: Not modified (ETag match)
        "404":
          description: No session found

  /question:
    get:
      tags: [Session]
      summary: List pending questions
      description: Returns all pending human-in-the-loop questions for active sessions.
      operationId: getQuestions
      responses:
        "200":
          description: List of pending questions
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: "#/components/schemas/Question"

  "/question/{request_id}/reply":
    post:
      tags: [Session]
      summary: Answer a pending question
      operationId: replyToQuestion
      parameters:
        - name: request_id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                answer:
                  type: string
                  description: The user's answer
      responses:
        "200":
          description: Answer accepted
        "404":
          description: Question not found

  "/question/{request_id}/reject":
    post:
      tags: [Session]
      summary: Reject a pending question
      operationId: rejectQuestion
      parameters:
        - name: request_id
          in: path
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Question rejected
        "404":
          description: Question not found

  /diff:
    get:
      tags: [Session]
      summary: Get file change diff for a session
      description: Returns a unified diff of all file changes made during the session.
      operationId: getDiff
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Diff data
          content:
            application/json:
              schema:
                type: object
                properties:
                  thread_id:
                    type: string
                  session_id:
                    type: string
                  diff:
                    type: string
                    description: Unified diff string

  /context-budget:
    get:
      tags: [Session]
      summary: Get context window usage
      description: |
        Returns token usage, context budget telemetry, and compaction hints.
        Used by the UI to show context utilization and by the runtime to decide
        when to trigger compaction.
      operationId: getContextBudget
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Context budget data
          content:
            application/json:
              schema:
                type: object
                properties:
                  model_context_limit:
                    type: integer
                  tokens_used:
                    type: integer
                  tokens_remaining:
                    type: integer
                  usage_percent:
                    type: number
                  status:
                    type: string
                    enum: [ok, warning, critical, overflow]
                  compaction_available:
                    type: boolean

  # ── Artifacts ───────────────────────────────────────────────────

  /artifacts/list:
    get:
      tags: [Artifacts]
      summary: List workspace files
      operationId: listArtifacts
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
        - name: root
          in: query
          schema:
            type: string
            default: /workspace
      responses:
        "200":
          description: File listing
          content:
            application/json:
              schema:
                type: object
                properties:
                  files:
                    type: array
                    items:
                      type: object
                      properties:
                        path:
                          type: string
                        size:
                          type: integer
                        modified:
                          type: string
                          format: date-time
                  truncated:
                    type: boolean

  /artifacts/download:
    get:
      tags: [Artifacts]
      summary: Download a workspace file
      operationId: downloadArtifact
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
        - name: path
          in: query
          required: true
          schema:
            type: string
      responses:
        "200":
          description: File content
        "404":
          description: File not found

  /artifacts/zip:
    get:
      tags: [Artifacts]
      summary: Download workspace as ZIP
      operationId: downloadZip
      parameters:
        - name: thread_id
          in: query
          required: true
          schema:
            type: string
        - name: root
          in: query
          schema:
            type: string
      responses:
        "200":
          description: ZIP archive
          content:
            application/zip:
              schema:
                type: string
                format: binary

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      description: Shared token for internal runtime communication

  schemas:
    HealthResponse:
      type: object
      required: [status, runtime]
      properties:
        status:
          type: string
          enum: [healthy, unhealthy]
        runtime:
          type: string
          description: Runtime type (opencode, pi, vibe, custom)
        service:
          type: string
        namespace:
          type: string
        provider:
          type: string
        agent:
          type: string
        sessions:
          type: object
          properties:
            total:
              type: integer
            active:
              type: integer
        uptime_seconds:
          type: number
        timestamp:
          type: string
          format: date-time

    ReadyResponse:
      type: object
      required: [status]
      properties:
        status:
          type: string
          enum: [ready, not_ready]
        runtime:
          type: string
        checks:
          type: object
          additionalProperties:
            type: boolean

    InfoResponse:
      type: object
      required: [runtime, contract_version]
      properties:
        runtime:
          type: string
        contract_version:
          type: string
          description: API contract version (e.g., "v1")
        service:
          type: string
        namespace:
          type: string
        provider:
          type: string
        model:
          type: string
        agent:
          type: string
        version:
          type: string
          description: Runtime software version

    CapabilitiesResponse:
      type: object
      required: [runtime, capabilities]
      properties:
        runtime:
          type: string
        service:
          type: string
        capabilities:
          type: object
          properties:
            native_tools:
              type: array
              items:
                type: string
            output_formats:
              type: array
              items:
                type: string
            structured_output:
              type: object
              properties:
                supported:
                  type: boolean
                json_schema:
                  type: boolean
            autonomous_execution:
              type: object
              properties:
                supported:
                  type: boolean
                default_max_turns:
                  type: integer
            session_management:
              type: object
              properties:
                abort:
                  type: boolean
                summarize:
                  type: boolean
                compaction:
                  type: boolean
            mcp_usage:
              type: object
              properties:
                supported:
                  type: boolean
            a2a:
              type: object
              properties:
                outbound_supported:
                  type: boolean
            tiers:
              type: array
              items:
                type: string
                enum: [core, session, artifacts, streaming]
              description: Implemented API tiers

    InvokeRequest:
      type: object
      required: [prompt]
      properties:
        prompt:
          type: string
          description: The user's prompt or instruction
          maxLength: 256000
        thread_id:
          type: string
          description: |
            Logical thread identifier. If omitted, a new thread is created.
            Subsequent calls with the same thread_id continue the conversation.
        model:
          type: string
          description: Model reference (e.g., "opencode-go/qwen3.6-plus")
        system_prompt:
          type: string
          description: Override the default system prompt
        max_turns:
          type: integer
          minimum: 1
          maximum: 256
          description: Maximum agent loop iterations
        output_format:
          type: string
          enum: [text, json, markdown, code]
          description: Expected output format
        output_schema:
          type: object
          description: JSON Schema for structured output (when output_format=json)
        working_directory:
          type: string
          default: /workspace
        timeout_seconds:
          type: number
          minimum: 1
          maximum: 600
          default: 300
        autonomous:
          type: boolean
          default: true
          description: Whether the agent can execute tool calls autonomously
        images:
          type: array
          items:
            type: object
            properties:
              url:
                type: string
              mime_type:
                type: string

    InvokeResponse:
      type: object
      required: [status, response]
      properties:
        thread_id:
          type: string
        response:
          type: string
          description: The agent's response text
        model:
          type: string
        status:
          type: string
          enum: [completed, error, cancelled, incomplete, context_overflow]
        approval_name:
          type: string
          description: Name of pending approval request (if any)
        retry_after_seconds:
          type: number
          description: Seconds to wait before retrying (for rate limits)
        warnings:
          type: array
          items:
            type: string
        artifacts:
          type: array
          items:
            type: object
            properties:
              path:
                type: string
              type:
                type: string
        tool_calls:
          type: array
          items:
            type: object
            properties:
              name:
                type: string
              args:
                type: object
              result:
                type: string
        continuity:
          type: object
          properties:
            created_new_session:
              type: boolean
            session_recovered:
              type: boolean
            has_prior_memory:
              type: boolean
        metadata:
          type: object
          properties:
            tokens:
              type: object
              properties:
                total:
                  type: integer
                input:
                  type: integer
                output:
                  type: integer
                reasoning:
                  type: integer
                cache:
                  type: object
                  properties:
                    read:
                      type: integer
                    write:
                      type: integer
            cost:
              type: number
            time:
              type: object
              properties:
                created:
                  type: integer
                completed:
                  type: integer
            finish_reason:
              type: string
              enum: [stop, length, tool_calls, error, context_overflow]
            context_budget:
              type: object
              properties:
                status:
                  type: string
                model_context_limit:
                  type: integer
            task_status:
              type: string
            agent_used:
              type: string

    Question:
      type: object
      properties:
        id:
          type: string
        session_id:
          type: string
        thread_id:
          type: string
        question:
          type: string
        options:
          type: array
          items:
            type: string
        tool_name:
          type: string
        created_at:
          type: string
          format: date-time

    TodoResponse:
      type: object
      properties:
        thread_id:
          type: string
        session_id:
          type: string
        todos:
          type: array
          items:
            type: object
            properties:
              content:
                type: string
              status:
                type: string
                enum: [pending, in_progress, completed, cancelled]

    ErrorResponse:
      type: object
      required: [error]
      properties:
        error:
          type: object
          required: [code, message]
          properties:
            code:
              type: string
              description: Machine-readable error code
            message:
              type: string
              description: Human-readable error message
            details:
              type: object
              description: Additional error context
            trace_id:
              type: string
              description: Request trace ID for debugging
```

---

## SSE Event Taxonomy

All runtimes that implement `/invoke/stream` MUST emit events using this canonical taxonomy:

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `response.started` | Server → Client | `{session_id, model, thread_id}` | Session started, LLM call initiated |
| `response.delta` | Server → Client | `{text, session_id}` | Incremental text token |
| `response.tool_call` | Server → Client | `{name, args, id, session_id}` | Tool call initiated |
| `response.tool_result` | Server → Client | `{id, result, status, session_id}` | Tool call completed |
| `todo.updated` | Server → Client | `{todos, session_id}` | Todo list changed |
| `question.asked` | Server → Client | `{id, question, options, session_id}` | Human approval required |
| `todo.cleared` | Server → Client | `{session_id}` | Todo list cleared |
| `response.completed` | Server → Client | `{session_id, tokens, status, finish_reason}` | Session completed successfully |
| `response.error` | Server → Client | `{session_id, error, code}` | Session failed |

**Rules:**
1. Every stream MUST end with either `response.completed` or `response.error`.
2. `response.started` MUST be the first event.
3. `response.delta` events MUST be concatenated in order to form the full response text.
4. `question.asked` pauses the stream until answered via `/question/{id}/reply`.
5. The `id` field in tool calls MUST be unique within a session.

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `invalid_request` | 400 | Malformed request or missing required field |
| `session_not_found` | 404 | No session exists for the given thread_id |
| `request_timeout` | 408 | LLM call exceeded timeout_seconds |
| `rate_limited` | 429 | Too many concurrent requests |
| `context_overflow` | 413 | Prompt exceeds model context limit |
| `model_unavailable` | 503 | LLM provider is unreachable |
| `internal_error` | 500 | Unexpected runtime error |
| `cancelled` | 200 | Session was cancelled by user |

---

## Migration Guide for Existing Runtimes

### pi-runtime
| Action | Endpoint |
|--------|----------|
| Add | `GET /info`, `GET /capabilities` |
| Rename | `/abort` → `/cancel` (keep `/abort` as alias for backward compat) |
| Add | `GET /todo`, `GET /question`, `POST /question/{id}/reply`, `POST /question/{id}/reject` |
| Add | `GET /diff`, `GET /context-budget` |
| Normalize | SSE events to canonical taxonomy |
| Remove | `/api/*` alias paths (or keep as deprecated) |
| Remove | `/prompt` legacy endpoint |

### vibe-runtime
| Action | Endpoint |
|--------|----------|
| Enrich | `/health` and `/ready` responses |
| Add | `GET /info`, `GET /capabilities` |
| Implement | `/cancel` and `/abort` (currently no-op stubs) |
| Add | `GET /artifacts/list`, `GET /artifacts/download`, `GET /artifacts/zip` |
| Add | `GET /todo`, `GET /question`, `POST /question/{id}/reply`, `POST /question/{id}/reject` |
| Add | `GET /diff`, `GET /context-budget` |
| Normalize | SSE events to canonical taxonomy |
