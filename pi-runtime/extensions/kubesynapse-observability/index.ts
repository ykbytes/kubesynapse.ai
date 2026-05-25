/**
 * kubesynapse Observability Extension for pi
 *
 * Emits structured JSON logs for agent lifecycle events, tool execution,
 * token usage, and errors. Designed to be consumed by Fluentd/Fluent Bit
 * and forwarded to the kubesynapse observability stack (Prometheus, Grafana).
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const AGENT_NAME = process.env.KUBESYNAPSE_AGENT_NAME || "unknown";
const NAMESPACE = process.env.KUBESYNAPSE_NAMESPACE || "default";
const WORKFLOW_RUN_ID = process.env.WORKFLOW_RUN_ID || process.env.EVAL_RUN_ID || "";
const WORKER_KIND = process.env.WORKER_KIND || "";
const TARGET_NAME = process.env.TARGET_NAME || "";

interface StructuredLog {
  ts: string;
  agent: string;
  namespace: string;
  event: string;
  runId?: string;
  workerKind?: string;
  targetName?: string;
  [key: string]: unknown;
}

function log(data: Record<string, unknown>): void {
  const entry: StructuredLog = {
    ts: new Date().toISOString(),
    agent: AGENT_NAME,
    namespace: NAMESPACE,
    event: String(data.event || "unknown"),
    runId: WORKFLOW_RUN_ID || undefined,
    workerKind: WORKER_KIND || undefined,
    targetName: TARGET_NAME || undefined,
    ...data,
  };
  // Structured JSON to stdout for log collectors
  process.stdout.write(JSON.stringify(entry) + "\n");
}

export default function (pi: ExtensionAPI) {
  // Agent lifecycle
  pi.on("agent_start", async () => {
    log({ event: "agent_start", timestamp: Date.now() });
  });

  pi.on("agent_end", async (event) => {
    const messages = event.messages || [];
    const totalTokens = messages.reduce((sum: number, m: { role: string; usage?: { totalTokens?: number } }) => {
      if (m.role === "assistant") {
        return sum + (m.usage?.totalTokens || 0);
      }
      return sum;
    }, 0);

    log({
      event: "agent_end",
      messageCount: messages.length,
      totalTokens,
      timestamp: Date.now(),
    });
  });

  // Turn tracking
  pi.on("turn_start", async (event) => {
    log({
      event: "turn_start",
      turnIndex: event.turnIndex,
      timestamp: Date.now(),
    });
  });

  pi.on("turn_end", async (event) => {
    log({
      event: "turn_end",
      turnIndex: event.turnIndex,
      hasMessage: !!event.message,
      toolResultCount: (event.toolResults || []).length,
      timestamp: Date.now(),
    });
  });

  // Tool execution
  pi.on("tool_execution_start", async (event) => {
    log({
      event: "tool_execution_start",
      toolName: event.toolName,
      toolCallId: event.toolCallId,
      timestamp: Date.now(),
    });
  });

  pi.on("tool_execution_end", async (event) => {
    log({
      event: "tool_execution_end",
      toolName: event.toolName,
      toolCallId: event.toolCallId,
      isError: event.isError,
      timestamp: Date.now(),
    });
  });

  // Compaction
  pi.on("compaction_start", async (event) => {
    log({
      event: "compaction_start",
      reason: (event as { reason?: string }).reason || "unknown",
      timestamp: Date.now(),
    });
  });

  pi.on("compaction_end", async (event) => {
    const result = (event as { result?: { tokensBefore?: number } }).result;
    log({
      event: "compaction_end",
      tokensBefore: result?.tokensBefore,
      aborted: (event as { aborted?: boolean }).aborted || false,
      timestamp: Date.now(),
    });
  });

  // Errors
  pi.on("extension_error", async (event) => {
    log({
      event: "extension_error",
      extensionPath: (event as { extensionPath?: string }).extensionPath,
      error: (event as { error?: string }).error,
      timestamp: Date.now(),
    });
  });

  log({ event: "extension_loaded", extensions: ["kubesynapse-observability"] });
}
