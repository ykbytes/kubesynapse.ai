import type { InvocationSummary } from "@/types";

export interface AgentCallSummary {
  id: string;
  kind: "explicit-a2a" | "tool-call";
  agentName: string;
  namespace: string | null;
  status: string;
  transport: string | null;
  threadId: string | null;
  requestId: string | null;
  responsePreview: string | null;
  commandPreview: string | null;
}

const AGENT_INVOKE_ROUTE_PATTERN = /\/api\/agents\/(?:([a-z0-9](?:[-a-z0-9]*[a-z0-9])?)\/)?([a-z0-9](?:[-a-z0-9]*[a-z0-9])?)\/invoke(?:\?[^\s"'`]*namespace=([a-z0-9](?:[-a-z0-9]*[a-z0-9])?))?/i;
const A2A_ROUTE_PATTERN = /\/a2a\/([a-z0-9](?:[-a-z0-9]*[a-z0-9])?)(?:\?[^\s"'`]*namespace=([a-z0-9](?:[-a-z0-9]*[a-z0-9])?))?/i;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? value as Record<string, unknown> : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  if (!record) return null;
  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function truncate(value: string | null | undefined, maxChars = 200): string | null {
  const text = String(value || "").trim();
  if (!text) return null;
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars - 1).trimEnd()}…`;
}

function decodeJsonString(value: string): string {
  try {
    return JSON.parse(`"${value}"`) as string;
  } catch {
    return value.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
}

function readQuotedJsonField(output: string, field: string): string | null {
  const match = output.match(new RegExp(`"${field}"\\s*:\\s*"((?:\\\\.|[^"\\\\])*)"`, "i"));
  return match?.[1] ? truncate(decodeJsonString(match[1])) : null;
}

function readOutputRecord(output: string): Record<string, unknown> | null {
  const trimmed = output.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    return asRecord(parsed);
  } catch {
    return null;
  }
}

function extractTextFromParts(parts: unknown): string | null {
  if (!Array.isArray(parts)) return null;
  const chunks = parts.flatMap((part) => {
    const record = asRecord(part);
    const text = readString(record, "text");
    if (text) return [text];
    if (record && Object.prototype.hasOwnProperty.call(record, "data")) {
      try {
        return [JSON.stringify(record.data)];
      } catch {
        return [String(record.data ?? "")];
      }
    }
    return [];
  }).filter((value) => value.trim());
  if (chunks.length === 0) return null;
  return truncate(chunks.join("\n\n"));
}

function taskStateToStatus(state: string | null): string | null {
  switch ((state || "").trim().toUpperCase()) {
    case "TASK_STATE_COMPLETED":
      return "completed";
    case "TASK_STATE_FAILED":
    case "TASK_STATE_CANCELED":
      return "failed";
    case "TASK_STATE_REJECTED":
      return "blocked";
    case "TASK_STATE_AUTH_REQUIRED":
      return "approval_pending";
    case "TASK_STATE_INPUT_REQUIRED":
      return "blocked";
    case "TASK_STATE_WORKING":
    case "TASK_STATE_SUBMITTED":
      return "partial";
    default:
      return null;
  }
}

function parseA2ATaskOutput(task: Record<string, unknown>): {
  agentName: string | null;
  responsePreview: string | null;
  status: string | null;
} {
  const metadata = asRecord(task.metadata);
  const artifacts = Array.isArray(task.artifacts) ? task.artifacts : [];
  const history = Array.isArray(task.history) ? task.history : [];
  const statusRecord = asRecord(task.status);
  const statusMessage = asRecord(statusRecord?.message);

  let responsePreview: string | null = null;
  for (const artifact of artifacts) {
    responsePreview = extractTextFromParts(asRecord(artifact)?.parts);
    if (responsePreview) break;
  }
  if (!responsePreview) {
    responsePreview = extractTextFromParts(statusMessage?.parts);
  }
  if (!responsePreview) {
    for (const message of [...history].reverse()) {
      const record = asRecord(message);
      const role = readString(record, "role")?.toUpperCase();
      if (role !== "ROLE_AGENT" && role !== "AGENT") continue;
      responsePreview = extractTextFromParts(record?.parts);
      if (responsePreview) break;
    }
  }

  return {
    agentName: readString(metadata, "assistantName"),
    responsePreview,
    status: readString(metadata, "status") || taskStateToStatus(readString(statusRecord, "state")),
  };
}

function parseGatewayOutput(output: string): { agentName: string | null; responsePreview: string | null; status: string | null } {
  const record = readOutputRecord(output);
  if (record) {
    const result = asRecord(record.result);
    const task = asRecord(result?.task);
    if (task) {
      return parseA2ATaskOutput(task);
    }

    const message = asRecord(result?.message);
    if (message) {
      return {
        agentName: null,
        responsePreview: extractTextFromParts(message.parts),
        status: "completed",
      };
    }

    return {
      agentName: readString(record, "agent_name"),
      responsePreview: truncate(readString(record, "response")),
      status: readString(record, "status"),
    };
  }

  return {
    agentName: readQuotedJsonField(output, "agent_name"),
    responsePreview: readQuotedJsonField(output, "response"),
    status: readQuotedJsonField(output, "status"),
  };
}

/* ------------------------------------------------------------------ */
/*  Security: strip tokens / auth headers / secrets from all text     */
/* ------------------------------------------------------------------ */

const AUTH_HEADER_PATTERN = /(-H\s+|--header\s+)(['"]?)Authorization:\s*[^\s'"]*(?:\s+[^\s'"]*)?(\2)/gi;
const BEARER_TOKEN_PATTERN = /Bearer\s+[A-Za-z0-9_.~+/=-]{6,}/gi;
const SECRET_ENV_PATTERN = /\$[{]?[A-Z_]*(?:TOKEN|SECRET|KEY|PASSWORD|CREDENTIALS|AUTH|INTERNAL_URL|GATEWAY|ENDPOINT|API_KEY|BEARER)[A-Z_]*(?:[:}][^"'\s]*)?[}]?/gi;
const INLINE_SECRET_PATTERN = /(?:token|key|secret|password|api[_-]?key|shared[_-]?token)\s*[=:]\s*['"]?[A-Za-z0-9_.~+/=-]{8,}['"]?/gi;
const INTERNAL_URL_PATTERN = /https?:\/\/[\w][\w.-]*\.svc\.cluster\.local(?::\d+)?(?:\/[^\s"'`)\]})]*)?/gi;

export function sanitizeCommand(command: string): string {
  return command
    .replace(AUTH_HEADER_PATTERN, "$1$2Authorization: [REDACTED]$3")
    .replace(BEARER_TOKEN_PATTERN, "Bearer [REDACTED]")
    .replace(SECRET_ENV_PATTERN, "$***")
    .replace(INLINE_SECRET_PATTERN, "[REDACTED]");
}

/** Sanitize any text (inputs AND outputs) — superset of sanitizeCommand. */
export function sanitizeText(text: string): string {
  return sanitizeCommand(text).replace(INTERNAL_URL_PATTERN, "[INTERNAL-URL]");
}

/** Replace full curl + internal URL with a short `POST agents/NAME/invoke` summary. */
function simplifyCommandPreview(command: string, agentName: string, namespace: string | null): string {
  const ns = namespace && namespace !== "default" ? `${namespace}/` : "";
  const short = `POST agents/${ns}${agentName}/invoke`;
  // If the command is a curl hitting the invoke route, just return the short form
  if (/curl\b/i.test(command) && AGENT_INVOKE_ROUTE_PATTERN.test(command)) {
    return short;
  }
  if (/curl\b/i.test(command) && A2A_ROUTE_PATTERN.test(command)) {
    return `A2A SendMessage agents/${ns}${agentName}`;
  }
  return truncate(command, 120) ?? short;
}

function parseAgentInvokeTarget(command: string): { namespace: string | null; agentName: string; route: "legacy" | "a2a" } | null {
  const legacyMatch = command.match(AGENT_INVOKE_ROUTE_PATTERN);
  if (legacyMatch?.[2]) {
    return {
      namespace: (legacyMatch[3] || legacyMatch[1] || "").trim() || null,
      agentName: legacyMatch[2].trim(),
      route: "legacy",
    };
  }

  const a2aMatch = command.match(A2A_ROUTE_PATTERN);
  if (!a2aMatch?.[1]) return null;
  return {
    namespace: (a2aMatch[2] || "").trim() || null,
    agentName: a2aMatch[1].trim(),
    route: "a2a",
  };
}

export function parseAgentInvokeCommand(command: string): { namespace: string | null; agentName: string } | null {
  const target = parseAgentInvokeTarget(command);
  return target ? { namespace: target.namespace, agentName: target.agentName } : null;
}

function extractMetadataA2ATarget(summary: InvocationSummary): AgentCallSummary | null {
  const metadata = asRecord(summary.metadata);
  const target = asRecord(metadata?.a2aTarget);
  if (!target) return null;

  const agentName = readString(target, "agent") || summary.a2a?.targetAgent || null;
  if (!agentName) return null;

  const namespace = readString(target, "namespace") || summary.a2a?.targetNamespace || null;
  const transport = readString(target, "transport") || summary.a2a?.transport || null;
  const threadId = readString(target, "threadId") || summary.a2a?.targetThreadId || null;
  const requestId = readString(target, "requestId");
  const status = summary.a2a?.responseStatus || summary.status;

  return {
    id: `explicit:${namespace || "default"}/${agentName}:${threadId || status || "completed"}`,
    kind: "explicit-a2a",
    agentName,
    namespace,
    status: status || "completed",
    transport,
    threadId,
    requestId,
    responsePreview: null,
    commandPreview: null,
  };
}

export function extractAgentCallFromToolCall(toolCall: Record<string, unknown>, index = 0): AgentCallSummary | null {
  const tool = String(toolCall.tool ?? "").trim().toLowerCase();
  if (tool !== "bash" && tool !== "shell") return null;

  const inputRecord = asRecord(toolCall.input);
  const command = typeof toolCall.input === "string"
    ? toolCall.input
    : readString(inputRecord, "command") || readString(inputRecord, "cmd") || "";
  const target = parseAgentInvokeTarget(command);
  if (!target) return null;

  const outputText = typeof toolCall.output === "string" ? toolCall.output : "";
  const outputInfo = parseGatewayOutput(outputText);
  const status = outputInfo.status || String(toolCall.status ?? "completed").trim() || "completed";

  return {
    id: `tool:${index}:${target.namespace || "default"}/${outputInfo.agentName || target.agentName}`,
    kind: "tool-call",
    agentName: outputInfo.agentName || target.agentName,
    namespace: target.namespace,
    status,
    transport: target.route === "a2a" ? "a2a-jsonrpc" : "gateway",
    threadId: null,
    requestId: null,
    responsePreview: outputInfo.responsePreview,
    commandPreview: simplifyCommandPreview(sanitizeCommand(command), target.agentName, target.namespace),
  };
}

export function extractAgentCallsFromSummary(summary: InvocationSummary | null): AgentCallSummary[] {
  if (!summary) return [];

  const calls: AgentCallSummary[] = [];
  const seen = new Set<string>();

  const addCall = (call: AgentCallSummary | null) => {
    if (!call || seen.has(call.id)) return;
    seen.add(call.id);
    calls.push(call);
  };

  addCall(extractMetadataA2ATarget(summary));
  (summary.toolCalls ?? []).forEach((toolCall, index) => {
    if (!toolCall || typeof toolCall !== "object") return;
    addCall(extractAgentCallFromToolCall(toolCall as Record<string, unknown>, index));
  });

  return calls;
}