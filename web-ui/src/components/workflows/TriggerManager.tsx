import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Zap,
  Filter,
  Plus,
  Trash2,
  Save,
  X,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  GanttChartSquare,
  Play,
  Skull,
  SkipForward,
  Bot,
  Workflow,
  Bell,
  Shield,
} from "lucide-react";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  listTriggers,
  createTrigger,
  updateTrigger,
  deleteTrigger,
  fetchTriggerHistory,
  listWorkflows,
  listWebhooks,
  listAgents,
  fetchDeadLetterExecutions,
  replayDeadLetter,
  apiErrorMessage,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { EmptyState } from "../shared/EmptyState";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import type { AgentInfo, WorkflowTriggerInfo, TriggerExecutionInfo, WorkflowInfo, WebhookReceiverInfo } from "../../types";

const OPERATORS = ["equals", "not_equals", "contains", "exists", "regex"] as const;
type Operator = (typeof OPERATORS)[number];
type FilterGroupOp = "AND" | "OR";

interface FilterGroup {
  op: FilterGroupOp;
  conditions: Array<{ field: string; operator: Operator; value: string }>;
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45",
        checked ? "bg-primary" : "bg-muted-foreground/30"
      )}
      aria-label={label}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform duration-200",
          checked ? "translate-x-[18px]" : "translate-x-[2px]"
        )}
      />
    </button>
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
}

function relativeTime(dateStr: string | null): string {
  if (!dateStr) return "never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function TriggerManager() {
  const { token, namespace, canMutate } = useConnection();

  const [triggers, setTriggers] = useState<WorkflowTriggerInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookReceiverInfo[]>([]);
  const [agentList, setAgentList] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingTrigger, setEditingTrigger] = useState<WorkflowTriggerInfo | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WorkflowTriggerInfo | null>(null);
  const [expandedTriggerId, setExpandedTriggerId] = useState<number | null>(null);

  // History & Dead-letter
  const [history, setHistory] = useState<TriggerExecutionInfo[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showHistoryFor, setShowHistoryFor] = useState<string | null>(null);
  const [deadLetter, setDeadLetter] = useState<TriggerExecutionInfo[]>([]);
  const [deadLetterLoading, setDeadLetterLoading] = useState(false);
  const [replayingId, setReplayingId] = useState<number | null>(null);
  const [showDeadLetterFor, setShowDeadLetterFor] = useState<string | null>(null);

  // Form state
  const [formName, setFormName] = useState("");
  const [formSourceKind, setFormSourceKind] = useState("WebhookReceiver");
  const [formSourceRef, setFormSourceRef] = useState("");
  const [formFilterGroups, setFormFilterGroups] = useState<FilterGroup[]>([{ op: "AND", conditions: [] }]);
  const [formTargetKind, setFormTargetKind] = useState<"workflow" | "agent">("workflow");
  const [formWorkflowName, setFormWorkflowName] = useState("");
  const [formAgentName, setFormAgentName] = useState("");
  const [formPayloadMapping, setFormPayloadMapping] = useState<Array<{ key: string; value: string }>>([]);
  const [formMaxRetries, setFormMaxRetries] = useState(3);
  const [formBackoffSeconds, setFormBackoffSeconds] = useState(5);
  const [formEnabled, setFormEnabled] = useState(true);
  const [formNotificationsOnSuccess, setFormNotificationsOnSuccess] = useState("");
  const [formNotificationsOnFailure, setFormNotificationsOnFailure] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const loadData = useCallback(async () => {
    if (!token || !namespace) return;
    setLoading(true);
    setError("");
    try {
      const [tData, wData, whData, aData] = await Promise.all([
        listTriggers(token, namespace),
        listWorkflows(token, namespace),
        listWebhooks(token, namespace),
        listAgents(token, namespace),
      ]);
      setTriggers(tData);
      setWorkflows(wData);
      setWebhooks(whData);
      setAgentList(aData);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [token, namespace]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    if (!token || !namespace || !showHistoryFor) {
      setHistory([]);
      return;
    }
    let cancelled = false;
    setHistoryLoading(true);
    fetchTriggerHistory(token, namespace, showHistoryFor)
      .then((data) => { if (!cancelled) setHistory(data); })
      .catch(() => { if (!cancelled) setHistory([]); })
      .finally(() => { if (!cancelled) setHistoryLoading(false); });
    return () => { cancelled = true; };
  }, [token, namespace, showHistoryFor]);

  useEffect(() => {
    if (!token || !namespace || !showDeadLetterFor) {
      setDeadLetter([]);
      return;
    }
    let cancelled = false;
    setDeadLetterLoading(true);
    fetchDeadLetterExecutions(token, namespace, showDeadLetterFor)
      .then((data) => { if (!cancelled) setDeadLetter(data); })
      .catch(() => { if (!cancelled) setDeadLetter([]); })
      .finally(() => { if (!cancelled) setDeadLetterLoading(false); });
    return () => { cancelled = true; };
  }, [token, namespace, showDeadLetterFor]);

  const resetForm = useCallback(() => {
    setFormName("");
    setFormSourceKind("WebhookReceiver");
    setFormSourceRef("");
    setFormFilterGroups([{ op: "AND", conditions: [] }]);
    setFormTargetKind("workflow");
    setFormWorkflowName("");
    setFormAgentName("");
    setFormPayloadMapping([]);
    setFormMaxRetries(3);
    setFormBackoffSeconds(60);
    setFormEnabled(true);
    setFormNotificationsOnSuccess("");
    setFormNotificationsOnFailure("");
    setShowAdvanced(false);
    setError("");
  }, []);

  const startCreate = useCallback(() => {
    resetForm();
    setEditingTrigger(null);
    setIsCreating(true);
    setShowHistoryFor(null);
    setShowDeadLetterFor(null);
  }, [resetForm]);

  const startEdit = useCallback((trigger: WorkflowTriggerInfo) => {
    setEditingTrigger(trigger);
    setIsCreating(false);
    setShowHistoryFor(null);
    setShowDeadLetterFor(null);
    setFormName(trigger.name);
    setFormSourceKind(trigger.source_kind);
    setFormSourceRef(trigger.source_ref);

    // Parse event_filter into filter groups
    const groups: FilterGroup[] = [];
    const rawFilter = trigger.event_filter;
    if (rawFilter && typeof rawFilter === "object") {
      const rootOp: FilterGroupOp = (rawFilter as { op?: string }).op === "OR" ? "OR" : "AND";
      const rawConditions = (rawFilter as { conditions?: unknown[] }).conditions;
      if (Array.isArray(rawConditions)) {
        // Top-level conditions (AND)
        const flatConditions: Array<{ field: string; operator: Operator; value: string }> = [];
        for (const item of rawConditions) {
          if (!item || typeof item !== "object") continue;
          const record = item as Record<string, unknown>;
          const field = String(record.field ?? "").trim();
          if (!field) continue;
          const operator = String(record.operator ?? "equals") as Operator;
          const value = String(record.value ?? "");
          if (OPERATORS.includes(operator)) {
            flatConditions.push({ field, operator, value });
          }
        }
        if (flatConditions.length > 0) {
          groups.push({ op: rootOp, conditions: flatConditions });
        }
      } else {
        // Nested groups: groups from the filter
        const rawGroups = (rawFilter as { groups?: unknown[] }).groups;
        if (Array.isArray(rawGroups)) {
          for (const g of rawGroups) {
            if (!g || typeof g !== "object") continue;
            const gr = g as Record<string, unknown>;
            const groupOp: FilterGroupOp = String(gr.op ?? "AND") === "OR" ? "OR" : "AND";
            const groupConditions = Array.isArray(gr.conditions) ? gr.conditions : [];
            const parsed: Array<{ field: string; operator: Operator; value: string }> = [];
            for (const item of groupConditions) {
              if (!item || typeof item !== "object") continue;
              const record = item as Record<string, unknown>;
              const field = String(record.field ?? "").trim();
              if (!field) continue;
              const operator = String(record.operator ?? "equals") as Operator;
              const value = String(record.value ?? "");
              if (OPERATORS.includes(operator)) {
                parsed.push({ field, operator, value });
              }
            }
            if (parsed.length > 0) {
              groups.push({ op: groupOp, conditions: parsed });
            }
          }
        } else {
          // Flat key-value fallback
          const fallback: Array<{ field: string; operator: Operator; value: string }> = [];
          for (const [field, value] of Object.entries(rawFilter)) {
            if (field === "op" || field === "conditions" || field === "groups") continue;
            fallback.push({ field, operator: "equals", value: String(value ?? "") });
          }
          if (fallback.length > 0) {
            groups.push({ op: "AND", conditions: fallback });
          }
        }
      }
    }
    if (groups.length === 0) groups.push({ op: "AND", conditions: [] });
    setFormFilterGroups(groups);

    // Parse target kind
    const tk = trigger.target_kind || "workflow";
    setFormTargetKind(tk as "workflow" | "agent");
    if (tk === "agent") {
      setFormAgentName(trigger.agent_ref?.name ?? "");
      setFormWorkflowName("");
    } else {
      setFormWorkflowName(trigger.workflow_ref?.name ?? "");
      setFormAgentName("");
    }

    const mappings = Object.entries(trigger.payload_mapping ?? {}).map(([k, v]) => ({ key: k, value: v }));
    setFormPayloadMapping(mappings);

    setFormMaxRetries(trigger.max_retries);
    setFormBackoffSeconds(trigger.backoff_seconds);
    setFormEnabled(trigger.enabled);

    const notif = trigger.notifications || {};
    setFormNotificationsOnSuccess((notif.on_success ?? []).join("\n"));
    setFormNotificationsOnFailure((notif.on_failure ?? []).join("\n"));
  }, []);

  const handleSave = useCallback(async () => {
    if (!token || !namespace) return;
    const name = formName.trim();
    if (!name) {
      setError("Trigger name is required.");
      return;
    }
    if (!formSourceRef.trim()) {
      setError("Source reference is required.");
      return;
    }

    if (formTargetKind === "workflow" && !formWorkflowName.trim()) {
      setError("Target workflow is required.");
      return;
    }
    if (formTargetKind === "agent" && !formAgentName.trim()) {
      setError("Target agent is required.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      // Build event filter from groups
      const nonEmptyGroups = formFilterGroups
        .filter((g) => g.conditions.some((c) => c.field.trim()))
        .map((g) => ({
          op: g.op,
          conditions: g.conditions
            .filter((c) => c.field.trim())
            .map((c) => ({
              field: c.field.trim(),
              operator: c.operator,
              value: c.operator === "exists" ? true : c.value,
            })),
        }));

      const eventFilter: Record<string, unknown> = {};
      if (nonEmptyGroups.length === 1) {
        const g = nonEmptyGroups[0];
        eventFilter.op = g.op;
        eventFilter.conditions = g.conditions;
      } else if (nonEmptyGroups.length > 1) {
        // Wrap in OR if multiple groups, or AND — use AND
        eventFilter.op = "AND";
        eventFilter.groups = nonEmptyGroups;
      }

      const payloadMapping: Record<string, string> = {};
      for (const m of formPayloadMapping) {
        if (m.key.trim()) payloadMapping[m.key.trim()] = m.value;
      }

      const successNots = formNotificationsOnSuccess.split("\n").map((s) => s.trim()).filter(Boolean);
      const failureNots = formNotificationsOnFailure.split("\n").map((s) => s.trim()).filter(Boolean);

      const notifications: { on_success?: string[]; on_failure?: string[] } = {};
      if (successNots.length > 0) notifications.on_success = successNots;
      if (failureNots.length > 0) notifications.on_failure = failureNots;
      const hasNotifications = successNots.length > 0 || failureNots.length > 0;

      const eventFilterPayload = Object.keys(eventFilter).length > 0 ? eventFilter : undefined;
      const workflowRef = formTargetKind === "workflow" ? { name: formWorkflowName.trim() } : undefined;
      const agentRef = formTargetKind === "agent" ? { name: formAgentName.trim() } : undefined;

      if (isCreating) {
        const created = await createTrigger(token, namespace, {
          name,
          source_kind: formSourceKind,
          source_ref: formSourceRef.trim(),
          event_filter: eventFilterPayload,
          target_kind: formTargetKind,
          workflow_ref: workflowRef,
          agent_ref: agentRef,
          payload_mapping: payloadMapping,
          max_retries: Math.max(0, formMaxRetries),
          backoff_seconds: Math.max(0, formBackoffSeconds),
          enabled: formEnabled,
          notifications: hasNotifications ? notifications : undefined,
        });
        setTriggers((prev) => [...prev, created]);
        setIsCreating(false);
        setEditingTrigger(created);
        toast.success("Trigger created");
      } else if (editingTrigger) {
        const updated = await updateTrigger(token, namespace, editingTrigger.name, {
          source_kind: formSourceKind,
          source_ref: formSourceRef.trim(),
          event_filter: eventFilterPayload,
          target_kind: formTargetKind,
          workflow_ref: workflowRef,
          agent_ref: agentRef,
          payload_mapping: payloadMapping,
          max_retries: Math.max(0, formMaxRetries),
          backoff_seconds: Math.max(0, formBackoffSeconds),
          enabled: formEnabled,
          notifications: hasNotifications ? notifications : undefined,
        });
        setTriggers((prev) => prev.map((t) => (t.name === editingTrigger.name ? updated : t)));
        setEditingTrigger(updated);
        toast.success("Trigger saved");
      }
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to save trigger", { description: msg });
    } finally {
      setSaving(false);
    }
  }, [
    token, namespace, formName, formSourceKind, formSourceRef, formFilterGroups,
    formTargetKind, formWorkflowName, formAgentName, formPayloadMapping,
    formMaxRetries, formBackoffSeconds, formEnabled,
    formNotificationsOnSuccess, formNotificationsOnFailure,
    isCreating, editingTrigger,
  ]);

  const handleDelete = useCallback(async () => {
    if (!token || !namespace || !deleteTarget) return;
    setSaving(true);
    try {
      await deleteTrigger(token, namespace, deleteTarget.name);
      setTriggers((prev) => prev.filter((t) => t.name !== deleteTarget.name));
      if (editingTrigger?.name === deleteTarget.name) {
        setEditingTrigger(null);
        setIsCreating(false);
        resetForm();
      }
      setDeleteTarget(null);
      toast.success("Trigger deleted");
    } catch (err) {
      const msg = apiErrorMessage(err);
      toast.error("Failed to delete trigger", { description: msg });
    } finally {
      setSaving(false);
    }
  }, [token, namespace, deleteTarget, editingTrigger, resetForm]);

  const handleReplay = useCallback(async (executionId: number) => {
    if (!token || !namespace) return;
    setReplayingId(executionId);
    try {
      await replayDeadLetter(token, namespace, executionId);
      setDeadLetter((prev) => prev.filter((e) => e.id !== executionId));
      toast.success("Execution re-queued for replay");
    } catch (err) {
      toast.error("Failed to replay execution", { description: apiErrorMessage(err) });
    } finally {
      setReplayingId(null);
    }
  }, [token, namespace]);

  // ── Filter group helpers ──

  const addFilterGroup = useCallback(() => {
    setFormFilterGroups((prev) => [...prev, { op: "AND", conditions: [] }]);
  }, []);

  const removeFilterGroup = useCallback((groupIndex: number) => {
    setFormFilterGroups((prev) => prev.filter((_, i) => i !== groupIndex));
  }, []);

  const updateGroupOp = useCallback((groupIndex: number, op: FilterGroupOp) => {
    setFormFilterGroups((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, op } : g)));
  }, []);

  const addCondition = useCallback((groupIndex: number) => {
    setFormFilterGroups((prev) => prev.map((g, i) =>
      i === groupIndex ? { ...g, conditions: [...g.conditions, { field: "", operator: "equals" as Operator, value: "" }] } : g
    ));
  }, []);

  const updateCondition = useCallback((groupIndex: number, condIndex: number, patch: Partial<{ field: string; operator: Operator; value: string }>) => {
    setFormFilterGroups((prev) => prev.map((g, gi) =>
      gi === groupIndex ? {
        ...g,
        conditions: g.conditions.map((c, ci) => (ci === condIndex ? { ...c, ...patch } : c)),
      } : g
    ));
  }, []);

  const removeCondition = useCallback((groupIndex: number, condIndex: number) => {
    setFormFilterGroups((prev) => prev.map((g, gi) =>
      gi === groupIndex ? { ...g, conditions: g.conditions.filter((_, ci) => ci !== condIndex) } : g
    ));
  }, []);

  const addMapping = useCallback(() => {
    setFormPayloadMapping((prev) => [...prev, { key: "", value: "" }]);
  }, []);

  const updateMapping = useCallback((index: number, patch: Partial<{ key: string; value: string }>) => {
    setFormPayloadMapping((prev) => prev.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  }, []);

  const removeMapping = useCallback((index: number) => {
    setFormPayloadMapping((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const availableSources = useMemo(() => {
    return formSourceKind === "WebhookReceiver" ? webhooks : [];
  }, [formSourceKind, webhooks]);

  const totalConditions = useMemo(() =>
    formFilterGroups.reduce((sum, g) => sum + g.conditions.length, 0),
    [formFilterGroups]
  );

  const canSubmit = Boolean(formName.trim()) && Boolean(formSourceRef.trim()) &&
    (formTargetKind === "workflow" ? Boolean(formWorkflowName.trim()) : Boolean(formAgentName.trim()));

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Workflow Triggers</h3>
          <p className="text-xs text-muted-foreground">Map incoming events to workflow or agent executions.</p>
        </div>
        {canMutate && (
          <Button size="sm" className="h-8 gap-1.5 text-xs" onClick={startCreate}>
            <Plus className="h-3.5 w-3.5" />
            New Trigger
          </Button>
        )}
      </div>

      {error && !isCreating && !editingTrigger && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive" role="alert">
          {error}
        </div>
      )}

      {/* Editor */}
      {(isCreating || editingTrigger) && (
        <Card className="border-border/70 bg-card/55">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <CardTitle className="text-base font-semibold">
                  {isCreating ? "New Trigger" : `Edit ${editingTrigger?.name}`}
                </CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  {isCreating ? "Create a rule that launches workflows or agents in response to events." : "Update the trigger configuration."}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs"
                  onClick={() => { setIsCreating(false); setEditingTrigger(null); resetForm(); }}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="h-8 gap-1.5 text-xs"
                  onClick={handleSave}
                  disabled={saving || !canSubmit}
                >
                  <Save className="h-3.5 w-3.5" />
                  {saving ? "Saving..." : "Save"}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {error && (
              <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive" role="alert">
                {error}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  disabled={!canMutate || !isCreating}
                  placeholder="deploy-trigger"
                  className="h-9 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label>Source Kind</Label>
                <Select value={formSourceKind} onValueChange={setFormSourceKind} disabled={!canMutate}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="WebhookReceiver">Webhook Receiver</SelectItem>
                    <SelectItem value="AgentEvent">Agent Event</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>Source Reference</Label>
                {availableSources.length > 0 ? (
                  <Select value={formSourceRef} onValueChange={setFormSourceRef} disabled={!canMutate}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue placeholder="Select source..." />
                    </SelectTrigger>
                    <SelectContent>
                      {availableSources.map((s) => (
                        <SelectItem key={s.name} value={s.name}>{s.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={formSourceRef}
                    onChange={(e) => setFormSourceRef(e.target.value)}
                    disabled={!canMutate}
                    placeholder={formSourceKind === "WebhookReceiver" ? "webhook-name" : "agent-name"}
                    className="h-9 text-sm"
                  />
                )}
              </div>
            </div>

            {/* Event Filter — AND/OR Groups */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  Event Filter
                  {totalConditions > 0 && (
                    <Badge variant="outline" className="text-[10px]">{totalConditions} condition{totalConditions === 1 ? "" : "s"}</Badge>
                  )}
                </div>
                <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={addFilterGroup} disabled={!canMutate}>
                  <Plus className="h-3.5 w-3.5" />
                  Add group
                </Button>
              </div>
              {formFilterGroups.length === 0 && (
                <p className="text-xs text-muted-foreground">No conditions — the trigger will match all events from this source.</p>
              )}
              <div className="space-y-3">
                {formFilterGroups.map((group, gIndex) => (
                  <div key={gIndex} className="rounded-lg border border-border/60 bg-background/30 p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Select
                          value={group.op}
                          onValueChange={(v) => updateGroupOp(gIndex, v as FilterGroupOp)}
                          disabled={!canMutate}
                        >
                          <SelectTrigger className="h-7 w-16 text-[10px]">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="AND" className="text-xs">AND</SelectItem>
                            <SelectItem value="OR" className="text-xs">OR</SelectItem>
                          </SelectContent>
                        </Select>
                        <span className="text-[11px] text-muted-foreground">Group {gIndex + 1}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 gap-1 text-[10px]"
                          onClick={() => addCondition(gIndex)}
                          disabled={!canMutate}
                        >
                          <Plus className="h-3 w-3" />
                          Condition
                        </Button>
                        {formFilterGroups.length > 1 && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 text-muted-foreground hover:text-destructive"
                            onClick={() => removeFilterGroup(gIndex)}
                            disabled={!canMutate}
                            aria-label="Remove group"
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                    {group.conditions.length === 0 && (
                      <p className="text-[11px] text-muted-foreground italic">No conditions in this group.</p>
                    )}
                    <div className="space-y-2">
                      {group.conditions.map((cond, cIndex) => (
                        <div key={cIndex} className="flex items-center gap-2">
                          <Input
                            value={cond.field}
                            onChange={(e) => updateCondition(gIndex, cIndex, { field: e.target.value })}
                            disabled={!canMutate}
                            placeholder="field.path"
                            className="h-7 flex-1 text-xs"
                          />
                          <Select
                            value={cond.operator}
                            onValueChange={(v) => updateCondition(gIndex, cIndex, { operator: v as Operator })}
                            disabled={!canMutate}
                          >
                            <SelectTrigger className="h-7 w-24 text-[10px]">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {OPERATORS.map((op) => (
                                <SelectItem key={op} value={op} className="text-xs">{op}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Input
                            value={cond.value}
                            onChange={(e) => updateCondition(gIndex, cIndex, { value: e.target.value })}
                            disabled={!canMutate || cond.operator === "exists"}
                            placeholder="value"
                            className="h-7 flex-1 text-xs"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-destructive"
                            onClick={() => removeCondition(gIndex, cIndex)}
                            disabled={!canMutate}
                            aria-label="Remove condition"
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Target Kind selector */}
            <div className="space-y-1.5">
              <Label>Target Type</Label>
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => { setFormTargetKind("workflow"); setFormAgentName(""); }}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors",
                    formTargetKind === "workflow"
                      ? "border-primary/50 bg-primary/10 text-foreground"
                      : "border-border/60 bg-background/40 text-muted-foreground hover:border-border"
                  )}
                  disabled={!canMutate}
                >
                  <Workflow className="h-4 w-4" />
                  Workflow
                </button>
                <button
                  type="button"
                  onClick={() => { setFormTargetKind("agent"); setFormWorkflowName(""); }}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors",
                    formTargetKind === "agent"
                      ? "border-primary/50 bg-primary/10 text-foreground"
                      : "border-border/60 bg-background/40 text-muted-foreground hover:border-border"
                  )}
                  disabled={!canMutate}
                >
                  <Bot className="h-4 w-4" />
                  Agent
                </button>
              </div>
            </div>

            {/* Target Workflow */}
            {formTargetKind === "workflow" && (
              <div className="space-y-1.5">
                <Label>Target Workflow</Label>
                {workflows.length > 0 ? (
                  <Select value={formWorkflowName} onValueChange={setFormWorkflowName} disabled={!canMutate}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue placeholder="Select workflow..." />
                    </SelectTrigger>
                    <SelectContent>
                      {workflows.map((w) => (
                        <SelectItem key={w.name} value={w.name}>{w.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={formWorkflowName}
                    onChange={(e) => setFormWorkflowName(e.target.value)}
                    disabled={!canMutate}
                    placeholder="workflow-name"
                    className="h-9 text-sm"
                  />
                )}
              </div>
            )}

            {/* Target Agent */}
            {formTargetKind === "agent" && (
              <div className="space-y-1.5">
                <Label>Target Agent</Label>
                {agentList.length > 0 ? (
                  <Select value={formAgentName} onValueChange={setFormAgentName} disabled={!canMutate}>
                    <SelectTrigger className="h-9 text-sm">
                      <SelectValue placeholder="Select agent..." />
                    </SelectTrigger>
                    <SelectContent>
                      {agentList.map((a) => (
                        <SelectItem key={a.name} value={a.name}>{a.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={formAgentName}
                    onChange={(e) => setFormAgentName(e.target.value)}
                    disabled={!canMutate}
                    placeholder="agent-name"
                    className="h-9 text-sm"
                  />
                )}
              </div>
            )}

            {/* Payload Mapping */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-foreground">Payload Mapping</div>
                <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={addMapping} disabled={!canMutate}>
                  <Plus className="h-3.5 w-3.5" />
                  Add mapping
                </Button>
              </div>
              {formPayloadMapping.length === 0 && (
                <p className="text-xs text-muted-foreground">No mappings — the target will receive the original payload.</p>
              )}
              <div className="space-y-2">
                {formPayloadMapping.map((m, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <Input
                      value={m.key}
                      onChange={(e) => updateMapping(index, { key: e.target.value })}
                      disabled={!canMutate}
                      placeholder="target_input_key"
                      className="h-8 flex-1 text-sm"
                    />
                    <span className="text-xs text-muted-foreground">→</span>
                    <Input
                      value={m.value}
                      onChange={(e) => updateMapping(index, { value: e.target.value })}
                      disabled={!canMutate}
                      placeholder="event.payload.field"
                      className="h-8 flex-1 text-sm"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => removeMapping(index)}
                      disabled={!canMutate}
                      aria-label="Remove mapping"
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            {/* Notifications */}
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Bell className="h-4 w-4 text-muted-foreground" />
                Notifications
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1">
                  <Label>On Success (webhook names, one per line)</Label>
                  <textarea
                    value={formNotificationsOnSuccess}
                    onChange={(e) => setFormNotificationsOnSuccess(e.target.value)}
                    disabled={!canMutate}
                    placeholder="success-webhook"
                    rows={2}
                    className="flex w-full rounded-lg border border-border/60 bg-background/50 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                </div>
                <div className="space-y-1">
                  <Label>On Failure (webhook names, one per line)</Label>
                  <textarea
                    value={formNotificationsOnFailure}
                    onChange={(e) => setFormNotificationsOnFailure(e.target.value)}
                    disabled={!canMutate}
                    placeholder="failure-webhook"
                    rows={2}
                    className="flex w-full rounded-lg border border-border/60 bg-background/50 px-3 py-1.5 text-xs placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 disabled:cursor-not-allowed disabled:opacity-50"
                  />
                </div>
              </div>
            </div>

            {/* Enabled */}
            <div className="flex items-center gap-3">
              <Toggle checked={formEnabled} onChange={setFormEnabled} label="Enabled" />
              <span className="text-sm text-muted-foreground">{formEnabled ? "Enabled" : "Disabled"}</span>
            </div>

            {/* Advanced */}
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => setShowAdvanced((v) => !v)}
                className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                {showAdvanced ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                Advanced
              </button>
              {showAdvanced && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label>Max Retries</Label>
                    <Input
                      type="number"
                      value={formMaxRetries}
                      onChange={(e) => setFormMaxRetries(Number(e.target.value))}
                      disabled={!canMutate}
                      min={0}
                      className="h-9 text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Backoff Seconds</Label>
                    <Input
                      type="number"
                      value={formBackoffSeconds}
                      onChange={(e) => setFormBackoffSeconds(Number(e.target.value))}
                      disabled={!canMutate}
                      min={0}
                      className="h-9 text-sm"
                    />
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Trigger List */}
      {loading && triggers.length === 0 ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-[1.75rem]" />
          ))}
        </div>
      ) : triggers.length === 0 && !isCreating && !editingTrigger ? (
        <EmptyState
          icon={Zap}
          title="No triggers configured"
          description="Create a trigger to automatically launch workflows or agents when events arrive."
          action={canMutate ? { label: "Create Trigger", onClick: startCreate } : undefined}
          className="py-12"
        />
      ) : (
        <div className="space-y-3">
          {triggers.map((trigger) => {
            const isExpanded = expandedTriggerId === trigger.id;
            const isEditing = editingTrigger?.id === trigger.id;
            if (isEditing) return null;
            const tk = trigger.target_kind || "workflow";
            const targetName = tk === "agent"
              ? trigger.agent_ref?.name ?? "unknown"
              : trigger.workflow_ref?.name ?? trigger.workflow_ref?.workflow_name ?? "unknown";
            return (
              <Card key={trigger.id} className="border-border/70 bg-card/55">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant={trigger.source_kind === "WebhookReceiver" ? "default" : "secondary"} className="text-[10px]">
                          {trigger.source_kind === "WebhookReceiver" ? "Webhook" : "Agent Event"}
                        </Badge>
                        <span className="text-sm font-semibold text-foreground">{trigger.name}</span>
                        <Badge variant={trigger.enabled ? "outline" : "secondary"} className="text-[10px]">
                          {trigger.enabled ? "Enabled" : "Disabled"}
                        </Badge>
                        {tk === "agent" && (
                          <Badge variant="secondary" className="text-[10px] flex items-center gap-1">
                            <Bot className="h-2.5 w-2.5" />
                            Agent
                          </Badge>
                        )}
                        {trigger.dead_letter_count > 0 && (
                          <Badge variant="destructive" className="text-[10px] flex items-center gap-1">
                            <Skull className="h-2.5 w-2.5" />
                            {trigger.dead_letter_count} DLQ
                          </Badge>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        When{" "}
                        <span className="font-medium text-foreground">{trigger.source_ref}</span>{" "}
                        → launch {tk === "agent" ? "agent" : "workflow"}{" "}
                        <span className="font-medium text-foreground">{targetName}</span>
                      </p>
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Play className="h-3 w-3" />
                          {trigger.execution_count} run{trigger.execution_count === 1 ? "" : "s"}
                        </span>
                        <span className="flex items-center gap-1">
                          <ClockIcon />
                          {relativeTime(trigger.last_triggered)}
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Toggle
                        checked={trigger.enabled}
                        onChange={async (v) => {
                          if (!token || !namespace || !canMutate) return;
                          try {
                            const updated = await updateTrigger(token, namespace, trigger.name, { enabled: v });
                            setTriggers((prev) => prev.map((t) => (t.name === trigger.name ? updated : t)));
                            toast.success(v ? "Trigger enabled" : "Trigger disabled");
                          } catch (err) {
                            toast.error(apiErrorMessage(err));
                          }
                        }}
                        label="Toggle trigger"
                      />
                      {canMutate && (
                        <>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-foreground"
                            onClick={() => startEdit(trigger)}
                            aria-label={`Edit ${trigger.name}`}
                          >
                            <GanttChartSquare className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={() => setDeleteTarget(trigger)}
                            aria-label={`Delete ${trigger.name}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="mt-2">
                    <button
                      type="button"
                      onClick={() => setExpandedTriggerId(isExpanded ? null : trigger.id)}
                      className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {isExpanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                      {isExpanded ? "Hide details" : "Show details & history"}
                    </button>
                  </div>

                  {isExpanded && (
                    <div className="mt-3 space-y-3">
                      <Separator />
                      {/* Event filter summary */}
                      {trigger.event_filter && Object.keys(trigger.event_filter).length > 0 && (
                        <div className="space-y-1">
                          <div className="text-xs font-medium text-foreground">Event Filter</div>
                          <div className="flex flex-wrap gap-1.5">
                            {(() => {
                              const raw = trigger.event_filter;
                              const conditions = (raw as { conditions?: unknown[] }).conditions;
                              if (Array.isArray(conditions)) {
                                return conditions.map((item, i) => {
                                  const r = (item ?? {}) as Record<string, unknown>;
                                  const field = String(r.field ?? "");
                                  const op = String(r.operator ?? "equals");
                                  const val = String(r.value ?? "");
                                  return (
                                    <Badge key={`cond-${i}`} variant="outline" className="text-[10px]">
                                      {field} {op} {val}
                                    </Badge>
                                  );
                                });
                              }
                              return Object.entries(raw).filter(([k]) => k !== "op" && k !== "conditions" && k !== "groups").map(([k, v]) => (
                                <Badge key={k} variant="outline" className="text-[10px]">{k} = {String(v)}</Badge>
                              ));
                            })()}
                          </div>
                        </div>
                      )}
                      {/* Target type */}
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Shield className="h-3 w-3" />
                        Target:{" "}
                        <span className="font-medium text-foreground">
                          {tk === "agent" ? `Agent ${targetName}` : `Workflow ${targetName}`}
                        </span>
                      </div>
                      {/* Payload mapping summary */}
                      {Object.keys(trigger.payload_mapping).length > 0 && (
                        <div className="space-y-1">
                          <div className="text-xs font-medium text-foreground">Payload Mapping</div>
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(trigger.payload_mapping).map(([k, v]) => (
                              <Badge key={k} variant="outline" className="text-[10px]">
                                {k} → {v}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* Notifications summary */}
                      {trigger.notifications && (
                        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                          {trigger.notifications.on_success && trigger.notifications.on_success.length > 0 && (
                            <span className="flex items-center gap-1">
                              <Bell className="h-3 w-3 text-emerald-400" />
                              Success: {trigger.notifications.on_success.join(", ")}
                            </span>
                          )}
                          {trigger.notifications.on_failure && trigger.notifications.on_failure.length > 0 && (
                            <span className="flex items-center gap-1">
                              <Bell className="h-3 w-3 text-destructive" />
                              Failure: {trigger.notifications.on_failure.join(", ")}
                            </span>
                          )}
                        </div>
                      )}
                      {/* History */}
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="text-xs font-medium text-foreground">Execution History</div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 gap-1 text-[10px]"
                            onClick={() => setShowHistoryFor(showHistoryFor === trigger.name ? null : trigger.name)}
                          >
                            <RefreshCw className="h-3 w-3" />
                            Refresh
                          </Button>
                        </div>
                        {showHistoryFor === trigger.name && historyLoading && history.length === 0 ? (
                          <div className="space-y-2">
                            {[0, 1].map((i) => (
                              <Skeleton key={i} className="h-8 w-full rounded-lg" />
                            ))}
                          </div>
                        ) : showHistoryFor === trigger.name && history.length === 0 ? (
                          <p className="text-xs text-muted-foreground">No executions yet.</p>
                        ) : showHistoryFor === trigger.name ? (
                          <div className="space-y-1.5">
                            {history.map((exec) => (
                              <div
                                key={exec.id}
                                className="flex items-center justify-between rounded-lg border border-border/60 bg-background/40 px-3 py-2"
                              >
                                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                  <span>{formatDate(exec.executed_at)}</span>
                                  <span className="text-border">·</span>
                                  <span>{exec.webhook_name}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <Badge
                                    variant={exec.status === "dispatched" ? "default" : exec.status === "failed" ? "destructive" : "secondary"}
                                    className="text-[10px]"
                                  >
                                    {exec.status}
                                  </Badge>
                                  {exec.workflow_run_id && (
                                    <Badge variant="outline" className="text-[10px]">
                                      {exec.workflow_run_id.slice(0, 8)}…
                                    </Badge>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>

                      {/* Dead-letter */}
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                            <Skull className="h-3.5 w-3.5 text-destructive" />
                            Dead Letter
                            {trigger.dead_letter_count > 0 && (
                              <Badge variant="destructive" className="text-[10px]">{trigger.dead_letter_count}</Badge>
                            )}
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 gap-1 text-[10px]"
                            onClick={() => setShowDeadLetterFor(showDeadLetterFor === trigger.name ? null : trigger.name)}
                          >
                            <RefreshCw className="h-3 w-3" />
                            Load
                          </Button>
                        </div>
                        {showDeadLetterFor === trigger.name && deadLetterLoading && deadLetter.length === 0 ? (
                          <div className="space-y-2">
                            {[0, 1].map((i) => (
                              <Skeleton key={i} className="h-12 w-full rounded-lg" />
                            ))}
                          </div>
                        ) : showDeadLetterFor === trigger.name && deadLetter.length === 0 ? (
                          <p className="text-xs text-muted-foreground">No dead-letter items.</p>
                        ) : showDeadLetterFor === trigger.name ? (
                          <div className="space-y-1.5">
                            {deadLetter.map((exec) => (
                              <div
                                key={exec.id}
                                className="flex items-center justify-between rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2"
                              >
                                <div className="flex items-center gap-2 text-[11px]">
                                  <span className="text-muted-foreground">{formatDate(exec.executed_at)}</span>
                                  <Badge variant="destructive" className="text-[10px]">{exec.status}</Badge>
                                  <span className="text-muted-foreground">{exec.attempt_count} attempt{exec.attempt_count === 1 ? "" : "s"}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                  {exec.error_message && (
                                    <span className="text-[10px] text-destructive/80 max-w-[200px] truncate" title={exec.error_message}>
                                      {exec.error_message}
                                    </span>
                                  )}
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 gap-1 text-[10px]"
                                    onClick={() => handleReplay(exec.id)}
                                    disabled={replayingId === exec.id}
                                  >
                                    <SkipForward className="h-3 w-3" />
                                    {replayingId === exec.id ? "Replaying..." : "Replay"}
                                  </Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete trigger"
        description={`This will permanently delete the trigger "${deleteTarget?.name}". This action cannot be undone.`}
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={handleDelete}
      />
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-sm font-medium text-foreground">{children}</div>;
}

function ClockIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}
