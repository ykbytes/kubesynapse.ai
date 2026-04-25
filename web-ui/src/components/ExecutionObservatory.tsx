import { useEffect, useState, useCallback, type ComponentType } from "react";
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Calendar,
  Filter,
  GitCompare,
  Search,
  StepForward,
  Timer,
  Wrench,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  listExecutions,
  fetchExecutionDetail,
  deleteExecution,
  exportExecutionJson,
  exportExecutionHtml,
} from "@/lib/api";
import type { ExecutionListItem, ExecutionTrace, LLMCallRecord, StepTrace } from "@/types";

import { ExecutionTimeline } from "./observatory/ExecutionTimeline";
import { TracePlayer } from "./observatory/TracePlayer";
import { StepInspector } from "./observatory/StepInspector";
import { LLMCallViewer } from "./observatory/LLMCallViewer";
import { ExecutionDiffView } from "./observatory/ExecutionDiffView";

interface Filters {
  workflow: string;
  agent: string;
  status: string;
  from_date: string;
  to_date: string;
  search: string;
  sort_by: string;
}

const DEFAULT_FILTERS: Filters = {
  workflow: "",
  agent: "",
  status: "",
  from_date: "",
  to_date: "",
  search: "",
  sort_by: "started_at_desc",
};

function statusDotClasses(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500";
  if (s === "failed" || s === "error") return "bg-red-500";
  if (s === "running" || s === "in_progress") return "bg-amber-500 animate-pulse";
  return "bg-muted-foreground/40";
}

function statusBadgeClasses(status: string): string {
  const s = status.toLowerCase();
  if (s === "completed" || s === "succeeded") return "bg-emerald-500/10 text-emerald-500 border-emerald-500/20";
  if (s === "failed" || s === "error") return "bg-red-500/10 text-red-500 border-red-500/20";
  if (s === "running" || s === "in_progress") return "bg-amber-500/10 text-amber-500 border-amber-500/20";
  return "bg-muted text-muted-foreground border-border/60";
}

function formatDuration(ms?: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function ExecutionObservatory() {
  const { token, namespace } = useConnection();

  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ExecutionTrace | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");

  // Step inspector
  const [selectedStep, setSelectedStep] = useState<StepTrace | null>(null);
  const [stepInspectorOpen, setStepInspectorOpen] = useState(false);

  // LLM viewer
  const [selectedLLM, setSelectedLLM] = useState<LLMCallRecord | null>(null);
  const [llmViewerOpen, setLlmViewerOpen] = useState(false);

  // Replay
  const [replayActiveEventId, setReplayActiveEventId] = useState<string | null>(null);

  // Compare
  const [compareLeftId, setCompareLeftId] = useState<string | null>(null);
  const [compareRightId, setCompareRightId] = useState<string | null>(null);
  const [compareLeft, setCompareLeft] = useState<ExecutionTrace | null>(null);
  const [compareRight, setCompareRight] = useState<ExecutionTrace | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  const loadExecutions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listExecutions(token, namespace, {
        workflow: filters.workflow || undefined,
        agent: filters.agent || undefined,
        status: filters.status || undefined,
        from_date: filters.from_date || undefined,
        to_date: filters.to_date || undefined,
        search: filters.search || undefined,
        sort_by: filters.sort_by || undefined,
        limit: 50,
      });
      setExecutions(res.items);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load executions");
    } finally {
      setLoading(false);
    }
  }, [token, namespace, filters]);

  useEffect(() => {
    void loadExecutions();
  }, [loadExecutions]);

  useEffect(() => {
    if (!selectedExecutionId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    fetchExecutionDetail(token, selectedExecutionId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled) toast.error(err instanceof Error ? err.message : "Failed to load execution detail");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => { cancelled = true; };
  }, [token, selectedExecutionId]);

  useEffect(() => {
    if (!compareLeftId && !compareRightId) return;
    let cancelled = false;
    setCompareLoading(true);
    Promise.all([
      compareLeftId ? fetchExecutionDetail(token, compareLeftId).catch(() => null) : Promise.resolve(null),
      compareRightId ? fetchExecutionDetail(token, compareRightId).catch(() => null) : Promise.resolve(null),
    ])
      .then(([l, r]) => {
        if (!cancelled) {
          setCompareLeft(l);
          setCompareRight(r);
        }
      })
      .finally(() => {
        if (!cancelled) setCompareLoading(false);
      });
    return () => { cancelled = true; };
  }, [token, compareLeftId, compareRightId]);

  // selectedExecution metadata available via detail state

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this execution trace? This cannot be undone.")) return;
    try {
      await deleteExecution(token, id);
      toast.success("Execution deleted");
      if (selectedExecutionId === id) setSelectedExecutionId(null);
      void loadExecutions();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleExportJson = async (id: string) => {
    try {
      const text = await exportExecutionJson(token, id);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `execution-${id}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Exported JSON");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed");
    }
  };

  const handleExportHtml = async (id: string) => {
    try {
      const text = await exportExecutionHtml(token, id);
      const blob = new Blob([text], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `execution-${id}.html`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Exported HTML");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed");
    }
  };

  const handleOpenStep = (step: StepTrace) => {
    setSelectedStep(step);
    setStepInspectorOpen(true);
  };

  const handleOpenLLM = (llm: LLMCallRecord) => {
    setSelectedLLM(llm);
    setLlmViewerOpen(true);
  };

  const clearFilters = () => setFilters(DEFAULT_FILTERS);

  const hasFilters = Object.entries(filters).some(([k, v]) => k !== "sort_by" && v !== "") || filters.sort_by !== DEFAULT_FILTERS.sort_by;

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-2">
      {/* Header */}
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="break-words text-sm font-semibold leading-tight text-foreground">Observatory</h2>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-2">
        {/* Left sidebar — execution list */}
        <div className="flex w-full shrink-0 flex-col gap-2 md:w-72">
          <div className="rounded-[1.75rem] border border-border/70 bg-card/55 p-2.5 space-y-2">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filters.search}
                onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
                placeholder="Search executions..."
                className="h-9 border-border/60 pl-9 text-xs"
                aria-label="Search executions"
              />
            </div>

            {/* Sort */}
            <div className="flex items-center gap-2">
              <Select value={filters.sort_by} onValueChange={(v) => setFilters((f) => ({ ...f, sort_by: v }))}>
                <SelectTrigger className="h-8 text-xs" aria-label="Sort executions">
                  <SelectValue placeholder="Sort by" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="started_at_desc">Newest first</SelectItem>
                  <SelectItem value="started_at_asc">Oldest first</SelectItem>
                  <SelectItem value="duration_desc">Longest first</SelectItem>
                  <SelectItem value="duration_asc">Shortest first</SelectItem>
                </SelectContent>
              </Select>
              {hasFilters && (
                <Button variant="ghost" size="sm" className="h-8 gap-1 text-xs" onClick={clearFilters}>
                  <X className="h-3 w-3" />
                  Clear
                </Button>
              )}
            </div>

            {/* Filters */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                <Filter className="h-3 w-3" />
                Filters
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Input
                  value={filters.workflow}
                  onChange={(e) => setFilters((f) => ({ ...f, workflow: e.target.value }))}
                  placeholder="Workflow"
                  className="h-8 text-xs"
                  aria-label="Filter by workflow"
                />
                <Input
                  value={filters.agent}
                  onChange={(e) => setFilters((f) => ({ ...f, agent: e.target.value }))}
                  placeholder="Agent"
                  className="h-8 text-xs"
                  aria-label="Filter by agent"
                />
                <Input
                  value={filters.status}
                  onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
                  placeholder="Status"
                  className="h-8 text-xs"
                  aria-label="Filter by status"
                />
                <Input
                  type="date"
                  value={filters.from_date}
                  onChange={(e) => setFilters((f) => ({ ...f, from_date: e.target.value }))}
                  className="h-8 text-xs"
                  aria-label="From date"
                />
                <Input
                  type="date"
                  value={filters.to_date}
                  onChange={(e) => setFilters((f) => ({ ...f, to_date: e.target.value }))}
                  className="h-8 text-xs"
                  aria-label="To date"
                />
              </div>
            </div>
          </div>

          {/* List */}
          <ScrollArea className="flex-1 rounded-[1.75rem] border border-border/70 bg-card/55">
            <div className="space-y-1.5 p-2.5">
              {loading && executions.length === 0 && (
                <>
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="rounded-xl border border-transparent px-3 py-2.5 space-y-2">
                      <div className="flex items-center gap-2">
                        <Skeleton className="h-2 w-2 rounded-full" />
                        <Skeleton className="h-3.5 w-3/4 rounded" />
                      </div>
                      <Skeleton className="h-3 w-1/2 rounded" />
                    </div>
                  ))}
                </>
              )}
              {!loading && executions.length === 0 && (
                <div className="flex flex-col items-center justify-center py-10">
                  <Activity className="h-6 w-6 text-muted-foreground/40" />
                  <p className="mt-2 text-sm text-muted-foreground">No executions found.</p>
                </div>
              )}
              {executions.map((ex) => {
                const isSelected = selectedExecutionId === ex.id;
                return (
                  <button
                    key={ex.id}
                    onClick={() => { setSelectedExecutionId(ex.id); setActiveTab("overview"); }}
                    className={cn(
                      "flex w-full flex-col rounded-xl border px-3 py-2.5 text-left transition-all duration-150 ease-productive",
                      isSelected
                        ? "border-border bg-accent/80 shadow-sm"
                        : "border-transparent hover:border-border/60 hover:bg-accent/40",
                    )}
                    aria-label={`${ex.workflow_name} execution ${ex.status}`}
                    aria-pressed={isSelected}
                  >
                    <div className="flex items-center gap-2">
                      <span className={cn("h-2 w-2 rounded-full", statusDotClasses(ex.status))} aria-hidden="true" />
                      <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">{ex.workflow_name}</span>
                      <span className={cn("shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide", statusBadgeClasses(ex.status))}>
                        {ex.status}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                      {ex.agent_name && <span>{ex.agent_name}</span>}
                      <span>·</span>
                      <span>{formatDuration(ex.duration_ms)}</span>
                      <span>·</span>
                      <span>{ex.step_count} steps</span>
                    </div>
                    {isSelected && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        <Button variant="outline" size="sm" className="h-6 text-[10px] rounded-lg" onClick={(e) => { e.stopPropagation(); void handleExportJson(ex.id); }}>
                          Export JSON
                        </Button>
                        <Button variant="outline" size="sm" className="h-6 text-[10px] rounded-lg" onClick={(e) => { e.stopPropagation(); void handleExportHtml(ex.id); }}>
                          Export HTML
                        </Button>
                        <Button variant="outline" size="sm" className="h-6 text-[10px] rounded-lg text-destructive hover:bg-destructive/10" onClick={(e) => { e.stopPropagation(); void handleDelete(ex.id); }}>
                          Delete
                        </Button>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        {/* Main area */}
        <div className="flex min-w-0 flex-1 flex-col">
          {detailLoading && (
            <div className="flex flex-1 items-center justify-center">
              <div className="flex flex-col items-center gap-3 animate-fade-in">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <p className="text-sm text-muted-foreground">Loading execution...</p>
              </div>
            </div>
          )}

          {!detailLoading && !detail && (
            <div className="flex flex-1 items-center justify-center rounded-[1.75rem] border border-dashed border-border/70 bg-card/30">
              <div className="text-center">
                <Activity className="mx-auto h-8 w-8 text-muted-foreground/40" />
                <p className="mt-3 text-sm text-muted-foreground">Select an execution to inspect details.</p>
              </div>
            </div>
          )}

          {!detailLoading && detail && (
            <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
              <TabsList className="shrink-0 w-fit">
                <TabsTrigger value="overview" className="text-xs">Overview</TabsTrigger>
                <TabsTrigger value="timeline" className="text-xs">Timeline</TabsTrigger>
                <TabsTrigger value="steps" className="text-xs">Steps</TabsTrigger>
                <TabsTrigger value="llm" className="text-xs">LLM Calls</TabsTrigger>
                <TabsTrigger value="tools" className="text-xs">Tool Calls</TabsTrigger>
                <TabsTrigger value="replay" className="text-xs">Replay</TabsTrigger>
                <TabsTrigger value="compare" className="text-xs">Compare</TabsTrigger>
              </TabsList>

              <div className="mt-2 flex min-h-0 flex-1 overflow-auto rounded-[1.75rem] border border-border/70 bg-card/55 p-4">
                <TabsContent value="overview" className="mt-0 w-full">
                  <OverviewTab detail={detail} />
                </TabsContent>
                <TabsContent value="timeline" className="mt-0 w-full">
                  <ExecutionTimeline events={detail.events} activeEventId={replayActiveEventId} />
                </TabsContent>
                <TabsContent value="steps" className="mt-0 w-full">
                  <StepsTab steps={detail.steps} onOpenStep={handleOpenStep} />
                </TabsContent>
                <TabsContent value="llm" className="mt-0 w-full">
                  <LLMCallsTab llmCalls={detail.llm_calls} onOpenLLM={handleOpenLLM} />
                </TabsContent>
                <TabsContent value="tools" className="mt-0 w-full">
                  <ToolCallsTab toolCalls={detail.tool_calls} />
                </TabsContent>
                <TabsContent value="replay" className="mt-0 w-full">
                  <TracePlayer events={detail.events} onActiveEventChange={(id: string | null) => setReplayActiveEventId(id)} />
                </TabsContent>
                <TabsContent value="compare" className="mt-0 w-full">
                  <CompareTab
                    executions={executions}
                    compareLeftId={compareLeftId}
                    compareRightId={compareRightId}
                    onChangeLeft={setCompareLeftId}
                    onChangeRight={setCompareRightId}
                    compareLeft={compareLeft}
                    compareRight={compareRight}
                    compareLoading={compareLoading}
                  />
                </TabsContent>
              </div>
            </Tabs>
          )}
        </div>
      </div>

      <StepInspector step={selectedStep} open={stepInspectorOpen} onOpenChange={setStepInspectorOpen} />
      <LLMCallViewer llmCall={selectedLLM} open={llmViewerOpen} onOpenChange={setLlmViewerOpen} />
    </div>
  );
}

function OverviewTab({ detail }: { detail: ExecutionTrace }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricCard icon={Activity} label="Status" value={detail.status} />
        <MetricCard icon={Timer} label="Duration" value={formatDuration(detail.duration_ms)} />
        <MetricCard icon={StepForward} label="Steps" value={String(detail.step_count)} />
        <MetricCard icon={BarChart3} label="Total Tokens" value={String(detail.total_tokens)} />
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div className="rounded-xl border border-border/50 bg-card/55 p-3 space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Input Preview</h4>
          <pre className="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">
            {detail.input_preview ?? "No input preview available."}
          </pre>
        </div>
        <div className="rounded-xl border border-border/50 bg-card/55 p-3 space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Output Preview</h4>
          <pre className="max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-relaxed text-slate-100">
            {detail.output_preview ?? "No output preview available."}
          </pre>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MetricCard icon={BrainCircuit} label="LLM Calls" value={String(detail.llm_call_count)} />
        <MetricCard icon={Wrench} label="Tool Calls" value={String(detail.tool_call_count)} />
        <MetricCard icon={Coins} label="Cost" value={detail.total_cost_usd != null ? `$${detail.total_cost_usd.toFixed(4)}` : "—"} />
        <MetricCard icon={Calendar} label="Started" value={detail.started_at ? new Date(detail.started_at).toLocaleString() : "—"} />
      </div>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value }: { icon: ComponentType<{ className?: string }>; label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/50 bg-card/55 p-3">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className="mt-1 text-sm font-semibold text-foreground">{value}</p>
    </div>
  );
}

function StepsTab({ steps, onOpenStep }: { steps: StepTrace[]; onOpenStep: (step: StepTrace) => void }) {
  if (steps.length === 0) return <p className="text-sm text-muted-foreground">No steps recorded.</p>;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border/60 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="pb-2 pl-2 font-medium">Step</th>
              <th className="pb-2 font-medium">Status</th>
              <th className="pb-2 font-medium">Duration</th>
              <th className="pb-2 font-medium">LLM</th>
              <th className="pb-2 font-medium">Tools</th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step) => (
              <tr
                key={step.id}
                onClick={() => onOpenStep(step)}
                className="cursor-pointer border-b border-border/30 transition-colors hover:bg-accent/40"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") onOpenStep(step); }}
                role="button"
                aria-label={`Inspect step ${step.name}`}
              >
                <td className="py-2 pl-2 font-medium text-foreground">{step.name}</td>
                <td className="py-2">
                  <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", statusBadgeClasses(step.status))}>
                    {step.status}
                  </span>
                </td>
                <td className="py-2 text-muted-foreground">{formatDuration(step.latency_ms)}</td>
                <td className="py-2 text-muted-foreground">{step.llm_calls.length}</td>
                <td className="py-2 text-muted-foreground">{step.tool_calls.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function LLMCallsTab({ llmCalls, onOpenLLM }: { llmCalls: LLMCallRecord[]; onOpenLLM: (llm: LLMCallRecord) => void }) {
  if (llmCalls.length === 0) return <p className="text-sm text-muted-foreground">No LLM calls recorded.</p>;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border/60 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="pb-2 pl-2 font-medium">Model</th>
              <th className="pb-2 font-medium">Tokens</th>
              <th className="pb-2 font-medium">Cost</th>
              <th className="pb-2 font-medium">Latency</th>
            </tr>
          </thead>
          <tbody>
            {llmCalls.map((llm) => (
              <tr
                key={llm.id}
                onClick={() => onOpenLLM(llm)}
                className="cursor-pointer border-b border-border/30 transition-colors hover:bg-accent/40"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") onOpenLLM(llm); }}
                role="button"
                aria-label={`View LLM call ${llm.model}`}
              >
                <td className="py-2 pl-2 font-medium text-foreground">{llm.model}</td>
                <td className="py-2 text-muted-foreground">{llm.total_tokens}</td>
                <td className="py-2 text-muted-foreground">{llm.estimated_cost_usd != null ? `$${llm.estimated_cost_usd.toFixed(4)}` : "—"}</td>
                <td className="py-2 text-muted-foreground">{llm.latency_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ToolCallsTab({ toolCalls }: { toolCalls: import("@/types").ToolCallRecord[] }) {
  if (toolCalls.length === 0) return <p className="text-sm text-muted-foreground">No tool calls recorded.</p>;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border/60 text-xs uppercase tracking-wide text-muted-foreground">
              <th className="pb-2 pl-2 font-medium">Tool</th>
              <th className="pb-2 font-medium">Status</th>
              <th className="pb-2 font-medium">Latency</th>
              <th className="pb-2 font-medium">Result Preview</th>
            </tr>
          </thead>
          <tbody>
            {toolCalls.map((tc) => (
              <tr key={tc.id} className="border-b border-border/30">
                <td className="py-2 pl-2 font-medium text-foreground">{tc.tool_name}</td>
                <td className="py-2">
                  <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", statusBadgeClasses(tc.status))}>
                    {tc.status}
                  </span>
                </td>
                <td className="py-2 text-muted-foreground">{tc.latency_ms} ms</td>
                <td className="py-2 text-muted-foreground">
                  <span className="line-clamp-1 max-w-xs text-[11px]">{tc.result_preview ?? "—"}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CompareTab({
  executions,
  compareLeftId,
  compareRightId,
  onChangeLeft,
  onChangeRight,
  compareLeft,
  compareRight,
  compareLoading,
}: {
  executions: ExecutionListItem[];
  compareLeftId: string | null;
  compareRightId: string | null;
  onChangeLeft: (id: string | null) => void;
  onChangeRight: (id: string | null) => void;
  compareLeft: ExecutionTrace | null;
  compareRight: ExecutionTrace | null;
  compareLoading: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={compareLeftId ?? ""} onValueChange={(v) => onChangeLeft(v || null)}>
          <SelectTrigger className="h-9 w-64 text-xs" aria-label="Select left execution">
            <SelectValue placeholder="Left execution" />
          </SelectTrigger>
          <SelectContent>
            {executions.map((ex) => (
              <SelectItem key={ex.id} value={ex.id} className="text-xs">
                {ex.workflow_name} · {ex.status} · {new Date(ex.started_at ?? "").toLocaleDateString()}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <GitCompare className="h-4 w-4 text-muted-foreground" />
        <Select value={compareRightId ?? ""} onValueChange={(v) => onChangeRight(v || null)}>
          <SelectTrigger className="h-9 w-64 text-xs" aria-label="Select right execution">
            <SelectValue placeholder="Right execution" />
          </SelectTrigger>
          <SelectContent>
            {executions.map((ex) => (
              <SelectItem key={ex.id} value={ex.id} className="text-xs">
                {ex.workflow_name} · {ex.status} · {new Date(ex.started_at ?? "").toLocaleDateString()}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {compareLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : (
        <ExecutionDiffView left={compareLeft} right={compareRight} />
      )}
    </div>
  );
}

function Coins(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="8" cy="8" r="6" />
      <path d="M18.09 10.37A6 6 0 1 1 10.34 18" />
      <path d="M7 6h1v4" />
      <path d="m16.71 13.88.7.71-2.82 2.82" />
    </svg>
  );
}
