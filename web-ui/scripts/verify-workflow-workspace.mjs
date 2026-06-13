import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const manager = readFileSync(resolve(root, "src/components/workflows/WorkflowManager.tsx"), "utf8");
const history = readFileSync(resolve(root, "src/components/workflow/WorkflowHistoryView.tsx"), "utf8");

const checks = [
  ["manager has overview tab", /value="overview"/.test(manager)],
  ["manager has runs tab", /value="runs"/.test(manager)],
  ["manager has files tab", /value="files"/.test(manager)],
  ["manager has definition tab", /value="definition"/.test(manager)],
  ["old duplicate workspace banner removed", !manager.includes("Workflow workspace")],
  ["runs view no longer embeds workspace files", !history.includes("Workspace Files")],
];

const failed = checks.filter(([, ok]) => !ok);
if (failed.length > 0) {
  console.error("Workflow workspace verification failed:");
  for (const [name] of failed) {
    console.error(`- ${name}`);
  }
  process.exit(1);
}

console.log("Workflow workspace verification passed.");
