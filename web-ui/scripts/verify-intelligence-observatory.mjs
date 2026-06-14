import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

const overview = read("../src/components/observatory/ObservatoryOverview.tsx");
const observatory = read("../src/components/intelligence/ExecutionObservatory.tsx");
const waterfall = read("../src/components/observatory/StepWaterfall.tsx");
const api = read("../src/lib/api.ts");
const agentSignals = read("../src/lib/agentSignals.ts");

const checks = [
  ["overview uses compact run digest", overview.includes("RunDigestBar")],
  ["overview removed five-card scorecard loop", !overview.includes("scorecard.map")],
  ["overview removed oversized five-column scorecard grid", !overview.includes("lg:grid-cols-5")],
  ["overview keeps trace-derived quality flags", overview.includes("qualityFlags")],
  ["overview keeps trace-derived token breakdown", overview.includes("tokenBreakdown")],
  ["overview groups insight panels into compact runtime profile", overview.includes("Runtime Profile")],
  ["observatory has a unified trace tab contract", observatory.includes('type ObservatoryTab = "overview" | "trace" | "optimise" | "logs" | "compare";')],
  ["observatory renders the trace explorer", observatory.includes("TraceExplorer")],
  ["trace explorer builds a joined execution chronology", observatory.includes("buildTraceRecords")],
  ["trace explorer exposes step and agent attribution", observatory.includes("Agent / step")],
  ["trace explorer exposes tool filtering", observatory.includes("Filter by tool")],
  ["trace chronology is narrower than inspector", observatory.includes("xl:grid-cols-[13rem_minmax(22rem,0.78fr)_minmax(30rem,1.22fr)]")],
  ["observatory renders optimisation cockpit", observatory.includes("OptimisePanel")],
  ["optimise tab can select platform agents", observatory.includes("listAgents") && observatory.includes("optimiseAgents")],
  ["optimise tab can invoke selected agent", observatory.includes("invokeAgent") && observatory.includes("Run optimisation")],
  ["optimise tab builds trace optimisation packet", observatory.includes("buildOptimisationPacket")],
  ["optimise tab shows cost and latency opportunities", observatory.includes("Opportunity map") && observatory.includes("Token pressure")],
  ["optimise tab includes source Kubernetes manifests", observatory.includes("fetchWorkflowManifest") && observatory.includes("fetchAgentManifest") && observatory.includes("source_manifests")],
  ["optimise packet includes every referenced agent manifest", observatory.includes("agent_refs") && observatory.includes("agentManifests") && observatory.includes("agent manifest(s)")],
  ["optimise prompt requests optimized manifest copies", observatory.includes("Optimized Kubernetes manifests for copied workflow/agent resources")],
  ["optimise tab documents least privilege deploy agent", observatory.includes("Deployment access model") && observatory.includes("admin-created deployment agent")],
  ["api exposes read-only manifest wrappers", api.includes("fetchWorkflowManifest") && api.includes("fetchAgentManifest")],
  ["agent card exposes Kubernetes access explicitly", agentSignals.includes('label: "Cluster access"') && agentSignals.includes("least-privilege RBAC")],
  ["overview jumps into the trace explorer", observatory.includes('setActiveTab("trace")')],
  ["separate steps tab removed", !observatory.includes('value="steps"')],
  ["separate models tab removed", !observatory.includes('value="models"')],
  ["llm parser preserves gateway started_at timestamps", api.includes('readOptionalString(record, "started_at", label)')],
  ["compare tab uses compact comparison toolbar", observatory.includes("CompareToolbar")],
  ["waterfall rows are dense", waterfall.includes("h-4 rounded bg-muted/20")],
];

const failed = checks.filter(([, ok]) => !ok);
for (const [name, ok] of checks) {
  console.log(`${ok ? "ok" : "FAIL"} - ${name}`);
}

if (failed.length > 0) {
  console.error(`\nIntelligence observatory verification failed: ${failed.length} check(s).`);
  process.exit(1);
}

console.log("\nIntelligence observatory verification passed.");
