import { ExternalLink, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetClose,
} from "@/components/ui/sheet";
import { McpServerBadgeIcon } from "@/components/shared/McpServerBadgeIcon";
import { formatContainerImageDisplay } from "@/lib/mcp";
import type { McpRegistryServer } from "@/types";
import {
  SUPPORT_STYLES,
  TRANSPORT_STYLES,
  buildAuthPreview,
  formatAuthLabel,
  formatOauthScopeLabel,
  formatSupportLabel,
  getDeploymentModelLabel,
  getProtocolLabel,
} from "./mcp-helpers";

interface McpServerDetailProps {
  server: McpRegistryServer | null;
  onClose: () => void;
  onCreateConnection: (serverId?: string) => void;
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

export function McpServerDetail({ server, onClose, onCreateConnection }: McpServerDetailProps) {
  if (!server) return null;

  const transport = TRANSPORT_STYLES[server.transport];
  const authPreview = buildAuthPreview(server);
  const hasFullToolCatalog = server.tool_names.length >= server.tools_count;

  return (
    <Sheet open={!!server} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
        <SheetHeader className="space-y-4 pb-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <McpServerBadgeIcon
                serverId={server.id}
                serverName={server.name}
                transport={server.transport}
                iconName={server.icon}
                size="md"
              />
              <div>
                <SheetTitle className="text-base">{server.name}</SheetTitle>
                <SheetDescription className="text-sm">{server.description}</SheetDescription>
              </div>
            </div>
            <SheetClose asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8" aria-label="Close detail panel">
                <X className="h-4 w-4" />
              </Button>
            </SheetClose>
          </div>

          {server.attachable && (
            <Button size="sm" onClick={() => onCreateConnection(server.id)} className="w-fit">
              Create saved connection
            </Button>
          )}
        </SheetHeader>

        <div className="space-y-6">
          {/* Metadata */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">Transport</p>
              <p className={`text-sm font-semibold ${transport.color}`}>{transport.label}</p>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">Protocol</p>
              <p className="text-sm font-semibold text-foreground">{getProtocolLabel(server)}</p>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">Readiness</p>
              <Badge variant="outline" className={`mt-0.5 text-xs ${SUPPORT_STYLES[server.support_level]}`}>
                {formatSupportLabel(server.support_level)}
              </Badge>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">Authentication</p>
              <p className="text-sm font-semibold text-foreground">{formatAuthLabel(server.auth_type)}</p>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">Tools</p>
              <p className="text-sm font-semibold text-foreground">{server.tools_count}</p>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium uppercase text-muted-foreground">Category</p>
              <p className="text-sm font-semibold capitalize text-foreground">{server.category.replace("-", " ")}</p>
            </div>
          </div>

          <Separator />

          {/* Connection model */}
          <div className="space-y-2">
            <p className="text-xs font-medium uppercase text-muted-foreground">Connection model</p>
            <p className="text-sm font-semibold text-foreground">{getDeploymentModelLabel(server)}</p>
            {server.connection_notes && (
              <p className="text-sm leading-relaxed text-muted-foreground">{server.connection_notes}</p>
            )}
            {(server.docs_url || server.repository_url) && (
              <div className="flex flex-wrap gap-2 pt-1">
                {server.docs_url && <RegistryLinkButton href={server.docs_url} label="Official docs" />}
                {server.repository_url && <RegistryLinkButton href={server.repository_url} label="Source repo" />}
              </div>
            )}
          </div>

          {/* Endpoint */}
          {server.endpoint && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">Registry endpoint</p>
              <code className="block break-all rounded-lg bg-muted px-3 py-2 text-xs font-mono text-foreground">
                {server.endpoint}
              </code>
              <p className="text-sm text-muted-foreground">
                Saved connections prefill this value automatically. You usually only add credentials on top.
              </p>
            </div>
          )}

          {!server.endpoint && server.transport === "remote" && server.suggested_endpoint && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">Suggested endpoint</p>
              <code className="block break-all rounded-lg bg-muted px-3 py-2 text-xs font-mono text-foreground">
                {server.suggested_endpoint}
              </code>
              <p className="text-sm text-muted-foreground">
                This example comes from the published docs for self-hosted use. Replace it if your deployment exposes
                the MCP URL somewhere else.
              </p>
            </div>
          )}

          {!server.endpoint && server.transport === "remote" && !server.suggested_endpoint && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">Endpoint</p>
              <p className="text-sm text-muted-foreground">
                No default endpoint is published for this MCP. Create a saved connection only if you run your own remote
                deployment and can provide its MCP URL.
              </p>
            </div>
          )}

          {/* Auth preview */}
          {authPreview && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">{authPreview.label}</p>
              <code className="block break-all rounded-lg bg-muted px-3 py-2 text-xs font-mono text-foreground">
                {authPreview.value}
              </code>
              <p className="text-sm leading-relaxed text-muted-foreground">{authPreview.help}</p>
            </div>
          )}

          {/* OAuth scopes */}
          {server.auth_type === "oauth" && server.oauth_scopes && server.oauth_scopes.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium uppercase text-muted-foreground">Requested OAuth scopes</p>
                <span className="text-xs text-muted-foreground">{server.oauth_scopes.length} total</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {server.oauth_scopes.map((scope) => (
                  <Badge key={scope} variant="outline" className="rounded-full px-2.5 py-0.5 text-xs text-muted-foreground">
                    {formatOauthScopeLabel(scope)}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {/* Sidecar image */}
          {server.sidecar_image && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">Managed sidecar runtime</p>
              <p className="text-sm font-semibold text-foreground">{formatContainerImageDisplay(server.sidecar_image)}</p>
              <p className="text-sm text-muted-foreground">
                kubesynapse provides the default sidecar build for this toolkit. Override the image only when you need a
                custom runtime.
                {server.sidecar_port ? ` The default pod-local port is ${server.sidecar_port}.` : ""}
              </p>
            </div>
          )}

          {/* Status reason */}
          {server.status_reason && (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase text-muted-foreground">Current support</p>
              <p className="text-sm leading-relaxed text-muted-foreground">{server.status_reason}</p>
            </div>
          )}

          <Separator />

          {/* Tools */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium uppercase text-muted-foreground">
                {hasFullToolCatalog ? "Published tools" : "Published tool highlights"}
              </p>
              <span className="text-xs text-muted-foreground">{server.tools_count} total</span>
            </div>
            {server.tool_names.length > 0 ? (
              <ScrollArea className="max-h-40">
                <div className="flex flex-wrap gap-2 pr-3">
                  {server.tool_names.map((toolName) => (
                    <Badge key={toolName} variant="secondary" className="rounded-full px-2.5 py-0.5 text-xs">
                      {toolName}
                    </Badge>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="text-sm text-muted-foreground">
                This registry entry reports the number of tools, but the detailed tool catalog is not published in the
                registry metadata yet.
              </p>
            )}
          </div>

          {/* Config schema */}
          {server.config_schema && server.config_schema.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs font-medium uppercase text-muted-foreground">Configuration required</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {server.config_schema.map((field) => (
                  <div key={field.key} className="rounded-xl border border-border/50 bg-muted/30 p-3">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground">{field.label}</p>
                      {field.required && (
                        <Badge variant="destructive" className="px-1.5 py-0 text-xs">
                          Required
                        </Badge>
                      )}
                      {field.is_credential && (
                        <Badge variant="outline" className="px-1.5 py-0 text-xs">
                          Secret
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {field.type} &middot; {field.group ?? "general"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tags */}
          <div className="flex flex-wrap gap-2">
            {server.tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="rounded-full px-2.5 py-0.5 text-xs">
                {tag}
              </Badge>
            ))}
          </div>

          <Separator />

          {/* How to use */}
          <div className="text-sm leading-relaxed text-muted-foreground">
            <p>
              <strong className="text-foreground">How to use:</strong>{" "}
              {!server.attachable &&
                "Keep this entry as a catalog reference for now. It should not be attached to agents until the remaining MCP management and runtime work lands."}
              {server.attachable &&
                server.transport === "hub" &&
                "This server is attachable through the shared mcp-hub namespace. Create a saved connection for it, then attach that connection to an agent when you want the hub route available."}
              {server.attachable &&
                server.transport === "sidecar" &&
                "This server will be deployed as a container in the agent's pod. Create a saved connection for it, then attach that connection to the agent so the sidecar launches automatically."}
              {server.attachable &&
                server.transport === "remote" &&
                (server.endpoint
                  ? "This server is modeled as a direct remote MCP endpoint. Saved connections default to the published registry URL; add credentials or connection-specific overrides only when needed."
                  : "This server is modeled as a self-hosted remote MCP integration. Create a saved connection only if you operate your own deployment and can provide its MCP endpoint URL.")}
            </p>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
