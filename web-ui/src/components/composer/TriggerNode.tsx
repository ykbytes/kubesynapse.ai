import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { TriggerNode as TriggerNodeType } from "@/lib/composer-utils";
import { cn } from "@/lib/utils";
import { Play } from "lucide-react";

export function TriggerNode({ data, selected }: NodeProps<TriggerNodeType>) {
  return (
    <div
      aria-label="Workflow trigger node"
      className={cn(
        "rounded-full border-2 border-primary/50 bg-gradient-to-br from-primary/20 to-primary/5 px-4 py-2.5 shadow-md shadow-primary/15",
        "flex items-center gap-2 min-w-[140px] transition-all duration-200 hover:shadow-lg hover:shadow-primary/20",
        selected && "ring-2 ring-primary ring-offset-2 ring-offset-background shadow-lg shadow-primary/25",
      )}
    >
      <Play className="h-4 w-4 text-primary shrink-0" />
      <span className="text-xs font-semibold truncate">{data.label || "Start"}</span>
      <Handle type="source" position={Position.Bottom} className="!bg-primary !w-3 !h-3" />
    </div>
  );
}
