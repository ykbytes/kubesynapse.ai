/**
 * Run Intelligence Layer — Runtime event emitter (Node.js)
 *
 * Emits structured runtime events to the API gateway's ingestion endpoint:
 *   POST /api/v1/traces/runtime-events
 *
 * Features:
 * - Bounded queue with batch flushing (max 50 events, 2s interval)
 * - Idempotent event_id generation (UUID v4 + seq)
 * - Per-execution_id sequence tracking
 * - Payload sanitization (secrets redacted)
 * - Graceful shutdown with queue flush
 * - Non-blocking: failures are logged, never raised to caller
 */

const http = require("http");
const crypto = require("crypto");
const { logger } = require("./logger");

const log = logger("pi-runtime-events");

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const API_GATEWAY_URL = (process.env.API_GATEWAY_INTERNAL_URL || "").replace(/\/+$/, "");
const API_GATEWAY_TOKEN = process.env.API_GATEWAY_SHARED_TOKEN || "";
const EMIT_ENABLED = !!(API_GATEWAY_URL && API_GATEWAY_TOKEN);
const RUNTIME_KIND = "pi";
const AGENT_NAME = process.env.AGENT_NAME || "pi-agent";
const NAMESPACE = process.env.AGENT_NAMESPACE || "default";

const QUEUE_MAX_SIZE = parseInt(process.env.RUNTIME_EVENTS_QUEUE_SIZE || "500", 10);
const BATCH_MAX_SIZE = parseInt(process.env.RUNTIME_EVENTS_BATCH_SIZE || "50", 10);
const FLUSH_INTERVAL_MS = parseInt(process.env.RUNTIME_EVENTS_FLUSH_INTERVAL || "2000", 10);
const HTTP_TIMEOUT_MS = parseInt(process.env.RUNTIME_EVENTS_HTTP_TIMEOUT || "10000", 10);

const SECRET_KEYS = new Set([
  "api_key", "secret", "token", "password", "credential",
  "authorization", "bearer", "x-api-key", "x-auth-token",
]);

// ---------------------------------------------------------------------------
// Sequence tracker
// ---------------------------------------------------------------------------

const sequences = new Map();

function nextSeq(executionId) {
  const seq = (sequences.get(executionId) || 0) + 1;
  sequences.set(executionId, seq);
  return seq;
}

// ---------------------------------------------------------------------------
// Payload sanitization
// ---------------------------------------------------------------------------

function sanitizePayload(payload) {
  if (!payload || typeof payload !== "object") return payload;
  const result = {};
  for (const [key, value] of Object.entries(payload)) {
    const keyLower = key.toLowerCase();
    if ([...SECRET_KEYS].some(sk => keyLower.includes(sk))) {
      result[key] = "[REDACTED]";
    } else if (typeof value === "string" && value.length > 4096) {
      result[key] = value.slice(0, 4096) + "...[truncated]";
    } else if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      result[key] = sanitizePayload(value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Event queue
// ---------------------------------------------------------------------------

const queue = [];
let running = false;
let flushTimer = null;
let sentCount = 0;
let droppedCount = 0;

function buildRuntimeEvent(event) {
  const executionId = event.execution_id || "";
  const seq = nextSeq(executionId);
  return {
    id: `rre-${crypto.randomUUID().slice(0, 16)}`,
    event_id: `${executionId}-${seq}`,
    execution_id: executionId,
    session_id: event.session_id || null,
    thread_id: event.thread_id || null,
    namespace: event.namespace || NAMESPACE,
    agent_name: event.agent_name || AGENT_NAME,
    runtime_kind: RUNTIME_KIND,
    event_type: event.event_type || "custom",
    seq,
    severity: event.severity || "info",
    payload: sanitizePayload(event.payload || {}),
    duration_ms: event.duration_ms || null,
    prompt_tokens: event.prompt_tokens || null,
    completion_tokens: event.completion_tokens || null,
    total_tokens: event.total_tokens || null,
    cost_usd: event.cost_usd || null,
  };
}

function enqueue(event) {
  if (!running) return;
  if (queue.length >= QUEUE_MAX_SIZE) {
    droppedCount++;
    console.warn(`[pi-runtime-events] Queue full, dropping event (${event.event_type})`);
    return;
  }
  queue.push(buildRuntimeEvent(event));
}

function sendBatch(batch) {
  if (!batch.length || !API_GATEWAY_URL) return;

  const payload = JSON.stringify({ events: batch });
  const urlObj = new URL(`${API_GATEWAY_URL}/api/v1/traces/runtime-events`);

  const req = http.request(
    {
      hostname: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === "https:" ? 443 : 80),
      path: urlObj.pathname,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${API_GATEWAY_TOKEN}`,
        "Content-Length": Buffer.byteLength(payload),
      },
      timeout: HTTP_TIMEOUT_MS,
    },
    (resp) => {
      if (resp.statusCode === 200 || resp.statusCode === 201) {
        sentCount += batch.length;
      } else {
        console.warn(`[pi-runtime-events] Ingestion failed: status=${resp.statusCode}`);
      }
    },
  );

  req.on("error", (err) => {
    console.warn("[pi-runtime-events] Batch send failed:", err.message);
  });

  req.on("timeout", () => {
    req.destroy();
    console.warn("[pi-runtime-events] Batch send timed out");
  });

  req.write(payload);
  req.end();
}

function flushLoop() {
  if (queue.length >= BATCH_MAX_SIZE || (!running && queue.length > 0)) {
    const batch = queue.splice(0, BATCH_MAX_SIZE);
    sendBatch(batch);
  }

  if (running || queue.length > 0) {
    flushTimer = setTimeout(flushLoop, FLUSH_INTERVAL_MS);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function startEmitter() {
  if (running || !EMIT_ENABLED) return;
  running = true;
  flushLoop();
  log.info(`Emitter started → ${API_GATEWAY_URL}`);
}

function stopEmitter() {
  if (!running) return;
  running = false;
  if (flushTimer) clearTimeout(flushTimer);
  // Final flush
  if (queue.length > 0) {
    sendBatch(queue.splice(0));
  }
  log.info(`Emitter stopped (sent=${sentCount}, dropped=${droppedCount})`);
}

function emitRunStarted(executionId, opts = {}) {
  enqueue({
    event_type: "run.started",
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: "info",
    payload: { model: opts.model },
  });
}

function emitRunCompleted(executionId, opts = {}) {
  enqueue({
    event_type: "run.completed",
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: "info",
    payload: { status: opts.status || "completed", finish_reason: opts.finish_reason },
    total_tokens: opts.total_tokens,
    cost_usd: opts.cost_usd,
    duration_ms: opts.duration_ms,
  });
}

function emitRunError(executionId, opts = {}) {
  enqueue({
    event_type: "run.error",
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: "error",
    payload: { error: (opts.error || "").slice(0, 2048), error_code: opts.error_code },
  });
}

function emitToolCall(executionId, opts = {}) {
  enqueue({
    event_type: `tool.${opts.status || "started"}`,
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: opts.status === "failed" ? "error" : "info",
    payload: { tool_name: opts.tool_name, tool_args: opts.tool_args, status: opts.status || "started" },
    duration_ms: opts.duration_ms,
  });
}

function emitLlmCall(executionId, opts = {}) {
  enqueue({
    event_type: "llm.call",
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: "info",
    payload: { model: opts.model },
    prompt_tokens: opts.prompt_tokens,
    completion_tokens: opts.completion_tokens,
    total_tokens: opts.total_tokens,
    cost_usd: opts.cost_usd,
    duration_ms: opts.duration_ms,
  });
}

function emitQuestionAsked(executionId, opts = {}) {
  enqueue({
    event_type: "human.question",
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: "info",
    payload: { question: (opts.question || "").slice(0, 1024), options: opts.options },
  });
}

function emitTodoUpdated(executionId, opts = {}) {
  enqueue({
    event_type: "todo.updated",
    execution_id: executionId,
    session_id: opts.session_id,
    thread_id: opts.thread_id,
    severity: "info",
    payload: { todo_count: Array.isArray(opts.todos) ? opts.todos.length : 0 },
  });
}

module.exports = {
  startEmitter,
  stopEmitter,
  emitRunStarted,
  emitRunCompleted,
  emitRunError,
  emitToolCall,
  emitLlmCall,
  emitQuestionAsked,
  emitTodoUpdated,
};
