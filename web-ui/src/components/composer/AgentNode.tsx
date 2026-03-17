import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { AgentStepNode } from "@/lib/composer-utils";
import { cn } from "@/lib/utils";
import { UserCheck, Repeat } from "lucide-react";

function stepStatusColor(status?: string | null): string {
  switch (status) {
    case "completed":
      return "border-green-500 bg-green-500/10";
    case "running":
      return "border-yellow-500 bg-yellow-500/10 animate-pulse";
    case "failed":
      return "border-red-500 bg-red-500/10";
    case "waiting_approval":
      return "border-orange-500 bg-orange-500/10";
    default:
      return "border-border bg-card";
  }
}

export function AgentNode({ data, selected }: NodeProps<AgentStepNode>) {
  return (
    <div
      className={cn(
        "rounded-lg border-2 px-3 py-2 shadow-sm w-[240px] transition-colors",
        stepStatusColor(data.stepState?.status),
        selected && "ring-2 ring-primary",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-primary !w-2.5 !h-2.5" />
      <div className="flex items-center gap-1.5 text-xs font-semibold truncate">
        {data.stepName}
        {data.requireApproval && <UserCheck className="h-3 w-3 text-orange-500 shrink-0" />}
        {data.stepType === "loop" && <Repeat className="h-3 w-3 text-blue-500 shrink-0" />}
      </div>
      <div className="text-[10px] text-muted-foreground truncate">
        {data.agentRef || "no agent assigned"}
      </div>
      {data.prompt && (
        <div className="text-[10px] text-muted-foreground/70 truncate mt-0.5">
          {data.prompt.slice(0, 80)}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-primary !w-2.5 !h-2.5" />
    </div>
  );
}
