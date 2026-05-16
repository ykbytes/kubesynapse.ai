import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertTriangle, Layers, Plug, RefreshCw, Server, Shield } from "lucide-react";

import {
  createMcpConnection,
  deleteMcpConnection,
  fetchMcpConnectionBindings,
  fetchMcpConnections,
  fetchMcpRegistry,
  fetchMcpProfiles,
  fetchMcpStats,
  fetchMcpCategories,
  refreshMcpConnectionOAuth,
  startMcpConnectionOAuth,
  updateMcpConnection,
  validateMcpConnection,
  apiErrorMessage,
} from "@/lib/api";
import type {
  McpCategory,
  McpConnection,
  McpConnectionBinding,
  McpProfile,
  McpRegistryServer,
  McpStats,
} from "@/types";

import { McpArchitectureTab } from "../mcp/McpArchitectureTab";
import { McpConnectionsTab } from "../mcp/McpConnectionsTab";
import {
  type McpConnectionDraft,
  buildConnectionFields,
  buildSuggestedConnectionName,
  draftFromConnection,
  resolveEffectiveRemoteEndpoint,
  trimRecordValues,
} from "../mcp/mcp-helpers";
import { McpProfilesTab } from "../mcp/McpProfilesTab";
import { McpRegistryTab } from "../mcp/McpRegistryTab";

type McpManagementTab = "registry" | "connections" | "profiles" | "architecture";

interface McpManagementPanelProps {
  token: string;
  namespace: string;
}

function validateConnectionDraft(
  draft: McpConnectionDraft,
  server: McpRegistryServer | null,
): string | null {
  if (!draft.name.trim()) return "Connection name is required.";
  if (!draft.serverId.trim()) return "Select an MCP registry server.";
  if (!server) return "Selected server was not found in the registry.";

  const transport = server.transport;
  if (transport === "remote") {
    const endpoint = String(draft.config.endpoint_url ?? server.endpoint ?? "").trim();
    if (server.attachable && !endpoint) {
      return "Endpoint URL is required for this remote MCP server.";
    }
  }
  if (transport === "sidecar") {
    const port = draft.config.sidecar_port;
    if (port !== undefined && port !== "") {
      const num = Number(port);
      if (!Number.isInteger(num) || num < 1 || num > 65535) {
        return "Sidecar port must be an integer between 1 and 65535.";
      }
    }
  }
  for (const field of server.config_schema) {
    if (field.required && !field.is_credential) {
      const val = draft.config[field.key];
      if (val === undefined || String(val).trim() === "") {
        return `${field.label} is required.`;
      }
    }
  }
  return null;
}

export function McpManagementPanel({ token, namespace }: McpManagementPanelProps) {
  const [registry, setRegistry] = useState<McpRegistryServer[]>([]);
  const [profiles, setProfiles] = useState<McpProfile[]>([]);
  const [stats, setStats] = useState<McpStats | null>(null);
  const [categories, setCategories] = useState<McpCategory[]>([]);
  const [connections, setConnections] = useState<McpConnection[]>([]);
  const [connectionBindings, setConnectionBindings] = useState<McpConnectionBinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<McpManagementTab>("registry");
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [connectionDraft, setConnectionDraft] = useState<McpConnectionDraft>({
    id: null,
    name: "",
    serverId: "",
    config: {},
    credentials: {},
  });
  const [connectionNameMode, setConnectionNameMode] = useState<"auto" | "manual">("auto");
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const oauthPopupRef = useRef<Window | null>(null);
  const oauthPopupWatchRef = useRef<number | null>(null);

  const stopOauthPopupWatch = useCallback(() => {
    if (oauthPopupWatchRef.current !== null) {
      window.clearInterval(oauthPopupWatchRef.current);
      oauthPopupWatchRef.current = null;
    }
    oauthPopupRef.current = null;
  }, []);

  const loadData = useCallback(async () => {
    if (!token.trim()) return;
    setLoading(true);
    setError("");
    try {
      const [reg, prof, st, cats, savedConnections] = await Promise.all([
        fetchMcpRegistry(token),
        fetchMcpProfiles(token),
        fetchMcpStats(token),
        fetchMcpCategories(token),
        fetchMcpConnections(token, namespace),
      ]);
      setRegistry(reg);
      setProfiles(prof);
      setStats(st);
      setCategories(cats);
      setConnections(savedConnections);
      setSelectedConnectionId((current) => current ?? savedConnections[0]?.id ?? null);
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to load MCP registry", { description: msg });
    } finally {
      setLoading(false);
    }
  }, [token, namespace]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    function handleOauthMessage(event: MessageEvent) {
      const payload = event.data as {
        type?: string;
        connectionId?: string;
        status?: string;
        message?: string;
        restartedAgents?: string[];
      } | null;
      if (!payload || payload.type !== "kubesynapse-mcp-oauth-result") {
        return;
      }
      stopOauthPopupWatch();
      setOauthBusy(false);
      if (payload.connectionId) {
        setSelectedConnectionId(payload.connectionId);
      }
      void loadData();
      if (payload.status === "success") {
        toast.success(payload.message || "OAuth sign-in completed");
      } else {
        toast.error(payload.message || "OAuth sign-in failed");
      }
    }

    window.addEventListener("message", handleOauthMessage);
    return () => {
      window.removeEventListener("message", handleOauthMessage);
      stopOauthPopupWatch();
    };
  }, [loadData, stopOauthPopupWatch]);

  const selectedConnection = useMemo(
    () => connections.find((connection) => connection.id === selectedConnectionId) ?? null,
    [connections, selectedConnectionId],
  );
  const selectedConnectionServer = useMemo(
    () => registry.find((server) => server.id === (connectionDraft.serverId || selectedConnection?.server_id || "")) ?? null,
    [registry, connectionDraft.serverId, selectedConnection],
  );
  const suggestedConnectionName = useMemo(
    () => buildSuggestedConnectionName(selectedConnectionServer, connections, connectionDraft.id),
    [selectedConnectionServer, connections, connectionDraft.id],
  );
  const effectiveConnectionEndpoint = useMemo(
    () => resolveEffectiveRemoteEndpoint(selectedConnectionServer, connectionDraft.config),
    [selectedConnectionServer, connectionDraft.config],
  );
  const connectionFields = useMemo(() => buildConnectionFields(selectedConnectionServer), [selectedConnectionServer]);
  const draftValidationError = useMemo(
    () => validateConnectionDraft(connectionDraft, selectedConnectionServer),
    [connectionDraft, selectedConnectionServer],
  );

  useEffect(() => {
    if (!selectedConnection) {
      setConnectionDraft((current) =>
        current.id ? { id: null, name: "", serverId: "", config: {}, credentials: {} } : current,
      );
      setConnectionBindings([]);
      return;
    }
    setConnectionDraft(draftFromConnection(selectedConnection));
    setConnectionNameMode("manual");
    void fetchMcpConnectionBindings(token, namespace, selectedConnection.id)
      .then(setConnectionBindings)
      .catch((err) => {
        const msg = apiErrorMessage(err);
        toast.error("Failed to load MCP connection bindings", { description: msg });
        setConnectionBindings([]);
      });
  }, [selectedConnection, token, namespace]);

  function handleConnectionServerSelection(nextServerId: string) {
    const nextServer = registry.find((server) => server.id === nextServerId) ?? null;
    setConnectionDraft((current) => ({
      ...current,
      serverId: nextServerId,
      name:
        !current.id && (connectionNameMode === "auto" || !current.name.trim())
          ? buildSuggestedConnectionName(nextServer, connections)
          : current.name,
      config: {},
      credentials: {},
    }));
  }

  async function handleSaveConnection(validateOnSave = false): Promise<void> {
    if (!token.trim()) return;
    const resolvedName = connectionDraft.name.trim() || suggestedConnectionName.trim();
    const validationError = validateConnectionDraft(
      { ...connectionDraft, name: resolvedName },
      selectedConnectionServer,
    );
    if (validationError) {
      setError(validationError);
      toast.error("Check the form before saving", { description: validationError });
      return;
    }
    setConnectionBusy(true);
    setError("");
    try {
      const payload = {
        name: resolvedName,
        server_id: connectionDraft.serverId,
        config: trimRecordValues(connectionDraft.config),
        credentials: trimRecordValues(connectionDraft.credentials),
        validate_on_save: validateOnSave,
      };
      const saved = connectionDraft.id
        ? await updateMcpConnection(token, namespace, connectionDraft.id, payload)
        : await createMcpConnection(token, namespace, payload);
      await loadData();
      setSelectedConnectionId(saved.id);
      setConnectionDraft(draftFromConnection(saved));
      toast.success(connectionDraft.id ? "MCP connection updated" : "MCP connection created");
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to save MCP connection", { description: msg });
    } finally {
      setConnectionBusy(false);
    }
  }

  async function handleValidateSelectedConnection(): Promise<void> {
    if (!token.trim() || !selectedConnectionId) return;
    setConnectionBusy(true);
    setError("");
    try {
      const validated = await validateMcpConnection(token, namespace, selectedConnectionId);
      setConnections((current) => current.map((connection) => (connection.id === validated.id ? validated : connection)));
      setConnectionDraft(draftFromConnection(validated));
      toast.success("MCP connection validated");
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to validate MCP connection", { description: msg });
    } finally {
      setConnectionBusy(false);
    }
  }

  async function handleDeleteSelectedConnection(): Promise<void> {
    if (!token.trim() || !selectedConnection) return;
    if (connectionBindings.length > 0 && !showDeleteConfirm) {
      setShowDeleteConfirm(true);
      const boundAgents = connectionBindings.map((b) => `${b.namespace}/${b.agent_name}`).join(", ");
      toast.error("Cannot delete bound connection", {
        description: `Unbind from these agents first: ${boundAgents}`,
        duration: 6000,
      });
      return;
    }
    setShowDeleteConfirm(false);
    setConnectionBusy(true);
    setError("");
    try {
      await deleteMcpConnection(token, namespace, selectedConnection.id);
      setSelectedConnectionId(null);
      setConnectionDraft({ id: null, name: "", serverId: "", config: {}, credentials: {} });
      setConnectionNameMode("auto");
      setConnectionBindings([]);
      await loadData();
      toast.success("MCP connection deleted");
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to delete MCP connection", { description: msg });
    } finally {
      setConnectionBusy(false);
    }
  }

  async function handleStartSelectedConnectionOAuth(): Promise<void> {
    if (!token.trim() || !selectedConnectionId) return;
    setOauthBusy(true);
    setError("");
    try {
      const { authorization_url } = await startMcpConnectionOAuth(token, namespace, selectedConnectionId);
      const popup = window.open(
        authorization_url,
        `kubesynapse-mcp-oauth-${selectedConnectionId}`,
        "popup=yes,width=640,height=760",
      );
      if (!popup) {
        setOauthBusy(false);
        toast.error("Popup blocked", { description: "Allow popups for this site to complete the OAuth sign-in flow." });
        return;
      }
      popup.focus();
      oauthPopupRef.current = popup;
      stopOauthPopupWatch();
      oauthPopupRef.current = popup;
      oauthPopupWatchRef.current = window.setInterval(() => {
        if (oauthPopupRef.current?.closed) {
          stopOauthPopupWatch();
          setOauthBusy(false);
          void loadData();
        }
      }, 700);
    } catch (err) {
      const msg = apiErrorMessage(err);
      setOauthBusy(false);
      setError(msg);
      toast.error("Failed to start MCP OAuth", { description: msg });
    }
  }

  async function handleRefreshSelectedConnectionOAuth(): Promise<void> {
    if (!token.trim() || !selectedConnectionId) return;
    setOauthBusy(true);
    setError("");
    try {
      const refreshed = await refreshMcpConnectionOAuth(token, namespace, selectedConnectionId);
      setConnections((current) => current.map((connection) => (connection.id === refreshed.id ? refreshed : connection)));
      setConnectionDraft(draftFromConnection(refreshed));
      const bindings = await fetchMcpConnectionBindings(token, namespace, refreshed.id);
      setConnectionBindings(bindings);
      toast.success("OAuth session refreshed");
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to refresh OAuth session", { description: msg });
    } finally {
      setOauthBusy(false);
    }
  }

  function handleStartNewConnection(serverId?: string): void {
    const nextServer = registry.find((server) => server.id === (serverId ?? "")) ?? null;
    setSelectedConnectionId(null);
    setConnectionBindings([]);
    setConnectionNameMode("auto");
    setConnectionDraft({
      id: null,
      name: buildSuggestedConnectionName(nextServer, connections),
      serverId: serverId ?? "",
      config: {},
      credentials: {},
    });
    setActiveTab("connections");
    setError("");
  }

  if (loading && registry.length === 0) {
    return (
      <div className="flex flex-1 flex-col gap-4 p-3">
        <div className="flex items-center gap-3">
          <Skeleton className="h-10 w-10 rounded-2xl" />
          <div className="space-y-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 rounded-2xl" />
          ))}
        </div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-32 rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1">
      <div className="mx-auto max-w-7xl space-y-4 p-3 pb-20 sm:p-4 md:pb-0">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/60 bg-gradient-to-br from-background/95 to-muted/25 px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <Plug className="h-5 w-5 text-foreground/60" />
            <h1 className="text-base font-semibold text-foreground">MCP Server Registry</h1>
            <Badge variant="outline" className="border-border/60 bg-background/80 text-xs">
              {namespace}
            </Badge>
            <Badge variant="outline" className="border-orange-500/25 bg-orange-500/10 text-orange-500 text-xs">
              Saved connections drive agent attachments
            </Badge>
          </div>
          <Button variant="outline" size="sm" onClick={() => void loadData()} disabled={loading} className="gap-1.5">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {error && (
          <Card className="border-destructive/30 bg-destructive/8 rounded-2xl">
            <CardContent className="flex items-center gap-3 py-3">
              <AlertTriangle className="h-5 w-5 text-destructive" />
              <p className="text-sm text-destructive">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-card/55 px-4 py-3">
              <span className="text-xs text-muted-foreground">Servers</span>
              <span className="text-base font-bold tabular-nums text-foreground">{stats.total_servers}</span>
            </div>
            <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-card/55 px-4 py-3">
              <span className="text-xs text-muted-foreground">Tools</span>
              <span className="text-base font-bold tabular-nums text-foreground">{stats.total_tools}</span>
            </div>
            <div className="flex items-center justify-between rounded-2xl border border-amber-500/25 bg-amber-500/5 px-4 py-3">
              <span className="text-xs text-muted-foreground">Profiles</span>
              <span className="text-base font-bold tabular-nums text-foreground">{stats.total_profiles}</span>
            </div>
            <div className="flex items-center justify-between rounded-2xl border border-border/60 bg-card/55 px-4 py-3">
              <span className="text-xs text-muted-foreground">Categories</span>
              <span className="text-base font-bold tabular-nums text-foreground">{stats.categories}</span>
            </div>
          </div>
        )}

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as McpManagementTab)} className="space-y-4">
          <TabsList className="h-auto flex-wrap justify-start gap-1 rounded-2xl border border-border/60 bg-background/70 p-1">
            <TabsTrigger value="registry" className="gap-1.5 rounded-xl px-4 py-2 text-sm">
              <Server className="h-4 w-4" />
              Registry
            </TabsTrigger>
            <TabsTrigger value="connections" className="gap-1.5 rounded-xl px-4 py-2 text-sm">
              <Plug className="h-4 w-4" />
              Connections
            </TabsTrigger>
            <TabsTrigger value="profiles" className="gap-1.5 rounded-xl px-4 py-2 text-sm">
              <Layers className="h-4 w-4" />
              Profiles
            </TabsTrigger>
            <TabsTrigger value="architecture" className="gap-1.5 rounded-xl px-4 py-2 text-sm">
              <Shield className="h-4 w-4" />
              Architecture
            </TabsTrigger>
          </TabsList>

          <TabsContent value="registry">
            <McpRegistryTab
              registry={registry}
              categories={categories}
              onCreateConnection={handleStartNewConnection}
            />
          </TabsContent>

          <TabsContent value="connections">
            <McpConnectionsTab
              connections={connections}
              selectedConnectionId={selectedConnectionId}
              setSelectedConnectionId={setSelectedConnectionId}
              connectionDraft={connectionDraft}
              setConnectionDraft={setConnectionDraft}
              connectionNameMode={connectionNameMode}
              setConnectionNameMode={setConnectionNameMode}
              selectedConnection={selectedConnection}
              selectedConnectionServer={selectedConnectionServer}
              suggestedConnectionName={suggestedConnectionName}
              effectiveConnectionEndpoint={effectiveConnectionEndpoint}
              connectionFields={connectionFields}
              registry={registry}
              connectionBindings={connectionBindings}
              error={error}
              connectionBusy={connectionBusy}
              oauthBusy={oauthBusy}
              draftValidationError={draftValidationError}
              onServerChange={handleConnectionServerSelection}
              onSave={handleSaveConnection}
              onValidate={handleValidateSelectedConnection}
              onDelete={handleDeleteSelectedConnection}
              onReset={() => handleStartNewConnection()}
              onStartOAuth={handleStartSelectedConnectionOAuth}
              onRefreshOAuth={handleRefreshSelectedConnectionOAuth}
              onNewConnection={handleStartNewConnection}
            />
          </TabsContent>

          <TabsContent value="profiles">
            <McpProfilesTab profiles={profiles} />
          </TabsContent>

          <TabsContent value="architecture">
            <McpArchitectureTab />
          </TabsContent>
        </Tabs>
      </div>
    </ScrollArea>
  );
}
