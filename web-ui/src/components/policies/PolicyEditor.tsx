import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Plus, Save, Trash2, ShieldAlert, X, AlertTriangle, Loader2,
  Search, Info, Eye, Gavel, BrainCircuit, Globe, Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
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
    inputGuardrails: { ...DEFAULT_INPUT },
    outputGuardrails: { ...DEFAULT_OUTPUT },
    allowedModels: [] as string[],
    allowedMcpServers: [] as string[],
    mcpRequireHitl: true,
    toolPolicy: { ...DEFAULT_TOOL } as PolicyToolPolicy,
    memoryPolicy: { ...DEFAULT_MEMORY } as PolicyMemoryPolicy,
  };
}

type FormState = ReturnType<typeof EMPTY_FORM>;

// ── Utility helpers ────────────────────────────────────────────────────────

function formsAreEqual(a: FormState, b: FormState): boolean {
  return (
    a.name === b.name &&
    JSON.stringify(a.inputGuardrails) === JSON.stringify(b.inputGuardrails) &&
    JSON.stringify(a.outputGuardrails) === JSON.stringify(b.outputGuardrails) &&
    JSON.stringify(a.allowedModels) === JSON.stringify(b.allowedModels) &&
    JSON.stringify(a.allowedMcpServers) === JSON.stringify(b.allowedMcpServers) &&
    a.mcpRequireHitl === b.mcpRequireHitl &&
    JSON.stringify(a.toolPolicy) === JSON.stringify(b.toolPolicy) &&
    JSON.stringify(a.memoryPolicy) === JSON.stringify(b.memoryPolicy)
  );
}

function policyToForm(policy: PolicyInfo): FormState {
  return {
    name: policy.name,
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
  };
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
    <div className="space-y-1.5">
      <div className="flex gap-1.5">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={placeholder}
          className="h-7 text-xs flex-1"
        />
        <Button variant="outline" size="sm" className="h-7 text-xs px-2" onClick={add}>
          <Plus className="h-3 w-3" />
        </Button>
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <Badge key={v} variant="secondary" className="text-xs gap-1 pr-1">
              {v}
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} className="hover:text-destructive ml-0.5">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ToggleField({ label, description, checked, onChange }: { label: string; description?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="flex-1 min-w-0">
        <Label className="text-xs">{label}</Label>
        {description && <p className="text-[10px] text-muted-foreground mt-0.5">{description}</p>}
      </div>
      <Button
        variant={checked ? "default" : "outline"}
        size="sm"
        className="h-6 text-[10px] w-12 shrink-0"
        onClick={() => onChange(!checked)}
      >
        {checked ? "ON" : "OFF"}
      </Button>
    </div>
  );
}

function SectionCard({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <Card className="p-3 space-y-3">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-medium">{title}</h3>
      </div>
      <Separator />
      {children}
    </Card>
  );
}

// ── Policy list sidebar item ───────────────────────────────────────────────

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
    <div className="w-64 shrink-0 border-r flex flex-col h-full">
      <div className="p-3 border-b space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold flex items-center gap-1.5">
            <ShieldAlert className="h-4 w-4 text-primary" /> Policies
          </h2>
          <Badge variant="secondary" className="text-[10px] h-5">{policies.length}</Badge>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Filter policies..."
            className="h-7 pl-7 text-xs"
          />
        </div>
        {canMutate && (
          <Button
            variant={isCreateMode ? "default" : "outline"}
            size="sm"
            className="w-full h-7 text-xs"
            onClick={onCreateNew}
          >
            <Plus className="h-3.5 w-3.5 mr-1" /> New Policy
          </Button>
        )}
      </div>
      <ScrollArea className="flex-1">
        {filtered.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            {searchQuery ? "No matching policies." : "No policies yet."}
          </div>
        ) : (
          <div className="p-1.5 space-y-0.5">
            {filtered.map((p) => (
              <button
                key={p.name}
                onClick={() => onSelect(p.name)}
                className={`w-full text-left p-2 rounded-md text-xs transition-colors ${
                  selectedName === p.name && !isCreateMode
                    ? "bg-primary/10 text-primary font-medium"
                    : "hover:bg-muted"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="truncate font-medium">{p.name}</span>
                  {p.mcp_require_hitl && (
                    <Eye className="h-3 w-3 text-amber-500 shrink-0 ml-1" />
                  )}
                </div>
                <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted-foreground">
                  {p.allowed_models.length > 0 && (
                    <span className="flex items-center gap-0.5">
                      <BrainCircuit className="h-3 w-3" /> {p.allowed_models.length}
                    </span>
                  )}
                  {p.allowed_mcp_servers.length > 0 && (
                    <span className="flex items-center gap-0.5">
                      <Globe className="h-3 w-3" /> {p.allowed_mcp_servers.length}
                    </span>
                  )}
                  {(p.tool_policy.blockedToolNames?.length ?? 0) > 0 && (
                    <span className="flex items-center gap-0.5">
                      <Wrench className="h-3 w-3" /> {(p.tool_policy.blockedToolNames ?? []).length}
                    </span>
                  )}
                </div>
              </button>
            ))}
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

  // §fix: Track whether the USER has made manual edits (not just form-vs-policy diff)
  const hasUserEdits = useRef(false);
  // Store the "last loaded policy name" to detect external sidebar switches
  const lastLoadedPolicyName = useRef<string | null>(null);
  // Pending policy to load after discard confirmation
  const pendingPolicyRef = useRef<PolicyInfo | null | undefined>(null);

  // Form state
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  // Derive isDirty for the banner — purely cosmetic
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

  // ── Mark user edit on any field change ──────────────────────────────────
  const markEdit = useCallback(() => {
    hasUserEdits.current = true;
  }, []);

  // ── Field updaters ─────────────────────────────────────────────────────
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

  // ── Effect: when selectedPolicy changes externally (sidebar click) ──────
  useEffect(() => {
    if (!selectedPolicy) {
      // No policy selected — if we were in edit mode with edits, prompt discard
      if (!isCreateMode && hasUserEdits.current) {
        setConfirmDiscardOpen(true);
      } else {
        // Just clear
        setIsCreateMode(false);
        hasUserEdits.current = false;
        lastLoadedPolicyName.current = null;
      }
      return;
    }

    // Same policy as already loaded? Skip
    if (lastLoadedPolicyName.current === selectedPolicy.name && !isCreateMode) {
      return;
    }

    // Different policy selected — check if user has edits
    if (hasUserEdits.current) {
      pendingPolicyRef.current = selectedPolicy;
      setConfirmDiscardOpen(true);
    } else {
      loadPolicy(selectedPolicy);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPolicy]);

  // ── Reset to "new policy" mode ─────────────────────────────────────────
  const resetToNew = useCallback(() => {
    if (hasUserEdits.current) {
      pendingPolicyRef.current = null;
      setConfirmDiscardOpen(true);
      return;
    }
    setIsCreateMode(true);
    setForm(EMPTY_FORM());
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
          input_guardrails: form.inputGuardrails,
          output_guardrails: form.outputGuardrails,
          allowed_models: form.allowedModels,
          allowed_mcp_servers: form.allowedMcpServers,
          mcp_require_hitl: form.mcpRequireHitl,
          tool_policy: form.toolPolicy,
          memory_policy: form.memoryPolicy,
        };
        await createPolicy(token, namespace, payload);
        toast.success(`Policy "${trimmedName}" created.`);
        setIsCreateMode(false);
        hasUserEdits.current = false;
        lastLoadedPolicyName.current = null;
      } else {
        const payload: UpdatePolicyPayload = {
          input_guardrails: form.inputGuardrails,
          output_guardrails: form.outputGuardrails,
          allowed_models: form.allowedModels,
          allowed_mcp_servers: form.allowedMcpServers,
          mcp_require_hitl: form.mcpRequireHitl,
          tool_policy: form.toolPolicy,
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

  // ── Select policy from sidebar ─────────────────────────────────────────
  const handleSelectPolicy = useCallback((name: string) => {
    ws.selectPolicy?.(name);
  }, [ws]);

  // ── Empty state: no policy selected ────────────────────────────────────
  if (!selectedPolicy && !isCreateMode) {
    return (
      <div className="flex flex-1 h-full">
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
          <ShieldAlert className="h-14 w-14 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground text-center max-w-xs">
            Select a policy from the sidebar to view or edit it, or create a new policy.
          </p>
        </div>
      </div>
    );
  }

  // ── Policy count display ───────────────────────────────────────────────
  const modelCount = form.allowedModels.length;
  const mcpCount = form.allowedMcpServers.length;
  const blockedToolCount = form.toolPolicy.blockedToolNames?.length ?? 0;
  const hasActiveGuardrails =
    form.inputGuardrails.blockPromptInjection ||
    (form.inputGuardrails.blockedPatterns?.length ?? 0) > 0 ||
    form.outputGuardrails.maskPII ||
    (form.outputGuardrails.blockedOutputPatterns?.length ?? 0) > 0 ||
    modelCount > 0 ||
    mcpCount > 0 ||
    blockedToolCount > 0;

  // ── Main render ────────────────────────────────────────────────────────
  return (
    <div className="flex flex-1 h-full">
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

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-4 max-w-2xl mx-auto">
          {/* ── Header bar ──────────────────────────────────────────────── */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <ShieldAlert className="h-5 w-5 text-primary shrink-0" />
              {isCreateMode ? (
                <h2 className="text-base font-semibold">New Policy</h2>
              ) : (
                <>
                  <h2 className="text-base font-semibold truncate">{form.name}</h2>
                  {hasActiveGuardrails && (
                    <Badge variant="default" className="text-[10px] h-5 shrink-0">
                      Active
                    </Badge>
                  )}
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              {canMutate && !isCreateMode && (
                <Button
                  variant="destructive"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => setConfirmDeleteOpen(true)}
                  disabled={deleting}
                >
                  {deleting ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Trash2 className="h-3 w-3 mr-1" />}
                  {deleting ? "Deleting..." : "Delete"}
                </Button>
              )}
              {canMutate && (
                <Button
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => void handleSave()}
                  disabled={saving || (!isCreateMode && !isDirty)}
                >
                  {saving ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Save className="h-3 w-3 mr-1" />}
                  {saving ? "Saving..." : "Save"}
                </Button>
              )}
            </div>
          </div>

          {/* ── Status info bar ─────────────────────────────────────────── */}
          {!isCreateMode && (
            <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
              {modelCount > 0 && (
                <span className="flex items-center gap-1">
                  <BrainCircuit className="h-3.5 w-3.5" /> {modelCount} model{modelCount !== 1 ? "s" : ""} allowed
                </span>
              )}
              {mcpCount > 0 && (
                <span className="flex items-center gap-1">
                  <Globe className="h-3.5 w-3.5" /> {mcpCount} MCP server{mcpCount !== 1 ? "s" : ""} allowed
                </span>
              )}
              {blockedToolCount > 0 && (
                <span className="flex items-center gap-1">
                  <Wrench className="h-3.5 w-3.5" /> {blockedToolCount} tool{blockedToolCount !== 1 ? "s" : ""} blocked
                </span>
              )}
              {form.mcpRequireHitl && (
                <span className="flex items-center gap-1 text-amber-500">
                  <Eye className="h-3.5 w-3.5" /> HITL required for MCP
                </span>
              )}
            </div>
          )}

          {/* ── Name field (create mode only) ───────────────────────────── */}
          {isCreateMode && (
            <Card className="p-3 space-y-2">
              <Label className="text-xs font-medium">Policy Name</Label>
              <Input
                value={form.name}
                onChange={(e) => updateForm({ name: e.target.value })}
                placeholder="my-security-policy"
                className="h-8 text-sm font-mono"
                autoFocus
              />
              <p className="text-[10px] text-muted-foreground">
                Lowercase letters, numbers, and hyphens. Must be unique.
              </p>
            </Card>
          )}

          {/* ── Tabs for sections ───────────────────────────────────────── */}
          <Tabs defaultValue="guardrails" className="w-full">
            <TabsList className="w-full h-8">
              <TabsTrigger value="guardrails" className="text-xs h-7 flex-1">
                <AlertTriangle className="h-3.5 w-3.5 mr-1" /> Guardrails
              </TabsTrigger>
              <TabsTrigger value="access" className="text-xs h-7 flex-1">
                <Gavel className="h-3.5 w-3.5 mr-1" /> Access
              </TabsTrigger>
              <TabsTrigger value="tools" className="text-xs h-7 flex-1">
                <Wrench className="h-3.5 w-3.5 mr-1" /> Tools
              </TabsTrigger>
              <TabsTrigger value="memory" className="text-xs h-7 flex-1">
                <BrainCircuit className="h-3.5 w-3.5 mr-1" /> Memory
              </TabsTrigger>
            </TabsList>

            {/* ── Tab: Guardrails ──────────────────────────────────────── */}
            <TabsContent value="guardrails" className="mt-3 space-y-3">
              <SectionCard icon={AlertTriangle} title="Input Guardrails">
                <ToggleField
                  label="Block Prompt Injection"
                  description="Enable prompt-injection detection and blocking for all requests."
                  checked={form.inputGuardrails.blockPromptInjection}
                  onChange={(v) => updateInput({ blockPromptInjection: v })}
                />
                <div className="space-y-1">
                  <Label className="text-xs">Max Input Tokens</Label>
                  <Input
                    type="number"
                    value={form.inputGuardrails.maxInputTokens}
                    onChange={(e) => updateInput({ maxInputTokens: Math.max(0, Number(e.target.value) || 0) })}
                    className="h-7 text-xs w-32"
                    min={0}
                  />
                  <p className="text-[10px] text-muted-foreground">0 = no limit.</p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Blocked Input Patterns</Label>
                  <TagListEditor
                    values={form.inputGuardrails.blockedPatterns}
                    onChange={(v) => updateInput({ blockedPatterns: v })}
                    placeholder="Add regex pattern..."
                  />
                </div>
              </SectionCard>

              <SectionCard icon={AlertTriangle} title="Output Guardrails">
                <ToggleField
                  label="Mask PII"
                  description="Automatically redact names, emails, credit cards, and other PII from model responses."
                  checked={form.outputGuardrails.maskPII}
                  onChange={(v) => updateOutput({ maskPII: v })}
                />
                <div className="space-y-1">
                  <Label className="text-xs">Max Output Tokens</Label>
                  <Input
                    type="number"
                    value={form.outputGuardrails.maxOutputTokens}
                    onChange={(e) => updateOutput({ maxOutputTokens: Math.max(0, Number(e.target.value) || 0) })}
                    className="h-7 text-xs w-32"
                    min={0}
                  />
                  <p className="text-[10px] text-muted-foreground">0 = no limit.</p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Blocked Output Patterns</Label>
                  <TagListEditor
                    values={form.outputGuardrails.blockedOutputPatterns}
                    onChange={(v) => updateOutput({ blockedOutputPatterns: v })}
                    placeholder="Add regex pattern..."
                  />
                </div>
              </SectionCard>
            </TabsContent>

            {/* ── Tab: Access ──────────────────────────────────────────── */}
            <TabsContent value="access" className="mt-3 space-y-3">
              <SectionCard icon={BrainCircuit} title="Model Access">
                <div className="space-y-1">
                  <Label className="text-xs">Allowed Models</Label>
                  <TagListEditor
                    values={form.allowedModels}
                    onChange={(v) => updateForm({ allowedModels: v })}
                    placeholder="e.g. gpt-4o, claude-sonnet-4"
                  />
                  <p className="text-[10px] text-muted-foreground">
                    {modelCount === 0 ? "Empty = all models allowed." : `${modelCount} model${modelCount !== 1 ? "s" : ""} allowlisted.`}
                  </p>
                </div>
              </SectionCard>

              <SectionCard icon={Globe} title="MCP Server Access">
                <div className="space-y-1">
                  <Label className="text-xs">Allowed MCP Servers</Label>
                  <TagListEditor
                    values={form.allowedMcpServers}
                    onChange={(v) => updateForm({ allowedMcpServers: v })}
                    placeholder="e.g. code-exec, web-search"
                  />
                  <p className="text-[10px] text-muted-foreground">
                    {mcpCount === 0 ? "Empty = all MCP servers allowed." : `${mcpCount} server${mcpCount !== 1 ? "s" : ""} allowlisted.`}
                  </p>
                </div>
                <ToggleField
                  label="Require Human-in-the-Loop for MCP"
                  description="All tool calls routed through MCP servers will pause for human approval."
                  checked={form.mcpRequireHitl}
                  onChange={(v) => updateForm({ mcpRequireHitl: v })}
                />
              </SectionCard>
            </TabsContent>

            {/* ── Tab: Tools ────────────────────────────────────────────── */}
            <TabsContent value="tools" className="mt-3 space-y-3">
              <SectionCard icon={Wrench} title="Tool Governance">
                <div className="space-y-1">
                  <Label className="text-xs">Max Delegation Depth</Label>
                  <Input
                    type="number"
                    value={typeof form.toolPolicy.maxDelegationDepth === "number" ? form.toolPolicy.maxDelegationDepth : ""}
                    onChange={(e) => updateTool({
                      maxDelegationDepth: e.target.value.trim() === "" ? undefined : Math.max(0, Number(e.target.value) || 0),
                    })}
                    className="h-7 text-xs w-32"
                    min={0}
                    placeholder="unlimited"
                  />
                  <p className="text-[10px] text-muted-foreground">Max tool sub-delegation chain length.</p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Allowed Tool Prefixes</Label>
                  <TagListEditor
                    values={form.toolPolicy.allowedToolPrefixes}
                    onChange={(v) => updateTool({ allowedToolPrefixes: v })}
                    placeholder="e.g. local.command., github/"
                  />
                  <p className="text-[10px] text-muted-foreground">Empty = all tool prefixes allowed.</p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Blocked Tool Names</Label>
                  <TagListEditor
                    values={form.toolPolicy.blockedToolNames}
                    onChange={(v) => updateTool({ blockedToolNames: v })}
                    placeholder="e.g. local.command.rm"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Require Approval For</Label>
                  <TagListEditor
                    values={form.toolPolicy.requireApprovalFor}
                    onChange={(v) => updateTool({ requireApprovalFor: v })}
                    placeholder="e.g. github/create_issue"
                  />
                  <p className="text-[10px] text-muted-foreground">These tools will always require human approval.</p>
                </div>
              </SectionCard>
            </TabsContent>

            {/* ── Tab: Memory ───────────────────────────────────────────── */}
            <TabsContent value="memory" className="mt-3 space-y-3">
              <SectionCard icon={BrainCircuit} title="Memory Governance">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Max Injected Memories</Label>
                    <Input
                      type="number"
                      value={typeof form.memoryPolicy.maxInjectedMemories === "number" ? form.memoryPolicy.maxInjectedMemories : ""}
                      onChange={(e) => updateMemory({
                        maxInjectedMemories: e.target.value.trim() === "" ? undefined : Math.max(0, Number(e.target.value) || 0),
                      })}
                      className="h-7 text-xs"
                      min={0}
                      placeholder="unlimited"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Max Injected Chars</Label>
                    <Input
                      type="number"
                      value={typeof form.memoryPolicy.maxInjectedChars === "number" ? form.memoryPolicy.maxInjectedChars : ""}
                      onChange={(e) => updateMemory({
                        maxInjectedChars: e.target.value.trim() === "" ? undefined : Math.max(0, Number(e.target.value) || 0),
                      })}
                      className="h-7 text-xs"
                      min={0}
                      placeholder="unlimited"
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Allowed Memory Types</Label>
                  <TagListEditor
                    values={form.memoryPolicy.allowedMemoryTypes}
                    onChange={(v) => updateMemory({ allowedMemoryTypes: v })}
                    placeholder="e.g. procedural, episodic"
                  />
                  <p className="text-[10px] text-muted-foreground">Empty = all memory types allowed.</p>
                </div>
                <ToggleField
                  label="Auto-promote high-signal memory"
                  description="Automatically promote memory records that match high-signal criteria."
                  checked={form.memoryPolicy.autoPromote}
                  onChange={(v) => updateMemory({ autoPromote: v })}
                />
              </SectionCard>
            </TabsContent>
          </Tabs>

          {/* ── Dirty state banner ──────────────────────────────────────── */}
          {isDirty && (
            <div className="flex items-center gap-2 p-2 rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
              <Info className="h-4 w-4 text-amber-500 shrink-0" />
              <p className="text-xs text-amber-700 dark:text-amber-300">
                You have unsaved changes. Press <kbd className="px-1 py-0.5 bg-amber-100 dark:bg-amber-900 rounded text-[10px]">Ctrl+S</kbd> to save.
              </p>
            </div>
          )}
        </div>
      </ScrollArea>

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
            // "New Policy" was clicked
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
