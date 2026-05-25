const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

function buildContinuity(createdNewSession) {
  return {
    created_new_session: createdNewSession,
    session_recovered: false,
    has_prior_memory: false,
  };
}

function summarizePrompt(prompt) {
  const singleLine = String(prompt || "").trim().replace(/\s+/g, " ");
  if (singleLine.length <= 120) {
    return singleLine;
  }
  return `${singleLine.slice(0, 117)}...`;
}

function mapTodoStatus(sessionStatus) {
  if (sessionStatus === "active") return "in_progress";
  if (sessionStatus === "completed") return "completed";
  return "cancelled";
}

function mapToolTodoStatus(toolStatus, fallbackStatus) {
  if (toolStatus === "running") return "in_progress";
  if (toolStatus === "completed") return "completed";
  if (toolStatus === "pending") return "pending";
  if (toolStatus === "error") return "cancelled";
  return fallbackStatus;
}

function normalizeToolCalls(toolCalls) {
  return (toolCalls || []).map((toolCall) => ({
    name: String((toolCall && (toolCall.name || toolCall.tool)) || "tool"),
    args: toolCall && (toolCall.args !== undefined ? toolCall.args : toolCall.input),
    result: toolCall && toolCall.result !== undefined ? toolCall.result : "",
    status: String((toolCall && toolCall.status) || "completed"),
  }));
}

function buildSessionTodos(prompt, toolCalls, sessionStatus) {
  const todos = [];
  const fallbackStatus = mapTodoStatus(sessionStatus);
  if (prompt) {
    todos.push({
      content: summarizePrompt(prompt),
      status: fallbackStatus,
    });
  }
  for (const toolCall of normalizeToolCalls(toolCalls)) {
    todos.push({
      content: `Run tool ${toolCall.name}`,
      status: mapToolTodoStatus(toolCall.status, fallbackStatus),
    });
  }
  return todos;
}

function deriveContextBudget(metadata = {}, modelContextLimit = 128000) {
  const tokens = metadata && typeof metadata.tokens === "object" ? metadata.tokens : {};
  const total = Number.isFinite(Number(tokens.total))
    ? Number(tokens.total)
    : Number(tokens.input || 0) + Number(tokens.output || 0);
  const limit = Math.max(Number(modelContextLimit) || 128000, 1024);
  const tokensUsed = Math.max(total, 0);
  const tokensRemaining = Math.max(limit - tokensUsed, 0);
  const usagePercent = Number(((tokensUsed / limit) * 100).toFixed(2));
  let status = "ok";
  if (usagePercent >= 100) {
    status = "overflow";
  } else if (usagePercent >= 90) {
    status = "critical";
  } else if (usagePercent >= 75) {
    status = "warning";
  }
  return {
    model_context_limit: limit,
    tokens_used: tokensUsed,
    tokens_remaining: tokensRemaining,
    usage_percent: usagePercent,
    status,
    compaction_available: false,
  };
}

function captureWorkspaceSnapshot(rootDir, options = {}) {
  const maxFiles = Math.max(Number(options.maxFiles || 128), 1);
  const maxFileBytes = Math.max(Number(options.maxFileBytes || (128 * 1024)), 1);
  const snapshot = {};
  const root = path.resolve(rootDir);
  if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    return snapshot;
  }

  const stack = [root];
  while (stack.length > 0 && Object.keys(snapshot).length < maxFiles) {
    const current = stack.pop();
    let entries = [];
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
        stack.push(fullPath);
        continue;
      }
      if (!entry.isFile()) {
        continue;
      }
      let stat;
      try {
        stat = fs.statSync(fullPath);
      } catch {
        continue;
      }
      if (stat.size > maxFileBytes) {
        continue;
      }
      try {
        snapshot[path.relative(root, fullPath).replace(/\\/g, "/")] = fs.readFileSync(fullPath, "utf8").split(/(?<=\n)/);
      } catch {
        continue;
      }
      if (Object.keys(snapshot).length >= maxFiles) {
        break;
      }
    }
  }
  return snapshot;
}

function renderFileDiff(relativePath, beforeLines, afterLines) {
  if (JSON.stringify(beforeLines) === JSON.stringify(afterLines)) {
    return "";
  }
  const removed = beforeLines.map((line) => `-${line.replace(/\n$/, "")}`);
  const added = afterLines.map((line) => `+${line.replace(/\n$/, "")}`);
  return [
    `--- a/${relativePath}`,
    `+++ b/${relativePath}`,
    ...removed,
    ...added,
  ].join("\n");
}

function buildWorkspaceDiff(beforeSnapshot, afterSnapshot) {
  const changed = [];
  const allPaths = new Set([...Object.keys(beforeSnapshot || {}), ...Object.keys(afterSnapshot || {})]);
  for (const relativePath of Array.from(allPaths).sort()) {
    const rendered = renderFileDiff(relativePath, beforeSnapshot[relativePath] || [], afterSnapshot[relativePath] || []);
    if (rendered) {
      changed.push(rendered);
    }
  }
  return changed.join("\n\n");
}

class SessionStore {
  constructor(options = {}) {
    this.workspaceDir = path.resolve(options.workspaceDir || process.cwd());
    this.modelContextLimit = Math.max(Number(options.modelContextLimit || 128000), 1024);
    this.snapshotMaxFiles = Math.max(Number(options.snapshotMaxFiles || 128), 1);
    this.snapshotMaxFileBytes = Math.max(Number(options.snapshotMaxFileBytes || (128 * 1024)), 1);
    this.sessions = new Map();
  }

  begin(threadId, { model, prompt }) {
    const existing = this.sessions.get(threadId);
    if (existing) {
      existing.model = model;
      existing.prompt = prompt;
      existing.status = "active";
      existing.updatedAt = Date.now();
      existing.todos = buildSessionTodos(prompt, existing.toolCalls, "active");
      return { session: existing, continuity: buildContinuity(false) };
    }

    const session = {
      threadId,
      sessionId: `pi-session-${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`,
      model,
      prompt,
      status: "active",
      createdAt: Date.now(),
      updatedAt: Date.now(),
      toolCalls: [],
      todos: buildSessionTodos(prompt, [], "active"),
      metadata: {},
      contextBudget: deriveContextBudget({}, this.modelContextLimit),
      diff: "",
      workspaceSnapshot: captureWorkspaceSnapshot(this.workspaceDir, {
        maxFiles: this.snapshotMaxFiles,
        maxFileBytes: this.snapshotMaxFileBytes,
      }),
      responseText: "",
    };
    this.sessions.set(threadId, session);
    return { session, continuity: buildContinuity(true) };
  }

  complete(threadId, { status = "completed", toolCalls = [], metadata = {}, responseText = "" } = {}) {
    const session = this.sessions.get(threadId);
    if (!session) {
      return null;
    }
    session.status = status;
    session.updatedAt = Date.now();
    session.toolCalls = normalizeToolCalls(toolCalls);
    session.metadata = metadata;
    session.todos = buildSessionTodos(session.prompt, session.toolCalls, status);
    session.contextBudget = deriveContextBudget(metadata, this.modelContextLimit);
    session.diff = buildWorkspaceDiff(
      session.workspaceSnapshot,
      captureWorkspaceSnapshot(this.workspaceDir, {
        maxFiles: this.snapshotMaxFiles,
        maxFileBytes: this.snapshotMaxFileBytes,
      }),
    );
    session.responseText = responseText;
    return session;
  }

  cancel(threadId) {
    const session = this.sessions.get(threadId);
    if (!session) {
      return null;
    }
    if (session.status === "active") {
      session.status = "cancelled";
      session.updatedAt = Date.now();
      session.todos = buildSessionTodos(session.prompt, session.toolCalls, "cancelled");
      return session;
    }
    return session;
  }

  get(threadId) {
    return this.sessions.get(threadId) || null;
  }

  reset() {
    this.sessions.clear();
  }
}

module.exports = {
  SessionStore,
  buildContinuity,
  buildSessionTodos,
  deriveContextBudget,
  captureWorkspaceSnapshot,
  buildWorkspaceDiff,
};