import { Activity, BookOpen, Bot, GitBranch, FlaskConical, Inbox, MessageSquare, Package, Play, Plug, Plus, Radar, RefreshCw, PanelLeftClose, PanelLeft, Search, Blocks, Settings, ShieldCheck, ShieldAlert, Trash2, Webhook } from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AgentVisualSignals } from "@/lib/agentSignals";
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
  signals?: AgentVisualSignals;
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
  onDeleteItem?: (id: string) => void;
}

const VIEW_META: Record<WorkspaceView, { label: string; icon: typeof Bot }> = {
  agents: { label: "Agents", icon: Bot },
  chat: { label: "Chat", icon: MessageSquare },
  workflows: { label: "Workflows", icon: GitBranch },
  composer: { label: "Composer", icon: Blocks },
  evals: { label: "Evals", icon: FlaskConical },
  catalog: { label: "Catalog", icon: Package },
  policies: { label: "Policies", icon: ShieldAlert },
  intelligence: { label: "Intelligence", icon: Radar },
  mcp: { label: "MCP Servers", icon: Plug },
  settings: { label: "Settings", icon: Settings },
  admin: { label: "Admin", icon: ShieldCheck },
  observatory: { label: "Observatory", icon: Activity },
  docs: { label: "Documentation", icon: BookOpen },
  webhooks: { label: "Webhooks", icon: Webhook },
};

function statusDotClasses(status: string): string {
  switch (status) {
    case "running":
      return "bg-success animate-[breathe-pulse_2s_cubic-bezier(0.2,0,0.38,0.9)_infinite]";
    case "succeeded":
    case "completed":
      return "bg-success";
    case "pending":
    case "queued":
    case "progressing":
      return "bg-warning animate-[breathe-pulse_2s_cubic-bezier(0.2,0,0.38,0.9)_infinite]";
    case "failed":
    case "error":
      return "bg-destructive";
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
  onDeleteItem,
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
        item.subtitle.toLowerCase().includes(lower) ||
        (item.note ?? "").toLowerCase().includes(lower) ||
        (item.signals?.runtime.label.toLowerCase().includes(lower) ?? false) ||
        (item.signals?.access.label.toLowerCase().includes(lower) ?? false) ||
        (item.signals?.capabilities.some((capability) => capability.label.toLowerCase().includes(lower) || capability.shortLabel.toLowerCase().includes(lower)) ?? false),
    );
  }, [items, debouncedFilter]);
  if (collapsed) {
    return (
      <TooltipProvider delayDuration={100}>
        <aside className="flex w-14 flex-col items-center border-r border-sidebar-border/80 bg-sidebar/92 backdrop-blur-xl">
          {/* Match header height */}
          <div className="flex h-10 w-full items-center justify-center border-b border-sidebar-border/80">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon" className="h-9 w-9 rounded-xl text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-accent-foreground" onClick={onToggleCollapse} aria-label="Expand sidebar">
                  <PanelLeft className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">Expand sidebar</TooltipContent>
            </Tooltip>
          </div>
          <nav className="flex flex-col items-center gap-1 py-2" aria-label="Workspace views">
            {visibleViews.map((view) => {
              const { icon: Icon, label } = VIEW_META[view];
              const isActive = activeView === view;
              return (
                <Tooltip key={view}>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className={cn(
                        "h-9 w-9 rounded-xl transition-colors duration-150 ease-productive",
                        isActive ? "bg-sidebar-primary/15 text-primary shadow-sm hover:bg-sidebar-primary/18" : "text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-accent-foreground",
                      )}
                      onClick={() => onViewChange(view)}
                      aria-label={`${label} (${counts[view]})`}
                      aria-pressed={isActive}
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
          </nav>
          {canMutate && (
            <div className="mt-auto border-t border-sidebar-border/80 py-2">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-9 w-9 rounded-xl text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-accent-foreground" onClick={onCreateNew} aria-label="Create new">
                    <Plus className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="right">Create new</TooltipContent>
              </Tooltip>
            </div>
          )}
        </aside>
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={100}>
    <aside className="flex h-full w-full min-w-0 flex-col border-r border-sidebar-border/80 bg-sidebar/92 backdrop-blur-xl">
      {/* Header */}
      <div className="flex h-10 items-center justify-between border-b border-sidebar-border/80 px-2.5">
        <div className="min-w-0">
          <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-muted-foreground">Workspace</p>
          <p className="truncate text-sm font-semibold text-sidebar-foreground">{VIEW_META[activeView].label}</p>
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0 rounded-xl text-muted-foreground hover:bg-sidebar-accent/75 hover:text-sidebar-accent-foreground" onClick={onToggleCollapse} aria-label="Collapse sidebar">
          <PanelLeftClose className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* Vertical nav */}
      <nav className="border-b border-sidebar-border/80 px-1.5 py-1.5" aria-label="Workspace views">
        <div className="space-y-0.5">
          {visibleViews.map((view) => {
            const { icon: Icon, label } = VIEW_META[view];
            const count = counts[view];
            const isActive = activeView === view;
            return (
              <button
                key={view}
                onClick={() => onViewChange(view)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg border px-2 py-1 text-xs font-medium transition-all duration-150 ease-productive",
                  isActive
                    ? "border-sidebar-border bg-sidebar-primary/15 text-sidebar-foreground shadow-sm"
                    : "border-transparent text-muted-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground",
                )}
                aria-label={`${label} (${count})`}
                aria-pressed={isActive}
              >
                <Icon className={cn("h-4 w-4 shrink-0 transition-colors", isActive ? "text-primary" : "")} />
                <span className="flex-1 text-left">{label}</span>
                {count > 0 && (
                  <span
                    className={cn(
                      "ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full border px-1.5 text-[10px] font-semibold tabular-nums",
                      isActive ? "border-primary/25 bg-primary/14 text-primary" : "border-border/55 bg-secondary/70 text-muted-foreground",
                    )}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Actions */}
      <div className="flex gap-1.5 border-b border-sidebar-border/80 px-2.5 py-1.5">
        {canMutate && (
          <Button size="sm" className="h-8 flex-1 gap-1.5 rounded-xl text-xs" onClick={onCreateNew}>
            <Plus className="h-3.5 w-3.5" />
            New
          </Button>
        )}
        <Button variant="outline" size="icon" className="h-8 w-8 rounded-xl" onClick={onRefresh} disabled={loading} aria-label="Refresh list">
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
        </Button>
      </div>

      {/* Search */}
      <div className="border-b border-sidebar-border/80 px-2.5 py-1.5">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value)}
            placeholder={`Search ${VIEW_META[activeView].label.toLowerCase()}...`}
            className="h-9 border-sidebar-border/70 bg-card/68 pl-9 text-xs"
            aria-label="Filter resources"
          />
        </div>
      </div>

      {/* Resource list */}
      <ScrollArea className="flex-1">
        <div className="space-y-1 p-2" role="listbox" aria-label={`${VIEW_META[activeView].label} list`}>
          {loading && filteredItems.length === 0 && (
            <>
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="flex items-start gap-2 rounded-xl border border-transparent px-2.5 py-2">
                  <Skeleton className="mt-1 h-2 w-2 shrink-0 rounded-full" />
                  <div className="min-w-0 flex-1 space-y-1">
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
                !filter.trim() && canMutate && (activeView === "agents" || activeView === "chat" || activeView === "workflows" || activeView === "evals")
                  ? {
                      label: activeView === "chat" ? "Create Agent" : `Create ${VIEW_META[activeView].label.replace(/s$/, "")}`,
                      onClick: onCreateNew,
                    }
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
              onDelete={onDeleteItem}
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
  onDelete,
}: {
  item: SidebarResourceItem;
  index: number;
  isSelected: boolean;
  onSelect: (id: string) => void;
  onQuickRun?: (id: string) => void;
  quickRunLabel?: string;
  onDelete?: (id: string) => void;
}) {
  const actionLabel = quickRunLabel ? `${quickRunLabel} ${item.title}` : `Run ${item.title}`;
  const hasActions = onQuickRun || onDelete;
  const runtimeSignal = item.signals?.runtime;
  const accessSignal = item.signals?.access;
  const secondaryMeta = [item.note, runtimeSignal?.label, accessSignal?.label].filter(Boolean).join(" • ");
  return (
    <div
      role="option"
      aria-selected={isSelected}
      onClick={() => onSelect(item.id)}
      onKeyDown={(e) => { if (e.key === "Enter") onSelect(item.id); }}
      tabIndex={0}
      style={{ animationDelay: `${index * 30}ms` }}
      className={cn(
        "group flex w-full cursor-pointer flex-col rounded-[calc(var(--radius-lg)+2px)] border px-2.5 py-2 text-left text-sm",
        "transition-all duration-150 ease-productive hover:border-sidebar-border/65 hover:bg-sidebar-accent/55 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        "animate-slide-up opacity-0 [animation-fill-mode:forwards]",
        isSelected ? "border-sidebar-border bg-sidebar-accent/82 shadow-sm" : "border-transparent",
      )}
    >
      <div className="flex w-full items-start gap-2.5">
        {runtimeSignal ? (
          <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border shadow-inner", runtimeSignal.tone)} aria-hidden="true">
            <runtimeSignal.icon className="h-4 w-4" />
          </span>
        ) : (
          <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", statusDotClasses(item.status))} aria-hidden="true" />
        )}
        <span className="sr-only">Status: {item.status}</span>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 flex-1 line-clamp-2 break-words text-[12.5px] font-medium leading-5 text-sidebar-foreground">{item.title}</p>
            {runtimeSignal ? <span className={cn("mt-1 inline-flex h-2 w-2 shrink-0 rounded-full", statusDotClasses(item.status))} aria-hidden="true" /> : null}
          </div>
          <p className="line-clamp-1 break-all text-[11px] leading-5 text-muted-foreground">{item.subtitle}</p>
          {secondaryMeta ? <p className="line-clamp-2 break-all text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground/85">{secondaryMeta}</p> : null}
        </div>
      </div>
      {hasActions && (
        <div
          className={cn(
            "mt-2 items-center gap-1.5 group-focus-within:flex",
            isSelected ? "flex" : "hidden group-hover:flex",
            item.signals ? "ml-11" : "ml-4.5 pl-0.5",
          )}
        >
          {onQuickRun && (
            <span
              role="button"
              tabIndex={0}
              aria-label={actionLabel}
              title={actionLabel}
              onClick={(e) => { e.stopPropagation(); onQuickRun(item.id); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onQuickRun(item.id); } }}
              className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-card/64 px-2 py-1 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground hover:border-primary/25 hover:bg-primary/12 hover:text-primary"
            >
              <Play className="h-3 w-3" />
              {quickRunLabel}
            </span>
          )}
          {onDelete && (
            <span
              role="button"
              tabIndex={0}
              aria-label={`Delete ${item.title}`}
              title={`Delete ${item.title}`}
              onClick={(e) => { e.stopPropagation(); onDelete(item.id); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); onDelete(item.id); } }}
              className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-card/64 px-2 py-1 text-[10px] font-medium uppercase tracking-[0.1em] text-muted-foreground hover:border-destructive/25 hover:bg-destructive/12 hover:text-destructive"
            >
              <Trash2 className="h-3 w-3" />
              Delete
            </span>
          )}
        </div>
      )}
    </div>
  );
});
