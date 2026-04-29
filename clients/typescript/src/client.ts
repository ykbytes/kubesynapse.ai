/**
 * kubesynapse API client — idiomatic TypeScript SDK.
 *
 * Usage:
 *   const client = new KubeSynapseClient("http://localhost:8080");
 *   const health = await client.health();
 *   const agents = await client.listAgents();
 */

import type {
  Agent,
  AgentCreate,
  AgentList,
  AgentPolicy,
  AgentWorkflow,
  AgentWorkflowCreate,
  HealthStatus,
} from "./models.js";

// ── Error ─────────────────────────────────────────────────────────

export class KubeSynapseError extends Error {
  public statusCode: number;
  public detail: Record<string, unknown> | undefined;

  constructor(statusCode: number, message: string, detail?: Record<string, unknown>) {
    super(`[${statusCode}] ${message}`);
    this.name = "KubeSynapseError";
    this.statusCode = statusCode;
    this.detail = detail;
  }

  static async fromResponse(response: Response): Promise<KubeSynapseError> {
    let message = response.statusText;
    let detail: Record<string, unknown> | undefined;
    try {
      const body = await response.json();
      message = body.message || message;
      detail = body.detail;
    } catch {
      // Use default message
    }
    return new KubeSynapseError(response.status, message, detail);
  }
}

// ── Client ────────────────────────────────────────────────────────

export class KubeSynapseClient {
  private baseUrl: string;
  private token: string | undefined;
  private timeout: number;

  constructor(
    baseUrl: string = "http://localhost:8080",
    options?: { token?: string; timeout?: number },
  ) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = options?.token;
    this.timeout = options?.timeout ?? 30_000;
  }

  // ── Internal ────────────────────────────────────────────────────

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      Accept: "application/json",
      "Content-Type": "application/json",
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | undefined>,
  ): Promise<T> {
    const url = new URL(`${this.baseUrl}${path}`);
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined) url.searchParams.set(k, String(v));
      });
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(url.toString(), {
        method,
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      if (!response.ok) {
        throw await KubeSynapseError.fromResponse(response);
      }

      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Health ──────────────────────────────────────────────────────

  async health(): Promise<HealthStatus> {
    return this.request<HealthStatus>("GET", "/api/v1/health");
  }

  async ready(): Promise<void> {
    await this.request("GET", "/api/v1/ready");
  }

  async healthDb(): Promise<{ status: string }> {
    return this.request("GET", "/api/v1/health/db");
  }

  // ── Agents ──────────────────────────────────────────────────────

  async createAgent(agent: AgentCreate): Promise<Agent> {
    return this.request<Agent>("POST", "/api/v1/agents", agent);
  }

  async getAgent(name: string, namespace: string = "kubesynapse"): Promise<Agent> {
    return this.request<Agent>("GET", `/api/v1/agents/${namespace}/${name}`);
  }

  async listAgents(
    namespace: string = "kubesynapse",
    page: number = 1,
    pageSize: number = 20,
  ): Promise<AgentList> {
    return this.request<AgentList>("GET", "/api/v1/agents", undefined, {
      namespace,
      page,
      page_size: pageSize,
    });
  }

  async deleteAgent(name: string, namespace: string = "kubesynapse"): Promise<void> {
    await this.request("DELETE", `/api/v1/agents/${namespace}/${name}`);
  }

  // ── Workflows ───────────────────────────────────────────────────

  async createWorkflow(workflow: AgentWorkflowCreate): Promise<AgentWorkflow> {
    return this.request<AgentWorkflow>("POST", "/api/v1/workflows", workflow);
  }

  async getWorkflow(
    name: string,
    namespace: string = "kubesynapse",
  ): Promise<AgentWorkflow> {
    return this.request<AgentWorkflow>("GET", `/api/v1/workflows/${namespace}/${name}`);
  }

  async listWorkflows(
    namespace: string = "kubesynapse",
    status?: string,
    page: number = 1,
    pageSize: number = 20,
  ): Promise<AgentWorkflow[]> {
    return this.request<AgentWorkflow[]>("GET", "/api/v1/workflows", undefined, {
      namespace,
      status,
      page,
      page_size: pageSize,
    });
  }

  async cancelWorkflow(
    name: string,
    namespace: string = "kubesynapse",
  ): Promise<AgentWorkflow> {
    return this.request<AgentWorkflow>(
      "POST",
      `/api/v1/workflows/${namespace}/${name}/cancel`,
    );
  }

  // ── Policies ────────────────────────────────────────────────────

  async getPolicy(name: string, namespace: string = "kubesynapse"): Promise<AgentPolicy> {
    return this.request<AgentPolicy>("GET", `/api/v1/policies/${namespace}/${name}`);
  }

  async listPolicies(namespace: string = "kubesynapse"): Promise<AgentPolicy[]> {
    return this.request<AgentPolicy[]>("GET", "/api/v1/policies", undefined, { namespace });
  }

  // ── Observability ───────────────────────────────────────────────

  async listTraces(
    workflowName?: string,
    limit: number = 50,
  ): Promise<Record<string, unknown>[]> {
    return this.request("GET", "/api/v1/traces", undefined, {
      workflow_name: workflowName,
      limit,
    });
  }

  async getTrace(traceId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/api/v1/traces/${traceId}`);
  }
}
