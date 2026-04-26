import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
    buildInvocationSummary,
    createChatSession,
    deleteMemoryRecord,
    decideApproval,
    deleteChatSession,
    fetchAgentTodos,
  fetchPendingQuestions,
    pollAgentTodos,
    fetchAgentLogs,
    getChatSessionMessages,
    invokeAgent,
    listAgentMemory,
    listChatSessions,
    rejectQuestion,
    replyToQuestion,
    saveChatSessionMessages,
    streamAgentInvoke,
    streamAgentLogs,
    updateMemoryRecord,
    updateChatSessionTitle,
    apiErrorMessage,
    sanitizeErrorMessage,
} from "@/lib/api";
import type { ChatSessionInfo, ChatSessionSummary, MemoryRecordInfo } from "@/lib/api";
import { isValidK8sName } from "@/lib/a2a";
import { useConnection } from "./ConnectionContext";
import { useWorkspace } from "./WorkspaceContext";
import type {
  FactoryMode,
  InvocationSummary,
  InvokePayload,
  QuestionRequest,
  SpecialistSubagentDraft,
  UiActivity,
  UiMessage,
  UiTodo,
} from "@/types";
import { DEFAULT_FACTORY_MODE, isFactoryAgentName } from "@/lib/factoryModes";

// ── Local types ──

type InvokeExecutionOptions = {
  agentName: string;
  payload: InvokePayload;
  userPrompt?: string;
  appendUserMessage?: boolean;
  systemNotice?: string;
};

type PromptSubmissionOptions = {
  appendUserMessage?: boolean;
  clearComposer?: boolean;
  systemNotice?: string;
};

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

function parseA2ATimeoutSeconds(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number.parseFloat(trimmed);
  if (!Number.isFinite(parsed) || parsed < 1) throw new Error("A2A timeout seconds must be a number >= 1.");
  return parsed;
}

function hasSpecialistTeamEntries(items: SpecialistSubagentDraft[]): boolean {
  return items.some((i) => i.name.trim() || i.namespace.trim() || i.role.trim() || i.task.trim() || i.inputFilesText.trim() || i.resultFilePath.trim());
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

function buildMessageSignature(messages: UiMessage[]): string {
  return JSON.stringify(messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    status: message.status ?? "complete",
    toolName: message.toolName ?? null,
    toolNode: message.toolNode ?? null,
  })));
}

function upsertChatSession(sessions: ChatSessionInfo[], nextSession: ChatSessionInfo): ChatSessionInfo[] {
  const remaining = sessions.filter((session) => session.session_id !== nextSession.session_id);
  return [nextSession, ...remaining];
}

function normalizeUiTodos(value: unknown): UiTodo[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const todo = item as Record<string, unknown>;
    const content = String(todo.content ?? todo.title ?? "").trim();
    if (!content) return [];
    const status = String(todo.status ?? "pending").trim().toLowerCase();
    const priority = String(todo.priority ?? "medium").trim().toLowerCase();
    return [{
      content,
      status: (status === "in_progress" || status === "completed" || status === "cancelled" ? status : "pending") as UiTodo["status"],
      priority: (priority === "high" || priority === "low" ? priority : "medium") as UiTodo["priority"],
    }];
  });
}

function normalizeToolCallStatus(rawStatus: string): NonNullable<UiMessage["toolCalls"]>[number]["status"] {
  const status = rawStatus.trim().toLowerCase();
  if (status === "failed") return "error";
  if (status === "working" || status === "in_progress") return "running";
  if (status === "completed" || status === "error" || status === "running") {
    return status as NonNullable<UiMessage["toolCalls"]>[number]["status"];
  }
  return "unknown";
}

function normalizeMessageToolCalls(value: Array<Record<string, unknown>> | null | undefined): UiMessage["toolCalls"] {
  if (!Array.isArray(value) || value.length === 0) return undefined;
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const tool = String(item.tool ?? "").trim();
    if (!tool) return [];
    return [{
      tool,
      status: normalizeToolCallStatus(String(item.status ?? "unknown")),
      input: item.input,
      output: typeof item.output === "string" ? item.output : undefined,
    }];
  });
}

function finalizeAssistantMessage(
  message: UiMessage,
  summary: InvocationSummary,
  fallbackContent: string,
): UiMessage {
  const normalizedToolCalls = normalizeMessageToolCalls(summary.toolCalls);
  return {
    ...message,
    content: message.content || fallbackContent,
    status: summary.status === "blocked" ? "error" : "complete",
    toolCalls: normalizedToolCalls ?? message.toolCalls,
    artifacts: summary.artifacts ?? message.artifacts,
    a2a: summary.a2a ?? message.a2a,
    subagents: summary.subagents ?? message.subagents,
    metadata: summary.metadata ?? message.metadata,
  };
}

function normalizePersistedMessageStatus(status: UiMessage["status"] | string | null | undefined): NonNullable<UiMessage["status"]> {
  if (status === "error" || status === "complete") return status;
  return "complete";
}

function normalizeQuestionRequest(payload: Record<string, unknown>): QuestionRequest | null {
  const id = String(payload.id ?? "").trim();
  if (!id) return null;
  const rawQuestions = payload.questions;
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) return null;
  const questions = rawQuestions.map((q: Record<string, unknown>) => ({
    question: String(q.question ?? ""),
    header: q.header ? String(q.header) : undefined,
    options: Array.isArray(q.options)
      ? q.options.map((o: Record<string, unknown>) => ({
          label: String(o.label ?? ""),
          description: String(o.description ?? ""),
        }))
      : [],
    multiple: q.multiple === true,
    custom: q.custom !== false,
  }));
  return { id, questions, sessionID: payload.sessionID ? String(payload.sessionID) : undefined };
}

// ── Context value type ──

export interface ChatContextValue {
  // Per-agent state
  messages: UiMessage[];
  activity: UiActivity[];
  summary: InvocationSummary | null;
  todos: UiTodo[];
  phase: "plan" | "build" | "idle";
  logs: string;
  selectedOpenCodeChatSettings: OpenCodeChatSettings;
  selectedFactoryMode: FactoryMode;

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

  // Question / HITL state
  pendingQuestion: QuestionRequest | null;
  questionResponding: boolean;
  handleQuestionReply: (requestId: string, answers: string[][]) => Promise<void>;
  handleQuestionReject: (requestId: string) => Promise<void>;

  // Followup suggestions
  followupSuggestions: { id: string; text: string }[];
  followupSending: string | undefined;
  handleFollowupSend: (id: string) => void;
  handleFollowupEdit: (id: string) => void;
  lastUserPrompt: string | null;
  handleReusePrompt: (text: string) => void;
  handleRegeneratePrompt: (text?: string) => Promise<void>;

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

  // OpenCode settings
  setOpenCodeOutputFormat: (value: string) => void;
  setOpenCodeAutonomous: (value: boolean) => void;
  setOpenCodeMaxTurns: (value: string) => void;
  setOpenCodeWorkingDirectory: (value: string) => void;
  setSelectedFactoryMode: (value: FactoryMode) => void;

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

  // Chat session persistence
  chatSessions: ChatSessionInfo[];
  activeSessionId: string | null;
  activeSessionSummary: ChatSessionSummary | null;
  activeMemoryRecords: MemoryRecordInfo[];
  agentMemoryRecords: MemoryRecordInfo[];
  sessionsLoading: boolean;
  sessionSearch: string;
  setSessionSearch: (value: string) => void;
  sessionDirty: boolean;
  sessionSaving: boolean;
  lastSessionSaveAt: string | null;
  handlePromoteMemoryRecord: (recordId: number, promoted: boolean) => Promise<void>;
  handleEditMemoryRecord: (recordId: number, patch: { topic?: string; content?: string; promoted?: boolean }) => Promise<void>;
  handleDeleteMemoryRecord: (recordId: number) => Promise<void>;
  handleNewSession: () => Promise<void>;
  handleLoadSession: (sessionId: string) => Promise<void>;
  handleDeleteSession: (sessionId: string) => Promise<void>;
  handleRenameSession: (sessionId: string, title: string) => Promise<void>;
  handleSaveCurrentSession: () => Promise<void>;
}

const ChatContext = createContext<ChatContextValue | null>(null);

// ── Provider ──

export function ChatProvider({ children }: { children: ReactNode }) {
  const { token, namespace } = useConnection();
  const {
    selectedAgentName,
    selectedRuntimeKind,
    selectedWorkflow,
    refreshWorkspaceData,
    setWorkspaceError,
  } = useWorkspace();

  const [messagesByAgent, setMessagesByAgent] = useState<Record<string, UiMessage[]>>({});
  const [activityByAgent, setActivityByAgent] = useState<Record<string, UiActivity[]>>({});
  const [summaryByAgent, setSummaryByAgent] = useState<Record<string, InvocationSummary | null>>({});
  const [todosByAgent, setTodosByAgent] = useState<Record<string, UiTodo[]>>({});
  const [phaseByAgent, setPhaseByAgent] = useState<Record<string, "plan" | "build" | "idle">>({});
  const [logsByAgent, setLogsByAgent] = useState<Record<string, string>>({});
  const [opencodeChatSettingsByAgent, setOpenCodeChatSettingsByAgent] = useState<Record<string, OpenCodeChatSettings>>({});
  const [factoryModeByAgent, setFactoryModeByAgent] = useState<Record<string, FactoryMode>>({});

  const [prompt, setPrompt] = useState("");
  const [streamMode, setStreamMode] = useState(true);
  const [requireApproval, setRequireApproval] = useState(false);
  const [chatError, setChatError] = useState("");
  const [isSendingByAgent, setIsSendingByAgent] = useState<Record<string, boolean>>({});
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

  // Question / HITL state
  const [pendingQuestionByAgent, setPendingQuestionByAgent] = useState<Record<string, QuestionRequest | null>>({});
  const [questionResponding, setQuestionResponding] = useState(false);

  // Followup suggestions
  const [followupSuggestionsByAgent, setFollowupSuggestionsByAgent] = useState<Record<string, { id: string; text: string }[]>>({});
  const [followupSending, setFollowupSending] = useState<string | undefined>(undefined);

  // Chat session persistence state
  const [chatSessions, setChatSessions] = useState<ChatSessionInfo[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeMemoryRecords, setActiveMemoryRecords] = useState<MemoryRecordInfo[]>([]);
  const [agentMemoryRecords, setAgentMemoryRecords] = useState<MemoryRecordInfo[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");
  const [sessionDirty, setSessionDirty] = useState(false);
  const [sessionSaving, setSessionSaving] = useState(false);
  const [lastSessionSaveAt, setLastSessionSaveAt] = useState<string | null>(null);
  const savedMessageSignatureRef = useRef<string>("[]");
  const sessionListRequestIdRef = useRef(0);

  const threadIdsRef = useRef<Record<string, string>>({});
  const pendingRequestRef = useRef<Record<string, InvokePayload | null>>({});
  const streamAbortByAgentRef = useRef<Record<string, AbortController>>({});

  // ── Derived ──

  const isSending = selectedAgentName ? isSendingByAgent[selectedAgentName] ?? false : false;

  // ── Derived ──

  const messages = selectedAgentName ? messagesByAgent[selectedAgentName] ?? [] : [];
  const activity = selectedAgentName ? activityByAgent[selectedAgentName] ?? [] : [];
  const summary = selectedAgentName ? summaryByAgent[selectedAgentName] ?? null : null;
  const todos = selectedAgentName ? todosByAgent[selectedAgentName] ?? [] : [];
  const phase: "plan" | "build" | "idle" = selectedAgentName ? phaseByAgent[selectedAgentName] ?? "idle" : "idle";
  const logs = selectedAgentName ? logsByAgent[selectedAgentName] ?? "" : "";
  const pendingQuestion = selectedAgentName ? pendingQuestionByAgent[selectedAgentName] ?? null : null;
  const followupSuggestions = selectedAgentName ? followupSuggestionsByAgent[selectedAgentName] ?? [] : [];
  const selectedOpenCodeChatSettings = selectedAgentName
    ? opencodeChatSettingsByAgent[selectedAgentName] ?? DEFAULT_OPENCODE_CHAT_SETTINGS
    : DEFAULT_OPENCODE_CHAT_SETTINGS;
  const selectedFactoryMode = selectedAgentName
    ? factoryModeByAgent[selectedAgentName] ?? DEFAULT_FACTORY_MODE
    : DEFAULT_FACTORY_MODE;
  const approvalSupported = selectedRuntimeKind === "opencode";
  const specialistTeamConfigured = hasSpecialistTeamEntries(specialistSubagents);
  const canSubmitChat = Boolean(prompt.trim());
  const chatEmptyMessage = selectedAgentName
    ? "Run chat requests or explicit A2A delegations from this workspace. Streaming is enabled by default."
    : "Select an agent from the catalog or create a new one to start an invocation.";
  const lastUserPrompt = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      const message = messages[index];
      if (message?.role !== "user") continue;
      const content = message.content.trim();
      if (content) return content;
    }
    return null;
  }, [messages]);
  const selectedWorkflowApprovalName = typeof selectedWorkflow?.pending_approval?.name === "string"
    ? selectedWorkflow.pending_approval.name
    : undefined;
  const activeSessionSummary = useMemo(() => {
    if (!activeSessionId) return null;
    return chatSessions.find((session) => session.session_id === activeSessionId)?.summary ?? null;
  }, [activeSessionId, chatSessions]);

  const reloadChatSessions = useCallback(async (
    agentName: string,
    options: { clearOnError?: boolean } = {},
  ): Promise<ChatSessionInfo[]> => {
    if (!token.trim() || !agentName) return [];
    const { clearOnError = true } = options;
    const requestId = ++sessionListRequestIdRef.current;
    setSessionsLoading(true);
    try {
      const sessions = await listChatSessions(token, namespace, agentName);
      if (sessionListRequestIdRef.current === requestId) {
        setChatSessions(sessions);
      }
      return sessions;
    } catch (err) {
      if (clearOnError && sessionListRequestIdRef.current === requestId) {
        setChatSessions([]);
      }
      throw err;
    } finally {
      if (sessionListRequestIdRef.current === requestId) {
        setSessionsLoading(false);
      }
    }
  }, [namespace, token]);

  const handlePromoteMemoryRecord = useCallback(async (recordId: number, promoted: boolean) => {
    if (!token.trim()) return;
    try {
      const updated = await updateMemoryRecord(token, recordId, { promoted });
      setActiveMemoryRecords((prev) => prev.map((record) => record.id === recordId ? updated : record));
      setAgentMemoryRecords((prev) => prev.map((record) => record.id === recordId ? updated : record));
    } catch (err) {
      setChatError(apiErrorMessage(err));
    }
  }, [token]);

  const handleEditMemoryRecord = useCallback(async (recordId: number, patch: { topic?: string; content?: string; promoted?: boolean }) => {
    if (!token.trim()) return;
    try {
      const updated = await updateMemoryRecord(token, recordId, patch);
      setActiveMemoryRecords((prev) => prev.map((record) => record.id === recordId ? updated : record));
      setAgentMemoryRecords((prev) => prev.map((record) => record.id === recordId ? updated : record));
    } catch (err) {
      setChatError(apiErrorMessage(err));
    }
  }, [token]);

  const handleDeleteMemoryRecord = useCallback(async (recordId: number) => {
    if (!token.trim()) return;
    try {
      await deleteMemoryRecord(token, recordId);
      setActiveMemoryRecords((prev) => prev.filter((record) => record.id !== recordId));
      setAgentMemoryRecords((prev) => prev.filter((record) => record.id !== recordId));
    } catch (err) {
      setChatError(apiErrorMessage(err));
    }
  }, [token]);

  useEffect(() => {
    if (!token.trim() || !selectedAgentName) {
      setAgentMemoryRecords([]);
      return;
    }
    let cancelled = false;
    void listAgentMemory(token, namespace, selectedAgentName)
      .then((records) => {
        if (!cancelled) setAgentMemoryRecords(records);
      })
      .catch(() => {
        if (!cancelled) setAgentMemoryRecords([]);
      });
    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName]);

  useEffect(() => {
    if (!token.trim() || !selectedAgentName || !activeSessionId) {
      setActiveMemoryRecords([]);
      return;
    }
    let cancelled = false;
    void listAgentMemory(token, namespace, selectedAgentName, activeSessionId)
      .then((records) => {
        if (!cancelled) setActiveMemoryRecords(records);
      })
      .catch(() => {
        if (!cancelled) setActiveMemoryRecords([]);
      });
    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName, activeSessionId]);

  // ── Effects ──

  useEffect(() => {
    if (!approvalSupported && requireApproval) setRequireApproval(false);
  }, [approvalSupported, requireApproval]);

  useEffect(() => {
    setA2ATargetAgent(""); setA2ATargetNamespace(""); setA2ATimeoutSeconds("");
    setSpecialistSubagents([]); setSubagentStrategy("sequential");
    setApprovalReason("");
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

  function setTodosForAgent(agentName: string, updater: UiTodo[] | ((current: UiTodo[]) => UiTodo[])) {
    setTodosByAgent((prev) => {
      const current = prev[agentName] ?? [];
      const next = typeof updater === "function" ? (updater as (current: UiTodo[]) => UiTodo[])(current) : updater;
      return { ...prev, [agentName]: next };
    });
  }

  function setLogsForAgent(agentName: string, value: string | ((prev: string) => string)) {
    setLogsByAgent((prev) => {
      const current = prev[agentName] ?? "";
      const next = typeof value === "function" ? value(current) : value;
      return { ...prev, [agentName]: next };
    });
  }

  function setOpenCodeChatSettingsForAgent(agentName: string, updater: (current: OpenCodeChatSettings) => OpenCodeChatSettings) {
    setOpenCodeChatSettingsByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? DEFAULT_OPENCODE_CHAT_SETTINGS) }));
  }

  function setFactoryModeForAgent(agentName: string, updater: (current: FactoryMode) => FactoryMode) {
    setFactoryModeByAgent((prev) => ({ ...prev, [agentName]: updater(prev[agentName] ?? DEFAULT_FACTORY_MODE) }));
  }

  function resetLiveChatState(agentName: string) {
    const ctrl = streamAbortByAgentRef.current[agentName];
    if (ctrl) {
      ctrl.abort();
      delete streamAbortByAgentRef.current[agentName];
    }
    delete threadIdsRef.current[agentName];
    delete pendingRequestRef.current[agentName];
    setActivityForAgent(agentName, () => []);
    setSummaryForAgent(agentName, () => null);
    setTodosForAgent(agentName, []);
    setPhaseByAgent((prev) => ({ ...prev, [agentName]: "idle" }));
    setPendingQuestionByAgent((prev) => ({ ...prev, [agentName]: null }));
    setFollowupSuggestionsByAgent((prev) => ({ ...prev, [agentName]: [] }));
    setIsSendingByAgent((prev) => ({ ...prev, [agentName]: false }));
  }

  const removeAgentChatState = useCallback((agentName: string) => {
    setMessagesByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setActivityByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setSummaryByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setTodosByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setPhaseByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setLogsByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setPendingQuestionByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setFollowupSuggestionsByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setOpenCodeChatSettingsByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setFactoryModeByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    setIsSendingByAgent((prev) => { const n = { ...prev }; delete n[agentName]; return n; });
    const ctrl = streamAbortByAgentRef.current[agentName];
    if (ctrl) { ctrl.abort(); delete streamAbortByAgentRef.current[agentName]; }
    delete threadIdsRef.current[agentName];
    delete pendingRequestRef.current[agentName];
  }, []);

  // ── Internal helpers ──

  function pushActivity(agentName: string, event: string, payload: Record<string, unknown>) {
    if (event === "response.delta") return;
    if (event === "response.reasoning") return;
    // Skip unnamed/empty SSE events (keepalives parsed as "message" with no data)
    if (event === "message" && Object.keys(payload).length === 0) return;
    setActivityForAgent(agentName, (cur) => {
      const nextEntry = { id: createId(), event, payload, timestamp: new Date().toISOString() };
      if (event === "todo.updated" && cur[0]?.event === "todo.updated") {
        return [nextEntry, ...cur.slice(1)].slice(0, 200);
      }
      return [nextEntry, ...cur].slice(0, 200);
    });
  }

  function setPendingAssistantContent(agentName: string, messageId: string, content: string, status: UiMessage["status"]) {
    setMessagesForAgent(agentName, (cur) => cur.map((m) => m.id === messageId ? { ...m, content, status } : m));
  }

  function applyInvocationFailure(agentName: string, messageId: string, message: string) {
    const nextMessage = sanitizeErrorMessage(message, "Agent invocation failed.");
    pendingRequestRef.current[agentName] = null;
    setPendingAssistantContent(agentName, messageId, nextMessage, "error");
    setChatError(nextMessage);
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
    setIsSendingByAgent((prev) => ({ ...prev, [agentName]: true }));

    const applyInvokeSuccess = (result: Awaited<ReturnType<typeof invokeAgent>>) => {
      const nextSummary = updateSummary(agentName, result.thread_id, result);
      setTodosForAgent(agentName, nextSummary.todos ?? []);
      threadIdsRef.current[agentName] = nextSummary.threadId;
      pendingRequestRef.current[agentName] = nextSummary.status === "approval_pending" ? { ...payload, thread_id: nextSummary.threadId } : null;
      setMessagesForAgent(agentName, (cur) => cur.map((m) => (
        m.id === assistantMessageId
          ? finalizeAssistantMessage(
              m,
              nextSummary,
              result.response || (nextSummary.status === "approval_pending" ? "Approval pending. Re-submit after approval." : "No response body returned."),
            )
          : m
      )));
    };

    if (!streamMode) {
      try {
        const result = await invokeAgent(token, namespace, agentName, payload, requestId);
        applyInvokeSuccess(result);
      } catch (err) {
        applyInvocationFailure(agentName, assistantMessageId, apiErrorMessage(err));
      } finally { setIsSendingByAgent((prev) => ({ ...prev, [agentName]: false })); }
      return;
    }

    const abortController = new AbortController();
    const previousController = streamAbortByAgentRef.current[agentName];
    streamAbortByAgentRef.current[agentName] = abortController;
    previousController?.abort();
    let streamFailure: Error | null = null;
    let streamProducedOutput = false;

    try {
      await streamAgentInvoke({
        signal: abortController.signal, token, namespace, agentName, payload, requestId,
        onEvent: ({ event, payload: ep }) => {
          pushActivity(agentName, event, ep);
          const TOOL_NODES = new Set(["sandbox_tool", "mcp_tool", "retrieval", "output_guard"]);

          if (event === "response.started") {
            if (typeof ep.thread_id === "string" && ep.thread_id.trim()) {
              threadIdsRef.current[agentName] = ep.thread_id.trim();
            }
            return;
          }

          if (event === "response.turn_started") {
            const agent = String(ep.agent ?? "").toLowerCase();
            setPhaseByAgent((prev) => ({ ...prev, [agentName]: agent === "plan" ? "plan" : "build" }));
            return;
          }

          if (event === "graph.node") {
            const nodeName = String(ep.node ?? "");
            if (TOOL_NODES.has(nodeName)) {
              streamProducedOutput = true;
            }
            return;
          }

          if (event === "mcp.result") {
            streamProducedOutput = true;
            return;
          }

          if (event === "subagent.call") {
            streamProducedOutput = true;
            return;
          }

          if (event === "response.delta") {
            if (typeof ep.delta !== "string") throw new Error("response.delta events must include a string delta field.");
            streamProducedOutput = true;
            const delta = ep.delta;
            setMessagesForAgent(agentName, (cur) => cur.map((m) => {
              if (m.id !== assistantMessageId) return m;
              const nextContent = delta.startsWith(m.content)
                ? delta
                : m.content.startsWith(delta)
                  ? m.content
                  : `${m.content}${delta}`;
              return { ...m, content: nextContent, status: "streaming" };
            }));
            return;
          }

          if (event === "response.reasoning") {
            if (typeof ep.reasoning !== "string") return;
            streamProducedOutput = true;
            const reasoning = ep.reasoning;
            setMessagesForAgent(agentName, (cur) => cur.map((m) => {
              if (m.id !== assistantMessageId) return m;
              const currentReasoning = m.reasoning ?? "";
              const nextReasoning = reasoning.startsWith(currentReasoning)
                ? reasoning
                : currentReasoning.startsWith(reasoning)
                  ? currentReasoning
                  : currentReasoning
                    ? `${currentReasoning}\n${reasoning}`
                    : reasoning;
              return { ...m, reasoning: nextReasoning, status: "streaming" };
            }));
            return;
          }

          if (event === "response.completed") {
            streamProducedOutput = true;
            const fallbackThread = threadIdsRef.current[agentName] || `thread-${agentName}-${createId()}`;
            const nextSummary = updateSummary(agentName, fallbackThread, ep);
            setTodosForAgent(agentName, nextSummary.todos ?? []);
            threadIdsRef.current[agentName] = nextSummary.threadId;
            pendingRequestRef.current[agentName] = nextSummary.status === "approval_pending" ? { ...payload, thread_id: nextSummary.threadId } : null;
            setMessagesForAgent(agentName, (cur) => cur.map((m) => (
              m.id === assistantMessageId
                ? finalizeAssistantMessage(
                    m,
                    nextSummary,
                    nextSummary.status === "approval_pending" ? "Approval pending. Re-submit after approval." : "Invocation completed.",
                  )
                : m
            )));
            return;
          }

          if (event === "response.tool_call") {
            streamProducedOutput = true;
            const tool = String(ep.tool ?? "");
            const status = normalizeToolCallStatus(String(ep.status ?? "unknown"));
            const input = ep.input;
            const output = typeof ep.output === "string" ? ep.output : "";
            setMessagesForAgent(agentName, (cur) => cur.map((m) => {
              if (m.id !== assistantMessageId) return m;
              const tc = { tool, status, input, output };
              return { ...m, toolCalls: [...(m.toolCalls ?? []), tc] };
            }));
            return;
          }

          if (event === "response.patch") {
            const files = Array.isArray(ep.files) ? (ep.files as string[]) : [];
            if (files.length > 0) {
              streamProducedOutput = true;
              setMessagesForAgent(agentName, (cur) => cur.map((m) => {
                if (m.id !== assistantMessageId) return m;
                return { ...m, patches: [...(m.patches ?? []), { files }] };
              }));
            }
            return;
          }

          if (event === "todo.updated") {
            streamProducedOutput = true;
            setTodosForAgent(agentName, normalizeUiTodos(ep.todos));
            return;
          }

          if (event === "question.asked") {
            streamProducedOutput = true;
            const questionRequest = normalizeQuestionRequest(ep);
            if (questionRequest) {
              // Auto-reply when in autonomous mode
              if (selectedOpenCodeChatSettings.autonomous) {
                const autoAnswers = questionRequest.questions.map((q) => {
                  if (q.options.length > 0) return [q.options[0].label];
                  return ["yes"];
                });
                void replyToQuestion(token, namespace, agentName, questionRequest.id, autoAnswers).catch(() => {});
              } else {
                setPendingQuestionByAgent((prev) => ({ ...prev, [agentName]: questionRequest }));
              }
            }
            return;
          }

          if (event === "response.error") {
            if (typeof ep.error !== "string" || !ep.error.trim()) throw new Error(`${event} events must include a non-empty string error field.`);
            streamFailure = new Error(sanitizeErrorMessage(ep.error, "Agent invocation failed."));
            throw streamFailure;
          }
        },
        onError: (err) => { streamFailure = err instanceof Error ? err : new Error(String(err)); },
        onClose: () => undefined,
      });
    } catch (err) {
      if (!abortController.signal.aborted) {
        let failure = streamFailure ?? (err instanceof Error ? err : new Error(String(err)));
        let recovered = false;

        if (!streamProducedOutput) {
          try {
            const fallbackResult = await invokeAgent(token, namespace, agentName, payload, createId());
            applyInvokeSuccess(fallbackResult);
            recovered = true;
          } catch (fallbackErr) {
            failure = fallbackErr instanceof Error ? fallbackErr : new Error(String(fallbackErr));
          }
        }

        if (!recovered) {
          applyInvocationFailure(agentName, assistantMessageId, apiErrorMessage(failure));
        }
      }
    } finally {
      setIsSendingByAgent((prev) => ({ ...prev, [agentName]: false }));
      setPhaseByAgent((prev) => ({ ...prev, [agentName]: "idle" }));
      if (streamAbortByAgentRef.current[agentName] === abortController) {
        delete streamAbortByAgentRef.current[agentName];
      }
    }
  }

  // ── prompt submission helpers ──

  const buildInvokePayload = useCallback((agentName: string, promptText: string): InvokePayload | null => {
    const nextPrompt = promptText.trim();
    let opencodeMaxTurns: number | undefined;
    let opencodeWorkingDirectory: string | undefined;
    let explicitA2ATimeoutSeconds: number | undefined;

    try {
      opencodeMaxTurns = parseOpenCodeMaxTurns(selectedOpenCodeChatSettings.maxTurns);
      opencodeWorkingDirectory = normalizeOpenCodeWorkingDirectory(selectedOpenCodeChatSettings.workingDirectory);
    } catch (err) { setChatError(apiErrorMessage(err)); return null; }
    try { explicitA2ATimeoutSeconds = parseA2ATimeoutSeconds(a2aTimeoutSeconds); }
    catch (err) { setChatError(apiErrorMessage(err)); return null; }

    const normA2AAgent = a2aTargetAgent.trim();
    const normA2ANs = a2aTargetNamespace.trim();
    const hasExplicitA2A = normA2AAgent.length > 0 || normA2ANs.length > 0;
    if (specialistTeamConfigured) {
      setChatError("OpenCode agents do not support specialist-team orchestration.");
      return null;
    }
    if (hasExplicitA2A) {
      if (!normA2AAgent || !normA2ANs) { setChatError("Provide both an A2A target namespace and an A2A target agent."); return null; }
      if (!isValidK8sName(normA2AAgent)) { setChatError("A2A target agent must be a valid lowercase Kubernetes name."); return null; }
      if (!isValidK8sName(normA2ANs)) { setChatError("A2A target namespace must be a valid lowercase Kubernetes name."); return null; }
    }
    if (!nextPrompt) { setChatError("Enter a prompt before sending a chat request."); return null; }

    return {
      prompt: nextPrompt, thread_id: threadIdsRef.current[agentName], require_approval: requireApproval,
      approval_action: requireApproval ? `Approve UI request for ${agentName}` : undefined,
      a2a_target_agent: hasExplicitA2A ? normA2AAgent : undefined, a2a_target_namespace: hasExplicitA2A ? normA2ANs : undefined,
      a2a_timeout_seconds: explicitA2ATimeoutSeconds,
      max_turns: opencodeMaxTurns,
      working_directory: opencodeWorkingDirectory,
      output_format: selectedOpenCodeChatSettings.outputFormat || undefined,
      autonomous: selectedOpenCodeChatSettings.autonomous,
      factory_mode: isFactoryAgentName(agentName) ? selectedFactoryMode : undefined,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOpenCodeChatSettings, selectedFactoryMode, a2aTimeoutSeconds, a2aTargetAgent, a2aTargetNamespace, specialistTeamConfigured, requireApproval]);

  const submitPromptText = useCallback(async (promptText: string, options: PromptSubmissionOptions = {}) => {
    if (!token.trim()) { setChatError("Enter the gateway token before sending chat requests."); return; }
    if (!selectedAgentName) return;

    const nextPrompt = promptText.trim();
    const payload = buildInvokePayload(selectedAgentName, nextPrompt);
    if (!payload) return;

    if (options.clearComposer !== false) {
      setPrompt("");
    }

    await runInvocation({
      agentName: selectedAgentName,
      payload,
      userPrompt: nextPrompt,
      appendUserMessage: options.appendUserMessage ?? true,
      systemNotice: options.systemNotice,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, selectedAgentName, buildInvokePayload]);

  // ── handleSubmit ──

  const handleSubmit = useCallback(async () => {
    if (!selectedAgentName || !canSubmitChat) return;
    await submitPromptText(prompt, { clearComposer: true });
  }, [selectedAgentName, canSubmitChat, prompt, submitPromptText]);

  const handleReusePrompt = useCallback((text: string) => {
    setChatError("");
    setPrompt(text);
  }, []);

  const handleRegeneratePrompt = useCallback(async (text?: string) => {
    const nextPrompt = String(text ?? lastUserPrompt ?? "").trim();
    if (!nextPrompt) {
      setChatError("No previous prompt is available to regenerate.");
      return;
    }
    await submitPromptText(nextPrompt, {
      appendUserMessage: false,
      clearComposer: false,
      systemNotice: "Regenerating a prior prompt in the current session.",
    });
  }, [lastUserPrompt, submitPromptText]);

  // ── handleLoadLogs ──

  const handleLoadLogs = useCallback(async () => {
    if (!token.trim() || !selectedAgentName) return;
    setLogsLoading(true); setWorkspaceError("");
    try {
      const result = await fetchAgentLogs(token, namespace, selectedAgentName, 500);
      setLogsForAgent(selectedAgentName, result.logs);
    } catch (err) { setWorkspaceError(apiErrorMessage(err)); }
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
    let errorHandled = false;

    setWorkspaceError("");

    streamAgentLogs({
      signal: abortController.signal,
      token,
      namespace,
      agentName,
      tail: 100,
      onStarted: (info) => {
        // Mark streaming only after connection succeeds
        setLogsStreaming(true);
        setLogsForAgent(agentName, `── streaming logs from pod ${info.pod_name} ──\n`);
      },
      onLine: (line) => {
        setLogsForAgent(agentName, (prev) => prev + line + "\n");
      },
      onError: (error) => {
        errorHandled = true;
        if (!abortController.signal.aborted) {
          setWorkspaceError(`Log stream error: ${error.message}`);
        }
        setLogsStreaming(false);
        logStreamAbortRef.current = null;
      },
      onStopped: () => {
        if (!errorHandled) {
          setLogsStreaming(false);
          logStreamAbortRef.current = null;
        }
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
    } catch (err) { setWorkspaceError(apiErrorMessage(err)); }
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
    } catch (err) { setWorkspaceError(apiErrorMessage(err)); }
    finally { setApprovalBusy(false); }
  }, [token, namespace, selectedWorkflowApprovalName, approvalReason, refreshWorkspaceData, setWorkspaceError]);

  // ── Question handlers ──

  const handleQuestionReply = useCallback(async (requestId: string, answers: string[][]) => {
    if (!token.trim() || !selectedAgentName) return;
    const agentName = selectedAgentName;
    setQuestionResponding(true);
    try {
      await replyToQuestion(token, namespace, agentName, requestId, answers);
      setPendingQuestionByAgent((prev) => ({ ...prev, [agentName]: null }));
      // Show answer as user message
      const answerText = answers.map((a) => a.join(", ")).join(" | ");
      setMessagesForAgent(agentName, (cur) => [...cur, {
        id: createId(), role: "user" as const, content: answerText, status: "complete" as const,
      }]);
    } catch (err) { setChatError(apiErrorMessage(err)); }
    finally { setQuestionResponding(false); }
  }, [token, namespace, selectedAgentName]);

  const handleQuestionReject = useCallback(async (requestId: string) => {
    if (!token.trim() || !selectedAgentName) return;
    const agentName = selectedAgentName;
    setQuestionResponding(true);
    try {
      await rejectQuestion(token, namespace, agentName, requestId);
      setPendingQuestionByAgent((prev) => ({ ...prev, [agentName]: null }));
    } catch (err) { setChatError(apiErrorMessage(err)); }
    finally { setQuestionResponding(false); }
  }, [token, namespace, selectedAgentName]);

  // ── Followup suggestion handlers ──

  const handleFollowupSend = useCallback(async (id: string) => {
    if (!selectedAgentName) return;
    const suggestions = followupSuggestionsByAgent[selectedAgentName] ?? [];
    const suggestion = suggestions.find((s) => s.id === id);
    if (!suggestion) return;
    setFollowupSending(id);
    try {
      await submitPromptText(suggestion.text, { clearComposer: true });
      setFollowupSuggestionsByAgent((prev) => ({ ...prev, [selectedAgentName]: [] }));
    } finally {
      setFollowupSending(undefined);
    }
  }, [selectedAgentName, followupSuggestionsByAgent, submitPromptText]);

  const handleFollowupEdit = useCallback((id: string) => {
    const suggestions = selectedAgentName ? followupSuggestionsByAgent[selectedAgentName] ?? [] : [];
    const suggestion = suggestions.find((s) => s.id === id);
    if (!suggestion) return;
    handleReusePrompt(suggestion.text);
    setFollowupSuggestionsByAgent((prev) => {
      if (!selectedAgentName) return prev;
      return { ...prev, [selectedAgentName]: [] };
    });
  }, [selectedAgentName, followupSuggestionsByAgent, handleReusePrompt]);

  // ── Generate followup suggestions from completed responses ──
  useEffect(() => {
    if (!selectedAgentName || isSending) return;
    if (!messages.length) return;
    const lastMsg = messages[messages.length - 1];
    if (lastMsg.role !== "assistant" || lastMsg.status !== "complete") return;
    // Extract questions or action items from the response
    const content = lastMsg.content;
    const suggestions: { id: string; text: string }[] = [];
    // Detect questions at end of response
    const lines = content.split("\n").filter((l) => l.trim());
    const lastLines = lines.slice(-8);
    for (const line of lastLines) {
      const trimmed = line.trim();
      // Pattern: numbered/bulleted list items, or **bold:** prefixed options
      const match = trimmed.match(/^(?:\d+[.)]\s*|-\s*|\*\s*)(?:\*{1,2})?(.{5,120})$/);
      if (match) {
        const text = match[1].replace(/\*{1,2}/g, "").replace(/^:\s*/, "").replace(/[`]/g, "").trim();
        if (text.length >= 5) {
          suggestions.push({ id: createId(), text });
        }
      }
    }
    // Also detect if the response ends with a question
    if (suggestions.length === 0 && lastLines.length > 0) {
      const lastLine = lastLines[lastLines.length - 1].trim();
      if (lastLine.endsWith("?") && lastLine.length > 15 && lastLine.length < 200) {
        suggestions.push({ id: createId(), text: "Yes" });
        suggestions.push({ id: createId(), text: "No" });
        suggestions.push({ id: createId(), text: "Tell me more" });
      }
    }
    if (suggestions.length > 0) {
      setFollowupSuggestionsByAgent((prev) => ({ ...prev, [selectedAgentName]: suggestions.slice(0, 6) }));
    }
  }, [selectedAgentName, messages, isSending]);

  // ── cancelStream ──

  const cancelStream = useCallback(() => {
    if (!selectedAgentName) return;
    const controller = streamAbortByAgentRef.current[selectedAgentName];
    if (controller) {
      controller.abort();
      delete streamAbortByAgentRef.current[selectedAgentName];
    }
    setIsSendingByAgent((prev) => ({ ...prev, [selectedAgentName]: false }));
    setMessagesForAgent(selectedAgentName, (cur) =>
      cur.map((m) => m.status === "streaming" ? { ...m, status: "complete" as const, content: m.content || (m.role === "tool" ? "(cancelled)" : "(cancelled)") } : m)
    );
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
  const setSelectedFactoryMode = useCallback((value: FactoryMode) => {
    if (!selectedAgentName) return;
    setChatError("");
    setFactoryModeForAgent(selectedAgentName, () => value);
  }, [selectedAgentName]);

  // ── Chat session persistence ──

  // Load sessions list when agent changes
  useEffect(() => {
    if (!token.trim() || !selectedAgentName) {
      sessionListRequestIdRef.current += 1;
      setChatSessions([]);
      setActiveSessionId(null);
      setSessionSearch("");
      setSessionsLoading(false);
      return;
    }
    void reloadChatSessions(selectedAgentName).catch(() => {});
  }, [reloadChatSessions, selectedAgentName, token]);

  useEffect(() => {
    if (!activeSessionId) {
      setSessionDirty(false);
      return;
    }
    setSessionDirty(buildMessageSignature(messages) !== savedMessageSignatureRef.current);
  }, [messages, activeSessionId]);

  useEffect(() => {
    if (!token.trim() || !selectedAgentName || selectedRuntimeKind !== "opencode") return;
    const threadId = threadIdsRef.current[selectedAgentName] || summary?.threadId;
    if (!threadId) return;
    let cancelled = false;
    void fetchAgentTodos(token, namespace, selectedAgentName, threadId)
      .then((next) => {
        if (!cancelled) setTodosForAgent(selectedAgentName, normalizeUiTodos(next));
      })
      .catch(() => {
        if (!cancelled && summary?.todos) {
          setTodosForAgent(selectedAgentName, summary.todos);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, namespace, selectedAgentName, selectedRuntimeKind, summary?.threadId, summary?.todos]);

  // Background todo polling with ETag when idle (not streaming)
  useEffect(() => {
    if (isSending || !token.trim() || !selectedAgentName || selectedRuntimeKind !== "opencode") return;
    const threadId = threadIdsRef.current[selectedAgentName] || summary?.threadId;
    if (!threadId) return;
    let cancelled = false;
    let etag: string | undefined;
    const poll = async () => {
      try {
        const result = await pollAgentTodos(token, namespace, selectedAgentName, threadId, etag);
        if (cancelled) return;
        if (result) {
          etag = result.etag ?? undefined;
          setTodosForAgent(selectedAgentName, normalizeUiTodos(result.todos));
        }
      } catch { /* ignore polling errors */ }
    };
    const interval = setInterval(poll, 3000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [isSending, token, namespace, selectedAgentName, selectedRuntimeKind, summary?.threadId]);

  useEffect(() => {
    if (!selectedAgentName) return;
    if (!token.trim() || selectedRuntimeKind !== "opencode") {
      setPendingQuestionByAgent((prev) => {
        if ((prev[selectedAgentName] ?? null) === null) return prev;
        return { ...prev, [selectedAgentName]: null };
      });
      return;
    }

    let cancelled = false;
    const syncPendingQuestion = async () => {
      try {
        const pending = await fetchPendingQuestions(token, namespace, selectedAgentName);
        if (cancelled) return;

        let nextQuestion: QuestionRequest | null = null;
        for (const item of pending) {
          const normalized = normalizeQuestionRequest(item);
          if (normalized) {
            nextQuestion = normalized;
            break;
          }
        }

        setPendingQuestionByAgent((prev) => {
          const current = prev[selectedAgentName] ?? null;
          if ((current?.id ?? "") === (nextQuestion?.id ?? "")) return prev;
          return { ...prev, [selectedAgentName]: nextQuestion };
        });
      } catch {
        // Keep the current question state when the recovery probe fails.
      }
    };

    void syncPendingQuestion();
    if (isSending) {
      return () => {
        cancelled = true;
      };
    }

    const interval = setInterval(() => {
      void syncPendingQuestion();
    }, 4000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [isSending, token, namespace, selectedAgentName, selectedRuntimeKind]);

  const handleNewSession = useCallback(async () => {
    if (!token.trim() || !selectedAgentName) return;
    try {
      const title = "New Chat";
      const session = await createChatSession(token, namespace, selectedAgentName, title);
      resetLiveChatState(selectedAgentName);
      setMessagesForAgent(selectedAgentName, () => []);
      savedMessageSignatureRef.current = "[]";
      setActiveSessionId(session.session_id);
      setLastSessionSaveAt(session.updated_at ?? new Date().toISOString());
      setSessionDirty(false);
      setChatSessions((prev) => upsertChatSession(prev, session));
      void reloadChatSessions(selectedAgentName, { clearOnError: false }).catch(() => {});
    } catch (err) { setChatError(apiErrorMessage(err)); }
  }, [namespace, reloadChatSessions, selectedAgentName, setMessagesForAgent, token]);

  const handleLoadSession = useCallback(async (sessionId: string) => {
    if (!token.trim() || !selectedAgentName) return;
    try {
      const msgs = await getChatSessionMessages(token, sessionId);
      resetLiveChatState(selectedAgentName);
      setMessagesForAgent(selectedAgentName, () =>
        msgs.map((m) => ({
          id: m.message_id,
          role: m.role as UiMessage["role"],
          content: m.content,
          status: normalizePersistedMessageStatus(m.status as UiMessage["status"]),
          toolName: m.tool_name ?? undefined, toolNode: m.tool_node ?? undefined,
        })),
      );
      savedMessageSignatureRef.current = buildMessageSignature(msgs.map((m) => ({
        id: m.message_id,
        role: m.role as UiMessage["role"],
        content: m.content,
        status: normalizePersistedMessageStatus(m.status as UiMessage["status"]),
        toolName: m.tool_name ?? undefined,
        toolNode: m.tool_node ?? undefined,
      })));
      setActiveSessionId(sessionId);
      setLastSessionSaveAt(chatSessions.find((session) => session.session_id === sessionId)?.updated_at ?? new Date().toISOString());
      setSessionDirty(false);
      setChatError("");
    } catch (err) { setChatError(apiErrorMessage(err)); }
  }, [token, selectedAgentName, setMessagesForAgent, chatSessions]);

  const handleDeleteSession = useCallback(async (sessionId: string) => {
    if (!token.trim()) return;
    try {
      await deleteChatSession(token, sessionId);
      setChatSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (activeSessionId === sessionId) setActiveSessionId(null);
    } catch (err) { setChatError(apiErrorMessage(err)); }
  }, [token, activeSessionId]);

  const handleRenameSession = useCallback(async (sessionId: string, title: string) => {
    if (!token.trim()) return;
    try {
      const updated = await updateChatSessionTitle(token, sessionId, title);
      setChatSessions((prev) => prev.map((s) => s.session_id === sessionId ? { ...s, ...updated } : s));
    } catch (err) { setChatError(apiErrorMessage(err)); }
  }, [token]);

  const handleSaveCurrentSession = useCallback(async () => {
    if (!token.trim() || !activeSessionId || !selectedAgentName) return;
    try {
      setSessionSaving(true);
      await saveChatSessionMessages(token, activeSessionId, messages.map((m) => ({
        message_id: m.id,
        role: m.role,
        content: m.content,
        status: normalizePersistedMessageStatus(m.status),
        toolName: m.toolName,
        toolNode: m.toolNode,
      })));
      savedMessageSignatureRef.current = buildMessageSignature(messages);
      const savedAt = new Date().toISOString();
      setLastSessionSaveAt(savedAt);
      setSessionDirty(false);
      setChatSessions((prev) => prev.map((session) => (
        session.session_id === activeSessionId
          ? { ...session, updated_at: savedAt }
          : session
      )));
      await reloadChatSessions(selectedAgentName, { clearOnError: false });
    } catch (err) { setChatError(apiErrorMessage(err)); }
    finally {
      setSessionSaving(false);
    }
  }, [activeSessionId, messages, reloadChatSessions, selectedAgentName, token]);

  // Auto-save after each invocation completes (isSending true → false)
  const prevSendingRef = useRef(false);
  const saveRef = useRef(handleSaveCurrentSession);
  const newSessionRef = useRef(handleNewSession);
  saveRef.current = handleSaveCurrentSession;
  newSessionRef.current = handleNewSession;

  useEffect(() => {
    if (prevSendingRef.current && !isSending) {
      if (activeSessionId) {
        void saveRef.current();
      } else if (token.trim() && selectedAgentName && messages.length > 0) {
        // Create session and save without clearing messages
        void (async () => {
          try {
            const title = messages.find((m) => m.role === "user")?.content?.slice(0, 80) || "New Chat";
            const session = await createChatSession(token, namespace, selectedAgentName, title);
            setActiveSessionId(session.session_id);
            setChatSessions((prev) => upsertChatSession(prev, session));
            await saveChatSessionMessages(token, session.session_id, messages.map((m) => ({
              message_id: m.id,
              role: m.role,
              content: m.content,
              status: normalizePersistedMessageStatus(m.status),
              toolName: m.toolName,
              toolNode: m.toolNode,
            })));
            savedMessageSignatureRef.current = buildMessageSignature(messages);
            const savedAt = new Date().toISOString();
            setLastSessionSaveAt(savedAt);
            setSessionDirty(false);
            await reloadChatSessions(selectedAgentName, { clearOnError: false });
          } catch (err) { setChatError(apiErrorMessage(err)); }
        })();
      }
    }
    prevSendingRef.current = isSending;
  }, [isSending, activeSessionId, token, namespace, reloadChatSessions, selectedAgentName, messages]);

  const ctxValue = useMemo(() => ({
    messages, activity, summary, todos, phase, logs, selectedOpenCodeChatSettings, selectedFactoryMode,
    prompt, streamMode, requireApproval, approvalSupported, chatError, isSending, logsLoading, logsStreaming, canSubmitChat, chatEmptyMessage,
    a2aTargetAgent, a2aTargetNamespace, a2aTimeoutSeconds,
    specialistSubagents, specialistTeamConfigured, subagentStrategy,
    approvalReason, approvalBusy, selectedWorkflowApprovalName,
    lastUserPrompt,
    setPrompt, setStreamMode, setRequireApproval, setChatError, setApprovalReason,
    setA2ATargetAgent, setA2ATargetNamespace, setA2ATimeoutSeconds, setSubagentStrategy,
    addSpecialistSubagent, updateSpecialistSubagent, removeSpecialistSubagent, clearSpecialistTeam,
    setOpenCodeOutputFormat, setOpenCodeAutonomous, setOpenCodeMaxTurns, setOpenCodeWorkingDirectory, setSelectedFactoryMode,
    pendingQuestion, questionResponding, handleQuestionReply, handleQuestionReject,
    followupSuggestions, followupSending, handleFollowupSend, handleFollowupEdit, handleReusePrompt, handleRegeneratePrompt,
    handleSubmit, handleLoadLogs, handleStreamLogs, handleStopLogStream, handleAgentApprovalDecision, handleWorkflowApprovalDecision, cancelStream,
    setMessagesForAgent, removeAgentChatState,
    chatSessions, activeSessionId, activeSessionSummary, activeMemoryRecords, agentMemoryRecords, sessionsLoading,
    sessionSearch, setSessionSearch, sessionDirty, sessionSaving, lastSessionSaveAt,
    handlePromoteMemoryRecord, handleEditMemoryRecord, handleDeleteMemoryRecord,
    handleNewSession, handleLoadSession, handleDeleteSession, handleRenameSession, handleSaveCurrentSession,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [
    messages, activity, summary, todos, phase, logs, selectedOpenCodeChatSettings, selectedFactoryMode,
    prompt, streamMode, requireApproval, approvalSupported, chatError, isSending, logsLoading, logsStreaming, canSubmitChat, chatEmptyMessage,
    a2aTargetAgent, a2aTargetNamespace, a2aTimeoutSeconds,
    specialistSubagents, specialistTeamConfigured, subagentStrategy,
    approvalReason, approvalBusy, selectedWorkflowApprovalName,
    pendingQuestion, questionResponding, followupSuggestions, followupSending, lastUserPrompt,
    chatSessions, activeSessionId, activeSessionSummary, activeMemoryRecords, agentMemoryRecords, sessionsLoading,
    sessionSearch, sessionDirty, sessionSaving, lastSessionSaveAt,
    handlePromoteMemoryRecord, handleEditMemoryRecord, handleDeleteMemoryRecord,
    handleReusePrompt, handleRegeneratePrompt,
    handleNewSession, handleLoadSession, handleDeleteSession, handleRenameSession, handleSaveCurrentSession, setSelectedFactoryMode,
  ]);

  return (
    <ChatContext.Provider value={ctxValue}>
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
