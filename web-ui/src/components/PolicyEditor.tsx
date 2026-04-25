import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Plus, Save, Trash2, ShieldAlert, X, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { ConfirmDialog } from "./ConfirmDialog";
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

const DEFAULT_TOOL_POLICY: PolicyToolPolicy = {
  allowedToolPrefixes: [],
  blockedToolNames: [],
  requireApprovalFor: [],
};

const DEFAULT_MEMORY_POLICY: PolicyMemoryPolicy = {
  allowedMemoryTypes: [],
  autoPromote: false,
};

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
              <button type="button" onClick={() => onChange(values.filter((x) => x !== v))} className="hover:text-destructive">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ToggleField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <Label className="text-xs">{label}</Label>
      <Button
        variant={checked ? "default" : "outline"}
        size="sm"
        className="h-6 text-[10px] w-12"
        onClick={() => onChange(!checked)}
      >
        {checked ? "ON" : "OFF"}
      </Button>
    </div>
  );
}

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
  const pendingPolicyRef = useRef<PolicyInfo | null | undefined>(undefined);

  // Form state
  const [name, setName] = useState("");
  const [inputGuardrails, setInputGuardrails] = useState<PolicyInputGuardrails>({ ...DEFAULT_INPUT });
  const [outputGuardrails, setOutputGuardrails] = useState<PolicyOutputGuardrails>({ ...DEFAULT_OUTPUT });
  const [allowedModels, setAllowedModels] = useState<string[]>([]);
  const [allowedMcpServers, setAllowedMcpServers] = useState<string[]>([]);
  const [mcpRequireHitl, setMcpRequireHitl] = useState(true);
  const [toolPolicy, setToolPolicy] = useState<PolicyToolPolicy>({ ...DEFAULT_TOOL_POLICY });
  const [memoryPolicy, setMemoryPolicy] = useState<PolicyMemoryPolicy>({ ...DEFAULT_MEMORY_POLICY });

  // Dirty-state tracking: compare current form to the loaded policy
  const isDirty = useMemo(() => {
    if (isCreateMode) {
      return name.trim() !== "" ||
        inputGuardrails.blockPromptInjection !== DEFAULT_INPUT.blockPromptInjection ||
        inputGuardrails.maxInputTokens !== DEFAULT_INPUT.maxInputTokens ||
        inputGuardrails.blockedPatterns.length > 0 ||
        outputGuardrails.maskPII !== DEFAULT_OUTPUT.maskPII ||
        outputGuardrails.maxOutputTokens !== DEFAULT_OUTPUT.maxOutputTokens ||
        outputGuardrails.blockedOutputPatterns.length > 0 ||
        allowedModels.length > 0 || allowedMcpServers.length > 0 || !mcpRequireHitl ||
        toolPolicy.allowedToolPrefixes.length > 0 || toolPolicy.blockedToolNames.length > 0 ||
        toolPolicy.requireApprovalFor.length > 0 || typeof toolPolicy.maxDelegationDepth === "number" ||
        memoryPolicy.allowedMemoryTypes.length > 0 || typeof memoryPolicy.maxInjectedMemories === "number" ||
        typeof memoryPolicy.maxInjectedChars === "number" || memoryPolicy.autoPromote;
    }
    if (!selectedPolicy) return false;
    return (
      JSON.stringify(inputGuardrails) !== JSON.stringify(selectedPolicy.input_guardrails) ||
      JSON.stringify(outputGuardrails) !== JSON.stringify(selectedPolicy.output_guardrails) ||
      JSON.stringify(allowedModels) !== JSON.stringify(selectedPolicy.allowed_models) ||
      JSON.stringify(allowedMcpServers) !== JSON.stringify(selectedPolicy.allowed_mcp_servers) ||
      mcpRequireHitl !== selectedPolicy.mcp_require_hitl ||
      JSON.stringify(toolPolicy) !== JSON.stringify(selectedPolicy.tool_policy) ||
      JSON.stringify(memoryPolicy) !== JSON.stringify(selectedPolicy.memory_policy)
    );
  }, [isCreateMode, name, inputGuardrails, outputGuardrails, allowedModels, allowedMcpServers, mcpRequireHitl, toolPolicy, memoryPolicy, selectedPolicy]);

  // Load form from selected policy — with dirty-state guard
  function loadPolicy(policy: PolicyInfo) {
    setIsCreateMode(false);
    setName(policy.name);
    setInputGuardrails({ ...policy.input_guardrails });
    setOutputGuardrails({ ...policy.output_guardrails });
    setAllowedModels([...policy.allowed_models]);
    setAllowedMcpServers([...policy.allowed_mcp_servers]);
    setMcpRequireHitl(policy.mcp_require_hitl);
    setToolPolicy({
      maxDelegationDepth: policy.tool_policy.maxDelegationDepth,
      allowedToolPrefixes: [...policy.tool_policy.allowedToolPrefixes],
      blockedToolNames: [...policy.tool_policy.blockedToolNames],
      requireApprovalFor: [...policy.tool_policy.requireApprovalFor],
    });
    setMemoryPolicy({
      maxInjectedMemories: policy.memory_policy.maxInjectedMemories,
      maxInjectedChars: policy.memory_policy.maxInjectedChars,
      allowedMemoryTypes: [...policy.memory_policy.allowedMemoryTypes],
      autoPromote: policy.memory_policy.autoPromote,
    });
  }

  // Populate form from selected policy
  useEffect(() => {
    if (selectedPolicy) {
      if (isDirty) {
        pendingPolicyRef.current = selectedPolicy;
        setConfirmDiscardOpen(true);
      } else {
        loadPolicy(selectedPolicy);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPolicy]);

  const resetToNew = useCallback(() => {
    setIsCreateMode(true);
    setName("");
    setInputGuardrails({ ...DEFAULT_INPUT });
    setOutputGuardrails({ ...DEFAULT_OUTPUT });
    setAllowedModels([]);
    setAllowedMcpServers([]);
    setMcpRequireHitl(true);
    setToolPolicy({ ...DEFAULT_TOOL_POLICY });
    setMemoryPolicy({ ...DEFAULT_MEMORY_POLICY });
  }, []);

  const handleSave = useCallback(async () => {
    if (!token || !namespace) return;
    setSaving(true);
    try {
      if (isCreateMode) {
        if (!name.trim()) {
          toast.error("Policy name is required");
          return;
        }
        const payload: CreatePolicyPayload = {
          name: name.trim(),
          input_guardrails: inputGuardrails,
          output_guardrails: outputGuardrails,
          allowed_models: allowedModels,
          allowed_mcp_servers: allowedMcpServers,
          mcp_require_hitl: mcpRequireHitl,
          tool_policy: toolPolicy,
          memory_policy: memoryPolicy,
        };
        await createPolicy(token, namespace, payload);
        toast.success(`Policy "${name}" created`);
        setIsCreateMode(false);
      } else {
        const payload: UpdatePolicyPayload = {
          input_guardrails: inputGuardrails,
          output_guardrails: outputGuardrails,
          allowed_models: allowedModels,
          allowed_mcp_servers: allowedMcpServers,
          mcp_require_hitl: mcpRequireHitl,
          tool_policy: toolPolicy,
          memory_policy: memoryPolicy,
        };
        await updatePolicy(token, namespace, name, payload);
        toast.success(`Policy "${name}" updated`);
      }
      void ws.refreshWorkspaceData({ silent: false });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  }, [token, namespace, isCreateMode, name, inputGuardrails, outputGuardrails, allowedModels, allowedMcpServers, mcpRequireHitl, toolPolicy, memoryPolicy, ws]);

  const handleDelete = useCallback(async () => {
    if (!token || !namespace || !selectedPolicyName) return;
    setDeleting(true);
    try {
      await deletePolicy(token, namespace, selectedPolicyName);
      toast.success(`Policy "${selectedPolicyName}" deleted`);
      void ws.refreshWorkspaceData({ silent: false });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete policy");
    } finally {
      setDeleting(false);
    }
  }, [token, namespace, selectedPolicyName, ws]);

  if (!selectedPolicy && !isCreateMode) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6">
        <ShieldAlert className="h-12 w-12 text-muted-foreground/40" />
        <p className="text-sm text-muted-foreground">Select a policy from the sidebar or create a new one.</p>
        {canMutate && (
          <Button size="sm" onClick={resetToNew}>
            <Plus className="h-4 w-4 mr-1" /> New Policy
          </Button>
        )}
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1">
      <div className="p-3 space-y-3 max-w-2xl">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-primary" />
            <h2 className="text-base font-semibold">{isCreateMode ? "New Policy" : name}</h2>
          </div>
          <div className="flex items-center gap-2">
            {canMutate && !isCreateMode && (
              <Button variant="destructive" size="sm" className="h-7 text-xs" onClick={() => setConfirmDeleteOpen(true)} disabled={deleting}>
                <Trash2 className="h-3 w-3 mr-1" /> {deleting ? "Deleting..." : "Delete"}
              </Button>
            )}
            {canMutate && (
              <Button size="sm" className="h-7 text-xs" onClick={() => void handleSave()} disabled={saving}>
                <Save className="h-3 w-3 mr-1" /> {saving ? "Saving..." : "Save"}
              </Button>
            )}
          </div>
        </div>

        {/* Name (only in create mode) */}
        {isCreateMode && (
          <div className="space-y-1">
            <Label className="text-xs font-medium">Policy Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-policy"
              className="h-8 text-sm"
            />
            <p className="text-[10px] text-muted-foreground">Lowercase letters, numbers, and hyphens only.</p>
          </div>
        )}

        {/* Input Guardrails */}
        <Card className="p-3 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-medium">Input Guardrails</h3>
          </div>
          <Separator />
          <ToggleField
            label="Block Prompt Injection"
            checked={inputGuardrails.blockPromptInjection}
            onChange={(v) => setInputGuardrails((prev) => ({ ...prev, blockPromptInjection: v }))}
          />
          <div className="space-y-1">
            <Label className="text-xs">Max Input Tokens</Label>
            <Input
              type="number"
              value={inputGuardrails.maxInputTokens}
              onChange={(e) => setInputGuardrails((prev) => ({ ...prev, maxInputTokens: Number(e.target.value) || 0 }))}
              className="h-7 text-xs w-32"
              min={0}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Blocked Input Patterns</Label>
            <TagListEditor
              values={inputGuardrails.blockedPatterns}
              onChange={(v) => setInputGuardrails((prev) => ({ ...prev, blockedPatterns: v }))}
              placeholder="Add regex pattern..."
            />
          </div>
        </Card>

        {/* Output Guardrails */}
        <Card className="p-3 space-y-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <h3 className="text-sm font-medium">Output Guardrails</h3>
          </div>
          <Separator />
          <ToggleField
            label="Mask PII"
            checked={outputGuardrails.maskPII}
            onChange={(v) => setOutputGuardrails((prev) => ({ ...prev, maskPII: v }))}
          />
          <div className="space-y-1">
            <Label className="text-xs">Max Output Tokens</Label>
            <Input
              type="number"
              value={outputGuardrails.maxOutputTokens}
              onChange={(e) => setOutputGuardrails((prev) => ({ ...prev, maxOutputTokens: Number(e.target.value) || 0 }))}
              className="h-7 text-xs w-32"
              min={0}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Blocked Output Patterns</Label>
            <TagListEditor
              values={outputGuardrails.blockedOutputPatterns}
              onChange={(v) => setOutputGuardrails((prev) => ({ ...prev, blockedOutputPatterns: v }))}
              placeholder="Add regex pattern..."
            />
          </div>
        </Card>

        {/* Model & MCP Access Control */}
        <Card className="p-3 space-y-3">
          <h3 className="text-sm font-medium">Access Control</h3>
          <Separator />
          <div className="space-y-1">
            <Label className="text-xs">Allowed Models</Label>
            <TagListEditor
              values={allowedModels}
              onChange={setAllowedModels}
              placeholder="e.g. gpt-4o, claude-sonnet-4-20250514"
            />
            <p className="text-[10px] text-muted-foreground">Leave empty to allow all models.</p>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Allowed MCP Servers</Label>
            <TagListEditor
              values={allowedMcpServers}
              onChange={setAllowedMcpServers}
              placeholder="e.g. code-exec, web-search"
            />
            <p className="text-[10px] text-muted-foreground">Leave empty to allow all MCP servers.</p>
          </div>
          <ToggleField
            label="Require Human-in-the-Loop for MCP"
            checked={mcpRequireHitl}
            onChange={setMcpRequireHitl}
          />
        </Card>

        <Card className="p-3 space-y-3">
          <h3 className="text-sm font-medium">Tool Governance</h3>
          <Separator />
          <div className="space-y-1">
            <Label className="text-xs">Max Delegation Depth</Label>
            <Input
              type="number"
              value={typeof toolPolicy.maxDelegationDepth === "number" ? toolPolicy.maxDelegationDepth : ""}
              onChange={(e) => setToolPolicy((prev) => ({
                ...prev,
                maxDelegationDepth: e.target.value.trim() === "" ? undefined : Number(e.target.value),
              }))}
              className="h-7 text-xs w-32"
              min={0}
              placeholder="unset"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Allowed Tool Prefixes</Label>
            <TagListEditor
              values={toolPolicy.allowedToolPrefixes}
              onChange={(v) => setToolPolicy((prev) => ({ ...prev, allowedToolPrefixes: v }))}
              placeholder="e.g. local.command., github/, filesystem."
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Blocked Tool Names</Label>
            <TagListEditor
              values={toolPolicy.blockedToolNames}
              onChange={(v) => setToolPolicy((prev) => ({ ...prev, blockedToolNames: v }))}
              placeholder="e.g. local.command.rm, github/delete_repo"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Require Approval For</Label>
            <TagListEditor
              values={toolPolicy.requireApprovalFor}
              onChange={(v) => setToolPolicy((prev) => ({ ...prev, requireApprovalFor: v }))}
              placeholder="e.g. github/create_issue"
            />
          </div>
        </Card>

        <Card className="p-3 space-y-3">
          <h3 className="text-sm font-medium">Memory Governance</h3>
          <Separator />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label className="text-xs">Max Injected Memories</Label>
              <Input
                type="number"
                value={typeof memoryPolicy.maxInjectedMemories === "number" ? memoryPolicy.maxInjectedMemories : ""}
                onChange={(e) => setMemoryPolicy((prev) => ({
                  ...prev,
                  maxInjectedMemories: e.target.value.trim() === "" ? undefined : Number(e.target.value),
                }))}
                className="h-7 text-xs w-32"
                min={0}
                placeholder="unset"
              />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Max Injected Chars</Label>
              <Input
                type="number"
                value={typeof memoryPolicy.maxInjectedChars === "number" ? memoryPolicy.maxInjectedChars : ""}
                onChange={(e) => setMemoryPolicy((prev) => ({
                  ...prev,
                  maxInjectedChars: e.target.value.trim() === "" ? undefined : Number(e.target.value),
                }))}
                className="h-7 text-xs w-32"
                min={0}
                placeholder="unset"
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Allowed Memory Types</Label>
            <TagListEditor
              values={memoryPolicy.allowedMemoryTypes}
              onChange={(v) => setMemoryPolicy((prev) => ({ ...prev, allowedMemoryTypes: v }))}
              placeholder="e.g. procedural, episodic, response-summary"
            />
          </div>
          <ToggleField
            label="Auto-promote high-signal memory"
            checked={memoryPolicy.autoPromote}
            onChange={(v) => setMemoryPolicy((prev) => ({ ...prev, autoPromote: v }))}
          />
        </Card>

        {isDirty && (
          <p className="text-xs text-amber-500">You have unsaved changes.</p>
        )}
      </div>

      <ConfirmDialog
        open={confirmDiscardOpen}
        onOpenChange={(open) => {
          if (!open) {
            pendingPolicyRef.current = undefined;
            setConfirmDiscardOpen(false);
          }
        }}
        title="Discard unsaved changes?"
        description={`You have unsaved changes to "${name}". Switching to another policy will discard them.`}
        confirmLabel="Discard"
        variant="destructive"
        onConfirm={() => {
          const pending = pendingPolicyRef.current;
          pendingPolicyRef.current = undefined;
          if (pending) loadPolicy(pending);
        }}
      />
      <ConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
        title={`Delete policy "${name}"?`}
        description="This will permanently remove this policy. Agents referencing it will lose their policy assignment."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => void handleDelete()}
      />
    </ScrollArea>
  );
}
