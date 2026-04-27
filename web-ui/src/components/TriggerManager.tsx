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
import { ConfirmDialog } from "./ConfirmDialog";
import { EmptyState } from "./EmptyState";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import type { WorkflowTriggerInfo, TriggerExecutionInfo, WorkflowInfo, WebhookReceiverInfo } from "../types";

const OPERATORS = ["equals", "not_equals", "contains", "exists", "regex"] as const;
type Operator = (typeof OPERATORS)[number];

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

export function TriggerManager() {
  const { token, namespace, canMutate } = useConnection();

  const [triggers, setTriggers] = useState<WorkflowTriggerInfo[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [webhooks, setWebhooks] = useState<WebhookReceiverInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [editingTrigger, setEditingTrigger] = useState<WorkflowTriggerInfo | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WorkflowTriggerInfo | null>(null);
  const [expandedTriggerId, setExpandedTriggerId] = useState<number | null>(null);

  // History
  const [history, setHistory] = useState<TriggerExecutionInfo[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showHistoryFor, setShowHistoryFor] = useState<string | null>(null);

  // Form state
  const [formName, setFormName] = useState("");
  const [formSourceKind, setFormSourceKind] = useState("WebhookReceiver");
  const [formSourceRef, setFormSourceRef] = useState("");
  const [formConditions, setFormConditions] = useState<Array<{ field: string; operator: Operator; value: string }>>([]);
  const [formWorkflowName, setFormWorkflowName] = useState("");
  const [formPayloadMapping, setFormPayloadMapping] = useState<Array<{ key: string; value: string }>>([]);
  const [formMaxRetries, setFormMaxRetries] = useState(3);
  const [formBackoffSeconds, setFormBackoffSeconds] = useState(5);
  const [formEnabled, setFormEnabled] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const loadData = useCallback(async () => {
    if (!token || !namespace) return;
    setLoading(true);
    setError("");
    try {
      const [tData, wData, whData] = await Promise.all([
        listTriggers(token, namespace),
        listWorkflows(token, namespace),
        listWebhooks(token, namespace),
      ]);
      setTriggers(tData);
      setWorkflows(wData);
      setWebhooks(whData);
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

  const resetForm = useCallback(() => {
    setFormName("");
    setFormSourceKind("WebhookReceiver");
    setFormSourceRef("");
    setFormConditions([]);
    setFormWorkflowName("");
    setFormPayloadMapping([]);
    setFormMaxRetries(3);
    setFormBackoffSeconds(5);
    setFormEnabled(true);
    setShowAdvanced(false);
    setError("");
  }, []);

  const startCreate = useCallback(() => {
    resetForm();
    setEditingTrigger(null);
    setIsCreating(true);
    setShowHistoryFor(null);
  }, [resetForm]);

  const startEdit = useCallback((trigger: WorkflowTriggerInfo) => {
    setEditingTrigger(trigger);
    setIsCreating(false);
    setShowHistoryFor(null);
    setFormName(trigger.name);
    setFormSourceKind(trigger.source_kind);
    setFormSourceRef(trigger.source_ref);

    // Parse event_filter into conditions
    const conditions: Array<{ field: string; operator: Operator; value: string }> = [];
    if (trigger.event_filter && typeof trigger.event_filter === "object") {
      for (const [key, val] of Object.entries(trigger.event_filter)) {
        if (val && typeof val === "object") {
          const obj = val as Record<string, unknown>;
          const op = Object.keys(obj)[0] as Operator;
          const v = String(Object.values(obj)[0] ?? "");
          if (OPERATORS.includes(op)) {
            conditions.push({ field: key, operator: op, value: v });
          } else {
            conditions.push({ field: key, operator: "equals", value: v });
          }
        } else {
          conditions.push({ field: key, operator: "equals", value: String(val) });
        }
      }
    }
    setFormConditions(conditions);

    // Parse workflow_ref
    const wfName = trigger.workflow_ref?.name ?? "";
    setFormWorkflowName(wfName);

    // Parse payload_mapping
    const mappings = Object.entries(trigger.payload_mapping ?? {}).map(([k, v]) => ({ key: k, value: v }));
    setFormPayloadMapping(mappings);

    setFormMaxRetries(trigger.max_retries);
    setFormBackoffSeconds(trigger.backoff_seconds);
    setFormEnabled(trigger.enabled);
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
    if (!formWorkflowName.trim()) {
      setError("Target workflow is required.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      const eventFilter: Record<string, unknown> = {};
      for (const cond of formConditions) {
        if (!cond.field.trim()) continue;
        eventFilter[cond.field] = { [cond.operator]: cond.value };
      }

      const payloadMapping: Record<string, string> = {};
      for (const m of formPayloadMapping) {
        if (m.key.trim()) payloadMapping[m.key.trim()] = m.value;
      }

      const payload = {
        name,
        source_kind: formSourceKind,
        source_ref: formSourceRef.trim(),
        event_filter: eventFilter,
        workflow_ref: { name: formWorkflowName.trim() },
        payload_mapping: payloadMapping,
        max_retries: Math.max(0, formMaxRetries),
        backoff_seconds: Math.max(0, formBackoffSeconds),
        enabled: formEnabled,
      };

      if (isCreating) {
        const created = await createTrigger(token, namespace, payload);
        setTriggers((prev) => [...prev, created]);
        setIsCreating(false);
        setEditingTrigger(created);
        toast.success("Trigger created");
      } else if (editingTrigger) {
        const updated = await updateTrigger(token, namespace, editingTrigger.name, payload);
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
    token, namespace, formName, formSourceKind, formSourceRef, formConditions,
    formWorkflowName, formPayloadMapping, formMaxRetries, formBackoffSeconds,
    formEnabled, isCreating, editingTrigger,
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

  const addCondition = useCallback(() => {
    setFormConditions((prev) => [...prev, { field: "", operator: "equals", value: "" }]);
  }, []);

  const updateCondition = useCallback((index: number, patch: Partial<{ field: string; operator: Operator; value: string }>) => {
    setFormConditions((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }, []);

  const removeCondition = useCallback((index: number) => {
    setFormConditions((prev) => prev.filter((_, i) => i !== index));
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

  const canSubmit = Boolean(formName.trim()) && Boolean(formSourceRef.trim()) && Boolean(formWorkflowName.trim());

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Workflow Triggers</h3>
          <p className="text-xs text-muted-foreground">Map incoming events to workflow executions.</p>
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
                  {isCreating ? "Create a rule that launches workflows in response to events." : "Update the trigger configuration."}
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

            {/* Event Filter */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Filter className="h-4 w-4 text-muted-foreground" />
                  Event Filter
                </div>
                <Button variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={addCondition} disabled={!canMutate}>
                  <Plus className="h-3.5 w-3.5" />
                  Add condition
                </Button>
              </div>
              {formConditions.length === 0 && (
                <p className="text-xs text-muted-foreground">No conditions — the trigger will match all events from this source.</p>
              )}
              <div className="space-y-2">
                {formConditions.map((cond, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <Input
                      value={cond.field}
                      onChange={(e) => updateCondition(index, { field: e.target.value })}
                      disabled={!canMutate}
                      placeholder="field.path"
                      className="h-8 flex-1 text-sm"
                    />
                    <Select
                      value={cond.operator}
                      onValueChange={(v) => updateCondition(index, { operator: v as Operator })}
                      disabled={!canMutate}
                    >
                      <SelectTrigger className="h-8 w-28 text-xs">
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
                      onChange={(e) => updateCondition(index, { value: e.target.value })}
                      disabled={!canMutate || cond.operator === "exists"}
                      placeholder="value"
                      className="h-8 flex-1 text-sm"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => removeCondition(index)}
                      disabled={!canMutate}
                      aria-label="Remove condition"
                    >
                      <X className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            {/* Target Workflow */}
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
                <p className="text-xs text-muted-foreground">No mappings — the workflow will receive the original payload.</p>
              )}
              <div className="space-y-2">
                {formPayloadMapping.map((m, index) => (
                  <div key={index} className="flex items-center gap-2">
                    <Input
                      value={m.key}
                      onChange={(e) => updateMapping(index, { key: e.target.value })}
                      disabled={!canMutate}
                      placeholder="workflow_input_key"
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
          description="Create a trigger to automatically launch workflows when events arrive."
          action={canMutate ? { label: "Create Trigger", onClick: startCreate } : undefined}
          className="py-12"
        />
      ) : (
        <div className="space-y-3">
          {triggers.map((trigger) => {
            const isExpanded = expandedTriggerId === trigger.id;
            const isEditing = editingTrigger?.id === trigger.id;
            if (isEditing) return null;
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
                      </div>
                      <p className="text-xs text-muted-foreground">
                        When{" "}
                        <span className="font-medium text-foreground">{trigger.source_ref}</span>{" "}
                        → launch{" "}
                        <span className="font-medium text-foreground">{trigger.workflow_ref?.name ?? trigger.workflow_ref?.workflow_name ?? "unknown"}</span>
                      </p>
                      <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                        <span className="flex items-center gap-1">
                          <Play className="h-3 w-3" />
                          {trigger.execution_count} run{trigger.execution_count === 1 ? "" : "s"}
                        </span>
                        <span className="flex items-center gap-1">
                          <ClockIcon />
                          {formatDate(trigger.last_triggered)}
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
                      {Object.keys(trigger.event_filter).length > 0 && (
                        <div className="space-y-1">
                          <div className="text-xs font-medium text-foreground">Event Filter</div>
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(trigger.event_filter).map(([key, val]) => {
                              let display = `${key} = ${String(val)}`;
                              if (val && typeof val === "object") {
                                const entries = Object.entries(val as Record<string, unknown>);
                                display = entries.map(([op, v]) => `${key} ${op} ${String(v)}`).join(", ");
                              }
                              return (
                                <Badge key={key} variant="outline" className="text-[10px]">
                                  {display}
                                </Badge>
                              );
                            })}
                          </div>
                        </div>
                      )}
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
