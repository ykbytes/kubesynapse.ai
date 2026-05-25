/**
 * TypeScript types matching the kubesynapse API v1 schema.
 */

export type AgentStatus =
  | "pending"
  | "provisioning"
  | "running"
  | "degraded"
  | "stopped"
  | "failed";

export type AgentWorkflowStatus =
  | "pending"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  version: string;
  uptime_seconds: number;
  database: string;
  timestamp: string;
}

export interface AgentCreate {
  name: string;
  namespace?: string;
  policy_ref?: string;
  replicas?: number;
  resources?: {
    requests: { cpu: string; memory: string };
    limits: { cpu: string; memory: string };
  };
  config?: {
    contextWindow?: number;
    sessionTimeout?: number;
    [key: string]: unknown;
  };
}

export interface Agent {
  name: string;
  namespace: string;
  status: AgentStatus;
  policy_ref: string;
  replicas: number;
  ready_replicas: number;
  created_at: string;
  updated_at: string | null;
  spec: Record<string, unknown>;
}

export interface AgentList {
  items: Agent[];
  total: number;
  page: number;
  page_size: number;
}

export interface AgentPolicy {
  name: string;
  max_tokens_per_request: number;
  max_daily_cost: number;
  allowed_tools: string[];
  require_approval: string[];
  llm_model: string;
  system_prompt: string;
}

export interface WorkflowStep {
  name: string;
  action: string;
  agent?: string;
  params?: Record<string, unknown>;
  depends_on?: string[];
  timeout?: number;
  require_approval?: boolean;
}

export interface AgentWorkflowCreate {
  name: string;
  namespace?: string;
  agent: string;
  steps: WorkflowStep[];
  retry_policy?: {
    max_retries?: number;
    backoff?: "fixed" | "exponential";
  };
}

export interface StepResult {
  name: string;
  status: string;
  output: string | null;
  error: string | null;
  duration_ms: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentWorkflow {
  name: string;
  namespace: string;
  agent: string;
  status: AgentWorkflowStatus;
  steps: StepResult[];
  total_steps: number;
  completed_steps: number;
  created_at: string;
  updated_at: string | null;
}

export interface ExecutionListResponse {
  items: Record<string, unknown>[];
  limit: number;
  offset: number;
}

export interface ExecutionDetailResponse {
  id: string;
  namespace: string;
  workflow_name: string;
  agent_name: string;
  run_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  total_steps: number;
  completed_steps: number;
  failed_steps: number;
  total_llm_calls: number;
  total_tool_calls: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number | null;
  triggered_by: string | null;
  error_message: string | null;
  trace_file_path: string | null;
  steps: Record<string, unknown>[];
  llm_calls: Record<string, unknown>[];
  tool_calls: Record<string, unknown>[];
  events: Record<string, unknown>[];
}

export interface APIError {
  error: string;
  message: string;
  status_code: number;
  detail?: Record<string, unknown>;
}
