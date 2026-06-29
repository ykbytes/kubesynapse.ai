import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(here, "../src/components/intelligence/ExecutionObservatory.tsx");
const apiPath = resolve(here, "../src/lib/api.ts");
const typesPath = resolve(here, "../src/types.ts");
const tracePanelPath = resolve(here, "../src/components/intelligence/OptimizerTracePanel.tsx");
const source = readFileSync(sourcePath, "utf8");
const apiSource = readFileSync(apiPath, "utf8");
const typesSource = readFileSync(typesPath, "utf8");
const tracePanelSource = existsSync(tracePanelPath) ? readFileSync(tracePanelPath, "utf8") : "";

const checks = [
  {
    name: "optimizer agent selection prefers dedicated optimizers",
    pass:
      source.includes("chooseDefaultOptimiserAgent") &&
      source.includes("isOptimiserAgentCandidate") &&
      !source.includes("optimiseAgents.find((agent) => agent.name === detail?.agent_name) ??"),
  },
  {
    name: "optimizer prompt has a runtime safety budget",
    pass:
      source.includes("OPTIMISE_PROMPT_MAX_CHARS") &&
      source.includes("const OPTIMISE_PROMPT_MAX_CHARS = 48_000") &&
      source.includes("buildRuntimeSafeOptimisationPrompt") &&
      source.includes("Prompt compacted to keep optimizer analysis responsive"),
  },
  {
    name: "ROI study failure message distinguishes agent invoke failures",
    pass:
      source.includes("Optimizer agent invocation failed after the baseline study was created"),
  },
  {
    name: "optimizer analysis uses streaming invoke to avoid proxy timeouts",
    pass:
      source.includes("streamAgentInvoke") &&
      source.includes("invokeOptimizerAgentForRoi") &&
      source.includes("Optimizer is streaming analysis") &&
      !source.includes("const result = await invokeAgent(\n          token,\n          namespace,\n          optimiseAgentName"),
  },
  {
    name: "optimizer fallback tolerates non-array affected steps",
    pass:
      source.includes("normaliseOptimizerStringList") &&
      source.includes("normaliseOptimizerStringList(topOpportunity?.affected_steps)") &&
      !source.includes("topOpportunity?.affected_steps?.slice"),
  },
  {
    name: "ROI study run has visible phase feedback",
    pass:
      source.includes("type OptimisationRunPhase") &&
      source.includes("createOptimiseRunPhases") &&
      source.includes("updateOptimiseRunPhase") &&
      source.includes("Live run pipeline"),
  },
  {
    name: "optimizer prompt carries run intelligence and manifest output contract",
    pass:
      source.includes("run_intelligence") &&
      source.includes("candidate_manifest_bundle") &&
      source.includes("Workflow run intelligence dossier") &&
      source.includes("Never edit the source workflow in place"),
  },
  {
    name: "optimizer prompt requires structured ROI hypothesis and change log",
    pass:
      source.includes("roi_hypothesis") &&
      source.includes("expected_metric_delta") &&
      source.includes("change_log") &&
      source.includes("extractOptimiserExpectedSavings"),
  },
  {
    name: "workflow agents cannot be used as optimizer agents",
    pass:
      source.includes("selectedAgentLooksOptimiser") &&
      source.includes("Cannot run with a workflow agent") &&
      source.includes("Choose a dedicated workflow optimizer agent"),
  },
  {
    name: "optimizer comparison endpoint is consumed by the UI",
    pass:
      apiSource.includes("fetchOptimizationComparison") &&
      apiSource.includes("/comparison") &&
      source.includes("optimiseComparison") &&
      source.includes("Candidate vs baseline"),
  },
  {
    name: "optimizer tab hydrates persisted studies and selectable candidate history",
    pass:
      apiSource.includes("fetchOptimizationStudies") &&
      apiSource.includes("/api/optimizations/studies") &&
      source.includes("loadPersistedOptimisationStudy") &&
      source.includes("handleSelectOptimisationCandidate") &&
      source.includes("Candidate history") &&
      source.includes("Expected gain"),
  },
  {
    name: "optimizer comparison renders trial, step, tool, and manifest evidence",
    pass:
      source.includes("Trial evidence") &&
      source.includes("Step impact") &&
      source.includes("Tool impact") &&
      source.includes("Side-by-side manifest comparison") &&
      source.includes("Original ·") &&
      source.includes("Candidate ·"),
  },
  {
    name: "optimizer UI uses compact internal tabs and topology mode control",
    pass:
      source.includes("optimiseWorkspaceTab") &&
      source.includes("Preserve topology") &&
      source.includes("Allow topology rewrite") &&
      source.includes("value=\"diff\"") &&
      source.includes("value=\"candidate\"") &&
      source.includes("allowTopologyRewrite"),
  },
  {
    name: "optimizer prompt separates source workflow from topology rewrite mode",
    pass:
      source.includes("optimization_mode") &&
      source.includes("The source workflow and source agents must not become aware of ROI Lab") &&
      source.includes("Topology rewrite mode") &&
      apiSource.includes("allow_topology_rewrite"),
  },
  {
    name: "optimizer prompt references attached ROI optimization skills",
    pass:
      source.includes("critical-path-roi") &&
      source.includes("context-compression") &&
      source.includes("tool-economy") &&
      source.includes("regression-proof-gate") &&
      source.includes("no-change control candidate"),
  },
  {
    name: "optimizer prompt requires topology consolidation search and visible audit record",
    pass:
      source.includes("evaluate at least one fewer-step or fewer-agent candidate") &&
      source.includes("optimizer_decision_record") &&
      source.includes("do not include private chain-of-thought") &&
      source.includes("topology_equivalence_map") &&
      source.includes("do_not_emit_private_chain_of_thought"),
  },
  {
    name: "candidate API exposes a persisted optimizer trace",
    pass:
      typesSource.includes("export interface OptimizerTrace") &&
      typesSource.includes("export interface OptimizerTraceEvent") &&
      typesSource.includes("optimizer_trace?: OptimizerTrace") &&
      apiSource.includes("optimizer_trace: parseOptimizerTrace") &&
      apiSource.includes("optimizer_trace?: OptimizerTrace"),
  },
  {
    name: "optimizer stream captures observable reasoning, tools, completion, and errors",
    pass:
      source.includes("optimizerTraceEvents") &&
      source.includes("appendOptimizerTraceEvent(\"reasoning\"") &&
      source.includes("appendOptimizerTraceEvent(\"tool\"") &&
      source.includes("\"completion\",") &&
      source.includes("appendOptimizerTraceEvent(\"error\"") &&
      source.includes("optimizer_trace: optimizerTrace"),
  },
  {
    name: "candidate workspace provides a focused optimizer trace timeline and inspector",
    pass:
      source.includes("Optimizer trace") &&
      source.includes("<OptimizerTracePanel") &&
      tracePanelSource.includes("Trace chronology") &&
      tracePanelSource.includes("Event inspector") &&
      tracePanelSource.includes("Reasoning summaries") &&
      tracePanelSource.includes("Skills & resources") &&
      tracePanelSource.includes("Visible final response") &&
      tracePanelSource.includes("Observable execution only") &&
      !source.includes("Optimizer decision audit"),
  },
  {
    name: "optimizer UI keeps secondary analysis in collapsible panels",
    pass:
      source.includes("<details className=\"rounded-lg border border-border/50 bg-card/45 p-3\"") &&
      source.includes("Ranked optimization levers") &&
      source.includes("Execution economics") &&
      source.includes("Candidate analysis") &&
      source.includes("Inspectors"),
  },
  {
    name: "optimizer comparison uses authoritative scorecard data",
    pass:
      typesSource.includes("OptimizationComparisonScorecard") &&
      apiSource.includes("diff_rows") &&
      source.includes("actualComparisonMetrics") &&
      source.includes("Actual vs estimate") &&
      source.includes("paired trial") &&
      source.includes("Estimated by optimizer"),
  },
  {
    name: "optimizer comparison highlights regressions and line-level manifest changes",
    pass:
      source.includes("Regressions to review") &&
      source.includes("renderManifestDiffRows") &&
      source.includes("selectedManifestSection.diff_rows") &&
      source.includes("bg-emerald-500/10") &&
      source.includes("bg-red-500/10"),
  },
];

const failures = checks.filter((check) => !check.pass);
if (failures.length > 0) {
  console.error("Optimise ROI contract checks failed:");
  for (const failure of failures) {
    console.error(`- ${failure.name}`);
  }
  process.exit(1);
}

console.log("Optimise ROI contract checks passed.");
