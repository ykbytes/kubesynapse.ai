import { useCallback, useEffect, useMemo, useState } from "react";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  fetchUsageSummary,
  fetchUsageDetail,
  type UsageSummaryItem,
  type UsageDetailItem,
} from "@/lib/api";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { RefreshCw, DollarSign, Cpu, BarChart3, Layers } from "lucide-react";

const GROUP_OPTIONS = [
  { value: "agent", label: "By Agent" },
  { value: "model", label: "By Model" },
  { value: "user", label: "By User" },
  { value: "day", label: "By Day" },
] as const;

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(n: number): string {
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export default function UsageDashboard() {
  const { token } = useConnection();
  const [summary, setSummary] = useState<UsageSummaryItem[]>([]);
  const [detail, setDetail] = useState<UsageDetailItem[]>([]);
  const [detailTotal, setDetailTotal] = useState(0);
  const [groupBy, setGroupBy] = useState("agent");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [detailPage, setDetailPage] = useState(0);
  const PAGE_SIZE = 50;

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [summaryData, detailData] = await Promise.all([
        fetchUsageSummary(token, {
          group_by: groupBy,
          from_date: fromDate || undefined,
          to_date: toDate || undefined,
        }),
        fetchUsageDetail(token, {
          from_date: fromDate || undefined,
          to_date: toDate || undefined,
          limit: PAGE_SIZE,
          offset: detailPage * PAGE_SIZE,
        }),
      ]);
      setSummary(summaryData);
      setDetail(detailData.items);
      setDetailTotal(detailData.total);
    } catch (e) {
      toast.error("Failed to load usage data");
    } finally {
      setLoading(false);
    }
  }, [token, groupBy, fromDate, toDate, detailPage]);

  useEffect(() => {
    load();
  }, [load]);

  const totals = useMemo(() => {
    let prompt = 0,
      completion = 0,
      total = 0,
      cost = 0,
      invocations = 0;
    for (const s of summary) {
      prompt += s.prompt_tokens;
      completion += s.completion_tokens;
      total += s.total_tokens;
      cost += s.estimated_cost_usd;
      invocations += s.invocations;
    }
    return { prompt, completion, total, cost, invocations };
  }, [summary]);

  const maxTokens = useMemo(
    () => Math.max(1, ...summary.map((s) => s.total_tokens)),
    [summary],
  );

  return (
    <div className="space-y-6 p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Token Usage & Cost</h2>
        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="w-36 h-8 text-xs"
            placeholder="From"
          />
          <Input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="w-36 h-8 text-xs"
            placeholder="To"
          />
          <Select value={groupBy} onValueChange={setGroupBy}>
            <SelectTrigger className="w-32 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {GROUP_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      {loading && summary.length === 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-3 w-24 rounded" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-7 w-20 rounded mb-1" />
                <Skeleton className="h-3 w-32 rounded" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Cpu className="h-3.5 w-3.5" /> Total Tokens
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{formatTokens(totals.total)}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {formatTokens(totals.prompt)} prompt · {formatTokens(totals.completion)} completion
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <DollarSign className="h-3.5 w-3.5" /> Estimated Cost
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{formatCost(totals.cost)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5" /> Invocations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{totals.invocations.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <BarChart3 className="h-3.5 w-3.5" /> Groups
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{summary.length}</p>
          </CardContent>
        </Card>
      </div>
      )}

      {/* Bar chart (simple CSS) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            Usage {GROUP_OPTIONS.find((o) => o.value === groupBy)?.label ?? ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {summary.length === 0 && (
            <p className="text-sm text-muted-foreground">No usage data for this period.</p>
          )}
          <div className="space-y-2">
            {summary.slice(0, 20).map((row) => (
              <div key={row.group} className="flex items-center gap-3 text-xs">
                <span className="w-32 truncate font-mono text-right" title={row.group}>
                  {row.group}
                </span>
                <div className="flex-1 bg-muted rounded-sm h-5 relative overflow-hidden">
                  <div
                    className="absolute inset-y-0 left-0 bg-teal-600 rounded-sm transition-all"
                    style={{
                      width: `${(row.total_tokens / maxTokens) * 100}%`,
                    }}
                  />
                  <span className="relative z-10 px-2 leading-5 text-white mix-blend-difference">
                    {formatTokens(row.total_tokens)}
                  </span>
                </div>
                <span className="w-16 text-right text-muted-foreground">
                  {formatCost(row.estimated_cost_usd)}
                </span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Detail table */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm">Recent Invocations</CardTitle>
          <span className="text-xs text-muted-foreground">{detailTotal} total</span>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3">Time</th>
                  <th className="py-2 pr-3">Agent</th>
                  <th className="py-2 pr-3">Model</th>
                  <th className="py-2 pr-3 text-right">Prompt</th>
                  <th className="py-2 pr-3 text-right">Completion</th>
                  <th className="py-2 pr-3 text-right">Total</th>
                  <th className="py-2 text-right">Cost</th>
                </tr>
              </thead>
              <tbody>
                {detail.map((row) => (
                  <tr key={row.id} className="border-b border-border/40">
                    <td className="py-1.5 pr-3 font-mono text-muted-foreground">
                      {row.timestamp
                        ? new Date(row.timestamp).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td className="py-1.5 pr-3 font-mono">{row.agent_name}</td>
                    <td className="py-1.5 pr-3 font-mono">{row.model ?? "—"}</td>
                    <td className="py-1.5 pr-3 text-right">{row.prompt_tokens.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right">{row.completion_tokens.toLocaleString()}</td>
                    <td className="py-1.5 pr-3 text-right font-medium">{row.total_tokens.toLocaleString()}</td>
                    <td className="py-1.5 text-right">
                      {row.estimated_cost_usd != null ? formatCost(row.estimated_cost_usd) : "—"}
                    </td>
                  </tr>
                ))}
                {detail.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-muted-foreground">
                      No invocations recorded yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {detailTotal > PAGE_SIZE && (
            <div className="flex justify-center gap-2 mt-4">
              <Button
                size="sm"
                variant="outline"
                disabled={detailPage === 0}
                onClick={() => setDetailPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-xs leading-8 text-muted-foreground">
                Page {detailPage + 1} of {Math.ceil(detailTotal / PAGE_SIZE)}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={(detailPage + 1) * PAGE_SIZE >= detailTotal}
                onClick={() => setDetailPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
