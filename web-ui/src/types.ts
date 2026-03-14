export type RuntimeKind = "langgraph" | "goose" | "codex";

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
  files: Record<string, string>;
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
  goose_builtin_extensions: string[];
  goose_stdio_extensions: string[];
  goose_streamable_http_extensions: string[];
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

export type WorkspaceView = "agents" | "workflows" | "evals" | "catalog";

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
}

export interface SkillsCatalogResponse {
  skills: CatalogSkill[];
  total: number;
}

export interface McpToolsResponse {
  categories: McpToolCategory[];
}

export interface PolicyInfo {
  name: string;
  namespace: string;
}

export interface AgentDetail extends AgentInfo {
  system_prompt: string;
  policy_ref?: string | null;
  storage_size?: string | null;
  runtime_kind: RuntimeKind;
  enable_gvisor: boolean;
  mcp_servers: string[];
  mcp_sidecars: Array<Record<string, unknown>>;
  a2a_config: AgentA2AConfig;
  skills: AgentSkillsConfig;
  skill_summaries: AgentSkillSummary[];
  goose_config_files: Record<string, unknown>;
  created_at?: string | null;
}

export interface CreateAgentPayload {
  name: string;
  model: string;
  system_prompt?: string;
  policy_ref?: string;
  storage_size?: string;
  runtime_kind?: RuntimeKind;
  enable_gvisor?: boolean;
  mcp_servers?: string[];
  mcp_sidecars?: Array<Record<string, unknown>>;
  a2a_config?: AgentA2AConfig;
  skills?: AgentSkillsConfig;
  goose_config_files?: Record<string, unknown>;
}

export interface UpdateAgentPayload {
  model: string;
  system_prompt?: string;
  policy_ref?: string;
  storage_size?: string;
  runtime_kind?: RuntimeKind;
  enable_gvisor?: boolean;
  mcp_servers?: string[];
  mcp_sidecars?: Array<Record<string, unknown>>;
  a2a_config?: AgentA2AConfig;
  skills?: AgentSkillsConfig;
  goose_config_files?: Record<string, unknown>;
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
}

export interface InvokePayload {
  prompt: string;
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
}

export interface AgentLogsResponse {
  agent_name: string;
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
}

export interface WorkflowPayload {
  name: string;
  description?: string;
  input?: string;
  message_bus?: string;
  steps: WorkflowStep[];
}

export interface WorkflowUpdatePayload {
  description?: string;
  input?: string;
  message_bus?: string;
  steps: WorkflowStep[];
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
  step: string;
  reason?: string;
}

export interface WorkflowInfo {
  name: string;
  namespace: string;
  description: string;
  input: string;
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

export interface EvalTestCase {
  input: string;
  expected_output: string;
  metrics: string[];
}

export interface EvalPayload {
  name: string;
  agent_ref: string;
  schedule?: string;
  test_suite: EvalTestCase[];
  failure_threshold?: Record<string, unknown>;
}

export interface EvalUpdatePayload {
  agent_ref: string;
  schedule?: string;
  test_suite: EvalTestCase[];
  failure_threshold?: Record<string, unknown>;
}

export interface EvalInfo {
  name: string;
  namespace: string;
  agent_ref: string;
  schedule?: string | null;
  test_suite: EvalTestCase[];
  failure_threshold: Record<string, unknown>;
  phase: string;
  passed?: boolean | null;
  last_run?: string | null;
  observed_generation?: number | null;
  summary?: Record<string, unknown> | null;
  artifact_ref?: Record<string, unknown> | null;
  worker_job?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface DeleteResponse {
  status: string;
  kind: string;
  name: string;
  namespace: string;
}

export interface UiMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  status?: "streaming" | "complete" | "error";
  /** Tool-call fields (populated when role === "tool") */
  toolName?: string;
  toolNode?: string;
  toolDetail?: Record<string, unknown>;
}

export interface UiActivity {
  id: string;
  event: string;
  payload: Record<string, unknown>;
  timestamp: string;
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
}

export interface StreamEvent {
  event: string;
  payload: Record<string, unknown>;
}
