#!/usr/bin/env node
/**
 * HTTP-to-pi-RPC Bridge (Node.js)  —  Subprocess Manager Edition
 *
 * The bridge is now PID 1. It spawns and manages the `pi` process as a child,
 * communicating via FIFOs. When an invoke request specifies a different
 * model/provider/thinkingLevel than what the current pi subprocess is using,
 * the bridge gracefully kills the old pi and spawns a new one with updated
 * arguments — no pod redeploy required.
 *
 * Endpoints:
 *   GET  /health         — Returns 200 if pi process is alive
 *   GET  /ready          — Returns 200 if pi responds to get_state
 *   GET  /state          — Returns pi session state
 *   POST /prompt         — Sends a prompt and streams SSE events back
 *   POST /invoke         — Synchronous invoke (blocks until response, returns JSON)
 *   POST /invoke/stream  — SSE streaming invoke (compatible with API gateway)
 *   POST /abort          — Aborts the current operation
 */

const http = require("http");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execSync } = require("child_process");

// Run Intelligence Layer — runtime event emitter
const runtimeEvents = require("./runtime_events");
const { SessionStore } = require("./session_state");

const HOST = process.env.PI_BRIDGE_HOST || "0.0.0.0";
const PORT = parseInt(process.env.PI_BRIDGE_PORT || "8080", 10);
const PI_STDIN_FIFO = "/tmp/pi-stdin";
const PI_STDOUT_FIFO = "/tmp/pi-stdout";
const WORKDIR = path.resolve(process.env.OPENCODE_WORKDIR || "/workspace");
const HOME_DIR = path.resolve(process.env.HOME || "/home/piuser");
const SERVICE_NAME = (process.env.AGENT_NAME || "pi-agent").trim() || "pi-agent";
const SERVICE_NAMESPACE = (process.env.AGENT_NAMESPACE || "default").trim() || "default";
const RUNTIME_TIERS = ["core", "session", "artifacts", "streaming"];
const SESSION_DIR = process.env.PI_CODING_AGENT_DIR
  ? path.join(process.env.PI_CODING_AGENT_DIR, "sessions")
  : "/home/piuser/.pi/agent/sessions";
const ARTIFACT_COLLECTION_MAX_FILES = Math.max(parseInt(process.env.PI_ARTIFACT_MAX_FILES || "200", 10) || 200, 1);
const ARTIFACT_DOWNLOAD_MAX_SIZE = Math.max(parseInt(process.env.PI_ARTIFACT_DOWNLOAD_MAX_SIZE || String(50 * 1024 * 1024), 10) || (50 * 1024 * 1024), 1);
const SKIP_DIRS = new Set([".git", "node_modules", "__pycache__", ".next", ".venv", "venv", "dist", ".cache"]);
const MIME_TYPES = {
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".yaml": "application/yaml; charset=utf-8",
  ".yml": "application/yaml; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".pdf": "application/pdf",
  ".doc": "application/msword",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

let commandCounter = 0;
const pendingResponses = new Map();
const eventStreams = new Set();
const ACTIVE_INVOCATIONS = new Map(); // invocationId -> { res, chunks, tools, done, timer }
const MODEL_TIMEOUT_MS = Math.max(parseInt(process.env.PI_MODEL_TIMEOUT_MS || "120000", 10) || 120000, 10000);
const sessionStore = new SessionStore({ workspaceDir: WORKDIR, modelContextLimit: 128000 });

// ── Pi Subprocess State ─────────────────────────────────────────────

let piProcess = null;         // child_process.ChildProcess | null
let stdinKeepAliveFd = null;  // fd keeping stdin FIFO open (O_RDWR, never blocks)
let stdoutReader = null;      // fs.ReadStream | null
let piReady = false;
let piStarting = false;

// Current running configuration
let currentConfig = {
  model: process.env.PI_MODEL || "",
  provider: process.env.PI_PROVIDER || "",
  thinkingLevel: process.env.PI_THINKING_LEVEL || "medium",
};

function buildPiMetadata(config, overrides = {}) {
  return {
    runtime: "pi",
    config: { ...(config || currentConfig) },
    tokens: {
      total: 0,
      input: 0,
      output: 0,
      reasoning: 0,
      cache: { read: 0, write: 0 },
    },
    finish_reason: "stop",
    ...overrides,
  };
}

function formatToolCalls(toolCalls) {
  return (toolCalls || []).map((toolCall) => ({
    name: toolCall.name || toolCall.tool || "tool",
    args: toolCall.args !== undefined ? toolCall.args : toolCall.input,
    result: toolCall.result !== undefined ? toolCall.result : "",
    status: toolCall.status || "completed",
  }));
}

const ERROR_CODES = {
  400: "invalid_request",
  401: "unauthorized",
  403: "forbidden",
  404: "not_found",
  408: "timeout",
  409: "conflict",
  413: "payload_too_large",
  422: "invalid_request",
  429: "rate_limited",
  500: "internal_error",
  502: "upstream_error",
  503: "service_unavailable",
  504: "timeout",
};

function errorCodeForStatus(status) {
  if (ERROR_CODES[status]) {
    return ERROR_CODES[status];
  }
  return status >= 500 ? "upstream_error" : "runtime_error";
}

function normalizeErrorDetails(details) {
  if (details === undefined || details === null || details === "") {
    return null;
  }
  if (Array.isArray(details) && details.length === 0) {
    return null;
  }
  if (typeof details === "object" && !Array.isArray(details) && Object.keys(details).length === 0) {
    return null;
  }
  return details;
}

function buildErrorPayload(status, message, options = {}) {
  const traceId = options.traceId || options.trace_id || null;
  const error = {
    code: options.code || errorCodeForStatus(status),
    message: message || "Unexpected error",
  };
  const details = normalizeErrorDetails(options.details);
  if (details !== null) {
    error.details = details;
  }
  if (traceId) {
    error.trace_id = traceId;
  }
  return { error };
}

// ── Helpers ─────────────────────────────────────────────────────────

function extractTextFromPiMessage(message) {
  if (!message) return "";
  if (typeof message.content === "string") return message.content;
  if (Array.isArray(message.content)) {
    const parts = [];
    for (const part of message.content) {
      if (part && part.type === "text" && part.text) {
        parts.push(part.text);
      }
    }
    return parts.join("");
  }
  if (typeof message.text === "string") return message.text;
  return "";
}

function pathIsWithin(targetPath, rootPath) {
  const relative = path.relative(rootPath, targetPath);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function artifactRoots() {
  const roots = [WORKDIR, HOME_DIR, os.tmpdir()]
    .map((value) => path.resolve(value))
    .filter((value, index, array) => array.indexOf(value) === index && fs.existsSync(value));
  return roots;
}

function resolveArtifactRoot(root = "") {
  const allowedRoots = artifactRoots();
  if (!root) {
    return { walkRoots: allowedRoots, roots: allowedRoots.map((item) => item.replace(/\\/g, "/")) };
  }

  const target = path.resolve(root);
  if (!allowedRoots.some((allowedRoot) => pathIsWithin(target, allowedRoot))) {
    const error = new Error(`root '${root}' is outside the allowed runtime roots`);
    error.statusCode = 400;
    throw error;
  }
  if (!fs.existsSync(target) || !fs.statSync(target).isDirectory()) {
    const error = new Error(`root '${root}' is not a directory`);
    error.statusCode = 404;
    throw error;
  }
  return { walkRoots: [target], roots: [target.replace(/\\/g, "/")] };
}

function resolveArtifactFile(filePath) {
  const candidate = path.resolve(filePath);
  const allowedRoots = artifactRoots();
  if (!allowedRoots.some((allowedRoot) => pathIsWithin(candidate, allowedRoot))) {
    const error = new Error(`path '${filePath}' is outside the allowed runtime roots`);
    error.statusCode = 400;
    throw error;
  }
  if (!fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) {
    const error = new Error(`path '${filePath}' is not a file`);
    error.statusCode = 404;
    throw error;
  }
  return candidate;
}

function shouldSkipDir(baseRoot, dirPath) {
  const relative = path.relative(baseRoot, dirPath);
  if (!relative) return false;
  return relative.split(path.sep).some((part) => part.startsWith(".") || SKIP_DIRS.has(part));
}

function iterArtifactFiles(baseRoot, onFile) {
  const stack = [baseRoot];
  while (stack.length > 0) {
    const current = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }

    for (const entry of entries) {
      if (entry.name.startsWith(".")) {
        continue;
      }
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (!SKIP_DIRS.has(entry.name) && !shouldSkipDir(baseRoot, fullPath)) {
          stack.push(fullPath);
        }
        continue;
      }
      if (!entry.isFile()) {
        continue;
      }
      const result = onFile(fullPath);
      if (result === false) {
        return false;
      }
    }
  }
  return true;
}

function listArtifacts(root = "") {
  const { walkRoots, roots } = resolveArtifactRoot(root);
  const files = [];
  const seen = new Set();
  let truncated = false;

  for (const walkRoot of walkRoots) {
    const completed = iterArtifactFiles(walkRoot, (fullPath) => {
      const normalizedPath = fullPath.replace(/\\/g, "/");
      if (seen.has(normalizedPath)) {
        return true;
      }
      seen.add(normalizedPath);

      let stat;
      try {
        stat = fs.statSync(fullPath);
      } catch {
        return true;
      }

      files.push({
        path: normalizedPath,
        name: path.basename(fullPath),
        size: stat.size,
        modified: Math.floor(stat.mtimeMs / 1000),
        directory: path.dirname(normalizedPath),
      });

      if (files.length >= ARTIFACT_COLLECTION_MAX_FILES) {
        truncated = true;
        return false;
      }
      return true;
    });

    if (!completed || truncated) {
      break;
    }
  }

  return { files, truncated, roots };
}

function contentTypeForFile(filePath) {
  return MIME_TYPES[path.extname(filePath).toLowerCase()] || "application/octet-stream";
}

function piCapabilities() {
  return {
    native_tools: ["bash", "read", "write", "edit", "glob", "grep", "webfetch", "websearch", "codesearch", "skill", "task", "todowrite"],
    output_formats: ["text", "json", "markdown", "code"],
    structured_output: { supported: true, json_schema: true },
    autonomous_execution: { supported: true, default_max_turns: 10 },
    session_management: { abort: true, summarize: false, compaction: false },
    mcp_usage: { supported: false },
    a2a: { outbound_supported: true },
    tiers: RUNTIME_TIERS,
  };
}

function sendError(res, err, fallbackStatus = 500) {
  const status = Number.isInteger(err?.statusCode) ? err.statusCode : fallbackStatus;
  return jsonError(res, status, err?.message || "Unexpected error", {
    code: err?.code,
    details: err?.details,
    traceId: err?.traceId || err?.trace_id,
  });
}

function streamArtifactsZip(res, root = "") {
  let walkRoot;
  try {
    if (root) {
      const resolved = resolveArtifactRoot(root);
      walkRoot = resolved.walkRoots[0];
    } else {
      walkRoot = WORKDIR;
      if (!fs.existsSync(walkRoot) || !fs.statSync(walkRoot).isDirectory()) {
        const error = new Error("workspace directory does not exist");
        error.statusCode = 404;
        throw error;
      }
    }
  } catch (err) {
    return sendError(res, err);
  }

  const zipName = `${path.basename(walkRoot) || "workspace"}.zip`;
  const args = ["-q", "-r", "-", ".", "-x", "*/.git/*", "*/node_modules/*", "*/__pycache__/*", "*/.next/*", "*/.venv/*", "*/venv/*", "*/dist/*", "*/.cache/*"];
  const zipProcess = spawn("zip", args, { cwd: walkRoot, stdio: ["ignore", "pipe", "pipe"] });
  let stderr = "";

  res.writeHead(200, {
    "Content-Type": "application/zip",
    "Content-Disposition": `attachment; filename="${zipName}"`,
  });

  zipProcess.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
  });

  zipProcess.on("error", (err) => {
    if (!res.headersSent) {
      sendError(res, err);
    } else {
      res.destroy(err);
    }
  });

  zipProcess.stdout.pipe(res);
  zipProcess.on("close", (code) => {
    if (code !== 0 && !res.destroyed) {
      res.destroy(new Error(stderr.trim() || `zip exited with code ${code}`));
    }
  });
}

// ── Pi Subprocess Management ────────────────────────────────────────

function buildPiArgs(config) {
  const args = ["--mode", "rpc"];

  // Session handling
  if (process.env.PI_NO_SESSION === "true") {
    args.push("--no-session");
  } else {
    args.push("--session-dir", SESSION_DIR);
  }

  // Provider & model
  if (config.provider) {
    args.push("--provider", config.provider);
  }
  if (config.model) {
    args.push("--model", config.model);
  }

  // Thinking level
  if (config.thinkingLevel) {
    args.push("--thinking", config.thinkingLevel);
  }

  // Tools configuration
  if (process.env.PI_NO_TOOLS === "true") {
    args.push("--no-tools");
  } else if (process.env.PI_TOOLS) {
    args.push("--tools", process.env.PI_TOOLS);
  }

  // Extensions
  if (process.env.PI_EXTENSIONS) {
    for (const ext of process.env.PI_EXTENSIONS.split(/\s+/).filter(Boolean)) {
      args.push("-e", ext);
    }
  }

  // System prompt
  if (process.env.PI_SYSTEM_PROMPT) {
    args.push("--system-prompt", process.env.PI_SYSTEM_PROMPT);
  }

  return args;
}

function configChanged(requested) {
  const model = (requested.model || "").trim();
  const provider = (requested.provider || "").trim();
  const thinkingLevel = (requested.thinkingLevel || requested.thinking_level || "").trim();

  // Only consider changed if the request explicitly provides a non-empty value
  // that differs from the current config
  if (model && model !== currentConfig.model) return true;
  if (provider && provider !== currentConfig.provider) return true;
  if (thinkingLevel && thinkingLevel !== currentConfig.thinkingLevel) return true;
  return false;
}

function stopPi() {
  return new Promise((resolve) => {
    piReady = false;

    // Clean up stdout reader
    if (stdoutReader) {
      try { stdoutReader.destroy(); } catch {}
      stdoutReader = null;
    }

    // Close stdin keep-alive fd
    if (stdinKeepAliveFd !== null) {
      try { fs.closeSync(stdinKeepAliveFd); } catch {}
      stdinKeepAliveFd = null;
    }

    // Kill pi process
    if (piProcess) {
      const proc = piProcess;
      piProcess = null;

      proc.once("exit", () => {
        // Clean up FIFOs
        try { fs.unlinkSync(PI_STDIN_FIFO); } catch {}
        try { fs.unlinkSync(PI_STDOUT_FIFO); } catch {}
        resolve();
      });

      try { proc.kill("SIGTERM"); } catch {}

      // Force kill after 5 seconds
      setTimeout(() => {
        try { proc.kill("SIGKILL"); } catch {}
      }, 5000);

      // Safety: resolve anyway after 8 seconds
      setTimeout(resolve, 8000);
    } else {
      // No process, just clean up FIFOs
      try { fs.unlinkSync(PI_STDIN_FIFO); } catch {}
      try { fs.unlinkSync(PI_STDOUT_FIFO); } catch {}
      resolve();
    }

    // Reject all pending responses
    for (const [id, handler] of pendingResponses) {
      clearTimeout(handler.timeout);
      handler.reject(new Error("Pi process restarting"));
    }
    pendingResponses.clear();
  });
}

function startPi(config) {
  return new Promise((resolve, reject) => {
    if (piStarting) {
      reject(new Error("Pi subprocess is already starting"));
      return;
    }
    piStarting = true;
    piReady = false;

    // Update current config
    currentConfig = {
      model: (config.model || "").trim(),
      provider: (config.provider || "").trim(),
      thinkingLevel: (config.thinkingLevel || "medium").trim(),
    };

    const args = buildPiArgs(currentConfig);
    console.log(`[pi-bridge] Starting pi subprocess: pi ${args.join(" ")}`);

    // Create FIFOs
    try { fs.unlinkSync(PI_STDIN_FIFO); } catch {}
    try { fs.unlinkSync(PI_STDOUT_FIFO); } catch {}
    try {
      execSync(`mkfifo ${PI_STDIN_FIFO}`);
      execSync(`mkfifo ${PI_STDOUT_FIFO}`);
    } catch (err) {
      piStarting = false;
      reject(new Error(`Failed to create FIFOs: ${err.message}`));
      return;
    }

    // Keep stdin FIFO open with O_RDWR (never blocks on FIFO, unlike O_WRONLY)
    stdinKeepAliveFd = fs.openSync(PI_STDIN_FIFO, fs.constants.O_RDWR);

    // Open stdout FIFO for reading with O_RDWR (never blocks)
    // We'll use this fd for the read stream and also as the write target for pi
    const stdoutRwFd = fs.openSync(PI_STDOUT_FIFO, fs.constants.O_RDWR);

    // Start stdout reader using the already-opened fd
    startStdoutReaderFromFd(stdoutRwFd);

    // Small delay for reader to attach before starting pi
    setTimeout(() => {
      // Spawn pi — stdin reads from our FIFO, stdout writes to our FIFO
      // Open non-blocking fds for pi's stdio
      const stdinFd = fs.openSync(PI_STDIN_FIFO, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
      const stdoutFd = fs.openSync(PI_STDOUT_FIFO, fs.constants.O_WRONLY | fs.constants.O_NONBLOCK);

      piProcess = spawn("pi", args, {
        stdio: [stdinFd, stdoutFd, "pipe"],
        cwd: WORKDIR,
        env: process.env,
      });

      // Close our copies of the file descriptors (pi now owns them)
      fs.closeSync(stdinFd);
      fs.closeSync(stdoutFd);

      piProcess.stderr.on("data", (chunk) => {
        const text = chunk.toString().trim();
        if (text) console.log(`[pi-stderr] ${text}`);
      });

      piProcess.on("error", (err) => {
        console.error(`[pi-bridge] Pi subprocess error: ${err.message}`);
        piProcess = null;
        piReady = false;
        piStarting = false;
      });

      piProcess.on("exit", (code, signal) => {
        console.log(`[pi-bridge] Pi subprocess exited: code=${code}, signal=${signal}`);
        piProcess = null;
        piReady = false;
      });

      // Consider pi started after a brief delay (it needs to initialize)
      setTimeout(() => {
        piReady = piProcess !== null;
        piStarting = false;
        if (piReady) {
          console.log(`[pi-bridge] Pi subprocess ready (PID: ${piProcess.pid}, model: ${currentConfig.model || "default"}, provider: ${currentConfig.provider || "auto"})`);
          resolve();
        } else {
          reject(new Error("Pi process exited before becoming ready"));
        }
      }, 1500);
    }, 500);
  });
}

async function ensurePiWithConfig(requestedConfig) {
  // If config changed, restart pi
  if (piProcess && configChanged(requestedConfig)) {
    const newModel = requestedConfig.model || currentConfig.model;
    const newProvider = requestedConfig.provider || currentConfig.provider;
    const newThinking = requestedConfig.thinkingLevel || requestedConfig.thinking_level || currentConfig.thinkingLevel;
    console.log(`[pi-bridge] Model config change detected: ${currentConfig.provider}/${currentConfig.model} -> ${newProvider}/${newModel}`);

    // Fail any active invocations
    for (const [invId, inv] of ACTIVE_INVOCATIONS) {
      clearTimeout(inv.timer);
      inv.error = "Pi restarting for model change";
      inv.done = true;
      if (inv.stream && !inv.stream.destroyed) {
        inv.stream.write(`event: response.error\ndata: ${JSON.stringify({ session_id: invId, error: inv.error, code: 503 })}\n\n`);
        inv.stream.end();
      }
      ACTIVE_INVOCATIONS.delete(invId);
    }

    await stopPi();
    await startPi({
      model: newModel,
      provider: newProvider,
      thinkingLevel: newThinking,
    });
    return;
  }

  // If pi is not running, start it with requested config (or defaults)
  if (!piProcess && !piStarting) {
    await startPi({
      model: requestedConfig.model || currentConfig.model,
      provider: requestedConfig.provider || currentConfig.provider,
      thinkingLevel: requestedConfig.thinkingLevel || requestedConfig.thinking_level || currentConfig.thinkingLevel,
    });
    return;
  }

  // If pi is starting, wait for it
  if (piStarting) {
    const start = Date.now();
    while (piStarting && Date.now() - start < 10000) {
      await new Promise((r) => setTimeout(r, 200));
    }
    if (!piProcess) {
      throw new Error("Pi process failed to start");
    }
  }
}

// ── Pi Communication ────────────────────────────────────────────────

function sendToPi(command) {
  const id = `bridge-${++commandCounter}`;
  const payload = JSON.stringify({ ...command, id }) + "\n";

  return new Promise((resolve, reject) => {
    if (!piProcess) {
      reject(new Error("Pi process is not running"));
      return;
    }
    try {
      // Write via the keep-alive fd (O_RDWR, never blocks) instead of
      // opening the FIFO each time which could block the event loop.
      if (stdinKeepAliveFd === null) {
        reject(new Error("stdin FIFO not open"));
        return;
      }
      fs.writeSync(stdinKeepAliveFd, payload);

      const timeout = setTimeout(() => {
        pendingResponses.delete(id);
        reject(new Error(`Timeout waiting for response to ${command.type}`));
      }, command.type === "prompt" ? 300000 : 30000);

      pendingResponses.set(id, { resolve, reject, timeout });
    } catch (err) {
      reject(err);
    }
  });
}

function handlePiOutput(line) {
  try {
    const data = JSON.parse(line.trim());
    const id = data.id;

    // Handle extension UI requests
    if (data.type === "extension_ui_request") {
      handleExtensionUIRequest(data);
      return;
    }

    // Route to pending command response
    if (id && pendingResponses.has(id)) {
      const handler = pendingResponses.get(id);
      clearTimeout(handler.timeout);
      if (data.type === "response") {
        pendingResponses.delete(id);
        if (data.success === false) {
          const errorMessage = typeof data.error === "string" && data.error.trim()
            ? data.error.trim()
            : `Pi ${data.command || "command"} failed`;
          for (const inv of ACTIVE_INVOCATIONS.values()) {
            clearTimeout(inv.timer);
            inv.error = errorMessage;
            inv.done = true;
            sessionStore.complete(inv.threadId, {
              status: "error",
              toolCalls: inv.tools,
              metadata: buildPiMetadata(inv.config, { finish_reason: "error" }),
              responseText: "",
            });
            if (inv.stream) {
              inv.stream.write(`event: response.error\ndata: ${JSON.stringify({ session_id: inv.sessionId || null, error: errorMessage, code: 502 })}\n\n`);
            }
          }
          handler.reject(new Error(errorMessage));
        } else {
          handler.resolve(data);
        }
        return;
      }
      // Keep waiting — re-register
      pendingResponses.set(id, handler);
    }

    // Route to active synchronous invocations
    if (data.type === "message_update" && data.assistantMessageEvent) {
      const evt = data.assistantMessageEvent;
      if (evt.type === "text_delta" && evt.delta) {
        for (const inv of ACTIVE_INVOCATIONS.values()) {
          inv.chunks.push(evt.delta);
          if (inv.stream) {
            inv.stream.write(`event: response.delta\ndata: ${JSON.stringify({ text: evt.delta, session_id: inv.sessionId || null })}\n\n`);
          }
        }
      }
      const text = extractTextFromPiMessage(data.message);
      if (text && data.message && data.message.role === "assistant") {
        for (const inv of ACTIVE_INVOCATIONS.values()) {
          if (inv.chunks.length === 0 || inv.chunks.join("") !== text) {
            inv.chunks.push(text);
          }
        }
      }
    }

    // Extract final text from message_end (assistant only)
    if (data.type === "message_end" && data.message && data.message.role === "assistant") {
      const text = extractTextFromPiMessage(data.message);
      if (text) {
        for (const inv of ACTIVE_INVOCATIONS.values()) {
          inv.chunks = [text];
        }
      }
    }

    if (data.type === "tool_execution_start") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        inv.tools.push({ name: data.toolName, args: data.args, result: "", status: "running" });
        if (inv.stream) {
          inv.stream.write(`event: response.tool_call\ndata: ${JSON.stringify({
            name: data.toolName,
            args: data.args,
            id: `tool-${++commandCounter}`,
            session_id: inv.sessionId || null,
          })}\n\n`);
        }
      }
    }

    if (data.type === "tool_execution_end") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        const t = inv.tools.find((x) => x.name === data.toolName && x.status === "running");
        if (t) {
          t.status = data.isError ? "error" : "completed";
          t.result = data.result ? JSON.stringify(data.result) : "";
        }
        if (inv.stream) {
          inv.stream.write(`event: response.tool_result\ndata: ${JSON.stringify({
            id: `tool-${commandCounter}`,
            result: data.result ? JSON.stringify(data.result) : "",
            status: data.isError ? "error" : "completed",
            session_id: inv.sessionId || null,
          })}\n\n`);
        }
      }
    }

    // Mark invocation complete on agent_end
    if (data.type === "agent_end") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        clearTimeout(inv.timer);
        inv.done = true;
        const responseText = inv.chunks.join("");
        sessionStore.complete(inv.threadId, {
          status: "completed",
          toolCalls: inv.tools,
          metadata: buildPiMetadata(inv.config, { finish_reason: "stop" }),
          responseText,
        });
        if (inv.stream) {
          inv.stream.write(`event: response.completed\ndata: ${JSON.stringify({ session_id: inv.sessionId || null, tokens: buildPiMetadata(inv.config).tokens, status: "completed", finish_reason: "stop", response: responseText })}\n\n`);
        }
      }
    }

    if (data.type === "error") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        clearTimeout(inv.timer);
        inv.error = data.error || "Unknown error";
        inv.done = true;
        sessionStore.complete(inv.threadId, {
          status: "error",
          toolCalls: inv.tools,
          metadata: buildPiMetadata(inv.config, { finish_reason: "error" }),
          responseText: "",
        });
        if (inv.stream) {
          inv.stream.write(`event: response.error\ndata: ${JSON.stringify({ session_id: inv.sessionId || null, error: inv.error, code: 500 })}\n\n`);
        }
      }
    }

    // Broadcast events to SSE clients
    if (data.type && data.type !== "response") {
      const sseData = `data: ${JSON.stringify(data)}\n\n`;
      for (const stream of eventStreams) {
        try {
          stream.write(sseData);
        } catch (e) {
          eventStreams.delete(stream);
        }
      }
    }
  } catch (e) {
    // Non-JSON line, ignore
  }
}

function handleExtensionUIRequest(data) {
  const { id, method } = data;

  if (["notify", "setStatus", "setWidget", "setTitle", "set_editor_text"].includes(method)) {
    console.log("[pi-bridge] Extension UI:", method, data.message || data.statusText || "");
    return;
  }

  // Emit question.asked SSE event for interactive methods
  if (["confirm", "select", "input", "editor"].includes(method)) {
    const questionEvent = {
      id: `q-${id}`,
      question: data.title || data.message || "",
      options: data.options || [],
      session_id: null,
      method,
    };
    const sseData = `event: question.asked\ndata: ${JSON.stringify(questionEvent)}\n\n`;
    for (const stream of eventStreams) {
      try { stream.write(sseData); } catch (e) { eventStreams.delete(stream); }
    }
    for (const inv of ACTIVE_INVOCATIONS.values()) {
      if (inv.stream) {
        try { inv.stream.write(sseData); } catch (e) {}
      }
    }
  }

  let response = { type: "extension_ui_response", id };

  if (method === "confirm") {
    response.confirmed = true;
    console.log("[pi-bridge] Auto-approved confirm:", data.title);
  } else if (method === "select") {
    response.value = (data.options && data.options[0]) || "Allow";
    console.log("[pi-bridge] Auto-selected:", response.value);
  } else if (method === "input") {
    response.value = "";
  } else if (method === "editor") {
    response.value = data.prefill || "";
  } else {
    response.cancelled = true;
  }

  try {
    if (stdinKeepAliveFd !== null) {
      fs.writeSync(stdinKeepAliveFd, JSON.stringify(response) + "\n");
    } else {
      console.error("[pi-bridge] Cannot send extension UI response: stdin FIFO not open");
    }
  } catch (e) {
    console.error("[pi-bridge] Failed to send extension UI response:", e.message);
  }
}

function isPiAlive() {
  return piProcess !== null && !piProcess.killed && piProcess.exitCode === null;
}

// ── Read pi's stdout ────────────────────────────────────────────────

function startStdoutReader() {
  startStdoutReaderFromFd(null);
}

function startStdoutReaderFromFd(fd) {
  if (stdoutReader) {
    try { stdoutReader.destroy(); } catch {}
  }

  let buffer = "";
  try {
    const opts = { encoding: "utf8", highWaterMark: 4096 };
    if (fd !== null) {
      opts.fd = fd;
      opts.autoClose = false;
    }
    stdoutReader = fd !== null
      ? fs.createReadStream(null, opts)
      : fs.createReadStream(PI_STDOUT_FIFO, opts);

    stdoutReader.on("data", (chunk) => {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (line.trim()) {
          console.log("[pi-stdout]", line.trim());
          handlePiOutput(line);
        }
      }
    });

    stdoutReader.on("end", () => {
      console.log("[pi-bridge] stdout stream ended");
      stdoutReader = null;
    });

    stdoutReader.on("error", (err) => {
      console.error("[pi-bridge] stdout read error:", err.message);
      stdoutReader = null;
    });
  } catch (err) {
    console.error("[pi-bridge] Cannot read pi stdout:", err.message);
    stdoutReader = null;
  }
}

// ── HTTP Helpers ────────────────────────────────────────────────────

function jsonResponse(res, status, data, headers = {}) {
  res.writeHead(status, { "Content-Type": "application/json", ...headers });
  res.end(JSON.stringify(data));
}

function jsonError(res, status, message, options = {}) {
  const traceId = options.traceId || options.trace_id || res.getHeader("x-request-id");
  return jsonResponse(res, status, buildErrorPayload(status, message, {
    ...options,
    traceId,
  }));
}

function sseEvent(res, event, data) {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        resolve(JSON.parse(body));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

// ── Image/file attachment handler ───────────────────────────────────

function handleImageAttachments(message, images) {
  let finalMessage = message;
  if (Array.isArray(images) && images.length > 0) {
    const imagePaths = [];
    for (let i = 0; i < images.length; i++) {
      const img = images[i];
      const dataUrl = img.data || "";
      const name = img.name || `image-${i + 1}.png`;
      const safeName = name.replace(/[^a-zA-Z0-9._-]/g, "_");
      const match = dataUrl.match(/^data:[^;]+;base64,(.+)$/);
      if (match) {
        const filePath = `/workspace/${safeName}`;
        try {
          fs.writeFileSync(filePath, Buffer.from(match[1], "base64"));
          imagePaths.push(filePath);
        } catch (err) {
          console.error(`[pi-bridge] Failed to write image ${safeName}:`, err.message);
        }
      }
    }
    if (imagePaths.length > 0) {
      const fileList = imagePaths.map((p) => `- ${p}`).join("\n");
      finalMessage = `${message}\n\n[The user attached ${imagePaths.length} file(s) which have been saved to the workspace:\n${fileList}\n]`;
    }
  }
  return finalMessage;
}

// ── HTTP Handlers ───────────────────────────────────────────────────

async function handleRequest(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const requestPath = url.pathname;
  const method = req.method;
  const requestId = String(req.headers["x-request-id"] || crypto.randomUUID());

  // CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("x-request-id", requestId);
  if (method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization, x-request-id",
    });
    res.end();
    return;
  }

  // Health check — includes current config
  if (requestPath === "/health") {
    const alive = isPiAlive();
    const activeInvocations = Array.from(ACTIVE_INVOCATIONS.values()).filter((invocation) => !invocation.done).length;
    return jsonResponse(res, alive ? 200 : 503, {
      status: alive ? "healthy" : "unhealthy",
      runtime: "pi",
      service: SERVICE_NAME,
      namespace: SERVICE_NAMESPACE,
      provider: currentConfig.provider || "auto",
      agent: "build",
      sessions: {
        total: ACTIVE_INVOCATIONS.size,
        active: activeInvocations,
      },
      uptime_seconds: Math.max(Math.round(process.uptime() * 10) / 10, 0),
      timestamp: new Date().toISOString(),
      pi: alive ? "running" : "not running",
      pid: piProcess?.pid || null,
      config: currentConfig,
    });
  }

  // Readiness check
  if (requestPath === "/ready") {
    const checks = {
      pi_alive: isPiAlive(),
      state_accessible: false,
    };
    let error = null;
    try {
      await sendToPi({ type: "get_state" });
      checks.state_accessible = true;
    } catch (err) {
      error = err.message;
    }
    if (!checks.pi_alive && error === null) {
      error = "pi not running";
    }
    return jsonResponse(res, checks.pi_alive && checks.state_accessible ? 200 : 503, {
      status: checks.pi_alive && checks.state_accessible ? "ready" : "not_ready",
      runtime: "pi",
      checks,
      error,
    });
  }

  // Get state — includes current config
  if (requestPath === "/state" || requestPath === "/api/state") {
    try {
      const response = await sendToPi({ type: "get_state" });
      return jsonResponse(res, 200, {
        ...(response.data || response),
        currentConfig,
      });
    } catch (err) {
      return jsonError(res, 500, err.message);
    }
  }

  // Abort
  if (requestPath === "/abort" || requestPath === "/api/abort") {
    try {
      await sendToPi({ type: "abort" });
      return jsonResponse(res, 200, { status: "aborted" });
    } catch (err) {
      return jsonError(res, 500, err.message);
    }
  }

  if (requestPath === "/artifacts/list" && method === "GET") {
    try {
      return jsonResponse(res, 200, listArtifacts(url.searchParams.get("root") || ""));
    } catch (err) {
      return sendError(res, err);
    }
  }

  if (requestPath === "/artifacts/download" && method === "GET") {
    try {
      const requestedPath = url.searchParams.get("path") || "";
      if (!requestedPath) {
        return jsonError(res, 400, "path is required");
      }

      const artifactPath = resolveArtifactFile(requestedPath);
      const stat = fs.statSync(artifactPath);
      if (stat.size > ARTIFACT_DOWNLOAD_MAX_SIZE) {
        return jsonError(res, 413, `file exceeds max download size of ${ARTIFACT_DOWNLOAD_MAX_SIZE} bytes`);
      }

      res.writeHead(200, {
        "Content-Type": contentTypeForFile(artifactPath),
        "Content-Length": stat.size,
        "Content-Disposition": `attachment; filename="${path.basename(artifactPath)}"`,
      });
      fs.createReadStream(artifactPath).pipe(res);
      return;
    } catch (err) {
      return sendError(res, err);
    }
  }

  if (requestPath === "/artifacts/zip" && method === "GET") {
    return streamArtifactsZip(res, url.searchParams.get("root") || "");
  }

  // ── /invoke (synchronous) ────────────────────────────────────────
  if ((requestPath === "/invoke" || requestPath === "/api/invoke") && method === "POST") {
    try {
      const parsed = await readBody(req);
      const message = parsed.prompt || parsed.message || "";
      if (!message) {
        return jsonError(res, 400, "prompt is required");
      }

      const threadId = parsed.thread_id || `pi-${++commandCounter}`;
      const executionId = `exec-${threadId.slice(0, 16)}`;
      const startTime = Date.now();

      runtimeEvents.emitRunStarted(executionId, {
        thread_id: threadId,
        model: parsed.model || currentConfig.model,
      });

      // Dynamic model switching: check if request specifies different config
      await ensurePiWithConfig({
        model: parsed.model || "",
        provider: parsed.provider || "",
        thinkingLevel: parsed.thinkingLevel || parsed.thinking_level || "",
      });

      // Handle image attachments
      const finalMessage = handleImageAttachments(message, parsed.images);

      const { session, continuity } = sessionStore.begin(threadId, {
        model: currentConfig.model,
        prompt: finalMessage,
      });

      const invId = `invoke-${commandCounter}`;
      const invocation = {
        chunks: [],
        tools: [],
        done: false,
        error: null,
        stream: null,
        threadId,
        executionId,
        model: currentConfig.model,
        config: { ...currentConfig },
        continuity,
        sessionId: session.sessionId,
      };
      ACTIVE_INVOCATIONS.set(invId, invocation);

      await sendToPi({ type: "prompt", message: finalMessage });

      // Poll until done or timeout
      const start = Date.now();
      const timeout = MODEL_TIMEOUT_MS;
      while (!invocation.done && Date.now() - start < timeout) {
        await new Promise((r) => setTimeout(r, 100));
      }

      if (!invocation.done) {
        await sendToPi({ type: "abort" }).catch(() => {});
        invocation.error = `Model call timed out after ${MODEL_TIMEOUT_MS}ms`;
        sessionStore.complete(threadId, {
          status: "error",
          toolCalls: invocation.tools,
          metadata: buildPiMetadata(invocation.config, { finish_reason: "error" }),
          responseText: "",
        });
      }

      ACTIVE_INVOCATIONS.delete(invId);

      const durationMs = Date.now() - startTime;

      if (invocation.error) {
        runtimeEvents.emitRunError(executionId, {
          thread_id: threadId,
          error: invocation.error,
        });
        const timeoutError = invocation.error.toLowerCase().includes("timed out");
        return jsonError(res, timeoutError ? 504 : 502, invocation.error, {
          code: timeoutError ? "timeout" : "upstream_error",
          details: {
            thread_id: threadId,
            model: currentConfig.model,
          },
        });
      }

      const responseText = invocation.chunks.join("");
      sessionStore.complete(threadId, {
        status: "completed",
        toolCalls: invocation.tools,
        metadata: buildPiMetadata(invocation.config, { finish_reason: "stop" }),
        responseText,
      });
      runtimeEvents.emitLlmCall(executionId, {
        thread_id: threadId,
        model: currentConfig.model,
        total_tokens: 0,
        duration_ms: durationMs,
      });
      runtimeEvents.emitRunCompleted(executionId, {
        thread_id: threadId,
        status: "completed",
        duration_ms: durationMs,
      });

      // Emit tool call events
      for (const tc of invocation.tools) {
        runtimeEvents.emitToolCall(executionId, {
          tool_name: tc.name || "unknown",
          tool_args: tc.args,
          status: tc.status || "completed",
          thread_id: threadId,
        });
      }

      return jsonResponse(res, 200, {
        thread_id: threadId,
        response: responseText,
        model: currentConfig.model,
        status: "completed",
        warnings: [],
        artifacts: [],
        tool_calls: formatToolCalls(invocation.tools),
        continuity: invocation.continuity,
        metadata: buildPiMetadata(invocation.config, { finish_reason: "stop" }),
      });
    } catch (err) {
      return jsonError(res, 400, err.message);
    }
  }

  // ── /invoke/stream (SSE) ─────────────────────────────────────────
  if ((requestPath === "/invoke/stream" || requestPath === "/api/invoke/stream") && method === "POST") {
    try {
      const parsed = await readBody(req);
      const message = parsed.prompt || parsed.message || "";
      if (!message) {
        return jsonError(res, 400, "prompt is required");
      }

      const threadId = parsed.thread_id || `pi-${++commandCounter}`;
      const executionId = `exec-${threadId.slice(0, 16)}`;
      const startTime = Date.now();

      runtimeEvents.emitRunStarted(executionId, {
        thread_id: threadId,
        model: parsed.model || currentConfig.model,
      });

      // Dynamic model switching: check if request specifies different config
      await ensurePiWithConfig({
        model: parsed.model || "",
        provider: parsed.provider || "",
        thinkingLevel: parsed.thinkingLevel || parsed.thinking_level || "",
      });

      // Handle image attachments
      const finalMessage = handleImageAttachments(message, parsed.images);

      const { session, continuity } = sessionStore.begin(threadId, {
        model: currentConfig.model,
        prompt: finalMessage,
      });

      const invId = `stream-${commandCounter}`;
      const invocation = {
        chunks: [],
        tools: [],
        done: false,
        error: null,
        stream: res,
        id: invId,
        threadId,
        executionId,
        model: currentConfig.model,
        config: { ...currentConfig },
        continuity,
        sessionId: session.sessionId,
      };
      ACTIVE_INVOCATIONS.set(invId, invocation);

      // Set model timeout
      const modelTimer = setTimeout(() => {
        if (!invocation.done && !invocation.error) {
          const timeoutErr = `Model call timed out after ${MODEL_TIMEOUT_MS}ms`;
          console.error(`[pi-bridge] ${timeoutErr} for ${invId}`);
          invocation.error = timeoutErr;
          invocation.done = true;
          sessionStore.complete(threadId, {
            status: "error",
            toolCalls: invocation.tools,
            metadata: buildPiMetadata(invocation.config, { finish_reason: "error" }),
            responseText: "",
          });
          if (!invocation.stream.destroyed) {
            invocation.stream.write(`event: response.error\ndata: ${JSON.stringify({ session_id: invocation.sessionId, error: timeoutErr, code: 504 })}\n\n`);
            invocation.stream.end();
          }
          runtimeEvents.emitRunError(executionId, {
            thread_id: threadId,
            error: timeoutErr,
          });
          sendToPi({ type: "abort" }).catch(() => {});
        }
      }, MODEL_TIMEOUT_MS);
      invocation.timer = modelTimer;

      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });

      // Send response.started as first SSE event
      res.write(`event: response.started\ndata: ${JSON.stringify({ session_id: invocation.sessionId, model: currentConfig.model, thread_id: threadId })}\n\n`);

      req.on("close", () => {
        clearTimeout(invocation.timer);
        ACTIVE_INVOCATIONS.delete(invId);
        if (invocation.done && !invocation.error) {
          const durationMs = Date.now() - startTime;
          runtimeEvents.emitLlmCall(executionId, {
            thread_id: threadId,
            model: invocation.model,
            total_tokens: 0,
            duration_ms: durationMs,
          });
          runtimeEvents.emitRunCompleted(executionId, {
            thread_id: threadId,
            status: "completed",
            duration_ms: durationMs,
          });
          for (const tc of invocation.tools) {
            runtimeEvents.emitToolCall(executionId, {
              tool_name: tc.name || "unknown",
              tool_args: tc.args,
              status: tc.status || "completed",
              thread_id: threadId,
            });
          }
        } else if (invocation.error) {
          runtimeEvents.emitRunError(executionId, {
            thread_id: threadId,
            error: invocation.error,
          });
        }
      });

      await sendToPi({ type: "prompt", message: finalMessage });

      // Keep connection alive and close when done
      const keepalive = setInterval(() => {
        if (invocation.done || res.destroyed) {
          clearInterval(keepalive);
          clearTimeout(invocation.timer);
          if (!res.destroyed) {
            res.end();
          }
          ACTIVE_INVOCATIONS.delete(invId);
          return;
        }
        res.write(":keepalive\n\n");
      }, 15000);

      return;
    } catch (err) {
      if (res.headersSent) {
        res.end();
      } else {
        jsonError(res, 400, err.message);
      }
    }
  }

  // ── /prompt (legacy SSE) ─────────────────────────────────────────
  if ((requestPath === "/prompt" || requestPath === "/api/prompt") && method === "POST") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", async () => {
      try {
        const parsed = JSON.parse(body);
        const message = parsed.message || parsed.prompt || "";
        if (!message) {
          return jsonError(res, 400, "message is required");
        }

        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        });

        eventStreams.add(res);
        req.on("close", () => eventStreams.delete(res));

        await sendToPi({ type: "prompt", message }).catch((err) => {
          res.write(`data: ${JSON.stringify({ type: "error", error: err.message })}\n\n`);
        });
      } catch (err) {
        jsonError(res, 400, err.message);
      }
    });
    return;
  }

  // ── /info (runtime metadata) ──────────────────────────────────────
  if (requestPath === "/info" && method === "GET") {
    return jsonResponse(res, 200, {
      runtime: "pi",
      contract_version: "v1",
      service: SERVICE_NAME,
      namespace: SERVICE_NAMESPACE,
      provider: currentConfig.provider || "auto",
      model: currentConfig.model || "default",
      agent: "build",
      version: "1.0.0",
      capabilities: piCapabilities(),
    });
  }

  // ── /capabilities ─────────────────────────────────────────────────
  if (requestPath === "/capabilities" && method === "GET") {
    return jsonResponse(res, 200, {
      runtime: "pi",
      service: SERVICE_NAME,
      capabilities: piCapabilities(),
    });
  }

  // ── /cancel (alias for /abort) ────────────────────────────────────
  if (requestPath === "/cancel" && method === "POST") {
    const threadId = url.searchParams.get("thread_id") || "";
    if (!threadId) {
      return jsonError(res, 400, "thread_id query parameter is required");
    }
    const session = sessionStore.get(threadId);
    if (!session) {
      return jsonError(res, 404, `No session found for thread_id '${threadId}'`);
    }
    try {
      await sendToPi({ type: "abort" });
      const cancelled = sessionStore.cancel(threadId);
      return jsonResponse(res, 200, {
        status: cancelled && cancelled.status === "cancelled" ? "cancelled" : "cancel_failed",
        session_id: session.sessionId,
        thread_id: threadId,
      });
    } catch (err) {
      sessionStore.cancel(threadId);
      return jsonResponse(res, 200, {
        status: "cancel_failed",
        session_id: session.sessionId,
        thread_id: threadId,
      });
    }
  }

  // ── /todo ─────────────────────────────────────────────────────────
  if (requestPath === "/todo" && method === "GET") {
    const threadId = url.searchParams.get("thread_id");
    if (!threadId) {
      return jsonError(res, 400, "thread_id query parameter is required");
    }
    const session = sessionStore.get(threadId);
    if (!session) {
      return jsonError(res, 404, `No session found for thread_id '${threadId}'`);
    }
    const todos = session.todos || [];
    const etag = `"${crypto.createHash("md5").update(JSON.stringify(todos)).digest("hex")}"`;
    const clientEtag = (req.headers["if-none-match"] || "").trim().replace(/^"|"$/g, "");
    if (clientEtag && clientEtag === etag.replace(/^"|"$/g, "")) {
      res.writeHead(304, { ETag: etag });
      return res.end();
    }
    return jsonResponse(res, 200, { thread_id: threadId, session_id: session.sessionId, todos }, { ETag: etag });
  }

  // ── /question ─────────────────────────────────────────────────────
  if (requestPath === "/question" && method === "GET") {
    return jsonResponse(res, 200, []);
  }

  // ── /question/{id}/reply ──────────────────────────────────────────
  if (requestPath.match(/^\/question\/[^/]+\/reply$/) && method === "POST") {
    const requestId = requestPath.split("/")[2];
    try {
      const parsed = await readBody(req);
      await sendToPi({ type: "extension_ui_response", id: `bridge-${++commandCounter}`, confirmed: true, value: parsed.answer || "" });
      return jsonResponse(res, 200, { status: "accepted", request_id: requestId });
    } catch (err) {
      return jsonError(res, 500, err.message);
    }
  }

  // ── /question/{id}/reject ─────────────────────────────────────────
  if (requestPath.match(/^\/question\/[^/]+\/reject$/) && method === "POST") {
    const requestId = requestPath.split("/")[2];
    try {
      await sendToPi({ type: "extension_ui_response", id: `bridge-${++commandCounter}`, confirmed: false, cancelled: true });
      return jsonResponse(res, 200, { status: "rejected", request_id: requestId });
    } catch (err) {
      return jsonError(res, 500, err.message);
    }
  }

  // ── /diff ─────────────────────────────────────────────────────────
  if (requestPath === "/diff" && method === "GET") {
    const threadId = url.searchParams.get("thread_id");
    if (!threadId) {
      return jsonError(res, 400, "thread_id query parameter is required");
    }
    const session = sessionStore.get(threadId);
    if (!session) {
      return jsonError(res, 404, `No session found for thread_id '${threadId}'`);
    }
    return jsonResponse(res, 200, { thread_id: threadId, session_id: session.sessionId, diff: session.diff || "" });
  }

  // ── /context-budget ───────────────────────────────────────────────
  if (requestPath === "/context-budget" && method === "GET") {
    const threadId = url.searchParams.get("thread_id");
    if (!threadId) {
      return jsonError(res, 400, "thread_id query parameter is required");
    }
    const session = sessionStore.get(threadId);
    if (!session) {
      return jsonError(res, 404, `No session found for thread_id '${threadId}'`);
    }
    return jsonResponse(res, 200, {
      thread_id: threadId,
      session_id: session.sessionId,
      ...session.contextBudget,
    });
  }

  // ── /openapi.json (OpenAPI spec) ──────────────────────────────────
  if (requestPath === "/openapi.json" && method === "GET") {
    try {
      const specPath = path.join(__dirname, "openapi.json");
      const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
      return jsonResponse(res, 200, spec);
    } catch (err) {
      return jsonError(res, 500, "OpenAPI spec not available");
    }
  }

  // ── /docs (Swagger UI) ────────────────────────────────────────────
  if (requestPath === "/docs" && method === "GET") {
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KubeSynth Runtime API — Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>body{margin:0;padding:0}#swagger-ui{max-width:1400px;margin:0 auto}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = () => {
      SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.StandalonePreset],
        layout: "BaseLayout",
      });
    };
  </script>
</body>
</html>`);
    return;
  }

  // ── /events (SSE event subscription) ──────────────────────────────
  if (requestPath === "/events" && method === "GET") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    res.write(":connected\n\n");
    eventStreams.add(res);
    req.on("close", () => {
      eventStreams.delete(res);
      if (!res.destroyed) res.end();
    });
    return;
  }

  // 404
  jsonError(res, 404, "Not found");
}

// ── Main ─────────────────────────────────────────────────────────────
let server = null;

function startServer() {
  console.log("[pi-bridge] Starting subprocess manager on", HOST + ":" + PORT);
  console.log("[pi-bridge] Default config:", JSON.stringify(currentConfig));

  runtimeEvents.startEmitter();

  server = http.createServer(handleRequest);
  server.listen(PORT, HOST, async () => {
    console.log("[pi-bridge] HTTP server listening on", HOST + ":" + PORT);

    try {
      await startPi(currentConfig);
      console.log("[pi-bridge] Pi subprocess started successfully");
    } catch (err) {
      console.error("[pi-bridge] Failed to start pi subprocess:", err.message);
      console.error("[pi-bridge] Bridge will retry when first invoke request arrives");
    }
  });

  return server;
}

// Graceful shutdown
async function shutdown(signal) {
  console.log(`[pi-bridge] Received ${signal}, shutting down...`);
  runtimeEvents.stopEmitter();
  await stopPi();
  if (!server) {
    process.exit(0);
    return;
  }
  server.close(() => {
    console.log("[pi-bridge] HTTP server closed");
    process.exit(0);
  });
  // Force exit after 10 seconds
  setTimeout(() => process.exit(1), 10000);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

if (require.main === module) {
  startServer();
}

module.exports = {
  buildErrorPayload,
  handleRequest,
  jsonError,
  jsonResponse,
  sendError,
  startServer,
};
