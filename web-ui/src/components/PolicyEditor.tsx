import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Plus, Save, Trash2, ShieldAlert, X, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { useConnection } from "@/contexts/ConnectionContext";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  createPolicy,
  updatePolicy,
  deletePolicy,
  type CreatePolicyPayload,
  type UpdatePolicyPayload,
} from "@/lib/api";
import type { PolicyInfo, PolicyInputGuardrails, PolicyOutputGuardrails } from "@/types";

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

  // Form state
  const [name, setName] = useState("");
  const [inputGuardrails, setInputGuardrails] = useState<PolicyInputGuardrails>({ ...DEFAULT_INPUT });
  const [outputGuardrails, setOutputGuardrails] = useState<PolicyOutputGuardrails>({ ...DEFAULT_OUTPUT });
  const [allowedModels, setAllowedModels] = useState<string[]>([]);
  const [allowedMcpServers, setAllowedMcpServers] = useState<string[]>([]);
  const [mcpRequireHitl, setMcpRequireHitl] = useState(true);

  // Populate form from selected policy
  useEffect(() => {
    if (selectedPolicy) {
      setIsCreateMode(false);
      setName(selectedPolicy.name);
      setInputGuardrails({ ...selectedPolicy.input_guardrails });
      setOutputGuardrails({ ...selectedPolicy.output_guardrails });
      setAllowedModels([...selectedPolicy.allowed_models]);
      setAllowedMcpServers([...selectedPolicy.allowed_mcp_servers]);
      setMcpRequireHitl(selectedPolicy.mcp_require_hitl);
    }
  }, [selectedPolicy]);

  const resetToNew = useCallback(() => {
    setIsCreateMode(true);
    setName("");
    setInputGuardrails({ ...DEFAULT_INPUT });
    setOutputGuardrails({ ...DEFAULT_OUTPUT });
    setAllowedModels([]);
    setAllowedMcpServers([]);
    setMcpRequireHitl(true);
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
  }, [token, namespace, isCreateMode, name, inputGuardrails, outputGuardrails, allowedModels, allowedMcpServers, mcpRequireHitl, ws]);

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
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
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
      <div className="p-4 space-y-4 max-w-2xl">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-primary" />
            <h2 className="text-base font-semibold">{isCreateMode ? "New Policy" : name}</h2>
          </div>
          <div className="flex items-center gap-2">
            {canMutate && !isCreateMode && (
              <Button variant="destructive" size="sm" className="h-7 text-xs" onClick={() => void handleDelete()} disabled={deleting}>
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
      </div>
    </ScrollArea>
  );
}
