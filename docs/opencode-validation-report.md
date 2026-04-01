# OpenCode Source Validation Report

**Date:** Cross-validation of `simulation.md` execution trace against actual OpenCode source  
**OpenCode commit:** `0bbf26a1ce54dc7fb79e2cb098ed593787f20125` (dev branch, github.com/anomalyco/opencode.git)  
**kubesynth:** Current working tree with fixes applied  

---

## Executive Summary

Cross-validated all 16 problems from `simulation.md` against the actual OpenCode TypeScript source code and the kubesynth codebase. Found:

- **1 critical bug** (compaction completely broken — fixed)
- **2 medium bugs** (pre_authorized_actions dead code, loop step missing cancel — fixed)
- **4 simulation claims that are WRONG** for the OpenCode runtime
- **3 simulation claims that are ALREADY FIXED** in prior sessions
- **8 claims that are VALID** (varying severity)

All 3 bugs have been fixed and all tests pass (214 opencode-runtime, 103 operator).

**Session 2 update:** Deep cross-validation against OpenCode TypeScript source found **4 additional bugs**:

- **1 medium bug** (token calculation missing `cache.write` — fixed)
- **1 medium bug** (session recovery creates orphaned sessions — fixed)
- **1 medium bug** (structured output format lost on retry — fixed)
- **1 medium bug** (proactive compaction ordering blocks completed tasks — fixed)

All fixes pass tests (225 opencode-runtime, 103 operator).

---

## Critical Bug Found & Fixed

### `summarize_session()` sends no JSON body → compaction NEVER works

**Source evidence:** OpenCode's `POST /session/:id/summarize` endpoint validates request body with Zod:

```typescript
// packages/opencode/src/server/routes/session.ts
z.object({
  providerID: ProviderID.zod,
  modelID: ModelID.zod,
  auto: z.boolean().optional().default(false),
})
```

**The bug:** `opencode-runtime/main.py` was calling:
```python
hclient.post(f"/session/{session_id}/summarize")  # NO body
```

**Impact:** Every compaction attempt returned HTTP 400 (Zod validation error), silently caught by the `except httpx.HTTPError` handler. This means:
- Context overflow recovery **never worked**
- Long autonomous loops would hit context limits and fail without recovery
- The `detect_completion_status() == "context_overflow"` branch was dead code in practice

**Fix applied:** `summarize_session()` now sends `json={"providerID": ..., "modelID": ..., "auto": True}`, extracting provider/model from the `model_ref` parameter passed by callers.

---

## Medium Bugs Found & Fixed

### `pre_authorized_actions` silently dropped by Pydantic

**The bug:** `operator/worker.py` sends `"pre_authorized_actions": [...]` in the invoke payload, but `InvokeRequest` (Pydantic BaseModel) had no such field → Pydantic silently drops unknown fields.

**Fix:** Added `pre_authorized_actions: list[str] = Field(default_factory=list)` to `InvokeRequest` and wired it into the system prompt so the agent knows which actions are pre-approved.

### Loop step exception handler doesn't cancel agent session

**The bug:** `execute_step()` calls `cancel_agent_session()` on error, but `execute_loop_step()` didn't — leaving orphaned agent sessions running after timeout/failure.

**Fix:** Added `cancel_agent_session(agent_ref, TARGET_NAMESPACE, thread_id)` in the loop step exception handler.

---

## Problem-by-Problem Validation

### Problem 1: Shallow Clone Blocks Push — **VALID**
The git MCP sidecar's `git_clone()` does `--depth 1` then `git fetch --unshallow`. If unshallow fails, the repo stays shallow. This is a sidecar issue, not an OpenCode issue. **No change to OpenCode-related code needed.**

### Problem 2: git push Blocked by Destructive Gate — **WRONG for OpenCode**
The simulation conflates the agent-runtime (LangGraph) with opencode-runtime. OpenCode's permission system is completely different:

```typescript
// packages/opencode/src/permission/index.ts
export function fromConfig(config: Permission): Resolved[] {
  if (config === "allow") return [{ permission: "*", action: "allow", pattern: "*" }]
}
```

When `opencode-runtime/main.py` sets `"permission": "allow"` in the OpenCode config, **ALL bash commands including `git push` are auto-allowed**. There is no destructive action gate in OpenCode. The `DESTRUCTIVE_SHELL_COMMANDS` frozenset is in `agent-runtime/agent_logic.py` (LangGraph runtime only).

### Problem 3: No git push via MCP in OpenCode — **PARTIALLY WRONG**
The simulation says OpenCode has "no git push capability". This is incorrect:
1. `configure_git_credentials()` in `opencode-runtime/main.py` reads `GIT_TOKEN`, `GIT_USERNAME`, `GIT_PASSWORD` env vars and writes `~/.git-credentials`
2. The operator injects these env vars into the main agent container at `operator/main.py` line 1826: `env.extend(git_agent_env)`
3. With `permission: "allow"`, bash `git push` works with full auth

**However:** The OpenCode runtime does correctly skip the GitHub MCP adapter (the adapter exposes HTTP, not native `/mcp`). Git operations go through bash, which is fine when credentials are configured.

### Problem 4: Context Overflow During Large Scaffold — **VALID (was critical, now fixed)**
The context overflow path was completely broken because `summarize_session()` sent no body → 400 error → compaction never happened. **Now fixed.** The compaction recovery prompt and todowrite plan approach are sound once compaction actually works.

OpenCode's actual compaction logic (`session/compaction.ts`) is sophisticated:
- `isOverflow()` checks token count against `model.limit.input - reserved`
- `prune()` walks backward through parts, protecting the last 40K tokens of tool calls, erasing older tool output
- `PRUNE_PROTECTED_TOOLS = ["skill"]` protects skill tool calls from pruning

### Problem 5: previous_output Truncation — **VALID (low severity)**
The `previous_response[:2000]` truncation in `build_loop_iteration_prompt()` is intentional. OpenCode's structured output already produces JSON summaries rather than raw terminal dumps, mitigating this.

### Problem 6: Verification Gate on Noisy Test Output — **VALID (improved by prior work)**
Previous sessions enhanced the verification prompts with goal-backward framing. Still a valid concern for very noisy outputs.

### Problem 7: No Git Credentials in Agent Container — **ALREADY FIXED**
The simulation says credentials only go to the git sidecar. This was true but has been fixed:
- `operator/main.py` lines 1754–1780: Builds `git_agent_env` list with `GIT_REPO_URL`, `GIT_AUTH_METHOD`, `GIT_TOKEN`/`GIT_USERNAME`/`GIT_PASSWORD`
- Line 1826: `if git_config.get("repoUrl") and git_agent_env: env.extend(git_agent_env)`
- `opencode-runtime/main.py`: `configure_git_credentials()` reads these and writes `~/.git-credentials`

### Problem 8: Race Condition in Parallel Steps — **VALID (by design)**
Parallel steps share a workspace PVC. This is a known limitation, not specific to OpenCode.

### Problem 9: git_commit Only Stages Tracked Files — **NOT APPLICABLE to OpenCode**
`execute_git_commit()` is in `agent-runtime/agent_logic.py` (LangGraph runtime). OpenCode agents use bash `git add` and `git commit` directly — the agent decides what to stage.

### Problem 10: Timeout Doesn't Cancel OpenCode Session — **PARTIALLY FIXED**
- `cancel_agent_session()` already calls `abort_session()` via the OpenCode `/session/:id/abort` endpoint
- `execute_step()` already calls `cancel_agent_session()` on timeout
- **Fix this session:** Added `cancel_agent_session()` to `execute_loop_step()` exception handler too

OpenCode's actual abort mechanism (`session/status.ts`):
```typescript
export function abort(sessionID: SessionID) {
  const controller = controllers.get(sessionID)
  if (controller) controller.abort()
}
```
This aborts the AI SDK's streaming call, which stops the LLM mid-response.

### Problem 11: Session Isolation Between Steps — **VALID (by design)**
Each step gets a unique `thread_id`. The `?directory=` parameter ensures all sessions work in the same filesystem directory. OpenCode's server middleware processes this:

```typescript
// packages/opencode/src/server/server.ts (middleware)
const raw = c.req.query("directory") || c.req.header("x-opencode-directory") || process.cwd()
return Instance.provide({ directory: Filesystem.resolve(raw) }, ...)
```

So all sessions share the same working directory — file persistence across steps works correctly via the shared workspace PVC.

### Problem 12: Retry Amplification — **VALID (low severity)**
Thread IDs include the step name, so retries create new sessions. The working directory is shared though, so files from attempt 1 persist for attempt 2.

### Problem 13: continueOnError Kills Workflow — **VALID (configurable)**
Already configurable via `execution.continueOnError` in the CRD.

### Problem 14: Artifact Loss on Pod Kill — **VALID (already handled)**
Atomic write with `temp_path.replace(path)` handles this on Linux.

### Problem 15: System Prompt Exceeds Token Limits — **VALID (low severity)**
OpenCode handles this gracefully — its `SystemPrompt` module has token-aware truncation.

### Problem 16: Agent Uses bash Instead of Git MCP — **VALID (by design for OpenCode)**
For OpenCode agents, bash git operations with `permission: "allow"` and configured credentials is the intended path. The pre_authorized_actions wiring (fixed this session) provides additional prompt guidance.

---

## OpenCode API Contract Summary

Verified from source code at `packages/opencode/src/server/routes/session.ts`:

| Endpoint | Method | Body Required | Verified |
|---|---|---|---|
| `/session` | POST | `{title?, parentID?, permission?, workspaceID?}` | ✅ Runtime sends correct body |
| `/session/:id/message` | POST | `{parts: [{type, text}], model?, agent?, system?, format?}` | ✅ Runtime sends correct body |
| `/session/:id/summarize` | POST | `{providerID, modelID, auto?}` | ✅ **Fixed this session** |
| `/session/:id/init` | POST | `{providerID, modelID, messageID}` | ✅ Runtime sends correct body |
| `/session/:id/abort` | POST | none | ✅ Runtime sends no body |
| `/session/status` | GET | n/a | ✅ Runtime polls correctly |
| `/session/:id/message` | GET | n/a | ✅ Runtime reads correctly |
| `/session/:id/todo` | GET | n/a | ✅ Runtime reads correctly |
| `/global/health` | GET | n/a | ✅ Runtime checks correctly |

**`?directory=` query parameter:** Confirmed used by middleware in `server.ts` line ~196. The runtime's `params={"directory": working_directory}` IS correct — not dead code.

---

## Files Modified This Session

| File | Change | Impact |
|---|---|---|
| `opencode-runtime/main.py` | `summarize_session()` now sends JSON body with providerID/modelID/auto | **Critical** — compaction actually works now |
| `opencode-runtime/main.py` | Added `pre_authorized_actions` field to `InvokeRequest` | Medium — worker's pre-auth list reaches the agent |
| `opencode-runtime/main.py` | Pre-authorized actions injected into system prompt | Medium — agent knows what's pre-approved |
| `operator/worker.py` | Added `cancel_agent_session()` in loop step exception handler | Medium — no orphaned sessions on loop failure |
| `opencode-runtime/tests/test_main.py` | Updated SummarizeSessionTests to validate JSON body | Test fix |

---

## Test Results

- **opencode-runtime:** 225 passed, 0 failed, 10 skipped
- **operator:** 103 passed, 0 failed, 0 skipped

---

## Session 2: Deep Cross-Validation Findings

### Bug A: Token calculation missing `cache.write` — **FIXED (Medium)**

**Source evidence:** OpenCode calculates total tokens in `packages/opencode/src/session/compaction.ts`:
```typescript
// lines 33-51: isOverflow()
const total = tokens.total || (tokens.input + tokens.output + tokens.cache.read + tokens.cache.write)
```

**The bug:** `check_context_overflow()` and `compute_context_budget()` computed fallback total as:
```python
total = (tokens.get("input") or 0) + (tokens.get("output") or 0) + (cache.get("read") or 0)
# MISSING: cache.get("write") or 0
```

**Impact:** Underestimates token usage by the size of the write cache. Proactive compaction threshold may not trigger in time, leading to unexpected ContextOverflowErrors.

**Fix:** Added `+ (cache.get("write") or 0)` to both functions.

### Bug B: Session recovery on 404 doesn't update registry — **FIXED (Medium)**

**The bug:** `_send_prompt_with_session_recovery()` creates a new session on 404 but calls:
```python
SESSION_REGISTRY.get_or_set(logical_thread_id, session_id)
```
`get_or_set()` returns the EXISTING (dead) session if the thread_id already has an entry, discarding the newly-created session. The return value wasn't even assigned back to `session_id`.

**Impact:** After a 404 recovery, the registry permanently points to the dead session. Every subsequent invoke with that thread_id creates another orphaned session on the OpenCode server.

**Fix:** Changed to `SESSION_REGISTRY.set(logical_thread_id, session_id)` to forcefully update the registry after confirmed 404 recovery.

### Bug C: Structured output format not resent on retry — **FIXED (Medium)**

**Source evidence:** OpenCode's prompt loop reads `lastUser.format` to decide whether to inject the StructuredOutput tool:
```typescript
// packages/opencode/src/session/prompt.ts
if (lastUser.format?.type === "json_schema") {
  tools["StructuredOutput"] = createStructuredOutputTool({ schema: lastUser.format.schema, ... })
}
```

**The bug:** The runtime only sent `prompt_format` on the first turn:
```python
prompt_format=prompt_format if turn == 0 else None
```
When a StructuredOutputError triggered a retry (turn > 0), the format was absent. OpenCode wouldn't inject the StructuredOutput tool on the retry user message.

**Impact:** Structured output retries always fail because the StructuredOutput tool is not available to the model on retry turns.

**Fix:** Added `_resend_format` flag set to `True` on StructuredOutputError recovery, included in the format condition: `prompt_format if (turn == 0 or _resend_format) else None`, reset to `False` after each successful send.

### Bug D: Proactive compaction blocks completed tasks — **FIXED (Medium)**

**The bug:** In the autonomous loop, the proactive compaction check ran BEFORE the `completion == "completed"` exit:
```python
# Token-based proactive compaction (runs for ALL responses including completed ones)
if _can_compact and check_context_overflow(payload):
    ...
    continue  # <-- skips the "completed" break below!

if completion == "completed":
    break  # <-- never reached when tokens are high
```

**Impact:** When the model completes a task (finish: "stop") but token usage is above the compaction threshold, the loop triggers unnecessary compaction and sends a continuation prompt like "Context was proactively compacted... continue from next step." This confuses the model into doing more work on an already-finished task.

**Fix:** Moved `if completion == "completed": break` above the proactive compaction check. Proactive compaction now only triggers for incomplete responses.

### Validated (Not Bugs)

- **Summarize endpoint is synchronous:** `POST /session/:id/summarize` awaits the full compaction loop before returning HTTP 200. The runtime's `wait_for_session_idle()` after summarize is redundant but harmless.
- **`?directory=` query param:** Correctly used by OpenCode's middleware to set `Instance.directory`.
- **`system` field on messages:** Correctly consumed by OpenCode's LLM module (`llm.ts` line 77: `...(input.user.system ? [input.user.system] : [])`).
- **Session.create:** Uses `Instance.directory` from middleware, not request body. Runtime's `params={"directory": working_directory}` approach is correct.
- **Abort endpoint:** `POST /session/:id/abort` calls `SessionPrompt.cancel(sessionID)` and returns boolean. Runtime matches.
- **Init endpoint:** `POST /session/:id/init` expects `{providerID, modelID, messageID}` (sessionID from path). Runtime matches.
- **Session status:** `GET /session/status` returns `Record<string, {type: "idle"|"busy"|"retry"}>`. Runtime correctly looks up by session_id.
- **Thread IDs:** Built with `slugify_identifier` (`[a-zA-Z0-9_-]+`), safe for URL query params without encoding.
