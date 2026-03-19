import { useMemo, useState, type DragEvent } from "react";
import type { AgentInfo } from "@/types";
import { Bot, Brain, Bird, Code, Terminal, GripVertical, Search, ChevronDown, ChevronRight, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface NodePaletteProps {
  agents: AgentInfo[];
  collapsed: boolean;
  onToggleCollapse: () => void;
}

function runtimeIcon(kind?: string | null) {
  const cls = "h-3.5 w-3.5 shrink-0";
  switch (kind) {
    case "langgraph":
      return <Brain className={cn(cls, "text-violet-400")} />;
    case "goose":
      return <Bird className={cn(cls, "text-amber-400")} />;
    case "opencode":
      return <Code className={cn(cls, "text-sky-400")} />;
    case "codex":
      return <Terminal className={cn(cls, "text-emerald-400")} />;
    default:
      return <Bot className={cn(cls, "text-muted-foreground")} />;
  }
}

function statusDot(status?: string) {
  const color =
    status === "Running" || status === "running"
      ? "bg-emerald-500"
      : status === "Failed" || status === "failed"
        ? "bg-red-500"
        : "bg-muted-foreground/40";
  return <span className={cn("h-1.5 w-1.5 rounded-full shrink-0", color)} />;
}

export function NodePalette({ agents, collapsed, onToggleCollapse }: NodePaletteProps) {
  const [search, setSearch] = useState("");
  const [groupCollapsed, setGroupCollapsed] = useState<Record<string, boolean>>({});

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    if (!q) return agents;
    return agents.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        (a.runtime_kind ?? "").toLowerCase().includes(q),
    );
  }, [agents, search]);

  const grouped = useMemo(() => {
    const map = new Map<string, AgentInfo[]>();
    for (const a of filtered) {
      const key = a.runtime_kind ?? "other";
      const list = map.get(key) ?? [];
      list.push(a);
      map.set(key, list);
    }
    return map;
  }, [filtered]);

  function onDragStart(e: DragEvent<HTMLDivElement>, agentName: string) {
    e.dataTransfer.setData("application/kubemininions-agent", agentName);
    e.dataTransfer.effectAllowed = "move";
  }

  function toggleGroup(key: string) {
    setGroupCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div
      className={cn(
        "border-r bg-muted/20 flex flex-col overflow-hidden shrink-0 transition-[width] duration-200 ease-out",
        collapsed ? "w-10" : "w-52",
      )}
    >
      {/* Collapsed strip */}
      {collapsed ? (
        <div className="flex flex-col items-center py-2 gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 cursor-pointer"
            onClick={onToggleCollapse}
            title="Expand palette (Ctrl+B)"
          >
            <PanelLeftOpen className="h-3.5 w-3.5" />
          </Button>
          <span className="text-[9px] font-semibold text-muted-foreground uppercase tracking-wider [writing-mode:vertical-lr] rotate-180 select-none">
            Agents
          </span>
        </div>
      ) : (
        <>
      <div className="px-3 py-2 border-b space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
            Node Palette
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0 cursor-pointer text-muted-foreground hover:text-foreground"
            onClick={onToggleCollapse}
            title="Collapse palette (Ctrl+B)"
          >
            <PanelLeftClose className="h-3 w-3" />
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground/60" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search agents…"
            className="h-7 text-xs pl-7"
          />
        </div>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {Array.from(grouped.entries()).map(([kind, group]) => {
            const isCollapsed = groupCollapsed[kind];
            return (
              <div key={kind}>
                {/* Category header */}
                <button
                  type="button"
                  className="flex items-center gap-1.5 w-full px-1 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors cursor-pointer"
                  onClick={() => toggleGroup(kind)}
                  aria-expanded={!isCollapsed}
                >
                  {isCollapsed ? (
                    <ChevronRight className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                  {runtimeIcon(kind)}
                  <span className="flex-1 text-left">{kind}</span>
                  <span className="text-[9px] text-muted-foreground/60">{group.length}</span>
                </button>

                {!isCollapsed && (
                  <div className="space-y-0.5 ml-1">
                    {group.map((a) => (
                      <div
                        key={a.name}
                        draggable
                        onDragStart={(e) => onDragStart(e, a.name)}
                        className="flex items-center gap-1.5 rounded-lg border border-transparent bg-card/60 px-2 py-1.5 text-xs cursor-grab active:cursor-grabbing hover:bg-accent hover:border-border transition-colors group"
                        title={`Drag "${a.name}" onto the canvas to add a step`}
                        aria-label={`${a.name} — drag to add step`}
                      >
                        <GripVertical className="h-3 w-3 text-muted-foreground/30 group-hover:text-muted-foreground/60 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1">
                            {statusDot(a.status)}
                            <span className="truncate font-medium">{a.name}</span>
                          </div>
                          {a.model && (
                            <div className="text-[9px] text-muted-foreground/60 font-mono truncate ml-3">
                              {a.model}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {filtered.length === 0 && agents.length > 0 && (
            <div className="text-center py-4 px-2">
              <Search className="h-5 w-5 text-muted-foreground/40 mx-auto mb-1.5" />
              <p className="text-[10px] text-muted-foreground">No agents match "{search}"</p>
            </div>
          )}

          {agents.length === 0 && (
            <div className="text-center py-6 px-2">
              <Bot className="h-6 w-6 text-muted-foreground/40 mx-auto mb-1.5" />
              <p className="text-[10px] text-muted-foreground">
                No agents available. Switch to the Agents view to create one first.
              </p>
            </div>
          )}
        </div>
      </ScrollArea>
        </>
      )}
    </div>
  );
}
