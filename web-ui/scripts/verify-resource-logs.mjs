import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const repoRoot = resolve(root, "..");
const panel = readFileSync(resolve(root, "src/components/shared/ResourceLogsPanel.tsx"), "utf8");
const agentsRouter = readFileSync(resolve(repoRoot, "api-gateway/routers/agents.py"), "utf8");
const workflowsRouter = readFileSync(resolve(repoRoot, "api-gateway/routers/workflows.py"), "utf8");
const adminRouter = readFileSync(resolve(repoRoot, "api-gateway/routers/admin.py"), "utf8");
const authMiddleware = readFileSync(resolve(repoRoot, "api-gateway/auth_middleware.py"), "utf8");
const authStore = readFileSync(resolve(repoRoot, "api-gateway/auth_store.py"), "utf8");
const agentPanel = readFileSync(resolve(root, "src/components/agents/AgentManagementPanel.tsx"), "utf8");
const workflowManager = readFileSync(resolve(root, "src/components/workflows/WorkflowManager.tsx"), "utf8");
const connectionContext = readFileSync(resolve(root, "src/contexts/ConnectionContext.tsx"), "utf8");
const adminPanel = readFileSync(resolve(root, "src/components/admin/AdminPanel.tsx"), "utf8");
const apiTs = readFileSync(resolve(root, "src/lib/api.ts"), "utf8");
const typesTs = readFileSync(resolve(root, "src/types.ts"), "utf8");

const checks = [
  // Shared panel implementation
  ["shared ResourceLogsPanel exists", panel.includes("function ResourceLogsPanel")],
  ["panel uses streaming API wrappers", panel.includes("streamAgentLogs") && panel.includes("streamWorkflowLogs")],
  ["panel handles agent + workflow sources", panel.includes('kind: "agent"') && panel.includes('kind: "workflow"')],
  ["panel surfaces a denial state distinct from errors", panel.includes("denied")],
  ["panel caps buffered lines", /MAX_BUFFERED_LINES\s*=\s*\d+/.test(panel)],
  ["panel exposes pause / resume", panel.includes("Pause") && panel.includes("Resume")],
  ["panel exposes level filter", panel.includes("error") && panel.includes("warn") && panel.includes("info")],
  ["panel exposes search filter", panel.includes("Filter")],
  ["panel exposes copy + export", panel.includes("Copy") && panel.includes("Export")],
  ["panel degrades to a static view when capability is missing", panel.includes("capabilityMissing")],

  // Backend contract: capability gate
  ["auth middleware exposes user_has_capability", authMiddleware.includes("def user_has_capability")],
  ["auth middleware exposes ensure_capability", authMiddleware.includes("def ensure_capability")],
  ["auth middleware knows about runtime:logs", authMiddleware.includes('"runtime:logs"')],
  ["ensure_capability raises 403 with capability code", authMiddleware.includes("status_code=403")],
  ["operator default for runtime:logs is True", authMiddleware.includes("is not False")],
  ["user record stores capabilities JSON", authStore.includes("capabilities = Column(JSON")],
  ["user record sanitizes capabilities on update", authStore.includes("def _sanitize_capabilities")],
  ["admin update propagates capabilities into audit", /"capabilities":\s*updated\.get\("capabilities"\)/.test(adminRouter)],
  // The capabilities toggle in the AdminPanel edit dialog actually submits a payload.
  ["admin panel edit form toggles runtime:logs capability", /editForm\.capabilities\?\.\["runtime:logs"\]/.test(adminPanel)],
  ["admin panel capabilities payload includes runtime:logs", adminPanel.includes('"runtime:logs"') && /updateUser\([\s\S]*?editUser\.id[\s\S]*?editForm/.test(adminPanel)],
  ["agent logs tail endpoint enforces capability", agentsRouter.includes('ensure_capability(user, "runtime:logs")')],
  ["agent logs stream endpoint enforces capability", /stream_agent_logs[\s\S]{0,400}ensure_capability\(user,\s*"runtime:logs"\)/.test(agentsRouter)],
  ["workflow logs endpoint enforces capability", workflowsRouter.includes('ensure_capability(user, "runtime:logs")')],
  ["workflow logs stream endpoint enforces capability", /stream_workflow_logs[\s\S]{0,400}ensure_capability\(user,\s*"runtime:logs"\)/.test(workflowsRouter)],

  // UI: tabs + connection context
  ["connection context exposes hasCapability", connectionContext.includes("hasCapability")],
  ["connection context applies admin-pass-through for capabilities", connectionContext.includes("currentUser.role === \"admin\"")],
  ["connection context keeps operator default for runtime:logs", connectionContext.includes('capability === "runtime:logs"')],
  ["AuthenticatedUser type carries capabilities", /capabilities\?:\s*Record<string,\s*boolean>/.test(typesTs)],
  ["AdminUser type carries capabilities", /capabilities\?:\s*Record<string,\s*boolean>/.test(typesTs)],
  ["api client parses capabilities flag", apiTs.includes("readCapabilityFlags")],
  ["agent panel imports the shared logs panel", agentPanel.includes("ResourceLogsPanel")],
  ["agent panel exposes a Logs tab", /TabsTrigger value="logs"/.test(agentPanel)],
  ["agent panel wires runtime:logs capability to the panel", agentPanel.includes('hasCapability("runtime:logs")')],
  ["workflow manager imports the shared logs panel", workflowManager.includes("ResourceLogsPanel")],
  ["workflow manager exposes a Logs tab", /TabsTrigger value="logs"/.test(workflowManager)],
  ["workflow manager wires runtime:logs capability to the panel", workflowManager.includes('hasCapability("runtime:logs")')],
  ["workflow manager guards logs behind hasBeenTriggered", /workflow\s*&&\s*hasBeenTriggered\s*&&\s*\(\s*\n\s*<TabsContent\s+value="logs"/.test(workflowManager)],

  // Admin can grant log access
  ["admin panel surfaces the runtime:logs toggle", adminPanel.includes("runtime:logs")],
  ["admin panel edit form passes capabilities", /editForm[\s\S]{0,200}capabilities/.test(adminPanel)],
  ["admin panel includes capabilities in update payload", adminPanel.includes('"runtime:logs"') && /updateUser\([\s\S]*?editUser\.id[\s\S]*?editForm/.test(adminPanel)],
];

const failed = checks.filter(([, ok]) => !ok);
if (failed.length > 0) {
  console.error("Resource logs verification failed:");
  for (const [name] of failed) {
    console.error(`- ${name}`);
  }
  process.exit(1);
}

console.log("Resource logs verification passed.");
