import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { TriggerNode as TriggerNodeType } from "@/lib/composer-utils";
import { getCurrentDirection } from "@/lib/composer-utils";
import { cn } from "@/lib/utils";
import { Zap } from "lucide-react";

export function TriggerNode({ data, selected }: NodeProps<TriggerNodeType>) {
  const dir = getCurrentDirection();
  const isHorizontal = dir === "horizontal";
  const sourcePos = isHorizontal ? Position.Right : Position.Bottom;
  const sourceHandleClass = isHorizontal
    ? "!h-5 !w-2 !rounded-sm !bg-primary !border-0 !right-[-4px]"
    : "!w-5 !h-2 !rounded-sm !bg-primary !border-0 !bottom-[-4px]";

  return (
    <div
      aria-label="Workflow trigger node"
      className={cn(
        "relative rounded-2xl border-2 border-primary/40 bg-gradient-to-br from-primary/15 via-primary/5 to-transparent",
        "px-5 py-3 shadow-lg shadow-primary/10 min-w-[160px]",
        "flex flex-col items-center gap-1 transition-all duration-150",
        "hover:shadow-xl hover:shadow-primary/20 hover:border-primary/60",
        selected && "ring-2 ring-primary ring-offset-2 ring-offset-background shadow-lg shadow-primary/25",
      )}
    >
      {/* Icon + label */}
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/20">
          <Zap className="h-4 w-4 text-primary" />
        </div>
        <div>
          <div className="text-[9px] uppercase tracking-widest text-primary/70 font-semibold leading-none">Trigger</div>
          <div className="text-xs font-semibold truncate max-w-[140px]">{data.label || "Start"}</div>
        </div>
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={sourcePos}
        className={sourceHandleClass}
      />
      {!isHorizontal && (
        <div className="absolute -bottom-5 left-1/2 -translate-x-1/2 pointer-events-none">
          <span className="text-[8px] font-semibold uppercase tracking-widest text-primary/50 mt-0.5 select-none">out</span>
        </div>
      )}
    </div>
  );
}
