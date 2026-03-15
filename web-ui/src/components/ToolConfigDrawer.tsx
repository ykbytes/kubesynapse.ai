import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle, LoaderCircle, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  createGitCredentials,
  createGitHubCredentials,
  deleteGitCredentials,
  deleteGitHubCredentials,
  getGitCredentials,
  getGitHubCredentials,
} from "../lib/api";
import type {
  AgentDetail,
  ConfigField,
  GitAuthMethod,
  GitCredentialInfo,
  GitHubCredentialInfo,
  McpHubServer,
  McpToolCategory,
} from "../types";

type ToolDef = McpToolCategory | McpHubServer;

interface ToolConfigDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tool: ToolDef | null;
  agent: AgentDetail;
  token: string;
  namespace: string;
  /** Called after credentials are saved so the parent can refresh agent detail. */
  onConfigSaved: (specUpdates?: {
    git_config?: AgentDetail["git_config"];
    github_config?: AgentDetail["github_config"];
  }) => void;
}

function isFieldVisible(field: ConfigField, values: Record<string, string>): boolean {
  if (!field.visible_when) return true;
  const current = values[field.visible_when.field];
  return field.visible_when.values.includes(current ?? "");
}

const GROUP_LABELS: Record<string, string> = {
  repository: "Repository Settings",
  credentials: "Authentication",
  general: "Settings",
};

export function ToolConfigDrawer({
  open,
  onOpenChange,
  tool,
  agent,
  token,
  namespace,
  onConfigSaved,
}: ToolConfigDrawerProps) {
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [credentialStatus, setCredentialStatus] = useState<{
    exists: boolean;
    loading: boolean;
    error?: string;
  }>({ exists: false, loading: false });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const schema = tool?.config_schema ?? [];
  const credentialType = tool?.credential_type ?? null;

  // Initialize form values when drawer opens
  useEffect(() => {
    if (!open || !tool) return;
    const initial: Record<string, string> = {};

    // Set defaults from schema
    for (const field of schema) {
      if (field.default !== undefined) {
        initial[field.key] = String(field.default);
      }
    }

    // Populate from existing agent spec for git tool
    if (credentialType === "git" && agent.git_config) {
      const gc = agent.git_config;
      if (gc.repo_url) initial.repo_url = gc.repo_url;
      if (gc.default_branch) initial.default_branch = gc.default_branch;
      if (gc.auth_method) initial.auth_method = gc.auth_method;
      if (gc.push_policy) initial.push_policy = gc.push_policy;
    }

    setFormValues(initial);
    setError("");
    setSuccessMessage("");
  }, [open, tool, agent, schema, credentialType]);

  // Fetch credential status when drawer opens
  useEffect(() => {
    if (!open || !tool || !credentialType) {
      setCredentialStatus({ exists: false, loading: false });
      return;
    }
    let cancelled = false;
    setCredentialStatus({ exists: false, loading: true });

    (async () => {
      try {
        if (credentialType === "git") {
          const info: GitCredentialInfo = await getGitCredentials(token, agent.name, namespace);
          if (!cancelled) setCredentialStatus({ exists: info.exists, loading: false });
        } else if (credentialType === "github") {
          const info: GitHubCredentialInfo = await getGitHubCredentials(token, agent.name, namespace);
          if (!cancelled) setCredentialStatus({ exists: info.exists, loading: false });
        } else {
          if (!cancelled) setCredentialStatus({ exists: false, loading: false });
        }
      } catch {
        if (!cancelled) setCredentialStatus({ exists: false, loading: false, error: "Failed to check credentials" });
      }
    })();

    return () => { cancelled = true; };
  }, [open, tool, credentialType, token, agent.name, namespace]);

  const handleFieldChange = useCallback((key: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [key]: value }));
    setError("");
    setSuccessMessage("");
  }, []);

  const handleSave = async () => {
    if (!tool) return;
    setSaving(true);
    setError("");
    setSuccessMessage("");

    try {
      // Validate required fields
      for (const field of schema) {
        if (field.required && isFieldVisible(field, formValues) && !formValues[field.key]?.trim()) {
          throw new Error(`${field.label} is required`);
        }
      }

      // Save credentials based on credential_type
      if (credentialType === "git") {
        const authMethod = (formValues.auth_method || "token") as GitAuthMethod;
        const hasCredentialData =
          (authMethod === "token" && formValues.token?.trim()) ||
          (authMethod === "basic" && formValues.username?.trim()) ||
          (authMethod === "ssh" && formValues.ssh_private_key?.trim());

        if (hasCredentialData) {
          await createGitCredentials(token, agent.name, {
            auth_method: authMethod,
            token: authMethod === "token" ? formValues.token : undefined,
            username: authMethod === "basic" ? formValues.username : undefined,
            password: authMethod === "basic" ? formValues.password : undefined,
            ssh_private_key: authMethod === "ssh" ? formValues.ssh_private_key : undefined,
          }, namespace);
        }

        // Build spec updates for git_config
        const repoUrl = formValues.repo_url?.trim();
        if (repoUrl) {
          onConfigSaved({
            git_config: {
              repo_url: repoUrl,
              default_branch: formValues.default_branch?.trim() || undefined,
              push_policy: (formValues.push_policy as AgentDetail["git_config"] extends { push_policy?: infer P } ? P : never) || undefined,
              auth_method: (formValues.auth_method as GitAuthMethod) || "token",
              credential_secret_ref: `${agent.name}-git-credentials`,
            },
          });
        } else {
          onConfigSaved();
        }
      } else if (credentialType === "github") {
        if (formValues.token?.trim()) {
          await createGitHubCredentials(token, agent.name, {
            token: formValues.token,
          }, namespace);
        }
        onConfigSaved({
          github_config: {
            credential_secret_ref: `${agent.name}-github-credentials`,
          },
        });
      } else {
        onConfigSaved();
      }

      setCredentialStatus((prev) => ({ ...prev, exists: true }));
      setSuccessMessage("Configuration saved successfully");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCredentials = async () => {
    if (!tool || !credentialType) return;
    setSaving(true);
    setError("");

    try {
      if (credentialType === "git") {
        await deleteGitCredentials(token, agent.name, namespace);
      } else if (credentialType === "github") {
        await deleteGitHubCredentials(token, agent.name, namespace);
      }
      setCredentialStatus({ exists: false, loading: false });
      setSuccessMessage("Credentials deleted");
      // Clear credential fields
      setFormValues((prev) => {
        const next = { ...prev };
        for (const field of schema) {
          if (field.is_credential) delete next[field.key];
        }
        return next;
      });
      onConfigSaved();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    } finally {
      setSaving(false);
    }
  };

  // Group fields by group key
  const groups = new Map<string, ConfigField[]>();
  for (const field of schema) {
    const group = field.group ?? "general";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push(field);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
              <span className="text-sm font-bold">{tool?.name?.charAt(0) ?? "?"}</span>
            </div>
            <div>
              <SheetTitle>{tool?.name ?? "Tool"} Configuration</SheetTitle>
              <SheetDescription>{tool?.description}</SheetDescription>
            </div>
          </div>
          {credentialType && (
            <div className="mt-3 flex items-center gap-2 rounded-lg border border-border/60 bg-background/60 px-3 py-2">
              {credentialStatus.loading ? (
                <LoaderCircle className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : credentialStatus.exists ? (
                <CheckCircle className="h-4 w-4 text-emerald-400" />
              ) : (
                <AlertCircle className="h-4 w-4 text-amber-400" />
              )}
              <span className="text-xs text-muted-foreground">
                {credentialStatus.loading
                  ? "Checking credentials..."
                  : credentialStatus.exists
                    ? "Credentials configured"
                    : "No credentials configured"}
              </span>
              {credentialStatus.exists && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto h-6 px-2 text-xs text-destructive hover:text-destructive"
                  onClick={handleDeleteCredentials}
                  disabled={saving}
                >
                  <Trash2 className="mr-1 h-3 w-3" />
                  Remove
                </Button>
              )}
            </div>
          )}
        </SheetHeader>

        <ScrollArea className="-mx-6 flex-1 px-6">
          {schema.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border/60 bg-background/60">
                <CheckCircle className="h-5 w-5 text-emerald-400" />
              </div>
              <p className="mt-3 text-sm font-medium text-foreground">No configuration required</p>
              <p className="mt-1 text-xs text-muted-foreground">
                This toolkit works out of the box with no additional setup.
              </p>
            </div>
          ) : (
            <div className="space-y-6 pb-6">
              {[...groups.entries()].map(([groupKey, fields]) => {
                const visibleFields = fields.filter((f) => isFieldVisible(f, formValues));
                if (visibleFields.length === 0) return null;
                return (
                  <div key={groupKey} className="space-y-3">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {GROUP_LABELS[groupKey] ?? groupKey}
                      </p>
                      <Separator className="flex-1" />
                    </div>
                    {visibleFields.map((field) => (
                      <div key={field.key} className="space-y-1.5">
                        <Label className="text-xs">
                          {field.label}
                          {field.required && <span className="ml-0.5 text-destructive">*</span>}
                        </Label>
                        <FieldRenderer
                          field={field}
                          value={formValues[field.key] ?? ""}
                          onChange={(v) => handleFieldChange(field.key, v)}
                        />
                        {field.help && (
                          <p className="text-[11px] text-muted-foreground">{field.help}</p>
                        )}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </ScrollArea>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {error}
          </div>
        )}
        {successMessage && (
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
            {successMessage}
          </div>
        )}

        {schema.length > 0 && (
          <SheetFooter className="mt-auto border-t border-border/40 pt-4">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? (
                <>
                  <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save Configuration"
              )}
            </Button>
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}

/* ── Field renderer ── */

function FieldRenderer({
  field,
  value,
  onChange,
}: {
  field: ConfigField;
  value: string;
  onChange: (value: string) => void;
}) {
  switch (field.type) {
    case "select":
      return (
        <Select value={value || field.default || ""} onValueChange={onChange}>
          <SelectTrigger className="h-9 w-full text-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(field.options ?? []).map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    case "textarea":
      return (
        <Textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          rows={4}
          className="font-mono text-xs"
        />
      );
    case "password":
      return (
        <Input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder ?? "••••••••"}
          className="h-9 font-mono text-xs"
        />
      );
    default:
      return (
        <Input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          className="h-9 text-sm"
        />
      );
  }
}

/* ── Credential status badge for tool cards ── */

export function CredentialStatusDot({ configured }: { configured: boolean }) {
  return configured ? (
    <Badge variant="outline" className="gap-1 border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300">
      <CheckCircle className="h-3 w-3" /> Configured
    </Badge>
  ) : null;
}
