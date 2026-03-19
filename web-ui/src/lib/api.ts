import { fetchEventSource } from "@microsoft/fetch-event-source";

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
  CreateUserPayload,
  CreateAgentPayload,
  DeleteResponse,
  EvalCaseResult,
  EvalInfo,
  EvalPayload,
  EvalTestCase,
  EvalUpdatePayload,
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
  LLMKeyInfo,
  LLMModelInfo,
  LLMProvider,
  LoopConfig,
  ModelSuggestion,
  McpHubServer,
  McpToolCategory,
  PolicyInfo,
  PolicyInputGuardrails,
  PolicyOutputGuardrails,
  RuntimeKind,
  SubagentInvocationMetadata,
  SubagentInvocationResult,
  SubagentSharedFile,
  StreamEvent,
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
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";
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

export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || err.message;
  if (err instanceof Error) return err.message;
  return String(err);
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
      localStorage.setItem("ai-agent-sandbox/token", session.access_token);

      // Retry the original request with the new token
      return fetch(url, buildAuthenticatedInit(session.access_token, requestId, init));
    } catch {
      _refreshPromise = null;
      // Refresh truly failed — clear stale token so the UI re-shows login
      localStorage.removeItem("ai-agent-sandbox/token");
      return response;
    }
  }

  return response;
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
  if (runtimeKind !== "langgraph" && runtimeKind !== "goose" && runtimeKind !== "codex" && runtimeKind !== "opencode") {
    throw new Error(`${label}.${key} must be 'langgraph', 'goose', 'codex', or 'opencode'.`);
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
    goose_builtin_extensions: readStringArray(record, "goose_builtin_extensions", label, []),
    goose_stdio_extensions: readStringArray(record, "goose_stdio_extensions", label, []),
    goose_streamable_http_extensions: readStringArray(record, "goose_streamable_http_extensions", label, []),
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
  if (rawSkillSummaries !== undefined && !Array.isArray(rawSkillSummaries)) {
    throw new Error("AgentDetail.skill_summaries must be an array.");
  }
  return {
    ...base,
    system_prompt: readString(record, "system_prompt", "AgentDetail", ""),
    policy_ref: readOptionalString(record, "policy_ref", "AgentDetail"),
    storage_size: readOptionalString(record, "storage_size", "AgentDetail"),
    runtime_kind: readRuntimeKind(record, "runtime_kind", "AgentDetail", "langgraph"),
    enable_gvisor: readBoolean(record, "enable_gvisor", "AgentDetail", false),
    mcp_servers: readStringArray(record, "mcp_servers", "AgentDetail"),
    mcp_sidecars: readRecordArray(record, "mcp_sidecars", "AgentDetail"),
    a2a_config: parseAgentA2AConfigPayload(record.a2a_config, "AgentDetail.a2a_config"),
    skills: parseAgentSkillsConfigPayload(record.skills, "AgentDetail.skills"),
    skill_summaries: (rawSkillSummaries ?? []).map((item, index) =>
      parseAgentSkillSummaryPayload(item, `AgentDetail.skill_summaries[${index}]`),
    ),
    goose_config_files: readRecord(record, "goose_config_files", "AgentDetail"),
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
    step_type: (readOptionalString(record, "step_type", label) as "agent" | "loop" | "conditional" | undefined) ?? "agent",
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
    step_states: readOptionalRecord(record, "step_states", label) as Record<string, WorkflowStepState> | null,
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
  const rawCases = record.cases;
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
    cases: Array.isArray(rawCases) ? rawCases as EvalCaseResult[] : null,
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
    job_name: readOptionalString(record, "job_name", "WorkflowLogsResponse") ?? undefined,
    pod_name: readOptionalString(record, "pod_name", "WorkflowLogsResponse") ?? undefined,
    logs: readString(record, "logs", "WorkflowLogsResponse", ""),
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
    metadata: record.metadata !== undefined && record.metadata !== null
      ? expectRecord(record.metadata, "Invocation summary payload.metadata") : null,
  };
}

async function parseJsonResponse<T>(response: Response, parser: (payload: unknown) => T): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let detail = "";
    if (text) {
      try {
        const parsed = JSON.parse(text) as { detail?: string };
        detail = parsed.detail ?? "";
      } catch {
        detail = text;
      }
    }
    throw new ApiError(
      response.status,
      `Request failed with status ${response.status}`,
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
  const response = await fetch(buildUrl("/api/health"));
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
  const response = await fetch(buildUrl("/api/auth/config"), buildCredentialedInit());
  return parseJsonResponse(response, parseAuthConfigPayload);
}

export async function loginWithPassword(
  username: string,
  password: string,
  provider: "local" | "ldap" = "local",
): Promise<AuthSession> {
  const response = await fetch(
    buildUrl("/api/auth/login"),
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
    buildUrl("/api/auth/register"),
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
    buildUrl("/api/auth/refresh"),
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
  const response = await fetchAuthenticated(buildUrl("/api/auth/logout"), token, {
    method: "POST",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Logout failed with status ${response.status}`);
  }
}

export async function fetchCurrentUser(token: string): Promise<AuthenticatedUser> {
  const response = await fetchAuthenticated(buildUrl("/api/auth/me"), token);
  return parseJsonResponse(response, (payload) => {
    const record = expectRecord(payload, "CurrentUserResponse");
    return parseAuthenticatedUserPayload(record.user, "CurrentUserResponse.user");
  });
}

export async function changePassword(token: string, currentPassword: string, newPassword: string): Promise<AuthenticatedUser> {
  const response = await fetchAuthenticated(buildUrl("/api/auth/change-password"), token, {
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
  input_guardrails: PolicyInputGuardrails;
  output_guardrails: PolicyOutputGuardrails;
  allowed_models: string[];
  allowed_mcp_servers: string[];
  mcp_require_hitl: boolean;
}

export type UpdatePolicyPayload = Partial<Omit<CreatePolicyPayload, "name">>;

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

export async function deletePolicy(token: string, namespace: string, name: string): Promise<DeleteResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/policies/${name}`, namespace), token, {
    method: "DELETE",
  });
  return parseJsonResponse(response, parseDeleteResponsePayload);
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
    buildUrl(`/api/agents/${agentName}/invoke`, namespace),
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

export async function triggerWorkflow(
  token: string,
  namespace: string,
  workflowName: string,
  input?: string,
): Promise<WorkflowInfo> {
  const payload: Record<string, unknown> = {};
  if (input !== undefined) {
    payload.input = input;
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
    return payload as WorkflowRunRecord[];
  });
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

export function createWorkflowStatusStream(
  token: string,
  namespace: string,
  workflowName: string,
): EventSource {
  const url = buildUrl(`/api/workflows/${workflowName}/status/stream`, namespace);
  return new EventSource(`${url}&token=${encodeURIComponent(token)}`);
}

export function createNotificationStream(
  token: string,
  namespace: string,
): EventSource {
  const url = buildUrl("/api/notifications/stream", namespace);
  return new EventSource(`${url}&token=${encodeURIComponent(token)}`);
}

export async function listEvals(token: string, namespace: string): Promise<EvalInfo[]> {
  const response = await fetchAuthenticated(buildUrl("/api/evals", namespace), token);
  return parseJsonResponse(response, (payload) => {
    if (!Array.isArray(payload)) {
      throw new Error("Eval list response must be an array.");
    }
    return payload.map((item, index) => parseEvalInfoPayload(item ?? {}, `EvalInfo[${index}]`));
  });
}

export async function createEval(token: string, namespace: string, payload: EvalPayload): Promise<EvalInfo> {
  const response = await fetchAuthenticated(buildUrl("/api/evals", namespace), token, {
    method: "POST",
    headers: {
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
  const response = await fetchAuthenticated(buildUrl(`/api/evals/${evalName}`, namespace), token, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  return parseJsonResponse(response, parseEvalInfoPayload);
}

export async function deleteEval(token: string, namespace: string, evalName: string): Promise<DeleteResponse> {
  const response = await fetchAuthenticated(buildUrl(`/api/evals/${evalName}`, namespace), token, {
    method: "DELETE",
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

// ── Chat Session Persistence ──

export interface ChatSessionInfo {
  session_id: string;
  title: string;
  agent_name: string;
  namespace: string;
  username: string | null;
  created_at: string | null;
  updated_at: string | null;
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
    return payload as ChatSessionInfo[];
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
