# A2A Communication Best Practices

## When to Apply

Use this skill when invoking peer agents via A2A (agent-to-agent) communication or when receiving A2A invocations from other agents.

## Core Principles

### 1. A2A is Stateless
- Peer agents do NOT remember previous conversations.
- Every A2A invocation is a fresh session with no prior context.
- You must include ALL necessary context in each message.

### 2. Include Full Context
When invoking a peer agent, always provide:
- **Task scope**: What exactly needs to be done
- **File paths**: Relevant files to read/modify
- **Error messages**: Full error text if debugging
- **Environment**: Namespace, pod name, relevant env vars
- **Constraints**: Time limits, resource limits, forbidden actions

### 3. Choose the Right Agent

| Agent | Purpose | When to Invoke |
|-------|---------|----------------|
| @seeker | Code exploration, search | Finding files, understanding codebase structure |
| @kimiiaz | General coding tasks | Implementation, debugging, refactoring |
| @reviewer | Code review | After completing changes, before merging |
| @tester | Test writing | When tests are needed or failing |

### 4. Message Format

```
@agentname TASK_TYPE: Brief description

Context:
- File: path/to/file.py (relevant lines: 45-67)
- Error: <full error message>
- Goal: <what success looks like>

Constraints:
- Do not modify X
- Must maintain backward compatibility with Y
```

### 5. Handling Failures

If an A2A call fails:
1. Record the failure in your todowrite plan
2. Try once more with clearer instructions
3. If it fails again, proceed with fallback or escalate to user
4. Never silently ignore A2A failures

### 6. Receiving A2A Calls

When you receive an A2A invocation:
1. Read the context carefully
2. Check if you have the required tools/capabilities
3. If missing context, ask for it explicitly in your response
4. Complete the task fully before responding
5. Include verification evidence in your response

## Session Continuity for A2A

Since A2A is stateless, use these techniques for continuity:
- **Memory tool**: Save shared context to memory with shared key
- **Thread IDs**: Use consistent thread IDs for related tasks
- **Artifacts**: Reference file paths that both agents can access

## Anti-Patterns

- Don't send vague requests like "@seeker help me" — be specific.
- Don't assume the peer knows your project structure.
- Don't send multi-part tasks in one message — break them down.
- Don't ignore peer responses — review them before proceeding.
