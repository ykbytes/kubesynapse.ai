import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const manager = readFileSync(resolve(root, "src/components/workflows/WorkflowManager.tsx"), "utf8");
const history = readFileSync(resolve(root, "src/components/workflow/WorkflowHistoryView.tsx"), "utf8");
const live = readFileSync(resolve(root, "src/components/workflow/WorkflowLiveView.tsx"), "utf8");
const detail = readFileSync(resolve(root, "src/components/workflow/WorkflowStepDetail.tsx"), "utf8");

const checks = [
  ["manager has overview tab", /value="overview"/.test(manager)],
  ["manager has runs tab", /value="runs"/.test(manager)],
  ["manager has files tab", /value="files"/.test(manager)],
  ["manager has definition tab", /value="definition"/.test(manager)],
  ["old duplicate workspace banner removed", !manager.includes("Workflow workspace")],
  ["runs view no longer embeds workspace files", !history.includes("Workspace Files")],
  ["workflow header no longer renders the redundant status metrics band", !manager.includes('uppercase tracking-wide text-muted-foreground">Status')],
  ["workflow overview no longer renders the bulky command center title", !live.includes("Run command center")],
  ["workflow overview no longer renders suggested-next summary block", !live.includes("Suggested next")],
  ["workflow overview avoids green-on-green checklist rows", !detail.includes('item.done ? "bg-emerald-500/10 text-emerald-300"')],
  ["workflow overview uses neutral completed checklist rows", detail.includes("border-border/45 bg-card/70")],
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
