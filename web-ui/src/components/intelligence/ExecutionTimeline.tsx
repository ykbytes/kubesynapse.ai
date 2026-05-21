import { memo, useState, useMemo } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cog,
  LoaderCircle,
  XCircle,
} from "lucide-react";
import { CopyButton } from "../shared/CopyButton";
import type { UiToolCall } from "../../types";

/* ------------------------------------------------------------------ */
/*  Per-message execution timeline (Onyx-inspired)                    */
/*                                                                    */
/*  Shows tool calls as a compact vertical timeline with collapse-all  */
/*  toggle.  Each step shows tool name, status icon, input summary,   */
/*  and expandable output.                                             */
/* ------------------------------------------------------------------ */

interface ExecutionTimelineProps {
  toolCalls: UiToolCall[];
  patches?: { files: string[] }[];
}

const StepStatusIcon = memo(function StepStatusIcon({ status }: { status?: string }) {
  if (status === "error") return <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />;
  if (status === "running") return <LoaderCircle className="h-3.5 w-3.5 text-amber-500 animate-spin shrink-0" />;
  return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />;
});

function getInputSummary(tc: UiToolCall): string {
  if (!tc.input) return "";
  if (typeof tc.input === "string") return tc.input.slice(0, 120);
  if (typeof tc.input === "object") {
    const obj = tc.input as Record<string, unknown>;
    const filePath = obj.filePath || obj.file_path || obj.path || obj.command || obj.url;
    if (typeof filePath === "string") return filePath;
    return JSON.stringify(tc.input).slice(0, 120);
  }
  return String(tc.input).slice(0, 120);
}

const TimelineStep = memo(function TimelineStep({
  tc,
  isLast,
}: {
  tc: UiToolCall;
  isLast: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const inputSummary = useMemo(() => getInputSummary(tc), [tc.input]);
  const isRunning = tc.status === "running";

  return (
    <div className="relative flex gap-2.5">
      {/* Vertical line connector */}
      {!isLast && (
        <div className="absolute left-[7px] top-5 bottom-0 w-px bg-border/40" />
      )}

      {/* Step dot */}
      <div className="relative z-10 mt-0.5 flex shrink-0 items-center justify-center">
        <StepStatusIcon status={tc.status} />
      </div>

      {/* Step content */}
      <div className="min-w-0 flex-1 pb-3">
        <button
          type="button"
          onClick={() => setExpanded((o) => !o)}
          className="flex w-full items-center gap-1.5 text-left text-xs hover:text-foreground transition-colors"
        >
          <Cog className={`h-3 w-3 shrink-0 text-muted-foreground ${isRunning ? "animate-[spin_2s_linear_infinite]" : ""}`} />
          <span className="font-medium text-foreground truncate">{tc.tool || "tool"}</span>
          {inputSummary && (
            <span className="truncate text-muted-foreground/60 text-[11px] max-w-[16rem]">{inputSummary}</span>
          )}
          {tc.output && (
            <ChevronRight className={`h-3 w-3 shrink-0 ml-auto text-muted-foreground transition-transform duration-150 ${expanded ? "rotate-90" : ""}`} />
          )}
        </button>

        {expanded && tc.output && (
          <div className="mt-1.5 rounded-lg border border-border/40 bg-muted/20 text-[10px]">
            <div className="relative group">
              <pre className="whitespace-pre-wrap break-words font-mono leading-relaxed text-muted-foreground max-h-40 overflow-auto px-2.5 py-2">
                {tc.output}
              </pre>
              <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <CopyButton value={tc.output} className="h-5 w-5" />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
});

export const ExecutionTimeline = memo(function ExecutionTimeline({
  toolCalls,
  patches,
}: ExecutionTimelineProps) {
  const [collapsed, setCollapsed] = useState(false);

  const totalSteps = toolCalls.length + (patches?.length ?? 0);
  const completed = toolCalls.filter((tc) => tc.status !== "running" && tc.status !== "error").length;
  const failed = toolCalls.filter((tc) => tc.status === "error").length;
  const running = toolCalls.filter((tc) => tc.status === "running").length;

  if (totalSteps === 0) return null;

  return (
    <div className="rounded-xl border border-border/50 bg-muted/15 overflow-hidden">
      {/* Header */}
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? (
          <ChevronRight className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
        )}
        <span className="font-medium text-foreground">
          {running > 0 ? "Running" : "Executed"} {totalSteps} {totalSteps === 1 ? "step" : "steps"}
        </span>
        <div className="flex items-center gap-1.5 ml-auto">
          {completed > 0 && (
            <span className="flex items-center gap-0.5 text-emerald-500">
              <CheckCircle2 className="h-3 w-3" /> {completed}
            </span>
          )}
          {failed > 0 && (
            <span className="flex items-center gap-0.5 text-red-500">
              <XCircle className="h-3 w-3" /> {failed}
            </span>
          )}
          {running > 0 && (
            <span className="flex items-center gap-0.5 text-amber-500">
              <LoaderCircle className="h-3 w-3 animate-spin" /> {running}
            </span>
          )}
        </div>
      </button>

      {/* Timeline steps */}
      {!collapsed && (
        <div className="border-t border-border/30 px-3 py-2.5">
          {toolCalls.map((tc, idx) => (
            <TimelineStep
              key={`${tc.tool}-${idx}`}
              tc={tc}
              isLast={idx === toolCalls.length - 1 && (!patches || patches.length === 0)}
            />
          ))}
          {patches?.map((p, idx) => (
            <div key={`patch-${idx}`} className="relative flex gap-2.5">
              <div className="relative z-10 mt-0.5 flex shrink-0 items-center justify-center">
                <CheckCircle2 className="h-3.5 w-3.5 text-blue-500 shrink-0" />
              </div>
              <div className="min-w-0 flex-1 pb-1">
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="font-medium text-foreground">Files changed</span>
                  {p.files.map((f) => (
                    <span key={f} className="font-mono text-[10px] text-blue-500 truncate max-w-[10rem]">
                      {f.split("/").pop() || f}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
