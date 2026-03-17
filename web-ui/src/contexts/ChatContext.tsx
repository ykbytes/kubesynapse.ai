import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import {
  buildInvocationSummary,
  decideApproval,
  fetchAgentLogs,
  invokeAgent,
  streamAgentInvoke,
  streamAgentLogs,
} from "@/lib/api";
import { isValidK8sName } from "@/lib/a2a";
import { useConnection } from "./ConnectionContext";
import { useWorkspace } from "./WorkspaceContext";
import type {
  InvocationSummary,
  InvokePayload,
  SpecialistSubagentDraft,
  UiActivity,
  UiMessage,
} from "@/types";

// ── Local types ──

type InvokeExecutionOptions = {
  agentName: string;
  payload: InvokePayload;
  userPrompt?: string;
  appendUserMessage?: boolean;
  systemNotice?: string;
};

type GooseChatSettings = {
  maxTurns: string;
  workingDirectory: string;
};

const DEFAULT_GOOSE_CHAT_SETTINGS: GooseChatSettings = { maxTurns: "", workingDirectory: "" };

type OpenCodeChatSettings = {
  outputFormat: string;
  autonomous: boolean;
  maxTurns: string;
  workingDirectory: string;
};

const DEFAULT_OPENCODE_CHAT_SETTINGS: OpenCodeChatSettings = { outputFormat: "text", autonomous: true, maxTurns: "", workingDirectory: "" };

// ── Utility functions ──

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function createSpecialistSubagentDraft(initial?: Partial<SpecialistSubagentDraft>): SpecialistSubagentDraft {
  return {
    id: createId(),
    name: initial?.name ?? "",
    namespace: initial?.namespace ?? "",
    role: initial?.role ?? "",
    task: initial?.task ?? "",
    inputFilesText: initial?.inputFilesText ?? "",
    resultFilePath: initial?.resultFilePath ?? "",
    shareSandboxSession: initial?.shareSandboxSession ?? true,
    timeoutSeconds: initial?.timeoutSeconds ?? "",
  };
}

function parseGooseMaxTurns(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (!/^\d+$/.test(trimmed)) throw new Error("Goose max turns must be a positive integer.");
  const parsed = Number.parseInt(trimmed, 10);
  if (parsed < 1) throw new Error("Goose max turns must be at least 1.");
  return parsed;
}

function parseA2ATimeoutSeconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed < 1) throw new Error("A2A timeout seconds must be a number >= 1.");
  return parsed;
}

function parseSubagentTimeoutSeconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed < 1) throw new Error("Subagent timeout seconds must be a number >= 1.");
  return parsed;
}

function parseSubagentInputFiles(text: string): Array<{ path: string; purpose?: string }> {
  return text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((line) => {
    const [pathPart, ...purposeParts] = line.split("|");
    const path = pathPart?.trim() ?? "";
    if (!path) throw new Error("Shared file entries must include a path.");
    const purpose = purposeParts.join("|").trim();
    return purpose ? { path, purpose } : { path };
  });
}

function hasSpecialistTeamEntries(items: SpecialistSubagentDraft[]): boolean {
  return items.some((i) => i.name.trim() || i.namespace.trim() || i.role.trim() || i.task.trim() || i.inputFilesText.trim() || i.resultFilePath.trim());
}

function normalizeGooseWorkingDirectory(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(trimmed)) throw new Error("Goose working directory must stay inside the mounted workspace. Use a relative subdirectory.");
  const segments = trimmed.replace(/\\+/g, "/").split("/").filter((s) => s.length > 0);
  if (segments.length === 0) return undefined;
  if (segments.some((s) => s === "." || s === "..")) throw new Error("Goose working directory must use a workspace-relative path without '.' or '..' segments.");
  return segments.join("/");
}

function parseOpenCodeMaxTurns(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (!/^\d+$/.test(trimmed)) throw new Error("OpenCode max turns must be a positive integer.");
  const parsed = Number.parseInt(trimmed, 10);
  if (parsed < 1) throw new Error("OpenCode max turns must be at least 1.");
  return parsed;
}

function normalizeOpenCodeWorkingDirectory(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(trimmed)) throw new Error("OpenCode working directory must stay inside the mounted workspace. Use a relative subdirectory.");
  const segments = trimmed.replace(/\\+/g, "/").split("/").filter((s) => s.length > 0);
  if (segments.length === 0) return undefined;
  if (segments.some((s) => s === "." || s === "..")) throw new Error("OpenCode working directory must use a workspace-relative path without '.' or '..' segments.");
  return segments.join("/");
}

// ── Context value type ──

export interface ChatContextValue {
  // Per-agent state
  messages: UiMessage[];
  activity: UiActivity[];
  summary: InvocationSummary | null;
  logs: string;
  selectedGooseChatSettings: GooseChatSettings;
  selectedOpenCodeChatSettings: OpenCodeChatSettings;
  gooseSystemPromptPreview: string;

  // Chat UI state
  prompt: string;
  streamMode: boolean;
  requireApproval: boolean;
  approvalSupported: boolean;
  chatError: string;
  isSending: boolean;
  logsLoading: boolean;
  logsStreaming: boolean;
  canSubmitChat: boolean;
  chatEmptyMessage: string;

  // A2A state
  a2aTargetAgent: string;
  a2aTargetNamespace: string;
  a2aTimeoutSeconds: string;

  // Specialist team
  specialistSubagents: SpecialistSubagentDraft[];
  specialistTeamConfigured: boolean;
  subagentStrategy: "sequential" | "parallel";

  // Approval
  approvalReason: string;
  approvalBusy: boolean;
  selectedWorkflowApprovalName: string | undefined;

  // Setters
  setPrompt: (value: string) => void;
  setStreamMode: (value: boolean) => void;
  setRequireApproval: (value: boolean) => void;
  setChatError: (value: string) => void;
  setApprovalReason: (value: string) => void;
  setA2ATargetAgent: (value: string) => void;
  setA2ATargetNamespace: (value: string) => void;
  setA2ATimeoutSeconds: (value: string) => void;
  setSubagentStrategy: (value: "sequential" | "parallel") => void;

  // Specialist actions
  addSpecialistSubagent: () => void;
  updateSpecialistSubagent: (id: string, patch: Partial<SpecialistSubagentDraft>) => void;
  removeSpecialistSubagent: (id: string) => void;
  clearSpecialistTeam: () => void;

  // Goose settings
  setGooseMaxTurns: (value: string) => void;
  setGooseWorkingDirectory: (value: string) => void;

  // OpenCode settings
  setOpenCodeOutputFormat: (value: string) => void;
  setOpenCodeAutonomous: (value: boolean) => void;
  setOpenCodeMaxTurns: (value: string) => void;
  setOpenCodeWorkingDirectory: (value: string) => void;

  // Actions
  handleSubmit: () => Promise<void>;
  handleLoadLogs: () => Promise<void>;
  handleStreamLogs: () => void;
  handleStopLogStream: () => void;
  handleAgentApprovalDecision: (decision: "approved" | "denied") => Promise<void>;
  handleWorkflowApprovalDecision: (decision: "approved" | "denied") => Promise<void>;
  cancelStream: () => void;

  // Cross-cutting helpers (for AppLayout use)
  setMessagesForAgent: (agentName: string, updater: (current: UiMessage[]) => UiMessage[]) => void;
  removeAgentChatState: (agentName: string) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

// ── Provider ──

export function ChatProvider({ children }: { children: ReactNode }) {
  const { token, namespace } = useConnection();
  const {
    selectedAgentName,
    selectedRuntimeKind,
    selectedAgentDetail,
    selectedWorkflow,
    refreshWorkspaceData,
    setWorkspaceError,
  } = useWorkspace();

  const [messagesByAgent, setMessagesByAgent] = useState<Record<string, UiMessage[]>>({});
  const [activityByAgent, setActivityByAgent] = useState<Record<string, UiActivity[]>>({});
  const [summaryByAgent, setSummaryByAgent] = useState<Record<string, InvocationSummary | null>>({});
  const [logsByAgent, setLogsByAgent] = useState<Record<string, string>>({});
  const [gooseChatSettingsByAgent, setGooseChatSettingsByAgent] = useState<Record<string, GooseChatSettings>>({});
  const [opencodeChatSettingsByAgent, setOpenCodeChatSettingsByAgent] = useState<Record<string, OpenCodeChatSettings>>({});

  const [prompt, setPrompt] = useState("");
  const [streamMode, setStreamMode] = useState(true);
  const [requireApproval, setRequireApproval] = useState(false);
  const [chatError, setChatError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [logsStreaming, setLogsStreaming] = useState(false);
  const logStreamAbortRef = useRef<AbortController | null>(null);

  const [a2aTargetAgent, setA2ATargetAgent] = useState("");
  const [a2aTargetNamespace, setA2ATargetNamespace] = useState("");
  const [a2aTimeoutSeconds, setA2ATimeoutSeconds] = useState("");
  const [specialistSubagents, setSpecialistSubagents] = useState<SpecialistSubagentDraft[]>([]);
  const [subagentStrategy, setSubagentStrategy] = useState<"sequential" | "parallel">("sequential");

  const [approvalReason, setApprovalReason] = useState("");
  const [approvalBusy, setApprovalBusy] = useState(false);

  const threadIdsRef = useRef<Record<string, string>>({});
  const pendingRequestRef = useRef<Record<string, InvokePayload | null>>({});
  const streamAbortRef = useRef<AbortController | null>(null);

  // ── Derived ──

  const messages = selectedAgentName ? messagesByAgent[selectedAgentName] ?? [] : [];
  const activity = selectedAgentName ? activityByAgent[selectedAgentName] ?? [] : [];
  const summary = selectedAgentName ? summaryByAgent[selectedAgentName] ?? null : null;
  const logs = selectedAgentName ? logsByAgent[selectedAgentName] ?? "" : "";
  const selectedGooseChatSettings = selectedAgentName
    ? gooseChatSettingsByAgent[selectedAgentName] ?? DEFAULT_GOOSE_CHAT_SETTINGS
    : DEFAULT_GOOSE_CHAT_SETTINGS;
  const selectedOpenCodeChatSettings = selectedAgentName
    ? opencodeChatSettingsByAgent[selectedAgentName] ?? DEFAULT_OPENCODE_CHAT_SETTINGS
    : DEFAULT_OPENCODE_CHAT_SETTINGS;
  const approvalSupported = selectedRuntimeKind === "langgraph" || selectedRuntimeKind === "opencode";
  const specialistTeamConfigured = hasSpecialistTeamEntries(specialistSubagents);
  const canSubmitChat = Boolean(prompt.trim() || specialistSubagents.some((i) => i.task.trim()));
  const gooseSystemPromptPreview = selectedAgentDetail?.system_prompt.trim()
    ? selectedAgentDetail.system_prompt
    : "This agent is using the container-level Goose system prompt. Save an agent-specific prompt here when the runtime needs stronger guidance.";
  const chatEmptyMessage = selectedAgentName
    ? "Run chat requests, explicit A2A delegations, or specialist-team orchestration from this workspace. Streaming is enabled by default."
    : "Select an agent from the catalog or create a new one to start an invocation.";
  const selectedWorkflowApprovalName = typeof selectedWorkflow?.pending_approval?.name === "string"
    ? selectedWorkflow.pending_approval.name
    : undefined;

  // ── Effects ──

  useEffect(() => {
    if (!approvalSupported && requireApproval) setRequireApproval(false);
  }, [approvalSupported, requireApproval]);

  useEffect(() => {
    setA2ATargetAgent(""); setA2ATargetNamespace(""); setA2ATimeoutSeconds("");
    setSpecialistSubagents([]); setSubagentStrategy("sequential");
  }, [selectedAgentName, selectedRuntimeKind]);

  // ── Per-agent state helpers ──

  const setMessagesForAgent = useCallback((agentName: string, updater: (current: UiMessage[]) => UiMessage[]) => {
    setMessagesByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? []) }));
  }, []);

  function setActivityForAgent(agentName: string, updater: (current: UiActivity[]) => UiActivity[]) {
    setActivityByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? []) }));
  }

  function setSummaryForAgent(agentName: string, updater: (current: InvocationSummary | null) => InvocationSummary | null) {
    setSummaryByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? null) }));
  }

  function setLogsForAgent(agentName: string, value: string | ((prev: string) => string)) {
    setLogsByAgent((prev) => {
      const current = prev[agentName] ?? "";
      const next = typeof value === "function" ? value(current) : value;
      return { ...prev, [agentName]: next };
    });
  }

  function setGooseChatSettingsForAgent(agentName: string, updater: (current: GooseChatSettings) => GooseChatSettings) {
    setGooseChatSettingsByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? DEFAULT_GOOSE_CHAT_SETTINGS) }));
  }

  function setOpenCodeChatSettingsForAgent(agentName: string, updater: (current: OpenCodeChatSettings) => OpenCodeChatSettings) {
    setOpenCodeChatSettingsByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? DEFAULT_OPENCODE_CHAT_SETTINGS) }));
  }

  const removeAgentChatState = useCallback((agentName: string) => {
    setMessagesByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setActivityByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setSummaryByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setLogsByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setGooseChatSettingsByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setOpenCodeChatSettingsByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    delete threadIdsRef.current[agentName];
    delete pendingRequestRef.current[agentName];
  }, []);

  // ── Internal helpers ──

  function pushActivity(agentName: string, event: string, payload: Record<string, unknown>) {
    if (event === "response.delta") return;
    setActivityForAgent(agentName, (cur) => [{ id: createId(), event, payload, timestamp: new Date().toISOString() }, ...cur].slice(0, 200));
  }

  function setPendingAssistantContent(agentName: string, messageId: string, content: string, status: UiMessage["status"]) {
    setMessagesForAgent(agentName, (cur) => cur.map((m) => m.id === messageId ? { ...m, content, status } : m));
  }

  function applyInvocationFailure(agentName: string, messageId: string, message: string) {
    pendingRequestRef.current[agentName] = null;
    setPendingAssistantContent(agentName, messageId, message, "error");
    setChatError(message);
  }

  function updateSummary(agentName: string, threadId: string, payload: unknown): InvocationSummary {
    const next = buildInvocationSummary(threadId, payload);
    setSummaryForAgent(agentName, () => next);
    return next;
  }

  // ── runInvocation ──

  async function runInvocation({ agentName, payload, userPrompt, appendUserMessage = true, systemNotice }: InvokeExecutionOptions) {
    const requestId = createId();
    const assistantMessageId = createId();

    setChatError(""); setWorkspaceError(""); setLogsForAgent(agentName, ""); setActivityForAgent(agentName, () => []); setSummaryForAgent(agentName, () => null);
    setMessagesForAgent(agentName, (cur) => {
      const next = [...cur];
      if (systemNotice) next.push({ id: createId(), role: "system", content: systemNotice, status: "complete" });
      if (appendUserMessage && userPrompt?.trim()) next.push({ id: createId(), role: "user", content: userPrompt.trim(), status: "complete" });
      next.push({ id: assistantMessageId, role: "assistant", content: "", status: "streaming" });
      return next;
    });
    setIsSending(true);

    if (!streamMode) {
      try {
        const result = await invokeAgent(token, namespace, agentName, payload, requestId);
        const nextSummary = updateSummary(agentName, result.thread_id, result);
        threadIdsRef.current[agentName] = nextSummary.threadId;
        pendingRequestRef.current[agentName] = nextSummary.status === "approval_pending" ? { ...payload, thread_id: nextSummary.threadId } : null;
        setPendingAssistantContent(agentName, assistantMessageId,
          result.response || (nextSummary.status === "approval_pending" ? "Approval pending. Re-submit after approval." : "No response body returned."),
          nextSummary.status === "blocked" ? "error" : "complete");
      } catch (err) {
        applyInvocationFailure(agentName, assistantMessageId, err instanceof Error ? err.message : String(err));
      } finally { setIsSending(false); }
      return;
    }

    const abortController = new AbortController();
    const previousController = streamAbortRef.current;
    streamAbortRef.current = abortController;
    previousController?.abort();
    let streamErrorHandled = false;

    try {
      await streamAgentInvoke({
        signal: abortController.signal, token, namespace, agentName, payload, requestId,
        onEvent: ({ event, payload: ep }) => {
          pushActivity(agentName, event, ep);
          const TOOL_NODES = new Set(["sandbox_tool", "mcp_tool", "retrieval", "output_guard"]);

          if (event === "graph.node") {
            const nodeName = String(ep.node ?? "");
            const nodeStatus = String(ep.status ?? "");
            if (TOOL_NODES.has(nodeName)) {
              if (nodeStatus === "started") {
                const toolMsgId = `tool-${nodeName}-${createId()}`;
                setMessagesForAgent(agentName, (cur) => {
                  const idx = cur.findIndex((m) => m.id === assistantMessageId);
                  const toolMsg: UiMessage = { id: toolMsgId, role: "tool", content: "", status: "streaming", toolName: nodeName.replace(/_/g, " "), toolNode: nodeName };
                  if (idx >= 0) { const n = [...cur]; n.splice(idx, 0, toolMsg); return n; }
                  return [...cur, toolMsg];
                });
              } else if (nodeStatus === "completed" || nodeStatus === "failed") {
                setMessagesForAgent(agentName, (cur) => cur.map((m) =>
                  m.role === "tool" && m.toolNode === nodeName && m.status === "streaming"
                    ? { ...m, status: nodeStatus === "failed" ? "error" : "complete", content: nodeStatus === "failed" ? String(ep.error ?? "Tool call failed") : m.content || "Completed" }
                    : m));
              }
            }
            return;
          }

          if (event === "mcp.result") {
            const serverType = String(ep.serverType ?? "");
            const toolName = String(ep.toolName ?? "");
            const label = serverType ? `${serverType}/${toolName}` : toolName;
            setMessagesForAgent(agentName, (cur) => cur.map((m) =>
              m.role === "tool" && m.toolNode === "mcp_tool" && m.status === "streaming"
                ? { ...m, toolName: label, content: `${label} → ${ep.bytes ?? "?"} bytes` }
                : m));
            return;
          }

          if (event === "subagent.call") {
            const target = String(ep.targetAgent ?? "subagent");
            const status = String(ep.status ?? "");
            if (status === "started") {
              setMessagesForAgent(agentName, (cur) => {
                const idx = cur.findIndex((m) => m.id === assistantMessageId);
                const toolMsg: UiMessage = { id: `tool-subagent-${createId()}`, role: "tool", content: "", status: "streaming", toolName: `subagent → ${target}`, toolNode: "subagent" };
                if (idx >= 0) { const n = [...cur]; n.splice(idx, 0, toolMsg); return n; }
                return [...cur, toolMsg];
              });
            } else if (status === "completed" || status === "failed") {
              setMessagesForAgent(agentName, (cur) => cur.map((m) =>
                m.role === "tool" && m.toolNode === "subagent" && m.status === "streaming"
                  ? { ...m, status: status === "failed" ? "error" : "complete", content: m.content || "Completed" }
                  : m));
            }
            return;
          }

          if (event === "response.delta") {
            if (typeof ep.delta !== "string") throw new Error("response.delta events must include a string delta field.");
            setMessagesForAgent(agentName, (cur) => cur.map((m) => m.id === assistantMessageId ? { ...m, content: `${m.content}${ep.delta}`, status: "streaming" } : m));
            return;
          }

          if (event === "response.completed") {
            const nextSummary = updateSummary(agentName, threadIdsRef.current[agentName] ?? "", ep);
            threadIdsRef.current[agentName] = nextSummary.threadId;
            pendingRequestRef.current[agentName] = nextSummary.status === "approval_pending" ? { ...payload, thread_id: nextSummary.threadId } : null;
            setMessagesForAgent(agentName, (cur) => cur.map((m) => m.id === assistantMessageId
              ? { ...m, content: m.content || (nextSummary.status === "approval_pending" ? "Approval pending. Re-submit after approval." : "Invocation completed."), status: nextSummary.status === "blocked" ? "error" : "complete" }
              : m));
            return;
          }

          if (event === "response.error") {
            if (typeof ep.error !== "string" || !ep.error.trim()) throw new Error(`${event} events must include a non-empty string error field.`);
            applyInvocationFailure(agentName, assistantMessageId, ep.error);
          }
        },
        onError: (err) => { streamErrorHandled = true; applyInvocationFailure(agentName, assistantMessageId, err.message); },
        onClose: () => undefined,
      });
    } catch (err) {
      if (!abortController.signal.aborted && !streamErrorHandled) {
        applyInvocationFailure(agentName, assistantMessageId, err instanceof Error ? err.message : String(err));
      }
    } finally {
      setIsSending(false);
      if (streamAbortRef.current === abortController) {
        streamAbortRef.current = null;
      }
    }
  }

  // ── handleSubmit ──

  const handleSubmit = useCallback(async () => {
    if (!token.trim()) { setChatError("Enter the gateway token before sending chat requests."); return; }
    if (!selectedAgentName || !canSubmitChat) return;

    const agentName = selectedAgentName;
    const nextPrompt = prompt.trim();
    let gooseMaxTurns: number | undefined;
    let gooseWorkingDirectory: string | undefined;
    let opencodeMaxTurns: number | undefined;
    let opencodeWorkingDirectory: string | undefined;
    let explicitA2ATimeoutSeconds: number | undefined;
    let specialistPayload: InvokePayload["subagents"];

    if (selectedRuntimeKind === "goose") {
      try {
        gooseMaxTurns = parseGooseMaxTurns(selectedGooseChatSettings.maxTurns);
        gooseWorkingDirectory = normalizeGooseWorkingDirectory(selectedGooseChatSettings.workingDirectory);
      } catch (err) { setChatError(err instanceof Error ? err.message : String(err)); return; }
    }
    if (selectedRuntimeKind === "opencode") {
      try {
        opencodeMaxTurns = parseOpenCodeMaxTurns(selectedOpenCodeChatSettings.maxTurns);
        opencodeWorkingDirectory = normalizeOpenCodeWorkingDirectory(selectedOpenCodeChatSettings.workingDirectory);
      } catch (err) { setChatError(err instanceof Error ? err.message : String(err)); return; }
    }
    try { explicitA2ATimeoutSeconds = parseA2ATimeoutSeconds(a2aTimeoutSeconds); }
    catch (err) { setChatError(err instanceof Error ? err.message : String(err)); return; }

    const normA2AAgent = a2aTargetAgent.trim();
    const normA2ANs = a2aTargetNamespace.trim();
    const hasExplicitA2A = normA2AAgent.length > 0 || normA2ANs.length > 0;
    if (specialistTeamConfigured && selectedRuntimeKind !== "langgraph") { setChatError("Specialist-team orchestration is currently available for LangGraph agents only."); return; }
    if (hasExplicitA2A) {
      if (selectedRuntimeKind !== "langgraph") { setChatError("Explicit A2A routing is only supported for LangGraph agents."); return; }
      if (!normA2AAgent || !normA2ANs) { setChatError("Provide both an A2A target namespace and an A2A target agent."); return; }
      if (!isValidK8sName(normA2AAgent)) { setChatError("A2A target agent must be a valid lowercase Kubernetes name."); return; }
      if (!isValidK8sName(normA2ANs)) { setChatError("A2A target namespace must be a valid lowercase Kubernetes name."); return; }
    }
    if (hasExplicitA2A && specialistTeamConfigured) { setChatError("Use either an explicit A2A target or a specialist team for this request, not both."); return; }

    if (specialistTeamConfigured) {
      try {
        specialistPayload = specialistSubagents.filter((i) => i.name.trim() || i.namespace.trim() || i.role.trim() || i.task.trim() || i.inputFilesText.trim() || i.resultFilePath.trim())
          .map((item, idx) => {
            const name = item.name.trim(); const sns = item.namespace.trim();
            if (!name || !sns) throw new Error(`Specialist ${idx + 1} requires both a namespace and an agent name.`);
            if (!isValidK8sName(name)) throw new Error(`Specialist ${idx + 1} agent name must be a valid lowercase Kubernetes name.`);
            if (!isValidK8sName(sns)) throw new Error(`Specialist ${idx + 1} namespace must be a valid lowercase Kubernetes name.`);
            const timeoutSeconds = parseSubagentTimeoutSeconds(item.timeoutSeconds);
            const inputFiles = parseSubagentInputFiles(item.inputFilesText);
            const task = item.task.trim();
            if (!nextPrompt && !task) throw new Error(`Specialist ${idx + 1} requires a delegated task when the main prompt is blank.`);
            return { name, namespace: sns, role: item.role.trim() || undefined, task: task || undefined,
              input_files: inputFiles.length > 0 ? inputFiles : undefined, result_file_path: item.resultFilePath.trim() || undefined,
              share_sandbox_session: item.shareSandboxSession, timeout_seconds: timeoutSeconds };
          });
      } catch (err) { setChatError(err instanceof Error ? err.message : String(err)); return; }
    }

    const payload: InvokePayload = {
      prompt: nextPrompt, thread_id: threadIdsRef.current[agentName], require_approval: requireApproval,
      approval_action: requireApproval ? `Approve UI request for ${agentName}` : undefined,
      a2a_target_agent: hasExplicitA2A ? normA2AAgent : undefined, a2a_target_namespace: hasExplicitA2A ? normA2ANs : undefined,
      a2a_timeout_seconds: explicitA2ATimeoutSeconds, subagents: specialistPayload,
      subagent_strategy: specialistPayload && specialistPayload.length > 0 ? subagentStrategy : undefined,
      max_turns: gooseMaxTurns ?? opencodeMaxTurns,
      working_directory: gooseWorkingDirectory ?? opencodeWorkingDirectory,
      output_format: selectedRuntimeKind === "opencode" ? selectedOpenCodeChatSettings.outputFormat || undefined : undefined,
      autonomous: selectedRuntimeKind === "opencode" ? selectedOpenCodeChatSettings.autonomous : undefined,
    };

    setPrompt("");
    await runInvocation({ agentName, payload, userPrompt: nextPrompt, appendUserMessage: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, namespace, selectedAgentName, selectedRuntimeKind, prompt, canSubmitChat, streamMode, requireApproval,
    a2aTargetAgent, a2aTargetNamespace, a2aTimeoutSeconds, specialistSubagents, subagentStrategy, selectedGooseChatSettings, selectedOpenCodeChatSettings]);

  // ── handleLoadLogs ──

  const handleLoadLogs = useCallback(async () => {
    if (!token.trim() || !selectedAgentName) return;
    setLogsLoading(true); setWorkspaceError("");
    try {
      const result = await fetchAgentLogs(token, namespace, selectedAgentName, 500);
      setLogsForAgent(selectedAgentName, result.logs);
    } catch (err) { setWorkspaceError(err instanceof Error ? err.message : String(err)); }
    finally { setLogsLoading(false); }
  }, [token, namespace, selectedAgentName, setWorkspaceError]);

  // ── handleStreamLogs / handleStopLogStream ──

  const handleStopLogStream = useCallback(() => {
    if (logStreamAbortRef.current) {
      logStreamAbortRef.current.abort();
      logStreamAbortRef.current = null;
    }
    setLogsStreaming(false);
  }, []);

  const handleStreamLogs = useCallback(() => {
    if (!token.trim() || !selectedAgentName) return;
    // Stop any existing stream first
    if (logStreamAbortRef.current) logStreamAbortRef.current.abort();

    const abortController = new AbortController();
    logStreamAbortRef.current = abortController;
    const agentName = selectedAgentName;

    setLogsStreaming(true);
    setWorkspaceError("");

    streamAgentLogs({
      signal: abortController.signal,
      token,
      namespace,
      agentName,
      tail: 100,
      onStarted: (info) => {
        // Clear logs only after connection succeeds (not before)
        setLogsForAgent(agentName, `── streaming logs from pod ${info.pod_name} ──\n`);
      },
      onLine: (line) => {
        setLogsForAgent(agentName, (prev) => prev + line + "\n");
      },
      onError: (error) => {
        if (!abortController.signal.aborted) {
          setWorkspaceError(`Log stream error: ${error.message}`);
        }
        setLogsStreaming(false);
        logStreamAbortRef.current = null;
      },
      onStopped: () => {
        setLogsStreaming(false);
        logStreamAbortRef.current = null;
      },
    }).catch(() => {
      // handled by onError/onStopped
      setLogsStreaming(false);
      logStreamAbortRef.current = null;
    });
  }, [token, namespace, selectedAgentName, setWorkspaceError]);

  // Stop log stream when agent selection changes
  useEffect(() => {
    return () => {
      if (logStreamAbortRef.current) {
        logStreamAbortRef.current.abort();
        logStreamAbortRef.current = null;
      }
    };
  }, [selectedAgentName]);

  // ── handleAgentApprovalDecision ──

  const handleAgentApprovalDecision = useCallback(async (decision: "approved" | "denied") => {
    if (!token.trim() || !selectedAgentName || !summary?.approvalName) return;
    const agentName = selectedAgentName;
    const approvalName = summary.approvalName;
    setApprovalBusy(true); setWorkspaceError("");
    try {
      await decideApproval(token, namespace, approvalName, decision, approvalReason);
      if (decision === "denied") {
        pendingRequestRef.current[agentName] = null;
        setSummaryForAgent(agentName, (cur) => cur ? { ...cur, status: "blocked" } : cur);
        setMessagesForAgent(agentName, (cur) => [...cur, {
          id: createId(), role: "system" as const,
          content: approvalReason.trim() ? `Approval ${approvalName} was denied. Reason: ${approvalReason.trim()}` : `Approval ${approvalName} was denied.`,
          status: "complete" as const,
        }]);
      } else {
        const pendingPayload = pendingRequestRef.current[agentName];
        if (!pendingPayload) {
          setSummaryForAgent(agentName, (cur) => cur ? { ...cur, status: "approved" } : cur);
        } else {
          await runInvocation({
            agentName, payload: { ...pendingPayload, thread_id: threadIdsRef.current[agentName] ?? pendingPayload.thread_id },
            appendUserMessage: false, systemNotice: `Approval ${approvalName} granted. Retrying the pending request.`,
          });
        }
      }
      setApprovalReason("");
    } catch (err) { setWorkspaceError(err instanceof Error ? err.message : String(err)); }
    finally { setApprovalBusy(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, namespace, selectedAgentName, summary, approvalReason, setWorkspaceError]);

  // ── handleWorkflowApprovalDecision ──

  const handleWorkflowApprovalDecision = useCallback(async (decision: "approved" | "denied") => {
    const approvalName = selectedWorkflowApprovalName;
    if (!token.trim() || !approvalName) return;
    setApprovalBusy(true); setWorkspaceError("");
    try {
      await decideApproval(token, namespace, approvalName, decision, approvalReason);
      setApprovalReason("");
      await refreshWorkspaceData({ silent: false });
    } catch (err) { setWorkspaceError(err instanceof Error ? err.message : String(err)); }
    finally { setApprovalBusy(false); }
  }, [token, namespace, selectedWorkflowApprovalName, approvalReason, refreshWorkspaceData, setWorkspaceError]);

  // ── cancelStream ──

  const cancelStream = useCallback(() => {
    const controller = streamAbortRef.current;
    if (controller) {
      controller.abort();
      streamAbortRef.current = null;
    }
    setIsSending(false);
    if (selectedAgentName) {
      setMessagesForAgent(selectedAgentName, (cur) =>
        cur.map((m) => m.status === "streaming" ? { ...m, status: "complete" as const, content: m.content || "(cancelled)" } : m)
      );
    }
  }, [selectedAgentName, setMessagesForAgent]);

  // ── Specialist helpers ──

  const addSpecialistSubagent = useCallback(() => {
    setChatError(""); setSpecialistSubagents((cur) => [...cur, createSpecialistSubagentDraft()]);
  }, []);
  const updateSpecialistSubagent = useCallback((id: string, patch: Partial<SpecialistSubagentDraft>) => {
    setChatError(""); setSpecialistSubagents((cur) => cur.map((i) => i.id === id ? { ...i, ...patch } : i));
  }, []);
  const removeSpecialistSubagent = useCallback((id: string) => {
    setChatError(""); setSpecialistSubagents((cur) => cur.filter((i) => i.id !== id));
  }, []);
  const clearSpecialistTeam = useCallback(() => {
    setChatError(""); setSpecialistSubagents([]); setSubagentStrategy("sequential");
  }, []);

  // ── Goose settings ──

  const setGooseMaxTurns = useCallback((value: string) => {
    setChatError(""); setGooseChatSettingsForAgent(selectedAgentName, (cur) => ({ ...cur, maxTurns: value }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentName]);
  const setGooseWorkingDirectory = useCallback((value: string) => {
    setChatError(""); setGooseChatSettingsForAgent(selectedAgentName, (cur) => ({ ...cur, workingDirectory: value }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentName]);

  // ── OpenCode settings ──

  const setOpenCodeOutputFormat = useCallback((value: string) => {
    setChatError(""); setOpenCodeChatSettingsForAgent(selectedAgentName, (cur) => ({ ...cur, outputFormat: value }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentName]);
  const setOpenCodeAutonomous = useCallback((value: boolean) => {
    setChatError(""); setOpenCodeChatSettingsForAgent(selectedAgentName, (cur) => ({ ...cur, autonomous: value }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentName]);
  const setOpenCodeMaxTurns = useCallback((value: string) => {
    setChatError(""); setOpenCodeChatSettingsForAgent(selectedAgentName, (cur) => ({ ...cur, maxTurns: value }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentName]);
  const setOpenCodeWorkingDirectory = useCallback((value: string) => {
    setChatError(""); setOpenCodeChatSettingsForAgent(selectedAgentName, (cur) => ({ ...cur, workingDirectory: value }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentName]);

  return (
    <ChatContext.Provider value={{
      messages, activity, summary, logs, selectedGooseChatSettings, selectedOpenCodeChatSettings, gooseSystemPromptPreview,
      prompt, streamMode, requireApproval, approvalSupported, chatError, isSending, logsLoading, logsStreaming, canSubmitChat, chatEmptyMessage,
      a2aTargetAgent, a2aTargetNamespace, a2aTimeoutSeconds,
      specialistSubagents, specialistTeamConfigured, subagentStrategy,
      approvalReason, approvalBusy, selectedWorkflowApprovalName,
      setPrompt, setStreamMode, setRequireApproval, setChatError, setApprovalReason,
      setA2ATargetAgent, setA2ATargetNamespace, setA2ATimeoutSeconds, setSubagentStrategy,
      addSpecialistSubagent, updateSpecialistSubagent, removeSpecialistSubagent, clearSpecialistTeam,
      setGooseMaxTurns, setGooseWorkingDirectory,
      setOpenCodeOutputFormat, setOpenCodeAutonomous, setOpenCodeMaxTurns, setOpenCodeWorkingDirectory,
      handleSubmit, handleLoadLogs, handleStreamLogs, handleStopLogStream, handleAgentApprovalDecision, handleWorkflowApprovalDecision, cancelStream,
      setMessagesForAgent, removeAgentChatState,
    }}>
      {children}
    </ChatContext.Provider>
  );
}

// ── Hook ──

export function useChat() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
