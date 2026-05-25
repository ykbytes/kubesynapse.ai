const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { SessionStore } = require("../session_state");

function withWorkspace(run) {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), "pi-session-store-"));
  try {
    fs.writeFileSync(path.join(workspace, "hello.txt"), "hello\n", "utf8");
    run(workspace);
  } finally {
    fs.rmSync(workspace, { recursive: true, force: true });
  }
}

test("reused thread ids keep the same logical session id", () => {
  withWorkspace((workspace) => {
    const store = new SessionStore({ workspaceDir: workspace });

    const first = store.begin("thread-1", { model: "pi-model", prompt: "First prompt" });
    const second = store.begin("thread-1", { model: "pi-model", prompt: "Second prompt" });

    assert.equal(first.continuity.created_new_session, true);
    assert.equal(second.continuity.created_new_session, false);
    assert.equal(first.session.sessionId, second.session.sessionId);
  });
});

test("completed sessions expose todos, diff, and context budget", () => {
  withWorkspace((workspace) => {
    const store = new SessionStore({ workspaceDir: workspace });
    store.begin("thread-2", { model: "pi-model", prompt: "Inspect workspace" });

    fs.writeFileSync(path.join(workspace, "hello.txt"), "updated\n", "utf8");

    const session = store.complete("thread-2", {
      status: "completed",
      toolCalls: [{ name: "bash", args: { command: "pwd" }, status: "completed" }],
      metadata: { tokens: { total: 18, input: 10, output: 8 } },
      responseText: "done",
    });

    assert.equal(session.todos[0].status, "completed");
    assert.equal(session.todos[1].content, "Run tool bash");
    assert.equal(session.contextBudget.tokens_used, 18);
    assert.match(session.diff, /hello\.txt/);
  });
});

test("cancel marks the active session as cancelled", () => {
  withWorkspace((workspace) => {
    const store = new SessionStore({ workspaceDir: workspace });
    const { session } = store.begin("thread-3", { model: "pi-model", prompt: "Cancel me" });
    const cancelled = store.cancel("thread-3");

    assert.equal(cancelled.sessionId, session.sessionId);
    assert.equal(cancelled.status, "cancelled");
    assert.equal(cancelled.todos[0].status, "cancelled");
  });
});