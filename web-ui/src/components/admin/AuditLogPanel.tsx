import { useCallback, useEffect, useMemo, useState } from "react";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  fetchAuditLogs,
  purgeAuditLogs,
  type AuditLogEntry,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  AlertTriangle,
  Shield,
  Search,
  ChevronLeft,
  ChevronRight,
  Trash2,
  RefreshCw,
  User,
  Bot,
  Server,
  Link,
  CheckCircle2,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { EmptyState } from "../shared/EmptyState";

const PAGE_SIZE = 50;

const ACTION_COLORS: Record<string, string> = {
  created: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  updated: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  deleted: "bg-red-500/10 text-red-400 border-red-500/20",
  invoked: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  approved: "bg-green-500/10 text-green-400 border-green-500/20",
  denied: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  triggered: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  cancelled: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  login: "bg-teal-500/10 text-teal-400 border-teal-500/20",
  login_failed: "bg-red-500/10 text-red-400 border-red-500/20",
  registered: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
  purged: "bg-gray-500/10 text-gray-400 border-gray-500/20",
};

function ActorTypeIcon({ type }: { type: string | null }) {
  switch (type) {
    case "user":
      return <User className="h-3 w-3" />;
    case "operator":
      return <Server className="h-3 w-3" />;
    case "a2a":
      return <Link className="h-3 w-3" />;
    default:
      return <Bot className="h-3 w-3" />;
  }
}

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  return `${days}d ago`;
}

export function AuditLogPanel() {
  const conn = useConnection();
  const [items, setItems] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);

  // Filters
  const [actorFilter, setActorFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [resourceKindFilter, setResourceKindFilter] = useState("");
  const [searchText, setSearchText] = useState("");

  const filters = useMemo(
    () => ({
      actor: actorFilter || undefined,
      action: actionFilter || undefined,
      resource_kind: resourceKindFilter || undefined,
      resource_name: searchText || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [actorFilter, actionFilter, resourceKindFilter, searchText, page],
  );

  const loadData = useCallback(async () => {
    if (!conn.token) return;
    setLoading(true);
    try {
      const result = await fetchAuditLogs(conn.token, filters);
      setItems(result.items);
      setTotal(result.total);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [conn.token, filters]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const activeFilters = useMemo(
    () => [
      actorFilter ? { label: "Actor", value: actorFilter } : null,
      actionFilter ? { label: "Action", value: actionFilter } : null,
      resourceKindFilter ? { label: "Kind", value: resourceKindFilter } : null,
      searchText ? { label: "Name", value: searchText } : null,
    ].filter((item): item is { label: string; value: string } => Boolean(item)),
    [actionFilter, actorFilter, resourceKindFilter, searchText],
  );
  const summary = useMemo(() => {
    const riskyActions = new Set(["login_failed", "denied", "deleted", "purged", "cancelled"]);
    const approvalActions = new Set(["approved", "denied"]);
    return {
      visible: items.length,
      risky: items.filter((item) => riskyActions.has(item.action)).length,
      approvals: items.filter((item) => approvalActions.has(item.action)).length,
      uniqueActors: new Set(items.map((item) => item.actor || "system")).size,
    };
  }, [items]);
  const resetFilters = useCallback(() => {
    setActorFilter("");
    setActionFilter("");
    setResourceKindFilter("");
    setSearchText("");
    setPage(0);
  }, []);

  const handlePurge = useCallback(async () => {
    if (!conn.token) return;
    if (!window.confirm("Purge audit records older than retention period?")) return;
    try {
      const result = await purgeAuditLogs(conn.token);
      toast.success(`Purged ${result.deleted} old audit records`);
      loadData();
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }, [conn.token, loadData]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">Audit Log</h2>
          <Badge variant="outline" className="text-[10px]">{total} records</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1 cursor-pointer" onClick={loadData}>
            <RefreshCw className="h-3 w-3" /> Refresh
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs gap-1 text-destructive cursor-pointer" onClick={handlePurge}>
            <Trash2 className="h-3 w-3" /> Purge Old
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="px-4 py-3 border-b shrink-0 space-y-3">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Card className="border-border/60 bg-card/70 shadow-none">
            <CardContent className="py-3">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Visible events</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{summary.visible}</div>
              <p className="mt-1 text-xs text-muted-foreground">Current page results after filters and namespace scoping.</p>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/70 shadow-none">
            <CardContent className="py-3">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Risk signals</div>
              <div className="mt-1 flex items-center gap-2 text-lg font-semibold text-foreground">
                {summary.risky}
                {summary.risky > 0 ? <AlertTriangle className="h-4 w-4 text-amber-400" /> : <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">Denied, destructive, cancelled, or failed auth events in view.</p>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/70 shadow-none">
            <CardContent className="py-3">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Approvals</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{summary.approvals}</div>
              <p className="mt-1 text-xs text-muted-foreground">Decision events that explain how humans are gating sensitive actions.</p>
            </CardContent>
          </Card>
          <Card className="border-border/60 bg-card/70 shadow-none">
            <CardContent className="py-3">
              <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">Actors</div>
              <div className="mt-1 text-lg font-semibold text-foreground">{summary.uniqueActors}</div>
              <p className="mt-1 text-xs text-muted-foreground">Distinct users, agents, or operator identities represented in this slice.</p>
            </CardContent>
          </Card>
        </div>

        <div className="flex items-end gap-3 flex-wrap">
        <div className="space-y-1">
          <Label className="text-[10px]">Actor</Label>
          <Input
            value={actorFilter}
            onChange={(e) => { setActorFilter(e.target.value); setPage(0); }}
            placeholder="Username"
            className="h-7 text-xs w-28"
          />
        </div>
        <div className="space-y-1">
          <Label className="text-[10px]">Action</Label>
          <Select value={actionFilter} onValueChange={(v) => { setActionFilter(v === "all" ? "" : v); setPage(0); }}>
            <SelectTrigger className="h-7 text-xs w-32">
              <SelectValue placeholder="All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {["created", "updated", "deleted", "invoked", "approved", "denied", "triggered", "cancelled", "login", "login_failed", "registered"].map((a) => (
                <SelectItem key={a} value={a}>{a}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-[10px]">Resource Kind</Label>
          <Select value={resourceKindFilter} onValueChange={(v) => { setResourceKindFilter(v === "all" ? "" : v); setPage(0); }}>
            <SelectTrigger className="h-7 text-xs w-32">
              <SelectValue placeholder="All" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {["agent", "workflow", "eval", "policy", "tenant", "user", "session", "audit"].map((k) => (
                <SelectItem key={k} value={k}>{k}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label className="text-[10px]">Resource Name</Label>
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
            <Input
              value={searchText}
              onChange={(e) => { setSearchText(e.target.value); setPage(0); }}
              placeholder="Search..."
              className="h-7 text-xs w-36 pl-6"
            />
          </div>
        </div>

          {activeFilters.length > 0 && (
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={resetFilters}>
              Clear filters
            </Button>
          )}
        </div>

        {activeFilters.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {activeFilters.map((filter) => (
              <Badge key={`${filter.label}:${filter.value}`} variant="outline" className="text-[10px]">
                {filter.label}: {filter.value}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Table */}
      <ScrollArea className="flex-1 min-h-0">
        {loading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={activeFilters.length > 0 ? Search : ShieldCheck}
              title={activeFilters.length > 0 ? "No events match the current filters" : "Audit history will appear here"}
              description={activeFilters.length > 0 ? "Broaden the filters to review a wider slice of actor, resource, and approval activity." : "Once users, agents, and operator actions move through the platform, this panel becomes the source of truth for governance review."}
              action={activeFilters.length > 0 ? { label: "Clear filters", onClick: resetFilters } : undefined}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted/50 backdrop-blur-sm z-10">
              <tr className="border-b text-muted-foreground text-left">
                <th className="px-3 py-2 font-medium">Time</th>
                <th className="px-3 py-2 font-medium">Actor</th>
                <th className="px-3 py-2 font-medium">Action</th>
                <th className="px-3 py-2 font-medium">Resource</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">IP</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr key={entry.id} className="border-b border-border/30 hover:bg-muted/20 transition-colors">
                  <td className="px-3 py-2 text-muted-foreground whitespace-nowrap" title={entry.timestamp ?? undefined}>
                    {relativeTime(entry.timestamp)}
                  </td>
                  <td className="px-3 py-2">
                    <span className="inline-flex items-center gap-1">
                      <ActorTypeIcon type={entry.actor_type} />
                      <span className="truncate max-w-[120px]">{entry.actor ?? "system"}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="outline" className={cn("text-[9px]", ACTION_COLORS[entry.action] ?? "")}>
                      {entry.action}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{entry.resource_kind ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-[10px] truncate max-w-[160px]" title={entry.resource_name ?? undefined}>
                    {entry.resource_name ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground font-mono text-[10px]">{entry.ip_address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </ScrollArea>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="px-4 py-2 border-t flex items-center justify-between text-xs shrink-0">
          <span className="text-muted-foreground">Page {page + 1} of {totalPages}</span>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" className="h-7 cursor-pointer" disabled={page === 0} onClick={() => setPage((p) => p - 1)} aria-label="Previous page">
              <ChevronLeft className="h-3 w-3" />
            </Button>
            <Button variant="ghost" size="sm" className="h-7 cursor-pointer" disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)} aria-label="Next page">
              <ChevronRight className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
