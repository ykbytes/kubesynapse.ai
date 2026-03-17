import type { AgentInfo } from "@/types";
import { Bot, Plus } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { DragEvent } from "react";

interface NodePaletteProps {
  agents: AgentInfo[];
}

export function NodePalette({ agents }: NodePaletteProps) {
  function onDragStart(e: DragEvent<HTMLDivElement>, agentName: string) {
    e.dataTransfer.setData("application/kubemininions-agent", agentName);
    e.dataTransfer.effectAllowed = "move";
  }

  return (
    <div className="w-48 border-r bg-muted/30 flex flex-col overflow-hidden shrink-0">
      <div className="px-3 py-2 text-xs font-semibold text-muted-foreground border-b">
        Agents ({agents.length})
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {agents.map((a) => (
            <div
              key={a.name}
              draggable
              onDragStart={(e) => onDragStart(e, a.name)}
              className="flex items-center gap-2 rounded-md border bg-card px-2 py-1.5 text-xs cursor-grab active:cursor-grabbing hover:bg-accent transition-colors"
              title={`Drag "${a.name}" onto the canvas to add a step`}
            >
              <Bot className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <div className="truncate font-medium">{a.name}</div>
                {a.runtime_kind && (
                  <div className="text-[10px] text-muted-foreground truncate">{a.runtime_kind}</div>
                )}
              </div>
              <Plus className="h-3 w-3 text-muted-foreground/50 shrink-0 ml-auto" />
            </div>
          ))}
          {agents.length === 0 && (
            <div className="text-center py-4 px-2">
              <Bot className="h-6 w-6 text-muted-foreground/40 mx-auto mb-1.5" />
              <p className="text-[10px] text-muted-foreground">
                No agents available. Switch to the Agents view to create one first.
              </p>
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
