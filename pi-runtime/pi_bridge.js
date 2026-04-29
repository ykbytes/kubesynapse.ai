#!/usr/bin/env node
/**
 * HTTP-to-pi-RPC Bridge (Node.js)
 *
 * Minimal HTTP server that bridges HTTP requests to pi's RPC stdin/stdout.
 * No external dependencies — uses only Node.js built-in modules.
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
const { spawn } = require("child_process");

const HOST = process.env.PI_BRIDGE_HOST || "0.0.0.0";
const PORT = parseInt(process.env.PI_BRIDGE_PORT || "8080", 10);
const PI_FIFO = process.env.PI_FIFO_PATH || "/tmp/pi-stdin";
const PI_STDOUT_FIFO = process.env.PI_STDOUT_PATH || "/tmp/pi-stdout";
const WORKDIR = path.resolve(process.env.OPENCODE_WORKDIR || "/workspace");
const HOME_DIR = path.resolve(process.env.HOME || "/home/piuser");
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
const MODEL_TIMEOUT_MS = Math.max(parseInt(process.env.PI_MODEL_TIMEOUT_MS || "120000", 10) || 120000, 10000); // default 120s, min 10s

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

// ── Pi Communication ────────────────────────────────────────────────

function sendToPi(command) {
  const id = `bridge-${++commandCounter}`;
  const payload = JSON.stringify({ ...command, id }) + "\n";

  return new Promise((resolve, reject) => {
    try {
      const fd = fs.openSync(PI_FIFO, "w");
      fs.writeSync(fd, payload);
      fs.closeSync(fd);

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
    // Pi sends message_update with assistantMessageEvent.delta for text chunks
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
      // Also accumulate from message.content if present (assistant only)
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

    // Mark invocation complete on agent_end (full response received)
    if (data.type === "agent_end") {
      for (const inv of ACTIVE_INVOCATIONS.values()) {
        clearTimeout(inv.timer);
        inv.done = true;
        if (inv.stream) {
          inv.stream.write(`event: response.completed\ndata: ${JSON.stringify({ status: "completed" })}\n\n`);
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
    const fd = fs.openSync(PI_FIFO, "w");
    fs.writeSync(fd, JSON.stringify(response) + "\n");
    fs.closeSync(fd);
  } catch (e) {
    console.error("[pi-bridge] Failed to send extension UI response:", e.message);
  }
}

function isPiAlive() {
  try {
    const cmdline = fs.readFileSync("/proc/1/cmdline", "utf8");
    return cmdline.includes("pi");
  } catch {
    return false;
  }
}

// ── Read pi's stdout ────────────────────────────────────────────────

function startStdoutReader() {
  let buffer = "";
  const stdoutPath = PI_STDOUT_FIFO || "/tmp/pi-stdout";

  try {
    const stdout = fs.createReadStream(stdoutPath, {
      encoding: "utf8",
      highWaterMark: 4096,
    });

    stdout.on("data", (chunk) => {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (line.trim()) {
          // Log raw pi output for Kubernetes observability
          console.log("[pi-stdout]", line.trim());
          handlePiOutput(line);
        }
      }
    });

    stdout.on("end", () => {
      // Pi exited or stdout closed; attempt to re-open after a delay
      console.log("[pi-bridge] stdout stream ended, will retry in 2s...");
      setTimeout(startStdoutReader, 2000);
    });

    stdout.on("error", (err) => {
      console.error("[pi-bridge] stdout read error:", err.message);
      setTimeout(startStdoutReader, 2000);
    });
  } catch (err) {
    console.error("[pi-bridge] Cannot read pi stdout:", err.message);
    setTimeout(startStdoutReader, 2000);
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

  // Health check
  if (requestPath === "/health") {
    const alive = isPiAlive();
    return jsonResponse(res, alive ? 200 : 503, {
      status: alive ? "healthy" : "unhealthy",
      pi: alive ? "running" : "not running",
    });
  }

  // Readiness check
  if (requestPath === "/ready") {
    try {
      await sendToPi({ type: "get_state" });
      return jsonResponse(res, 200, { status: "ready" });
    } catch (err) {
      return jsonResponse(res, 503, { status: "not ready", error: err.message });
    }
  }

  // Get state
  if (requestPath === "/state" || requestPath === "/api/state") {
    try {
      const response = await sendToPi({ type: "get_state" });
      return jsonResponse(res, 200, response.data || response);
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

      const invId = `invoke-${++commandCounter}`;
      const invocation = { chunks: [], tools: [], done: false, error: null, stream: null };
      ACTIVE_INVOCATIONS.set(invId, invocation);

      // Send prompt
      await sendToPi({ type: "prompt", message });

      // Poll until done or timeout
      const start = Date.now();
      const timeout = MODEL_TIMEOUT_MS;
      while (!invocation.done && Date.now() - start < timeout) {
        await new Promise((r) => setTimeout(r, 100));
      }

      if (!invocation.done) {
        // Timeout — abort Pi
        await sendToPi({ type: "abort" }).catch(() => {});
        invocation.error = `Model call timed out after ${MODEL_TIMEOUT_MS}ms`;
      }

      ACTIVE_INVOCATIONS.delete(invId);

      if (invocation.error) {
        return jsonResponse(res, 502, {
          thread_id: parsed.thread_id || invId,
          response: "",
          model: parsed.model || "",
          status: "failed",
          warnings: [invocation.error],
          artifacts: [],
          tool_calls: invocation.tools,
          metadata: {},
        });
      }

      const responseText = invocation.chunks.join("");
      return jsonResponse(res, 200, {
        thread_id: parsed.thread_id || invId,
        response: responseText,
        model: parsed.model || "",
        status: "completed",
        warnings: [],
        artifacts: [],
        tool_calls: invocation.tools,
        metadata: { runtime: "pi" },
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

      const invId = `stream-${++commandCounter}`;
      const invocation = { chunks: [], tools: [], done: false, error: null, stream: res };
      ACTIVE_INVOCATIONS.set(invId, invocation);

      // Set model timeout — abort if Pi doesn't respond within MODEL_TIMEOUT_MS
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
          // Abort Pi to free it for next request
          sendToPi({ type: "abort" }).catch(() => {});
        }
      }, MODEL_TIMEOUT_MS);
      invocation.timer = modelTimer;

      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      });

      req.on("close", () => {
        clearTimeout(invocation.timer);
        ACTIVE_INVOCATIONS.delete(invId);
      });

      // Send prompt
      await sendToPi({ type: "prompt", message });

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

console.log("[pi-bridge] Starting on", HOST + ":" + PORT);
console.log("[pi-bridge] Pi FIFO:", PI_FIFO);

startStdoutReader();

const server = http.createServer(handleRequest);
server.listen(PORT, HOST, () => {
  console.log("[pi-bridge] Listening on", HOST + ":" + PORT);
  console.log("[pi-bridge] Pi alive:", isPiAlive());
});

process.on("SIGTERM", () => {
  console.log("[pi-bridge] Shutting down...");
  server.close(() => process.exit(0));
});

process.on("SIGINT", () => {
  server.close(() => process.exit(0));
});
