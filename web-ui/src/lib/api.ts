import { fetchEventSource } from "@microsoft/fetch-event-source";

import { SYSTEM_PROMPT_MAX_CHARS } from "./agentPrompt";

import type {
  A2AInvocationMetadata,
  A2APeerRef,
  AdminUser,
  AgentA2AConfig,
  AgentInfo,
  AgentDetail,
  AgentDiscoveryPeer,
  AgentDiscoveryResponse,
  AgentLogsResponse,
  AgentSkillSummary,
  AgentSkillsConfig,
  AuthConfig,
  AuthProviderSummary,
  AuthSession,
  AuthenticatedUser,
  ApprovalInfo,
  CatalogSkill,
  CatalogSkillDetail,
  ConfigField,
  ConnectedProvider,
  CopilotAuthStatus,
  CopilotDeviceFlowResponse,
  CopilotPollResponse,
  CreateUserPayload,
  CustomProviderPayload,
  CreateAgentPayload,
  DeleteResponse,
  ExecutionTrace,
  FactoryMode,
  GatewayHealth,
  GitCredentialInfo,
  GitCredentialRequest,
  GitConfig,
  GitHubConfig,
  GitHubCredentialInfo,
  GitHubCredentialRequest,
  InvocationSummary,
  InvokePayload,
  InvokeResponse,
  LLMCallRecord,
  LLMKeyInfo,
  LLMModelInfo,
  LLMProvider,
  LoopConfig,
  ModelSuggestion,
  McpHubServer,
  McpToolCategory,
  McpRegistryServer,
  McpProfile,
  McpProfileServer,
  McpCategory,
  McpConnection,
  McpConnectionBinding,
  McpConnectionCredentialField,
  McpConnectionOAuth,
  McpConnectionOAuthStart,
  McpConnectionRuntimeHeader,
  McpConnectionRuntimePreview,
  McpConnectionRuntimeSidecar,
  McpConnectionValidation,
  McpConnectionValidationStatus,
  McpStats,
  McpSupportLevel,
  PolicyInfo,
  ProviderCatalogModel,
  PolicyInputGuardrails,
  PolicyMemoryPolicy,
  PolicyOutputGuardrails,
  PolicyToolPolicy,
  RuntimeKind,
  SubagentInvocationMetadata,
  SubagentInvocationResult,
  SubagentSharedFile,
  StepTrace,
  StreamEvent,
  ToolCallRecord,
  TraceEvent,
  UpdateUserPayload,
  UpdateAgentPayload,
  WorkflowInfo,
  WorkflowLogsResponse,
  WorkflowNextAction,
  WorkflowPayload,
  WorkflowPendingApproval,
  WorkflowStep,
  WorkflowStepState,
  WorkflowSummary,
  WorkflowUpdatePayload,
  AgentMcpConnection,
  WebhookProvider,
  WebhookReceiverInfo,
  WebhookInvocationInfo,
  WorkflowTriggerInfo,
  TriggerExecutionInfo,
  IncidentInfo,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
const API_PATH_PREFIX = "/api/v1";
type JsonRecord = Record<string, unknown>;

// ── Structured API error ──

export type ApiErrorCategory = "network" | "auth" | "validation" | "server" | "timeout" | "unknown";

function categorizeStatus(status: number): ApiErrorCategory {
  if (status === 401 || status === 403) return "auth";
  if (status === 408 || status === 504) return "timeout";
  if (status >= 400 && status < 500) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

export class ApiError extends Error {
  readonly code: number;
  readonly category: ApiErrorCategory;
  readonly detail: string;

  constructor(code: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.category = categorizeStatus(code);
    this.detail = detail ?? "";
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

const HTML_ERROR_MARKUP_RE = /<(?:!doctype\s+html|html|body|title|h1)\b/i;
const HTML_TITLE_RE = /<title[^>]*>([\s\S]*?)<\/title>/i;
const HTML_H1_RE = /<h1[^>]*>([\s\S]*?)<\/h1>/i;
const HTML_TAG_RE = /<[^>]+>/g;
const ERROR_WHITESPACE_RE = /\s+/g;
const MAX_ERROR_MESSAGE_CHARS = 400;

function normalizeErrorWhitespace(value: string): string {
  return value.replace(ERROR_WHITESPACE_RE, " ").trim();
}

function clampErrorMessage(value: string, fallback: string): string {
  const normalized = normalizeErrorWhitespace(value);
  if (!normalized) return fallback;
  if (normalized.length <= MAX_ERROR_MESSAGE_CHARS) return normalized;
  return `${normalized.slice(0, MAX_ERROR_MESSAGE_CHARS - 3)}...`;
}

function decodeHtmlEntities(value: string): string {
  if (typeof document === "undefined") {
    return value
      .replace(/&nbsp;/gi, " ")
      .replace(/&amp;/gi, "&")
      .replace(/&lt;/gi, "<")
      .replace(/&gt;/gi, ">")
      .replace(/&quot;/gi, '"')
      .replace(/&#39;/gi, "'");
  }

  const textarea = document.createElement("textarea");
  textarea.innerHTML = value;
  return textarea.value;
}

function extractHtmlErrorHeadline(value: string): string | null {
  for (const pattern of [HTML_TITLE_RE, HTML_H1_RE]) {
    const match = pattern.exec(value);
    if (!match?.[1]) continue;
    const decoded = normalizeErrorWhitespace(decodeHtmlEntities(match[1].replace(HTML_TAG_RE, " ")));
    if (decoded) return decoded;
  }
  return null;
}

export function sanitizeErrorMessage(value: string | null | undefined, fallback = "Request failed."): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed) return fallback;

  if (HTML_ERROR_MARKUP_RE.test(trimmed)) {
    const headline = extractHtmlErrorHeadline(trimmed);
    if (headline) {
      return clampErrorMessage(`Upstream service error: ${headline}`, fallback);
    }

    const plainText = normalizeErrorWhitespace(decodeHtmlEntities(trimmed.replace(HTML_TAG_RE, " ")));
    if (plainText) {
      return clampErrorMessage(`Upstream service error: ${plainText}`, fallback);
    }
    return fallback;
  }

  return clampErrorMessage(trimmed, fallback);
}

export function apiErrorMessage(err: unknown): string {
  // Try parsing structured gateway error first
  const structured = parseStructuredError(err);
  if (structured) {
    const parts = [structured.message];
    if (structured.suggestion) parts.push(structured.suggestion);
    return parts.join(" — ");
  }
  if (err instanceof ApiError) return sanitizeErrorMessage(err.detail || err.message, "Request failed.");
  if (err instanceof Error) return sanitizeErrorMessage(err.message, "Request failed.");
  return sanitizeErrorMessage(String(err), "Request failed.");
}

/** Parsed fields from the gateway's structured ErrorResponse envelope. */
export interface StructuredError {
  code: string;
  message: string;
  detail?: string;
  suggestion?: string;
  requestId?: string;
}

/** Attempt to parse a structured ErrorResponse from an error object.
 *  Returns null if the error is not a structured API error. */
export function parseStructuredError(err: unknown): StructuredError | null {
  if (!(err instanceof ApiError)) return null;
  try {
    const parsed = JSON.parse(err.detail);
    if (parsed && typeof parsed === "object" && typeof parsed.code === "string") {
      return {
        code: parsed.code,
        message: parsed.message || err.message,
        detail: parsed.detail,
        suggestion: parsed.suggestion,
        requestId: parsed.request_id,
      };
    }
  } catch { /* not JSON */ }
  return null;
}

function formatApiErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return sanitizeErrorMessage(detail, "Request failed.");
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (isRecord(item)) {
          const path = Array.isArray(item.loc)
            ? item.loc.filter((segment): segment is string | number => typeof segment === "string" || typeof segment === "number").join(".")
            : "";
          const msg = typeof item.msg === "string" ? item.msg : "Validation error";
          const normalizedPath = path.replace(/^body\./, "");
          if (normalizedPath === "system_prompt" && /at most\s+\d+\s+characters/i.test(msg)) {
            return `System prompt must be ${SYSTEM_PROMPT_MAX_CHARS} characters or fewer. Shorten it before saving.`;
          }
          return path ? `${path}: ${msg}` : msg;
        }
        return typeof item === "string" ? item : "Validation error";
      })
      .filter((item) => item.trim().length > 0);
    return parts.join("; ");
  }
  if (isRecord(detail)) {
    const nestedDetail = detail.detail;
    if (nestedDetail !== undefined && nestedDetail !== detail) {
      const nested = formatApiErrorDetail(nestedDetail);
      if (nested) return nested;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return "Request failed.";
    }
  }
  if (detail == null) {
    return "";
  }
  return String(detail);
}

/**
 * Global callback invoked when a silent token refresh succeeds.
 * ConnectionContext registers this so the React state stays in sync.
 */
let _onTokenRefreshed: ((newToken: string) => void) | null = null;

export function setOnTokenRefreshed(cb: ((newToken: string) => void) | null): void {
  _onTokenRefreshed = cb;
}

/** Deduplicates concurrent refresh attempts. */
let _refreshPromise: Promise<AuthSession> | null = null;

function buildUrl(path: string, namespace?: string): string {
  const baseUrl = API_BASE_URL || window.location.origin;
  const normalizedPath = path.startsWith("/api/v1")
    ? path
    : path.startsWith("/api/")
      ? `${API_PATH_PREFIX}${path.slice(4)}`
      : path;
  const url = new URL(normalizedPath, baseUrl);
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

function buildCredentialedInit(init: RequestInit = {}): RequestInit {
  return {
    credentials: "include",
    ...init,
  };
}

function buildAuthenticatedInit(token?: string, requestId?: string, init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers ?? undefined);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (token?.trim()) {
    headers.set("Authorization", `Bearer ${token.trim()}`);
  }
  if (requestId) {
    headers.set("X-Request-Id", requestId);
  }
  return buildCredentialedInit({
    cache: "no-store" as RequestCache,
    ...init,
    headers,
  });
}

async function fetchAuthenticated(
  url: string,
  token?: string,
  init: RequestInit = {},
  requestId?: string,
): Promise<Response> {
  const trimmedToken = token?.trim() || undefined;
  const response = await fetch(url, buildAuthenticatedInit(trimmedToken, requestId, init));

  // On 401, attempt a silent token refresh and retry once
  if (response.status === 401 && trimmedToken) {
    try {
      if (!_refreshPromise) {
        _refreshPromise = refreshAuthSessionInternal();
      }
      const session = await _refreshPromise;
      _refreshPromise = null;

      // Notify React state
      if (_onTokenRefreshed) _onTokenRefreshed(session.access_token);
      localStorage.setItem("kubesynapse/token", session.access_token);

      // Retry the original request with the new token
      return fetch(url, buildAuthenticatedInit(session.access_token, requestId, init));
    } catch {
      _refreshPromise = null;
      // Refresh truly failed — clear stale token so the UI re-shows login
      localStorage.removeItem("kubesynapse/token");
      return response;
    }
  }

  return response;
}

function requestInfoToUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function buildEventSourceFetch(token: string, requestId?: string) {
  return (input: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
    fetchAuthenticated(requestInfoToUrl(input), token, init ?? {}, requestId);
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

function readNumber(record: JsonRecord, key: string, label: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label}.${key} must be a finite number.`);
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

function readCapabilityFlags(
  record: JsonRecord,
  key: string,
  _label: string,
): Record<string, boolean> {
  const value = record[key];
  if (value === undefined || value === null) return {};
  if (typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const flags: Record<string, boolean> = {};
  for (const [capability, raw] of Object.entries(value as JsonRecord)) {
    if (typeof raw === "boolean") {
      flags[capability] = raw;
    }
  }
  return flags;
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

function readOptionalRecordArray(record: JsonRecord, key: string, label: string): JsonRecord[] | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  if (!Array.isArray(value)) {
    throw new Error(`${label}.${key} must be an array when present.`);
  }
  return value.map((item, index) => expectRecord(item, `${label}.${key}[${index}]`));
}

function normalizeWorkflowStepStatus(status: string | null | undefined): string {
  const normalized = status?.trim().toLowerCase() ?? "";
  switch (normalized) {
    case "":
      return "pending";
    case "succeeded":
      return "completed";
    case "waiting-approval":
    case "waitingapproval":
    case "waiting approval":
      return "waiting_approval";
    default:
      return normalized;
  }
}

function parseWorkflowStepStatePayload(
  payload: unknown,
  fallbackStepName: string,
  label = "WorkflowStepState",
): WorkflowStepState {
  const record = expectRecord(payload, label);
  const warnings = record.warnings === undefined || record.warnings === null
    ? null
    : readStringArray(record, "warnings", label);

  return {
    stepName: readString(record, "stepName", label, fallbackStepName),
    agentRef: readString(record, "agentRef", label, ""),
    status: normalizeWorkflowStepStatus(readString(record, "status", label, "pending")),
    attempts: readOptionalNumber(record, "attempts", label) ?? undefined,
    startedAt: readOptionalString(record, "startedAt", label),
    completedAt: readOptionalString(record, "completedAt", label),
    updatedAt: readOptionalString(record, "updatedAt", label),
    latencyMs: readOptionalNumber(record, "latencyMs", label),
    error: readOptionalString(record, "error", label),
    failureClass: readOptionalString(record, "failureClass", label),
    approvalWaitMs: readOptionalNumber(record, "approvalWaitMs", label),
    workerJob: readOptionalRecord(record, "workerJob", label),
    execution: readOptionalRecord(record, "execution", label),
    loopProgress: readOptionalRecord(record, "loopProgress", label) as WorkflowStepState["loopProgress"],
    planProgress: readOptionalRecord(record, "planProgress", label) as WorkflowStepState["planProgress"],
    verificationResult: readOptionalRecord(record, "verificationResult", label) as WorkflowStepState["verificationResult"],
    reviewResult: readOptionalRecord(record, "reviewResult", label) as WorkflowStepState["reviewResult"],
    iterationFailures: readOptionalRecordArray(record, "iterationFailures", label) as WorkflowStepState["iterationFailures"],
    responsePreview: readOptionalString(record, "responsePreview", label),
    artifactCount: readOptionalNumber(record, "artifactCount", label),
    toolCallCount: readOptionalNumber(record, "toolCallCount", label),
    artifacts: readOptionalRecordArray(record, "artifacts", label) as WorkflowStepState["artifacts"],
    toolCalls: readOptionalRecordArray(record, "toolCalls", label) as WorkflowStepState["toolCalls"],
    warnings,
  };
}

function readOptionalJsonValue(record: JsonRecord, key: string): unknown {
  const value = record[key];
  return value === undefined ? null : value;
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
  if (runtimeKind !== "opencode" && runtimeKind !== "pi" && runtimeKind !== "mistral-vibe") {
    throw new Error(`${label}.${key} must be 'opencode', 'pi', or 'mistral-vibe'.`);
  }
  return runtimeKind;
}

function readOptionalRuntimeKind(record: JsonRecord, key: string, label: string): RuntimeKind | null {
  const value = record[key];
  if (value === undefined || value === null) {
    return null;
  }
  return readRuntimeKind(record, key, label);
}

function parseA2APeerRefPayload(payload: unknown, label: string): A2APeerRef {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
  };
}

function parseA2APeerRefArrayPayload(payload: unknown, label: string): A2APeerRef[] {
  if (!Array.isArray(payload)) {
    throw new Error(`${label} must be an array.`);
  }
  return payload.map((item, index) => parseA2APeerRefPayload(item, `${label}[${index}]`));
}

function parseAgentA2AConfigPayload(payload: unknown, label: string): AgentA2AConfig {
  if (payload === undefined || payload === null) {
    return { allowed_callers: [] };
  }

  const record = expectRecord(payload, label);
  const rawAllowedCallers = record.allowed_callers ?? record.allowedCallers;
  return {
    allowed_callers:
      rawAllowedCallers === undefined ? [] : parseA2APeerRefArrayPayload(rawAllowedCallers, `${label}.allowed_callers`),
  };
}

function parseAgentSkillsConfigPayload(payload: unknown, label: string): AgentSkillsConfig {
  if (payload === undefined || payload === null) {
    return { files: {} };
  }

  const record = expectRecord(payload, label);
  const files = record.files;
  if (files === undefined || files === null) {
    return { files: {} };
  }
  if (!isRecord(files)) {
    throw new Error(`${label}.files must be an object keyed by Markdown file path.`);
  }

  const normalizedFiles: Record<string, string> = {};
  for (const [path, value] of Object.entries(files)) {
    if (typeof value !== "string") {
      throw new Error(`${label}.files.${path} must be a string.`);
    }
    normalizedFiles[path] = value;
  }
  return { files: normalizedFiles };
}

function parseGitConfigPayload(payload: unknown, label: string): GitConfig | null {
  if (payload === undefined || payload === null) {
    return null;
  }

  const record = expectRecord(payload, label);
  return {
    repo_url: readString(record, "repo_url", label),
    default_branch: readOptionalString(record, "default_branch", label) ?? undefined,
    branch: readOptionalString(record, "branch", label) ?? undefined,
    push_policy: (readOptionalString(record, "push_policy", label) ?? undefined) as GitConfig["push_policy"],
    auth_method: readString(record, "auth_method", label) as GitConfig["auth_method"],
    credential_secret_ref: readOptionalString(record, "credential_secret_ref", label) ?? undefined,
  };
}

function parseGitHubConfigPayload(payload: unknown, label: string): GitHubConfig | null {
  if (payload === undefined || payload === null) {
    return null;
  }

  const record = expectRecord(payload, label);
  return {
    credential_secret_ref: readOptionalString(record, "credential_secret_ref", label) ?? undefined,
  };
}

function parseMcpConnectionValidationStatus(
  value: string,
  label: string,
): McpConnectionValidationStatus {
  if (value === "draft" || value === "valid" || value === "warning" || value === "invalid") {
    return value;
  }
  throw new Error(`${label} must be draft, valid, warning, or invalid.`);
}

function parseMcpConnectionOAuthState(
  value: string,
  label: string,
): McpConnectionOAuth["state"] {
  if (value === "required" || value === "connected" || value === "expired") {
    return value;
  }
  throw new Error(`${label} must be required, connected, or expired.`);
}

function parseMcpConnectionCredentialFieldPayload(
  payload: unknown,
  label: string,
): McpConnectionCredentialField {
  const record = expectRecord(payload, label);
  return {
    key: readString(record, "key", label),
    label: readString(record, "label", label),
    type: readString(record, "type", label),
    group: readString(record, "group", label, "credentials"),
    required: readBoolean(record, "required", label, false),
    configured: readBoolean(record, "configured", label, false),
  };
}

function parseMcpConnectionValidationPayload(payload: unknown, label: string): McpConnectionValidation {
  const record = expectRecord(payload, label);
  return {
    status: parseMcpConnectionValidationStatus(readString(record, "status", label, "draft"), `${label}.status`),
    message: readOptionalString(record, "message", label),
    detail: readOptionalRecord(record, "detail", label),
    last_validated_at: readOptionalString(record, "last_validated_at", label),
  };
}

function parseMcpConnectionRuntimeHeaderPayload(payload: unknown, label: string): McpConnectionRuntimeHeader {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    envVar: readOptionalString(record, "envVar", label),
    prefix: readOptionalString(record, "prefix", label),
  };
}

function parseMcpConnectionRuntimeSidecarPayload(payload: unknown, label: string): McpConnectionRuntimeSidecar {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    image: readString(record, "image", label),
    port: readNumber(record, "port", label),
    endpointPath: readOptionalString(record, "endpointPath", label),
    env: record.env === undefined ? [] : readRecordArray(record, "env", label),
  };
}

function parseMcpConnectionRuntimePreviewPayload(payload: unknown, label: string): McpConnectionRuntimePreview {
  const record = expectRecord(payload, label);
  const kind = readString(record, "kind", label);
  if (kind !== "remote" && kind !== "sidecar") {
    throw new Error(`${label}.kind must be remote or sidecar.`);
  }
  const rawHeaders = record.headers;
  if (rawHeaders !== undefined && !Array.isArray(rawHeaders)) {
    throw new Error(`${label}.headers must be an array when present.`);
  }
  return {
    kind,
    configKey: readString(record, "configKey", label),
    url: readOptionalString(record, "url", label),
    headers: (rawHeaders ?? []).map((item, index) =>
      parseMcpConnectionRuntimeHeaderPayload(item, `${label}.headers[${index}]`),
    ),
    sidecar:
      record.sidecar === undefined || record.sidecar === null
        ? null
        : parseMcpConnectionRuntimeSidecarPayload(record.sidecar, `${label}.sidecar`),
  };
}

function parseMcpConnectionOAuthPayload(payload: unknown, label: string): McpConnectionOAuth {
  const record = expectRecord(payload, label);
  return {
    connected: readBoolean(record, "connected", label, false),
    state: parseMcpConnectionOAuthState(readString(record, "state", label), `${label}.state`),
    expires_at: readOptionalString(record, "expires_at", label),
    refresh_available: readBoolean(record, "refresh_available", label, false),
    scope: readStringArray(record, "scope", label, []),
  };
}

function parseMcpConnectionPayload(payload: unknown, label = "McpConnection"): McpConnection {
  const record = expectRecord(payload, label);
  const rawCredentialMetadata = record.credential_metadata;
  if (rawCredentialMetadata !== undefined && !Array.isArray(rawCredentialMetadata)) {
    throw new Error(`${label}.credential_metadata must be an array.`);
  }
  return {
    id: readString(record, "id", label),
    namespace: readString(record, "namespace", label),
    name: readString(record, "name", label),
    slug: readString(record, "slug", label),
    server_id: readString(record, "server_id", label),
    server_name: readOptionalString(record, "server_name", label),
    transport: readString(record, "transport", label) as McpConnection["transport"],
    auth_type: readString(record, "auth_type", label) as McpConnection["auth_type"],
    config: readRecord(record, "config", label),
    credential_metadata: (rawCredentialMetadata ?? []).map((item, index) =>
      parseMcpConnectionCredentialFieldPayload(item, `${label}.credential_metadata[${index}]`),
    ),
    validation: parseMcpConnectionValidationPayload(record.validation ?? {}, `${label}.validation`),
    support_level: parseMcpSupportLevel(readString(record, "support_level", label), `${label}.support_level`),
    attachable: readBoolean(record, "attachable", label, false),
    status_reason: readOptionalString(record, "status_reason", label),
    runtime_preview:
      record.runtime_preview === undefined || record.runtime_preview === null
        ? null
        : parseMcpConnectionRuntimePreviewPayload(record.runtime_preview, `${label}.runtime_preview`),
    oauth:
      record.oauth === undefined || record.oauth === null
        ? null
        : parseMcpConnectionOAuthPayload(record.oauth, `${label}.oauth`),
    binding_count: readNumber(record, "binding_count", label),
    created_at: readOptionalString(record, "created_at", label),
    updated_at: readOptionalString(record, "updated_at", label),
  };
}

function parseMcpConnectionBindingPayload(payload: unknown, label = "McpConnectionBinding"): McpConnectionBinding {
  const record = expectRecord(payload, label);
  return {
    agent_name: readString(record, "agent_name", label),
    namespace: readString(record, "namespace", label),
    connection_id: readString(record, "connection_id", label),
    connection_name: readString(record, "connection_name", label),
    server_id: readString(record, "server_id", label),
    transport: readString(record, "transport", label),
  };
}

function parseAgentMcpConnectionPayload(payload: unknown, label = "AgentMcpConnection"): AgentMcpConnection {
  const record = expectRecord(payload, label);
  const rawCredentialMetadata = record.credentialMetadata;
  if (rawCredentialMetadata !== undefined && !Array.isArray(rawCredentialMetadata)) {
    throw new Error(`${label}.credentialMetadata must be an array.`);
  }
  return {
    connection_id: readOptionalString(record, "connectionId", label),
    name: readString(record, "name", label),
    slug: readString(record, "slug", label),
    server_id: readString(record, "serverId", label),
    server_name: readOptionalString(record, "serverName", label),
    transport: readString(record, "transport", label) as AgentMcpConnection["transport"],
    support_level: parseMcpSupportLevel(readString(record, "supportLevel", label), `${label}.supportLevel`),
    attachable: readBoolean(record, "attachable", label, false),
    status_reason: readOptionalString(record, "statusReason", label),
    source: readString(record, "source", label, "saved"),
    config: readRecord(record, "config", label),
    credential_metadata: (rawCredentialMetadata ?? []).map((item, index) =>
      parseMcpConnectionCredentialFieldPayload(item, `${label}.credentialMetadata[${index}]`),
    ),
    validation: parseMcpConnectionValidationPayload(record.validation ?? {}, `${label}.validation`),
    runtime: parseMcpConnectionRuntimePreviewPayload(record.runtime ?? {}, `${label}.runtime`),
  };
}

function parseAgentSkillSummaryPayload(payload: unknown, label: string): AgentSkillSummary {
  const record = expectRecord(payload, label);
  return {
    path: readString(record, "path", label),
    name: readString(record, "name", label),
    description: readOptionalString(record, "description", label),
    instructions_preview: readOptionalString(record, "instructions_preview", label),
    allowed_sandbox_tools: readStringArray(record, "allowed_sandbox_tools", label, []),
    allowed_mcp_servers: readStringArray(record, "allowed_mcp_servers", label, []),
    allowed_a2a_targets: parseA2APeerRefArrayPayload(record.allowed_a2a_targets ?? [], `${label}.allowed_a2a_targets`),
    allow_subagents: readBoolean(record, "allow_subagents", label, false),
    valid: readBoolean(record, "valid", label, true),
    warnings: readStringArray(record, "warnings", label, []),
  };
}

function parseA2AInvocationMetadataPayload(payload: unknown, label: string): A2AInvocationMetadata {
  const record = expectRecord(payload, label);
  return {
    targetAgent: readOptionalString(record, "targetAgent", label),
    targetNamespace: readOptionalString(record, "targetNamespace", label),
    targetThreadId: readOptionalString(record, "targetThreadId", label),
    responseStatus: readOptionalString(record, "responseStatus", label),
    transport: readOptionalString(record, "transport", label),
    callerAgent: readOptionalString(record, "callerAgent", label),
    callerNamespace: readOptionalString(record, "callerNamespace", label),
    parentThreadId: readOptionalString(record, "parentThreadId", label),
    callerRequestId: readOptionalString(record, "callerRequestId", label),
  };
}

function parseSubagentSharedFilePayload(payload: unknown, label: string): SubagentSharedFile {
  const record = expectRecord(payload, label);
  return {
    path: readOptionalString(record, "path", label),
    purpose: readOptionalString(record, "purpose", label),
    chars: readOptionalNumber(record, "chars", label),
  };
}

function parseSubagentSharedFileArray(payload: unknown, label: string): SubagentSharedFile[] {
  if (payload === undefined || payload === null) {
    return [];
  }
  if (!Array.isArray(payload)) {
    throw new Error(`${label} must be an array.`);
  }
  return payload.map((item, index) => parseSubagentSharedFilePayload(item, `${label}[${index}]`));
}

function parseSubagentInvocationResultPayload(payload: unknown, label: string): SubagentInvocationResult {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
    role: readOptionalString(record, "role", label),
    task: readOptionalString(record, "task", label),
    status: readString(record, "status", label, "unknown"),
    transport: readOptionalString(record, "transport", label),
    threadId: readOptionalString(record, "threadId", label),
    responsePreview: readOptionalString(record, "responsePreview", label),
    resultFilePath: readOptionalString(record, "resultFilePath", label),
    sharedFiles: parseSubagentSharedFileArray(record.sharedFiles, `${label}.sharedFiles`),
    warnings: readStringArray(record, "warnings", label, []),
    approvalName: readOptionalString(record, "approvalName", label),
    retryAfterSeconds: readOptionalNumber(record, "retryAfterSeconds", label),
    error: readOptionalString(record, "error", label),
    metadata: readOptionalRecord(record, "metadata", label),
  };
}

function parseSubagentInvocationMetadataPayload(payload: unknown, label: string): SubagentInvocationMetadata {
  const record = expectRecord(payload, label);
  const rawResults = record.results;
  if (rawResults !== undefined && !Array.isArray(rawResults)) {
    throw new Error(`${label}.results must be an array.`);
  }

  return {
    strategy: readOptionalString(record, "strategy", label),
    count: readOptionalNumber(record, "count", label),
    sharedSandboxSession: readOptionalBoolean(record, "sharedSandboxSession", label),
    sharedFiles: parseSubagentSharedFileArray(record.sharedFiles, `${label}.sharedFiles`),
    resultFiles: readStringArray(record, "resultFiles", label, []),
    results: (rawResults ?? []).map((item, index) => parseSubagentInvocationResultPayload(item, `${label}.results[${index}]`)),
  };
}

function parseAgentDiscoveryPeerPayload(payload: unknown, label: string): AgentDiscoveryPeer {
  const record = expectRecord(payload, label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
    exists: readBoolean(record, "exists", label, false),
    model: readOptionalString(record, "model", label),
    status: readOptionalString(record, "status", label),
    runtime_kind: readOptionalRuntimeKind(record, "runtime_kind", label),
    accepts_caller: readBoolean(record, "accepts_caller", label, false),
    reachable: readBoolean(record, "reachable", label, false),
    reason: readOptionalString(record, "reason", label),
  };
}

function parseAgentDiscoveryResponsePayload(payload: unknown): AgentDiscoveryResponse {
  const record = expectRecord(payload, "AgentDiscoveryResponse");
  const peers = record.peers;
  if (peers !== undefined && !Array.isArray(peers)) {
    throw new Error("AgentDiscoveryResponse.peers must be an array.");
  }

  return {
    agent_name: readString(record, "agent_name", "AgentDiscoveryResponse"),
    namespace: readString(record, "namespace", "AgentDiscoveryResponse"),
    policy_ref: readOptionalString(record, "policy_ref", "AgentDiscoveryResponse"),
    peers: (peers ?? []).map((item, index) => parseAgentDiscoveryPeerPayload(item, `AgentDiscoveryResponse.peers[${index}]`)),
  };
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
  const rawSkillSummaries = record.skill_summaries;
  const rawMcpConnections = record.mcp_connections;
  if (rawSkillSummaries !== undefined && !Array.isArray(rawSkillSummaries)) {
    throw new Error("AgentDetail.skill_summaries must be an array.");
  }
  if (rawMcpConnections !== undefined && !Array.isArray(rawMcpConnections)) {
    throw new Error("AgentDetail.mcp_connections must be an array.");
  }
  return {
    ...base,
    system_prompt: readString(record, "system_prompt", "AgentDetail", ""),
    policy_ref: readOptionalString(record, "policy_ref", "AgentDetail"),
    storage_size: readOptionalString(record, "storage_size", "AgentDetail"),
    runtime_kind: readRuntimeKind(record, "runtime_kind", "AgentDetail", "opencode"),
    enable_gvisor: readBoolean(record, "enable_gvisor", "AgentDetail", false),
    mcp_connections: (rawMcpConnections ?? []).map((item, index) =>
      parseAgentMcpConnectionPayload(item, `AgentDetail.mcp_connections[${index}]`),
    ),
    mcp_servers: readStringArray(record, "mcp_servers", "AgentDetail"),
    mcp_sidecars: readRecordArray(record, "mcp_sidecars", "AgentDetail"),
    a2a_config: parseAgentA2AConfigPayload(record.a2a_config, "AgentDetail.a2a_config"),
    skills: parseAgentSkillsConfigPayload(record.skills, "AgentDetail.skills"),
    skill_summaries: (rawSkillSummaries ?? []).map((item, index) =>
      parseAgentSkillSummaryPayload(item, `AgentDetail.skill_summaries[${index}]`),
    ),
    opencode_config_files: readRecord(record, "opencode_config_files", "AgentDetail"),
    git_config: parseGitConfigPayload(record.git_config, "AgentDetail.git_config"),
    github_config: parseGitHubConfigPayload(record.github_config, "AgentDetail.github_config"),
    created_at: readOptionalString(record, "created_at", "AgentDetail"),
  };
}

function parsePolicyInfoPayload(payload: unknown, label = "PolicyInfo"): PolicyInfo {
  const record = expectRecord(payload, label);
  const igRaw = readOptionalRecord(record, "input_guardrails", label) ?? {};
  const ogRaw = readOptionalRecord(record, "output_guardrails", label) ?? {};
  const tpRaw = readOptionalRecord(record, "tool_policy", label) ?? {};
  const mpRaw = readOptionalRecord(record, "memory_policy", label) ?? {};
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
    input_guardrails: {
      blockPromptInjection: readOptionalBoolean(igRaw as JsonRecord, "blockPromptInjection", label) ?? false,
      blockedPatterns: readStringArray(igRaw as JsonRecord, "blockedPatterns", label, []),
      maxInputTokens: readOptionalNumber(igRaw as JsonRecord, "maxInputTokens", label) ?? 4096,
    },
    output_guardrails: {
      maskPII: readOptionalBoolean(ogRaw as JsonRecord, "maskPII", label) ?? false,
      blockedOutputPatterns: readStringArray(ogRaw as JsonRecord, "blockedOutputPatterns", label, []),
      maxOutputTokens: readOptionalNumber(ogRaw as JsonRecord, "maxOutputTokens", label) ?? 4096,
    },
    allowed_models: readStringArray(record, "allowed_models", label, []),
    allowed_mcp_servers: readStringArray(record, "allowed_mcp_servers", label, []),
    mcp_require_hitl: readOptionalBoolean(record, "mcp_require_hitl", label) ?? true,
    tool_policy: {
      maxDelegationDepth: readOptionalNumber(tpRaw as JsonRecord, "maxDelegationDepth", label) ?? undefined,
      allowedToolPrefixes: readStringArray(tpRaw as JsonRecord, "allowedToolPrefixes", label, []),
      blockedToolNames: readStringArray(tpRaw as JsonRecord, "blockedToolNames", label, []),
      requireApprovalFor: readStringArray(tpRaw as JsonRecord, "requireApprovalFor", label, []),
    },
    memory_policy: {
      maxInjectedMemories: readOptionalNumber(mpRaw as JsonRecord, "maxInjectedMemories", label) ?? undefined,
      maxInjectedChars: readOptionalNumber(mpRaw as JsonRecord, "maxInjectedChars", label) ?? undefined,
      allowedMemoryTypes: readStringArray(mpRaw as JsonRecord, "allowedMemoryTypes", label, []),
      autoPromote: readOptionalBoolean(mpRaw as JsonRecord, "autoPromote", label) ?? false,
    },
  };
}

function parseGatewayHealthPayload(payload: unknown): GatewayHealth {
  const record = expectRecord(payload, "GatewayHealth");
  return {
    status: readString(record, "status", "GatewayHealth"),
    gateway: readString(record, "gateway", "GatewayHealth"),
    auth_mode: readString(record, "auth_mode", "GatewayHealth"),
    browser_auth_enabled: readOptionalBoolean(record, "browser_auth_enabled", "GatewayHealth") ?? undefined,
    local_auth_enabled: readOptionalBoolean(record, "local_auth_enabled", "GatewayHealth") ?? undefined,
    shared_token_enabled: readOptionalBoolean(record, "shared_token_enabled", "GatewayHealth") ?? undefined,
    nats_url: readString(record, "nats_url", "GatewayHealth"),
    qdrant_url: readString(record, "qdrant_url", "GatewayHealth"),
  };
}

function parseAuthProviderSummaryPayload(payload: unknown, label: string): AuthProviderSummary {
  const record = expectRecord(payload, label);
  return {
    id: readString(record, "id", label),
    name: readString(record, "name", label),
    kind: readString(record, "kind", label),
    brand: readOptionalString(record, "brand", label) ?? undefined,
    supported: readOptionalBoolean(record, "supported", label) ?? undefined,
  };
}

function parseAuthenticatedUserPayload(payload: unknown, label = "AuthenticatedUser"): AuthenticatedUser {
  const record = expectRecord(payload, label);
  const role = readString(record, "role", label) as AuthenticatedUser["role"];
  if (role !== "viewer" && role !== "operator" && role !== "admin") {
    throw new Error(`${label}.role must be viewer, operator, or admin.`);
  }
  return {
    sub: readString(record, "sub", label),
    id: readString(record, "id", label),
    username: readString(record, "username", label),
    display_name: readString(record, "display_name", label),
    email: readOptionalString(record, "email", label),
    role,
    allowed_namespaces: readStringArray(record, "allowed_namespaces", label, []),
    capabilities: readCapabilityFlags(record, "capabilities", label),
    auth_provider: readString(record, "auth_provider", label),
    session_id: readOptionalString(record, "session_id", label),
    is_active: readBoolean(record, "is_active", label, true),
  };
}

function parseAdminUserPayload(payload: unknown, label = "AdminUser"): AdminUser {
  const record = expectRecord(payload, label);
  const role = readString(record, "role", label) as AdminUser["role"];
  if (role !== "viewer" && role !== "operator" && role !== "admin") {
    throw new Error(`${label}.role must be viewer, operator, or admin.`);
  }
  return {
    id: readNumber(record, "id", label),
    username: readString(record, "username", label),
    email: readOptionalString(record, "email", label),
    display_name: readString(record, "display_name", label),
    role,
    allowed_namespaces: readStringArray(record, "allowed_namespaces", label, []),
    capabilities: readCapabilityFlags(record, "capabilities", label),
    auth_provider: readString(record, "auth_provider", label),
    is_active: readBoolean(record, "is_active", label, true),
    created_at: readOptionalString(record, "created_at", label),
    updated_at: readOptionalString(record, "updated_at", label),
    last_login_at: readOptionalString(record, "last_login_at", label),
  };
}

function parseAuthConfigPayload(payload: unknown): AuthConfig {
  const record = expectRecord(payload, "AuthConfig");
  const oidcProviders = Array.isArray(record.oidc_providers)
    ? record.oidc_providers.map((item, index) => parseAuthProviderSummaryPayload(item, `AuthConfig.oidc_providers[${index}]`))
    : [];
  const samlProviders = Array.isArray(record.saml_providers)
    ? record.saml_providers.map((item, index) => parseAuthProviderSummaryPayload(item, `AuthConfig.saml_providers[${index}]`))
    : [];
  return {
    auth_mode: readString(record, "auth_mode", "AuthConfig"),
    local_enabled: readBoolean(record, "local_enabled", "AuthConfig", false),
    registration_enabled: readBoolean(record, "registration_enabled", "AuthConfig", false),
    shared_token_enabled: readBoolean(record, "shared_token_enabled", "AuthConfig", false),
    browser_auth_enabled: readBoolean(record, "browser_auth_enabled", "AuthConfig", false),
    bootstrap_complete: readBoolean(record, "bootstrap_complete", "AuthConfig", false),
    password_providers: readStringArray(record, "password_providers", "AuthConfig", []),
    oidc_providers: oidcProviders,
    saml_providers: samlProviders,
  };
}

function parseAuthSessionPayload(payload: unknown): AuthSession {
  const record = expectRecord(payload, "AuthSession");
  return {
    access_token: readString(record, "access_token", "AuthSession"),
    token_type: readString(record, "token_type", "AuthSession"),
    expires_in: readOptionalNumber(record, "expires_in", "AuthSession") ?? 0,
    expires_at: readString(record, "expires_at", "AuthSession"),
    refresh_expires_at: readOptionalString(record, "refresh_expires_at", "AuthSession"),
    user: parseAuthenticatedUserPayload(record.user, "AuthSession.user"),
    auth_mode: readString(record, "auth_mode", "AuthSession"),
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
    execution: readOptionalRecord(record, "execution", label),
    step_type: (readOptionalString(record, "step_type", label) as "agent" | "loop" | "conditional" | "review" | undefined) ?? "agent",
    loop_config: (readOptionalRecord(record, "loop_config", label) as LoopConfig | null) ?? null,
    condition_expr: readOptionalString(record, "condition_expr", label) ?? null,
    then_steps: record.then_steps ? (record.then_steps as string[]) : null,
    else_steps: record.else_steps ? (record.else_steps as string[]) : null,
    verify: readOptionalString(record, "verify", label) ?? null,
    review_criteria: readOptionalString(record, "review_criteria", label) ?? null,
  };
}

function parseWorkflowInfoPayload(payload: unknown, label = "WorkflowInfo"): WorkflowInfo {
  const record = expectRecord(payload, label);
  const rawStepStates = readOptionalRecord(record, "step_states", label);
  return {
    name: readString(record, "name", label),
    namespace: readString(record, "namespace", label),
    description: readString(record, "description", label, ""),
    input: readString(record, "input", label, ""),
    context_ref: readOptionalString(record, "context_ref", label),
    message_bus: readString(record, "message_bus", label, "in-memory"),
    steps: (record.steps === undefined ? [] : readRecordArray(record, "steps", label)).map((item, index) =>
      parseWorkflowStepPayload(item, `${label}.steps[${index}]`)
    ),
    phase: readString(record, "phase", label, "pending"),
    current_step: readString(record, "current_step", label, ""),
    observed_generation: readOptionalNumber(record, "observed_generation", label),
    summary: readOptionalRecord(record, "summary", label) as WorkflowSummary | null,
    artifact_ref: readOptionalRecord(record, "artifact_ref", label),
    journal_ref: readOptionalRecord(record, "journal_ref", label),
    pending_approval: (() => {
      const pa = readOptionalRecord(record, "pending_approval", label);
      if (pa) {
        const paRecord = pa as Record<string, unknown>;
        if (typeof paRecord.name === "string" && typeof paRecord.stepName === "string") {
          return {
            name: paRecord.name,
            stepName: paRecord.stepName,
            requestedAt: typeof paRecord.requestedAt === "string" ? paRecord.requestedAt : null,
            runId: typeof paRecord.runId === "string" ? paRecord.runId : null,
            action: typeof paRecord.action === "string" ? paRecord.action : null,
            reason: typeof paRecord.reason === "string" ? paRecord.reason : undefined,
          } satisfies WorkflowPendingApproval;
        }
      }
      return null;
    })(),
    run_id: readOptionalString(record, "run_id", label),
    step_states: rawStepStates
      ? Object.fromEntries(
          Object.entries(rawStepStates).map(([stepName, state]) => [
            stepName,
            parseWorkflowStepStatePayload(state, stepName, `${label}.step_states.${stepName}`),
          ]),
        )
      : null,
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

function parseWorkflowLogsResponsePayload(payload: unknown): WorkflowLogsResponse {
  const record = expectRecord(payload, "WorkflowLogsResponse");
  return {
    workflow_name: readString(record, "workflow_name", "WorkflowLogsResponse"),
    run_id: readOptionalString(record, "run_id", "WorkflowLogsResponse"),
    job_name: readOptionalString(record, "job_name", "WorkflowLogsResponse") ?? undefined,
    pod_name: readOptionalString(record, "pod_name", "WorkflowLogsResponse") ?? undefined,
    source: readOptionalString(record, "source", "WorkflowLogsResponse") ?? undefined,
    archived_log_available: readOptionalBoolean(record, "archived_log_available", "WorkflowLogsResponse") ?? undefined,
    archived_log_source: readOptionalString(record, "archived_log_source", "WorkflowLogsResponse"),
    archived_log_truncated: readOptionalBoolean(record, "archived_log_truncated", "WorkflowLogsResponse") ?? undefined,
    archived_log_captured_at: readOptionalString(record, "archived_log_captured_at", "WorkflowLogsResponse"),
    logs: readString(record, "logs", "WorkflowLogsResponse", ""),
  };
}

function parseWorkflowRunRecordPayload(payload: unknown, label = "WorkflowRunRecord"): WorkflowRunRecord {
  const record = expectRecord(payload, label);
  return {
    id: readNumber(record, "id", label),
    run_id: readOptionalString(record, "run_id", label),
    phase: readString(record, "phase", label, "pending"),
    total_steps: readOptionalNumber(record, "total_steps", label),
    completed_steps: readOptionalNumber(record, "completed_steps", label),
    failed_steps: readOptionalNumber(record, "failed_steps", label),
    started_at: readOptionalString(record, "started_at", label),
    completed_at: readOptionalString(record, "completed_at", label),
    triggered_by: readOptionalString(record, "triggered_by", label),
    input_text: readOptionalString(record, "input_text", label),
    created_at: readOptionalString(record, "created_at", label),
    trace_available: readOptionalBoolean(record, "trace_available", label) ?? false,
    archived_log_available: readOptionalBoolean(record, "archived_log_available", label) ?? false,
    journal_available: readOptionalBoolean(record, "journal_available", label) ?? false,
  };
}

export interface WorkflowRunTraceResponse {
  workflow_name: string;
  namespace: string;
  history_id: number | null;
  run_id: string;
  phase: string | null;
  source: string;
  logs: string;
  pod_name?: string;
  worker_job_name?: string;
  workflow: WorkflowInfo;
  summary: Record<string, unknown> | null;
  step_states: Record<string, WorkflowStepState> | null;
  triggered_by: string | null;
  input_text: string | null;
  artifact_path: string | null;
  journal_path: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  archived_log_available: boolean;
  archived_log_source: string | null;
  archived_log_truncated: boolean;
  archived_log_captured_at: string | null;
  live_log_error: string | null;
}

function parseWorkflowRunTraceResponsePayload(payload: unknown): WorkflowRunTraceResponse {
  const record = expectRecord(payload, "WorkflowRunTraceResponse");
  const rawStepStates = readOptionalRecord(record, "step_states", "WorkflowRunTraceResponse");
  const parsedStepStates = rawStepStates
    ? Object.fromEntries(
        Object.entries(rawStepStates).map(([stepName, state]) => [
          stepName,
          parseWorkflowStepStatePayload(state, stepName, `WorkflowRunTraceResponse.step_states.${stepName}`),
        ]),
      )
    : null;

  return {
    workflow_name: readString(record, "workflow_name", "WorkflowRunTraceResponse"),
    namespace: readString(record, "namespace", "WorkflowRunTraceResponse"),
    history_id: readOptionalNumber(record, "history_id", "WorkflowRunTraceResponse"),
    run_id: readString(record, "run_id", "WorkflowRunTraceResponse"),
    phase: readOptionalString(record, "phase", "WorkflowRunTraceResponse"),
    source: readString(record, "source", "WorkflowRunTraceResponse", "unavailable"),
    logs: readString(record, "logs", "WorkflowRunTraceResponse", ""),
    pod_name: readOptionalString(record, "pod_name", "WorkflowRunTraceResponse") ?? undefined,
    worker_job_name: readOptionalString(record, "worker_job_name", "WorkflowRunTraceResponse") ?? undefined,
    workflow: parseWorkflowInfoPayload(record.workflow, "WorkflowRunTraceResponse.workflow"),
    summary: readOptionalRecord(record, "summary", "WorkflowRunTraceResponse"),
    step_states: parsedStepStates,
    triggered_by: readOptionalString(record, "triggered_by", "WorkflowRunTraceResponse"),
    input_text: readOptionalString(record, "input_text", "WorkflowRunTraceResponse"),
    artifact_path: readOptionalString(record, "artifact_path", "WorkflowRunTraceResponse"),
    journal_path: readOptionalString(record, "journal_path", "WorkflowRunTraceResponse"),
    created_at: readOptionalString(record, "created_at", "WorkflowRunTraceResponse"),
    updated_at: readOptionalString(record, "updated_at", "WorkflowRunTraceResponse"),
    completed_at: readOptionalString(record, "completed_at", "WorkflowRunTraceResponse"),
    archived_log_available: readBoolean(record, "archived_log_available", "WorkflowRunTraceResponse", false),
    archived_log_source: readOptionalString(record, "archived_log_source", "WorkflowRunTraceResponse"),
    archived_log_truncated: readBoolean(record, "archived_log_truncated", "WorkflowRunTraceResponse", false),
    archived_log_captured_at: readOptionalString(record, "archived_log_captured_at", "WorkflowRunTraceResponse"),
    live_log_error: readOptionalString(record, "live_log_error", "WorkflowRunTraceResponse"),
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
    tool_result: readOptionalJsonValue(record, "tool_result"),
    sandbox_session: readOptionalRecord(record, "sandbox_session", "InvokeResponse"),
    status: readString(record, "status", "InvokeResponse", "completed"),
    approval_name: readOptionalString(record, "approval_name", "InvokeResponse"),
    retry_after_seconds: readOptionalNumber(record, "retry_after_seconds", "InvokeResponse"),
    a2a: record.a2a === undefined || record.a2a === null ? null : parseA2AInvocationMetadataPayload(record.a2a, "InvokeResponse.a2a"),
    subagents:
      record.subagents === undefined || record.subagents === null
        ? null
        : parseSubagentInvocationMetadataPayload(record.subagents, "InvokeResponse.subagents"),
    warnings: record.warnings === undefined ? [] : readStringArray(record, "warnings", "InvokeResponse"),
    artifacts: record.artifacts === undefined || record.artifacts === null ? null : readRecordArray(record, "artifacts", "InvokeResponse"),
    tool_calls: record.tool_calls === undefined || record.tool_calls === null ? null : readRecordArray(record, "tool_calls", "InvokeResponse"),
    metadata: readOptionalRecord(record, "metadata", "InvokeResponse") ?? null,
  };
}

function parseStreamPayload(data: string): JsonRecord {
  const trimmed = data.trim();
  if (!trimmed || trimmed === "[DONE]") {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error("Streaming event payload was not valid JSON.");
  }
  return expectRecord(parsed, "Streaming event payload");
}

function extractFilenameFromDisposition(headerValue: string | null, fallback: string): string {
  if (!headerValue) return fallback;
  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }
  const basicMatch = headerValue.match(/filename="?([^";]+)"?/i);
  return basicMatch?.[1] || fallback;
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

function buildArtifactDownloadUrl(namespace: string, agentName: string, artifactPath: string): string {
  const url = new URL(buildUrl(`/api/agents/${encodeURIComponent(agentName)}/artifacts/download`, namespace), window.location.origin);
  url.searchParams.set("path", artifactPath);
  return API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
}

const IMAGE_PREVIEW_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico"]);
const MARKDOWN_PREVIEW_EXTENSIONS = new Set([".md", ".markdown", ".mdx"]);
const MERMAID_PREVIEW_EXTENSIONS = new Set([".mmd", ".mermaid"]);

// Binary formats that cannot be meaningfully rendered as text
const BINARY_EXTENSIONS = new Set([
  ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
  ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o",
  ".wasm", ".class", ".pyc", ".pyo",
  ".woff", ".woff2", ".ttf", ".otf", ".eot",
  ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".flac", ".wav", ".ogg", ".webm",
  ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
  ".sqlite", ".db", ".lock",
]);

function getArtifactExtension(artifactPath: string): string {
  const fileName = artifactPath.split(/[\\/]/).pop()?.toLowerCase() ?? "";
  if (fileName === "dockerfile") return ".dockerfile";
  if (fileName.startsWith(".")) return fileName;
  const extensionIndex = fileName.lastIndexOf(".");
  return extensionIndex >= 0 ? fileName.slice(extensionIndex) : "";
}

export type AgentArtifactPreviewKind = "text" | "markdown" | "mermaid" | "image" | "pdf" | "unsupported";

export interface AgentArtifactPreview {
  path: string;
  name: string;
  size: number;
  contentType: string;
  kind: AgentArtifactPreviewKind;
  blob?: Blob;
  text?: string;
  message?: string;
}

function classifyArtifactPreviewKind(artifactPath: string, contentType: string): AgentArtifactPreviewKind {
  const extension = getArtifactExtension(artifactPath);
  const normalizedType = contentType.toLowerCase();

  if (normalizedType.startsWith("image/") || IMAGE_PREVIEW_EXTENSIONS.has(extension)) {
    return "image";
  }
  if (normalizedType === "application/pdf" || extension === ".pdf") {
    return "pdf";
  }
  if (normalizedType.includes("mermaid") || MERMAID_PREVIEW_EXTENSIONS.has(extension)) {
    return "mermaid";
  }
  if (normalizedType === "text/markdown" || MARKDOWN_PREVIEW_EXTENSIONS.has(extension)) {
    return "markdown";
  }
  // Known binary formats that cannot be rendered as text
  if (BINARY_EXTENSIONS.has(extension)) {
    return "unsupported";
  }
  if (
    normalizedType.startsWith("application/octet-stream") &&
    !extension // no extension — truly unknown binary blob
  ) {
    return "unsupported";
  }
  // Default: treat everything else as text (covers .j2, .conf, .cfg, .tf, .hcl, .service, etc.)
  return "text";
}

export async function downloadAgentArtifact(
  token: string,
  namespace: string,
  agentName: string,
  artifactPath: string,
  suggestedFilename?: string,
): Promise<void> {
  const target = buildArtifactDownloadUrl(namespace, agentName, artifactPath);
  const response = await fetchAuthenticated(target, token);
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to download artifact", text);
  }

  const blob = await response.blob();
  const fallback = suggestedFilename || artifactPath.split("/").pop() || artifactPath.split("\\").pop() || "artifact";
  const filename = extractFilenameFromDisposition(response.headers.get("content-disposition"), fallback);
  triggerBrowserDownload(blob, filename);
}

export async function previewAgentArtifact(
  token: string,
  namespace: string,
  agentName: string,
  artifactPath: string,
): Promise<AgentArtifactPreview> {
  const target = buildArtifactDownloadUrl(namespace, agentName, artifactPath);
  const response = await fetchAuthenticated(target, token, {
    headers: {
      Accept: "*/*",
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to preview artifact", text);
  }

  const blob = await response.blob();
  const name = artifactPath.split("/").pop() || artifactPath.split("\\").pop() || "artifact";
  const contentType = (response.headers.get("content-type") || blob.type || "application/octet-stream").split(";")[0].trim().toLowerCase();
  const kind = classifyArtifactPreviewKind(artifactPath, contentType);

  if (kind === "image" || kind === "pdf") {
    return {
      path: artifactPath,
      name,
      size: blob.size,
      contentType,
      kind,
      blob,
    };
  }

  if (kind === "unsupported") {
    return {
      path: artifactPath,
      name,
      size: blob.size,
      contentType,
      kind,
      message: "Preview is not available for this file type yet.",
    };
  }

  return {
    path: artifactPath,
    name,
    size: blob.size,
    contentType,
    kind,
    text: await blob.text(),
  };
}

export async function downloadAgentArtifactZip(
  token: string,
  namespace: string,
  agentName: string,
): Promise<void> {
  const url = new URL(buildUrl(`/api/agents/${encodeURIComponent(agentName)}/artifacts/zip`, namespace), window.location.origin);
  const target = API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
  const response = await fetchAuthenticated(target, token);
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to download ZIP archive", text);
  }

  const blob = await response.blob();
  const filename = extractFilenameFromDisposition(response.headers.get("content-disposition"), `${agentName}-workspace.zip`);
  triggerBrowserDownload(blob, filename);
}

export interface AgentFileEntry {
  path: string;
  name: string;
  size: number;
  modified: number;
  directory: string;
}

export interface AgentFileListResult {
  files: AgentFileEntry[];
  truncated: boolean;
  roots: string[];
}

export async function listAgentArtifacts(
  token: string,
  namespace: string,
  agentName: string,
  root?: string,
): Promise<AgentFileListResult> {
  const url = new URL(buildUrl(`/api/agents/${encodeURIComponent(agentName)}/artifacts/list`, namespace), window.location.origin);
  if (root) url.searchParams.set("root", root);
  const target = API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
  const response = await fetchAuthenticated(target, token);
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to list artifacts", text);
  }
  return response.json();
}

export function buildInvocationSummary(fallbackThreadId: string, payload: unknown): InvocationSummary {
  const record = expectRecord(payload, "Invocation summary payload");
  const threadId = readOptionalString(record, "thread_id", "Invocation summary payload") ?? fallbackThreadId.trim();
  if (!threadId) {
    throw new Error("Invocation summary payload is missing thread_id.");
  }

  const continuity = record.continuity && typeof record.continuity === "object"
    ? expectRecord(record.continuity, "Invocation summary payload.continuity")
    : null;
  const metadata = record.metadata !== undefined && record.metadata !== null
    ? expectRecord(record.metadata, "Invocation summary payload.metadata") : null;
  const todos = (() => {
    const raw = metadata?.todos;
    if (!Array.isArray(raw)) return null;
    return raw.flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const todo = item as Record<string, unknown>;
      const content = String(todo.content ?? todo.title ?? "").trim();
      if (!content) return [];
      const status = String(todo.status ?? "pending").trim().toLowerCase();
      const priority = String(todo.priority ?? "medium").trim().toLowerCase();
      return [{
        content,
        status: (status === "in_progress" || status === "completed" || status === "cancelled" ? status : "pending") as "pending" | "in_progress" | "completed" | "cancelled",
        priority: (priority === "high" || priority === "low" ? priority : "medium") as "high" | "medium" | "low",
      }];
    });
  })();

  return {
    threadId,
    status: readString(record, "status", "Invocation summary payload", "completed"),
    policyName: readOptionalString(record, "policy_name", "Invocation summary payload"),
    toolName: readOptionalString(record, "tool_name", "Invocation summary payload"),
    toolResult: readOptionalJsonValue(record, "tool_result"),
    sandboxSession: readOptionalRecord(record, "sandbox_session", "Invocation summary payload"),
    approvalName: readOptionalString(record, "approval_name", "Invocation summary payload"),
    retryAfterSeconds: readOptionalNumber(record, "retry_after_seconds", "Invocation summary payload"),
    a2a:
      record.a2a === undefined || record.a2a === null
        ? null
        : parseA2AInvocationMetadataPayload(record.a2a, "Invocation summary payload.a2a"),
    subagents:
      record.subagents === undefined || record.subagents === null
        ? null
        : parseSubagentInvocationMetadataPayload(record.subagents, "Invocation summary payload.subagents"),
    warnings: record.warnings === undefined ? [] : readStringArray(record, "warnings", "Invocation summary payload"),
    artifacts: Array.isArray(record.artifacts) ? (record.artifacts as Array<Record<string, unknown>>) : null,
    toolCalls: Array.isArray(record.tool_calls) ? (record.tool_calls as Array<Record<string, unknown>>) : null,
    continuity: continuity ? {
      createdNewSession: readOptionalBoolean(continuity, "created_new_session", "Invocation continuity") ?? undefined,
      sessionRecovered: readOptionalBoolean(continuity, "session_recovered", "Invocation continuity") ?? undefined,
      hasPriorMemory: readOptionalBoolean(continuity, "has_prior_memory", "Invocation continuity") ?? undefined,
      memoryApplied: readOptionalBoolean(continuity, "memory_applied", "Invocation continuity") ?? undefined,
      memoryEntryCount: readOptionalNumber(continuity, "memory_entry_count", "Invocation continuity"),
      handoffResumed: readOptionalBoolean(continuity, "handoff_resumed", "Invocation continuity") ?? undefined,
      remoteSessionId: readOptionalString(continuity, "remote_session_id", "Invocation continuity"),
    } satisfies RuntimeContinuitySummary : null,
    todos,
    metadata,
  };
}

async function parseJsonResponse<T>(response: Response, parser: (payload: unknown) => T): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let detail = "";
    if (text) {
      try {
        const parsed = JSON.parse(text) as { detail?: unknown };
        detail = formatApiErrorDetail(parsed.detail ?? parsed);
      } catch {
        detail = text;
      }
    }
    const message = detail ? `Request failed with status ${response.status}: ${detail}` : `Request failed with status ${response.status}`;
    throw new ApiError(
      response.status,
      message,
      detail || undefined,
    );
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
  const response = await fetch(buildUrl("/api/v1/health"));
  return parseJsonResponse(response, parseGatewayHealthPayload);
}

export async function fetchNamespaces(token: string): Promise<string[]> {
  const response = await fetchAuthenticated(buildUrl("/api/namespaces"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "Namespaces");
    const ns = record.namespaces;
    if (!Array.isArray(ns)) return ["default"];
    return ns.filter((n): n is string => typeof n === "string");
  });
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  const response = await fetch(buildUrl("/api/v1/auth/config"), buildCredentialedInit());
  return parseJsonResponse(response, parseAuthConfigPayload);
}

export async function loginWithPassword(
  username: string,
  password: string,
  provider: "local" | "ldap" = "local",
): Promise<AuthSession> {
  const response = await fetch(
    buildUrl("/api/v1/auth/login"),
    buildCredentialedInit({
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password, provider }),
    }),
  );
  return parseJsonResponse(response, parseAuthSessionPayload);
}

export async function registerWithPassword(
  username: string,
  password: string,
  email?: string,
  displayName?: string,
): Promise<AuthSession> {
  const response = await fetch(
    buildUrl("/api/v1/auth/register"),
    buildCredentialedInit({
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username,
        password,
        email: email?.trim() || undefined,
        display_name: displayName?.trim() || undefined,
      }),
    }),
  );
  return parseJsonResponse(response, parseAuthSessionPayload);
}

/** Internal refresh used by the 401-retry logic in fetchAuthenticated. */
async function refreshAuthSessionInternal(): Promise<AuthSession> {
  const response = await fetch(
    buildUrl("/api/v1/auth/refresh"),
    buildCredentialedInit({
      method: "POST",
      headers: { Accept: "application/json" },
    }),
  );
  return parseJsonResponse(response, parseAuthSessionPayload);
}

export async function refreshAuthSession(): Promise<AuthSession> {
  return refreshAuthSessionInternal();
}

export async function logoutSession(token?: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/auth/logout"), token, {
    method: "POST",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Logout failed with status ${response.status}`);
  }
}

export async function fetchCurrentUser(token: string): Promise<AuthenticatedUser> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/auth/me"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "CurrentUserResponse");
    return parseAuthenticatedUserPayload(record.user, "CurrentUserResponse.user");
  });
}

export async function changePassword(token: string, currentPassword: string, newPassword: string): Promise<AuthenticatedUser> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/auth/change-password"), token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "ChangePasswordResponse");
    return parseAuthenticatedUserPayload(record.user, "ChangePasswordResponse.user");
  });
}

export async function listUsers(token: string): Promise<AdminUser[]> {
  const response = await fetchAuthenticated(buildUrl("/api/admin/users"), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Admin user list response must be an array.");
    }
    return payload.map((item, index) => parseAdminUserPayload(item, `AdminUser[${index}]`));
  });
}

export async function createUser(token: string, payload: CreateUserPayload): Promise<AdminUser> {
  const response = await fetchAuthenticated(buildUrl("/api/admin/users"), token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username: payload.username.trim(),
      password: payload.password,
      email: payload.email?.trim() || undefined,
      display_name: payload.display_name?.trim() || undefined,
      role: payload.role ?? "viewer",
      allowed_namespaces: payload.allowed_namespaces?.map((item) => item.trim()).filter(Boolean) ?? [],
    }),
  });
  return parseJsonResponse(response, (payloadBody) => parseAdminUserPayload(payloadBody, "AdminUser"));
}

export async function updateUser(token: string, userId: number, payload: UpdateUserPayload): Promise<AdminUser> {
  const response = await fetchAuthenticated(buildUrl(`/api/admin/users/${userId}`), token, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      display_name: payload.display_name?.trim() || undefined,
      role: payload.role,
      is_active: payload.is_active,
      allowed_namespaces: payload.allowed_namespaces?.map((item) => item.trim()).filter(Boolean),
    }),
  });
  return parseJsonResponse(response, (payloadBody) => parseAdminUserPayload(payloadBody, "AdminUser"));
}

/* ── Audit Logs ── */

export interface AuditLogEntry {
  id: number;
  timestamp: string | null;
  actor: string | null;
  actor_type: string | null;
  action: string;
  resource_kind: string | null;
  resource_name: string | null;
  namespace: string | null;
  detail: Record<string, unknown> | null;
  ip_address: string | null;
  request_id: string | null;
}

export interface AuditLogResponse {
  items: AuditLogEntry[];
  total: number;
}

export async function fetchAuditLogs(
  token: string,
  filters: {
    actor?: string;
    actor_type?: string;
    action?: string;
    resource_kind?: string;
    resource_name?: string;
    namespace?: string;
    from_date?: string;
    to_date?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<AuditLogResponse> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const url = buildUrl(`/api/admin/audit${params.toString() ? `?${params}` : ""}`);
  const response = await fetchAuthenticated(url, token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "AuditLogResponse");
    return {
      items: (record.items as AuditLogEntry[]) ?? [],
      total: (record.total as number) ?? 0,
    };
  });
}

export async function purgeAuditLogs(token: string): Promise<{ deleted: number }> {
  const response = await fetchAuthenticated(buildUrl("/api/admin/audit/purge"), token, {
    method: "DELETE",
  });
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "PurgeResult");
    return { deleted: (record.deleted as number) ?? 0 };
  });
}

// ── Token Usage & Cost Tracking ──

export interface UsageSummaryItem {
  group: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  invocations: number;
}

export interface UsageDetailItem {
  id: number;
  timestamp: string | null;
  agent_name: string;
  namespace: string;
  user_id: string | null;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  session_id: string | null;
  request_id: string | null;
}

export interface UsageDetailResponse {
  items: UsageDetailItem[];
  total: number;
}

export async function fetchUsageSummary(
  token: string,
  params: {
    namespace?: string;
    group_by?: string;
    from_date?: string;
    to_date?: string;
  } = {},
): Promise<UsageSummaryItem[]> {
  const url = new URL(buildUrl("/api/usage/summary"), API_BASE_URL || window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v) url.searchParams.set(k, v);
  }
  const target = API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
  const response = await fetchAuthenticated(target, token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "UsageSummary");
    return (record.items as UsageSummaryItem[]) ?? [];
  });
}

export async function fetchUsageDetail(
  token: string,
  params: {
    namespace?: string;
    agent_name?: string;
    model?: string;
    from_date?: string;
    to_date?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<UsageDetailResponse> {
  const url = new URL(buildUrl("/api/usage/detail"), API_BASE_URL || window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }
  const target = API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
  const response = await fetchAuthenticated(target, token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "UsageDetail");
    return {
      items: (record.items as UsageDetailItem[]) ?? [],
      total: (record.total as number) ?? 0,
    };
  });
}

export function buildOidcLoginUrl(providerId: string, nextPath = window.location.pathname): string {
  const url = new URL(buildUrl(`/api/auth/oidc/start/${providerId}`), API_BASE_URL || window.location.origin);
  url.searchParams.set("next", nextPath || "/");
  return API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
}

export function buildSamlLoginUrl(providerId: string, nextPath = window.location.pathname): string {
  const url = new URL(buildUrl(`/api/auth/saml/start/${providerId}`), API_BASE_URL || window.location.origin);
  url.searchParams.set("next", nextPath || "/");
  return API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
}

export async function listAgents(token: string, namespace: string): Promise<AgentInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/agents", namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Agent list response must be an array.");
    }
    return payload.map((item, index) => parseAgentInfoPayload(item, `AgentInfo[${index}]`));
  });
}

export async function listPolicies(token: string, namespace: string): Promise<PolicyInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/policies", namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Policy list response must be an array.");
    }
    return payload.map((item, index) => parsePolicyInfoPayload(item ?? {}, `PolicyInfo[${index}]`));
  });
}

export interface CreatePolicyPayload {
  name: string;
  sealed?: boolean;
  input_guardrails: PolicyInputGuardrails;
  output_guardrails: PolicyOutputGuardrails;
  allowed_models: string[];
  allowed_mcp_servers: string[];
  mcp_require_hitl: boolean;
  tool_policy: PolicyToolPolicy;
  memory_policy: PolicyMemoryPolicy;
}

export type UpdatePolicyPayload = Partial<Omit<CreatePolicyPayload, "name">>;

export interface MemoryRecordInfo {
  id: number;
  namespace: string;
  agent_name: string;
  session_id: string | null;
  memory_type: string;
  topic: string | null;
  promoted: boolean;
  score: number;
  promote_reason: string | null;
  content: string;
  detail_json: Record<string, unknown> | null;
  username: string | null;
  created_at: string | null;
}

export async function fetchPolicy(token: string, namespace: string, name: string): Promise<PolicyInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/policies/${name}`, namespace), token);
  return parseJsonResponse(response, parsePolicyInfoPayload);
}

export async function createPolicy(token: string, namespace: string, payload: CreatePolicyPayload): Promise<PolicyInfo> {
  const response = await fetchAuthenticated(buildUrl("/api/policies", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parsePolicyInfoPayload);
}

export async function updatePolicy(token: string, namespace: string, name: string, payload: UpdatePolicyPayload): Promise<PolicyInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/policies/${name}`, namespace), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parsePolicyInfoPayload);
}

export async function listAgentMemory(
  token: string,
  namespace: string,
  agentName: string,
  sessionId?: string | null,
): Promise<MemoryRecordInfo[]> {
  const url = buildUrl(`/api/agents/${agentName}/memory`, namespace);
  const fullUrl = sessionId
    ? `${url}${url.includes("?") ? "&" : "?"}session_id=${encodeURIComponent(sessionId)}`
    : url;
  const response = await fetchAuthenticated(fullUrl, token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item) => {
      const record = expectRecord(item, "MemoryRecordInfo");
      return {
        id: readOptionalNumber(record, "id", "MemoryRecordInfo") ?? 0,
        namespace: readString(record, "namespace", "MemoryRecordInfo"),
        agent_name: readString(record, "agent_name", "MemoryRecordInfo"),
        session_id: readOptionalString(record, "session_id", "MemoryRecordInfo"),
        memory_type: readString(record, "memory_type", "MemoryRecordInfo"),
        topic: readOptionalString(record, "topic", "MemoryRecordInfo"),
        promoted: readOptionalBoolean(record, "promoted", "MemoryRecordInfo") ?? false,
        score: readOptionalNumber(record, "score", "MemoryRecordInfo") ?? 0,
        promote_reason: readOptionalString(record, "promote_reason", "MemoryRecordInfo"),
        content: readString(record, "content", "MemoryRecordInfo"),
        detail_json: readOptionalRecord(record, "detail_json", "MemoryRecordInfo"),
        username: readOptionalString(record, "username", "MemoryRecordInfo"),
        created_at: readOptionalString(record, "created_at", "MemoryRecordInfo"),
      } satisfies MemoryRecordInfo;
    });
  });
}

export async function deletePolicy(token: string, namespace: string, name: string): Promise<DeleteResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/policies/${name}`, namespace), token, {
    method: "DELETE",
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export async function updateMemoryRecord(
  token: string,
  recordId: number,
  patch: { promoted?: boolean; topic?: string; content?: string },
): Promise<MemoryRecordInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/memory/${recordId}`), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "MemoryRecordInfo");
    return {
      id: readOptionalNumber(record, "id", "MemoryRecordInfo") ?? 0,
      namespace: readString(record, "namespace", "MemoryRecordInfo"),
      agent_name: readString(record, "agent_name", "MemoryRecordInfo"),
      session_id: readOptionalString(record, "session_id", "MemoryRecordInfo"),
      memory_type: readString(record, "memory_type", "MemoryRecordInfo"),
      topic: readOptionalString(record, "topic", "MemoryRecordInfo"),
      promoted: readOptionalBoolean(record, "promoted", "MemoryRecordInfo") ?? false,
      score: readOptionalNumber(record, "score", "MemoryRecordInfo") ?? 0,
      promote_reason: readOptionalString(record, "promote_reason", "MemoryRecordInfo"),
      content: readString(record, "content", "MemoryRecordInfo"),
      detail_json: readOptionalRecord(record, "detail_json", "MemoryRecordInfo"),
      username: readOptionalString(record, "username", "MemoryRecordInfo"),
      created_at: readOptionalString(record, "created_at", "MemoryRecordInfo"),
    } satisfies MemoryRecordInfo;
  });
}

export async function deleteMemoryRecord(token: string, recordId: number): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/memory/${recordId}`), token, { method: "DELETE" });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to delete memory record", text);
  }
}

export async function createAgent(
  token: string,
  namespace: string,
  payload: CreateAgentPayload,
): Promise<AgentDetail> {
  const response = await fetchAuthenticated(buildUrl("/api/agents", namespace), token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseAgentDetailPayload);
}

export async function fetchAgent(token: string, namespace: string, agentName: string): Promise<AgentDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/agents/${agentName}`, namespace), token);
  return parseJsonResponse(response, parseAgentDetailPayload);
}

export async function fetchAgentManifest(token: string, namespace: string, agentName: string): Promise<Record<string, unknown>> {
  const response = await fetchAuthenticated(buildUrl(`/api/agents/${agentName}/manifest`, namespace), token);
  return parseJsonResponse(response, (payload) => expectRecord(payload, "AgentManifest"));
}

export async function discoverAgentPeers(
  token: string,
  namespace: string,
  agentName: string,
): Promise<AgentDiscoveryResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/agents/${agentName}/discover`, namespace), token);
  return parseJsonResponse(response, parseAgentDiscoveryResponsePayload);
}

export async function updateAgent(
  token: string,
  namespace: string,
  agentName: string,
  payload: UpdateAgentPayload,
): Promise<AgentDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/agents/${agentName}`, namespace), token, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseAgentDetailPayload);
}

export async function deleteAgent(token: string, namespace: string, agentName: string): Promise<DeleteResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/agents/${agentName}`, namespace), token, {
    method: "DELETE",
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export async function cloneAgent(
  token: string,
  namespace: string,
  agentName: string,
  newName?: string,
): Promise<AgentDetail> {
  const url = new URL(buildUrl(`/api/agents/${agentName}/clone`, namespace), API_BASE_URL || window.location.origin);
  if (newName) url.searchParams.set("new_name", newName);
  const target = API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
  const response = await fetchAuthenticated(target, token, { method: "POST" });
  return parseJsonResponse(response, (p) => parseAgentDetailPayload(p as Record<string, unknown>));
}

export function exportBundleUrl(token: string, namespace: string): string {
  const url = buildUrl("/api/export/bundle", namespace);
  return `${url}&token=${encodeURIComponent(token)}`;
}

export async function importBundle(token: string, namespace: string, yamlContent: string): Promise<{ imported: number; results: Array<Record<string, string>> }> {
  const response = await fetchAuthenticated(buildUrl("/api/import/bundle", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/x-yaml" },
    body: yamlContent,
  });
  return parseJsonResponse(response, (p) => p as { imported: number; results: Array<Record<string, string>> });
}

export interface SystemHealth {
  status: string;
  namespace: string;
  auth_mode: string;
  checks: Record<string, Record<string, unknown>>;
  timestamp: string;
}

export async function fetchSystemHealth(token: string, namespace: string): Promise<SystemHealth> {
  const response = await fetchAuthenticated(buildUrl("/api/system/health", namespace), token);
  return parseJsonResponse(response, (p) => p as SystemHealth);
}

export async function invokeAgent(
  token: string,
  namespace: string,
  agentName: string,
  payload: InvokePayload,
  requestId: string,
): Promise<InvokeResponse> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/v1/agents/${agentName}/invoke`, namespace),
    token,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
    requestId,
  );
  return parseJsonResponse(response, parseInvokeResponsePayload);
}

export async function fetchAgentLogs(
  token: string,
  namespace: string,
  agentName: string,
  tail?: number,
): Promise<AgentLogsResponse> {
  const url = buildUrl(`/api/agents/${agentName}/logs`, namespace);
  const fullUrl = tail ? `${url}${url.includes("?") ? "&" : "?"}tail=${tail}` : url;
  const response = await fetchAuthenticated(fullUrl, token);
  return parseJsonResponse(response, parseAgentLogsResponsePayload);
}

export interface LogStreamHandlers {
  signal: AbortSignal;
  token: string;
  namespace: string;
  agentName: string;
  tail?: number;
  onLine: (line: string) => void;
  onStarted: (info: { agent_name: string; pod_name: string }) => void;
  onError: (error: Error) => void;
  onStopped: () => void;
}

export async function streamAgentLogs(options: LogStreamHandlers): Promise<void> {
  const url = buildUrl(`/api/agents/${options.agentName}/logs/stream`, options.namespace);
  const fullUrl = options.tail ? `${url}${url.includes("?") ? "&" : "?"}tail=${options.tail}` : url;

  await fetchEventSource(fullUrl, {
    fetch: buildEventSourceFetch(options.token),
    headers: {
      ...buildHeaders(options.token),
      Accept: "text/event-stream",
    },
    signal: options.signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) {
        throw new Error(`Log stream failed with status ${response.status}`);
      }
    },
    onmessage(message) {
      if (!message.event || !message.data) return;
      try {
        const data = JSON.parse(message.data);
        switch (message.event) {
          case "log.line":
            if (typeof data.line === "string") options.onLine(data.line);
            break;
          case "log.started":
            options.onStarted(data);
            break;
          case "log.error":
            options.onError(new Error(data.error ?? "Unknown log stream error"));
            break;
          case "log.stopped":
            options.onStopped();
            break;
        }
      } catch (parseErr) {
        options.onError(new Error(`Failed to parse log event: ${parseErr instanceof Error ? parseErr.message : String(parseErr)}`));
      }
    },
    onerror(error) {
      options.onError(error instanceof Error ? error : new Error(String(error)));
      throw error; // stop reconnection
    },
    onclose() {
      options.onStopped();
    },
  });
}

export interface WorkflowLogStreamHandlers {
  signal: AbortSignal;
  token: string;
  namespace: string;
  workflowName: string;
  tail?: number;
  onLine: (line: string) => void;
  onStarted: (info: { workflow_name: string; job_name?: string; pod_name?: string }) => void;
  onError: (error: Error) => void;
  onStopped: () => void;
}

export async function fetchWorkflowLogs(
  token: string,
  namespace: string,
  workflowName: string,
  tail?: number,
): Promise<WorkflowLogsResponse> {
  const url = buildUrl(`/api/workflows/${workflowName}/logs`, namespace);
  const fullUrl = tail ? `${url}${url.includes("?") ? "&" : "?"}tail=${tail}` : url;
  const response = await fetchAuthenticated(fullUrl, token);
  return parseJsonResponse(response, parseWorkflowLogsResponsePayload);
}

export async function streamWorkflowLogs(options: WorkflowLogStreamHandlers): Promise<void> {
  const url = buildUrl(`/api/workflows/${options.workflowName}/logs/stream`, options.namespace);
  const fullUrl = options.tail ? `${url}${url.includes("?") ? "&" : "?"}tail=${options.tail}` : url;

  await fetchEventSource(fullUrl, {
    fetch: buildEventSourceFetch(options.token),
    headers: {
      ...buildHeaders(options.token),
      Accept: "text/event-stream",
    },
    signal: options.signal,
    openWhenHidden: true,
    async onopen(response) {
      if (!response.ok) {
        throw new Error(`Workflow log stream failed with status ${response.status}`);
      }
    },
    onmessage(message) {
      if (!message.event || !message.data) return;
      try {
        const data = JSON.parse(message.data);
        switch (message.event) {
          case "log.line":
            if (typeof data.line === "string") options.onLine(data.line);
            break;
          case "log.started":
            options.onStarted(data);
            break;
          case "log.error":
            options.onError(new Error(data.error ?? "Unknown workflow log stream error"));
            break;
          case "log.stopped":
            options.onStopped();
            break;
        }
      } catch (parseErr) {
        options.onError(new Error(`Failed to parse workflow log event: ${parseErr instanceof Error ? parseErr.message : String(parseErr)}`));
      }
    },
    onerror(error) {
      options.onError(error instanceof Error ? error : new Error(String(error)));
      throw error;
    },
    onclose() {
      options.onStopped();
    },
  });
}

export async function decideApproval(
  token: string,
  namespace: string,
  approvalName: string,
  decision: "approved" | "denied",
  reason?: string,
): Promise<ApprovalInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/approvals/${approvalName}`, namespace), token, {
    method: "PATCH",
    headers: {
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
  const response = await fetchAuthenticated(buildUrl("/api/workflows", namespace), token);
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
  const response = await fetchAuthenticated(buildUrl("/api/workflows", namespace), token, {
    method: "POST",
    headers: {
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
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}`, namespace), token, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function fetchWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
): Promise<WorkflowInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}`, namespace), token);
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function fetchWorkflowManifest(token: string, namespace: string, workflowName: string): Promise<Record<string, unknown>> {
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}/manifest`, namespace), token);
  return parseJsonResponse(response, (payload) => expectRecord(payload, "WorkflowManifest"));
}

export async function triggerWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
  input?: string,
  factoryMode?: FactoryMode,
): Promise<WorkflowInfo> {
  const payload: Record<string, unknown> = {};
  if (input !== undefined) {
    payload.input = input;
  }
  if (factoryMode !== undefined) {
    payload.factory_mode = factoryMode;
  }
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}/trigger`, namespace), token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function cancelWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
): Promise<WorkflowInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}/cancel`, namespace), token, {
    method: "POST",
  });
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function retryFailedSteps(
  token: string,
  namespace: string,
  workflowName: string,
): Promise<WorkflowInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}/retry-failed`, namespace), token, {
    method: "POST",
  });
  return parseJsonResponse(response, parseWorkflowInfoPayload);
}

export async function deleteWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
): Promise<DeleteResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/workflows/${workflowName}`, namespace), token, {
    method: "DELETE",
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export interface WorkflowRunRecord {
  id: number;
  run_id: string | null;
  phase: string;
  total_steps: number | null;
  completed_steps: number | null;
  failed_steps: number | null;
  started_at: string | null;
  completed_at: string | null;
  triggered_by: string | null;
  input_text: string | null;
  created_at: string | null;
  trace_available: boolean;
  archived_log_available: boolean;
  journal_available: boolean;
}

export async function fetchWorkflowRuns(
  token: string,
  namespace: string,
  workflowName: string,
  limit = 20,
): Promise<WorkflowRunRecord[]> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/workflows/${workflowName}/runs`, namespace) + `&limit=${limit}`,
    token,
  );
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) throw new Error("Expected array of workflow runs");
    return payload.map((item, index) => parseWorkflowRunRecordPayload(item, `WorkflowRunRecord[${index}]`));
  });
}

export async function fetchWorkflowRunTrace(
  token: string,
  namespace: string,
  workflowName: string,
  runId: string,
  tail = 4000,
): Promise<WorkflowRunTraceResponse> {
  const url = buildUrl(`/api/workflows/${workflowName}/runs/${runId}/trace`, namespace);
  const fullUrl = `${url}${url.includes("?") ? "&" : "?"}tail=${tail}`;
  const response = await fetchAuthenticated(fullUrl, token);
  return parseJsonResponse(response, parseWorkflowRunTraceResponsePayload);
}

export async function downloadWorkflowRunTraceExport(
  token: string,
  namespace: string,
  workflowName: string,
  runId: string,
): Promise<void> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/workflows/${workflowName}/runs/${runId}/export`, namespace),
    token,
  );
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to export workflow run trace", text);
  }
  const blob = await response.blob();
  const filename = extractFilenameFromDisposition(
    response.headers.get("content-disposition"),
    `${workflowName}-${runId}-trace.json`,
  );
  triggerBrowserDownload(blob, filename);
}

/* ── Execution Observatory API ── */

export interface ExecutionListItem {
  id: string;
  workflow_name: string;
  namespace: string;
  agent_name?: string | null;
  run_id?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  step_count: number;
  llm_call_count: number;
  tool_call_count: number;
  total_tokens: number;
  total_cost_usd?: number | null;
  triggered_by?: string | null;
}

export interface ExecutionListResponse {
  items: ExecutionListItem[];
  total: number;
  limit: number;
  offset: number;
}

export async function listExecutions(
  token: string,
  namespace: string,
  filters: {
    workflow?: string;
    agent?: string;
    run_id?: string;
    execution_kind?: "workflow" | "invoke" | "all";
    status?: string;
    from_date?: string;
    to_date?: string;
    search?: string;
    sort_by?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<ExecutionListResponse> {
  const url = new URL(buildUrl("/api/traces/executions", namespace), API_BASE_URL || window.location.origin);
  for (const [k, v] of Object.entries(filters)) {
    if (v === undefined || v === null || v === "") continue;
    const normalizedKey = {
      workflow: "workflow_name",
      agent: "agent_name",
      run_id: "run_id",
      execution_kind: "execution_kind",
      sort_by: "sort_by",
      from_date: "from_date",
      to_date: "to_date",
      search: "search",
      status: "status",
      limit: "limit",
      offset: "offset",
    }[k] ?? k;
    const normalizedValue =
      normalizedKey === "sort_by"
        ? ({
            started_at_desc: "newest",
            started_at_asc: "oldest",
            duration_desc: "newest",
            duration_asc: "oldest",
          }[String(v)] ?? String(v))
        : String(v);
    url.searchParams.set(normalizedKey, normalizedValue);
  }
  const target = API_BASE_URL ? url.toString() : `${url.pathname}${url.search}`;
  const response = await fetchAuthenticated(target, token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "ExecutionListResponse");
    const items = Array.isArray(record.items) ? record.items : [];
    return {
      items: items.map((item: unknown, index: number) => {
        const r = expectRecord(item, `ExecutionListItem[${index}]`);
        return {
          id: readString(r, "id", `ExecutionListItem[${index}]`),
          workflow_name: readString(r, "workflow_name", `ExecutionListItem[${index}]`),
          namespace: readString(r, "namespace", `ExecutionListItem[${index}]`),
          agent_name: readOptionalString(r, "agent_name", `ExecutionListItem[${index}]`),
          run_id: readOptionalString(r, "run_id", `ExecutionListItem[${index}]`),
          status: readString(r, "status", `ExecutionListItem[${index}]`, "unknown"),
          started_at: readOptionalString(r, "started_at", `ExecutionListItem[${index}]`),
          completed_at: readOptionalString(r, "completed_at", `ExecutionListItem[${index}]`),
          duration_ms: readOptionalNumber(r, "duration_ms", `ExecutionListItem[${index}]`),
          step_count:
            readOptionalNumber(r, "step_count", `ExecutionListItem[${index}]`) ??
            readOptionalNumber(r, "total_steps", `ExecutionListItem[${index}]`) ??
            0,
          llm_call_count:
            readOptionalNumber(r, "llm_call_count", `ExecutionListItem[${index}]`) ??
            readOptionalNumber(r, "total_llm_calls", `ExecutionListItem[${index}]`) ??
            0,
          tool_call_count:
            readOptionalNumber(r, "tool_call_count", `ExecutionListItem[${index}]`) ??
            readOptionalNumber(r, "total_tool_calls", `ExecutionListItem[${index}]`) ??
            0,
          total_tokens: readOptionalNumber(r, "total_tokens", `ExecutionListItem[${index}]`) ?? 0,
          total_cost_usd:
            readOptionalNumber(r, "total_cost_usd", `ExecutionListItem[${index}]`) ??
            readOptionalNumber(r, "estimated_cost_usd", `ExecutionListItem[${index}]`),
          triggered_by: readOptionalString(r, "triggered_by", `ExecutionListItem[${index}]`),
        } satisfies ExecutionListItem;
      }),
      total: readOptionalNumber(record, "total", "ExecutionListResponse") ?? 0,
      limit: readOptionalNumber(record, "limit", "ExecutionListResponse") ?? 20,
      offset: readOptionalNumber(record, "offset", "ExecutionListResponse") ?? 0,
    };
  });
}

export async function fetchExecutionDetail(token: string, executionId: string): Promise<ExecutionTrace> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/executions/${executionId}`), token);
  return parseJsonResponse(response, parseExecutionTracePayload);
}

export async function fetchExecutionSummary(token: string, executionId: string): Promise<ExecutionTrace> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/executions/${executionId}/summary`), token);
  return parseJsonResponse(response, parseExecutionTracePayload);
}

export async function fetchStepDetail(token: string, stepId: string): Promise<StepTrace> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/steps/${stepId}`), token);
  return parseJsonResponse(response, parseStepTracePayload);
}

export async function fetchExecutionEvents(token: string, executionId: string): Promise<TraceEvent[]> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/executions/${executionId}/events`), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item, index) => parseTraceEventPayload(item, `TraceEvent[${index}]`));
  });
}

export async function deleteExecution(token: string, executionId: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/executions/${executionId}`), token, {
    method: "DELETE",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to delete execution", text);
  }
}

export async function exportExecutionJson(token: string, executionId: string): Promise<string> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/executions/${executionId}/export/json`), token, {
    method: "POST",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to export execution JSON", text);
  }
  return response.text();
}

export async function exportExecutionHtml(token: string, executionId: string): Promise<string> {
  const response = await fetchAuthenticated(buildUrl(`/api/traces/executions/${executionId}/export/html`), token);
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to export execution HTML", text);
  }
  return response.text();
}

function parseTraceEventPayload(payload: unknown, label = "TraceEvent"): TraceEvent {
  const record = expectRecord(payload, label);
  const rawTimestamp = record.timestamp;
  const rawEventType = readString(record, "event_type", label, "custom");
  const payloadRecord = readRecord(record, "payload", label, {});
  const timestamp =
    typeof rawTimestamp === "number" && Number.isFinite(rawTimestamp)
      ? new Date((rawTimestamp > 1_000_000_000_000 ? rawTimestamp : rawTimestamp * 1000)).toISOString()
      : readString(record, "timestamp", label);
  const stepId =
    readOptionalString(record, "step_id", label) ??
    readOptionalString(payloadRecord, "step_id", `${label}.payload`) ??
    readOptionalString(payloadRecord, "step_name", `${label}.payload`);
  return {
    id: readString(
      record,
      "id",
      label,
      `${readString(record, "execution_id", label, "execution")}:${rawEventType}:${String(rawTimestamp ?? "")}`,
    ),
    execution_id: readString(record, "execution_id", label),
    event_type: rawEventType.toUpperCase() as TraceEvent["event_type"],
    timestamp,
    step_id: stepId,
    payload: payloadRecord,
  };
}

function parseLLMCallRecordPayload(payload: unknown, label = "LLMCallRecord"): LLMCallRecord {
  const record = expectRecord(payload, label);
  return {
    id: readString(record, "id", label),
    step_id: readOptionalString(record, "step_id", label),
    execution_id: readOptionalString(record, "execution_id", label) ?? "",
    model: readString(record, "model", label, ""),
    provider: readOptionalString(record, "provider", label),
    prompt_tokens: readOptionalNumber(record, "prompt_tokens", label) ?? 0,
    completion_tokens: readOptionalNumber(record, "completion_tokens", label) ?? 0,
    cache_read_tokens: readOptionalNumber(record, "cache_read_tokens", label),
    cache_write_tokens: readOptionalNumber(record, "cache_write_tokens", label),
    reasoning_tokens: readOptionalNumber(record, "reasoning_tokens", label),
    total_tokens: readOptionalNumber(record, "total_tokens", label) ?? 0,
    estimated_cost_usd:
      readOptionalNumber(record, "estimated_cost_usd", label) ??
      readOptionalNumber(record, "cost_usd", label),
    latency_ms: readOptionalNumber(record, "latency_ms", label) ?? 0,
    prompt_preview: readOptionalString(record, "prompt_preview", label),
    response_preview: readOptionalString(record, "response_preview", label),
    created_at:
      readOptionalString(record, "created_at", label) ??
      readOptionalString(record, "started_at", label) ??
      "",
  };
}

function parseToolCallRecordPayload(payload: unknown, label = "ToolCallRecord"): ToolCallRecord {
  const record = expectRecord(payload, label);
  const toolResult = readOptionalJsonValue(record, "tool_result");
  const toolArgs = readOptionalJsonValue(record, "tool_args");
  const errorMessage = readOptionalString(record, "error_message", label);
  return {
    id: readString(record, "id", label),
    step_id: readOptionalString(record, "step_id", label),
    execution_id: readOptionalString(record, "execution_id", label) ?? "",
    tool_name: readString(record, "tool_name", label, ""),
    tool_args: (toolArgs as Record<string, unknown> | null) ?? null,
    tool_result: toolResult,
    args_preview:
      readOptionalString(record, "args_preview", label) ??
      (toolArgs === null ? null : JSON.stringify(toolArgs, null, 2)),
    result_preview:
      readOptionalString(record, "result_preview", label) ??
      (toolResult === null ? errorMessage : JSON.stringify(toolResult, null, 2)),
    duration_ms: readOptionalNumber(record, "duration_ms", label),
    latency_ms:
      readOptionalNumber(record, "latency_ms", label) ??
      readOptionalNumber(record, "duration_ms", label) ??
      0,
    status: readString(record, "status", label, errorMessage ? "failed" : "completed"),
    error_message: errorMessage,
    started_at: readOptionalString(record, "started_at", label),
    created_at:
      readOptionalString(record, "created_at", label) ??
      readOptionalString(record, "started_at", label) ??
      "",
  };
}

function parseStepTracePayload(payload: unknown, label = "StepTrace"): StepTrace {
  const record = expectRecord(payload, label);
  const rawLlmCalls = record.llm_calls;
  const rawToolCalls = record.tool_calls;
  const inputSummary = readOptionalJsonValue(record, "input_summary");
  const outputSummary = readOptionalJsonValue(record, "output_summary");
  return {
    id: readString(record, "id", label),
    execution_id: readOptionalString(record, "execution_id", label) ?? "",
    name: readString(record, "name", label, readString(record, "step_name", label, "")),
    step_index:
      readOptionalNumber(record, "step_index", label) ??
      readOptionalNumber(record, "index", label),
    step_type:
      readOptionalString(record, "step_type", label) ??
      readOptionalString(record, "type", label),
    parent_step_id: readOptionalString(record, "parent_step_id", label),
    status: readString(record, "status", label, "unknown"),
    started_at: readOptionalString(record, "started_at", label),
    completed_at: readOptionalString(record, "completed_at", label),
    latency_ms:
      readOptionalNumber(record, "latency_ms", label) ??
      readOptionalNumber(record, "duration_ms", label),
    error: readOptionalString(record, "error", label) ?? readOptionalString(record, "error_message", label),
    tokens_used: readOptionalNumber(record, "tokens_used", label),
    cache_read_tokens: readOptionalNumber(record, "cache_read_tokens", label),
    cache_write_tokens: readOptionalNumber(record, "cache_write_tokens", label),
    reasoning_tokens: readOptionalNumber(record, "reasoning_tokens", label),
    cost_usd: readOptionalNumber(record, "cost_usd", label),
    llm_call_count: readOptionalNumber(record, "llm_calls_count", label) ?? 0,
    tool_call_count: readOptionalNumber(record, "tool_calls_count", label) ?? 0,
    llm_calls: Array.isArray(rawLlmCalls)
      ? rawLlmCalls.map((item, index) => parseLLMCallRecordPayload(item, `${label}.llm_calls[${index}]`))
      : [],
    tool_calls: Array.isArray(rawToolCalls)
      ? rawToolCalls.map((item, index) => parseToolCallRecordPayload(item, `${label}.tool_calls[${index}]`))
      : [],
    input_preview:
      readOptionalString(record, "input_preview", label) ??
      (inputSummary === null ? null : JSON.stringify(inputSummary, null, 2)),
    output_preview:
      readOptionalString(record, "output_preview", label) ??
      (outputSummary === null ? null : JSON.stringify(outputSummary, null, 2)),
  };
}

function parseExecutionTracePayload(payload: unknown, label = "ExecutionTrace"): ExecutionTrace {
  const record = expectRecord(payload, label);
  const rawSteps = record.steps;
  const rawLlmCalls = record.llm_calls;
  const rawToolCalls = record.tool_calls;
  const rawEvents = record.events;
  const inputSummary = readOptionalJsonValue(record, "input_summary");
  const outputSummary = readOptionalJsonValue(record, "output_summary");
  return {
    id: readString(record, "id", label),
    workflow_name: readString(record, "workflow_name", label, ""),
    namespace: readString(record, "namespace", label, ""),
    agent_name: readOptionalString(record, "agent_name", label),
    run_id: readOptionalString(record, "run_id", label),
    triggered_by: readOptionalString(record, "triggered_by", label),
    status: readString(record, "status", label, "unknown"),
    started_at: readOptionalString(record, "started_at", label),
    completed_at: readOptionalString(record, "completed_at", label),
    created_at: readOptionalString(record, "created_at", label),
    duration_ms: readOptionalNumber(record, "duration_ms", label),
    error_message: readOptionalString(record, "error_message", label),
    trace_file_path: readOptionalString(record, "trace_file_path", label),
    input_preview:
      readOptionalString(record, "input_preview", label) ??
      (inputSummary === null ? null : JSON.stringify(inputSummary, null, 2)),
    output_preview:
      readOptionalString(record, "output_preview", label) ??
      (outputSummary === null ? null : JSON.stringify(outputSummary, null, 2)),
    step_count:
      readOptionalNumber(record, "step_count", label) ??
      readOptionalNumber(record, "total_steps", label) ??
      0,
    completed_steps: readOptionalNumber(record, "completed_steps", label),
    failed_steps: readOptionalNumber(record, "failed_steps", label),
    llm_call_count:
      readOptionalNumber(record, "llm_call_count", label) ??
      readOptionalNumber(record, "total_llm_calls", label) ??
      0,
    tool_call_count:
      readOptionalNumber(record, "tool_call_count", label) ??
      readOptionalNumber(record, "total_tool_calls", label) ??
      0,
    total_tokens: readOptionalNumber(record, "total_tokens", label) ?? 0,
    prompt_tokens: readOptionalNumber(record, "prompt_tokens", label),
    completion_tokens: readOptionalNumber(record, "completion_tokens", label),
    cache_read_tokens: readOptionalNumber(record, "cache_read_tokens", label),
    cache_write_tokens: readOptionalNumber(record, "cache_write_tokens", label),
    reasoning_tokens: readOptionalNumber(record, "reasoning_tokens", label),
    total_cost_usd:
      readOptionalNumber(record, "total_cost_usd", label) ??
      readOptionalNumber(record, "estimated_cost_usd", label),
    steps: Array.isArray(rawSteps)
      ? rawSteps.map((item, index) => parseStepTracePayload(item, `${label}.steps[${index}]`))
      : [],
    llm_calls: Array.isArray(rawLlmCalls)
      ? rawLlmCalls.map((item, index) => parseLLMCallRecordPayload(item, `${label}.llm_calls[${index}]`))
      : [],
    tool_calls: Array.isArray(rawToolCalls)
      ? rawToolCalls.map((item, index) => parseToolCallRecordPayload(item, `${label}.tool_calls[${index}]`))
      : [],
    events: Array.isArray(rawEvents)
      ? rawEvents.map((item, index) => parseTraceEventPayload(item, `${label}.events[${index}]`))
      : [],
  };
}

export async function fetchWorkflowNextAction(
  token: string,
  namespace: string,
  workflowName: string,
): Promise<WorkflowNextAction> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/workflows/${workflowName}/next-action`, namespace),
    token,
  );
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "WorkflowNextAction");
    return {
      action: readString(record, "action", "WorkflowNextAction"),
      reason: readString(record, "reason", "WorkflowNextAction"),
      failedSteps: Array.isArray(record.failedSteps)
        ? record.failedSteps.map((value) => String(value))
        : undefined,
      rejectedReviews: Array.isArray(record.rejectedReviews)
        ? record.rejectedReviews.map((value) => String(value))
        : undefined,
      verifyFailures: Array.isArray(record.verifyFailures)
        ? record.verifyFailures.map((value) => String(value))
        : undefined,
    };
  });
}

/**
 * EventSource-compatible wrapper built on top of {@link fetchEventSource}.
 *
 * The native `EventSource` constructor does not allow setting custom
 * request headers, which forces callers to pass the auth token in the
 * URL query string. Tokens in query strings end up in reverse-proxy
 * access logs, browser history, and HTTP Referer headers, so the
 * helper below routes the token through the standard `Authorization`
 * header instead.
 *
 * The wrapper exposes the subset of the `EventSource` API used by the
 * existing call sites (`.close()`, `.addEventListener(name, handler)`,
 * `.onmessage`, `.onerror`, `.onopen`) so consumers do not need to
 * change.
 */
interface EventSourceLike {
  close(): void;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onopen: ((event: Event) => void) | null;
  readyState: number;
}

function createHeaderEventSource(
  url: string,
  token: string,
  extraQuery: Record<string, string | number> = {},
): EventSourceLike {
  const controller = new AbortController();
  const listeners = new Map<string, Set<(event: MessageEvent) => void>>();
  const compat: EventSourceLike = {
    close(): void {
      controller.abort();
    },
    addEventListener(type: string, listener: (event: MessageEvent) => void): void {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)!.add(listener);
    },
    onmessage: null,
    onerror: null,
    onopen: null,
    readyState: 0,
  };

  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(extraQuery)) {
    params.set(k, String(v));
  }
  const fullUrl = params.toString()
    ? `${url}${url.includes("?") ? "&" : "?"}${params.toString()}`
    : url;

  void fetchEventSource(fullUrl, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "text/event-stream",
    },
    signal: controller.signal,
    openWhenHidden: true,
    fetch: buildEventSourceFetch(token),
    async onopen(response) {
      compat.readyState = 1;
      if (compat.onopen) compat.onopen(new Event("open"));
      if (response.status >= 400) {
        throw new Error(`SSE connection failed: ${response.status}`);
      }
    },
    onmessage(event) {
      const messageEvent = new MessageEvent(event.event || "message", {
        data: event.data,
      });
      const named = listeners.get(event.event || "message");
      if (named) for (const fn of named) fn(messageEvent);
      if (compat.onmessage) compat.onmessage(messageEvent);
    },
    onclose() {
      compat.readyState = 2;
      if (compat.onerror) compat.onerror(new Event("error"));
    },
    onerror(err) {
      if (compat.onerror) compat.onerror(new Event("error"));
      // Re-throw so the underlying fetchEventSource handles reconnect
      throw err;
    },
  }).catch(() => {
    /* swallow — errors surface via onerror callback */
  });

  return compat;
}

export function createWorkflowStatusStream(
  token: string,
  namespace: string,
  workflowName: string,
): EventSource {
  const url = buildUrl(`/api/workflows/${workflowName}/status/stream`, namespace);
  // §security-R6: only use the header-based auth path. The previous
  // fallback (new EventSource(url + '&token=' + token)) leaked the
  // JWT in proxy logs, browser history, and the Referer header.
  return createHeaderEventSource(url, token) as unknown as EventSource;
}

export function createWorkflowActivitiesStream(
  token: string,
  namespace: string,
  workflowName: string,
  tail = 100,
): EventSource {
  const url = buildUrl(`/api/workflows/${workflowName}/activities/stream`, namespace);
  return createHeaderEventSource(url, token, { tail }) as unknown as EventSource;
}

export function createNotificationStream(
  token: string,
  namespace: string,
): EventSource {
  const url = buildUrl("/api/notifications/stream", namespace);
  // §security-R6: header-based auth only. The previous fallback
  // leaked the JWT in the URL.
  return createHeaderEventSource(url, token) as unknown as EventSource;
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

export async function fetchAgentTodos(
  token: string,
  namespace: string,
  agentName: string,
  threadId: string,
): Promise<Array<Record<string, unknown>>> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/todo?thread_id=${encodeURIComponent(threadId)}`, namespace),
    token,
  );
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "Agent todo response");
    return Array.isArray(record.todos) ? (record.todos as Array<Record<string, unknown>>) : [];
  });
}

/** ETag-aware todo polling. Returns `null` when 304 Not Modified. */
export async function pollAgentTodos(
  token: string,
  namespace: string,
  agentName: string,
  threadId: string,
  etag?: string,
): Promise<{ todos: Array<Record<string, unknown>>; etag: string | null } | null> {
  const headers: Record<string, string> = {};
  if (etag) headers["If-None-Match"] = etag;
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/todo?thread_id=${encodeURIComponent(threadId)}`, namespace),
    token,
    { headers },
  );
  if (response.status === 304) return null;
  const newEtag = response.headers.get("etag");
  const todos = await parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "Agent todo response");
    return Array.isArray(record.todos) ? (record.todos as Array<Record<string, unknown>>) : [];
  });
  return { todos, etag: newEtag };
}

/* ── Session Diff API ── */

export async function fetchSessionDiff(
  token: string,
  namespace: string,
  agentName: string,
  threadId: string,
): Promise<string> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/diff?thread_id=${encodeURIComponent(threadId)}`, namespace),
    token,
  );
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "Session diff response");
    return typeof record.diff === "string" ? record.diff : "";
  });
}

/* ── Question / HITL API ── */

export async function fetchPendingQuestions(
  token: string,
  namespace: string,
  agentName: string,
): Promise<Array<Record<string, unknown>>> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/question`, namespace),
    token,
  );
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) return payload as Array<Record<string, unknown>>;
    return [];
  });
}

export async function replyToQuestion(
  token: string,
  namespace: string,
  agentName: string,
  requestId: string,
  answers: string[][],
): Promise<void> {
  await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/question/${encodeURIComponent(requestId)}/reply`, namespace),
    token,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers }),
    },
  );
}

export async function rejectQuestion(
  token: string,
  namespace: string,
  agentName: string,
  requestId: string,
): Promise<void> {
  await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/question/${encodeURIComponent(requestId)}/reject`, namespace),
    token,
    { method: "POST" },
  );
}

export async function streamAgentInvoke(options: StreamHandlers): Promise<void> {
  await fetchEventSource(buildUrl(`/api/v1/agents/${options.agentName}/invoke/stream`, options.namespace), {
    fetch: buildEventSourceFetch(options.token, options.requestId),
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
        const detail = sanitizeErrorMessage(
          await response.text(),
          `Streaming request failed with status ${response.status}`,
        );
        throw new ApiError(
          response.status,
          `Streaming request failed with status ${response.status}`,
          detail,
        );
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
      const normalized = error instanceof Error ? error : new Error(String(error));
      try { options.onError(normalized); } catch { /* prevent double-throw */ }
      throw normalized; // stop reconnection
    },
    onclose() {
      options.onClose();
    },
  });
}

/* ── Skills Catalog API ── */

function parseCatalogSkillPayload(payload: unknown, label: string): CatalogSkill {
  const record = expectRecord(payload, label);
  const filesRecord = readRecord(record, "files", label, {});
  const filePaths = Object.keys(filesRecord);
  const totalSizeBytes = Object.values(filesRecord).reduce<number>((total, value, index) => {
    if (typeof value !== "string") {
      throw new Error(`${label}.files entry ${index} must be a string.`);
    }
    return total + value.length;
  }, 0);

  return {
    id: readString(record, "id", label),
    name: readString(record, "name", label),
    description: readString(record, "description", label),
    category: readString(record, "category", label),
    tags: [
      ...readStringArray(record, "allowed_mcp_servers", label, []),
      ...readStringArray(record, "allowed_sandbox_tools", label, []),
    ],
    files: filePaths,
    total_size_bytes: totalSizeBytes,
  };
}

function parseCatalogSkillDetailPayload(payload: unknown, label: string): CatalogSkillDetail {
  const record = expectRecord(payload, label);
  const filesRecord = readRecord(record, "files", label, {});
  const assets: Record<string, string> = {};

  for (const [path, value] of Object.entries(filesRecord)) {
    if (typeof value !== "string") {
      throw new Error(`${label}.files.${path} must be a string.`);
    }
    assets[path] = value;
  }

  return {
    ...parseCatalogSkillPayload(record, label),
    assets,
  };
}

function parseMcpToolCategoryPayload(payload: unknown, label: string): McpToolCategory {
  const record = expectRecord(payload, label);
  return {
    id: readString(record, "id", label),
    name: readString(record, "name", label),
    description: readString(record, "description", label),
    icon: readString(record, "icon", label),
    default_port: readOptionalNumber(record, "default_port", label) ?? 0,
    sidecar_image: readOptionalString(record, "sidecar_image", label),
    config_schema: Array.isArray(record.config_schema) ? (record.config_schema as ConfigField[]) : [],
    credential_type: readOptionalString(record, "credential_type", label),
  };
}

function parseMcpSupportLevel(value: string, label: string): McpSupportLevel {
  if (value === "ready" || value === "limited" || value === "planned") {
    return value;
  }
  throw new Error(`${label} must be one of ready, limited, or planned.`);
}

function parseMcpRegistryServerPayload(payload: unknown, label: string): McpRegistryServer {
  const record = expectRecord(payload, label);
  return {
    id: readString(record, "id", label),
    name: readString(record, "name", label),
    description: readString(record, "description", label),
    icon: readString(record, "icon", label),
    category: readString(record, "category", label),
    transport: readString(record, "transport", label) as McpRegistryServer["transport"],
    endpoint: readOptionalString(record, "endpoint", label),
    suggested_endpoint: readOptionalString(record, "suggested_endpoint", label),
    hub_server_name: readOptionalString(record, "hub_server_name", label),
    auth_type: readString(record, "auth_type", label) as McpRegistryServer["auth_type"],
    oauth_scopes: readStringArray(record, "oauth_scopes", label, []),
    auth_header_name: readOptionalString(record, "auth_header_name", label),
    auth_header_prefix: readOptionalString(record, "auth_header_prefix", label),
    enabled: readBoolean(record, "enabled", label),
    tags: readStringArray(record, "tags", label, []),
    tools_count: readNumber(record, "tools_count", label),
    tool_names: readStringArray(record, "tool_names", label, []),
    config_schema: Array.isArray(record.config_schema) ? (record.config_schema as ConfigField[]) : [],
    sidecar_image: readOptionalString(record, "sidecar_image", label),
    sidecar_port: readOptionalNumber(record, "sidecar_port", label),
    support_level: parseMcpSupportLevel(readString(record, "support_level", label), `${label}.support_level`),
    attachable: readBoolean(record, "attachable", label),
    status_reason: readOptionalString(record, "status_reason", label),
  };
}

function parseMcpProfileServerPayload(payload: unknown, label: string): McpProfileServer {
  const record = expectRecord(payload, label);
  return {
    id: readString(record, "id", label),
    name: readString(record, "name", label),
    transport: readString(record, "transport", label) as McpProfileServer["transport"],
    support_level: parseMcpSupportLevel(readString(record, "support_level", label), `${label}.support_level`),
    attachable: readBoolean(record, "attachable", label),
    status_reason: readOptionalString(record, "status_reason", label),
  };
}

function parseMcpProfilePayload(payload: unknown, label: string): McpProfile {
  const record = expectRecord(payload, label);
  const resolvedServers = readRecordArray(record, "resolved_servers", label).map((item, index) =>
    parseMcpProfileServerPayload(item, `${label}.resolved_servers[${index}]`),
  );
  const attachableServers = readRecordArray(record, "attachable_servers", label).map((item, index) =>
    parseMcpProfileServerPayload(item, `${label}.attachable_servers[${index}]`),
  );
  const blockedServers = readRecordArray(record, "blocked_servers", label).map((item, index) =>
    parseMcpProfileServerPayload(item, `${label}.blocked_servers[${index}]`),
  );
  return {
    id: readString(record, "id", label),
    name: readString(record, "name", label),
    description: readString(record, "description", label),
    icon: readString(record, "icon", label),
    color: readString(record, "color", label),
    servers: readStringArray(record, "servers", label, []),
    resolved_servers: resolvedServers,
    attachable_servers: attachableServers,
    blocked_servers: blockedServers,
    can_apply: readBoolean(record, "can_apply", label),
    support_level: parseMcpSupportLevel(readString(record, "support_level", label), `${label}.support_level`),
    total_tools: readNumber(record, "total_tools", label),
    tags: readStringArray(record, "tags", label, []),
  };
}

export async function fetchSkillsCatalog(
  token: string,
  category?: string,
  search?: string,
): Promise<CatalogSkill[]> {
  const query = new URLSearchParams();
  if (category) query.set("category", category);
  if (search) query.set("search", search);
  const baseUrl = buildUrl("/api/skills/catalog");
  const requestUrl = query.size > 0 ? `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}${query.toString()}` : baseUrl;
  const response = await fetchAuthenticated(requestUrl, token);
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) {
      return payload.map((item, index) => parseCatalogSkillPayload(item, `skills[${index}]`));
    }
    if (isRecord(payload) && Array.isArray(payload.skills)) {
      return payload.skills.map((item, index) => parseCatalogSkillPayload(item, `skills[${index}]`));
    }
    throw new Error("Invalid catalog response");
  });
}

export async function fetchCatalogSkillDetail(
  token: string,
  skillId: string,
): Promise<CatalogSkillDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/skills/catalog/${skillId}`), token);
  return parseJsonResponse(response, (payload) => parseCatalogSkillDetailPayload(payload, "skill_detail"));
}

export async function refreshSkillsCatalog(token: string): Promise<void> {
  await fetchAuthenticated(buildUrl("/api/skills/catalog/refresh"), token, { method: "POST" });
}

export async function fetchMcpToolCategories(token: string): Promise<McpToolCategory[]> {
  const response = await fetchAuthenticated(buildUrl("/api/skills/tools"), token);
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) {
      return payload.map((item, index) => parseMcpToolCategoryPayload(item, `categories[${index}]`));
    }
    if (isRecord(payload) && Array.isArray(payload.categories)) {
      return payload.categories.map((item, index) => parseMcpToolCategoryPayload(item, `categories[${index}]`));
    }
    throw new Error("Invalid tools response");
  });
}

/* ── Git Credential API ── */

export async function createGitCredentials(
  token: string,
  agentName: string,
  body: GitCredentialRequest,
  namespace = "default",
): Promise<Record<string, unknown>> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/git-credentials`, namespace),
    token,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  return parseJsonResponse(response, (p) => p as Record<string, unknown>);
}

export async function createGitHubCredentials(
  token: string,
  agentName: string,
  body: GitHubCredentialRequest,
  namespace = "default",
): Promise<Record<string, unknown>> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/github-credentials`, namespace),
    token,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  return parseJsonResponse(response, (p) => p as Record<string, unknown>);
}

export async function getGitCredentials(
  token: string,
  agentName: string,
  namespace = "default",
): Promise<GitCredentialInfo> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/git-credentials`, namespace),
    token,
  );
  return parseJsonResponse(response, (p) => p as GitCredentialInfo);
}

export async function deleteGitCredentials(
  token: string,
  agentName: string,
  namespace = "default",
): Promise<Record<string, unknown>> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/git-credentials`, namespace),
    token,
    { method: "DELETE" },
  );
  return parseJsonResponse(response, (p) => p as Record<string, unknown>);
}

/* ── GitHub Credential API ── */

export async function getGitHubCredentials(
  token: string,
  agentName: string,
  namespace = "default",
): Promise<GitHubCredentialInfo> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/github-credentials`, namespace),
    token,
  );
  return parseJsonResponse(response, (p) => p as GitHubCredentialInfo);
}

export async function deleteGitHubCredentials(
  token: string,
  agentName: string,
  namespace = "default",
): Promise<Record<string, unknown>> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/agents/${agentName}/github-credentials`, namespace),
    token,
    { method: "DELETE" },
  );
  return parseJsonResponse(response, (p) => p as Record<string, unknown>);
}

/* ── MCP Hub Servers API ── */

export async function fetchMcpHubServers(token: string): Promise<McpHubServer[]> {
  const response = await fetchAuthenticated(buildUrl("/api/mcp-hub/servers"), token);
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) return payload as McpHubServer[];
    throw new Error("Invalid MCP hub servers response");
  });
}

/* ── MCP Registry API ── */

export async function fetchMcpRegistry(
  token: string,
  options?: { category?: string; transport?: string; search?: string },
): Promise<McpRegistryServer[]> {
  const query = new URLSearchParams();
  if (options?.category) query.set("category", options.category);
  if (options?.transport) query.set("transport", options.transport);
  if (options?.search) query.set("search", options.search);
  const baseUrl = buildUrl("/api/mcp/registry");
  const requestUrl = query.size > 0 ? `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}${query.toString()}` : baseUrl;
  const response = await fetchAuthenticated(requestUrl, token);
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) {
      return payload.map((item, index) => parseMcpRegistryServerPayload(item, `mcp_registry[${index}]`));
    }
    throw new Error("Invalid MCP registry response");
  });
}

export async function fetchMcpProfiles(token: string): Promise<McpProfile[]> {
  const response = await fetchAuthenticated(buildUrl("/api/mcp/profiles"), token);
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) {
      return payload.map((item, index) => parseMcpProfilePayload(item, `mcp_profiles[${index}]`));
    }
    throw new Error("Invalid MCP profiles response");
  });
}

export async function fetchMcpServerDetail(token: string, serverId: string): Promise<McpRegistryServer> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/registry/${serverId}`), token);
  return parseJsonResponse(response, (payload) => parseMcpRegistryServerPayload(payload, "mcp_registry_detail"));
}

export async function fetchMcpCategories(token: string): Promise<McpCategory[]> {
  const response = await fetchAuthenticated(buildUrl("/api/mcp/categories"), token);
  return parseJsonResponse(response, (payload) => {
    if (Array.isArray(payload)) return payload as McpCategory[];
    throw new Error("Invalid MCP categories response");
  });
}

export async function fetchMcpStats(token: string): Promise<McpStats> {
  const response = await fetchAuthenticated(buildUrl("/api/mcp/stats"), token);
  return parseJsonResponse(response, (payload) => payload as McpStats);
}

export async function fetchMcpConnections(token: string, namespace: string): Promise<McpConnection[]> {
  const response = await fetchAuthenticated(buildUrl("/api/mcp/connections", namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Invalid MCP connections response");
    }
    return payload.map((item, index) => parseMcpConnectionPayload(item, `mcp_connections[${index}]`));
  });
}

export async function fetchMcpConnection(token: string, namespace: string, connectionId: string): Promise<McpConnection> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}`, namespace), token);
  return parseJsonResponse(response, (payload) => parseMcpConnectionPayload(payload, "mcp_connection"));
}

export async function createMcpConnection(
  token: string,
  namespace: string,
  payload: {
    name: string;
    server_id: string;
    config?: Record<string, unknown>;
    credentials?: Record<string, string>;
    validate_on_save?: boolean;
  },
): Promise<McpConnection> {
  const response = await fetchAuthenticated(buildUrl("/api/mcp/connections", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, (data) => parseMcpConnectionPayload(data, "mcp_connection_created"));
}

export async function updateMcpConnection(
  token: string,
  namespace: string,
  connectionId: string,
  payload: {
    name?: string;
    server_id?: string;
    config?: Record<string, unknown>;
    credentials?: Record<string, string>;
    validate_on_save?: boolean;
  },
): Promise<McpConnection> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}`, namespace), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, (data) => parseMcpConnectionPayload(data, "mcp_connection_updated"));
}

export async function validateMcpConnection(
  token: string,
  namespace: string,
  connectionId: string,
): Promise<McpConnection> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}/validate`, namespace), token, {
    method: "POST",
  });
  return parseJsonResponse(response, (data) => parseMcpConnectionPayload(data, "mcp_connection_validated"));
}

export async function startMcpConnectionOAuth(
  token: string,
  namespace: string,
  connectionId: string,
): Promise<McpConnectionOAuthStart> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}/oauth/start`, namespace), token, {
    method: "POST",
  });
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "mcp_connection_oauth_start");
    return {
      authorization_url: readString(record, "authorization_url", "mcp_connection_oauth_start"),
      expires_at: readOptionalString(record, "expires_at", "mcp_connection_oauth_start"),
    };
  });
}

export async function refreshMcpConnectionOAuth(
  token: string,
  namespace: string,
  connectionId: string,
): Promise<McpConnection> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}/oauth/refresh`, namespace), token, {
    method: "POST",
  });
  return parseJsonResponse(response, (data) => parseMcpConnectionPayload(data, "mcp_connection_oauth_refreshed"));
}

export async function deleteMcpConnection(
  token: string,
  namespace: string,
  connectionId: string,
): Promise<DeleteResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}`, namespace), token, {
    method: "DELETE",
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
}

export async function fetchMcpConnectionBindings(
  token: string,
  namespace: string,
  connectionId: string,
): Promise<McpConnectionBinding[]> {
  const response = await fetchAuthenticated(buildUrl(`/api/mcp/connections/${connectionId}/bindings`, namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Invalid MCP connection bindings response");
    }
    return payload.map((item, index) => parseMcpConnectionBindingPayload(item, `mcp_connection_bindings[${index}]`));
  });
}

/* ── LLM / Provider Management API ── */

export async function fetchLLMHealth(token: string): Promise<{ status: string; litellm_status?: number; error?: string }> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/health"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "LLMHealth");
    return {
      status: readString(record, "status", "LLMHealth"),
      litellm_status: readOptionalNumber(record, "litellm_status", "LLMHealth") ?? undefined,
      error: readOptionalString(record, "error", "LLMHealth") ?? undefined,
    };
  });
}

export async function fetchLLMModels(token: string): Promise<LLMModelInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/models"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "LLMModels");
    const models = record.models;
    if (!Array.isArray(models)) return [];
    return models.map((item, i) => {
      const m = expectRecord(item, `models[${i}]`);
      return {
        model_name: readString(m, "model_name", `models[${i}]`, ""),
        litellm_params: isRecord(m.litellm_params) ? (m.litellm_params as Record<string, unknown>) : {},
        model_info: isRecord(m.model_info) ? (m.model_info as Record<string, unknown>) : {},
      };
    });
  });
}

export async function addLLMModel(
  token: string,
  modelName: string,
  litellmParams: Record<string, unknown>,
): Promise<void> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/models"), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_name: modelName, litellm_params: litellmParams }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to add model (${response.status})`);
  }
}

export async function deleteLLMModel(token: string, modelId: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/models/delete"), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: modelId }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to delete model (${response.status})`);
  }
}

export async function fetchLLMKeys(token: string): Promise<LLMKeyInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/keys"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "LLMKeys");
    const keys = record.keys;
    if (!Array.isArray(keys)) return [];
    return keys.map((item, i) => {
      const k = expectRecord(item, `keys[${i}]`);
      return {
        name: readString(k, "name", `keys[${i}]`),
        is_set: readBoolean(k, "is_set", `keys[${i}]`, false),
      };
    });
  });
}

export async function updateLLMKeys(token: string, keys: Record<string, string>): Promise<void> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/keys"), token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to update keys (${response.status})`);
  }
}

/* ── Provider-centric LLM API ── */

export async function fetchLLMProviders(token: string): Promise<LLMProvider[]> {
  const response = await fetchAuthenticated(buildUrl("/api/llm/providers"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "LLMProviders");
    const providers = record.providers;
    if (!Array.isArray(providers)) return [];
    return providers.map((item, i) => {
      const p = expectRecord(item, `providers[${i}]`);
      return {
        key_name: readString(p, "key_name", `providers[${i}]`),
        label: readString(p, "label", `providers[${i}]`),
        prefix: readString(p, "prefix", `providers[${i}]`, ""),
        is_configured: typeof p.is_configured === "boolean" ? p.is_configured : null,
        model_count: typeof p.model_count === "number" ? p.model_count : 0,
        models: Array.isArray(p.models)
          ? p.models.map((m: unknown, j: number) => {
              const model = expectRecord(m, `providers[${i}].models[${j}]`);
              return {
                model_name: readString(model, "model_name", `model[${j}]`, ""),
                litellm_model: readString(model, "litellm_model", `model[${j}]`, ""),
                id: readString(model, "id", `model[${j}]`, ""),
              };
            })
          : [],
      };
    });
  });
}

export async function fetchConnectedProviders(token: string): Promise<ConnectedProvider[]> {
  const response = await fetchAuthenticated(buildUrl("/api/providers"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "ProvidersResponse");
    const providers = record.providers;
    if (!Array.isArray(providers)) return [];
    return providers.map((item, index) => {
      const provider = expectRecord(item, `providers[${index}]`);
      const headersValue = provider.headers;
      let headers: Record<string, string> = {};
      if (isRecord(headersValue)) {
        headers = Object.fromEntries(
          Object.entries(headersValue).map(([key, value]) => [key, typeof value === "string" ? value : String(value)]),
        );
      }
      return {
        id: readString(provider, "id", `providers[${index}]`),
        label: readString(provider, "label", `providers[${index}]`),
        kind: readString(provider, "kind", `providers[${index}]`) as "builtin" | "custom",
        description: readString(provider, "description", `providers[${index}]`, ""),
        auth_type: readString(provider, "auth_type", `providers[${index}]`) as "apiKey" | "oauth",
        connected: readBoolean(provider, "connected", `providers[${index}]`, false),
        docs_url: readOptionalString(provider, "docs_url", `providers[${index}]`),
        base_url: readOptionalString(provider, "base_url", `providers[${index}]`),
        key_placeholder: readOptionalString(provider, "key_placeholder", `providers[${index}]`),
        editable: readBoolean(provider, "editable", `providers[${index}]`, false),
        headers,
        models: Array.isArray(provider.models)
          ? provider.models.map((model, modelIndex) => {
              const entry = expectRecord(model, `providers[${index}].models[${modelIndex}]`);
              return {
                id: readString(entry, "id", `providers[${index}].models[${modelIndex}]`),
                name: readString(entry, "name", `providers[${index}].models[${modelIndex}]`),
                description: readOptionalString(entry, "description", `providers[${index}].models[${modelIndex}]`),
              };
            })
          : [],
      };
    });
  });
}

export async function fetchProviderCatalog(token: string): Promise<ProviderCatalogModel[]> {
  const response = await fetchAuthenticated(buildUrl("/api/providers/catalog"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "ProviderCatalogResponse");
    const models = record.models;
    if (!Array.isArray(models)) return [];
    return models.map((item, index) => {
      const model = expectRecord(item, `models[${index}]`);
      return {
        provider_id: readString(model, "provider_id", `models[${index}]`),
        provider_label: readString(model, "provider_label", `models[${index}]`),
        model_id: readString(model, "model_id", `models[${index}]`),
        model_ref: readString(model, "model_ref", `models[${index}]`),
        connected: readBoolean(model, "connected", `models[${index}]`, false),
        kind: readString(model, "kind", `models[${index}]`) as "builtin" | "custom",
        description: readOptionalString(model, "description", `models[${index}]`),
      };
    });
  });
}

export async function updateProviderCredential(token: string, providerId: string, apiKey: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/providers/${encodeURIComponent(providerId)}/credentials`), token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to update provider credential (${response.status})`);
  }
}

export async function createOrUpdateCustomProvider(token: string, payload: CustomProviderPayload): Promise<void> {
  const response = await fetchAuthenticated(buildUrl("/api/providers/custom"), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to save custom provider (${response.status})`);
  }
}

export async function deleteCustomProvider(token: string, providerId: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/providers/custom/${encodeURIComponent(providerId)}`), token, {
    method: "DELETE",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to delete custom provider (${response.status})`);
  }
}

export async function fetchProviderSuggestions(token: string, provider: string, q?: string): Promise<ModelSuggestion[]> {
  let url = buildUrl(`/api/llm/providers/${encodeURIComponent(provider)}/suggestions`);
  if (q) url += `?q=${encodeURIComponent(q)}`;
  const response = await fetchAuthenticated(url, token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "ProviderSuggestions");
    const suggestions = record.suggestions;
    if (!Array.isArray(suggestions)) return [];
    return suggestions.map((item, i) => {
      const s = expectRecord(item, `suggestions[${i}]`);
      return {
        model_id: readString(s, "model_id", `suggestions[${i}]`),
        display_name: readString(s, "display_name", `suggestions[${i}]`),
        description: readOptionalString(s, "description", `suggestions[${i}]`) ?? undefined,
      };
    });
  });
}

export async function addProviderModel(
  token: string,
  provider: string,
  modelId: string,
  alias?: string,
): Promise<void> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/llm/providers/${encodeURIComponent(provider)}/models`),
    token,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId, alias: alias || null }),
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to add model (${response.status})`);
  }
}

/* ── GitHub Copilot Auth ── */

export async function initiateCopilotAuth(token: string): Promise<CopilotDeviceFlowResponse> {
  const response = await fetchAuthenticated(buildUrl("/api/copilot/auth/device"), token, {
    method: "POST",
  });
  return parseJsonResponse(response, (payload) => {
    const r = expectRecord(payload, "CopilotDeviceFlow");
    return {
      user_code: readString(r, "user_code", "CopilotDeviceFlow"),
      verification_uri: readString(r, "verification_uri", "CopilotDeviceFlow"),
      interval: typeof r.interval === "number" ? r.interval : 5,
    };
  });
}

export async function pollCopilotAuth(token: string): Promise<CopilotPollResponse> {
  const response = await fetchAuthenticated(buildUrl("/api/copilot/auth/poll"), token, {
    method: "POST",
  });
  return parseJsonResponse(response, (payload) => {
    const r = expectRecord(payload, "CopilotPoll");
    return {
      status: readString(r, "status", "CopilotPoll") as CopilotPollResponse["status"],
      interval: typeof r.interval === "number" ? r.interval : undefined,
      error: readOptionalString(r, "error", "CopilotPoll") ?? undefined,
    };
  });
}

export async function getCopilotAuthStatus(token: string): Promise<CopilotAuthStatus> {
  const response = await fetchAuthenticated(buildUrl("/api/copilot/auth/status"), token);
  return parseJsonResponse(response, (payload) => {
    const r = expectRecord(payload, "CopilotAuthStatus");
    return {
      connected: typeof r.connected === "boolean" ? r.connected : false,
    };
  });
}

// ── Chat Session Persistence ──

export interface ChatSessionInfo {
  session_id: string;
  title: string;
  agent_name: string;
  namespace: string;
  username: string | null;
  created_at: string | null;
  updated_at: string | null;
  summary?: ChatSessionSummary | null;
}

export interface RuntimeContinuitySummary {
  createdNewSession?: boolean;
  sessionRecovered?: boolean;
  hasPriorMemory?: boolean;
  memoryApplied?: boolean;
  memoryEntryCount?: number | null;
  handoffResumed?: boolean;
  remoteSessionId?: string | null;
}

export interface ChatSessionMemoryCandidate {
  type: string;
  names?: string[];
  text?: string;
  count?: number;
}

export interface ChatSessionSummary {
  message_count: number;
  tool_names: string[];
  last_user_message: string;
  last_assistant_message: string;
  memory_candidates: {
    episodic: ChatSessionMemoryCandidate[];
    procedural: ChatSessionMemoryCandidate[];
  };
}

export interface ChatMessageInfo {
  message_id: string;
  role: string;
  content: string;
  status: string;
  tool_name: string | null;
  tool_node: string | null;
  created_at: string | null;
}

export async function listChatSessions(token: string, namespace: string, agentName: string): Promise<ChatSessionInfo[]> {
  const url = buildUrl("/api/chat-sessions", namespace);
  const fullUrl = `${url}${url.includes("?") ? "&" : "?"}agent_name=${encodeURIComponent(agentName)}`;
  const response = await fetchAuthenticated(fullUrl, token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item) => {
      const record = expectRecord(item, "ChatSessionInfo");
      const summaryRecord = record.summary && typeof record.summary === "object" ? record.summary as Record<string, unknown> : null;
      const memoryRecord = summaryRecord?.memory_candidates && typeof summaryRecord.memory_candidates === "object"
        ? summaryRecord.memory_candidates as Record<string, unknown>
        : null;
      const readCandidates = (key: "episodic" | "procedural"): ChatSessionMemoryCandidate[] => {
        const value = memoryRecord?.[key];
        if (!Array.isArray(value)) return [];
        return value
          .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === "object")
          .map((entry) => ({
            type: readString(entry, "type", `ChatSessionSummary.${key}`),
            names: Array.isArray(entry.names) ? entry.names.map((name) => String(name)) : undefined,
            text: readOptionalString(entry, "text", `ChatSessionSummary.${key}`) ?? undefined,
            count: typeof entry.count === "number" ? entry.count : undefined,
          }));
      };
      return {
        session_id: readString(record, "session_id", "ChatSessionInfo"),
        title: readString(record, "title", "ChatSessionInfo"),
        agent_name: readString(record, "agent_name", "ChatSessionInfo"),
        namespace: readString(record, "namespace", "ChatSessionInfo"),
        username: readOptionalString(record, "username", "ChatSessionInfo"),
        created_at: readOptionalString(record, "created_at", "ChatSessionInfo"),
        updated_at: readOptionalString(record, "updated_at", "ChatSessionInfo"),
        summary: summaryRecord ? {
          message_count: typeof summaryRecord.message_count === "number" ? summaryRecord.message_count : 0,
          tool_names: Array.isArray(summaryRecord.tool_names) ? summaryRecord.tool_names.map((name) => String(name)) : [],
          last_user_message: readOptionalString(summaryRecord, "last_user_message", "ChatSessionSummary") ?? "",
          last_assistant_message: readOptionalString(summaryRecord, "last_assistant_message", "ChatSessionSummary") ?? "",
          memory_candidates: {
            episodic: readCandidates("episodic"),
            procedural: readCandidates("procedural"),
          },
        } : null,
      } satisfies ChatSessionInfo;
    });
  });
}

export async function createChatSession(
  token: string, namespace: string, agentName: string, title?: string,
): Promise<ChatSessionInfo> {
  const response = await fetchAuthenticated(
    buildUrl("/api/chat-sessions", namespace),
    token,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ agent_name: agentName, title: title ?? "Untitled" }) },
  );
  return parseJsonResponse(response, (p) => p as ChatSessionInfo);
}

export async function getChatSessionMessages(token: string, sessionId: string): Promise<ChatMessageInfo[]> {
  const response = await fetchAuthenticated(buildUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}/messages`), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload as ChatMessageInfo[];
  });
}

export async function saveChatSessionMessages(
  token: string, sessionId: string, messages: Array<{ message_id: string; role: string; content: string; status: string; toolName?: string | null; toolNode?: string | null }>,
): Promise<void> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}/messages`),
    token,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages }) },
  );
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to save messages", text); }
}

export async function updateChatSessionTitle(token: string, sessionId: string, title: string): Promise<ChatSessionInfo> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}`),
    token,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) },
  );
  return parseJsonResponse(response, (p) => p as ChatSessionInfo);
}

export async function deleteChatSession(token: string, sessionId: string): Promise<void> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/chat-sessions/${encodeURIComponent(sessionId)}`),
    token,
    { method: "DELETE" },
  );
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete session", text); }
}

// --------------------------------------------------------------------------- //
//  AIOps Observability API                                                      //
// --------------------------------------------------------------------------- //

export interface ObservabilityTargetSummary {
  name: string;
  namespace: string;
  description?: string;
  targetType: string;
  connectorRef: string;
  policyRef?: string;
  endpoint: string;
  scrapeInterval: string;
  phase: string;
  lastScrapeTime: string | null;
  metricsCollected: number;
  connectorHealth: string;
  createdAt: string;
}

export interface ObservabilityFinding {
  id: string;
  severity: string;
  metric: string;
  algorithm: string;
  timestamp: string;
  value: number;
  expected: number;
  deviation: number;
  description: string;
  recommendation: string;
}

export interface ObservabilityResourceMetadata {
  name: string;
  namespace?: string;
  creationTimestamp?: string;
  resourceVersion?: string;
  labels?: Record<string, string>;
  annotations?: Record<string, string>;
  [key: string]: unknown;
}

export interface ObservabilityCondition {
  type?: string;
  status?: string;
  lastTransitionTime?: string;
  reason?: string;
  message?: string;
}

export interface ObservationTargetSelectorExpression {
  key: string;
  operator: string;
  values?: string[];
}

export interface ObservationTargetSelector {
  matchLabels?: Record<string, string>;
  matchExpressions?: ObservationTargetSelectorExpression[];
}

export interface ObservationTargetCredentials {
  secretRef?: string;
  vaultPath?: string;
  spiffeEnabled?: boolean;
}

export interface ObservationTargetTlsConfig {
  insecureSkipVerify?: boolean;
  caSecretRef?: string;
}

export interface ObservabilityTargetSpec {
  description?: string;
  targetType: string;
  connectorRef: string;
  endpoint?: string;
  scrapeInterval?: string;
  policyRef?: string;
  selector?: ObservationTargetSelector;
  credentials?: ObservationTargetCredentials;
  labels?: Record<string, string>;
  tlsConfig?: ObservationTargetTlsConfig;
}

export interface ObservabilityTargetStatus {
  phase?: string;
  lastScrapeTime?: string;
  lastScrapeError?: string;
  metricsCollected?: number;
  connectorHealth?: string;
  conditions?: ObservabilityCondition[];
}

export interface ObservabilityTargetDetail {
  apiVersion: string;
  kind: string;
  metadata: ObservabilityResourceMetadata;
  spec: ObservabilityTargetSpec;
  status?: ObservabilityTargetStatus;
}

export interface ObservationRetentionSpec {
  days?: number;
  downsampling?: {
    after?: string;
    resolution?: string;
  };
}

export interface ObservationAlertRule {
  name: string;
  expr: string;
  for?: string;
  severity?: string;
  annotations?: Record<string, string>;
}

export interface ObservationAnomalyDetectionSpec {
  enabled?: boolean;
  algorithm?: string;
  sensitivity?: number;
  windowSize?: string;
  evaluationInterval?: string;
  metrics?: string[];
}

export interface ObservationNotificationsSpec {
  webhookUrl?: string;
  natsSubject?: string;
}

export interface ObservabilityPolicySpec {
  description?: string;
  retention?: ObservationRetentionSpec;
  alertRules?: ObservationAlertRule[];
  anomalyDetection?: ObservationAnomalyDetectionSpec;
  notifications?: ObservationNotificationsSpec;
}

export interface ObservabilityPolicyStatus {
  activeAlerts?: number;
  lastEvaluated?: string;
  conditions?: ObservabilityCondition[];
}

export interface ObservabilityPolicyDetail {
  apiVersion: string;
  kind: string;
  metadata: ObservabilityResourceMetadata;
  spec: ObservabilityPolicySpec;
  status?: ObservabilityPolicyStatus;
}

export interface ConnectorPluginEnvVar {
  name?: string;
  value?: string;
  valueFrom?: Record<string, unknown>;
}

export interface ConnectorPluginResources {
  requests?: { cpu?: string; memory?: string };
  limits?: { cpu?: string; memory?: string };
}

export interface ObservabilityConnectorSpec {
  description?: string;
  image: string;
  protocol: string;
  port?: number;
  capabilities: string[];
  healthEndpoint?: string;
  resources?: ConnectorPluginResources;
  secretRef?: string;
  env?: ConnectorPluginEnvVar[];
}

export interface ObservabilityConnectorStatus {
  ready?: string;
  version?: string;
  lastHealthCheck?: string;
  conditions?: ObservabilityCondition[];
}

export interface ObservabilityConnectorDetail {
  apiVersion: string;
  kind: string;
  metadata: ObservabilityResourceMetadata;
  spec: ObservabilityConnectorSpec;
  status?: ObservabilityConnectorStatus;
}

export interface CreateObservationTargetPayload extends ObservabilityTargetSpec {
  name: string;
}

export type UpdateObservationTargetPayload = Partial<ObservabilityTargetSpec>;

export interface CreateObservationPolicyPayload extends ObservabilityPolicySpec {
  name: string;
}

export type UpdateObservationPolicyPayload = Partial<ObservabilityPolicySpec>;

export interface CreateConnectorPluginPayload extends ObservabilityConnectorSpec {
  name: string;
}

export type UpdateConnectorPluginPayload = Partial<ObservabilityConnectorSpec>;

export interface ObservabilityReport {
  name: string;
  targetRef: string;
  reportType: string;
  phase: string;
  healthScore: number | null;
  findingsCount: number;
  lastEvaluated: string | null;
  findings: ObservabilityFinding[];
  summary: string;
  createdAt: string;
}

export interface ObservabilityConnector {
  name: string;
  description?: string;
  image: string;
  protocol: string;
  port: number;
  capabilities: string[];
  ready: string;
  lastHealthCheck: string | null;
  createdAt: string;
}

export interface ObservabilityPolicy {
  name: string;
  description?: string;
  retentionDays: number;
  anomalyEnabled: boolean;
  anomalyAlgorithm: string;
  alertRulesCount: number;
  activeAlerts: number;
  createdAt: string;
}

export interface ObservabilityOverview {
  summary: {
    targets: { total: number; active: number; degraded: number; failed: number };
    reports: { total: number; totalFindings: number; avgHealthScore: number };
    connectors: { total: number; ready: number };
    policies: { total: number };
    agents: { total: number; ready: number; notReady: number };
  };
  targets: ObservabilityTargetSummary[];
  reports: ObservabilityReport[];
  connectors: ObservabilityConnector[];
  policies: ObservabilityPolicy[];
  timestamp: string;
}

export async function fetchObservabilityOverview(token: string, namespace: string): Promise<ObservabilityOverview> {
  const response = await fetchAuthenticated(buildUrl("/api/observability/overview", namespace), token);
  return parseJsonResponse(response, (p) => p as ObservabilityOverview);
}

export async function createObservationTarget(token: string, namespace: string, body: Record<string, unknown>): Promise<ObservabilityTargetDetail> {
  const response = await fetchAuthenticated(buildUrl("/api/observability/targets", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as ObservabilityTargetDetail);
}

export async function fetchObservationTarget(token: string, namespace: string, name: string): Promise<ObservabilityTargetDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/targets/${encodeURIComponent(name)}`, namespace), token);
  return parseJsonResponse(response, (p) => p as ObservabilityTargetDetail);
}

export async function updateObservationTarget(token: string, namespace: string, name: string, body: UpdateObservationTargetPayload): Promise<ObservabilityTargetDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/targets/${encodeURIComponent(name)}`, namespace), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as ObservabilityTargetDetail);
}

export async function deleteObservationTarget(token: string, namespace: string, name: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/targets/${encodeURIComponent(name)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete target", text); }
}

export async function createObservationPolicy(token: string, namespace: string, body: Record<string, unknown>): Promise<ObservabilityPolicyDetail> {
  const response = await fetchAuthenticated(buildUrl("/api/observability/policies", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as ObservabilityPolicyDetail);
}

export async function fetchObservationPolicy(token: string, namespace: string, name: string): Promise<ObservabilityPolicyDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/policies/${encodeURIComponent(name)}`, namespace), token);
  return parseJsonResponse(response, (p) => p as ObservabilityPolicyDetail);
}

export async function updateObservationPolicy(token: string, namespace: string, name: string, body: UpdateObservationPolicyPayload): Promise<ObservabilityPolicyDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/policies/${encodeURIComponent(name)}`, namespace), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as ObservabilityPolicyDetail);
}

export async function deleteObservationPolicy(token: string, namespace: string, name: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/policies/${encodeURIComponent(name)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete policy", text); }
}

export async function createConnectorPlugin(token: string, namespace: string, body: Record<string, unknown>): Promise<ObservabilityConnectorDetail> {
  const response = await fetchAuthenticated(buildUrl("/api/observability/connectors", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as ObservabilityConnectorDetail);
}

export async function fetchConnectorPlugin(token: string, namespace: string, name: string): Promise<ObservabilityConnectorDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/connectors/${encodeURIComponent(name)}`, namespace), token);
  return parseJsonResponse(response, (p) => p as ObservabilityConnectorDetail);
}

export async function updateConnectorPlugin(token: string, namespace: string, name: string, body: UpdateConnectorPluginPayload): Promise<ObservabilityConnectorDetail> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/connectors/${encodeURIComponent(name)}`, namespace), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as ObservabilityConnectorDetail);
}

export async function deleteConnectorPlugin(token: string, namespace: string, name: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/observability/connectors/${encodeURIComponent(name)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete connector", text); }
}

// ── Intelligence Collector API ──

export interface IntelligenceCollector {
  id: string;
  name: string;
  url: string;
  cluster: string;
  status: "online" | "offline" | "degraded";
  registered_at: string;
  tags: string[];
  version?: string;
  capabilities?: string[];
  builtin_scripts?: string[];
  node?: string;
  max_timeout?: number;
  error?: string;
}

export interface IntelligenceCollectorList {
  collectors: IntelligenceCollector[];
  total: number;
}

export interface CollectionTaskResult {
  status: "completed" | "error" | "timeout" | "rejected";
  exit_code?: number;
  stdout?: string;
  stderr?: string;
  error?: string;
  duration_ms?: number;
  node?: string;
  cluster?: string;
  timestamp?: string;
  builtin?: string;
}

export interface CollectionTask {
  task_id: string;
  collector_id: string;
  payload: Record<string, unknown>;
  results: Record<string, CollectionTaskResult>;
  submitted_by: string;
  submitted_at: string;
  total: number;
  completed: number;
}

export interface CollectionTaskList {
  tasks: CollectionTask[];
  total: number;
}

export interface DeleteCollectionTasksResponse {
  status: string;
  kind: string;
  namespace: string;
  deleted: number;
  requested: number;
  deleted_ids: string[];
  missing_ids: string[];
}

export interface RegisterCollectorPayload {
  name: string;
  url: string;
  token?: string;
  cluster?: string;
  tags?: string[];
}

export interface SubmitCollectionPayload {
  collector_id: string;
  script?: string;
  builtin?: string;
  type?: "bash" | "python";
  timeout?: number;
}

export async function fetchIntelligenceCollectors(token: string, namespace?: string): Promise<IntelligenceCollectorList> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/collectors", namespace), token);
  return parseJsonResponse(response, (p) => p as IntelligenceCollectorList);
}

export async function registerIntelligenceCollector(token: string, body: RegisterCollectorPayload, namespace?: string): Promise<IntelligenceCollector> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/collectors", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as IntelligenceCollector);
}

export async function unregisterIntelligenceCollector(token: string, collectorId: string, namespace?: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/collectors/${encodeURIComponent(collectorId)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to unregister collector", text); }
}

export async function submitCollectionTask(token: string, body: SubmitCollectionPayload, namespace?: string): Promise<CollectionTask> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/collect", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as CollectionTask);
}

export async function fetchCollectionTasks(token: string, limit = 50, namespace?: string): Promise<CollectionTaskList> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/tasks?limit=${limit}`, namespace), token);
  return parseJsonResponse(response, (p) => p as CollectionTaskList);
}

export async function fetchCollectionTask(token: string, taskId: string, namespace?: string): Promise<CollectionTask> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/tasks/${encodeURIComponent(taskId)}`, namespace), token);
  return parseJsonResponse(response, (p) => p as CollectionTask);
}

export async function deleteCollectionTask(token: string, taskId: string, namespace?: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/tasks/${encodeURIComponent(taskId)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete collection task", text); }
}

export async function deleteCollectionTasks(token: string, taskIds: string[], namespace?: string): Promise<DeleteCollectionTasksResponse> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/tasks/delete", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_ids: taskIds }),
  });
  return parseJsonResponse(response, (p) => p as DeleteCollectionTasksResponse);
}

// ─── Intelligence Schedules & Alerts ──────────────────────────────────────

export interface IntelligenceSchedule {
  id: string;
  name: string;
  cron: string;
  collector_id: string;
  builtin?: string;
  script?: string;
  script_type?: "bash" | "python";
  timeout: number;
  agent_name?: string;
  enabled: boolean;
  created_by: string;
  created_at: string;
  last_run?: string | null;
  next_run?: string | null;
}

export interface IntelligenceScheduleList {
  schedules: IntelligenceSchedule[];
  total: number;
}

export interface CreateSchedulePayload {
  name: string;
  cron: string;
  collector_id?: string;
  builtin?: string;
  script?: string;
  script_type?: "bash" | "python";
  timeout?: number;
  agent_name?: string;
  enabled?: boolean;
}

export interface IntelligenceAlert {
  id: string;
  name: string;
  schedule_id?: string | null;
  condition_type: "contains" | "not_contains" | "exit_code" | "regex";
  condition_value: string;
  action: "notify" | "invoke_agent";
  agent_name?: string;
  prompt_template?: string;
  enabled: boolean;
  created_by: string;
  created_at: string;
  last_triggered?: string | null;
  trigger_count: number;
}

export interface IntelligenceAlertList {
  alerts: IntelligenceAlert[];
  total: number;
}

export interface CreateAlertPayload {
  name: string;
  schedule_id?: string;
  condition_type: "contains" | "not_contains" | "exit_code" | "regex";
  condition_value: string;
  action?: "notify" | "invoke_agent";
  agent_name?: string;
  prompt_template?: string;
  enabled?: boolean;
}

export interface AlertHistoryEntry {
  id: string;
  alert_id: string;
  alert_name: string;
  triggered_at: string;
  condition_matched: string;
  action_taken: string;
  agent_invoked?: string;
  invoke_status?: number;
  invoke_error?: string;
  task_id?: string;
  snippet: string;
}

export interface AlertHistoryList {
  history: AlertHistoryEntry[];
  total: number;
}

export interface PromptContextResponse {
  context: string;
  task_id?: string;
  collector_id?: string;
  namespace?: string;
}

// ── Schedule CRUD ─────────────────────────────────────────────────────────

export async function fetchIntelligenceSchedules(token: string, namespace?: string): Promise<IntelligenceScheduleList> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/schedules", namespace), token);
  return parseJsonResponse(response, (p) => p as IntelligenceScheduleList);
}

export async function createIntelligenceSchedule(token: string, body: CreateSchedulePayload, namespace?: string): Promise<IntelligenceSchedule> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/schedules", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as IntelligenceSchedule);
}

export async function updateIntelligenceSchedule(token: string, id: string, body: Partial<CreateSchedulePayload>, namespace?: string): Promise<IntelligenceSchedule> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/schedules/${encodeURIComponent(id)}`, namespace), token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as IntelligenceSchedule);
}

export async function deleteIntelligenceSchedule(token: string, id: string, namespace?: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/schedules/${encodeURIComponent(id)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete schedule", text); }
}

// ── Alert CRUD ────────────────────────────────────────────────────────────

export async function fetchIntelligenceAlerts(token: string, agentName?: string, namespace?: string): Promise<IntelligenceAlertList> {
  const url = agentName
    ? buildUrl(`/api/intelligence/alerts?agent_name=${encodeURIComponent(agentName)}`, namespace)
    : buildUrl("/api/intelligence/alerts", namespace);
  const response = await fetchAuthenticated(url, token);
  return parseJsonResponse(response, (p) => p as IntelligenceAlertList);
}

export async function createIntelligenceAlert(token: string, body: CreateAlertPayload, namespace?: string): Promise<IntelligenceAlert> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/alerts", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as IntelligenceAlert);
}

export async function updateIntelligenceAlert(token: string, id: string, body: Partial<CreateAlertPayload>, namespace?: string): Promise<IntelligenceAlert> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/alerts/${encodeURIComponent(id)}`, namespace), token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as IntelligenceAlert);
}

export async function deleteIntelligenceAlert(token: string, id: string, namespace?: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/alerts/${encodeURIComponent(id)}`, namespace), token, { method: "DELETE" });
  if (!response.ok) { const text = await response.text(); throw new ApiError(response.status, "Failed to delete alert", text); }
}

export async function fetchAlertHistory(token: string, limit = 50, namespace?: string): Promise<AlertHistoryList> {
  const response = await fetchAuthenticated(buildUrl(`/api/intelligence/alerts/history?limit=${limit}`, namespace), token);
  return parseJsonResponse(response, (p) => p as AlertHistoryList);
}

// ── Prompt context ────────────────────────────────────────────────────────

export async function fetchPromptContext(token: string, body: { collector_id?: string; builtin?: string; script?: string; type?: string; timeout?: number }, namespace?: string): Promise<PromptContextResponse> {
  const response = await fetchAuthenticated(buildUrl("/api/intelligence/prompt-context", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => p as PromptContextResponse);
}

// ── Webhook API ───────────────────────────────────────────────────────────

function parseWebhookReceiverPayload(payload: unknown, label = "WebhookReceiverInfo"): WebhookReceiverInfo {
  const record = expectRecord(payload, label);
  return {
    id: readNumber(record, "id", label),
    namespace: readString(record, "namespace", label),
    name: readString(record, "name", label),
    secret_ref: readString(record, "secret_ref", label),
    ip_allowlist: readStringArray(record, "ip_allowlist", label, []),
    rate_limit: readOptionalNumber(record, "rate_limit", label) ?? 0,
    max_payload_bytes: readOptionalNumber(record, "max_payload_bytes", label) ?? 0,
    enabled: readBoolean(record, "enabled", label, true),
    provider: (readOptionalString(record, "provider", label) ?? "generic") as WebhookProvider,
    api_key_enabled: readBoolean(record, "api_key_enabled", label, false),
    failure_count: readOptionalNumber(record, "failure_count", label) ?? 0,
    last_failure: readOptionalString(record, "last_failure", label),
    active_keys: readOptionalNumber(record, "active_keys", label) ?? 1,
    created_at: readOptionalString(record, "created_at", label) ?? "",
    updated_at: readOptionalString(record, "updated_at", label) ?? "",
  };
}

function parseWebhookInvocationPayload(payload: unknown, label = "WebhookInvocationInfo"): WebhookInvocationInfo {
  const record = expectRecord(payload, label);
  return {
    id: readNumber(record, "id", label),
    invocation_id: readString(record, "invocation_id", label),
    webhook_name: readString(record, "webhook_name", label),
    namespace: readString(record, "namespace", label),
    source_ip: readString(record, "source_ip", label, ""),
    received_at: readOptionalString(record, "received_at", label) ?? "",
    signature_verified: readBoolean(record, "signature_verified", label, false),
    status: readString(record, "status", label, ""),
    matched_triggers: readOptionalNumber(record, "matched_triggers", label) ?? 0,
    provider: readOptionalString(record, "provider", label) ?? undefined,
    event_type: readOptionalString(record, "event_type", label) ?? undefined,
  };
}

export async function listWebhooks(token: string, namespace: string): Promise<WebhookReceiverInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/webhooks", namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item, index) => parseWebhookReceiverPayload(item, `WebhookReceiverInfo[${index}]`));
  });
}

export async function fetchWebhook(token: string, namespace: string, name: string): Promise<WebhookReceiverInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/webhooks/${encodeURIComponent(name)}`, namespace), token);
  return parseJsonResponse(response, (payload) => parseWebhookReceiverPayload(payload, "WebhookReceiverInfo"));
}

export interface CreateWebhookPayload {
  name: string;
  secret_ref: string;
  ip_allowlist?: string[];
  rate_limit?: number;
  max_payload_bytes?: number;
  enabled?: boolean;
  provider?: WebhookProvider;
  api_key_enabled?: boolean;
}

export interface UpdateWebhookPayload {
  secret_ref?: string;
  ip_allowlist?: string[];
  rate_limit?: number;
  max_payload_bytes?: number;
  enabled?: boolean;
  provider?: WebhookProvider;
  api_key_enabled?: boolean;
}

export async function createWebhook(token: string, namespace: string, payload: CreateWebhookPayload): Promise<WebhookReceiverInfo> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/webhooks", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, (p) => parseWebhookReceiverPayload(p, "WebhookReceiverInfo"));
}

export async function updateWebhook(token: string, namespace: string, name: string, payload: UpdateWebhookPayload): Promise<WebhookReceiverInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/webhooks/${encodeURIComponent(name)}`, namespace), token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, (p) => parseWebhookReceiverPayload(p, "WebhookReceiverInfo"));
}

export async function deleteWebhook(token: string, namespace: string, name: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/webhooks/${encodeURIComponent(name)}`, namespace), token, {
    method: "DELETE",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to delete webhook", text);
  }
}

export async function fetchWebhookHistory(token: string, namespace: string, name: string, limit = 50): Promise<WebhookInvocationInfo[]> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/v1/webhooks/${encodeURIComponent(name)}/history`, namespace) + `&limit=${limit}`,
    token,
  );
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item, index) => parseWebhookInvocationPayload(item, `WebhookInvocationInfo[${index}]`));
  });
}

// ── Workflow Trigger API ──────────────────────────────────────────────────

function parseWorkflowTriggerPayload(payload: unknown, label = "WorkflowTriggerInfo"): WorkflowTriggerInfo {
  const record = expectRecord(payload, label);
  return {
    id: readNumber(record, "id", label),
    namespace: readString(record, "namespace", label),
    name: readString(record, "name", label),
    source_kind: readString(record, "source_kind", label),
    source_ref: readString(record, "source_ref", label),
    event_filter: readRecord(record, "event_filter", label, {}),
    workflow_ref: readRecord(record, "workflow_ref", label, {}) as Record<string, string>,
    agent_ref: readRecord(record, "agent_ref", label, {}) as Record<string, string>,
    target_kind: readOptionalString(record, "target_kind", label) ?? "workflow",
    payload_mapping: readRecord(record, "payload_mapping", label, {}) as Record<string, string>,
    max_retries: readOptionalNumber(record, "max_retries", label) ?? 3,
    backoff_seconds: readOptionalNumber(record, "backoff_seconds", label) ?? 60,
    enabled: readBoolean(record, "enabled", label, true),
    execution_count: readOptionalNumber(record, "execution_count", label) ?? 0,
    dead_letter_count: readOptionalNumber(record, "dead_letter_count", label) ?? 0,
    last_triggered: readOptionalString(record, "last_triggered", label),
    notifications: readRecord(record, "notifications", label, {}) as { on_success?: string[]; on_failure?: string[] },
  };
}

function parseTriggerExecutionPayload(payload: unknown, label = "TriggerExecutionInfo"): TriggerExecutionInfo {
  const record = expectRecord(payload, label);
  return {
    id: readNumber(record, "id", label),
    trigger_name: readString(record, "trigger_name", label),
    namespace: readString(record, "namespace", label),
    webhook_name: readString(record, "webhook_name", label, ""),
    executed_at: readOptionalString(record, "executed_at", label) ?? "",
    status: readString(record, "status", label, ""),
    workflow_run_id: readOptionalString(record, "workflow_run_id", label),
    error_message: readOptionalString(record, "error_message", label),
    attempt_count: readOptionalNumber(record, "attempt_count", label) ?? 0,
    target_kind: readOptionalString(record, "target_kind", label) ?? undefined,
    agent_name: readOptionalString(record, "agent_name", label) ?? undefined,
    agent_namespace: readOptionalString(record, "agent_namespace", label) ?? undefined,
  };
}

export async function listTriggers(token: string, namespace: string): Promise<WorkflowTriggerInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/workflow-triggers", namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item, index) => parseWorkflowTriggerPayload(item, `WorkflowTriggerInfo[${index}]`));
  });
}

export async function fetchTrigger(token: string, namespace: string, name: string): Promise<WorkflowTriggerInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/workflow-triggers/${encodeURIComponent(name)}`, namespace), token);
  return parseJsonResponse(response, (payload) => parseWorkflowTriggerPayload(payload, "WorkflowTriggerInfo"));
}

export interface CreateTriggerPayload {
  name: string;
  source_kind: string;
  source_ref: string;
  event_filter?: Record<string, unknown>;
  workflow_ref?: Record<string, string>;
  agent_ref?: Record<string, string>;
  target_kind?: string;
  payload_mapping?: Record<string, string>;
  max_retries?: number;
  backoff_seconds?: number;
  enabled?: boolean;
  notifications?: { on_success?: string[]; on_failure?: string[] };
}

export interface UpdateTriggerPayload {
  source_kind?: string;
  source_ref?: string;
  event_filter?: Record<string, unknown>;
  workflow_ref?: Record<string, string>;
  agent_ref?: Record<string, string>;
  target_kind?: string;
  payload_mapping?: Record<string, string>;
  max_retries?: number;
  backoff_seconds?: number;
  enabled?: boolean;
  notifications?: { on_success?: string[]; on_failure?: string[] };
}

export async function createTrigger(token: string, namespace: string, payload: CreateTriggerPayload): Promise<WorkflowTriggerInfo> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/workflow-triggers", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, (p) => parseWorkflowTriggerPayload(p, "WorkflowTriggerInfo"));
}

export async function updateTrigger(token: string, namespace: string, name: string, payload: UpdateTriggerPayload): Promise<WorkflowTriggerInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/workflow-triggers/${encodeURIComponent(name)}`, namespace), token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, (p) => parseWorkflowTriggerPayload(p, "WorkflowTriggerInfo"));
}

export async function deleteTrigger(token: string, namespace: string, name: string): Promise<void> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/workflow-triggers/${encodeURIComponent(name)}`, namespace), token, {
    method: "DELETE",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to delete trigger", text);
  }
}

export async function fetchTriggerHistory(token: string, namespace: string, name: string, limit = 50): Promise<TriggerExecutionInfo[]> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/v1/workflow-triggers/${encodeURIComponent(name)}/history`, namespace) + `&limit=${limit}`,
    token,
  );
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item, index) => parseTriggerExecutionPayload(item, `TriggerExecutionInfo[${index}]`));
  });
}

// ── Webhook Secret Generation ─────────────────────────────────────────────

export async function generateWebhookSecret(token: string, namespace: string, name: string): Promise<{ secret: string; key_id: string }> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/v1/webhooks/${encodeURIComponent(name)}/generate-secret`, namespace),
    token,
    { method: "POST" },
  );
  return parseJsonResponse(response, (p) => {
    const record = expectRecord(p, "SecretGeneration");
    return {
      secret: readString(record, "secret", "SecretGeneration"),
      key_id: readString(record, "key_id", "SecretGeneration", "primary"),
    };
  });
}

// ── Dead-Letter Queue ─────────────────────────────────────────────────────

export async function fetchDeadLetterExecutions(token: string, namespace: string, name: string, limit = 50): Promise<TriggerExecutionInfo[]> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/v1/webhooks/${encodeURIComponent(name)}/dead-letter`, namespace) + `&limit=${limit}`,
    token,
  );
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) return [];
    return payload.map((item, index) => parseTriggerExecutionPayload(item, `TriggerExecutionInfo[${index}]`));
  });
}

export async function replayDeadLetter(token: string, namespace: string, executionId: number): Promise<void> {
  const response = await fetchAuthenticated(
    buildUrl(`/api/v1/webhooks/dead-letter/${executionId}/replay`, namespace),
    token,
    { method: "POST" },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, "Failed to replay execution", text);
  }
}

// ── Incident API ──────────────────────────────────────────────────────────

function parseIncidentPayload(payload: unknown, label = "IncidentInfo"): IncidentInfo {
  const record = expectRecord(payload, label);
  return {
    id: readNumber(record, "id", label),
    namespace: readOptionalString(record, "namespace", label) ?? "default",
    name: readString(record, "name", label),
    title: readString(record, "title", label),
    description: readOptionalString(record, "description", label) ?? "",
    severity: (readOptionalString(record, "severity", label) ?? "warning") as IncidentInfo["severity"],
    source: (readOptionalString(record, "source", label) ?? "manual") as IncidentInfo["source"],
    status: (readOptionalString(record, "status", label) ?? "firing") as IncidentInfo["status"],
    labels: (record.labels as Record<string, string>) ?? {},
    annotations: (record.annotations as Record<string, string>) ?? {},
    assigned_agent: readOptionalString(record, "assigned_agent", label) ?? null,
    escalation_timeout_minutes: readOptionalNumber(record, "escalation_timeout_minutes", label) ?? 15,
    escalated: readOptionalBoolean(record, "escalated", label) ?? false,
    auto_acknowledge: readOptionalBoolean(record, "auto_acknowledge", label) ?? true,
    acknowledged_at: readOptionalString(record, "acknowledged_at", label) ?? null,
    resolved_at: readOptionalString(record, "resolved_at", label) ?? null,
    closed_at: readOptionalString(record, "closed_at", label) ?? null,
    escalated_at: readOptionalString(record, "escalated_at", label) ?? null,
    alertmanager_fingerprint: readOptionalString(record, "alertmanager_fingerprint", label) ?? null,
    workflow_ref_name: readOptionalString(record, "workflow_ref_name", label) ?? null,
    workflow_ref_namespace: readOptionalString(record, "workflow_ref_namespace", label) ?? null,
    workflow_run_id: readOptionalString(record, "workflow_run_id", label) ?? null,
    timeline: Array.isArray(record.timeline) ? record.timeline.map((t: unknown, i: number) => {
      const te = expectRecord(t, `timeline[${i}]`);
      return { timestamp: readString(te, "timestamp", `timeline[${i}]`), event: readString(te, "event", `timeline[${i}]`), message: readString(te, "message", `timeline[${i}]`) };
    }) : [],
    created_at: readString(record, "created_at", label),
    updated_at: readString(record, "updated_at", label),
  };
}

export async function listIncidents(token: string, namespace: string, params?: { status?: string; severity?: string; limit?: number; offset?: number }): Promise<{ incidents: IncidentInfo[]; total: number }> {
  let url = buildUrl("/api/v1/incidents", namespace);
  if (params?.status) url += `&status=${encodeURIComponent(params.status)}`;
  if (params?.severity) url += `&severity=${encodeURIComponent(params.severity)}`;
  if (params?.limit) url += `&limit=${params.limit}`;
  if (params?.offset) url += `&offset=${params.offset}`;
  const response = await fetchAuthenticated(url, token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "listIncidents");
    const items = record.incidents;
    return {
      incidents: Array.isArray(items) ? items.map((item: unknown, i: number) => parseIncidentPayload(item, `IncidentInfo[${i}]`)) : [],
      total: readOptionalNumber(record, "total", "listIncidents") ?? 0,
    };
  });
}

export async function getIncident(token: string, namespace: string, name: string): Promise<IncidentInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/incidents/${encodeURIComponent(name)}`, namespace), token);
  return parseJsonResponse(response, (p) => parseIncidentPayload(p, "IncidentInfo"));
}

export async function createIncident(token: string, namespace: string, body: Partial<IncidentInfo> & { name: string; title: string }): Promise<IncidentInfo> {
  const response = await fetchAuthenticated(buildUrl("/api/v1/incidents", namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => parseIncidentPayload(p, "IncidentInfo"));
}

export async function updateIncidentStatus(token: string, namespace: string, name: string, body: { status?: string; message?: string; workflow_run_id?: string }): Promise<IncidentInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/incidents/${encodeURIComponent(name)}`, namespace), token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response, (p) => parseIncidentPayload(p, "IncidentInfo"));
}

export async function escalateIncident(token: string, namespace: string, name: string, message?: string): Promise<IncidentInfo> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/incidents/${encodeURIComponent(name)}/escalate`, namespace), token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: message ?? "Manual escalation" }),
  });
  return parseJsonResponse(response, (p) => parseIncidentPayload(p, "IncidentInfo"));
}

export async function getIncidentTimeline(token: string, namespace: string, name: string): Promise<{ timeline: Array<{ timestamp: string; event: string; message: string }> }> {
  const response = await fetchAuthenticated(buildUrl(`/api/v1/incidents/${encodeURIComponent(name)}/timeline`, namespace), token);
  return parseJsonResponse(response, (p) => {
    const record = expectRecord(p, "IncidentTimeline");
    return { timeline: Array.isArray(record.timeline) ? record.timeline : [] };
  });
}

// ── Agent API ─────────────────────────────────────────────────────────────
