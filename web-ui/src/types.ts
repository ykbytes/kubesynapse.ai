export type RuntimeKind = "langgraph" | "goose";

export interface AgentInfo {
  name: string;
  model: string;
  namespace: string;
  status: string;
  runtime_kind?: RuntimeKind;
}

export type WorkspaceView = "agents" | "workflows" | "evals";

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
}

export interface UpdateAgentPayload {
  model: string;
  system_prompt?: string;
  policy_ref?: string;
  storage_size?: string;
  runtime_kind?: RuntimeKind;
  enable_gvisor?: boolean;
}

export interface GatewayHealth {
  status: string;
  gateway: string;
  auth_mode: string;
  nats_url: string;
  qdrant_url: string;
}

export interface InvokePayload {
  prompt: string;
  thread_id?: string;
  model?: string;
  require_approval?: boolean;
  approval_action?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  mcp_server?: string;
}

export interface InvokeResponse {
  agent_name: string;
  response: string;
  thread_id: string;
  model: string;
  policy_name?: string | null;
  tool_name?: string | null;
  tool_result?: Record<string, unknown> | null;
  sandbox_session?: Record<string, unknown> | null;
  status: string;
  approval_name?: string | null;
  retry_after_seconds?: number | null;
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
  summary?: Record<string, unknown> | null;
  artifact_ref?: Record<string, unknown> | null;
  pending_approval?: Record<string, unknown> | null;
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
  role: "user" | "assistant" | "system";
  content: string;
  status?: "streaming" | "complete" | "error";
}

export interface UiActivity {
  id: string;
  event: string;
  payload: Record<string, unknown>;
}

export interface InvocationSummary {
  threadId: string;
  status: string;
  policyName?: string | null;
  toolName?: string | null;
  toolResult?: Record<string, unknown> | null;
  sandboxSession?: Record<string, unknown> | null;
  approvalName?: string | null;
  retryAfterSeconds?: number | null;
  warnings: string[];
}

export interface StreamEvent {
  event: string;
  payload: Record<string, unknown>;
}
