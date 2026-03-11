import { fetchEventSource } from "@microsoft/fetch-event-source";

import type {
  AgentInfo,
  AgentDetail,
  AgentLogsResponse,
  ApprovalInfo,
  CreateAgentPayload,
  DeleteResponse,
  EvalInfo,
  EvalPayload,
  EvalTestCase,
  EvalUpdatePayload,
  GatewayHealth,
  InvocationSummary,
  InvokePayload,
  InvokeResponse,
  PolicyInfo,
  RuntimeKind,
  StreamEvent,
  UpdateAgentPayload,
  WorkflowInfo,
  WorkflowPayload,
  WorkflowStep,
  WorkflowUpdatePayload,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
type JsonRecord = Record<string, unknown>;

function buildUrl(path: string, namespace?: string): string {
  const baseUrl = API_BASE_URL || window.location.origin;
  const url = new URL(path, baseUrl);
  if (namespace) {
    url.searchParams.set("namespace", namespace);
  }
  return API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
}

function buildHeaders(token?: string, requestId?: string): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (requestId) {
    headers["X-Request-Id"] = requestId;
  }
  return headers;
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function expectRecord(value: unknown, label: string): JsonRecord {
  if (!isRecord(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value;
}

function readString(record: JsonRecord, key: string, label: string, fallback?: string): string {
  const value = record[key];
  if (value === undefined && fallback !== undefined) {
    return fallback;
  }
  if (typeof value !== "string") {
    throw new Error(`${label}.${key} must be a string.`);
  }
  return value;
}

function readOptionalString(record: JsonRecord, key: string, label: string): string | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new Error(`${label}.${key} must be a string when present.`);
  }
  return value;
}

function readBoolean(record: JsonRecord, key: string, label: string, fallback?: boolean): boolean {
  const value = record[key];
  if (value === undefined && fallback !== undefined) {
    return fallback;
  }
  if (typeof value !== "boolean") {
    throw new Error(`${label}.${key} must be a boolean.`);
  }
  return value;
}

function readOptionalBoolean(record: JsonRecord, key: string, label: string): boolean | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "boolean") {
    throw new Error(`${label}.${key} must be a boolean when present.`);
  }
  return value;
}

function readOptionalNumber(record: JsonRecord, key: string, label: string): number | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label}.${key} must be a finite number when present.`);
  }
  return value;
}

function readStringArrayValue(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array.`);
  }
  return value.map((item, index) => {
    if (typeof item !== "string") {
      throw new Error(`${label}[${index}] must be a string.`);
    }
    return item;
  });
}

function readStringArray(record: JsonRecord, key: string, label: string, fallback: string[] = []): string[] {
  const value = record[key];
  if (value === undefined) {
    return fallback;
  }
  return readStringArrayValue(value, `${label}.${key}`);
}

function readRecordArray(record: JsonRecord, key: string, label: string): JsonRecord[] {
  const value = record[key];
  if (!Array.isArray(value)) {
    throw new Error(`${label}.${key} must be an array.`);
  }
  return value.map((item, index) => expectRecord(item, `${label}.${key}[${index}]`));
}

function readOptionalRecord(record: JsonRecord, key: string, label: string): JsonRecord | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  return expectRecord(value, `${label}.${key}`);
}

function readRecord(record: JsonRecord, key: string, label: string, fallback: JsonRecord = {}): JsonRecord {
  const value = record[key];
  if (value === undefined) {
    return fallback;
  }
  return expectRecord(value, `${label}.${key}`);
}

function readRuntimeKind(record: JsonRecord, key: string, label: string, fallback?: RuntimeKind): RuntimeKind {
  const value = record[key];
  const runtimeKind = value === undefined && fallback !== undefined ? fallback : value;
  if (runtimeKind !== "langgraph" && runtimeKind !== "goose") {
    throw new Error(`${label}.${key} must be 'langgraph' or 'goose'.`);
  }
  return runtimeKind;
}

function parseAgentInfoPayload(payload: unknown, label = "AgentInfo"): AgentInfo {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    model: readString(record, "model", label),
    namespace: readString(record, "namespace", label),
    status: readString(record, "status", label),
    runtime_kind: record.runtime_kind === undefined ? undefined : readRuntimeKind(record, "runtime_kind", label),
  };
}

function parseAgentDetailPayload(payload: unknown): AgentDetail {
  const base = parseAgentInfoPayload(payload, "AgentDetail");
  const record = expectRecord(payload, "AgentDetail");
  return {
    ...base,
    system_prompt: readString(record, "system_prompt", "AgentDetail", ""),
    policy_ref: readOptionalString(record, "policy_ref", "AgentDetail"),
    storage_size: readOptionalString(record, "storage_size", "AgentDetail"),
    runtime_kind: readRuntimeKind(record, "runtime_kind", "AgentDetail", "langgraph"),
    enable_gvisor: readBoolean(record, "enable_gvisor", "AgentDetail", false),
    mcp_servers: readStringArray(record, "mcp_servers", "AgentDetail"),
    mcp_sidecars: readRecordArray(record, "mcp_sidecars", "AgentDetail"),
    goose_config_files: readRecord(record, "goose_config_files", "AgentDetail"),
    created_at: readOptionalString(record, "created_at", "AgentDetail"),
  };
}

function parsePolicyInfoPayload(payload: unknown, label = "PolicyInfo"): PolicyInfo {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
  };
}

function parseGatewayHealthPayload(payload: unknown): GatewayHealth {
  const record = expectRecord(payload, "GatewayHealth");
  return {
    status: readString(record, "status", "GatewayHealth"),
    gateway: readString(record, "gateway", "GatewayHealth"),
    auth_mode: readString(record, "auth_mode", "GatewayHealth"),
    nats_url: readString(record, "nats_url", "GatewayHealth"),
    qdrant_url: readString(record, "qdrant_url", "GatewayHealth"),
  };
}

function parseApprovalInfoPayload(payload: unknown): ApprovalInfo {
  const record = expectRecord(payload, "ApprovalInfo");
  return {
    name: readString(record, "name", "ApprovalInfo"),
    namespace: readString(record, "namespace", "ApprovalInfo"),
    decision: readString(record, "decision", "ApprovalInfo"),
    agent_name: readString(record, "agent_name", "ApprovalInfo"),
    action: readString(record, "action", "ApprovalInfo"),
    requested_at: readOptionalString(record, "requested_at", "ApprovalInfo"),
    decided_by: readOptionalString(record, "decided_by", "ApprovalInfo"),
    decided_at: readOptionalString(record, "decided_at", "ApprovalInfo"),
    reason: readOptionalString(record, "reason", "ApprovalInfo"),
  };
}

function parseWorkflowStepPayload(payload: unknown, label = "WorkflowStep"): WorkflowStep {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    agent_ref: readString(record, "agent_ref", label),
    prompt: readString(record, "prompt", label, ""),
    depends_on: readStringArray(record, "depends_on", label),
    require_approval: readBoolean(record, "require_approval", label, false),
  };
}

function parseWorkflowInfoPayload(payload: unknown, label = "WorkflowInfo"): WorkflowInfo {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
    description: readString(record, "description", label, ""),
    input: readString(record, "input", label, ""),
    message_bus: readString(record, "message_bus", label, "in-memory"),
    steps: (record.steps === undefined ? [] : readRecordArray(record, "steps", label)).map((item, index) =>
      parseWorkflowStepPayload(item, `${label}.steps[${index}]`)
    ),
    phase: readString(record, "phase", label, "pending"),
    current_step: readString(record, "current_step", label, ""),
    observed_generation: readOptionalNumber(record, "observed_generation", label),
    summary: readOptionalRecord(record, "summary", label),
    artifact_ref: readOptionalRecord(record, "artifact_ref", label),
    pending_approval: readOptionalRecord(record, "pending_approval", label),
    worker_job: readOptionalRecord(record, "worker_job", label),
    created_at: readOptionalString(record, "created_at", label),
  };
}

function parseEvalTestCasePayload(payload: unknown, label = "EvalTestCase"): EvalTestCase {
  const record = expectRecord(payload, label);
  return {
    input: readString(record, "input", label),
    expected_output: readString(record, "expected_output", label, ""),
    metrics: readStringArray(record, "metrics", label),
  };
}

function parseEvalInfoPayload(payload: unknown, label = "EvalInfo"): EvalInfo {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
    agent_ref: readString(record, "agent_ref", label),
    schedule: readOptionalString(record, "schedule", label),
    test_suite: (record.test_suite === undefined ? [] : readRecordArray(record, "test_suite", label)).map((item, index) =>
      parseEvalTestCasePayload(item, `${label}.test_suite[${index}]`)
    ),
    failure_threshold: readRecord(record, "failure_threshold", label),
    phase: readString(record, "phase", label, "pending"),
    passed: readOptionalBoolean(record, "passed", label),
    last_run: readOptionalString(record, "last_run", label),
    observed_generation: readOptionalNumber(record, "observed_generation", label),
    summary: readOptionalRecord(record, "summary", label),
    artifact_ref: readOptionalRecord(record, "artifact_ref", label),
    worker_job: readOptionalRecord(record, "worker_job", label),
    created_at: readOptionalString(record, "created_at", label),
  };
}

function parseDeleteResponsePayload(payload: unknown): DeleteResponse {
  const record = expectRecord(payload, "DeleteResponse");
  return {
    status: readString(record, "status", "DeleteResponse"),
    kind: readString(record, "kind", "DeleteResponse"),
    name: readString(record, "name", "DeleteResponse"),
    namespace: readString(record, "namespace", "DeleteResponse"),
  };
}

function parseAgentLogsResponsePayload(payload: unknown): AgentLogsResponse {
  const record = expectRecord(payload, "AgentLogsResponse");
  return {
    agent_name: readString(record, "agent_name", "AgentLogsResponse"),
    logs: readString(record, "logs", "AgentLogsResponse", ""),
  };
}

function parseInvokeResponsePayload(payload: unknown): InvokeResponse {
  const record = expectRecord(payload, "InvokeResponse");
  return {
    agent_name: readString(record, "agent_name", "InvokeResponse"),
    response: readString(record, "response", "InvokeResponse", ""),
    thread_id: readString(record, "thread_id", "InvokeResponse"),
    model: readString(record, "model", "InvokeResponse"),
    policy_name: readOptionalString(record, "policy_name", "InvokeResponse"),
    tool_name: readOptionalString(record, "tool_name", "InvokeResponse"),
    tool_result: readOptionalRecord(record, "tool_result", "InvokeResponse"),
    sandbox_session: readOptionalRecord(record, "sandbox_session", "InvokeResponse"),
    status: readString(record, "status", "InvokeResponse", "completed"),
    approval_name: readOptionalString(record, "approval_name", "InvokeResponse"),
    retry_after_seconds: readOptionalNumber(record, "retry_after_seconds", "InvokeResponse"),
    warnings: record.warnings === undefined ? [] : readStringArray(record, "warnings", "InvokeResponse"),
  };
}

function parseStreamPayload(data: string): JsonRecord {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    throw new Error("Streaming event payload was not valid JSON.");
  }
  return expectRecord(parsed, "Streaming event payload");
}

export function buildInvocationSummary(fallbackThreadId: string, payload: unknown): InvocationSummary {
  const record = expectRecord(payload, "Invocation summary payload");
  const threadId = readOptionalString(record, "thread_id", "Invocation summary payload") ?? fallbackThreadId.trim();
  if (!threadId) {
    throw new Error("Invocation summary payload is missing thread_id.");
  }

  return {
    threadId,
    status: readString(record, "status", "Invocation summary payload", "completed"),
    policyName: readOptionalString(record, "policy_name", "Invocation summary payload"),
    toolName: readOptionalString(record, "tool_name", "Invocation summary payload"),
    toolResult: readOptionalRecord(record, "tool_result", "Invocation summary payload"),
    sandboxSession: readOptionalRecord(record, "sandbox_session", "Invocation summary payload"),
    approvalName: readOptionalString(record, "approval_name", "Invocation summary payload"),
    retryAfterSeconds: readOptionalNumber(record, "retry_after_seconds", "Invocation summary payload"),
    warnings: record.warnings === undefined ? [] : readStringArray(record, "warnings", "Invocation summary payload"),
  };
}

async function parseJsonResponse<T>(response: Response, parser: (payload: unknown) => T): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    if (text) {
      let detail = "";
      try {
        const parsed = JSON.parse(text) as { detail?: string };
        detail = parsed.detail ?? "";
      } catch {
        detail = "";
      }
      throw new Error(detail || text);
    }
    throw new Error(`Request failed with status ${response.status}`);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("Response body was not valid JSON.");
  }

  return parser(payload);
}

export async function fetchGatewayHealth(): Promise<GatewayHealth> {
  const response = await fetch(buildUrl("/api/health"));
  return parseJsonResponse(response, parseGatewayHealthPayload);
}

export async function listAgents(token: string, namespace: string): Promise<AgentInfo[]> {
  const response = await fetch(buildUrl("/api/agents", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Agent list response must be an array.");
    }
    return payload.map((item, index) => parseAgentInfoPayload(item, `AgentInfo[${index}]`));
  });
}

export async function listPolicies(token: string, namespace: string): Promise<PolicyInfo[]> {
  const response = await fetch(buildUrl("/api/policies", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Policy list response must be an array.");
    }
    return payload.map((item, index) => parsePolicyInfoPayload(item ?? {}, `PolicyInfo[${index}]`));
  });
}

export async function createAgent(
  token: string,
  namespace: string,
  payload: CreateAgentPayload,
): Promise<AgentDetail> {
  const response = await fetch(buildUrl("/api/agents", namespace), {
    method: "POST",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseAgentDetailPayload);
}

export async function fetchAgent(token: string, namespace: string, agentName: string): Promise<AgentDetail> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}`, namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, parseAgentDetailPayload);
}

export async function updateAgent(
  token: string,
  namespace: string,
  agentName: string,
  payload: UpdateAgentPayload,
): Promise<AgentDetail> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}`, namespace), {
    method: "PATCH",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseAgentDetailPayload);
}

export async function deleteAgent(token: string, namespace: string, agentName: string): Promise<DeleteResponse> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}`, namespace), {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export async function invokeAgent(
  token: string,
  namespace: string,
  agentName: string,
  payload: InvokePayload,
  requestId: string,
): Promise<InvokeResponse> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}/invoke`, namespace), {
    method: "POST",
    headers: {
      ...buildHeaders(token, requestId),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseInvokeResponsePayload);
}

export async function fetchAgentLogs(
  token: string,
  namespace: string,
  agentName: string,
): Promise<AgentLogsResponse> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}/logs`, namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, parseAgentLogsResponsePayload);
}

export async function decideApproval(
  token: string,
  namespace: string,
  approvalName: string,
  decision: "approved" | "denied",
  reason?: string,
): Promise<ApprovalInfo> {
  const response = await fetch(buildUrl(`/api/approvals/${approvalName}`, namespace), {
    method: "PATCH",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      decision,
      reason: reason?.trim() || undefined,
    }),
  });
  return parseJsonResponse(response, parseApprovalInfoPayload);
}

export async function listWorkflows(token: string, namespace: string): Promise<WorkflowInfo[]> {
  const response = await fetch(buildUrl("/api/workflows", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Workflow list response must be an array.");
    }
    return payload.map((item, index) => parseWorkflowInfoPayload(item ?? {}, `WorkflowInfo[${index}]`));
  });
}

export async function createWorkflow(
  token: string,
  namespace: string,
  payload: WorkflowPayload,
): Promise<WorkflowInfo> {
  const response = await fetch(buildUrl("/api/workflows", namespace), {
    method: "POST",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function updateWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
  payload: WorkflowUpdatePayload,
): Promise<WorkflowInfo> {
  const response = await fetch(buildUrl(`/api/workflows/${workflowName}`, namespace), {
    method: "PATCH",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function deleteWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
): Promise<DeleteResponse> {
  const response = await fetch(buildUrl(`/api/workflows/${workflowName}`, namespace), {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export async function listEvals(token: string, namespace: string): Promise<EvalInfo[]> {
  const response = await fetch(buildUrl("/api/evals", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Eval list response must be an array.");
    }
    return payload.map((item, index) => parseEvalInfoPayload(item ?? {}, `EvalInfo[${index}]`));
  });
}

export async function createEval(token: string, namespace: string, payload: EvalPayload): Promise<EvalInfo> {
  const response = await fetch(buildUrl("/api/evals", namespace), {
    method: "POST",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseEvalInfoPayload);
}

export async function updateEval(
  token: string,
  namespace: string,
  evalName: string,
  payload: EvalUpdatePayload,
): Promise<EvalInfo> {
  const response = await fetch(buildUrl(`/api/evals/${evalName}`, namespace), {
    method: "PATCH",
    headers: {
      ...buildHeaders(token),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseEvalInfoPayload);
}

export async function deleteEval(token: string, namespace: string, evalName: string): Promise<DeleteResponse> {
  const response = await fetch(buildUrl(`/api/evals/${evalName}`, namespace), {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export interface StreamHandlers {
  signal: AbortSignal;
  token: string;
  namespace: string;
  agentName: string;
  payload: InvokePayload;
  requestId: string;
  onEvent: (event: StreamEvent) => void;
  onError: (error: Error) => void;
  onClose: () => void;
}

export async function streamAgentInvoke(options: StreamHandlers): Promise<void> {
  await fetchEventSource(buildUrl(`/api/agents/${options.agentName}/invoke/stream`, options.namespace), {
    method: "POST",
    headers: {
      ...buildHeaders(options.token, options.requestId),
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(options.payload),
    signal: options.signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) {
        throw new Error(`Streaming request failed with status ${response.status}`);
      }
    },
    onmessage(message) {
      try {
        const payload = message.data ? parseStreamPayload(message.data) : {};
        const event = typeof message.event === "string" && message.event.trim() ? message.event : "message";
        options.onEvent({ event, payload });
      } catch (error) {
        const nextError = error instanceof Error ? error : new Error(String(error));
        options.onError(nextError);
        throw nextError;
      }
    },
    onerror(error) {
      options.onError(error instanceof Error ? error : new Error(String(error)));
      throw error;
    },
    onclose() {
      options.onClose();
    },
  });
}
