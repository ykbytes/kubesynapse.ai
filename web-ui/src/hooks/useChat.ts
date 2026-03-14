import { useCallback, useEffect, useRef, useState } from "react";
import { buildInvocationSummary, fetchAgentLogs, invokeAgent, streamAgentInvoke } from "@/lib/api";
import { isValidK8sName } from "@/lib/a2a";
import type {
  InvocationSummary,
  InvokePayload,
  InvokeSubagent,
  RuntimeKind,
  SpecialistSubagentDraft,
  UiActivity,
  UiMessage,
} from "@/types";

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

type GooseChatSettings = {
  maxTurns: string;
  workingDirectory: string;
};

const DEFAULT_GOOSE_CHAT_SETTINGS: GooseChatSettings = { maxTurns: "", workingDirectory: "" };

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
  return text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [pathPart, ...purposeParts] = line.split("|");
      const path = pathPart?.trim() ?? "";
      if (!path) throw new Error("Shared file entries must include a path.");
      const purpose = purposeParts.join("|").trim();
      return purpose ? { path, purpose } : { path };
    });
}

function normalizeGooseWorkingDirectory(value: string): string | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(trimmed)) throw new Error("Goose working directory must be workspace-relative.");
  const segments = trimmed.replace(/\\+/g, "/").split("/").filter((s) => s.length > 0);
  if (segments.length === 0) return undefined;
  if (segments.some((s) => s === "." || s === "..")) throw new Error("Use a workspace-relative path without '.' or '..' segments.");
  return segments.join("/");
}

export function hasSpecialistTeamEntries(items: SpecialistSubagentDraft[]): boolean {
  return items.some((i) => i.name.trim() || i.namespace.trim() || i.role.trim() || i.task.trim() || i.inputFilesText.trim() || i.resultFilePath.trim());
}

export function createSpecialistSubagentDraft(initial?: Partial<SpecialistSubagentDraft>): SpecialistSubagentDraft {
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

interface UseChatOptions {
  token: string;
  namespace: string;
  selectedAgentName: string;
  runtimeKind: RuntimeKind;
}

export function useChat({ token, namespace, selectedAgentName, runtimeKind }: UseChatOptions) {
  const [messagesByAgent, setMessagesByAgent] = useState<Record<string, UiMessage[]>>({});
  const [activityByAgent, setActivityByAgent] = useState<Record<string, UiActivity[]>>({});
  const [summaryByAgent, setSummaryByAgent] = useState<Record<string, InvocationSummary | null>>({});
  const [logsByAgent, setLogsByAgent] = useState<Record<string, string>>({});
  const [gooseChatSettingsByAgent, setGooseChatSettingsByAgent] = useState<Record<string, GooseChatSettings>>({});

  const [prompt, setPrompt] = useState("");
  const [streamMode, setStreamMode] = useState(true);
  const [requireApproval, setRequireApproval] = useState(false);
  const [chatError, setChatError] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);

  // A2A state
  const [a2aTargetAgent, setA2ATargetAgent] = useState("");
  const [a2aTargetNamespace, setA2ATargetNamespace] = useState("");
  const [a2aTimeoutSeconds, setA2ATimeoutSeconds] = useState("");

  // Specialist team
  const [specialistSubagents, setSpecialistSubagents] = useState<SpecialistSubagentDraft[]>([]);
  const [subagentStrategy, setSubagentStrategy] = useState<"sequential" | "parallel">("sequential");

  const threadIdsRef = useRef<Record<string, string>>({});
  const pendingRequestRef = useRef<Record<string, InvokePayload | null>>({});
  const streamAbortRef = useRef<AbortController | null>(null);

  const approvalSupported = runtimeKind !== "goose";

  useEffect(() => {
    if (!approvalSupported && requireApproval) setRequireApproval(false);
  }, [approvalSupported, requireApproval]);

  useEffect(() => {
    setA2ATargetAgent("");
    setA2ATargetNamespace("");
    setA2ATimeoutSeconds("");
    setSpecialistSubagents([]);
    setSubagentStrategy("sequential");
  }, [selectedAgentName, runtimeKind]);

  const messages = selectedAgentName ? messagesByAgent[selectedAgentName] ?? [] : [];
  const activity = selectedAgentName ? activityByAgent[selectedAgentName] ?? [] : [];
  const summary = selectedAgentName ? summaryByAgent[selectedAgentName] ?? null : null;
  const logs = selectedAgentName ? logsByAgent[selectedAgentName] ?? "" : "";
  const specialistTeamConfigured = hasSpecialistTeamEntries(specialistSubagents);
  const selectedGooseChatSettings = selectedAgentName ? gooseChatSettingsByAgent[selectedAgentName] ?? DEFAULT_GOOSE_CHAT_SETTINGS : DEFAULT_GOOSE_CHAT_SETTINGS;
  const canSubmitChat = Boolean(prompt.trim() || specialistSubagents.some((i) => i.task.trim()));

  // Helpers
  function setMessagesForAgent(agentName: string, updater: (c: UiMessage[]) => UiMessage[]) {
    setMessagesByAgent((cur) => ({ ...cur, [agentName]: updater(cur[agentName] ?? []) }));
  }
  function setActivityForAgent(agentName: string, updater: (c: UiActivity[]) => UiActivity[]) {
    setActivityByAgent((cur) => ({ ...cur, [agentName]: updater(cur[agentName] ?? []) }));
  }
  function setSummaryForAgent(agentName: string, updater: (c: InvocationSummary | null) => InvocationSummary | null) {
    setSummaryByAgent((cur) => ({ ...cur, [agentName]: updater(cur[agentName] ?? null) }));
  }
  function setLogsForAgent(agentName: string, value: string) {
    setLogsByAgent((cur) => ({ ...cur, [agentName]: value }));
  }
  function setGooseChatSettingsForAgent(agentName: string, updater: (c: GooseChatSettings) => GooseChatSettings) {
    setGooseChatSettingsByAgent((cur) => ({ ...cur, [agentName]: updater(cur[agentName] ?? DEFAULT_GOOSE_CHAT_SETTINGS) }));
  }

  function pushActivity(agentName: string, event: string, payload: Record<string, unknown>) {
    if (event === "response.delta") return;
    setActivityForAgent(agentName, (cur) => [{ id: createId(), event, payload, timestamp: new Date().toISOString() }, ...cur].slice(0, 24));
  }

  function setPendingAssistantContent(agentName: string, messageId: string, content: string, status: UiMessage["status"]) {
    setMessagesForAgent(agentName, (cur) => cur.map((m) => (m.id === messageId ? { ...m, content, status } : m)));
  }

  function applyInvocationFailure(agentName: string, messageId: string, message: string) {
    pendingRequestRef.current[agentName] = null;
    setPendingAssistantContent(agentName, messageId, message, "error");
    setChatError(message);
  }

  function updateSummary(agentName: string, threadId: string, payload: unknown): InvocationSummary {
    const s = buildInvocationSummary(threadId, payload);
    setSummaryForAgent(agentName, () => s);
    return s;
  }

  function removeAgentChatState(agentName: string) {
    setMessagesByAgent((cur) => { const n = { ...cur }; delete n[agentName]; return n; });
    setActivityByAgent((cur) => { const n = { ...cur }; delete n[agentName]; return n; });
    setSummaryByAgent((cur) => { const n = { ...cur }; delete n[agentName]; return n; });
    setLogsByAgent((cur) => { const n = { ...cur }; delete n[agentName]; return n; });
    delete threadIdsRef.current[agentName];
    delete pendingRequestRef.current[agentName];
  }

  const runInvocation = useCallback(
    async ({
      agentName,
      payload,
      userPrompt,
      appendUserMessage = true,
      systemNotice,
    }: {
      agentName: string;
      payload: InvokePayload;
      userPrompt?: string;
      appendUserMessage?: boolean;
      systemNotice?: string;
    }) => {
      const assistantMessageId = createId();
      const requestId = createId();
      setChatError("");
      setLogsForAgent(agentName, "");
      setActivityForAgent(agentName, () => []);
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
          const s = updateSummary(agentName, result.thread_id, result);
          threadIdsRef.current[agentName] = s.threadId;
          pendingRequestRef.current[agentName] = s.status === "approval_pending" ? { ...payload, thread_id: s.threadId } : null;
          setPendingAssistantContent(
            agentName,
            assistantMessageId,
            result.response || (s.status === "approval_pending" ? "Approval pending." : "No response body returned."),
            s.status === "blocked" ? "error" : "complete",
          );
        } catch (err) {
          applyInvocationFailure(agentName, assistantMessageId, err instanceof Error ? err.message : String(err));
        } finally {
          setIsSending(false);
        }
        return;
      }

      const abortController = new AbortController();
      streamAbortRef.current?.abort();
      streamAbortRef.current = abortController;
      let streamErrorHandled = false;

      try {
        await streamAgentInvoke({
          signal: abortController.signal,
          token,
          namespace,
          agentName,
          payload,
          requestId,
          onEvent: ({ event, payload: ep }) => {
            pushActivity(agentName, event, ep);
            if (event === "response.delta") {
              if (typeof ep.delta !== "string") throw new Error("response.delta must include a string delta.");
              setMessagesForAgent(agentName, (cur) => cur.map((m) => (m.id === assistantMessageId ? { ...m, content: `${m.content}${ep.delta}`, status: "streaming" } : m)));
              return;
            }
            if (event === "response.completed") {
              const s = updateSummary(agentName, threadIdsRef.current[agentName] ?? "", ep);
              threadIdsRef.current[agentName] = s.threadId;
              pendingRequestRef.current[agentName] = s.status === "approval_pending" ? { ...payload, thread_id: s.threadId } : null;
              setMessagesForAgent(agentName, (cur) =>
                cur.map((m) =>
                  m.id === assistantMessageId
                    ? { ...m, content: m.content || (s.status === "approval_pending" ? "Approval pending." : "Invocation completed."), status: s.status === "blocked" ? "error" : "complete" }
                    : m,
                ),
              );
              return;
            }
            if (event === "response.error" || event === "message") {
              if (typeof ep.error !== "string" || !ep.error.trim()) throw new Error(`${event} must include a non-empty error.`);
              applyInvocationFailure(agentName, assistantMessageId, ep.error);
            }
          },
          onError: (err) => {
            streamErrorHandled = true;
            applyInvocationFailure(agentName, assistantMessageId, err.message);
          },
          onClose: () => undefined,
        });
      } catch (err) {
        if (!abortController.signal.aborted && !streamErrorHandled) {
          applyInvocationFailure(agentName, assistantMessageId, err instanceof Error ? err.message : String(err));
        }
      } finally {
        setIsSending(false);
        streamAbortRef.current = null;
      }
    },
    [token, namespace, streamMode],
  );

  const handleSubmit = useCallback(async () => {
    if (!token.trim()) {
      setChatError("Enter the gateway token before sending.");
      return;
    }
    if (!selectedAgentName || !canSubmitChat) return;

    const agentName = selectedAgentName;
    const nextPrompt = prompt.trim();
    let gooseMaxTurns: number | undefined;
    let gooseWorkingDirectory: string | undefined;
    let explicitA2ATimeoutSeconds: number | undefined;
    let specialistPayload: InvokeSubagent[] | undefined;

    if (runtimeKind === "goose") {
      try {
        gooseMaxTurns = parseGooseMaxTurns(selectedGooseChatSettings.maxTurns);
        gooseWorkingDirectory = normalizeGooseWorkingDirectory(selectedGooseChatSettings.workingDirectory);
      } catch (err) {
        setChatError(err instanceof Error ? err.message : String(err));
        return;
      }
    }

    try {
      explicitA2ATimeoutSeconds = parseA2ATimeoutSeconds(a2aTimeoutSeconds);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
      return;
    }

    const normA2AAgent = a2aTargetAgent.trim();
    const normA2ANs = a2aTargetNamespace.trim();
    const hasExplicit = normA2AAgent.length > 0 || normA2ANs.length > 0;

    if (specialistTeamConfigured && runtimeKind !== "langgraph") {
      setChatError("Specialist-team orchestration is available for LangGraph agents only.");
      return;
    }
    if (hasExplicit) {
      if (!normA2AAgent || !normA2ANs) { setChatError("Provide both an A2A target namespace and agent."); return; }
      if (!isValidK8sName(normA2AAgent)) { setChatError("A2A target agent must be a valid lowercase K8s name."); return; }
      if (!isValidK8sName(normA2ANs)) { setChatError("A2A target namespace must be a valid lowercase K8s name."); return; }
    }
    if (hasExplicit && specialistTeamConfigured) {
      setChatError("Use either A2A target or specialist team, not both.");
      return;
    }

    if (specialistTeamConfigured) {
      try {
        specialistPayload = specialistSubagents
          .filter((i) => i.name.trim() || i.namespace.trim() || i.role.trim() || i.task.trim() || i.inputFilesText.trim() || i.resultFilePath.trim())
          .map((item, idx) => {
            const name = item.name.trim();
            const ns = item.namespace.trim();
            if (!name || !ns) throw new Error(`Specialist ${idx + 1} requires both namespace and agent name.`);
            if (!isValidK8sName(name)) throw new Error(`Specialist ${idx + 1} agent name must be valid K8s name.`);
            if (!isValidK8sName(ns)) throw new Error(`Specialist ${idx + 1} namespace must be valid K8s name.`);
            const timeout = parseSubagentTimeoutSeconds(item.timeoutSeconds);
            const inputFiles = parseSubagentInputFiles(item.inputFilesText);
            const task = item.task.trim();
            if (!nextPrompt && !task) throw new Error(`Specialist ${idx + 1} requires a task when main prompt is blank.`);
            return { name, namespace: ns, role: item.role.trim() || undefined, task: task || undefined, input_files: inputFiles.length > 0 ? inputFiles : undefined, result_file_path: item.resultFilePath.trim() || undefined, share_sandbox_session: item.shareSandboxSession, timeout_seconds: timeout };
          });
      } catch (err) {
        setChatError(err instanceof Error ? err.message : String(err));
        return;
      }
    }

    const payload: InvokePayload = {
      prompt: nextPrompt,
      thread_id: threadIdsRef.current[agentName],
      require_approval: requireApproval,
      approval_action: requireApproval ? `Approve UI request for ${agentName}` : undefined,
      a2a_target_agent: hasExplicit ? normA2AAgent : undefined,
      a2a_target_namespace: hasExplicit ? normA2ANs : undefined,
      a2a_timeout_seconds: explicitA2ATimeoutSeconds,
      subagents: specialistPayload,
      subagent_strategy: specialistPayload && specialistPayload.length > 0 ? subagentStrategy : undefined,
      max_turns: gooseMaxTurns,
      working_directory: gooseWorkingDirectory,
    };

    setPrompt("");
    await runInvocation({ agentName, payload, userPrompt: nextPrompt, appendUserMessage: true });
  }, [
    token, selectedAgentName, canSubmitChat, prompt, runtimeKind, selectedGooseChatSettings,
    a2aTimeoutSeconds, a2aTargetAgent, a2aTargetNamespace, specialistTeamConfigured,
    specialistSubagents, subagentStrategy, requireApproval, runInvocation,
  ]);

  const handleLoadLogs = useCallback(async () => {
    if (!token.trim() || !selectedAgentName) return;
    setLogsLoading(true);
    try {
      const result = await fetchAgentLogs(token, namespace, selectedAgentName);
      setLogsForAgent(selectedAgentName, result.logs);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setLogsLoading(false);
    }
  }, [token, namespace, selectedAgentName]);

  return {
    // Message data
    messages,
    activity,
    summary,
    logs,
    logsLoading,
    // Composer state
    prompt,
    setPrompt,
    streamMode,
    setStreamMode,
    requireApproval,
    setRequireApproval,
    approvalSupported,
    chatError,
    setChatError,
    isSending,
    canSubmitChat,
    // A2A
    a2aTargetAgent,
    setA2ATargetAgent,
    a2aTargetNamespace,
    setA2ATargetNamespace,
    a2aTimeoutSeconds,
    setA2ATimeoutSeconds,
    // Specialist team
    specialistSubagents,
    setSpecialistSubagents,
    specialistTeamConfigured,
    subagentStrategy,
    setSubagentStrategy,
    // Goose
    selectedGooseChatSettings,
    setGooseChatSettingsForAgent,
    // Actions
    handleSubmit,
    handleLoadLogs,
    runInvocation,
    removeAgentChatState,
    // Refs
    threadIdsRef,
    pendingRequestRef,
    // Helpers
    setSummaryForAgent,
    setMessagesForAgent,
  };
}
