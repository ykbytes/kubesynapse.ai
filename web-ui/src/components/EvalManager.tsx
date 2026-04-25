import { AlertTriangle, CheckCircle2, LoaderCircle, PlusCircle, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "./ConfirmDialog";
import { EvalResultsPanel } from "./EvalResultsPanel";
import { useConnection } from "@/contexts/ConnectionContext";
import type { AgentInfo, EvalInfo, EvalPayload, EvalTestCase, EvalUpdatePayload } from "../types";

interface EvalManagerProps {
  evalResource: EvalInfo | null;
  agents: AgentInfo[];
  isSaving: boolean;
  isDeleting: boolean;
  error: string;
  onCreate: (payload: EvalPayload) => void;
  onUpdate: (name: string, payload: EvalUpdatePayload) => void;
  onDelete: (name: string) => void;
}

type ThresholdDraft = {
  maxToxicity: string;
  minRelevance: string;
  maxLatencyMs: string;
};

type ThresholdBuildResult = {
  values: Record<string, unknown>;
  error: string | null;
};

const METRIC_OPTIONS = ["relevance", "faithfulness", "toxicity", "latency"];

function thresholdValueToDraft(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function defaultCases(): EvalTestCase[] {
  return [{ input: "", expected_output: "", metrics: ["relevance"] }];
}

function thresholdsFromResource(evalResource: EvalInfo | null): ThresholdDraft {
  return {
    maxToxicity: thresholdValueToDraft(evalResource?.failure_threshold.maxToxicity),
    minRelevance: thresholdValueToDraft(evalResource?.failure_threshold.minRelevance),
    maxLatencyMs: thresholdValueToDraft(evalResource?.failure_threshold.maxLatencyMs),
  };
}

export function EvalManager({
  evalResource,
  agents,
  isSaving,
  isDeleting,
  error,
  onCreate,
  onUpdate,
  onDelete,
}: EvalManagerProps) {
  const { canMutate } = useConnection();
  const [name, setName] = useState("");
  const [agentRef, setAgentRef] = useState("");
  const [schedule, setSchedule] = useState("");
  const [testSuite, setTestSuite] = useState<EvalTestCase[]>(defaultCases());
  const [thresholds, setThresholds] = useState<ThresholdDraft>(thresholdsFromResource(null));
  const [validationError, setValidationError] = useState("");
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  useEffect(() => {
    if (evalResource) {
      setName(evalResource.name);
      setAgentRef(evalResource.agent_ref);
      setSchedule(evalResource.schedule ?? "");
      setTestSuite(evalResource.test_suite.length > 0 ? evalResource.test_suite : defaultCases());
      setThresholds(thresholdsFromResource(evalResource));
      setValidationError("");
      return;
    }
    setName("");
    setAgentRef(agents[0]?.name ?? "");
    setSchedule("");
    setTestSuite(defaultCases());
    setThresholds(thresholdsFromResource(null));
    setValidationError("");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evalResource?.name, evalResource?.phase]);

  function updateCase(index: number, updater: (current: EvalTestCase) => EvalTestCase) {
    setTestSuite((current) => current.map((item, itemIndex) => (itemIndex === index ? updater(item) : item)));
  }

  function parseThresholdValue(label: string, rawValue: string): number | null {
    const trimmed = rawValue.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) throw new Error(`${label} must be a valid number.`);
    return parsed;
  }

  function buildFailureThreshold(): ThresholdBuildResult {
    const next: Record<string, unknown> = {};
    try {
      const maxToxicity = parseThresholdValue("Max toxicity", thresholds.maxToxicity);
      const minRelevance = parseThresholdValue("Min relevance", thresholds.minRelevance);
      const maxLatencyMs = parseThresholdValue("Max latency ms", thresholds.maxLatencyMs);
      if (maxToxicity !== null) next.maxToxicity = maxToxicity;
      if (minRelevance !== null) next.minRelevance = minRelevance;
      if (maxLatencyMs !== null) next.maxLatencyMs = maxLatencyMs;
    } catch (err) {
      return { values: {}, error: err instanceof Error ? err.message : String(err) };
    }
    return { values: next, error: null };
  }

  const canSubmit = Boolean(name.trim()) && Boolean(agentRef.trim()) && testSuite.every((item) => item.input.trim() && item.metrics.length > 0);
  const metricCoverage = useMemo(() => Array.from(new Set(testSuite.flatMap((item) => item.metrics))).sort(), [testSuite]);
  const thresholdPreview = useMemo(() => buildFailureThreshold(), [thresholds]);
  const configuredThresholdCount = Object.keys(thresholdPreview.values).length;
  const evalBrief = useMemo(() => {
    if (!evalResource) {
      return {
        tone: "border-primary/20 bg-primary/5",
        title: "Create an evaluation that can actually catch regressions",
        body: "Use enough cases to cover the real prompt shapes you care about, choose metrics deliberately, and configure thresholds only where the team is ready to enforce a standard.",
      };
    }
    if (evalResource.phase === "running") {
      return {
        tone: "border-primary/20 bg-primary/5",
        title: "An evaluation run is in flight",
        body: `The suite is currently executing against ${evalResource.agent_ref}. Keep this panel focused on quality posture, not config churn, until the results settle.`,
      };
    }
    if (evalResource.passed === true) {
      return {
        tone: "border-emerald-500/20 bg-emerald-500/10",
        title: "The current suite is passing",
        body: `The last recorded run cleared its quality gate. Use the result panel to confirm why it passed before broadening the test surface or tightening thresholds.`,
      };
    }
    if (evalResource.passed === false || evalResource.phase === "failed") {
      return {
        tone: "border-red-500/20 bg-red-500/10",
        title: "Quality regressions need operator attention",
        body: "The latest run did not meet the configured bar. Use the result summary to isolate which cases failed and whether the issue is relevance, toxicity, latency, or runtime behavior.",
      };
    }
    return {
      tone: "border-border/60 bg-muted/20",
      title: "This suite is defined but still needs an operational baseline",
      body: "Run the evaluation at least once so the team has a real pass/fail reference before editing prompts, thresholds, or schedule cadence.",
    };
  }, [evalResource]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <CardTitle className="text-base">
              {evalResource ? evalResource.name : "Create evaluation"}
            </CardTitle>
            <CardDescription>
              {evalResource ? "Edit evaluation configuration and test cases." : "Define test cases and quality thresholds."}
            </CardDescription>
          </div>
          <Badge variant={evalResource?.phase === "running" ? "default" : "secondary"}>
            {evalResource?.phase ?? "draft"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 p-3 pt-0 md:p-3 md:pt-0">
        <div className="grid gap-2 md:grid-cols-4">
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Status</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{evalResource?.phase ?? "draft"}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Cases</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{testSuite.length}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Metrics</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{metricCoverage.length}</p>
          </div>
          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground/70">Thresholds</p>
            <p className="mt-1 text-xl font-semibold text-foreground">{configuredThresholdCount}</p>
          </div>
        </div>

        <div className={evalBrief.tone + " rounded-2xl border px-3 py-3"}>
          <div className="flex items-start gap-3">
            {evalBrief.tone.includes("emerald") ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-400" /> : evalBrief.tone.includes("red") ? <AlertTriangle className="mt-0.5 h-4 w-4 text-red-400" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 text-primary" />}
            <div className="space-y-1">
              <p className="text-sm font-semibold text-foreground">{evalBrief.title}</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{evalBrief.body}</p>
              <div className="flex flex-wrap gap-2 pt-1">
                <Badge variant="outline" className="text-[10px]">Agent {agentRef || "unselected"}</Badge>
                <Badge variant="outline" className="text-[10px]">{schedule.trim() ? `Scheduled ${schedule.trim()}` : "Manual run"}</Badge>
                <Badge variant="outline" className="text-[10px]">{metricCoverage.join(", ") || "No metrics"}</Badge>
                {evalResource?.last_run && <Badge variant="outline" className="text-[10px]">Last run {new Date(evalResource.last_run).toLocaleString()}</Badge>}
              </div>
            </div>
          </div>
        </div>

        {thresholdPreview.error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {thresholdPreview.error}
          </div>
        )}

        {/* Config */}
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label className="text-xs">Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="research-assistant-eval"
              disabled={Boolean(evalResource)}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Agent</Label>
            <Select value={agentRef || "__none__"} onValueChange={(v) => setAgentRef(v === "__none__" ? "" : v)}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder="Select agent" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">Select agent</SelectItem>
                {agents.map((agent) => (
                  <SelectItem key={agent.name} value={agent.name}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Schedule (cron)</Label>
            <Input
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder="0 */6 * * *"
            />
          </div>
        </div>

        {/* Thresholds */}
        <div className="space-y-1.5">
          <h3 className="text-xs font-medium text-muted-foreground">Failure thresholds</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label className="text-[11px]">Max toxicity</Label>
              <Input
                className="h-8 text-xs"
                value={thresholds.maxToxicity}
                onChange={(e) => {
                  setValidationError("");
                  setThresholds((c) => ({ ...c, maxToxicity: e.target.value }));
                }}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Min relevance</Label>
              <Input
                className="h-8 text-xs"
                value={thresholds.minRelevance}
                onChange={(e) => {
                  setValidationError("");
                  setThresholds((c) => ({ ...c, minRelevance: e.target.value }));
                }}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[11px]">Max latency (ms)</Label>
              <Input
                className="h-8 text-xs"
                value={thresholds.maxLatencyMs}
                onChange={(e) => {
                  setValidationError("");
                  setThresholds((c) => ({ ...c, maxLatencyMs: e.target.value }));
                }}
              />
            </div>
          </div>
        </div>

        {/* Test cases heading */}
        <div className="flex items-center justify-between border-t border-border pt-4">
          <h3 className="text-sm font-medium">Test cases</h3>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() =>
              setTestSuite((current) => [
                ...current,
                { input: "", expected_output: "", metrics: ["relevance"] },
              ])
            }
          >
            <PlusCircle className="mr-1 h-3 w-3" />
            Add case
          </Button>
        </div>

        {/* Test case cards */}
        <div className="space-y-3 overflow-x-auto">
          {testSuite.map((testCase, index) => (
            <Card key={index} className="shadow-none">
              <CardContent className="p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">Case {index + 1}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-xs text-destructive hover:text-destructive"
                    disabled={testSuite.length === 1}
                    onClick={() =>
                      setTestSuite((current) => current.filter((_, i) => i !== index))
                    }
                    aria-label="Remove test case"
                  >
                    <Trash2 className="mr-1 h-3 w-3" />
                    Remove
                  </Button>
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px]">Input</Label>
                  <Textarea
                    rows={2}
                    className="text-xs"
                    value={testCase.input}
                    onChange={(e) =>
                      updateCase(index, (c) => ({ ...c, input: e.target.value }))
                    }
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-[11px]">Expected output</Label>
                  <Textarea
                    rows={2}
                    className="text-xs"
                    value={testCase.expected_output}
                    onChange={(e) =>
                      updateCase(index, (c) => ({ ...c, expected_output: e.target.value }))
                    }
                  />
                </div>
                <div className="flex flex-wrap gap-3">
                  {METRIC_OPTIONS.map((metric) => (
                    <label key={metric} className="flex items-center gap-1.5 cursor-pointer text-xs">
                      <input
                        type="checkbox"
                        checked={testCase.metrics.includes(metric)}
                        onChange={(e) =>
                          updateCase(index, (c) => ({
                            ...c,
                            metrics: e.target.checked
                              ? [...c.metrics, metric]
                              : c.metrics.filter((m) => m !== metric),
                          }))
                        }
                        className="h-4 w-4 rounded border-input accent-primary"
                      />
                      {metric}
                    </label>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {(validationError || error) && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
            {validationError || error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
          {canMutate && (
            <Button
              onClick={() => {
                const thresholdResult = buildFailureThreshold();
                if (thresholdResult.error) {
                  setValidationError(thresholdResult.error);
                  return;
                }
                setValidationError("");
                const payload = {
                  agent_ref: agentRef,
                  schedule: schedule.trim() || undefined,
                  test_suite: testSuite,
                  failure_threshold: thresholdResult.values,
                };
                if (evalResource) {
                  onUpdate(evalResource.name, payload as EvalUpdatePayload);
                  return;
                }
                onCreate({ name, ...payload });
              }}
              disabled={!canSubmit || isSaving}
            >
              {isSaving ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
              {isSaving ? "Saving..." : evalResource ? "Save evaluation" : "Create evaluation"}
            </Button>
          )}
          {evalResource && canMutate && (
            <Button
              variant="destructive"
              onClick={() => setDeleteDialogOpen(true)}
              disabled={isDeleting}
            >
              {isDeleting ? <LoaderCircle className="mr-1.5 h-4 w-4 animate-spin" /> : <Trash2 className="mr-1.5 h-4 w-4" />}
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          )}
          {!canMutate && (
            <p className="text-xs text-muted-foreground italic">Read-only — operator role required to edit</p>
          )}
        </div>

        {evalResource && (
          <ConfirmDialog
            open={deleteDialogOpen}
            onOpenChange={setDeleteDialogOpen}
            title="Delete evaluation"
            description={`This will permanently delete the evaluation "${evalResource.name}". This action cannot be undone.`}
            confirmLabel="Delete"
            onConfirm={() => onDelete(evalResource.name)}
          />
        )}

        {evalResource && (evalResource.phase === "completed" || evalResource.phase === "failed" || evalResource.phase === "running") && (
          <EvalResultsPanel evalResource={evalResource} />
        )}
      </CardContent>
    </Card>
  );
}
