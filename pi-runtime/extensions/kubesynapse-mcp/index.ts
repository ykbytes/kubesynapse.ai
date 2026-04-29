/**
 * kubesynapse MCP Extension for pi
 *
 * Integrates kubesynapse-managed MCP (Model Context Protocol) servers as pi tools.
 * Reads MCP connections from the same OPENCODE_MCP_CONNECTIONS_JSON env var
 * used by the OpenCode runtime, maintaining compatibility.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type, type Static } from "typebox";

// --- Types ---
interface McpConnection {
  connectionId?: string;
  name?: string;
  slug?: string;
  runtime?: {
    kind: "sidecar" | "remote" | "hub";
    configKey?: string;
    url?: string;
    sidecar?: {
      name?: string;
      port?: number;
      endpointPath?: string;
    };
    headers?: Array<{ name: string; value: string }>;
  };
  attachable?: boolean;
  validation?: {
    status: string;
    message?: string;
  };
}

interface McpTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

interface McpCallResult {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
}

// --- MCP Client ---
class McpClient {
  private baseUrl: string;
  private headers: Record<string, string>;

  constructor(baseUrl: string, headers: Record<string, string> = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.headers = { "Content-Type": "application/json", ...headers };
  }

  async listTools(signal?: AbortSignal): Promise<McpTool[]> {
    const response = await fetch(`${this.baseUrl}/tools/list`, {
      method: "GET",
      headers: this.headers,
      signal,
    });
    if (!response.ok) {
      throw new Error(`MCP tools/list failed: ${response.status}`);
    }
    const data = await response.json();
    return (data.tools || data || []).map((t: Record<string, unknown>) => ({
      name: String(t.name || ""),
      description: String(t.description || ""),
      inputSchema: (t.inputSchema || t.input_schema || {}) as Record<string, unknown>,
    }));
  }

  async callTool(
    toolName: string,
    args: Record<string, unknown>,
    signal?: AbortSignal
  ): Promise<McpCallResult> {
    const response = await fetch(`${this.baseUrl}/tools/call`, {
      method: "POST",
      headers: this.headers,
      body: JSON.stringify({
        name: toolName,
        arguments: args,
      }),
      signal,
    });
    if (!response.ok) {
      throw new Error(`MCP tools/call failed: ${response.status}`);
    }
    return response.json();
  }
}

// --- Load connections from env ---
function loadMcpConnections(): McpConnection[] {
  try {
    const raw = process.env.OPENCODE_MCP_CONNECTIONS_JSON || "[]";
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function buildMcpUrl(conn: McpConnection): string {
  const runtime = conn.runtime || {};

  if (runtime.kind === "sidecar" && runtime.sidecar) {
    const port = runtime.sidecar.port || 8080;
    const path = runtime.sidecar.endpointPath || "/mcp";
    return `http://127.0.0.1:${port}${path}`;
  }

  if (runtime.url) {
    return runtime.url;
  }

  throw new Error(`No URL configured for MCP connection: ${conn.name || conn.slug}`);
}

function buildMcpHeaders(conn: McpConnection): Record<string, string> {
  const headers: Record<string, string> = {};
  const runtimeHeaders = conn.runtime?.headers || [];

  for (const h of runtimeHeaders) {
    const name = (h.name || "").trim();
    const value = (h.value || "").trim();
    if (name && value) {
      headers[name] = value;
    }
  }

  return headers;
}

// --- Extension ---
export default async function (pi: ExtensionAPI) {
  const connections = loadMcpConnections();
  const registeredTools: string[] = [];

  if (connections.length === 0) {
    return;
  }

  for (const conn of connections) {
    try {
      const url = buildMcpUrl(conn);
      const headers = buildMcpHeaders(conn);
      const client = new McpClient(url, headers);
      const tools = await client.listTools();

      for (const tool of tools) {
        const toolName = `mcp_${conn.slug || conn.name || "unknown"}_${tool.name}`
          .toLowerCase()
          .replace(/[^a-z0-9_]/g, "_")
          .replace(/_+/g, "_")
          .slice(0, 64);

        pi.registerTool({
          name: toolName,
          label: `MCP: ${conn.name || tool.name}`,
          description: `[MCP] ${tool.description || toolName}. Server: ${conn.name || conn.slug}`,
          promptSnippet: `MCP tool from "${conn.name || conn.slug}" server`,
          promptGuidelines: [
            `Use ${toolName} when relevant to interact with the "${conn.name || conn.slug}" MCP server.`,
          ],
          parameters: Type.Object({
            arguments: Type.Record(Type.String(), Type.Unknown(), {
              description: "Tool arguments as a JSON object",
            }),
          }),
          async execute(_toolCallId, params, signal) {
            const result = await client.callTool(tool.name, params.arguments as Record<string, unknown>, signal);

            if (result.isError) {
              return {
                content: result.content,
                details: { isError: true },
              };
            }

            return {
              content: result.content || [{ type: "text", text: "Tool executed (no output)" }],
              details: { toolName: tool.name, serverName: conn.name },
            };
          },
        });

        registeredTools.push(toolName);
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      console.error(`[kubesynapse-mcp] Failed to load MCP server "${conn.name || conn.slug}": ${errorMsg}`);
    }
  }

  pi.on("session_start", async (_event, ctx) => {
    if (registeredTools.length > 0) {
      ctx.ui.notify(
        `MCP: ${registeredTools.length} tools from ${connections.length} server(s) loaded`,
        "info"
      );
    }
  });
};
