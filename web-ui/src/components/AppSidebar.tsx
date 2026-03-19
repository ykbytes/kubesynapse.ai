import { Bot, GitBranch, FlaskConical, Inbox, Package, Play, Plus, RefreshCw, PanelLeftClose, PanelLeft, Search, Blocks, Settings, ShieldCheck, ShieldAlert } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { EmptyState } from "./EmptyState";
import { useConnection } from "@/contexts/ConnectionContext";
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
  isAdmin?: boolean;
  onViewChange: (view: WorkspaceView) => void;
  onRefresh: () => void;
  onSelect: (id: string) => void;
  onCreateNew: () => void;
  onQuickRun?: (id: string) => void;
  quickRunLabel?: string;
}

const VIEW_META: Record<WorkspaceView, { label: string; icon: typeof Bot }> = {
  agents: { label: "Agents", icon: Bot },
  workflows: { label: "Workflows", icon: GitBranch },
  composer: { label: "Composer", icon: Blocks },
  evals: { label: "Evals", icon: FlaskConical },
  catalog: { label: "Catalog", icon: Package },
  policies: { label: "Policies", icon: ShieldAlert },
  settings: { label: "Settings", icon: Settings },
  admin: { label: "Admin", icon: ShieldCheck },
};

function statusDotClasses(status: string): string {
  switch (status) {
    case "running":
      return "bg-emerald-500 animate-[breathe-pulse_2s_ease-in-out_infinite]";
    case "succeeded":
    case "completed":
      return "bg-emerald-500";
    case "pending":
    case "queued":
    case "progressing":
      return "bg-amber-500 animate-[breathe-pulse_2s_ease-in-out_infinite]";
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
  isAdmin,
  onViewChange,
  onRefresh,
  onSelect,
  onCreateNew,
  onQuickRun,
  quickRunLabel,
}: AppSidebarProps) {
  const { canMutate } = useConnection();
  const [filter, setFilter] = useState("");
  const [debouncedFilter, setDebouncedFilter] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const visibleViews = useMemo(() => {
    const all = Object.keys(VIEW_META) as WorkspaceView[];
    return isAdmin ? all : all.filter((v) => v !== "admin");
  }, [isAdmin]);

  const handleFilterChange = useCallback((value: string) => {
    setFilter(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedFilter(value), 150);
  }, []);

  // Cleanup debounce timer on unmount to prevent memory leak
  useEffect(() => {
    return () => { clearTimeout(debounceRef.current); };
  }, []);

  // Reset view-local filtering when switching sections so resources don't appear "missing"
  useEffect(() => {
    setFilter("");
    setDebouncedFilter("");
    clearTimeout(debounceRef.current);
  }, [activeView]);

  const filteredItems = useMemo(() => {
    if (!debouncedFilter.trim()) return items;
    const lower = debouncedFilter.toLowerCase();
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(lower) ||
        item.subtitle.toLowerCase().includes(lower),
    );
  }, [items, debouncedFilter]);
  if (collapsed) {
    return (
      <TooltipProvider delayDuration={100}>
        <aside className="flex w-12 flex-col items-center border-r border-border bg-sidebar py-2 gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onToggleCollapse} aria-label="Expand sidebar">
                <PanelLeft className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Expand sidebar</TooltipContent>
          </Tooltip>
          {visibleViews.map((view) => {
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
          {canMutate && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onCreateNew} aria-label="Create new">
                <Plus className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Create new</TooltipContent>
          </Tooltip>
          )}
        </aside>
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={100}>
    <aside className="flex w-64 flex-col border-r border-border bg-sidebar">
      {/* View tabs */}
      <div className="border-b border-border px-2 py-2">
        <div className="grid grid-cols-4 gap-1">
          {visibleViews.map((view) => {
            const { icon: Icon, label } = VIEW_META[view];
            const count = counts[view];
            const isActive = activeView === view;
            return (
              <Tooltip key={view}>
                <TooltipTrigger asChild>
                  <Button
                    variant={isActive ? "secondary" : "ghost"}
                    size="sm"
                    className="h-10 flex-col items-center justify-center gap-0 px-1"
                    onClick={() => onViewChange(view)}
                    aria-label={`${label} (${count})`}
                    aria-pressed={isActive}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" />
                    <span className="max-w-full truncate text-[10px] leading-none">{label}</span>
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">{label} ({count})</TooltipContent>
              </Tooltip>
            );
          })}
        </div>
        <div className="mt-1 flex justify-end">
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onToggleCollapse} aria-label="Collapse sidebar">
            <PanelLeftClose className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-1.5 border-b border-border px-3 py-2">
{canMutate && (
        <Button size="sm" className="h-7 flex-1 gap-1.5 text-xs" onClick={onCreateNew}>
          <Plus className="h-3.5 w-3.5" />
          New
        </Button>
)}
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
            onChange={(e) => handleFilterChange(e.target.value)}
            placeholder="Filter..."
            className="h-7 pl-7 text-xs"
            aria-label="Filter resources"
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
            <EmptyState
              icon={filter.trim() ? Search : Inbox}
              title={filter.trim() ? "No matches" : emptyMessage}
              description={filter.trim() ? `No items match "${debouncedFilter}"` : undefined}
              action={
                !filter.trim() && canMutate && (activeView === "agents" || activeView === "workflows" || activeView === "evals")
                  ? { label: `Create ${VIEW_META[activeView].label.replace(/s$/, "")}`, onClick: onCreateNew }
                  : undefined
              }
              className="py-8"
            />
          )}
          {filteredItems.map((item, index) => (
            <SidebarItem
              key={item.id}
              item={item}
              index={index}
              isSelected={selectedId === item.id}
              onSelect={onSelect}
              onQuickRun={onQuickRun}
              quickRunLabel={quickRunLabel}
            />
          ))}
        </div>
      </ScrollArea>
    </aside>
    </TooltipProvider>
  );
}

const SidebarItem = memo(function SidebarItem({
  item,
  index,
  isSelected,
  onSelect,
  onQuickRun,
  quickRunLabel,
}: {
  item: SidebarResourceItem;
  index: number;
  isSelected: boolean;
  onSelect: (id: string) => void;
  onQuickRun?: (id: string) => void;
  quickRunLabel?: string;
}) {
  const actionLabel = quickRunLabel ? `${quickRunLabel} ${item.title}` : `Run ${item.title}`;
  return (
    <button
      type="button"
      role="option"
      aria-selected={isSelected}
      onClick={() => onSelect(item.id)}
      style={{ animationDelay: `${index * 30}ms` }}
      className={cn(
        "group flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm",
        "transition-all duration-150 hover:bg-sidebar-accent/80 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        "animate-slide-up opacity-0 [animation-fill-mode:forwards]",
        isSelected && "bg-sidebar-accent border-l-2 border-primary shadow-md shadow-primary/10",
      )}
    >
      <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", statusDotClasses(item.status))} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium text-sidebar-foreground">{item.title}</p>
        <p className="truncate text-xs text-muted-foreground">{item.subtitle}</p>
      </div>
      {onQuickRun && (
        <span
          role="button"
          tabIndex={0}
          aria-label={actionLabel}
          title={actionLabel}
          onClick={(e) => { e.stopPropagation(); onQuickRun(item.id); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onQuickRun(item.id); } }}
          className="mt-0.5 hidden shrink-0 rounded-md p-1 text-muted-foreground hover:bg-primary/20 hover:text-primary group-hover:inline-flex"
        >
          <Play className="h-3.5 w-3.5" />
        </span>
      )}
    </button>
  );
});
