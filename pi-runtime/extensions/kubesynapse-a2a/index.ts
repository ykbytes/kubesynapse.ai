/**
 * kubesynapse A2A Extension for pi
 *
 * Enables pi agents to invoke other kubesynapse agents via A2A (Agent-to-Agent)
 * communication. Reads A2A configuration from environment variables set by the
 * kubesynapse operator.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "typebox";

// --- Constants from environment ---
const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL || "http://kubesynapse-api-gateway.kubesynapse.svc.cluster.local:8000";
const A2A_TOKEN =
  process.env.A2A_SHARED_TOKEN || process.env.API_GATEWAY_SHARED_TOKEN || "";
const CURRENT_AGENT = process.env.KUBESYNAPSE_AGENT_NAME || "unknown";
const CURRENT_NAMESPACE = process.env.KUBESYNAPSE_NAMESPACE || "default";
// Comma-separated list of agent:namespace pairs this agent can call
const ALLOWED_CALLERS = (
  process.env.A2A_ALLOWED_CALLERS || ""
).split(",").filter(Boolean);

// --- Types ---
interface A2aSendResponse {
  thread_id: string;
  response?: string;
  status: "completed" | "pending" | "error";
  error?: string;
}

// --- Tool Definition ---
export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "KUBESYNAPSE_a2a_send",
    label: "Send A2A Message",
    description: `Send a message to another kubesynapse agent via A2A communication. 
Use this when you need another agent to perform a task or provide information.
Available peer agents are configured by the platform admin.`,
    promptSnippet:
      "Send a message to another kubesynapse agent via A2A and get their response",
    promptGuidelines: [
      "Use KUBESYNAPSE_a2a_send when you need another agent to help with a task or provide information.",
      "Always specify a clear, self-contained message — the target agent cannot see your conversation history.",
      "If the response is brief, include it directly in your answer. If extensive, summarize it.",
    ],
    parameters: Type.Object({
      agent_name: Type.String({
        description: "Name of the target agent to send the message to",
      }),
      message: Type.String({
        description: "The message text to send. Be clear and self-contained.",
      }),
      namespace: Type.Optional(
        Type.String({
          description: "Namespace of the target agent (defaults to current namespace)",
        })
      ),
    }),
    async execute(toolCallId, params, signal) {
      const targetAgent = params.agent_name;
      const targetNamespace = params.namespace || CURRENT_NAMESPACE;
      const message = params.message;

      // Permission check
      if (!ALLOWED_CALLERS.includes(targetAgent) && ALLOWED_CALLERS.length > 0) {
        return {
          content: [
            {
              type: "text",
              text: `A2A Error: Agent "${CURRENT_AGENT}" is not authorized to call agent "${targetAgent}". Allowed agents: ${ALLOWED_CALLERS.join(", ")}`,
            },
          ],
          details: { error: "permission_denied" },
        };
      }

      if (targetAgent === CURRENT_AGENT && targetNamespace === CURRENT_NAMESPACE) {
        return {
          content: [
            {
              type: "text",
              text: `A2A Error: Cannot send a message to yourself (${CURRENT_AGENT}). Use a different target agent.`,
            },
          ],
          details: { error: "self_reference" },
        };
      }

      const url = `${API_GATEWAY_URL}/api/v1/a2a/send`;
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (A2A_TOKEN) {
        headers["Authorization"] = `Bearer ${A2A_TOKEN}`;
      }

      const body = JSON.stringify({
        target_agent: targetAgent,
        target_namespace: targetNamespace,
        source_agent: CURRENT_AGENT,
        source_namespace: CURRENT_NAMESPACE,
        message: message,
        wait_for_reply: true,
      });

      try {
        const response = await fetch(url, {
          method: "POST",
          headers,
          body,
          signal,
        });

        if (!response.ok) {
          const errorText = await response.text().catch(() => "Unknown error");
          return {
            content: [
              {
                type: "text",
                text: `A2A Error: Gateway returned ${response.status} — ${errorText}`,
              },
            ],
            details: {
              error: `http_${response.status}`,
              status: response.status,
              errorText,
            },
          };
        }

        const data: A2aSendResponse = await response.json();

        if (data.status === "error") {
          return {
            content: [
              {
                type: "text",
                text: `A2A Error from ${targetAgent}: ${data.error || "Unknown error"}`,
              },
            ],
            details: { error: data.error },
          };
        }

        return {
          content: [
            {
              type: "text",
              text: data.response || `Message sent to ${targetAgent} (no immediate response)`,
            },
          ],
          details: {
            thread_id: data.thread_id,
            status: data.status,
            target_agent: targetAgent,
          },
        };
      } catch (err: unknown) {
        const errorMsg = err instanceof Error ? err.message : String(err);
        return {
          content: [
            {
              type: "text",
              text: `A2A Error: Failed to reach ${targetAgent} — ${errorMsg}`,
            },
          ],
          details: { error: errorMsg },
        };
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    const a2aInfo = ALLOWED_CALLERS.length > 0
      ? `A2A ready — can communicate with: ${ALLOWED_CALLERS.join(", ")}`
      : "A2A enabled but no peer agents configured";

    ctx.ui.notify(a2aInfo, "info");
  });
}
