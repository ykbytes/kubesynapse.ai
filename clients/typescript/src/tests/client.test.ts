import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { KubeSynapseClient } from "../client.js";

type MockFetch = typeof fetch;

const originalFetch = globalThis.fetch;

afterEach(() => {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
    return;
  }
  delete (globalThis as { fetch?: typeof fetch }).fetch;
});

function installFetchMock(handler: MockFetch): void {
  globalThis.fetch = handler;
}

function jsonResponse(body: unknown, status: number = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

test("listExecutions and listTraces use the execution list route", async () => {
  const calls: Array<{ url: URL; headers: Record<string, string> | undefined }> = [];
  const payload = {
    items: [{ id: "exec-1", workflow_name: "observatory-demo" }],
    limit: 25,
    offset: 5,
  };

  installFetchMock(async (input, init) => {
    calls.push({
      url: new URL(String(input)),
      headers: init?.headers as Record<string, string> | undefined,
    });
    return jsonResponse(payload);
  });

  const client = new KubeSynapseClient("http://gateway.example", {
    token: "test-token",
    timeout: 1000,
  });

  const canonical = await client.listExecutions("observatory-demo", 25, 5);
  const compatibility = await client.listTraces("observatory-demo", 25, 5);

  assert.deepEqual(canonical, payload);
  assert.deepEqual(compatibility, payload);
  assert.equal(calls.length, 2);

  for (const call of calls) {
    assert.equal(call.url.pathname, "/api/v1/traces/executions");
    assert.equal(call.url.searchParams.get("workflow_name"), "observatory-demo");
    assert.equal(call.url.searchParams.get("limit"), "25");
    assert.equal(call.url.searchParams.get("offset"), "5");
    assert.equal(call.headers?.Authorization, "Bearer test-token");
  }
});

test("getExecution and getTrace use the execution detail route", async () => {
  const calls: URL[] = [];
  const payload = {
    id: "exec-42",
    namespace: "default",
    workflow_name: "observatory-demo",
    agent_name: "observatory-demo",
    run_id: "wf-run-42",
    status: "completed",
    started_at: null,
    completed_at: null,
    duration_ms: null,
    input_summary: null,
    output_summary: null,
    total_steps: 0,
    completed_steps: 0,
    failed_steps: 0,
    total_llm_calls: 0,
    total_tool_calls: 0,
    total_tokens: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    estimated_cost_usd: null,
    triggered_by: null,
    error_message: null,
    trace_file_path: null,
    steps: [],
    llm_calls: [],
    tool_calls: [],
    events: [],
  };

  installFetchMock(async (input) => {
    calls.push(new URL(String(input)));
    return jsonResponse(payload);
  });

  const client = new KubeSynapseClient("http://gateway.example");

  const canonical = await client.getExecution("exec-42");
  const compatibility = await client.getTrace("exec-42");

  assert.deepEqual(canonical, payload);
  assert.deepEqual(compatibility, payload);
  assert.deepEqual(
    calls.map((call) => call.pathname),
    ["/api/v1/traces/executions/exec-42", "/api/v1/traces/executions/exec-42"],
  );
});