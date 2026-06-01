import { Plus } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { McpServerBadgeIcon } from "@/components/shared/McpServerBadgeIcon";
import type { ConfigField, McpConnection, McpConnectionBinding, McpRegistryServer } from "@/types";
import {
  type McpConnectionDraft,
  OAUTH_STATE_STYLES,
  SUPPORT_STYLES,
  TRANSPORT_STYLES,
  VALIDATION_STYLES,
  formatOauthStateLabel,
  formatSupportLabel,
  formatValidationLabel,
} from "./mcp-helpers";
import { McpConnectionEditor } from "./McpConnectionEditor";

interface McpConnectionsTabProps {
  connections: McpConnection[];
  selectedConnectionId: string | null;
  setSelectedConnectionId: (id: string | null) => void;
  connectionDraft: McpConnectionDraft;
  setConnectionDraft: React.Dispatch<React.SetStateAction<McpConnectionDraft>>;
  connectionNameMode: "auto" | "manual";
  setConnectionNameMode: (mode: "auto" | "manual") => void;
  selectedConnection: McpConnection | null;
  selectedConnectionServer: McpRegistryServer | null;
  suggestedConnectionName: string;
  effectiveConnectionEndpoint: string | null;
  connectionFields: ConfigField[];
  registry: McpRegistryServer[];
  connectionBindings: McpConnectionBinding[];
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
  onNewConnection: (serverId?: string) => void;
}

function StatusDot({ className }: { className?: string }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${className}`} />;
}

export function McpConnectionsTab({
  connections,
  selectedConnectionId,
  setSelectedConnectionId,
  connectionDraft,
  setConnectionDraft,
  connectionNameMode,
  setConnectionNameMode,
  selectedConnection,
  selectedConnectionServer,
  suggestedConnectionName,
  effectiveConnectionEndpoint,
  connectionFields,
  registry,
  connectionBindings,
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
  onNewConnection,
}: McpConnectionsTabProps) {
  return (
    <div className="animate-fade-in space-y-4">
      <p className="text-xs text-muted-foreground">Saved connections drive agent attachments. Configure a connection here, then attach it from the agent's Capabilities tab.</p>
      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        {/* Connection List */}
        <Card className="border-border/60 bg-card/55 rounded-2xl">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Saved connections</CardTitle>
                <CardDescription className="text-sm">
                  Reusable bindings for {selectedConnection?.namespace ?? "this namespace"}
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => onNewConnection()} className="gap-1.5">
                <Plus className="h-4 w-4" />
                New
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {connections.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border/60 bg-background/40 px-4 py-6 text-center text-sm text-muted-foreground">
                No saved connections yet. Pick a registry entry to create one.
              </div>
            ) : (
              <ScrollArea className="h-[calc(100vh-24rem)] min-h-[300px]">
                <div className="space-y-2 pr-3">
                  {connections.map((connection) => {
                    const isSelected = selectedConnectionId === connection.id;
                    const transportStyle = TRANSPORT_STYLES[connection.transport];
                    const validationClass = VALIDATION_STYLES[connection.validation.status] ?? "bg-muted-foreground";
                    const oauthClass = connection.oauth
                      ? (OAUTH_STATE_STYLES[connection.oauth.state]?.split(" ").find((c) => c.startsWith("text-"))?.replace("text-", "bg-") ?? "bg-muted-foreground")
                      : null;

                    return (
                      <button
                        key={connection.id}
                        type="button"
                        onClick={() => setSelectedConnectionId(connection.id)}
                        className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition ${
                          isSelected
                            ? "border-primary/25 bg-primary/5"
                            : "border-border/50 bg-background/50 hover:border-primary/20 hover:bg-accent/20"
                        }`}
                        aria-pressed={isSelected}
                      >
                        <McpServerBadgeIcon
                          serverId={connection.server_id}
                          serverName={connection.server_name ?? connection.server_id}
                          transport={connection.transport}
                          size="sm"
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-foreground">{connection.name}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {connection.server_name ?? connection.server_id}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <StatusDot className={transportStyle.color.replace("text-", "bg-")} />
                              {transportStyle.label}
                            </span>
                            <span className="flex items-center gap-1">
                              <StatusDot className={validationClass} />
                              {formatValidationLabel(connection.validation.status)}
                            </span>
                            {connection.auth_type === "oauth" && connection.oauth && oauthClass && (
                              <span className="flex items-center gap-1">
                                <StatusDot className={oauthClass} />
                                {formatOauthStateLabel(connection.oauth.state)}
                              </span>
                            )}
                            <span className="text-muted-foreground/70">
                              {connection.binding_count} binding{connection.binding_count === 1 ? "" : "s"}
                            </span>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>

        {/* Editor */}
        <Card className="border-border/60 bg-card/55 rounded-2xl">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Connection editor</CardTitle>
                <CardDescription className="text-sm">
                  Confirm endpoint, store credentials, and reuse from agents.
                </CardDescription>
              </div>
              {selectedConnection && (
                <Badge variant="outline" className={`text-xs ${SUPPORT_STYLES[selectedConnection.support_level]}`}>
                  {formatSupportLabel(selectedConnection.support_level)}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <McpConnectionEditor
              connectionDraft={connectionDraft}
              setConnectionDraft={setConnectionDraft}
              connectionNameMode={connectionNameMode}
              setConnectionNameMode={setConnectionNameMode}
              selectedConnectionServer={selectedConnectionServer}
              selectedConnection={selectedConnection}
              suggestedConnectionName={suggestedConnectionName}
              effectiveConnectionEndpoint={effectiveConnectionEndpoint}
              connectionFields={connectionFields}
              registry={registry}
              error={error}
              connectionBusy={connectionBusy}
              oauthBusy={oauthBusy}
              draftValidationError={draftValidationError}
              onServerChange={onServerChange}
              onSave={onSave}
              onValidate={onValidate}
              onDelete={onDelete}
              onReset={onReset}
              onStartOAuth={onStartOAuth}
              onRefreshOAuth={onRefreshOAuth}
            />
          </CardContent>
        </Card>
      </div>

      {/* Agent bindings */}
      <Card className="border-border/60 bg-card/55 rounded-2xl">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Agent bindings</CardTitle>
          <CardDescription className="text-sm">Agents currently using the selected connection.</CardDescription>
        </CardHeader>
        <CardContent>
          {!selectedConnection ? (
            <p className="text-sm text-muted-foreground">Select a saved connection to inspect current bindings.</p>
          ) : connectionBindings.length === 0 ? (
            <p className="text-sm text-muted-foreground">This saved connection is not bound to any agents yet.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {connectionBindings.map((binding) => (
                <Badge key={`${binding.namespace}-${binding.agent_name}`} variant="outline" className="px-2.5 py-1 text-sm">
                  {binding.namespace}/{binding.agent_name}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
