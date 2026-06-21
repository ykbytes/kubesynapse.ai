import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(here, "../src/components/intelligence/ExecutionObservatory.tsx");
const apiPath = resolve(here, "../src/lib/api.ts");
const typesPath = resolve(here, "../src/types.ts");
const source = readFileSync(sourcePath, "utf8");
const apiSource = readFileSync(apiPath, "utf8");
const typesSource = readFileSync(typesPath, "utf8");

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
      source.includes("buildRuntimeSafeOptimisationPrompt") &&
      source.includes("Prompt compacted to fit the opencode runtime"),
  },
  {
    name: "ROI study failure message distinguishes agent invoke failures",
    pass:
      source.includes("Optimizer agent invocation failed after the baseline study was created"),
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
    name: "optimizer comparison renders trial, step, tool, and manifest evidence",
    pass:
      source.includes("Trial evidence") &&
      source.includes("Step impact") &&
      source.includes("Tool impact") &&
      source.includes("Manifest diff") &&
      source.includes("Original ·") &&
      source.includes("Candidate ·"),
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
