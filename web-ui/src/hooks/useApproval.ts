import { useCallback, useState } from "react";
import { decideApproval } from "@/lib/api";
import type { InvocationSummary, InvokePayload, UiMessage } from "@/types";

interface UseApprovalOptions {
  token: string;
  namespace: string;
  selectedAgentName: string;
  summary: InvocationSummary | null;
  setWorkspaceError: (msg: string) => void;
  setSummaryForAgent: (agentName: string, updater: (c: InvocationSummary | null) => InvocationSummary | null) => void;
  setMessagesForAgent: (agentName: string, updater: (c: UiMessage[]) => UiMessage[]) => void;
  pendingRequestRef: React.MutableRefObject<Record<string, InvokePayload | null>>;
  threadIdsRef: React.MutableRefObject<Record<string, string>>;
  runInvocation: (opts: {
    agentName: string;
    payload: InvokePayload;
    appendUserMessage?: boolean;
    systemNotice?: string;
  }) => Promise<void>;
  refreshWorkspaceData: (opts?: { silent?: boolean }) => Promise<void>;
}

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

export function useApproval({
  token,
  namespace,
  selectedAgentName,
  summary,
  setWorkspaceError,
  setSummaryForAgent,
  setMessagesForAgent,
  pendingRequestRef,
  threadIdsRef,
  runInvocation,
  refreshWorkspaceData,
}: UseApprovalOptions) {
  const [approvalReason, setApprovalReason] = useState("");
  const [approvalBusy, setApprovalBusy] = useState(false);

  const handleAgentApprovalDecision = useCallback(
    async (decision: "approved" | "denied") => {
      if (!token.trim() || !selectedAgentName || !summary?.approvalName) return;

      const currentAgent = selectedAgentName;
      const approvalName = summary.approvalName;
      setApprovalBusy(true);
      setWorkspaceError("");
      try {
        await decideApproval(token, namespace, approvalName, decision, approvalReason);
        if (decision === "denied") {
          pendingRequestRef.current[currentAgent] = null;
          setSummaryForAgent(currentAgent, (c) => (c ? { ...c, status: "blocked" } : c));
          setMessagesForAgent(currentAgent, (cur) => [
            ...cur,
            {
              id: createId(),
              role: "system",
              content: approvalReason.trim()
                ? `Approval ${approvalName} was denied. Reason: ${approvalReason.trim()}`
                : `Approval ${approvalName} was denied.`,
              status: "complete",
            },
          ]);
        } else {
          const pending = pendingRequestRef.current[currentAgent];
          if (!pending) {
            setSummaryForAgent(currentAgent, (c) => (c ? { ...c, status: "approved" } : c));
          } else {
            await runInvocation({
              agentName: currentAgent,
              payload: { ...pending, thread_id: threadIdsRef.current[currentAgent] ?? pending.thread_id },
              appendUserMessage: false,
              systemNotice: `Approval ${approvalName} granted. Retrying the pending request.`,
            });
          }
        }
        setApprovalReason("");
      } catch (err) {
        setWorkspaceError(err instanceof Error ? err.message : String(err));
      } finally {
        setApprovalBusy(false);
      }
    },
    [token, namespace, selectedAgentName, summary, approvalReason, setWorkspaceError, setSummaryForAgent, setMessagesForAgent, pendingRequestRef, threadIdsRef, runInvocation],
  );

  const handleWorkflowApprovalDecision = useCallback(
    async (approvalName: string, decision: "approved" | "denied") => {
      if (!token.trim() || !approvalName) return;
      setApprovalBusy(true);
      setWorkspaceError("");
      try {
        await decideApproval(token, namespace, approvalName, decision, approvalReason);
        setApprovalReason("");
        await refreshWorkspaceData({ silent: false });
      } catch (err) {
        setWorkspaceError(err instanceof Error ? err.message : String(err));
      } finally {
        setApprovalBusy(false);
      }
    },
    [token, namespace, approvalReason, setWorkspaceError, refreshWorkspaceData],
  );

  return {
    approvalReason,
    setApprovalReason,
    approvalBusy,
    handleAgentApprovalDecision,
    handleWorkflowApprovalDecision,
  };
}
