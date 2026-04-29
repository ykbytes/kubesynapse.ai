import { useMemo } from "react";

import { ExternalLink } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { McpServerBadgeIcon } from "@/components/McpServerBadgeIcon";
import type { ConfigField, McpConnection, McpRegistryServer } from "@/types";
import {
  type McpConnectionDraft,
  SUPPORT_STYLES,
  TRANSPORT_STYLES,
  buildAuthPreview,
  formatSupportLabel,
  getDeploymentModelLabel,
  getProtocolLabel,
} from "./mcp-helpers";
import { McpOAuthSessionCard } from "./McpOAuthSessionCard";

interface McpConnectionEditorProps {
  connectionDraft: McpConnectionDraft;
  setConnectionDraft: React.Dispatch<React.SetStateAction<McpConnectionDraft>>;
  connectionNameMode: "auto" | "manual";
  setConnectionNameMode: (mode: "auto" | "manual") => void;
  selectedConnectionServer: McpRegistryServer | null;
  selectedConnection: McpConnection | null;
  suggestedConnectionName: string;
  effectiveConnectionEndpoint: string | null;
  connectionFields: ConfigField[];
  registry: McpRegistryServer[];
  error: string;
  connectionBusy: boolean;
  oauthBusy: boolean;
  draftValidationError: string | null;
  onServerChange: (serverId: string) => void;
  onSave: (validate?: boolean) => void;
  onValidate: () => void;
  onDelete: () => void;
  onReset: () => void;
  onStartOAuth: () => void;
  onRefreshOAuth: () => void;
}

function RegistryLinkButton({ href, label }: { href: string; label: string }) {
  return (
    <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
      <a href={href} target="_blank" rel="noreferrer">
        {label}
        <ExternalLink className="h-3.5 w-3.5" />
      </a>
    </Button>
  );
}

export function McpConnectionEditor({
  connectionDraft,
  setConnectionDraft,
  connectionNameMode: _connectionNameMode,
  setConnectionNameMode,
  selectedConnectionServer,
  selectedConnection,
  suggestedConnectionName,
  effectiveConnectionEndpoint,
  connectionFields,
  registry,
  error,
  connectionBusy,
  oauthBusy,
  draftValidationError,
  onServerChange,
  onSave,
  onValidate,
  onDelete,
  onReset,
  onStartOAuth,
  onRefreshOAuth,
}: McpConnectionEditorProps) {
  const requiredFields = useMemo(() => connectionFields.filter((f) => f.required), [connectionFields]);
  const optionalFields = useMemo(() => connectionFields.filter((f) => !f.required), [connectionFields]);

  const selectedConnectionAuthPreview = useMemo(
    () => (selectedConnectionServer ? buildAuthPreview(selectedConnectionServer) : null),
    [selectedConnectionServer],
  );

  function updateField(field: ConfigField, value: string) {
    if (field.is_credential) {
      setConnectionDraft((current) => ({
        ...current,
        credentials: { ...current.credentials, [field.key]: value },
      }));
    } else {
      setConnectionDraft((current) => ({
        ...current,
        config: { ...current.config, [field.key]: value },
      }));
    }
  }

  function renderField(field: ConfigField) {
    const value = field.is_credential
      ? (connectionDraft.credentials[field.key] ?? "")
      : (connectionDraft.config[field.key] ?? "");
    const configured = selectedConnection?.credential_metadata.find((item) => item.key === field.key)?.configured;

    return (
      <div key={field.key} className={`space-y-1.5 ${field.type === "textarea" ? "md:col-span-2" : ""}`}>
        <div className="flex items-center gap-2">
          <Label className="text-sm">{field.label}</Label>
          {field.required && <span className="text-xs text-red-500">*</span>}
          {field.is_credential && configured && (
            <Badge variant="outline" className="text-xs border-emerald-500/25 bg-emerald-500/10 text-emerald-500">
              Stored
            </Badge>
          )}
        </div>
        {field.type === "textarea" ? (
          <Textarea
            rows={3}
            value={value}
            onChange={(e) => updateField(field, e.target.value)}
            placeholder={field.placeholder}
            className="text-sm"
          />
        ) : (
          <Input
            type={field.type === "password" ? "password" : "text"}
            value={value}
            onChange={(e) => updateField(field, e.target.value)}
            placeholder={field.placeholder}
            className="h-10"
          />
        )}
        {field.help && <p className="text-xs text-muted-foreground">{field.help}</p>}
      </div>
    );
  }

  const disabled = connectionBusy || oauthBusy;

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Identity */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-foreground">Identity</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-sm">Connection name</Label>
            <Input
              value={connectionDraft.name}
              onChange={(e) => {
                const nextName = e.target.value;
                setConnectionNameMode(nextName.trim() ? "manual" : "auto");
                setConnectionDraft((current) => ({ ...current, name: nextName }));
              }}
              placeholder={suggestedConnectionName || "gmail-prod"}
              className="h-10"
            />
            {selectedConnectionServer && !connectionDraft.id && (
              <p className="text-xs text-muted-foreground">
                Filled from the selected registry server. Edit it only if you want an environment-specific label.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label className="text-sm">Registry server</Label>
            <Select value={connectionDraft.serverId} onValueChange={onServerChange}>
              <SelectTrigger className="h-10 w-full">
                {selectedConnectionServer ? (
                  <div className="flex min-w-0 items-center gap-2 pr-6">
                    <McpServerBadgeIcon
                      serverId={selectedConnectionServer.id}
                      serverName={selectedConnectionServer.name}
                      transport={selectedConnectionServer.transport}
                      iconName={selectedConnectionServer.icon}
                      size="xs"
                    />
                    <span className="truncate">{selectedConnectionServer.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{selectedConnectionServer.transport}</span>
                  </div>
                ) : (
                  <span className="text-muted-foreground">Select a registry server</span>
                )}
              </SelectTrigger>
              <SelectContent>
                {registry.map((server) => (
                  <SelectItem key={server.id} value={server.id}>
                    <div className="flex items-center gap-2">
                      <McpServerBadgeIcon
                        serverId={server.id}
                        serverName={server.name}
                        transport={server.transport}
                        iconName={server.icon}
                        size="xs"
                      />
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-sm text-foreground">{server.name}</span>
                        <span className="text-xs text-muted-foreground">
                          {server.transport} &middot; {server.tools_count} tool{server.tools_count === 1 ? "" : "s"}
                        </span>
                      </div>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Server info */}
      {selectedConnectionServer && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-foreground">Server info</h3>
          <div className="rounded-2xl border border-border/50 bg-muted/20 p-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className={`text-xs ${TRANSPORT_STYLES[selectedConnectionServer.transport].border} ${TRANSPORT_STYLES[selectedConnectionServer.transport].bg} ${TRANSPORT_STYLES[selectedConnectionServer.transport].color}`}>
                {selectedConnectionServer.transport}
              </Badge>
              <Badge variant="outline" className={`text-xs ${SUPPORT_STYLES[selectedConnectionServer.support_level]}`}>
                {formatSupportLabel(selectedConnectionServer.support_level)}
              </Badge>
              <span className="text-sm text-muted-foreground">{selectedConnectionServer.description}</span>
            </div>
            {selectedConnectionServer.status_reason && (
              <p className="text-sm text-muted-foreground">{selectedConnectionServer.status_reason}</p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="text-xs border-border/60">
                {getProtocolLabel(selectedConnectionServer)}
              </Badge>
              <Badge variant="outline" className="text-xs border-border/60">
                {getDeploymentModelLabel(selectedConnectionServer)}
              </Badge>
            </div>
            {selectedConnectionServer.connection_notes && (
              <p className="text-sm text-muted-foreground">{selectedConnectionServer.connection_notes}</p>
            )}
            {(selectedConnectionServer.docs_url || selectedConnectionServer.repository_url) && (
              <div className="flex flex-wrap gap-2">
                {selectedConnectionServer.docs_url && <RegistryLinkButton href={selectedConnectionServer.docs_url} label="Official docs" />}
                {selectedConnectionServer.repository_url && <RegistryLinkButton href={selectedConnectionServer.repository_url} label="Source repo" />}
              </div>
            )}

            {selectedConnectionServer.transport === "remote" && (
              selectedConnectionServer.endpoint ? (
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
                  <p className="text-sm font-medium text-foreground">Registry-managed endpoint</p>
                  <code className="mt-1 block break-all rounded-lg bg-muted px-2 py-1 text-xs font-mono text-foreground">
                    {selectedConnectionServer.endpoint}
                  </code>
                  <p className="mt-1 text-xs text-muted-foreground">
                    This value is published by the registry and will be reused automatically when the connection is validated and attached.
                  </p>
                </div>
              ) : effectiveConnectionEndpoint ? (
                <div className="rounded-xl border border-border/50 bg-background/60 p-3">
                  <p className="text-sm font-medium text-foreground">Configured self-hosted endpoint</p>
                  <code className="mt-1 block break-all rounded-lg bg-muted px-2 py-1 text-xs font-mono text-foreground">
                    {effectiveConnectionEndpoint}
                  </code>
                  <p className="mt-1 text-xs text-muted-foreground">
                    This URL is stored on the saved connection and will be reused for validation and runtime routing.
                  </p>
                </div>
              ) : selectedConnectionServer.suggested_endpoint ? (
                <div className="rounded-xl border border-border/50 bg-background/60 p-3">
                  <p className="text-sm font-medium text-foreground">Suggested self-hosted endpoint</p>
                  <code className="mt-1 block break-all rounded-lg bg-muted px-2 py-1 text-xs font-mono text-foreground">
                    {selectedConnectionServer.suggested_endpoint}
                  </code>
                  <p className="mt-1 text-xs text-muted-foreground">
                    This example comes from the published docs. Use it as a starting point, then replace it if your deployment exposes a different URL.
                  </p>
                </div>
              ) : (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-sm text-amber-500">
                  This server has no published vendor-hosted MCP endpoint. Use it only when you run your own remote deployment and can provide its endpoint URL.
                </div>
              )
            )}

            {selectedConnectionAuthPreview && (
              <div className="rounded-xl border border-border/50 bg-background/60 p-3">
                <p className="text-sm font-medium text-foreground">{selectedConnectionAuthPreview.label}</p>
                <code className="mt-1 block break-all rounded-lg bg-muted px-2 py-1 text-xs font-mono text-foreground">
                  {selectedConnectionAuthPreview.value}
                </code>
                <p className="mt-1 text-xs text-muted-foreground">{selectedConnectionAuthPreview.help}</p>
              </div>
            )}

            {selectedConnectionServer.auth_type === "oauth" && selectedConnectionServer.oauth_scopes && selectedConnectionServer.oauth_scopes.length > 0 && (
              <div className="rounded-xl border border-border/50 bg-background/60 p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-foreground">Requested OAuth scopes</p>
                  <span className="text-xs text-muted-foreground">{selectedConnectionServer.oauth_scopes.length} scope{selectedConnectionServer.oauth_scopes.length === 1 ? "" : "s"}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedConnectionServer.oauth_scopes.map((scope) => (
                    <Badge key={scope} variant="outline" className="rounded-full px-2.5 py-0.5 text-xs text-muted-foreground">
                      {scope}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-xl border border-border/50 bg-background/60 p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-foreground">
                  {selectedConnectionServer.tool_names.length >= selectedConnectionServer.tools_count ? "Published tools" : "Published tool highlights"}
                </p>
                <span className="text-xs text-muted-foreground">{selectedConnectionServer.tools_count} total</span>
              </div>
              {selectedConnectionServer.tool_names.length > 0 ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedConnectionServer.tool_names.map((toolName) => (
                    <Badge key={toolName} variant="secondary" className="rounded-full px-2.5 py-0.5 text-xs">
                      {toolName}
                    </Badge>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-xs text-muted-foreground">
                  This registry entry reports the tool count, but the detailed tool catalog has not been published yet.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* OAuth */}
      {selectedConnectionServer?.auth_type === "oauth" && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-foreground">Authentication</h3>
          <McpOAuthSessionCard
            server={selectedConnectionServer}
            connection={selectedConnection}
            busy={oauthBusy}
            onStart={onStartOAuth}
            onRefresh={onRefreshOAuth}
          />
        </div>
      )}

      {/* Credentials / Config fields */}
      {connectionFields.length > 0 ? (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-foreground">Configuration</h3>
          {requiredFields.length > 0 && (
            <div className="grid gap-4 md:grid-cols-2">{requiredFields.map(renderField)}</div>
          )}
          {optionalFields.length > 0 && (
            <Accordion type="single" collapsible className="w-full">
              <AccordionItem value="advanced" className="border-none">
                <AccordionTrigger className="text-sm font-medium hover:no-underline">
                  Advanced options ({optionalFields.length})
                </AccordionTrigger>
                <AccordionContent>
                  <div className="grid gap-4 md:grid-cols-2 pt-2">{optionalFields.map(renderField)}</div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}
        </div>
      ) : selectedConnectionServer ? (
        <div className="rounded-xl border border-dashed border-border/60 bg-background/40 px-4 py-3 text-sm text-muted-foreground">
          This connection does not require extra fields. Save it directly or validate it now.
        </div>
      ) : null}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2 pt-2">
        <Button
          size="sm"
          onClick={() => onSave(false)}
          disabled={disabled || !connectionDraft.serverId.trim() || !!draftValidationError}
          title={draftValidationError ?? undefined}
        >
          Save connection
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onSave(true)}
          disabled={disabled || !connectionDraft.serverId.trim() || !!draftValidationError}
          title={draftValidationError ?? undefined}
        >
          Save + validate
        </Button>
        <Button size="sm" variant="outline" onClick={onValidate} disabled={disabled || !selectedConnection}>
          Validate now
        </Button>
        <Button size="sm" variant="outline" onClick={onReset} disabled={disabled}>
          Reset draft
        </Button>
        <Button size="sm" variant="destructive" onClick={onDelete} disabled={disabled || !selectedConnection}>
          Delete
        </Button>
        {draftValidationError && (
          <span className="text-xs text-destructive">{draftValidationError}</span>
        )}
      </div>

      {/* Credential metadata */}
      {selectedConnection && (
        <div className="rounded-2xl border border-border/50 bg-muted/20 p-4 space-y-2">
          <p className="text-sm font-semibold text-foreground">Credential metadata</p>
          <div className="flex flex-wrap gap-2">
            {selectedConnection.credential_metadata.length > 0 ? (
              selectedConnection.credential_metadata.map((field) => (
                <Badge key={field.key} variant="outline" className="text-xs">
                  {field.label}: {field.configured ? "configured" : "not set"}
                </Badge>
              ))
            ) : (
              <span className="text-sm text-muted-foreground">No credential fields for this registry server.</span>
            )}
          </div>
          {selectedConnection.validation.message && (
            <p className="text-sm text-muted-foreground">{selectedConnection.validation.message}</p>
          )}
        </div>
      )}
    </div>
  );
}
