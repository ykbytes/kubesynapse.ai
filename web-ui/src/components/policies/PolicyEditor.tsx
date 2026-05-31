import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Plus, Save, Trash2, ShieldAlert, X, AlertTriangle, Loader2,
  Search, Info, Eye, BrainCircuit, Globe, Wrench, Shield,
  ShieldCheck, Database, KeyRound, Layers, Ban, CheckCircle2,
  ChevronsUpDown, Terminal, FileText, FileCode, Sparkles, Code2, BookOpen, ListChecks, MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  createPolicy,
  updatePolicy,
  deletePolicy,
  type CreatePolicyPayload,
  type UpdatePolicyPayload,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import type {
  PolicyInfo,
  PolicyInputGuardrails,
  PolicyMemoryPolicy,
  PolicyOutputGuardrails,
  PolicyToolPolicy,
} from "@/types";

// ── Defaults ──────────────────────────────────────────────────────────────

const DEFAULT_INPUT: PolicyInputGuardrails = {
  blockPromptInjection: false,
  blockedPatterns: [],
  maxInputTokens: 4096,
};

const DEFAULT_OUTPUT: PolicyOutputGuardrails = {
  maskPII: false,
  blockedOutputPatterns: [],
  maxOutputTokens: 4096,
};

const DEFAULT_TOOL: PolicyToolPolicy = {
  allowedToolPrefixes: [],
  blockedToolNames: [],
  requireApprovalFor: [],
};

const DEFAULT_MEMORY: PolicyMemoryPolicy = {
  allowedMemoryTypes: [],
  autoPromote: false,
};

function EMPTY_FORM() {
  return {
    name: "",
    sealed: false,
    inputGuardrails: { ...DEFAULT_INPUT },
    outputGuardrails: { ...DEFAULT_OUTPUT },
    allowedModels: [] as string[],
    allowedMcpServers: [] as string[],
    mcpRequireHitl: true,
    toolPolicy: { ...DEFAULT_TOOL } as PolicyToolPolicy,
    memoryPolicy: { ...DEFAULT_MEMORY } as PolicyMemoryPolicy,
    adminToolCeiling: {} as Record<string, "allow" | "ask" | "deny">,
  };
}

type FormState = ReturnType<typeof EMPTY_FORM>;
type PolicyTab = "overview" | "guardrails" | "access" | "tools" | "memory";

// ── Utility helpers ────────────────────────────────────────────────────────

function formsAreEqual(a: FormState, b: FormState): boolean {
  return (
    a.name === b.name &&
    a.sealed === b.sealed &&
    JSON.stringify(a.inputGuardrails) === JSON.stringify(b.inputGuardrails) &&
    JSON.stringify(a.outputGuardrails) === JSON.stringify(b.outputGuardrails) &&
    JSON.stringify(a.allowedModels) === JSON.stringify(b.allowedModels) &&
    JSON.stringify(a.allowedMcpServers) === JSON.stringify(b.allowedMcpServers) &&
    a.mcpRequireHitl === b.mcpRequireHitl &&
    JSON.stringify(a.toolPolicy) === JSON.stringify(b.toolPolicy) &&
    JSON.stringify(a.memoryPolicy) === JSON.stringify(b.memoryPolicy) &&
    JSON.stringify(a.adminToolCeiling) === JSON.stringify(b.adminToolCeiling)
  );
}

function policyToForm(policy: PolicyInfo): FormState {
  return {
    name: policy.name,
    sealed: policy.sealed ?? false,
    inputGuardrails: { ...policy.input_guardrails },
    outputGuardrails: { ...policy.output_guardrails },
    allowedModels: [...policy.allowed_models],
    allowedMcpServers: [...policy.allowed_mcp_servers],
    mcpRequireHitl: policy.mcp_require_hitl,
    toolPolicy: {
      maxDelegationDepth: policy.tool_policy.maxDelegationDepth,
      allowedToolPrefixes: [...policy.tool_policy.allowedToolPrefixes],
      blockedToolNames: [...policy.tool_policy.blockedToolNames],
      requireApprovalFor: [...policy.tool_policy.requireApprovalFor],
    },
    memoryPolicy: {
      maxInjectedMemories: policy.memory_policy.maxInjectedMemories,
      maxInjectedChars: policy.memory_policy.maxInjectedChars,
      allowedMemoryTypes: [...policy.memory_policy.allowedMemoryTypes],
      autoPromote: policy.memory_policy.autoPromote,
    },
    adminToolCeiling: { ...(policy.tool_policy.adminToolCeiling || {}) },
  };
}

function countActiveGuardrails(form: FormState): number {
  let count = 0;
  if (form.inputGuardrails.blockPromptInjection) count++;
  if (form.inputGuardrails.maxInputTokens > 0) count++;
  if (form.inputGuardrails.blockedPatterns.length > 0) count++;
  if (form.outputGuardrails.maskPII) count++;
  if (form.outputGuardrails.maxOutputTokens > 0) count++;
  if (form.outputGuardrails.blockedOutputPatterns.length > 0) count++;
  return count;
}

function countToolRestrictions(form: FormState): number {
  let count = 0;
  if (form.toolPolicy.blockedToolNames.length > 0) count += form.toolPolicy.blockedToolNames.length;
  if (form.toolPolicy.requireApprovalFor.length > 0) count += form.toolPolicy.requireApprovalFor.length;
  if (form.toolPolicy.maxDelegationDepth != null) count++;
  return count;
}

// ── Reusable subcomponents ─────────────────────────────────────────────────

function TagListEditor({ values, onChange, placeholder }: { values: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (v && !values.includes(v)) {
      onChange([...values, v]);
    }
    setDraft("");
  };
  return (
    <div className="space-y-2">
      <div className="flex gap-1.5">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={placeholder}
          className="h-8 text-xs flex-1"
        />
        <Button variant="outline" size="sm" className="h-8 px-2.5" onClick={add}>
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <Badge key={v} variant="secondary" className="text-[11px] gap-1 pr-1 py-0.5">
              <span className="font-mono">{v}</span>
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} className="hover:text-destructive ml-0.5 transition-colors">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Known OpenCode Tools ────────────────────────────────────────────────────
type ToolCategory = "filesystem" | "execution" | "web" | "delegation" | "git" | "code" | "planning" | "interaction" | "safety";

interface KnownTool {
  id: string;
  label: string;
  category: ToolCategory;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  description: string;
  supportsPatterns?: boolean;
  patternHint?: string;
}

const KNOWN_TOOLS: KnownTool[] = [
  { id: "read",          label: "Read",              category: "filesystem",  icon: FileText,    color: "text-cyan-400",    description: "Read file contents",                           supportsPatterns: true, patternHint: "file glob, e.g. *.env, src/**" },
  { id: "edit",          label: "Edit",              category: "filesystem",  icon: FileCode,    color: "text-amber-400",   description: "Write, edit, and patch files",                  supportsPatterns: true, patternHint: "file glob, e.g. *.env*, config/**" },
  { id: "glob",          label: "Glob",              category: "filesystem",  icon: FileText,    color: "text-cyan-400",    description: "Find files by pattern" },
  { id: "grep",          label: "Grep",              category: "filesystem",  icon: Search,      color: "text-violet-400",  description: "Search file contents with regex" },
  { id: "bash",          label: "Bash",              category: "execution",   icon: Terminal,    color: "text-emerald-400", description: "Execute shell commands",                        supportsPatterns: true, patternHint: "command prefix, e.g. git *, rm *, npm *" },
  { id: "task",          label: "Task",              category: "delegation",  icon: Layers,      color: "text-indigo-400",  description: "Launch subagents for parallel work",            supportsPatterns: true, patternHint: "subagent name, e.g. explore, general" },
  { id: "skill",         label: "Skill",             category: "delegation",  icon: Sparkles,    color: "text-pink-400",    description: "Load specialized skill instructions",           supportsPatterns: true, patternHint: "skill name, e.g. chaos-*, vault-*" },
  { id: "webfetch",      label: "Web Fetch",         category: "web",         icon: Globe,       color: "text-sky-400",     description: "Fetch content from URLs" },
  { id: "websearch",     label: "Web Search",        category: "web",         icon: BookOpen,    color: "text-violet-400",  description: "Search the web for information" },
  { id: "lsp",           label: "LSP",               category: "code",        icon: Code2,       color: "text-orange-400",  description: "Language server code intelligence" },
  { id: "question",      label: "Question",          category: "interaction", icon: MessageSquare, color: "text-blue-400",  description: "Ask user questions during execution" },
  { id: "todowrite",     label: "Todo Write",        category: "planning",    icon: ListChecks,  color: "text-teal-400",    description: "Track task progress" },
  { id: "external_directory", label: "External Dir", category: "safety",      icon: Shield,      color: "text-yellow-400",  description: "Access paths outside project directory",        supportsPatterns: true, patternHint: "path, e.g. ~/projects/*, /tmp/*" },
  { id: "doom_loop",     label: "Doom Loop",         category: "safety",      icon: AlertTriangle, color: "text-red-400",   description: "Recovery when agent repeats identical calls" },
];

const PERMISSION_CATEGORIES: { key: ToolCategory; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "filesystem",  label: "Filesystem",        icon: FileText },
  { key: "execution",   label: "Execution",         icon: Terminal },
  { key: "delegation",  label: "Delegation",        icon: Layers },
  { key: "web",         label: "Web",               icon: Globe },
  { key: "code",        label: "Code Intelligence", icon: Code2 },
  { key: "planning",    label: "Planning",          icon: ListChecks },
  { key: "interaction", label: "Interaction",       icon: MessageSquare },
  { key: "safety",      label: "Safety Guards",     icon: Shield },
];

type PermAction = "allow" | "ask" | "deny" | "default";

interface PatternRule {
  pattern: string;
  action: "allow" | "ask" | "deny";
}

// ── Permission Matrix helpers ─────────────────────────────────────────────

function getToolPermAction(toolId: string, toolPolicy: PolicyToolPolicy): PermAction {
  if (toolPolicy.blockedToolNames.includes(toolId)) return "deny";
  if (toolPolicy.requireApprovalFor.includes(toolId)) return "ask";
  if (toolPolicy.allowedToolPrefixes.includes(toolId)) return "allow";
  return "default";
}

function setToolPermAction(
  toolId: string,
  action: PermAction,
  toolPolicy: PolicyToolPolicy,
): PolicyToolPolicy {
  // Remove from all lists first
  const allowed = toolPolicy.allowedToolPrefixes.filter((t) => t !== toolId);
  const blocked = toolPolicy.blockedToolNames.filter((t) => t !== toolId);
  const approval = toolPolicy.requireApprovalFor.filter((t) => t !== toolId);

  // Add to the appropriate list
  if (action === "allow") allowed.push(toolId);
  else if (action === "deny") blocked.push(toolId);
  else if (action === "ask") approval.push(toolId);
  // "default" = not in any list

  return {
    ...toolPolicy,
    allowedToolPrefixes: allowed,
    blockedToolNames: blocked,
    requireApprovalFor: approval,
  };
}

// Extract pattern rules from the lists (format: "toolId:pattern")
function getPatternRules(toolId: string, toolPolicy: PolicyToolPolicy): PatternRule[] {
  const rules: PatternRule[] = [];
  const prefix = `${toolId}:`;
  for (const entry of toolPolicy.allowedToolPrefixes) {
    if (entry.startsWith(prefix)) rules.push({ pattern: entry.slice(prefix.length), action: "allow" });
  }
  for (const entry of toolPolicy.requireApprovalFor) {
    if (entry.startsWith(prefix)) rules.push({ pattern: entry.slice(prefix.length), action: "ask" });
  }
  for (const entry of toolPolicy.blockedToolNames) {
    if (entry.startsWith(prefix)) rules.push({ pattern: entry.slice(prefix.length), action: "deny" });
  }
  return rules;
}

function setPatternRules(toolId: string, rules: PatternRule[], toolPolicy: PolicyToolPolicy): PolicyToolPolicy {
  const prefix = `${toolId}:`;
  // Remove all existing pattern entries for this tool
  const allowed = toolPolicy.allowedToolPrefixes.filter((t) => !t.startsWith(prefix));
  const blocked = toolPolicy.blockedToolNames.filter((t) => !t.startsWith(prefix));
  const approval = toolPolicy.requireApprovalFor.filter((t) => !t.startsWith(prefix));

  // Add new pattern entries
  for (const rule of rules) {
    const entry = `${prefix}${rule.pattern}`;
    if (rule.action === "allow") allowed.push(entry);
    else if (rule.action === "deny") blocked.push(entry);
    else if (rule.action === "ask") approval.push(entry);
  }

  return { ...toolPolicy, allowedToolPrefixes: allowed, blockedToolNames: blocked, requireApprovalFor: approval };
}

// Generate opencode.json permission preview
function generatePermissionPreview(toolPolicy: PolicyToolPolicy): string {
  const permission: Record<string, string | Record<string, string>> = {};

  for (const tool of KNOWN_TOOLS) {
    const action = getToolPermAction(tool.id, toolPolicy);
    const rules = getPatternRules(tool.id, toolPolicy);

    if (action === "default" && rules.length === 0) continue;

    if (rules.length === 0) {
      permission[tool.id] = action === "default" ? "allow" : action;
    } else {
      const obj: Record<string, string> = {};
      if (action !== "default") obj["*"] = action;
      for (const r of rules) obj[r.pattern] = r.action;
      permission[tool.id] = obj;
    }
  }

  // Also include any custom (non-known) entries
  const knownIds = new Set(KNOWN_TOOLS.map((t) => t.id));
  for (const entry of toolPolicy.allowedToolPrefixes) {
    const base = entry.includes(":") ? entry.split(":")[0] : entry;
    if (!knownIds.has(base) && !entry.includes(":")) permission[entry] = "allow";
  }
  for (const entry of toolPolicy.blockedToolNames) {
    const base = entry.includes(":") ? entry.split(":")[0] : entry;
    if (!knownIds.has(base) && !entry.includes(":")) permission[entry] = "deny";
  }
  for (const entry of toolPolicy.requireApprovalFor) {
    const base = entry.includes(":") ? entry.split(":")[0] : entry;
    if (!knownIds.has(base) && !entry.includes(":")) permission[entry] = "ask";
  }

  if (Object.keys(permission).length === 0) return "// Default: all permissions allowed";
  return JSON.stringify({ permission }, null, 2);
}

// ── Permission Row Component ──────────────────────────────────────────────

const ACTION_COLORS: Record<PermAction, string> = {
  default: "bg-muted text-muted-foreground",
  allow: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  ask: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  deny: "bg-red-500/15 text-red-400 border-red-500/30",
};

const ACTION_LABELS: Record<PermAction, string> = {
  default: "Default",
  allow: "Allow",
  ask: "Ask",
  deny: "Deny",
};

function PermissionActionSelector({ value, onChange }: { value: PermAction; onChange: (v: PermAction) => void }) {
  const actions: PermAction[] = ["default", "allow", "ask", "deny"];
  return (
    <div className="flex gap-0.5 rounded-md border border-border/50 p-0.5 bg-muted/30">
      {actions.map((a) => (
        <button
          key={a}
          type="button"
          onClick={() => onChange(a)}
          className={cn(
            "px-2 py-0.5 text-[10px] font-medium rounded transition-all",
            value === a ? cn(ACTION_COLORS[a], "border shadow-sm") : "text-muted-foreground hover:text-foreground"
          )}
        >
          {ACTION_LABELS[a]}
        </button>
      ))}
    </div>
  );
}

function PatternRuleEditor({
  rules,
  onChange,
  patternHint,
}: {
  rules: PatternRule[];
  onChange: (rules: PatternRule[]) => void;
  patternHint?: string;
}) {
  const [draft, setDraft] = useState("");
  const [draftAction, setDraftAction] = useState<"allow" | "ask" | "deny">("allow");

  const addRule = () => {
    const p = draft.trim();
    if (p && !rules.some((r) => r.pattern === p)) {
      onChange([...rules, { pattern: p, action: draftAction }]);
      setDraft("");
    }
  };

  return (
    <div className="mt-2 ml-6 space-y-2 border-l-2 border-border/40 pl-3">
      <p className="text-[10px] text-muted-foreground font-medium">
        Pattern Rules <span className="text-muted-foreground/60">(last matching wins)</span>
      </p>
      {rules.length > 0 && (
        <div className="space-y-1">
          {rules.map((rule, idx) => (
            <div key={idx} className="flex items-center gap-2 text-xs">
              <code className="flex-1 font-mono text-[11px] text-foreground/80 bg-muted/50 px-2 py-0.5 rounded">{rule.pattern}</code>
              <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded", ACTION_COLORS[rule.action])}>
                {rule.action}
              </span>
              <button
                type="button"
                onClick={() => onChange(rules.filter((_, i) => i !== idx))}
                className="text-muted-foreground hover:text-destructive transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRule(); } }}
          placeholder={patternHint || "pattern..."}
          className="h-6 text-[11px] flex-1 font-mono"
        />
        <select
          value={draftAction}
          onChange={(e) => setDraftAction(e.target.value as "allow" | "ask" | "deny")}
          className="h-6 text-[10px] bg-muted border border-border rounded px-1.5 text-foreground"
        >
          <option value="allow">allow</option>
          <option value="ask">ask</option>
          <option value="deny">deny</option>
        </select>
        <Button variant="ghost" size="sm" className="h-6 px-1.5" onClick={addRule} disabled={!draft.trim()}>
          <Plus className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

function PermissionRow({
  tool,
  action,
  rules,
  onActionChange,
  onRulesChange,
}: {
  tool: KnownTool;
  action: PermAction;
  rules: PatternRule[];
  onActionChange: (a: PermAction) => void;
  onRulesChange: (r: PatternRule[]) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const ToolIcon = tool.icon;
  const hasRules = rules.length > 0;

  return (
    <div className="group">
      <div className="flex items-center gap-3 py-1.5 px-2 rounded-md hover:bg-muted/30 transition-colors">
        <ToolIcon className={cn("h-3.5 w-3.5 shrink-0", tool.color)} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-foreground">{tool.label}</span>
            <code className="text-[10px] text-muted-foreground font-mono">{tool.id}</code>
          </div>
          <p className="text-[10px] text-muted-foreground/70 truncate">{tool.description}</p>
        </div>
        <div className="flex items-center gap-2">
          {hasRules && (
            <Badge variant="outline" className="text-[9px] py-0 px-1.5 h-4">{rules.length} rule{rules.length !== 1 ? "s" : ""}</Badge>
          )}
          <PermissionActionSelector value={action} onChange={onActionChange} />
          {tool.supportsPatterns && (
            <button
              type="button"
              onClick={() => setExpanded(!expanded)}
              className={cn(
                "p-1 rounded transition-colors",
                expanded ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
              )}
              title="Pattern rules"
            >
              <ChevronsUpDown className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
      {expanded && tool.supportsPatterns && (
        <PatternRuleEditor rules={rules} onChange={onRulesChange} patternHint={tool.patternHint} />
      )}
    </div>
  );
}

// ── Admin Tool Ceiling Row ────────────────────────────────────────────────

type CeilingAction = "allow" | "ask" | "deny" | "none";

const CEILING_COLORS: Record<CeilingAction, string> = {
  none: "bg-muted text-muted-foreground",
  allow: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  ask: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  deny: "bg-red-500/15 text-red-400 border-red-500/30",
};

const CEILING_LABELS: Record<CeilingAction, string> = {
  none: "No Cap",
  allow: "Cap: Allow",
  ask: "Cap: Ask",
  deny: "Cap: Deny",
};

function CeilingActionSelector({ value, onChange }: { value: CeilingAction; onChange: (v: CeilingAction) => void }) {
  const actions: CeilingAction[] = ["none", "allow", "ask", "deny"];
  return (
    <div className="flex gap-0.5 rounded-md border border-border/50 p-0.5 bg-muted/30">
      {actions.map((a) => (
        <button
          key={a}
          type="button"
          onClick={() => onChange(a)}
          className={cn(
            "px-2 py-0.5 text-[10px] font-medium rounded transition-all",
            value === a ? cn(CEILING_COLORS[a], "border shadow-sm") : "text-muted-foreground hover:text-foreground"
          )}
        >
          {CEILING_LABELS[a]}
        </button>
      ))}
    </div>
  );
}

function CeilingRow({
  tool,
  ceiling,
  onChange,
}: {
  tool: KnownTool;
  ceiling: CeilingAction;
  onChange: (v: CeilingAction) => void;
}) {
  const ToolIcon = tool.icon;
  return (
    <div className="flex items-center gap-3 py-1.5 px-2 rounded-md hover:bg-muted/30 transition-colors">
      <ToolIcon className={cn("h-3.5 w-3.5 shrink-0", tool.color)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-foreground">{tool.label}</span>
          <code className="text-[10px] text-muted-foreground font-mono">{tool.id}</code>
        </div>
      </div>
      <CeilingActionSelector value={ceiling} onChange={onChange} />
    </div>
  );
}

function ToggleSwitch({ label, description, checked, onChange }: { label: string; description?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{label}</p>
        {description && <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{description}</p>}
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={cn(
          "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          checked ? "bg-emerald-500" : "bg-muted",
        )}
      >
        <span
          className={cn(
            "pointer-events-none block h-4 w-4 rounded-full bg-white shadow-lg ring-0 transition-transform duration-200",
            checked ? "translate-x-5" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

function SectionPanel({ icon: Icon, title, accentColor, children }: {
  icon: React.ElementType;
  title: string;
  accentColor: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-lg border border-border/50 bg-card overflow-hidden")}>
      <div className={cn("border-l-[3px] pl-4 pr-4 py-3", accentColor)}>
        <div className="flex items-center gap-2 mb-3">
          <Icon className="h-4 w-4 text-foreground/70" />
          <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        </div>
        <div className="space-y-4">
          {children}
        </div>
      </div>
    </div>
  );
}

function NumberField({ label, value, onChange, placeholder, hint, className }: {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  placeholder?: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label className="text-xs font-medium text-foreground/80">{label}</Label>
      <Input
        type="number"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value.trim() === "" ? undefined : Math.max(0, Number(e.target.value) || 0))}
        className="h-8 text-sm w-full"
        min={0}
        placeholder={placeholder}
      />
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

// ── KPI Chip ───────────────────────────────────────────────────────────────

function KpiChip({ icon: Icon, label, value, tone = "neutral" }: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  tone?: "success" | "warning" | "danger" | "neutral";
}) {
  return (
    <div className={cn(
      "flex items-center gap-2 rounded-md border px-3 py-1.5",
      tone === "success" && "border-emerald-500/20 bg-emerald-500/5",
      tone === "warning" && "border-amber-500/20 bg-amber-500/5",
      tone === "danger" && "border-red-500/20 bg-red-500/5",
      tone === "neutral" && "border-border/50 bg-card",
    )}>
      <Icon className={cn(
        "h-3.5 w-3.5",
        tone === "success" && "text-emerald-500",
        tone === "warning" && "text-amber-500",
        tone === "danger" && "text-red-500",
        tone === "neutral" && "text-muted-foreground",
      )} />
      <div>
        <p className="text-[10px] text-muted-foreground leading-none">{label}</p>
        <p className="text-sm font-semibold tabular-nums text-foreground">{value}</p>
      </div>
    </div>
  );
}

// ── Policy list sidebar ────────────────────────────────────────────────────

interface PolicySidebarProps {
  policies: PolicyInfo[];
  selectedName: string | null;
  isCreateMode: boolean;
  onSelect: (name: string) => void;
  onCreateNew: () => void;
  canMutate: boolean;
  searchQuery: string;
  onSearchChange: (q: string) => void;
}

function PolicySidebar({
  policies, selectedName, isCreateMode, onSelect, onCreateNew, canMutate, searchQuery, onSearchChange,
}: PolicySidebarProps) {
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return policies;
    const q = searchQuery.toLowerCase();
    return policies.filter(p =>
      p.name.toLowerCase().includes(q) ||
      (p.allowed_models || []).some(m => m.toLowerCase().includes(q)) ||
      (p.allowed_mcp_servers || []).some(s => s.toLowerCase().includes(q))
    );
  }, [policies, searchQuery]);

  return (
    <div className="w-56 shrink-0 border-r border-border/40 flex flex-col h-full bg-background">
      <div className="p-3 border-b border-border/40 space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-1.5">
            <ShieldAlert className="h-3.5 w-3.5" /> Policies
          </h2>
          <Badge variant="outline" className="text-[9px] h-4 px-1.5">{policies.length}</Badge>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-3 w-3 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Filter..."
            className="h-7 pl-7 text-[11px]"
          />
        </div>
        {canMutate && (
          <Button
            variant={isCreateMode ? "default" : "outline"}
            size="sm"
            className="w-full h-7 text-[11px]"
            onClick={onCreateNew}
          >
            <Plus className="h-3 w-3 mr-1" /> New Policy
          </Button>
        )}
      </div>
      <ScrollArea className="flex-1">
        {filtered.length === 0 ? (
          <div className="p-4 text-center text-[11px] text-muted-foreground">
            {searchQuery ? "No matching policies." : "No policies yet."}
          </div>
        ) : (
          <div className="p-1.5 space-y-0.5">
            {filtered.map((p) => {
              const isSelected = selectedName === p.name && !isCreateMode;
              const hasGuardrails = p.input_guardrails.blockPromptInjection || p.output_guardrails.maskPII;
              const hasHitl = p.mcp_require_hitl;
              return (
                <button
                  key={p.name}
                  onClick={() => onSelect(p.name)}
                  className={cn(
                    "w-full text-left rounded-md px-2.5 py-2 transition-all",
                    isSelected
                      ? "bg-primary/8 border-l-[3px] border-l-primary"
                      : "border-l-[3px] border-l-transparent hover:bg-muted/50",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      "h-2 w-2 shrink-0 rounded-full",
                      hasGuardrails ? "bg-emerald-500" : hasHitl ? "bg-amber-500" : "bg-muted-foreground/30",
                    )} />
                    <span className="truncate text-xs font-medium text-foreground">{p.name}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-1 pl-4 text-[10px] text-muted-foreground">
                    {p.allowed_models.length > 0 && (
                      <span className="flex items-center gap-0.5">
                        <BrainCircuit className="h-2.5 w-2.5" /> {p.allowed_models.length}
                      </span>
                    )}
                    {p.allowed_mcp_servers.length > 0 && (
                      <span className="flex items-center gap-0.5">
                        <Globe className="h-2.5 w-2.5" /> {p.allowed_mcp_servers.length}
                      </span>
                    )}
                    {hasHitl && (
                      <span className="flex items-center gap-0.5 text-amber-500">
                        <Eye className="h-2.5 w-2.5" />
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

// ── Main PolicyEditor component ────────────────────────────────────────────

interface PolicyEditorProps {
  selectedPolicyName: string | null;
}

export function PolicyEditor({ selectedPolicyName }: PolicyEditorProps) {
  const { token, namespace, canMutate } = useConnection();
  const ws = useWorkspace();

  const selectedPolicy: PolicyInfo | null = useMemo(
    () => ws.policies.find((p) => p.name === selectedPolicyName) ?? null,
    [ws.policies, selectedPolicyName],
  );

  const [isCreateMode, setIsCreateMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDiscardOpen, setConfirmDiscardOpen] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<PolicyTab>("overview");

  const hasUserEdits = useRef(false);
  const lastLoadedPolicyName = useRef<string | null>(null);
  const pendingPolicyRef = useRef<PolicyInfo | null | undefined>(null);

  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  const isDirty = useMemo(() => {
    if (isCreateMode) return hasUserEdits.current;
    if (!selectedPolicy) return false;
    return !formsAreEqual(form, policyToForm(selectedPolicy));
  }, [isCreateMode, form, selectedPolicy]);

  // ── Load form from a policy object ─────────────────────────────────────
  function loadPolicy(policy: PolicyInfo) {
    setIsCreateMode(false);
    setForm(policyToForm(policy));
    hasUserEdits.current = false;
    lastLoadedPolicyName.current = policy.name;
  }

  const markEdit = useCallback(() => { hasUserEdits.current = true; }, []);

  const updateForm = useCallback((patch: Partial<FormState>) => {
    markEdit();
    setForm((prev) => ({ ...prev, ...patch }));
  }, [markEdit]);

  const updateInput = useCallback((patch: Partial<PolicyInputGuardrails>) => {
    markEdit();
    setForm((prev) => ({ ...prev, inputGuardrails: { ...prev.inputGuardrails, ...patch } }));
  }, [markEdit]);

  const updateOutput = useCallback((patch: Partial<PolicyOutputGuardrails>) => {
    markEdit();
    setForm((prev) => ({ ...prev, outputGuardrails: { ...prev.outputGuardrails, ...patch } }));
  }, [markEdit]);

  const updateTool = useCallback((patch: Partial<PolicyToolPolicy>) => {
    markEdit();
    setForm((prev) => ({ ...prev, toolPolicy: { ...prev.toolPolicy, ...patch } }));
  }, [markEdit]);

  const updateMemory = useCallback((patch: Partial<PolicyMemoryPolicy>) => {
    markEdit();
    setForm((prev) => ({ ...prev, memoryPolicy: { ...prev.memoryPolicy, ...patch } }));
  }, [markEdit]);

  // ── Effect: when selectedPolicy changes externally ─────────────────────
  useEffect(() => {
    if (!selectedPolicy) {
      if (!isCreateMode && hasUserEdits.current) {
        setConfirmDiscardOpen(true);
      } else {
        setIsCreateMode(false);
        hasUserEdits.current = false;
        lastLoadedPolicyName.current = null;
      }
      return;
    }
    if (lastLoadedPolicyName.current === selectedPolicy.name && !isCreateMode) return;
    if (hasUserEdits.current) {
      pendingPolicyRef.current = selectedPolicy;
      setConfirmDiscardOpen(true);
    } else {
      loadPolicy(selectedPolicy);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPolicy]);

  const resetToNew = useCallback(() => {
    if (hasUserEdits.current) {
      pendingPolicyRef.current = null;
      setConfirmDiscardOpen(true);
      return;
    }
    setIsCreateMode(true);
    setForm(EMPTY_FORM());
    setActiveTab("guardrails");
    hasUserEdits.current = false;
    lastLoadedPolicyName.current = null;
  }, []);

  // ── Save handler ───────────────────────────────────────────────────────
  const handleSave = useCallback(async () => {
    if (!token || !namespace) return;
    setSaving(true);
    try {
      if (isCreateMode) {
        const trimmedName = form.name.trim();
        if (!trimmedName) { toast.error("Policy name is required."); return; }
        if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(trimmedName)) {
          toast.error("Invalid name. Use lowercase letters, numbers, and hyphens.");
          return;
        }
        const payload: CreatePolicyPayload = {
          name: trimmedName,
          sealed: form.sealed,
          input_guardrails: form.inputGuardrails,
          output_guardrails: form.outputGuardrails,
          allowed_models: form.allowedModels,
          allowed_mcp_servers: form.allowedMcpServers,
          mcp_require_hitl: form.mcpRequireHitl,
          tool_policy: {
            ...form.toolPolicy,
            adminToolCeiling: Object.keys(form.adminToolCeiling).length > 0 ? form.adminToolCeiling : undefined,
          },
          memory_policy: form.memoryPolicy,
        };
        await createPolicy(token, namespace, payload);
        toast.success(`Policy "${trimmedName}" created.`);
        setIsCreateMode(false);
        hasUserEdits.current = false;
        lastLoadedPolicyName.current = null;
      } else {
        const payload: UpdatePolicyPayload = {
          sealed: form.sealed,
          input_guardrails: form.inputGuardrails,
          output_guardrails: form.outputGuardrails,
          allowed_models: form.allowedModels,
          allowed_mcp_servers: form.allowedMcpServers,
          mcp_require_hitl: form.mcpRequireHitl,
          tool_policy: {
            ...form.toolPolicy,
            adminToolCeiling: Object.keys(form.adminToolCeiling).length > 0 ? form.adminToolCeiling : undefined,
          },
          memory_policy: form.memoryPolicy,
        };
        await updatePolicy(token, namespace, form.name, payload);
        toast.success(`Policy "${form.name}" updated.`);
        hasUserEdits.current = false;
      }
      void ws.refreshWorkspaceData({ silent: false });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save policy.";
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }, [token, namespace, isCreateMode, form, ws]);

  // ── Delete handler ─────────────────────────────────────────────────────
  const handleDelete = useCallback(async () => {
    if (!token || !namespace || !selectedPolicyName) return;
    setDeleting(true);
    try {
      await deletePolicy(token, namespace, selectedPolicyName);
      toast.success(`Policy "${selectedPolicyName}" deleted.`);
      hasUserEdits.current = false;
      lastLoadedPolicyName.current = null;
      void ws.refreshWorkspaceData({ silent: false });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to delete policy.";
      toast.error(msg);
    } finally {
      setDeleting(false);
    }
  }, [token, namespace, selectedPolicyName, ws]);

  // ── Keyboard shortcut: Ctrl+S ──────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if ((isCreateMode || selectedPolicy) && canMutate && !saving) {
          void handleSave();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isCreateMode, selectedPolicy, canMutate, saving, handleSave]);

  const handleSelectPolicy = useCallback((name: string) => {
    ws.selectPolicy?.(name);
  }, [ws]);

  // ── Computed values ────────────────────────────────────────────────────
  const modelCount = form.allowedModels.length;
  const mcpCount = form.allowedMcpServers.length;
  const guardrailCount = countActiveGuardrails(form);
  const toolRestrictions = countToolRestrictions(form);

  // ── Empty state: no policy selected ────────────────────────────────────
  if (!selectedPolicy && !isCreateMode) {
    return (
      <div className="flex flex-1 h-full overflow-hidden rounded-lg border border-border/40 bg-background">
        <PolicySidebar
          policies={ws.policies}
          selectedName={selectedPolicyName}
          isCreateMode={isCreateMode}
          onSelect={handleSelectPolicy}
          onCreateNew={resetToNew}
          canMutate={canMutate}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-border/70 bg-muted/20">
            <ShieldAlert className="h-8 w-8 text-muted-foreground/40" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-foreground">Select a policy</p>
            <p className="mt-1 text-xs text-muted-foreground max-w-xs">
              Choose a policy from the sidebar to view or edit, or create a new one.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Main render ────────────────────────────────────────────────────────
  return (
    <div className="flex flex-1 h-full overflow-hidden rounded-lg border border-border/40 bg-background">
      <PolicySidebar
        policies={ws.policies}
        selectedName={selectedPolicyName}
        isCreateMode={isCreateMode}
        onSelect={handleSelectPolicy}
        onCreateNew={resetToNew}
        canMutate={canMutate}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
      />

      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        {/* ── Sticky Banner ──────────────────────────────────────────── */}
        <div className="flex shrink-0 items-center gap-3 border-b border-border/50 bg-background/80 px-5 py-2.5 backdrop-blur-sm">
          <Shield className="h-5 w-5 text-primary shrink-0" />
          <div className="flex-1 min-w-0">
            {isCreateMode ? (
              <h2 className="text-sm font-semibold text-foreground">New Policy</h2>
            ) : (
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-foreground truncate">{form.name}</h2>
                <Badge
                  variant="outline"
                  className={cn(
                    "text-[9px] px-1.5 shrink-0",
                    guardrailCount > 0
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                      : "border-border/60 text-muted-foreground",
                  )}
                >
                  {guardrailCount > 0 ? "Active" : "Passive"}
                </Badge>
              </div>
            )}
            {!isCreateMode && (
              <div className="flex items-center gap-3 mt-0.5 text-[10px] text-muted-foreground">
                {modelCount > 0 && <span>{modelCount} model{modelCount !== 1 ? "s" : ""}</span>}
                {mcpCount > 0 && <span>{mcpCount} MCP</span>}
                {form.mcpRequireHitl && <span className="text-amber-500">HITL</span>}
                {toolRestrictions > 0 && <span>{toolRestrictions} tool restriction{toolRestrictions !== 1 ? "s" : ""}</span>}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            {canMutate && !isCreateMode && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-[11px] text-destructive hover:text-destructive hover:bg-destructive/10"
                onClick={() => setConfirmDeleteOpen(true)}
                disabled={deleting}
              >
                {deleting ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Trash2 className="h-3 w-3 mr-1" />}
                Delete
              </Button>
            )}
            {canMutate && (
              <Button
                size="sm"
                className="h-7 text-[11px]"
                onClick={() => void handleSave()}
                disabled={saving || (!isCreateMode && !isDirty)}
              >
                {saving ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Save className="h-3 w-3 mr-1" />}
                {saving ? "Saving..." : "Save"}
              </Button>
            )}
          </div>
        </div>

        {/* ── Tabbed Content ─────────────────────────────────────────── */}
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as PolicyTab)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="shrink-0 border-b border-border/40 px-5">
            <TabsList className="h-9 gap-0 rounded-none border-0 bg-transparent p-0">
              {!isCreateMode && (
                <TabsTrigger value="overview" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                  <Layers className="mr-1.5 h-3.5 w-3.5" />
                  Overview
                </TabsTrigger>
              )}
              <TabsTrigger value="guardrails" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />
                Guardrails
                {guardrailCount > 0 && <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[9px]">{guardrailCount}</Badge>}
              </TabsTrigger>
              <TabsTrigger value="access" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                <KeyRound className="mr-1.5 h-3.5 w-3.5" />
                Access
              </TabsTrigger>
              <TabsTrigger value="tools" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                <Wrench className="mr-1.5 h-3.5 w-3.5" />
                Tools
                {toolRestrictions > 0 && <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[9px]">{toolRestrictions}</Badge>}
              </TabsTrigger>
              <TabsTrigger value="memory" className="relative h-9 rounded-none border-b-2 border-transparent px-3 text-xs font-medium transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none">
                <Database className="mr-1.5 h-3.5 w-3.5" />
                Memory
              </TabsTrigger>
            </TabsList>
          </div>

          <ScrollArea className="flex-1 min-h-0">
            <div className="p-5 max-w-3xl">

              {/* ═══════ OVERVIEW TAB ═══════ */}
              {!isCreateMode && (
                <TabsContent value="overview" className="mt-0 space-y-5">
                  {/* KPI Scorecard */}
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                    <KpiChip
                      icon={ShieldCheck}
                      label="Guardrails"
                      value={guardrailCount}
                      tone={guardrailCount > 0 ? "success" : "neutral"}
                    />
                    <KpiChip
                      icon={BrainCircuit}
                      label="Models"
                      value={modelCount || "All"}
                      tone={modelCount > 0 ? "warning" : "neutral"}
                    />
                    <KpiChip
                      icon={Ban}
                      label="Tool Restrictions"
                      value={toolRestrictions}
                      tone={toolRestrictions > 0 ? "danger" : "neutral"}
                    />
                    <KpiChip
                      icon={Eye}
                      label="HITL"
                      value={form.mcpRequireHitl ? "Required" : "Off"}
                      tone={form.mcpRequireHitl ? "warning" : "neutral"}
                    />
                    <KpiChip
                      icon={ShieldAlert}
                      label="Sealed"
                      value={form.sealed ? "Locked" : "Open"}
                      tone={form.sealed ? "danger" : "neutral"}
                    />
                  </div>

                  {/* Quick summary cards */}
                  <div className="grid gap-3 sm:grid-cols-2">
                    {/* Input Protection */}
                    <div className="rounded-lg border border-border/50 bg-card p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <Shield className="h-4 w-4 text-amber-500" />
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Input Protection</h4>
                      </div>
                      <div className="space-y-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Prompt injection blocking</span>
                          <span className={form.inputGuardrails.blockPromptInjection ? "text-emerald-500 font-medium" : "text-muted-foreground/50"}>
                            {form.inputGuardrails.blockPromptInjection ? "Enabled" : "Off"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Max input tokens</span>
                          <span className="font-medium text-foreground">
                            {form.inputGuardrails.maxInputTokens > 0 ? form.inputGuardrails.maxInputTokens.toLocaleString() : "Unlimited"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Blocked patterns</span>
                          <span className="font-medium text-foreground">{form.inputGuardrails.blockedPatterns.length}</span>
                        </div>
                      </div>
                    </div>

                    {/* Output Protection */}
                    <div className="rounded-lg border border-border/50 bg-card p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <Shield className="h-4 w-4 text-violet-500" />
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Output Protection</h4>
                      </div>
                      <div className="space-y-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">PII masking</span>
                          <span className={form.outputGuardrails.maskPII ? "text-emerald-500 font-medium" : "text-muted-foreground/50"}>
                            {form.outputGuardrails.maskPII ? "Enabled" : "Off"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Max output tokens</span>
                          <span className="font-medium text-foreground">
                            {form.outputGuardrails.maxOutputTokens > 0 ? form.outputGuardrails.maxOutputTokens.toLocaleString() : "Unlimited"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Blocked patterns</span>
                          <span className="font-medium text-foreground">{form.outputGuardrails.blockedOutputPatterns.length}</span>
                        </div>
                      </div>
                    </div>

                    {/* Model & MCP */}
                    <div className="rounded-lg border border-border/50 bg-card p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <KeyRound className="h-4 w-4 text-sky-500" />
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Access Control</h4>
                      </div>
                      <div className="space-y-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Allowed models</span>
                          <span className="font-medium text-foreground">{modelCount || "All"}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Allowed MCP servers</span>
                          <span className="font-medium text-foreground">{mcpCount || "All"}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Human-in-the-loop</span>
                          <span className={form.mcpRequireHitl ? "text-amber-500 font-medium" : "text-muted-foreground/50"}>
                            {form.mcpRequireHitl ? "Required" : "Off"}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Tool Governance */}
                    <div className="rounded-lg border border-border/50 bg-card p-4">
                      <div className="flex items-center gap-2 mb-3">
                        <Wrench className="h-4 w-4 text-emerald-500" />
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Tool Governance</h4>
                      </div>
                      <div className="space-y-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Max delegation depth</span>
                          <span className="font-medium text-foreground">
                            {form.toolPolicy.maxDelegationDepth != null ? form.toolPolicy.maxDelegationDepth : "Unlimited"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Blocked tools</span>
                          <span className="font-medium text-foreground">{form.toolPolicy.blockedToolNames.length}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted-foreground">Require approval</span>
                          <span className="font-medium text-foreground">{form.toolPolicy.requireApprovalFor.length}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Active signals */}
                  {guardrailCount > 0 && (
                    <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                        <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">Policy Active</span>
                      </div>
                      <p className="text-[11px] text-emerald-600/80 dark:text-emerald-400/80 leading-relaxed">
                        This policy has {guardrailCount} active guardrail{guardrailCount !== 1 ? "s" : ""} protecting agent behavior.
                        {form.mcpRequireHitl && " Human-in-the-loop approval is required for MCP tool calls."}
                        {form.toolPolicy.blockedToolNames.length > 0 && ` ${form.toolPolicy.blockedToolNames.length} tool${form.toolPolicy.blockedToolNames.length !== 1 ? "s" : ""} are explicitly blocked.`}
                      </p>
                    </div>
                  )}

                  {/* Policy Seal */}
                  <div className={cn(
                    "rounded-lg border p-4",
                    form.sealed
                      ? "border-red-500/30 bg-red-500/5"
                      : "border-border/50 bg-card"
                  )}>
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-2">
                        <ShieldAlert className={cn("h-4 w-4", form.sealed ? "text-red-500" : "text-muted-foreground")} />
                        <div>
                          <h4 className="text-xs font-semibold text-foreground">Policy Seal</h4>
                          <p className="text-[10px] text-muted-foreground mt-0.5 leading-relaxed">
                            {form.sealed
                              ? "This policy is sealed. It cannot be modified via the API or kubectl. Only Helm upgrades or direct etcd access can unseal it."
                              : "Seal this policy to prevent any modifications. Enforced by OPA Gatekeeper admission webhook."}
                          </p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => updateForm({ sealed: !form.sealed })}
                        className={cn(
                          "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                          form.sealed ? "bg-red-500" : "bg-input"
                        )}
                      >
                        <span className={cn(
                          "pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm ring-0 transition-transform duration-200",
                          form.sealed ? "translate-x-5" : "translate-x-0.5"
                        )} />
                      </button>
                    </div>
                    {form.sealed && (
                      <div className="mt-3 flex items-center gap-2 px-2 py-1.5 rounded-md bg-red-500/10 border border-red-500/20">
                        <AlertTriangle className="h-3 w-3 text-red-400 shrink-0" />
                        <span className="text-[10px] text-red-400 font-medium">
                          Warning: Once saved as sealed, this policy cannot be modified without OPA Gatekeeper being disabled or using a Helm upgrade.
                        </span>
                      </div>
                    )}
                  </div>
                </TabsContent>
              )}

              {/* ═══════ GUARDRAILS TAB ═══════ */}
              <TabsContent value="guardrails" className="mt-0 space-y-4">
                {/* Create mode: name field */}
                {isCreateMode && (
                  <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 space-y-2">
                    <Label className="text-xs font-semibold text-foreground">Policy Name</Label>
                    <Input
                      value={form.name}
                      onChange={(e) => updateForm({ name: e.target.value })}
                      placeholder="my-security-policy"
                      className="h-9 text-sm font-mono"
                      autoFocus
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Lowercase letters, numbers, and hyphens. Must be unique within the namespace.
                    </p>
                  </div>
                )}

                <SectionPanel icon={Shield} title="Input Guardrails" accentColor="border-l-amber-500">
                  <ToggleSwitch
                    label="Block Prompt Injection"
                    description="Enable prompt-injection detection and blocking for all incoming requests."
                    checked={form.inputGuardrails.blockPromptInjection}
                    onChange={(v) => updateInput({ blockPromptInjection: v })}
                  />
                  <NumberField
                    label="Max Input Tokens"
                    value={form.inputGuardrails.maxInputTokens || undefined}
                    onChange={(v) => updateInput({ maxInputTokens: v ?? 0 })}
                    placeholder="0 = no limit"
                    hint="Maximum token count allowed per request. Set to 0 for unlimited."
                    className="max-w-xs"
                  />
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium text-foreground/80">Blocked Input Patterns</Label>
                    <TagListEditor
                      values={form.inputGuardrails.blockedPatterns}
                      onChange={(v) => updateInput({ blockedPatterns: v })}
                      placeholder="Add regex pattern..."
                    />
                    <p className="text-[10px] text-muted-foreground">Regex patterns that will cause immediate rejection of matching inputs.</p>
                  </div>
                </SectionPanel>

                <SectionPanel icon={Shield} title="Output Guardrails" accentColor="border-l-violet-500">
                  <ToggleSwitch
                    label="Mask PII"
                    description="Automatically redact names, emails, credit cards, and other PII from model responses."
                    checked={form.outputGuardrails.maskPII}
                    onChange={(v) => updateOutput({ maskPII: v })}
                  />
                  <NumberField
                    label="Max Output Tokens"
                    value={form.outputGuardrails.maxOutputTokens || undefined}
                    onChange={(v) => updateOutput({ maxOutputTokens: v ?? 0 })}
                    placeholder="0 = no limit"
                    hint="Maximum token count allowed per response. Set to 0 for unlimited."
                    className="max-w-xs"
                  />
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium text-foreground/80">Blocked Output Patterns</Label>
                    <TagListEditor
                      values={form.outputGuardrails.blockedOutputPatterns}
                      onChange={(v) => updateOutput({ blockedOutputPatterns: v })}
                      placeholder="Add regex pattern..."
                    />
                    <p className="text-[10px] text-muted-foreground">Regex patterns that will be stripped from model output.</p>
                  </div>
                </SectionPanel>
              </TabsContent>

              {/* ═══════ ACCESS TAB ═══════ */}
              <TabsContent value="access" className="mt-0 space-y-4">
                <SectionPanel icon={BrainCircuit} title="Model Access" accentColor="border-l-sky-500">
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium text-foreground/80">Allowed Models</Label>
                    <TagListEditor
                      values={form.allowedModels}
                      onChange={(v) => updateForm({ allowedModels: v })}
                      placeholder="e.g. litellm/gpt-5-mini, claude-sonnet-4"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      {modelCount === 0
                        ? "Empty list = all models are allowed. Add entries to create an allowlist."
                        : `${modelCount} model${modelCount !== 1 ? "s" : ""} allowlisted. Only these models may be used.`}
                    </p>
                  </div>
                </SectionPanel>

                <SectionPanel icon={Globe} title="MCP Server Access" accentColor="border-l-cyan-500">
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium text-foreground/80">Allowed MCP Servers</Label>
                    <TagListEditor
                      values={form.allowedMcpServers}
                      onChange={(v) => updateForm({ allowedMcpServers: v })}
                      placeholder="e.g. code-exec, web-search, context7"
                    />
                    <p className="text-[10px] text-muted-foreground">
                      {mcpCount === 0
                        ? "Empty list = all MCP servers are allowed."
                        : `${mcpCount} server${mcpCount !== 1 ? "s" : ""} allowlisted.`}
                    </p>
                  </div>
                  <ToggleSwitch
                    label="Require Human-in-the-Loop for MCP"
                    description="All tool calls routed through MCP servers will pause for human approval before execution."
                    checked={form.mcpRequireHitl}
                    onChange={(v) => updateForm({ mcpRequireHitl: v })}
                  />
                </SectionPanel>
              </TabsContent>

              {/* ═══════ TOOLS TAB ═══════ */}
              <TabsContent value="tools" className="mt-0 space-y-4">
                <SectionPanel icon={Wrench} title="Runtime Permissions" accentColor="border-l-emerald-500">
                  <p className="text-[11px] text-muted-foreground -mt-1 mb-3">
                    Configure what the agent runtime is allowed to do. Maps directly to OpenCode&apos;s permission system.
                    <span className="text-muted-foreground/60 ml-1">Last matching rule wins for pattern rules.</span>
                  </p>
                  <NumberField
                    label="Max Delegation Depth"
                    value={form.toolPolicy.maxDelegationDepth}
                    onChange={(v) => updateTool({ maxDelegationDepth: v })}
                    placeholder="unlimited"
                    hint="Maximum agent-to-agent sub-delegation chain length."
                    className="max-w-xs"
                  />
                </SectionPanel>

                {PERMISSION_CATEGORIES.map((cat) => {
                  const tools = KNOWN_TOOLS.filter((t) => t.category === cat.key);
                  if (tools.length === 0) return null;
                  const CatIcon = cat.icon;
                  return (
                    <div key={cat.key} className="rounded-lg border border-border/60 bg-card">
                      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
                        <CatIcon className="h-3.5 w-3.5 text-muted-foreground" />
                        <span className="text-xs font-medium text-foreground/80">{cat.label}</span>
                        <span className="text-[10px] text-muted-foreground">({tools.length})</span>
                      </div>
                      <div className="divide-y divide-border/30 px-1 py-0.5">
                        {tools.map((tool) => (
                          <PermissionRow
                            key={tool.id}
                            tool={tool}
                            action={getToolPermAction(tool.id, form.toolPolicy)}
                            rules={getPatternRules(tool.id, form.toolPolicy)}
                            onActionChange={(a) => updateTool(setToolPermAction(tool.id, a, form.toolPolicy))}
                            onRulesChange={(r) => updateTool(setPatternRules(tool.id, r, form.toolPolicy))}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}

                {/* JSON Preview */}
                <div className="rounded-lg border border-border/60 bg-card">
                  <div className="flex items-center gap-2 px-3 py-2 border-b border-border/40">
                    <Code2 className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-foreground/80">Generated Config Preview</span>
                    <span className="text-[10px] text-muted-foreground ml-auto font-mono">opencode.json</span>
                  </div>
                  <pre className="px-3 py-2 text-[11px] font-mono text-muted-foreground overflow-x-auto max-h-[200px] overflow-y-auto">
                    {generatePermissionPreview(form.toolPolicy)}
                  </pre>
                </div>

                {/* ── Admin Tool Ceiling ──────────────────────────────────── */}
                <div className="rounded-lg border border-orange-500/30 bg-orange-500/5">
                  <div className="flex items-center gap-2 px-3 py-2.5 border-b border-orange-500/20">
                    <ShieldAlert className="h-4 w-4 text-orange-500" />
                    <div className="flex-1">
                      <span className="text-xs font-semibold text-foreground">Admin Tool Ceiling</span>
                      <span className="text-[10px] text-muted-foreground ml-2">Platform Admin Only</span>
                    </div>
                    <Badge variant="outline" className="text-[9px] py-0 px-1.5 h-4 border-orange-500/30 text-orange-400">
                      {Object.keys(form.adminToolCeiling).length} cap{Object.keys(form.adminToolCeiling).length !== 1 ? "s" : ""}
                    </Badge>
                  </div>
                  <div className="px-3 py-2">
                    <p className="text-[10px] text-muted-foreground mb-3 leading-relaxed">
                      Set maximum permission ceilings per tool. Even if an agent&apos;s config says &quot;allow&quot;, the ceiling
                      caps the effective permission. Enforced by the operator at pod creation time.
                    </p>
                    <div className="divide-y divide-border/30">
                      {KNOWN_TOOLS.filter((t) => t.id !== "doom_loop").map((tool) => {
                        const ceilingVal = form.adminToolCeiling[tool.id] as CeilingAction | undefined;
                        return (
                          <CeilingRow
                            key={tool.id}
                            tool={tool}
                            ceiling={ceilingVal || "none"}
                            onChange={(v) => {
                              const next = { ...form.adminToolCeiling };
                              if (v === "none") {
                                delete next[tool.id];
                              } else {
                                next[tool.id] = v as "allow" | "ask" | "deny";
                              }
                              updateForm({ adminToolCeiling: next });
                            }}
                          />
                        );
                      })}
                    </div>
                  </div>
                </div>
              </TabsContent>

              {/* ═══════ MEMORY TAB ═══════ */}
              <TabsContent value="memory" className="mt-0 space-y-4">
                <SectionPanel icon={Database} title="Memory Governance" accentColor="border-l-pink-500">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <NumberField
                      label="Max Injected Memories"
                      value={form.memoryPolicy.maxInjectedMemories}
                      onChange={(v) => updateMemory({ maxInjectedMemories: v })}
                      placeholder="unlimited"
                      hint="Max memory records per context injection."
                    />
                    <NumberField
                      label="Max Injected Chars"
                      value={form.memoryPolicy.maxInjectedChars}
                      onChange={(v) => updateMemory({ maxInjectedChars: v })}
                      placeholder="unlimited"
                      hint="Max total characters from memory injection."
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium text-foreground/80">Allowed Memory Types</Label>
                    <TagListEditor
                      values={form.memoryPolicy.allowedMemoryTypes}
                      onChange={(v) => updateMemory({ allowedMemoryTypes: v })}
                      placeholder="e.g. procedural, episodic, semantic"
                    />
                    <p className="text-[10px] text-muted-foreground">Empty = all memory types allowed.</p>
                  </div>
                  <ToggleSwitch
                    label="Auto-promote high-signal memory"
                    description="Automatically promote memory records that match high-signal criteria to long-term storage."
                    checked={form.memoryPolicy.autoPromote}
                    onChange={(v) => updateMemory({ autoPromote: v })}
                  />
                </SectionPanel>
              </TabsContent>

            </div>
          </ScrollArea>

          {/* ── Dirty state banner ──────────────────────────────────────── */}
          {isDirty && (
            <div className="shrink-0 flex items-center gap-2 px-5 py-2 border-t border-amber-500/20 bg-amber-500/5">
              <Info className="h-3.5 w-3.5 text-amber-500 shrink-0" />
              <p className="text-[11px] text-amber-700 dark:text-amber-300 flex-1">
                You have unsaved changes. Press <kbd className="px-1 py-0.5 bg-amber-500/10 border border-amber-500/20 rounded text-[10px] mx-0.5">Ctrl+S</kbd> to save.
              </p>
              <Button size="sm" className="h-6 text-[10px]" onClick={() => void handleSave()} disabled={saving}>
                <Save className="h-3 w-3 mr-1" /> Save Now
              </Button>
            </div>
          )}
        </Tabs>
      </div>

      {/* ── Confirm dialogs ─────────────────────────────────────────────── */}
      <ConfirmDialog
        open={confirmDiscardOpen}
        onOpenChange={(open) => {
          if (!open) {
            pendingPolicyRef.current = undefined;
            setConfirmDiscardOpen(false);
          }
        }}
        title="Discard unsaved changes?"
        description={`You have unsaved changes to "${form.name || 'this policy'}". Switching will discard them.`}
        confirmLabel="Discard"
        variant="destructive"
        onConfirm={() => {
          const pending = pendingPolicyRef.current;
          pendingPolicyRef.current = undefined;
          setConfirmDiscardOpen(false);
          if (pending) {
            loadPolicy(pending);
          } else {
            setIsCreateMode(true);
            setForm(EMPTY_FORM());
            hasUserEdits.current = false;
            lastLoadedPolicyName.current = null;
          }
        }}
      />
      <ConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
        title={`Delete policy "${form.name}"?`}
        description="This will permanently remove this policy. Agents referencing it will lose their policy assignment."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => void handleDelete()}
      />
    </div>
  );
}
