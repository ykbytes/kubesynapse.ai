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
  EvalUpdatePayload,
  GatewayHealth,
  InvokePayload,
  InvokeResponse,
  PolicyInfo,
  StreamEvent,
  UpdateAgentPayload,
  WorkflowInfo,
  WorkflowPayload,
  WorkflowUpdatePayload,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() ?? "";

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

async function parseJsonResponse<T>(response: Response): Promise<T> {
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
  return (await response.json()) as T;
}

export async function fetchGatewayHealth(): Promise<GatewayHealth> {
  const response = await fetch(buildUrl("/api/health"));
  return parseJsonResponse<GatewayHealth>(response);
}

export async function listAgents(token: string, namespace: string): Promise<AgentInfo[]> {
  const response = await fetch(buildUrl("/api/agents", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<AgentInfo[]>(response);
}

export async function listPolicies(token: string, namespace: string): Promise<PolicyInfo[]> {
  const response = await fetch(buildUrl("/api/policies", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<PolicyInfo[]>(response);
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
  return parseJsonResponse<AgentDetail>(response);
}

export async function fetchAgent(token: string, namespace: string, agentName: string): Promise<AgentDetail> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}`, namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<AgentDetail>(response);
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
  return parseJsonResponse<AgentDetail>(response);
}

export async function deleteAgent(token: string, namespace: string, agentName: string): Promise<DeleteResponse> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}`, namespace), {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  return parseJsonResponse<DeleteResponse>(response);
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
  return parseJsonResponse<InvokeResponse>(response);
}

export async function fetchAgentLogs(
  token: string,
  namespace: string,
  agentName: string,
): Promise<AgentLogsResponse> {
  const response = await fetch(buildUrl(`/api/agents/${agentName}/logs`, namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<AgentLogsResponse>(response);
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
  return parseJsonResponse<ApprovalInfo>(response);
}

export async function listWorkflows(token: string, namespace: string): Promise<WorkflowInfo[]> {
  const response = await fetch(buildUrl("/api/workflows", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<WorkflowInfo[]>(response);
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
  return parseJsonResponse<WorkflowInfo>(response);
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
  return parseJsonResponse<WorkflowInfo>(response);
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
  return parseJsonResponse<DeleteResponse>(response);
}

export async function listEvals(token: string, namespace: string): Promise<EvalInfo[]> {
  const response = await fetch(buildUrl("/api/evals", namespace), {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<EvalInfo[]>(response);
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
  return parseJsonResponse<EvalInfo>(response);
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
  return parseJsonResponse<EvalInfo>(response);
}

export async function deleteEval(token: string, namespace: string, evalName: string): Promise<DeleteResponse> {
  const response = await fetch(buildUrl(`/api/evals/${evalName}`, namespace), {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  return parseJsonResponse<DeleteResponse>(response);
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
      const payload = message.data ? (JSON.parse(message.data) as Record<string, unknown>) : {};
      const event = message.event || "message";
      options.onEvent({ event, payload });
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
