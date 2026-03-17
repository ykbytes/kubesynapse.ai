import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { TriggerNode as TriggerNodeType } from "@/lib/composer-utils";
import { cn } from "@/lib/utils";
import { Play } from "lucide-react";

export function TriggerNode({ data, selected }: NodeProps<TriggerNodeType>) {
  return (
    <div
      className={cn(
        "rounded-full border-2 border-primary/60 bg-primary/10 px-4 py-2.5 shadow-sm",
        "flex items-center gap-2 min-w-[140px] transition-colors",
        selected && "ring-2 ring-primary",
      )}
    >
      <Play className="h-4 w-4 text-primary shrink-0" />
      <span className="text-xs font-semibold truncate">{data.label || "Start"}</span>
      <Handle type="source" position={Position.Bottom} className="!bg-primary !w-2.5 !h-2.5" />
    </div>
  );
}
