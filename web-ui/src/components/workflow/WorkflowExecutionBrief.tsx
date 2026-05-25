import { useState } from "react";
import { ChevronDown, ChevronRight, Info, Sparkles } from "lucide-react";
import type { WorkflowNextAction } from "../../types";

interface WorkflowExecutionBriefProps {
  title: string;
  body: string;
  nextAction?: WorkflowNextAction | null;
}

export function WorkflowExecutionBrief({
  title,
  body,
  nextAction,
}: WorkflowExecutionBriefProps) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="rounded-2xl border border-border/60 bg-muted/30 px-4 py-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-lg"
        aria-expanded={expanded}
        aria-label={expanded ? "Collapse execution brief" : "Expand execution brief"}
      >
        <Info className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">{title}</span>
        <span className="ml-auto">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2 animate-fade-in">
          <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
          {nextAction && (
            <div className="flex items-start gap-2 rounded-xl border border-border/50 bg-background/60 px-3 py-2">
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div>
                <p className="text-xs font-medium text-foreground">{nextAction.action}</p>
                <p className="text-xs text-muted-foreground">{nextAction.reason}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
