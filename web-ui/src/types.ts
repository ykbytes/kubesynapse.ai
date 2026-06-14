export type RuntimeKind = "opencode" | "pi" | "mistral-vibe";

export type FactoryMode = "lightweight-draft" | "governed-bundle" | "fully-autonomous";

/** Runtimes still under active development — shown with a red "Alpha" badge in the UI. */
export const ALPHA_RUNTIMES: ReadonlySet<RuntimeKind> = new Set<RuntimeKind>(["pi", "mistral-vibe"]);

export interface A2APeerRef {
  name: string;
  namespace: string;
}

export interface AgentA2AConfig {
  allowed_callers?: A2APeerRef[];
}

export interface TextFileDraft {
  id: string;
  path: string;
  content: string;
}

export interface AgentSkillsConfig {
  files?: Record<string, string>;
  config_map_ref?: string;
}

export interface OpaConfig {
  enabled?: boolean;
  policies?: string[];
  config_map_ref?: string;
}

/* ── Git Config types ── */

export type GitAuthMethod = "token" | "basic" | "ssh";
export type GitPushPolicy = "after-each-commit" | "end-of-session" | "on-approval" | "never";

export interface GitConfig {
  repo_url: string;
  default_branch?: string;
  branch?: string;
  push_policy?: GitPushPolicy;
  auth_method: GitAuthMethod;
  credential_secret_ref?: string;
}

export interface GitCredentialRequest {
  auth_method: GitAuthMethod;
  token?: string;
  username?: string;
  password?: string;
  ssh_private_key?: string;
}

export interface GitCredentialInfo {
  exists: boolean;
  secret_name: string;
  auth_method?: string;
}

export interface GitFormState {
  enabled: boolean;
  repoUrl: string;
  authMethod: GitAuthMethod;
  pushPolicy: GitPushPolicy;
  defaultBranch: string;
  branch: string;
  token: string;
  username: string;
  password: string;
  sshPrivateKey: string;
}

export interface GitHubConfig {
  credential_secret_ref?: string;
}

export interface GitHubCredentialRequest {
  token: string;
}

export interface GitHubCredentialInfo {
  exists: boolean;
  secret_name: string;
}

export interface GitHubFormState {
  enabled: boolean;
  token: string;
}

/* ── Loop / Circuit Breaker types ── */

export interface CircuitBreakerConfig {
  noProgressThreshold?: number;
  cooldownMinutes?: number;
}

export interface LoopExitConditions {
  planComplete?: boolean;
  completionSignalCount?: number;
}

export interface LoopConfig {
  maxIterations?: number;
  planSource?: "inline" | "prompt";
  plan?: string;
  commitAfterEachItem?: boolean;
  circuitBreaker?: CircuitBreakerConfig;
  exitConditions?: LoopExitConditions;
}

export interface LoopProgress {
  iteration: number;
  maxIterations: number;
  completedItems: number;
  totalItems: number;
  checklistItems?: { text: string; done: boolean }[];
  circuitBreakerState?: {
    state: string;
    consecutiveNoProgress: number;
    threshold: number;
  };
  exitReason?: string | null;
  featureBranch?: string | null;
  lastCommitSha?: string | null;
}

export interface AgentSkillSummary {
  path: string;
  name: string;
  description?: string | null;
  instructions_preview?: string | null;
  allowed_sandbox_tools: string[];
  allowed_mcp_servers: string[];
  allowed_a2a_targets: A2APeerRef[];
  allow_subagents: boolean;
  valid: boolean;
  warnings: string[];
}

export interface A2AInvocationMetadata {
  targetAgent?: string | null;
  targetNamespace?: string | null;
  targetThreadId?: string | null;
  responseStatus?: string | null;
  transport?: string | null;
  callerAgent?: string | null;
  callerNamespace?: string | null;
  parentThreadId?: string | null;
  callerRequestId?: string | null;
}

export interface SubagentInputFile {
  path: string;
  purpose?: string | null;
  include_content?: boolean;
  max_chars?: number;
}

export interface InvokeSubagent {
  name: string;
  namespace: string;
  role?: string;
  task?: string;
  input_files?: SubagentInputFile[];
  result_file_path?: string;
  share_sandbox_session?: boolean;
  timeout_seconds?: number;
}

export interface SpecialistSubagentDraft {
  id: string;
  name: string;
  namespace: string;
  role: string;
  task: string;
  inputFilesText: string;
  resultFilePath: string;
  shareSandboxSession: boolean;
  timeoutSeconds: string;
}

export interface SubagentSharedFile {
  path?: string | null;
  purpose?: string | null;
  chars?: number | null;
}

export interface SubagentInvocationResult {
  name: string;
  namespace: string;
  role?: string | null;
  task?: string | null;
  status: string;
  transport?: string | null;
  threadId?: string | null;
  responsePreview?: string | null;
  resultFilePath?: string | null;
  sharedFiles: SubagentSharedFile[];
  warnings: string[];
  approvalName?: string | null;
  retryAfterSeconds?: number | null;
  error?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface SubagentInvocationMetadata {
  strategy?: string | null;
  count?: number | null;
  sharedSandboxSession?: boolean | null;
  sharedFiles: SubagentSharedFile[];
  resultFiles: string[];
  results: SubagentInvocationResult[];
}

export interface AgentDiscoveryPeer {
  name: string;
  namespace: string;
  exists: boolean;
  model?: string | null;
  status?: string | null;
  runtime_kind?: RuntimeKind | null;
  accepts_caller: boolean;
  reachable: boolean;
  reason?: string | null;
}

export interface AgentDiscoveryResponse {
  agent_name: string;
  namespace: string;
  policy_ref?: string | null;
  peers: AgentDiscoveryPeer[];
}

export interface AgentInfo {
  name: string;
  model: string;
  namespace: string;
  status: string;
  runtime_kind?: RuntimeKind;
}

export type WorkspaceView = "agents" | "chat" | "workflows" | "catalog" | "composer" | "policies" | "intelligence" | "settings" | "admin" | "docs" | "webhooks" | "incidents";

/* ── LLM Provider types ── */

export interface LLMModelInfo {
  model_name: string;
  litellm_params: Record<string, unknown>;
  model_info?: Record<string, unknown>;
}

export interface LLMKeyInfo {
  name: string;
  is_set: boolean;
}

/* ── Provider-centric LLM types ── */

export interface ProviderModel {
  model_name: string;
  litellm_model: string;
  id: string;
}

export interface LLMProvider {
  key_name: string;
  label: string;
  prefix: string;
  is_configured: boolean | null;
  model_count: number;
  models: ProviderModel[];
}

export interface ModelSuggestion {
  model_id: string;
  display_name: string;
  description?: string;
}

export interface ConnectedProviderModel {
  id: string;
  name: string;
  description?: string | null;
}

export interface ConnectedProvider {
  id: string;
  label: string;
  kind: "builtin" | "custom";
  description: string;
  auth_type: "apiKey" | "oauth";
  connected: boolean;
  docs_url?: string | null;
  base_url?: string | null;
  key_placeholder?: string | null;
  editable: boolean;
  headers: Record<string, string>;
  models: ConnectedProviderModel[];
}

export interface ProviderCatalogModel {
  provider_id: string;
  provider_label: string;
  model_id: string;
  model_ref: string;
  connected: boolean;
  kind: "builtin" | "custom";
  description?: string | null;
}

export interface CustomProviderPayload {
  provider_id: string;
  name: string;
  base_url: string;
  description?: string;
  api_key?: string;
  headers: Record<string, string>;
  models: string[];
}

/* ── GitHub Copilot auth types ── */

export interface CopilotDeviceFlowResponse {
  user_code: string;
  verification_uri: string;
  interval: number;
}

export interface CopilotPollResponse {
  status: "pending" | "success" | "error";
  interval?: number;
  error?: string;
}

export interface CopilotAuthStatus {
  connected: boolean;
}

/* ── Skills Catalog types ── */

export interface CatalogSkill {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  files: string[];
  total_size_bytes: number;
}

export interface CatalogSkillDetail extends CatalogSkill {
  assets: Record<string, string>;
}

export interface McpToolCategory {
  id: string;
  name: string;
  description: string;
  icon: string;
  default_port: number;
  sidecar_image?: string | null;
  config_schema?: ConfigField[];
  credential_type?: string | null;
}

/* ── Config field types for MCP tool drawers ── */

export interface ConfigFieldOption {
  value: string;
  label: string;
}

export interface ConfigFieldVisibility {
  field: string;
  values: string[];
}

export interface ConfigField {
  key: string;
  label: string;
  type: "text" | "password" | "select" | "textarea" | "toggle";
  placeholder?: string;
  required?: boolean;
  group?: string;
  help?: string;
  default?: string;
  is_credential?: boolean;
  options?: ConfigFieldOption[];
  visible_when?: ConfigFieldVisibility;
}

export interface McpHubServer {
  id: string;
  name: string;
  description: string;
  icon: string;
  credential_type?: string | null;
  config_schema?: ConfigField[];
}

/* ── MCP Registry types ── */

export type McpTransport = "remote" | "hub" | "sidecar";
export type McpAuthType = "none" | "bearer" | "api_key" | "oauth" | "connection_string" | "kubeconfig";
export type McpSupportLevel = "ready" | "limited" | "planned";
export type McpConnectionValidationStatus = "draft" | "valid" | "warning" | "invalid";
export type McpConnectionOAuthState = "required" | "connected" | "expired";

export interface McpConnectionCredentialField {
  key: string;
  label: string;
  type: string;
  group: string;
  required: boolean;
  configured: boolean;
}

export interface McpConnectionValidation {
  status: McpConnectionValidationStatus;
  message?: string | null;
  detail?: Record<string, unknown> | null;
  last_validated_at?: string | null;
}

export interface McpConnectionRuntimeHeader {
  name: string;
  envVar?: string | null;
  prefix?: string | null;
}

export interface McpConnectionRuntimeSidecar {
  name: string;
  image: string;
  port: number;
  endpointPath?: string | null;
  env: Array<Record<string, unknown>>;
}

export interface McpConnectionRuntimePreview {
  kind: "remote" | "sidecar";
  configKey: string;
  url?: string | null;
  headers?: McpConnectionRuntimeHeader[];
  sidecar?: McpConnectionRuntimeSidecar | null;
}

export interface McpConnectionOAuth {
  connected: boolean;
  state: McpConnectionOAuthState;
  expires_at?: string | null;
  refresh_available: boolean;
  scope: string[];
}

export interface McpConnectionOAuthStart {
  authorization_url: string;
  expires_at?: string | null;
}

export interface McpConnection {
  id: string;
  namespace: string;
  name: string;
  slug: string;
  server_id: string;
  server_name?: string | null;
  transport: McpTransport;
  auth_type: McpAuthType;
  config: Record<string, unknown>;
  credential_metadata: McpConnectionCredentialField[];
  validation: McpConnectionValidation;
  support_level: McpSupportLevel;
  attachable: boolean;
  status_reason?: string | null;
  runtime_preview?: McpConnectionRuntimePreview | null;
  oauth?: McpConnectionOAuth | null;
  binding_count: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface McpConnectionBinding {
  agent_name: string;
  namespace: string;
  connection_id: string;
  connection_name: string;
  server_id: string;
  transport: string;
}

export interface AgentMcpConnection {
  connection_id?: string | null;
  name: string;
  slug: string;
  server_id: string;
  server_name?: string | null;
  transport: McpTransport;
  support_level: McpSupportLevel;
  attachable: boolean;
  status_reason?: string | null;
  source: string;
  config: Record<string, unknown>;
  credential_metadata: McpConnectionCredentialField[];
  validation: McpConnectionValidation;
  runtime: McpConnectionRuntimePreview;
}

export interface McpRegistryServer {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  transport: McpTransport;
  endpoint?: string | null;
  suggested_endpoint?: string | null;
  protocol_label?: string | null;
  deployment_model?: string | null;
  docs_url?: string | null;
  repository_url?: string | null;
  connection_notes?: string | null;
  hub_server_name?: string | null;
  auth_type: McpAuthType;
  oauth_scopes?: string[];
  auth_header_name?: string | null;
  auth_header_prefix?: string | null;
  enabled: boolean;
  tags: string[];
  tools_count: number;
  tool_names: string[];
  config_schema: ConfigField[];
  sidecar_image?: string | null;
  sidecar_port?: number | null;
  support_level: McpSupportLevel;
  attachable: boolean;
  status_reason?: string | null;
}

export interface McpProfileServer {
  id: string;
  name: string;
  transport: McpTransport;
  support_level: McpSupportLevel;
  attachable: boolean;
  status_reason?: string | null;
}

export interface McpProfile {
  id: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  servers: string[];
  resolved_servers: McpProfileServer[];
  attachable_servers: McpProfileServer[];
  blocked_servers: McpProfileServer[];
  can_apply: boolean;
  support_level: McpSupportLevel;
  total_tools: number;
  tags: string[];
}

export interface McpCategory {
  id: string;
  name: string;
  count: number;
}

export interface McpStats {
  total_servers: number;
  total_tools: number;
  total_profiles: number;
  by_transport: Record<string, number>;
  categories: number;
}

export interface SkillsCatalogResponse {
  skills: CatalogSkill[];
  total: number;
}

export interface McpToolsResponse {
  categories: McpToolCategory[];
}

export interface PolicyInputGuardrails {
  blockPromptInjection: boolean;
  blockedPatterns: string[];
  maxInputTokens: number;
}

export interface PolicyOutputGuardrails {
  maskPII: boolean;
  blockedOutputPatterns: string[];
  maxOutputTokens: number;
}

export interface PolicyToolPolicy {
  maxDelegationDepth?: number;
  allowedToolPrefixes: string[];
  blockedToolNames: string[];
  requireApprovalFor: string[];
  adminToolCeiling?: Record<string, "allow" | "ask" | "deny">;
}

export interface PolicyMemoryPolicy {
  maxInjectedMemories?: number;
  maxInjectedChars?: number;
  allowedMemoryTypes: string[];
  autoPromote: boolean;
}

export interface PolicyInfo {
  name: string;
  namespace: string;
  sealed?: boolean;
  input_guardrails: PolicyInputGuardrails;
  output_guardrails: PolicyOutputGuardrails;
  allowed_models: string[];
  allowed_mcp_servers: string[];
  mcp_require_hitl: boolean;
  tool_policy: PolicyToolPolicy;
  memory_policy: PolicyMemoryPolicy;
}

export interface AgentDetail extends AgentInfo {
  system_prompt: string;
  policy_ref?: string | null;
  storage_size?: string | null;
  runtime_kind: RuntimeKind;
  enable_gvisor: boolean;
  mcp_connections: AgentMcpConnection[];
  mcp_servers: string[];
  mcp_sidecars: Array<Record<string, unknown>>;
  a2a_config: AgentA2AConfig;
  skills: AgentSkillsConfig;
  skill_summaries: AgentSkillSummary[];
  opa?: OpaConfig | null;
  opencode_config_files: Record<string, unknown>;
  git_config?: GitConfig | null;
  github_config?: GitHubConfig | null;
  created_at?: string | null;
  /** Reconciliation error from the operator (CRD status conditions) */
  reconcile_error?: string | null;
}

export interface CreateAgentPayload {
  name: string;
  model: string;
  system_prompt?: string;
  policy_ref?: string;
  storage_size?: string;
  runtime_kind?: RuntimeKind;
  enable_gvisor?: boolean;
  mcp_connection_ids?: string[];
  mcp_servers?: string[];
  mcp_sidecars?: Array<Record<string, unknown>>;
  a2a_config?: AgentA2AConfig;
  skills?: AgentSkillsConfig;
  opa?: OpaConfig | null;
  opencode_config_files?: Record<string, unknown>;
  git_config?: GitConfig | null;
  github_config?: GitHubConfig | null;
}

export interface UpdateAgentPayload {
  model: string;
  system_prompt?: string;
  policy_ref?: string;
  storage_size?: string;
  runtime_kind?: RuntimeKind;
  enable_gvisor?: boolean;
  mcp_connection_ids?: string[];
  mcp_servers?: string[];
  mcp_sidecars?: Array<Record<string, unknown>>;
  a2a_config?: AgentA2AConfig;
  skills?: AgentSkillsConfig;
  opa?: OpaConfig | null;
  opencode_config_files?: Record<string, unknown>;
  git_config?: GitConfig | null;
  github_config?: GitHubConfig | null;
}

export interface GatewayHealth {
  status: string;
  gateway: string;
  auth_mode: string;
  browser_auth_enabled?: boolean;
  local_auth_enabled?: boolean;
  shared_token_enabled?: boolean;
  nats_url: string;
  qdrant_url: string;
}

export type UserRole = "viewer" | "operator" | "admin";

export interface AuthenticatedUser {
  sub: string;
  id: string;
  username: string;
  display_name: string;
  email?: string | null;
  role: UserRole;
  allowed_namespaces: string[];
  capabilities?: Record<string, boolean>;
  auth_provider: string;
  session_id?: string | null;
  is_active: boolean;
}

export interface AdminUser {
  id: number;
  username: string;
  email?: string | null;
  display_name: string;
  role: UserRole;
  allowed_namespaces: string[];
  capabilities?: Record<string, boolean>;
  auth_provider: string;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
}

export interface AuthProviderSummary {
  id: string;
  name: string;
  kind: string;
  brand?: string | null;
  supported?: boolean;
}

export interface AuthConfig {
  auth_mode: string;
  local_enabled: boolean;
  registration_enabled: boolean;
  shared_token_enabled: boolean;
  browser_auth_enabled: boolean;
  bootstrap_complete: boolean;
  password_providers: string[];
  oidc_providers: AuthProviderSummary[];
  saml_providers: AuthProviderSummary[];
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  expires_in: number;
  expires_at: string;
  refresh_expires_at?: string | null;
  user: AuthenticatedUser;
  auth_mode: string;
}

export interface CreateUserPayload {
  username: string;
  password: string;
  email?: string;
  display_name?: string;
  role?: UserRole;
  allowed_namespaces?: string[];
}

export interface UpdateUserPayload {
  display_name?: string;
  role?: UserRole;
  is_active?: boolean;
  allowed_namespaces?: string[];
  capabilities?: Record<string, boolean>;
}

export interface InvokePayload {
  prompt: string;
  images?: Array<{ data: string; media_type: string; name?: string }>;
  thread_id?: string;
  model?: string;
  system?: string;
  require_approval?: boolean;
  approval_action?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  mcp_server?: string;
  a2a_target_agent?: string;
  a2a_target_namespace?: string;
  a2a_timeout_seconds?: number;
  subagents?: InvokeSubagent[];
  subagent_strategy?: "sequential" | "parallel";
  debug?: boolean;
  no_session?: boolean;
  max_turns?: number;
  working_directory?: string;
  builtin_extensions?: string[];
  stdio_extensions?: string[];
  streamable_http_extensions?: string[];
  sandbox_session?: Record<string, unknown>;
  team_context?: string;
  output_format?: string;
  autonomous?: boolean;
  max_retries?: number;
  output_schema?: Record<string, unknown>;
  factory_mode?: FactoryMode;
}

export interface InvokeResponse {
  agent_name: string;
  response: string;
  thread_id: string;
  model: string;
  policy_name?: string | null;
  tool_name?: string | null;
  tool_result?: unknown;
  sandbox_session?: Record<string, unknown> | null;
  status: string;
  approval_name?: string | null;
  retry_after_seconds?: number | null;
  a2a?: A2AInvocationMetadata | null;
  subagents?: SubagentInvocationMetadata | null;
  warnings: string[];
  artifacts?: Array<Record<string, unknown>> | null;
  tool_calls?: Array<Record<string, unknown>> | null;
  metadata?: Record<string, unknown> | null;
}

export interface AgentLogsResponse {
  agent_name: string;
  pod_name?: string;
  logs: string;
}

export interface WorkflowLogsResponse {
  workflow_name: string;
  run_id?: string | null;
  job_name?: string;
  pod_name?: string;
  source?: string;
  archived_log_available?: boolean;
  archived_log_source?: string | null;
  archived_log_truncated?: boolean;
  archived_log_captured_at?: string | null;
  logs: string;
}

export interface ApprovalInfo {
  name: string;
  namespace: string;
  decision: string;
  agent_name: string;
  action: string;
  requested_at?: string | null;
  decided_by?: string | null;
  decided_at?: string | null;
  reason?: string | null;
}

export interface WorkflowStep {
  name: string;
  agent_ref: string;
  prompt: string;
  depends_on: string[];
  require_approval: boolean;
  execution?: Record<string, unknown> | null;
  step_type?: "agent" | "loop" | "conditional" | "review";
  loop_config?: LoopConfig | null;
  condition_expr?: string | null;
  then_steps?: string[] | null;
  else_steps?: string[] | null;
  verify?: string | null;
  review_criteria?: string | null;
}

export interface WorkflowPayload {
  name: string;
  description?: string;
  input?: string;
  context_ref?: string;
  message_bus?: string;
  steps: WorkflowStep[];
}

export interface WorkflowUpdatePayload {
  description?: string;
  input?: string;
  context_ref?: string;
  message_bus?: string;
  steps: WorkflowStep[];
}

export interface VerificationResult {
  passed: boolean;
  response: string;
  criteria: string;
  verifyAttempt?: number;
}

export interface ReviewResult {
  approved: boolean;
  verdict: string;
  response: string;
  criteria: string;
}

export interface PlanProgressItem {
  text: string;
  done: boolean;
}

export interface PlanProgress {
  items: PlanProgressItem[];
  completedItems: number;
  totalItems: number;
}

export interface IterationFailure {
  iteration: number;
  error: string;
  failureClass: string;
}

export interface WorkflowStepArtifactSummary {
  path?: string | null;
  name?: string | null;
  tool?: string | null;
  status?: string | null;
  type?: string | null;
  preview?: string | null;
  /** Preview of artifact content (from backend output/content field) */
  content?: string | null;
}

export interface WorkflowStepToolCallSummary {
  tool?: string | null;
  status?: string | null;
  inputPreview?: string | null;
  preview?: string | null;
  /** Duration in milliseconds */
  durationMs?: number | null;
  /** Preview of tool output/result */
  outputPreview?: string | null;
  /** Single file path (for file operations) */
  path?: string | null;
  /** Multiple file paths (for batch operations) */
  paths?: string[] | null;
  /** Error message if tool call failed */
  error?: string | null;
  /** Extracted search query (for search tools) */
  query?: string | null;
}

export interface WorkflowStepState {
  stepName: string;
  agentRef: string;
  status: string;
  attempts?: number;
  startedAt?: string | null;
  completedAt?: string | null;
  updatedAt?: string | null;
  latencyMs?: number | null;
  error?: string | null;
  failureClass?: string | null;
  approvalWaitMs?: number | null;
  workerJob?: Record<string, unknown> | null;
  execution?: Record<string, unknown> | null;
  loopProgress?: LoopProgress | null;
  planProgress?: PlanProgress | null;
  verificationResult?: VerificationResult | null;
  reviewResult?: ReviewResult | null;
  iterationFailures?: IterationFailure[] | null;
  responsePreview?: string | null;
  artifactCount?: number | null;
  toolCallCount?: number | null;
  artifacts?: WorkflowStepArtifactSummary[] | null;
  toolCalls?: WorkflowStepToolCallSummary[] | null;
  warnings?: string[] | null;
}

export interface WorkflowSummary {
  queuedAt?: string | null;
  startedAt?: string | null;
  updatedAt?: string | null;
  completedSteps?: number;
  failedSteps?: number;
  continuedSteps?: number;
  skippedSteps?: number;
  waitingApprovalSteps?: number;
  totalSteps?: number;
  currentFrontier?: string[];
  runId?: string | null;
}

export interface WorkflowPendingApproval {
  name: string;
  stepName: string;
  requestedAt?: string | null;
  runId?: string | null;
  action?: string | null;
  reason?: string;
}

export interface WorkflowNextAction {
  action: string;
  reason: string;
  failedSteps?: string[];
  rejectedReviews?: string[];
  verifyFailures?: string[];
}

export interface WorkflowInfo {
  name: string;
  namespace: string;
  description: string;
  input: string;
  context_ref?: string | null;
  message_bus: string;
  steps: WorkflowStep[];
  phase: string;
  current_step: string;
  observed_generation?: number | null;
  summary?: WorkflowSummary | null;
  artifact_ref?: Record<string, unknown> | null;
  journal_ref?: Record<string, unknown> | null;
  pending_approval?: WorkflowPendingApproval | null;
  run_id?: string | null;
  step_states?: Record<string, WorkflowStepState> | null;
  worker_job?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface DeleteResponse {
  status: string;
  kind: string;
  name: string;
  namespace: string;
}

export interface UiToolCall {
  tool: string;
  status: "completed" | "error" | "running" | "unknown";
  input?: unknown;
  output?: string;
}

export interface UiPatch {
  files: string[];
}

export interface UiMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  reasoning?: string;
  status?: "streaming" | "complete" | "error";
  /** Model that produced this message (assistant only) */
  modelName?: string;
  /** ISO timestamp when the message was created */
  timestamp?: string;
  /** Attached files or pasted images */
  attachments?: Array<{ name: string; type: string; dataUrl: string; isImage: boolean }>;
  /** Tool-call fields (populated when role === "tool") */
  toolName?: string;
  toolNode?: string;
  toolDetail?: Record<string, unknown>;
  /** Structured parts from OpenCode */
  toolCalls?: UiToolCall[];
  patches?: UiPatch[];
  artifacts?: Array<Record<string, unknown>>;
  a2a?: A2AInvocationMetadata | null;
  subagents?: SubagentInvocationMetadata | null;
  metadata?: Record<string, unknown> | null;
}

export interface UiActivity {
  id: string;
  event: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface UiTodo {
  content: string;
  status: "pending" | "in_progress" | "completed" | "cancelled";
  priority: "high" | "medium" | "low";
}

/* ── Question / HITL types ── */

export interface QuestionOption {
  label: string;
  description: string;
}

export interface QuestionInfo {
  question: string;
  header?: string;
  options: QuestionOption[];
  multiple?: boolean;
  custom?: boolean;
}

export interface QuestionRequest {
  id: string;
  sessionID?: string;
  questions: QuestionInfo[];
  tool?: { messageID: string; callID: string };
}

export interface InvocationSummary {
  threadId: string;
  status: string;
  policyName?: string | null;
  toolName?: string | null;
  toolResult?: unknown;
  sandboxSession?: Record<string, unknown> | null;
  approvalName?: string | null;
  retryAfterSeconds?: number | null;
  a2a?: A2AInvocationMetadata | null;
  subagents?: SubagentInvocationMetadata | null;
  warnings: string[];
  artifacts?: Array<Record<string, unknown>> | null;
  toolCalls?: Array<Record<string, unknown>> | null;
  continuity?: {
    createdNewSession?: boolean;
    sessionRecovered?: boolean;
    hasPriorMemory?: boolean;
    memoryApplied?: boolean;
    memoryEntryCount?: number | null;
    handoffResumed?: boolean;
    remoteSessionId?: string | null;
  } | null;
  todos?: UiTodo[] | null;
  metadata?: Record<string, unknown> | null;
}

export interface StreamEvent {
  event: string;
  payload: Record<string, unknown>;
}

/* ── Execution Trace types ── */

export type TraceEventType =
  | "EXECUTION_STARTED"
  | "EXECUTION_COMPLETED"
  | "EXECUTION_FAILED"
  | "EXECUTION_CANCELLED"
  | "STEP_STARTED"
  | "STEP_COMPLETED"
  | "STEP_FAILED"
  | "STEP_SKIPPED"
  | "LLM_CALL_STARTED"
  | "LLM_CALL_COMPLETED"
  | "LLM_CALL_FAILED"
  | "LLM_STREAM_CHUNK"
  | "TOOL_CALL_STARTED"
  | "TOOL_CALL_COMPLETED"
  | "TOOL_CALL_FAILED"
  | "DECISION"
  | "BRANCH_TAKEN"
  | "STATE_SNAPSHOT"
  | "VARIABLE_SET"
  | "ERROR"
  | "WARNING"
  | "PROGRESS"
  | "TODO_CREATED"
  | "TODO_COMPLETED"
  | "ARTIFACT_CREATED"
  | "CUSTOM";

export interface TraceEvent {
  id: string;
  execution_id: string;
  event_type: TraceEventType;
  timestamp: string;
  step_id?: string | null;
  payload: Record<string, unknown>;
}

export interface LLMCallRecord {
  id: string;
  step_id?: string | null;
  execution_id: string;
  model: string;
  provider?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  reasoning_tokens?: number | null;
  total_tokens: number;
  cost_usd?: number | null;
  estimated_cost_usd?: number | null;
  latency_ms: number;
  prompt_preview?: string | null;
  response_preview?: string | null;
  created_at: string;
  token_source?: string | null;
}

export interface ToolCallRecord {
  id: string;
  step_id?: string | null;
  execution_id: string;
  tool_name: string;
  tool_args?: Record<string, unknown> | null;
  tool_result?: unknown | null;
  args_preview?: string | null;
  result_preview?: string | null;
  error_message?: string | null;
  duration_ms?: number | null;
  latency_ms: number;
  status: string;
  started_at?: string | null;
  created_at: string;
}

export interface StepTrace {
  id: string;
  execution_id: string;
  name: string;
  step_index?: number | null;
  step_type?: string | null;
  parent_step_id?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  latency_ms?: number | null;
  error?: string | null;
  tokens_used?: number | null;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  reasoning_tokens?: number | null;
  cost_usd?: number | null;
  llm_call_count?: number | null;
  tool_call_count?: number | null;
  llm_calls: LLMCallRecord[];
  tool_calls: ToolCallRecord[];
  input_preview?: string | null;
  output_preview?: string | null;
}

export interface ExecutionTrace {
  id: string;
  workflow_name: string;
  namespace: string;
  agent_name?: string | null;
  run_id?: string | null;
  triggered_by?: string | null;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  created_at?: string | null;
  duration_ms?: number | null;
  error_message?: string | null;
  trace_file_path?: string | null;
  input_preview?: string | null;
  output_preview?: string | null;
  step_count: number;
  completed_steps?: number | null;
  failed_steps?: number | null;
  llm_call_count: number;
  tool_call_count: number;
  total_tokens: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  reasoning_tokens?: number | null;
  total_cost_usd?: number | null;
  steps: StepTrace[];
  llm_calls: LLMCallRecord[];
  tool_calls: ToolCallRecord[];
  events: TraceEvent[];
}

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
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  reasoning_tokens?: number | null;
  total_cost_usd?: number | null;
  triggered_by?: string | null;
}

export interface ExecutionListResponse {
  items: ExecutionListItem[];
  total: number;
  limit: number;
  offset: number;
}

/* ── Webhook & Trigger types ── */

export type WebhookProvider = "generic" | "github" | "slack" | "stripe" | "pagerduty" | "grafana";

export interface WebhookReceiverInfo {
  id: number;
  namespace: string;
  name: string;
  secret_ref: string;
  ip_allowlist: string[];
  rate_limit: number;
  max_payload_bytes: number;
  enabled: boolean;
  provider: WebhookProvider;
  api_key_enabled: boolean;
  failure_count: number;
  last_failure: string | null;
  active_keys: number;
  created_at: string;
  updated_at: string;
}

export interface WebhookInvocationInfo {
  id: number;
  invocation_id: string;
  webhook_name: string;
  namespace: string;
  source_ip: string;
  received_at: string;
  signature_verified: boolean;
  status: string;
  matched_triggers: number;
  provider?: string;
  event_type?: string;
}

export interface WorkflowTriggerInfo {
  id: number;
  namespace: string;
  name: string;
  source_kind: string;
  source_ref: string;
  event_filter: Record<string, unknown>;
  workflow_ref: Record<string, string>;
  agent_ref: Record<string, string>;
  target_kind: string;
  payload_mapping: Record<string, string>;
  max_retries: number;
  backoff_seconds: number;
  enabled: boolean;
  execution_count: number;
  dead_letter_count: number;
  last_triggered: string | null;
  notifications: {
    on_success?: string[];
    on_failure?: string[];
  };
}

export interface TriggerExecutionInfo {
  id: number;
  trigger_name: string;
  namespace: string;
  webhook_name: string;
  executed_at: string;
  status: string;
  workflow_run_id: string | null;
  error_message: string | null;
  attempt_count: number;
  target_kind?: string;
  agent_name?: string;
  agent_namespace?: string;
}

/* ── Live Agent Activity Stream types ── */

export type AgentActivityType = "reasoning" | "operation" | "a2a" | "file" | "warning" | "error" | "success" | "system";

export interface AgentActivity {
  id: string;
  timestamp: string;
  type: AgentActivityType;
  severity?: string;
  event: string;
  agentRef: string;
  step: string;
  runId: string;
  message: string;
  summary?: string;
  tool?: string | null;
  durationMs?: number | null;
  details: Record<string, unknown>;
  source: string;
}

export interface ActivityStreamState {
  activities: AgentActivity[];
  isConnected: boolean;
  isActive: boolean;
  phase: string;
  error: string | null;
}

/* ── Incident Management types ── */

export interface IncidentInfo {
  id: number;
  namespace: string;
  name: string;
  title: string;
  description: string;
  severity: "critical" | "warning" | "info";
  source: "alertmanager" | "manual" | "k8s-event" | "webhook";
  status: "firing" | "acknowledged" | "diagnosing" | "remediated" | "resolved" | "closed" | "escalated";
  labels: Record<string, string>;
  annotations: Record<string, string>;
  assigned_agent: string | null;
  escalation_timeout_minutes: number;
  escalated: boolean;
  auto_acknowledge: boolean;
  acknowledged_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  escalated_at: string | null;
  alertmanager_fingerprint: string | null;
  workflow_ref_name: string | null;
  workflow_ref_namespace: string | null;
  workflow_run_id: string | null;
  timeline: Array<{ timestamp: string; event: string; message: string }>;
  created_at: string;
  updated_at: string;
}

export interface IncidentTimelineEvent {
  timestamp: string;
  event: string;
  message: string;
}
