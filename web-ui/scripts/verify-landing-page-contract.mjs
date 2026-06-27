import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const sourcePath = resolve(here, "../src/components/landing/LandingPage.tsx");
const source = readFileSync(sourcePath, "utf8");

const checks = [
  {
    name: "hero positions KubeSynapse as measured AI operations",
    pass:
      source.includes("Measured AI operations for Kubernetes") &&
      source.includes("run agentic workflows, trace what happened, and prove whether changes save time, tokens, and tool calls"),
  },
  {
    name: "landing page promotes Optimize ROI Lab without overclaiming",
    pass:
      source.includes("Optimize ROI Lab") &&
      source.includes("baseline vs candidate") &&
      source.includes("estimated before trial, verified after paired runs"),
  },
  {
    name: "landing page explains candidate manifests and side-by-side diffs",
    pass:
      source.includes("Copied candidate manifests") &&
      source.includes("side-by-side manifest diff") &&
      source.includes("source workflow is never edited in place"),
  },
  {
    name: "enterprise value copy focuses on governance, audit, and proof",
    pass:
      source.includes("Governed by Kubernetes") &&
      source.includes("Evidence before promotion") &&
      source.includes("Every run becomes reusable data"),
  },
  {
    name: "new ROI section is linked from the page flow",
    pass:
      source.includes("function OptimizationSection") &&
      source.includes("<OptimizationSection />") &&
      source.includes('{ label: "Optimize", id: "optimize" }'),
  },
  {
    name: "copy avoids broad unsupported claims",
    pass:
      !source.includes("no security team required") &&
      !source.includes("under 5 minutes") &&
      !source.includes("complete AI operations layer"),
  },
];

const failures = checks.filter((check) => !check.pass);

if (failures.length > 0) {
  console.error("Landing page contract checks failed:");
  for (const failure of failures) {
    console.error(`- ${failure.name}`);
  }
  process.exit(1);
}

console.log("Landing page contract checks passed.");
