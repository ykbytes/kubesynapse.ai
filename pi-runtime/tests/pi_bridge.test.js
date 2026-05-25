const assert = require("node:assert/strict");
const test = require("node:test");

const { buildErrorPayload, handleRequest, jsonError } = require("../pi_bridge");

function createMockResponse() {
  const headers = new Map();
  let statusCode = null;
  let body = "";

  return {
    destroyed: false,
    headersSent: false,
    setHeader(name, value) {
      headers.set(String(name).toLowerCase(), value);
    },
    getHeader(name) {
      return headers.get(String(name).toLowerCase());
    },
    writeHead(nextStatusCode, nextHeaders = {}) {
      statusCode = nextStatusCode;
      this.headersSent = true;
      for (const [name, value] of Object.entries(nextHeaders)) {
        headers.set(String(name).toLowerCase(), value);
      }
    },
    end(chunk = "") {
      if (chunk) {
        body += chunk;
      }
    },
    get statusCode() {
      return statusCode;
    },
    get body() {
      return body;
    },
  };
}

test("jsonError emits the canonical nested error envelope", () => {
  const res = createMockResponse();
  res.setHeader("x-request-id", "trace-pi-1");

  jsonError(res, 400, "prompt is required");

  const payload = JSON.parse(res.body);
  assert.equal(res.statusCode, 400);
  assert.deepEqual(payload, buildErrorPayload(400, "prompt is required", { traceId: "trace-pi-1" }));
});

test("cancel route returns canonical error envelope when thread_id is missing", async () => {
  const req = {
    url: "/cancel",
    method: "POST",
    headers: {
      host: "127.0.0.1:8080",
      "x-request-id": "trace-pi-2",
    },
  };
  const res = createMockResponse();

  await handleRequest(req, res);

  const payload = JSON.parse(res.body);
  assert.equal(res.statusCode, 400);
  assert.equal(payload.error.code, "invalid_request");
  assert.equal(payload.error.message, "thread_id query parameter is required");
  assert.equal(payload.error.trace_id, "trace-pi-2");
});