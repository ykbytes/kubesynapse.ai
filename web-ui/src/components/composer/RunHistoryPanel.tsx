import { useEffect, useState } from "react";
import { fetchWorkflowRuns, type WorkflowRunRecord } from "@/lib/api";
import { useConnection } from "@/contexts/ConnectionContext";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { History, RefreshCw, CheckCircle2, XCircle, Clock, Loader2, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface RunHistoryPanelProps {
  workflowName: string;
  collapsed: boolean;
  onToggle: () => void;
}

function phaseIcon(phase: string) {
  switch (phase) {
    case "completed": return <CheckCircle2 className="h-3 w-3 text-emerald-400" />;
    case "failed": return <XCircle className="h-3 w-3 text-red-400" />;
    case "running": return <Loader2 className="h-3 w-3 text-amber-400 animate-spin" />;
    case "cancelled": return <XCircle className="h-3 w-3 text-muted-foreground" />;
    default: return <Clock className="h-3 w-3 text-muted-foreground" />;
  }
}

function phaseColor(phase: string): string {
  switch (phase) {
    case "completed": return "text-emerald-400 bg-emerald-500/10 border-emerald-500/20";
    case "failed": return "text-red-400 bg-red-500/10 border-red-500/20";
    case "running": return "text-amber-400 bg-amber-500/10 border-amber-500/20";
    case "cancelled": return "text-muted-foreground bg-muted/50 border-border";
    default: return "text-muted-foreground bg-muted/50 border-border";
  }
}

export function RunHistoryPanel({ workflowName, collapsed, onToggle }: RunHistoryPanelProps) {
  const { token, namespace } = useConnection();
  const [runs, setRuns] = useState<WorkflowRunRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const loadRuns = () => {
    if (!workflowName || !token.trim()) return;
    setLoading(true);
    fetchWorkflowRuns(token, namespace, workflowName)
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!collapsed) loadRuns();
  }, [workflowName, collapsed, token, namespace]);

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center justify-center w-8 border-t border-border/40 bg-muted/10 hover:bg-muted/30 transition-colors cursor-pointer shrink-0"
        title="Show run history"
      >
        <History className="h-3.5 w-3.5 text-muted-foreground" />
      </button>
    );
  }

  return (
    <div className="border-t border-border/40 bg-background shrink-0">
      <div className="flex items-center justify-between px-3 py-1.5">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground cursor-pointer"
        >
          <History className="h-3 w-3" /> Run History
        </button>
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 cursor-pointer"
          onClick={loadRuns}
          disabled={loading}
          title="Refresh"
        >
          <RefreshCw className={cn("h-3 w-3", loading && "animate-spin")} />
        </Button>
      </div>
      <div className="max-h-48 overflow-y-auto px-3 pb-2 space-y-1">
        {runs.length === 0 && !loading && (
          <p className="text-[10px] text-muted-foreground/60 text-center py-2">No runs recorded yet.</p>
        )}
        {runs.map((run) => (
          <RunRow key={run.id} run={run} />
        ))}
      </div>
    </div>
  );
}

function RunRow({ run }: { run: WorkflowRunRecord }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-md border bg-card/50 text-[10px]">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-accent/30 transition-colors"
        aria-expanded={expanded}
        aria-label={`Run ${run.run_id?.slice(0, 8) ?? run.id} — ${run.phase}`}
      >
        <span className="transition-transform duration-150" style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}>
          <ChevronRight className="h-2.5 w-2.5 text-muted-foreground" />
        </span>
        {phaseIcon(run.phase)}
        <Badge variant="outline" className={cn("text-[9px] h-4 px-1.5 border", phaseColor(run.phase))}>
          {run.phase}
        </Badge>
        {run.run_id && (
          <span className="font-mono text-muted-foreground">{run.run_id.slice(0, 8)}</span>
        )}
        <span className="text-muted-foreground">
          {run.completed_steps ?? 0}/{run.total_steps ?? "?"} steps
        </span>
        {run.triggered_by && (
          <span className="text-muted-foreground/60 truncate max-w-20" title={run.triggered_by}>
            by {run.triggered_by}
          </span>
        )}
        <span className="ml-auto text-muted-foreground/60 font-mono shrink-0">
          {run.created_at ? new Date(run.created_at).toLocaleString() : ""}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border/30 px-2.5 py-1.5 space-y-1 text-[10px] text-muted-foreground">
          {run.run_id && <div><span className="font-medium">Run ID:</span> <span className="font-mono">{run.run_id}</span></div>}
          {run.started_at && <div><span className="font-medium">Started:</span> {new Date(run.started_at).toLocaleString()}</div>}
          {run.completed_at && <div><span className="font-medium">Completed:</span> {new Date(run.completed_at).toLocaleString()}</div>}
          {run.failed_steps != null && run.failed_steps > 0 && (
            <div><span className="font-medium text-red-400">Failed steps:</span> {run.failed_steps}</div>
          )}
          {run.input_text && (
            <div>
              <span className="font-medium">Input:</span>
              <pre className="mt-0.5 whitespace-pre-wrap break-all bg-muted/30 rounded px-1.5 py-1 max-h-24 overflow-y-auto font-mono">
                {run.input_text.length > 500 ? `${run.input_text.slice(0, 500)}…` : run.input_text}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
