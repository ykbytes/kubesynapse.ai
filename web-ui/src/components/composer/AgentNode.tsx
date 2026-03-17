import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { AgentStepNode } from "@/lib/composer-utils";
import { cn } from "@/lib/utils";
import { UserCheck, Repeat, CheckCircle2, XCircle, LoaderCircle } from "lucide-react";

function stepStatusColor(status?: string | null): string {
  switch (status) {
    case "completed":
      return "border-green-500 bg-green-500/10";
    case "running":
      return "border-yellow-500 bg-yellow-500/10";
    case "failed":
      return "border-red-500 bg-red-500/10";
    case "waiting_approval":
      return "border-orange-500 bg-orange-500/10";
    default:
      return "border-border bg-card";
  }
}

function statusIndicator(status?: string | null) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-3 w-3 text-green-500 shrink-0" />;
    case "running":
      return <LoaderCircle className="h-3 w-3 text-yellow-500 animate-spin shrink-0" />;
    case "failed":
      return <XCircle className="h-3 w-3 text-red-500 shrink-0" />;
    default:
      return null;
  }
}

export function AgentNode({ data, selected }: NodeProps<AgentStepNode>) {
  return (
    <div
      aria-label={`${data.stepName} step${data.agentRef ? `, agent ${data.agentRef}` : ""}${data.requireApproval ? ", requires approval" : ""}`}
      className={cn(
        "rounded-lg border-2 px-3 py-2 shadow-sm w-[240px] transition-all duration-200 hover:shadow-md",
        stepStatusColor(data.stepState?.status),
        selected && "ring-2 ring-primary shadow-md",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-primary !w-3 !h-3" />
      <div className="flex items-center gap-1.5 text-xs font-semibold truncate">
        {data.stepName}
        {statusIndicator(data.stepState?.status)}
        {data.requireApproval && <UserCheck className="h-3 w-3 text-orange-500 shrink-0" />}
        {data.stepType === "loop" && <Repeat className="h-3 w-3 text-blue-500 shrink-0" />}
      </div>
      <div className="text-[10px] text-muted-foreground truncate" title={data.agentRef || "Agent not yet assigned"}>
        {data.agentRef || "no agent assigned"}
      </div>
      {data.prompt && (
        <div className="text-[10px] text-muted-foreground/70 truncate mt-0.5" title={data.prompt}>
          {data.prompt.slice(0, 80)}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-primary !w-3 !h-3" />
    </div>
  );
}
