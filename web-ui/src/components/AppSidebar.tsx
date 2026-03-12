import { Bot, GitBranch, FlaskConical, Package, Plus, RefreshCw, PanelLeftClose, PanelLeft, Search } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import type { WorkspaceView } from "@/types";

export interface SidebarResourceItem {
  id: string;
  title: string;
  subtitle: string;
  status: string;
  note?: string;
}

interface AppSidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
  activeView: WorkspaceView;
  counts: Record<WorkspaceView, number>;
  items: SidebarResourceItem[];
  selectedId: string;
  loading: boolean;
  emptyMessage: string;
  onViewChange: (view: WorkspaceView) => void;
  onRefresh: () => void;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
}

const VIEW_META: Record<WorkspaceView, { label: string; icon: typeof Bot }> = {
  agents: { label: "Agents", icon: Bot },
  workflows: { label: "Workflows", icon: GitBranch },
  evals: { label: "Evals", icon: FlaskConical },
  catalog: { label: "Catalog", icon: Package },
};

function statusColor(status: string): string {
  switch (status) {
    case "running":
    case "succeeded":
    case "completed":
      return "bg-emerald-500";
    case "pending":
    case "queued":
    case "progressing":
      return "bg-amber-500";
    case "failed":
    case "error":
      return "bg-red-500";
    default:
      return "bg-muted-foreground/40";
  }
}

export function AppSidebar({
  collapsed,
  onToggleCollapse,
  activeView,
  counts,
  items,
  selectedId,
  loading,
  emptyMessage,
  onViewChange,
  onRefresh,
  onSelect,
  onCreateNew,
}: AppSidebarProps) {
  const [filter, setFilter] = useState("");
  const filteredItems = filter.trim()
    ? items.filter(
        (item) =>
          item.title.toLowerCase().includes(filter.toLowerCase()) ||
          item.subtitle.toLowerCase().includes(filter.toLowerCase()),
      )
    : items;
  if (collapsed) {
    return (
      <TooltipProvider delayDuration={0}>
        <aside className="flex w-12 flex-col items-center border-r border-border bg-sidebar py-2 gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onToggleCollapse} aria-label="Expand sidebar">
                <PanelLeft className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Expand sidebar</TooltipContent>
          </Tooltip>
          {(Object.keys(VIEW_META) as WorkspaceView[]).map((view) => {
            const { icon: Icon, label } = VIEW_META[view];
            return (
              <Tooltip key={view}>
                <TooltipTrigger asChild>
                  <Button
                    variant={activeView === view ? "secondary" : "ghost"}
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => onViewChange(view)}
                    aria-label={`${label} (${counts[view]})`}
                    aria-pressed={activeView === view}
                  >
                    <Icon className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {label} ({counts[view]})
                </TooltipContent>
              </Tooltip>
            );
          })}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onCreateNew} aria-label="Create new">
                <Plus className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Create new</TooltipContent>
          </Tooltip>
        </aside>
      </TooltipProvider>
    );
  }

  return (
    <aside className="flex w-64 flex-col border-r border-border bg-sidebar">
      {/* View tabs */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex gap-1">
          {(Object.keys(VIEW_META) as WorkspaceView[]).map((view) => {
            const { icon: Icon, label } = VIEW_META[view];
            return (
              <Button
                key={view}
                variant={activeView === view ? "secondary" : "ghost"}
                size="sm"
                className="h-7 gap-1.5 px-2 text-xs"
                onClick={() => onViewChange(view)}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{label}</span>
                <Badge variant="outline" className="ml-0.5 h-4 px-1 text-[10px]">
                  {counts[view]}
                </Badge>
              </Button>
            );
          })}
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onToggleCollapse}>
          <PanelLeftClose className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Actions */}
      <div className="flex gap-1.5 border-b border-border px-3 py-2">
        <Button size="sm" className="h-7 flex-1 gap-1.5 text-xs" onClick={onCreateNew}>
          <Plus className="h-3.5 w-3.5" />
          New
        </Button>
        <Button variant="outline" size="icon" className="h-7 w-7" onClick={onRefresh} disabled={loading} aria-label="Refresh list">
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter..."
            className="h-7 pl-7 text-xs"
          />
        </div>
      </div>

      {/* Resource list */}
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1" role="listbox" aria-label={`${VIEW_META[activeView].label} list`}>
          {loading && filteredItems.length === 0 && (
            <>
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex items-start gap-2.5 rounded-md px-2.5 py-2">
                  <Skeleton className="mt-1.5 h-2 w-2 shrink-0 rounded-full" />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Skeleton className="h-3.5 w-3/4 rounded" />
                    <Skeleton className="h-3 w-1/2 rounded" />
                  </div>
                </div>
              ))}
            </>
          )}
          {!loading && filteredItems.length === 0 && (
            <p className="px-2 py-4 text-center text-xs text-muted-foreground">
              {filter.trim() ? "No matches" : emptyMessage}
            </p>
          )}
          {filteredItems.map((item) => (
            <button
              key={item.id}
              type="button"
              role="option"
              aria-selected={selectedId === item.id}
              onClick={() => onSelect(item.id)}
              className={cn(
                "flex w-full items-start gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-sidebar-accent animate-fade-in",
                selectedId === item.id && "bg-sidebar-accent border-l-2 border-primary",
              )}
            >
              <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", statusColor(item.status))} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-sidebar-foreground">{item.title}</p>
                <p className="truncate text-xs text-muted-foreground">{item.subtitle}</p>
              </div>
            </button>
          ))}
        </div>
      </ScrollArea>
    </aside>
  );
}
