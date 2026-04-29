import { Info, Timer } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { WorkflowSummary } from "../../types";

interface WorkflowSidebarProps {
  messageBus: string;
  setMessageBus: (v: string) => void;
  loopStepCount: number;
  reviewStepCount: number;
  uniqueAgentCount: number;
  stepsCount: number;
  isTriggered: boolean;
  wfSummary?: WorkflowSummary;
  phase: string;
}

export function WorkflowSidebar({
  messageBus,
  setMessageBus,
  loopStepCount,
  reviewStepCount,
  uniqueAgentCount,
  stepsCount,
  isTriggered,
  wfSummary,
  phase,
}: WorkflowSidebarProps) {
  const isActive = phase === "running" || phase === "queued" || phase === "waiting-approval";

  return (
    <div className="space-y-6">
      {/* Execution profile */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">Execution profile</h3>
          <p className="text-xs text-muted-foreground">Runtime and messaging configuration.</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="message-bus" className="text-sm font-medium">
            Message bus
          </Label>
          <Select value={messageBus} onValueChange={setMessageBus}>
            <SelectTrigger id="message-bus" className="h-10 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="in-memory">in-memory</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            The current gateway API supports the in-memory workflow bus only.
          </p>
        </div>
      </section>

      <Separator />

      {/* Stats */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Workflow stats</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-border/60 bg-card/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Agents</p>
            <p className="text-sm font-semibold">{uniqueAgentCount}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-card/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Steps</p>
            <p className="text-sm font-semibold">{stepsCount}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-card/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Loops</p>
            <p className="text-sm font-semibold">{loopStepCount}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-card/40 px-3 py-2">
            <p className="text-xs text-muted-foreground">Reviews</p>
            <p className="text-sm font-semibold">{reviewStepCount}</p>
          </div>
        </div>
      </section>

      {/* Live stats */}
      {isTriggered && wfSummary && (
        <>
          <Separator />
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-foreground">Run stats</h3>
            <div className="space-y-2">
              {wfSummary.runId && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Run ID</span>
                  <Badge variant="outline" className="font-mono text-xs">
                    {wfSummary.runId}
                  </Badge>
                </div>
              )}
              {wfSummary.startedAt && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Started</span>
                  <span className="text-xs font-medium">
                    {new Date(wfSummary.startedAt).toLocaleTimeString()}
                  </span>
                </div>
              )}
              {isActive && wfSummary.startedAt && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Elapsed</span>
                  <span className="flex items-center gap-1 text-xs font-medium">
                    <Timer className="h-3 w-3" />
                    {formatElapsed(wfSummary.startedAt)}
                  </span>
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Completed</span>
                <span className="text-xs font-medium">
                  {wfSummary.completedSteps ?? 0} / {wfSummary.totalSteps ?? 0}
                </span>
              </div>
            </div>
          </section>
        </>
      )}

      <Separator />

      {/* Operator-friendly defaults info */}
      <div className="flex items-start gap-2 rounded-xl border border-border/60 bg-card/40 px-3 py-3">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium text-foreground">Operator-friendly defaults</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Each step is independently targetable, dependencies stay explicit, and approval gates are visible directly on the step card.
          </p>
        </div>
      </div>
    </div>
  );
}

function formatElapsed(startedAt?: string | null): string {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return "—";
  const elapsed = Date.now() - start;
  const ms = Math.max(0, elapsed);
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}
