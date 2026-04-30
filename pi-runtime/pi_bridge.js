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
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, execSync } = require("child_process");

const HOST = process.env.PI_BRIDGE_HOST || "0.0.0.0";
const PORT = parseInt(process.env.PI_BRIDGE_PORT || "8080", 10);
const PI_STDIN_FIFO = "/tmp/pi-stdin";
const PI_STDOUT_FIFO = "/tmp/pi-stdout";
const WORKDIR = path.resolve(process.env.OPENCODE_WORKDIR || "/workspace");
const HOME_DIR = path.resolve(process.env.HOME || "/home/piuser");
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

function sendError(res, err, fallbackStatus = 500) {
  const status = Number.isInteger(err?.statusCode) ? err.statusCode : fallbackStatus;
  return jsonResponse(res, status, { error: err?.message || "Unexpected error" });
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
        inv.stream.write(`event: response.error\ndata: ${JSON.stringify({ error: inv.error })}\n\n`);
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
            if (inv.stream) {
              inv.stream.write(`event: response.error\ndata: ${JSON.stringify({ error: errorMessage })}\n\n`);
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
            inv.stream.write(`event: response.delta\ndata: ${JSON.stringify({ delta: evt.delta, source: "pi" })}\n\n`);
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
        inv.tools.push({ tool: data.toolName, status: "running", input: data.args });
        if (inv.stream) {
          inv.stream.write(`event: response.tool_call\ndata: ${JSON.stringify({
            tool: data.toolName,
            status: "running",
            input: data.args,
            source: "pi"
          })}\n\n`);
        }
      }
    }

    if (data.type === "tool_execution_end") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        const t = inv.tools.find((x) => x.tool === data.toolName && x.status === "running");
        if (t) t.status = data.isError ? "error" : "completed";
        if (inv.stream) {
          inv.stream.write(`event: response.tool_call\ndata: ${JSON.stringify({
            tool: data.toolName,
            status: data.isError ? "error" : "completed",
            output: data.result ? JSON.stringify(data.result) : "",
            source: "pi"
          })}\n\n`);
        }
      }
    }

    // Mark invocation complete on agent_end
    if (data.type === "agent_end") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        clearTimeout(inv.timer);
        inv.done = true;
        if (inv.stream) {
          const responseText = inv.chunks.join("");
          inv.stream.write(`event: response.completed\ndata: ${JSON.stringify({ status: "completed", response: responseText })}\n\n`);
        }
      }
    }

    if (data.type === "error") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        clearTimeout(inv.timer);
        inv.error = data.error || "Unknown error";
        inv.done = true;
        if (inv.stream) {
          inv.stream.write(`event: response.error\ndata: ${JSON.stringify({ error: inv.error })}\n\n`);
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

function jsonResponse(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
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

  // CORS
  res.setHeader("Access-Control-Allow-Origin", "*");
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
    return jsonResponse(res, alive ? 200 : 503, {
      status: alive ? "healthy" : "unhealthy",
      pi: alive ? "running" : "not running",
      pid: piProcess?.pid || null,
      config: currentConfig,
    });
  }

  // Readiness check
  if (requestPath === "/ready") {
    if (!isPiAlive()) {
      return jsonResponse(res, 503, { status: "not ready", error: "pi not running" });
    }
    try {
      await sendToPi({ type: "get_state" });
      return jsonResponse(res, 200, { status: "ready" });
    } catch (err) {
      return jsonResponse(res, 503, { status: "not ready", error: err.message });
    }
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
      return jsonResponse(res, 500, { error: err.message });
    }
  }

  // Abort
  if (requestPath === "/abort" || requestPath === "/api/abort") {
    try {
      await sendToPi({ type: "abort" });
      return jsonResponse(res, 200, { status: "aborted" });
    } catch (err) {
      return jsonResponse(res, 500, { error: err.message });
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
        return jsonResponse(res, 400, { error: "path is required" });
      }

      const artifactPath = resolveArtifactFile(requestedPath);
      const stat = fs.statSync(artifactPath);
      if (stat.size > ARTIFACT_DOWNLOAD_MAX_SIZE) {
        return jsonResponse(res, 413, { error: `file exceeds max download size of ${ARTIFACT_DOWNLOAD_MAX_SIZE} bytes` });
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
        return jsonResponse(res, 400, { error: "prompt is required" });
      }

      // Dynamic model switching: check if request specifies different config
      await ensurePiWithConfig({
        model: parsed.model || "",
        provider: parsed.provider || "",
        thinkingLevel: parsed.thinkingLevel || parsed.thinking_level || "",
      });

      // Handle image attachments
      const finalMessage = handleImageAttachments(message, parsed.images);

      const invId = `invoke-${++commandCounter}`;
      const invocation = { chunks: [], tools: [], done: false, error: null, stream: null };
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
      }

      ACTIVE_INVOCATIONS.delete(invId);

      if (invocation.error) {
        return jsonResponse(res, 502, {
          thread_id: parsed.thread_id || invId,
          response: "",
          model: currentConfig.model,
          status: "failed",
          warnings: [invocation.error],
          artifacts: [],
          tool_calls: invocation.tools,
          metadata: { runtime: "pi", config: currentConfig },
        });
      }

      const responseText = invocation.chunks.join("");
      return jsonResponse(res, 200, {
        thread_id: parsed.thread_id || invId,
        response: responseText,
        model: currentConfig.model,
        status: "completed",
        warnings: [],
        artifacts: [],
        tool_calls: invocation.tools,
        metadata: { runtime: "pi", config: currentConfig },
      });
    } catch (err) {
      return jsonResponse(res, 400, { error: err.message });
    }
  }

  // ── /invoke/stream (SSE) ─────────────────────────────────────────
  if ((requestPath === "/invoke/stream" || requestPath === "/api/invoke/stream") && method === "POST") {
    try {
      const parsed = await readBody(req);
      const message = parsed.prompt || parsed.message || "";
      if (!message) {
        return jsonResponse(res, 400, { error: "prompt is required" });
      }

      // Dynamic model switching: check if request specifies different config
      await ensurePiWithConfig({
        model: parsed.model || "",
        provider: parsed.provider || "",
        thinkingLevel: parsed.thinkingLevel || parsed.thinking_level || "",
      });

      // Handle image attachments
      const finalMessage = handleImageAttachments(message, parsed.images);

      const invId = `stream-${++commandCounter}`;
      const invocation = { chunks: [], tools: [], done: false, error: null, stream: res };
      ACTIVE_INVOCATIONS.set(invId, invocation);

      // Set model timeout
      const modelTimer = setTimeout(() => {
        if (!invocation.done && !invocation.error) {
          const timeoutErr = `Model call timed out after ${MODEL_TIMEOUT_MS}ms`;
          console.error(`[pi-bridge] ${timeoutErr} for ${invId}`);
          invocation.error = timeoutErr;
          invocation.done = true;
          if (!invocation.stream.destroyed) {
            invocation.stream.write(`event: response.error\ndata: ${JSON.stringify({ error: timeoutErr })}\n\n`);
            invocation.stream.end();
          }
          sendToPi({ type: "abort" }).catch(() => {});
        }
      }, MODEL_TIMEOUT_MS);
      invocation.timer = modelTimer;

      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });

      // Send config info as first SSE event so frontend knows the active model
      res.write(`event: response.config\ndata: ${JSON.stringify({ config: currentConfig })}\n\n`);

      req.on("close", () => {
        clearTimeout(invocation.timer);
        ACTIVE_INVOCATIONS.delete(invId);
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
        jsonResponse(res, 400, { error: err.message });
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
          return jsonResponse(res, 400, { error: "message is required" });
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
        jsonResponse(res, 400, { error: err.message });
      }
    });
    return;
  }

  // 404
  jsonResponse(res, 404, { error: "Not found" });
}

// ── Main ─────────────────────────────────────────────────────────────

console.log("[pi-bridge] Starting subprocess manager on", HOST + ":" + PORT);
console.log("[pi-bridge] Default config:", JSON.stringify(currentConfig));

// Start the HTTP server first, then spawn pi
const server = http.createServer(handleRequest);
server.listen(PORT, HOST, async () => {
  console.log("[pi-bridge] HTTP server listening on", HOST + ":" + PORT);

  // Spawn pi with default config from env vars
  try {
    await startPi(currentConfig);
    console.log("[pi-bridge] Pi subprocess started successfully");
  } catch (err) {
    console.error("[pi-bridge] Failed to start pi subprocess:", err.message);
    console.error("[pi-bridge] Bridge will retry when first invoke request arrives");
  }
});

// Graceful shutdown
async function shutdown(signal) {
  console.log(`[pi-bridge] Received ${signal}, shutting down...`);
  await stopPi();
  server.close(() => {
    console.log("[pi-bridge] HTTP server closed");
    process.exit(0);
  });
  // Force exit after 10 seconds
  setTimeout(() => process.exit(1), 10000);
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
