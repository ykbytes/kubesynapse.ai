import { useMemo } from "react";
import { CheckCircle, Download, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { EvalCaseResult, EvalInfo } from "@/types";

interface EvalResultsPanelProps {
  evalResource: EvalInfo;
}

function metricBadge(value: number, threshold: number | undefined, metric: string) {
  const isHigherBetter = metric === "relevance" || metric === "faithfulness";
  const isPass =
    threshold === undefined
      ? true
      : isHigherBetter
        ? value >= threshold
        : value <= threshold;

  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium tabular-nums ${
        isPass
          ? "bg-emerald-500/15 text-emerald-500"
          : "bg-red-500/15 text-red-500"
      }`}
    >
      {value.toFixed(2)}
      {isPass ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
    </span>
  );
}

function truncate(text: string, max = 80): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "…";
}

export function EvalResultsPanel({ evalResource }: EvalResultsPanelProps) {
  const cases = evalResource.cases ?? [];
  const summary = evalResource.summary ?? {};
  const thresholds = evalResource.failure_threshold ?? {};

  const stats = useMemo(() => {
    const total = cases.length;
    let passed = 0;
    let totalRelevance = 0;
    let totalFaithfulness = 0;
    let totalToxicity = 0;
    let totalLatency = 0;

    for (const c of cases) {
      const failed =
        c.status === "failed" ||
        c.status === "blocked" ||
        Boolean(c.error);
      if (!failed) passed++;
      totalRelevance += c.metrics?.relevance ?? 0;
      totalFaithfulness += c.metrics?.faithfulness ?? 0;
      totalToxicity += c.metrics?.toxicity ?? 0;
      totalLatency += c.latencyMs ?? 0;
    }

    return {
      total,
      passed,
      failed: total - passed,
      avgRelevance: total > 0 ? totalRelevance / total : 0,
      avgFaithfulness: total > 0 ? totalFaithfulness / total : 0,
      avgToxicity: total > 0 ? totalToxicity / total : 0,
      avgLatency: total > 0 ? totalLatency / total : 0,
      duration: (summary as Record<string, unknown>).completedAt && (summary as Record<string, unknown>).startedAt
        ? Math.round(
            (new Date(String((summary as Record<string, unknown>).completedAt)).getTime() -
              new Date(String((summary as Record<string, unknown>).startedAt)).getTime()) /
              1000,
          )
        : null,
    };
  }, [cases, summary]);

  const handleExportCsv = () => {
    const headers = [
      "Case",
      "Input",
      "Expected Output",
      "Response",
      "Status",
      "Error",
      "Relevance",
      "Faithfulness",
      "Toxicity",
      "Latency (ms)",
    ];
    const rows = cases.map((c, i) => [
      String(i + 1),
      `"${(c.input ?? "").replace(/"/g, '""')}"`,
      `"${(c.expectedOutput ?? "").replace(/"/g, '""')}"`,
      `"${(c.response ?? "").replace(/"/g, '""')}"`,
      c.status,
      `"${(c.error ?? "").replace(/"/g, '""')}"`,
      String(c.metrics?.relevance ?? ""),
      String(c.metrics?.faithfulness ?? ""),
      String(c.metrics?.toxicity ?? ""),
      String(c.latencyMs ?? ""),
    ]);

    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${evalResource.name}-results.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (cases.length === 0) {
    return (
      <Card className="mt-4">
        <CardContent className="py-6 text-center text-sm text-muted-foreground">
          {evalResource.phase === "running"
            ? `Running — ${(summary as Record<string, unknown>).completedCases ?? 0}/${(summary as Record<string, unknown>).caseCount ?? "?"} cases completed`
            : evalResource.phase === "pending"
              ? "Evaluation has not been run yet."
              : "No result data available for this evaluation."}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="mt-4 space-y-4">
      {/* ── Summary Cards ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Total</p>
            <p className="text-xl font-semibold tabular-nums">{stats.total}</p>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-emerald-500">Passed</p>
            <p className="text-xl font-semibold tabular-nums text-emerald-500">{stats.passed}</p>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-red-500">Failed</p>
            <p className="text-xl font-semibold tabular-nums text-red-500">{stats.failed}</p>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Avg Relevance</p>
            <p className="text-xl font-semibold tabular-nums">{stats.avgRelevance.toFixed(2)}</p>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Avg Faithfulness</p>
            <p className="text-xl font-semibold tabular-nums">{stats.avgFaithfulness.toFixed(2)}</p>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Avg Toxicity</p>
            <p className="text-xl font-semibold tabular-nums">{stats.avgToxicity.toFixed(3)}</p>
          </CardContent>
        </Card>
        <Card className="shadow-none">
          <CardContent className="p-3 text-center">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Duration</p>
            <p className="text-xl font-semibold tabular-nums">{stats.duration != null ? `${stats.duration}s` : "—"}</p>
          </CardContent>
        </Card>
      </div>

      {/* ── Overall pass/fail + export ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant={evalResource.passed ? "default" : "destructive"} className="gap-1">
            {evalResource.passed ? <CheckCircle className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
            {evalResource.passed ? "Passed" : "Failed"}
          </Badge>
          {evalResource.last_run && (
            <span className="text-xs text-muted-foreground">
              Last run: {new Date(evalResource.last_run).toLocaleString()}
            </span>
          )}
        </div>
        <Button variant="outline" size="sm" className="gap-1.5 text-xs" onClick={handleExportCsv}>
          <Download className="h-3.5 w-3.5" />
          Export CSV
        </Button>
      </div>

      {/* ── Results Table ── */}
      <Card className="overflow-hidden">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Test Case Results</CardTitle>
        </CardHeader>
        <ScrollArea className="max-h-[calc(100vh-480px)]">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-muted/50 sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground w-8">#</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Input</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Expected</th>
                <th className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground">Response</th>
                <th className="px-3 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">Relevance</th>
                <th className="px-3 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">Faithfulness</th>
                <th className="px-3 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">Toxicity</th>
                <th className="px-3 py-2 text-right text-xs font-medium uppercase tracking-wider text-muted-foreground">Latency</th>
                <th className="px-3 py-2 text-center text-xs font-medium uppercase tracking-wider text-muted-foreground">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {cases.map((c: EvalCaseResult, i: number) => (
                <tr key={i} className="hover:bg-muted/30 transition-colors">
                  <td className="px-3 py-2 text-xs text-muted-foreground tabular-nums">{i + 1}</td>
                  <td className="px-3 py-2 text-xs max-w-[160px]">
                    <span title={c.input} className="block truncate">{truncate(c.input, 60)}</span>
                  </td>
                  <td className="px-3 py-2 text-xs max-w-[140px] text-muted-foreground">
                    <span title={c.expectedOutput} className="block truncate">{truncate(c.expectedOutput || "—", 50)}</span>
                  </td>
                  <td className="px-3 py-2 text-xs max-w-[200px]">
                    {c.error ? (
                      <span className="text-red-500" title={c.error}>{truncate(c.error, 60)}</span>
                    ) : (
                      <span title={c.response} className="block truncate">{truncate(c.response, 60)}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {metricBadge(c.metrics?.relevance ?? 0, thresholds.minRelevance as number | undefined, "relevance")}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {metricBadge(c.metrics?.faithfulness ?? 0, thresholds.minFaithfulness as number | undefined, "faithfulness")}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {metricBadge(c.metrics?.toxicity ?? 0, thresholds.maxToxicity as number | undefined, "toxicity")}
                  </td>
                  <td className="px-3 py-2 text-right text-xs tabular-nums text-muted-foreground">
                    {c.latencyMs != null ? `${c.latencyMs}ms` : "—"}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Badge
                      variant={c.status === "completed" ? "outline" : "destructive"}
                      className={`text-[10px] ${c.status === "completed" ? "border-emerald-500/40 text-emerald-500" : ""}`}
                    >
                      {c.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      </Card>
    </div>
  );
}
