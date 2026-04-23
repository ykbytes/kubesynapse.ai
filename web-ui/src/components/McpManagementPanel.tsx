import {
  Activity,
  AlertTriangle,
  BookOpen,
  Box,
  CheckCircle2,
  Brain,
  Cloud,
  Code,
  Database,
  ExternalLink,
  Folder,
  Globe,
  GitBranch,
  Layers,
  LayoutList,
  Mail,
  MessageSquare,
  Monitor,
  Palette,
  Plug,
  RefreshCw,
  Search,
  Server,
  Shield,
  Sparkles,
  Users,
  Wrench,
  Zap,
  Link2,
  Loader2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

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
} from "@/lib/api";
import { formatContainerImageDisplay } from "@/lib/mcp";
import { McpServerBadgeIcon } from "@/components/McpServerBadgeIcon";
import type { ConfigField, McpConnection, McpConnectionBinding, McpRegistryServer, McpProfile, McpStats, McpCategory, McpTransport } from "@/types";

/* ── Icon mapping ── */

const ICON_MAP: Record<string, typeof Code> = {
  "git-branch": GitBranch,
  "book-open": BookOpen,
  globe: Globe,
  "alert-triangle": AlertTriangle,
  "layout-list": LayoutList,
  "message-square": MessageSquare,
  "file-text": BookOpen,
  cloud: Cloud,
  database: Database,
  search: Search,
  box: Box,
  server: Server,
  mail: Mail,
  monitor: Monitor,
  brain: Brain,
  folder: Folder,
  activity: Activity,
  sparkles: Sparkles,
  palette: Palette,
  code: Code,
  users: Users,
  layers: Layers,
  terminal: Code,
};

function resolveIcon(iconName: string): typeof Code {
  return ICON_MAP[iconName] ?? Plug;
}

/* ── Transport styling ── */

const CATEGORY_STYLE = "border-border/60 bg-background/75 text-foreground/70";
const PROFILE_STYLE = { border: "border-amber-500/25", bg: "bg-amber-500/8", accent: "text-amber-500" };

const TRANSPORT_STYLES: Record<McpTransport, { label: string; color: string; bg: string; border: string }> = {
  remote: { label: "Remote", color: "text-sky-500", bg: "bg-sky-500/10", border: "border-sky-500/25" },
  hub: { label: "Hub", color: "text-indigo-500", bg: "bg-indigo-500/10", border: "border-indigo-500/25" },
  sidecar: { label: "Sidecar", color: "text-amber-500", bg: "bg-amber-500/10", border: "border-amber-500/25" },
};

const CATEGORY_COLORS: Record<string, string> = {
  developer: CATEGORY_STYLE,
  search: CATEGORY_STYLE,
  cloud: CATEGORY_STYLE,
  data: CATEGORY_STYLE,
  devops: CATEGORY_STYLE,
  communication: CATEGORY_STYLE,
  observability: CATEGORY_STYLE,
  browser: CATEGORY_STYLE,
  ai: CATEGORY_STYLE,
  design: CATEGORY_STYLE,
  productivity: CATEGORY_STYLE,
  "project-management": CATEGORY_STYLE,
};

const PROFILE_COLORS: Record<string, { border: string; bg: string; accent: string }> = {
  sky: PROFILE_STYLE,
  violet: PROFILE_STYLE,
  emerald: PROFILE_STYLE,
  amber: PROFILE_STYLE,
  rose: PROFILE_STYLE,
  fuchsia: PROFILE_STYLE,
};

const SUPPORT_STYLES = {
  ready: "border-emerald-500/25 bg-emerald-500/10 text-emerald-500",
  limited: "border-amber-500/25 bg-amber-500/10 text-amber-500",
  planned: "border-border/60 bg-background/70 text-foreground/70",
} as const;

const OAUTH_STATE_STYLES = {
  connected: "border-emerald-500/25 bg-emerald-500/10 text-emerald-500",
  expired: "border-amber-500/25 bg-amber-500/10 text-amber-500",
  required: "border-border/60 bg-background/70 text-foreground/70",
} as const;

function formatSupportLabel(level: McpRegistryServer["support_level"]): string {
  return level === "ready" ? "Ready now" : level === "limited" ? "Needs setup" : "Planned";
}

function formatOauthStateLabel(state: "required" | "connected" | "expired"): string {
  return state === "connected" ? "OAuth connected" : state === "expired" ? "OAuth expired" : "OAuth required";
}

function formatOauthScopeLabel(scope: string): string {
  return scope
    .replace(/^https?:\/\/www\.googleapis\.com\/auth\//, "google:")
    .replace(/^https?:\/\//, "")
    .replace(/^openid$/, "openid")
    .replace(/^profile$/, "profile")
    .replace(/^email$/, "email");
}

function formatOauthExpiry(value?: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toLocaleString();
}

function getProtocolLabel(server: Pick<McpRegistryServer, "protocol_label" | "transport">): string {
  if (server.protocol_label?.trim()) {
    return server.protocol_label;
  }
  if (server.transport === "remote") {
    return "Streamable HTTP";
  }
  if (server.transport === "hub") {
    return "Cluster service HTTP";
  }
  return "Pod-local HTTP";
}

function getDeploymentModelLabel(server: Pick<McpRegistryServer, "deployment_model" | "transport" | "endpoint">): string {
  if (server.deployment_model?.trim()) {
    return server.deployment_model;
  }
  if (server.transport === "remote") {
    return server.endpoint ? "Vendor-hosted remote" : "Self-hosted remote";
  }
  if (server.transport === "hub") {
    return "Shared hub service";
  }
  return "Per-agent sidecar";
}

function formatAuthLabel(authType: McpRegistryServer["auth_type"]): string {
  if (authType === "none") {
    return "None required";
  }
  return authType.replace(/_/g, " ");
}

function buildAuthPreview(server: Pick<McpRegistryServer, "auth_type" | "auth_header_name" | "auth_header_prefix" | "config_schema" | "attachable" | "oauth_scopes">): {
  label: string;
  value: string;
  help: string;
} | null {
  if (server.auth_type === "none") {
    return null;
  }

  if (server.auth_type === "oauth") {
    const scopeSummary = server.oauth_scopes?.length
      ? `Scopes: ${server.oauth_scopes.map((scope) => formatOauthScopeLabel(scope)).join(", ")}.`
      : "";
    return {
      label: "Auth flow",
      value: "Browser OAuth sign-in",
      help: server.attachable
        ? `${scopeSummary} Save the connection first, then launch OAuth once from the MCP page so the runtime can reuse the stored token.`.trim()
        : `${scopeSummary} This registry entry still needs provider-specific OAuth wiring before agents can attach it.`.trim(),
    };
  }

  if (server.auth_type === "kubeconfig") {
    return {
      label: "Auth model",
      value: "Runtime-managed kubeconfig",
      help: "This flow depends on runtime support rather than a token stored on the saved connection.",
    };
  }

  const primaryCredentialField = server.config_schema.find((field) => field.is_credential);
  if (server.auth_type === "connection_string") {
    return {
      label: "Credential field",
      value: primaryCredentialField?.label ?? "Connection string",
      help: "Store the full connection string once on the saved connection and keep it out of the agent spec.",
    };
  }

  const headerName = server.auth_header_name?.trim() || (server.auth_type === "bearer" ? "Authorization" : server.auth_type === "api_key" ? "X-API-Key" : "");
  const headerPrefix = server.auth_header_prefix ?? (server.auth_type === "bearer" ? "Bearer " : null);

  if (headerName) {
    return {
      label: "Runtime header",
      value: `${headerName}: ${headerPrefix ?? ""}{secret}`,
      help: `Saved connections store ${primaryCredentialField?.label ?? "the secret"} and inject it only at runtime.`,
    };
  }

  return {
    label: "Credential field",
    value: primaryCredentialField?.label ?? formatAuthLabel(server.auth_type),
    help: "Store the secret on the saved connection. KubeSynth passes it to the runtime without exposing it in agent specs.",
  };
}

function RegistryLinkButton({ href, label }: { href: string; label: string }) {
  return (
    <Button asChild variant="outline" size="sm" className="h-7 px-2 text-[11px]">
      <a href={href} target="_blank" rel="noreferrer">
        {label}
        <ExternalLink className="h-3 w-3" />
      </a>
    </Button>
  );
}

type McpManagementTab = "registry" | "connections" | "profiles" | "architecture";

interface McpConnectionDraft {
  id: string | null;
  name: string;
  serverId: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
}

function normalizeConnectionName(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function buildSuggestedConnectionName(
  server: McpRegistryServer | null,
  connections: McpConnection[],
  currentId?: string | null,
): string {
  if (!server) {
    return "";
  }

  const baseName = server.name.trim() || server.id;
  const usedNames = new Set(
    connections
      .filter((connection) => connection.id !== currentId)
      .map((connection) => normalizeConnectionName(connection.name))
      .filter(Boolean),
  );

  const normalizedBase = normalizeConnectionName(baseName);
  if (!normalizedBase || !usedNames.has(normalizedBase)) {
    return baseName;
  }

  let suffix = 2;
  while (usedNames.has(normalizeConnectionName(`${baseName} ${suffix}`))) {
    suffix += 1;
  }
  return `${baseName} ${suffix}`;
}

function resolveEffectiveRemoteEndpoint(
  server: McpRegistryServer | null,
  config: Record<string, string>,
): string | null {
  if (!server || server.transport !== "remote") {
    return null;
  }
  const configuredEndpoint = String(config.endpoint_url ?? "").trim();
  if (configuredEndpoint) {
    return configuredEndpoint;
  }
  const registryEndpoint = String(server.endpoint ?? "").trim();
  return registryEndpoint || null;
}

function buildConnectionFields(server: McpRegistryServer | null): ConfigField[] {
  if (!server) {
    return [];
  }
  const fields = [...server.config_schema];
  if (server.transport === "remote" && !String(server.endpoint ?? "").trim()) {
    fields.unshift({
      key: "endpoint_url",
      label: "MCP Endpoint URL",
      type: "text",
      placeholder: server.suggested_endpoint?.trim() || "https://mcp.example.com/mcp",
      required: true,
      group: "connection",
      help: server.suggested_endpoint?.trim()
        ? "Example self-hosted endpoint from the published docs. Replace it with the URL for your own deployment if needed."
        : "External MCP endpoint to call for this saved connection.",
    });
  }
  if (server.transport === "sidecar") {
    fields.unshift(
      {
        key: "sidecar_port",
        label: "Sidecar Port",
        type: "text",
        placeholder: String(server.sidecar_port ?? 8097),
        group: "connection",
        help: "Pod-local port for the sidecar container.",
      },
      {
        key: "sidecar_image",
        label: "Custom Sidecar Image",
        type: "text",
        placeholder: "your-registry.example.com/mcp-sidecar:latest",
        group: "connection",
        help: "Leave empty to keep the platform-managed sidecar runtime.",
      },
    );
  }
  return fields;
}

function draftFromConnection(connection: McpConnection): McpConnectionDraft {
  return {
    id: connection.id,
    name: connection.name,
    serverId: connection.server_id,
    config: Object.fromEntries(Object.entries(connection.config ?? {}).map(([key, value]) => [key, String(value ?? "")])),
    credentials: {},
  };
}

function trimRecordValues(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values)
      .map(([key, value]) => [key, value.trim()])
      .filter(([, value]) => value.length > 0),
  );
}

/* ── Props ── */

interface McpManagementPanelProps {
  token: string;
  namespace: string;
}

/* ── Component ── */

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
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTransport, setActiveTransport] = useState<McpTransport | "all">("all");
  const [activeCategory, setActiveCategory] = useState("all");
  const [selectedServer, setSelectedServer] = useState<McpRegistryServer | null>(null);
  const [selectedConnectionId, setSelectedConnectionId] = useState<string | null>(null);
  const [connectionDraft, setConnectionDraft] = useState<McpConnectionDraft>({ id: null, name: "", serverId: "", config: {}, credentials: {} });
  const [connectionNameMode, setConnectionNameMode] = useState<"auto" | "manual">("auto");
  const [connectionBusy, setConnectionBusy] = useState(false);
  const [oauthBusy, setOauthBusy] = useState(false);
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
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast.error("Failed to load MCP registry", { description: msg });
    } finally {
      setLoading(false);
    }
  }, [token, namespace]);

  useEffect(() => { void loadData(); }, [loadData]);

  useEffect(() => {
    function handleOauthMessage(event: MessageEvent) {
      const payload = event.data as {
        type?: string;
        connectionId?: string;
        status?: string;
        message?: string;
        restartedAgents?: string[];
      } | null;
      if (!payload || payload.type !== "kubesynth-mcp-oauth-result") {
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

  useEffect(() => {
    if (!selectedConnection) {
      setConnectionDraft((current) => current.id ? { id: null, name: "", serverId: "", config: {}, credentials: {} } : current);
      setConnectionBindings([]);
      return;
    }
    setConnectionDraft(draftFromConnection(selectedConnection));
    setConnectionNameMode("manual");
    void fetchMcpConnectionBindings(token, namespace, selectedConnection.id)
      .then(setConnectionBindings)
      .catch((err) => {
        const msg = err instanceof Error ? err.message : String(err);
        toast.error("Failed to load MCP connection bindings", { description: msg });
        setConnectionBindings([]);
      });
  }, [selectedConnection, token, namespace]);

  const filteredServers = useMemo(() => {
    let result = registry;
    if (activeTransport !== "all") {
      result = result.filter((s) => s.transport === activeTransport);
    }
    if (activeCategory !== "all") {
      result = result.filter((s) => s.category === activeCategory);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q) ||
          s.id.toLowerCase().includes(q) ||
          s.tags.some((t) => t.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [registry, activeTransport, activeCategory, searchQuery]);
  const readyServers = useMemo(
    () => filteredServers.filter((server) => server.support_level === "ready"),
    [filteredServers],
  );
  const deferredServers = useMemo(
    () => filteredServers.filter((server) => server.support_level !== "ready"),
    [filteredServers],
  );
  const selectedConnectionAuthPreview = useMemo(
    () => (selectedConnectionServer ? buildAuthPreview(selectedConnectionServer) : null),
    [selectedConnectionServer],
  );

  const transportCounts = useMemo(() => {
    const counts = { all: registry.length, remote: 0, hub: 0, sidecar: 0 };
    for (const s of registry) {
      if (s.transport in counts) counts[s.transport as McpTransport]++;
    }
    return counts;
  }, [registry]);

  function handleConnectionServerSelection(nextServerId: string) {
    const nextServer = registry.find((server) => server.id === nextServerId) ?? null;
    setConnectionDraft((current) => ({
      ...current,
      serverId: nextServerId,
      name: !current.id && (connectionNameMode === "auto" || !current.name.trim())
        ? buildSuggestedConnectionName(nextServer, connections)
        : current.name,
      config: {},
      credentials: {},
    }));
  }

  async function handleSaveConnection(validateOnSave = false): Promise<void> {
    if (!token.trim()) return;
    const resolvedName = connectionDraft.name.trim() || suggestedConnectionName.trim();
    if (!resolvedName) {
      setError("Connection name is required.");
      return;
    }
    if (!connectionDraft.serverId.trim()) {
      setError("Select an MCP registry server before saving the connection.");
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
      const msg = err instanceof Error ? err.message : String(err);
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
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast.error("Failed to validate MCP connection", { description: msg });
    } finally {
      setConnectionBusy(false);
    }
  }

  async function handleDeleteSelectedConnection(): Promise<void> {
    if (!token.trim() || !selectedConnection) return;
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
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      toast.error("Failed to delete MCP connection", { description: msg });
    } finally {
      setConnectionBusy(false);
    }
  }

  async function handleStartSelectedConnectionOAuth(): Promise<void> {
    if (!token.trim() || !selectedConnectionId) {
      return;
    }
    setOauthBusy(true);
    setError("");
    try {
      const { authorization_url } = await startMcpConnectionOAuth(token, namespace, selectedConnectionId);
      const popup = window.open(authorization_url, `kubesynth-mcp-oauth-${selectedConnectionId}`, "popup=yes,width=640,height=760");
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
      const msg = err instanceof Error ? err.message : String(err);
      setOauthBusy(false);
      setError(msg);
      toast.error("Failed to start MCP OAuth", { description: msg });
    }
  }

  async function handleRefreshSelectedConnectionOAuth(): Promise<void> {
    if (!token.trim() || !selectedConnectionId) {
      return;
    }
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
      const msg = err instanceof Error ? err.message : String(err);
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
      <div className="flex flex-1 flex-col gap-6 p-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-10 w-10 rounded-2xl" />
          <div className="space-y-1">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-48 rounded-2xl" />)}
        </div>
      </div>
    );
  }

  return (
    <ScrollArea className="flex-1">
      <div className="mx-auto max-w-7xl space-y-6 p-6">
        {/* ── Header ── */}
        <div className="rounded-3xl border border-border/60 bg-gradient-to-br from-background/95 via-background/90 to-muted/35 p-5 shadow-sm shadow-black/5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border/60 bg-background/85 text-foreground/80 shadow-sm shadow-black/5">
                <Plug className="h-6 w-6" />
              </div>
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="border-border/60 bg-background/80">Namespace: {namespace}</Badge>
                  <Badge variant="outline" className="border-orange-500/25 bg-orange-500/10 text-orange-500">Saved connections drive agent attachments</Badge>
                </div>
                <div>
                  <h1 className="text-xl font-semibold tracking-tight text-foreground">MCP Server Registry</h1>
                  <p className="text-sm leading-6 text-muted-foreground">
                    Manage Model Context Protocol servers across remote endpoints, shared hubs, and pod-local sidecars.
                  </p>
                </div>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => void loadData()} disabled={loading} className="gap-1.5 bg-background/80">
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>

        {error && (
          <Card className="border-destructive/30 bg-destructive/8 shadow-sm shadow-black/5">
            <CardContent className="flex items-center gap-3 py-3">
              <AlertTriangle className="h-4 w-4 text-destructive" />
              <p className="text-sm text-destructive">{error}</p>
            </CardContent>
          </Card>
        )}

        {/* ── Stats Cards ── */}
        {stats && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardContent className="flex items-center gap-4 p-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border/60 bg-background/70 text-foreground/80">
                  <Server className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-2xl font-bold tabular-nums text-foreground">{stats.total_servers}</p>
                  <p className="text-xs text-muted-foreground">Total Servers</p>
                </div>
              </CardContent>
            </Card>
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardContent className="flex items-center gap-4 p-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border/60 bg-background/70 text-foreground/80">
                  <Wrench className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-2xl font-bold tabular-nums text-foreground">{stats.total_tools}</p>
                  <p className="text-xs text-muted-foreground">Available Tools</p>
                </div>
              </CardContent>
            </Card>
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardContent className="flex items-center gap-4 p-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-amber-500/25 bg-amber-500/10 text-amber-500">
                  <Layers className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-2xl font-bold tabular-nums text-foreground">{stats.total_profiles}</p>
                  <p className="text-xs text-muted-foreground">Curated Profiles</p>
                </div>
              </CardContent>
            </Card>
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardContent className="flex items-center gap-4 p-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border/60 bg-background/70 text-foreground/80">
                  <Zap className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-2xl font-bold tabular-nums text-foreground">{stats.categories}</p>
                  <p className="text-xs text-muted-foreground">Categories</p>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* ── Main Tabs ── */}
        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as McpManagementTab)} className="space-y-5">
          <TabsList className="h-auto flex-wrap justify-start gap-1 rounded-2xl border border-border/60 bg-background/70 p-1.5">
            <TabsTrigger value="registry" className="gap-1.5">
              <Server className="h-3.5 w-3.5" />
              Registry
            </TabsTrigger>
            <TabsTrigger value="connections" className="gap-1.5">
              <Plug className="h-3.5 w-3.5" />
              Connections
            </TabsTrigger>
            <TabsTrigger value="profiles" className="gap-1.5">
              <Layers className="h-3.5 w-3.5" />
              Profiles
            </TabsTrigger>
            <TabsTrigger value="architecture" className="gap-1.5">
              <Shield className="h-3.5 w-3.5" />
              Architecture
            </TabsTrigger>
          </TabsList>

          {/* ── Registry Tab ── */}
          <TabsContent value="registry" className="animate-fade-in space-y-5">
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardContent className="space-y-3 p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex gap-1.5 rounded-xl border border-border/60 bg-background/75 p-1">
                    {(["all", "remote", "hub", "sidecar"] as const).map((t) => {
                      const isActive = activeTransport === t;
                      const count = transportCounts[t];
                      return (
                        <button
                          key={t}
                          onClick={() => setActiveTransport(t)}
                          className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                            isActive
                              ? "bg-primary/15 text-primary shadow-sm"
                              : "text-muted-foreground hover:bg-accent hover:text-foreground"
                          }`}
                        >
                          {t === "all" ? "All" : TRANSPORT_STYLES[t].label}
                          <span className={`rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${isActive ? "bg-primary/20" : "bg-muted"}`}>
                            {count}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <div className="relative min-w-[200px] flex-1">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search servers, tools, or tags..."
                      className="h-9 bg-background/90 pl-9"
                    />
                  </div>
                  <select
                    value={activeCategory}
                    onChange={(e) => setActiveCategory(e.target.value)}
                    className="h-9 rounded-lg border border-border/60 bg-background/90 px-3 text-xs text-foreground shadow-sm"
                  >
                    <option value="all">All categories</option>
                    {categories.map((cat) => (
                      <option key={cat.id} value={cat.id}>
                        {cat.name} ({cat.count})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                  <span className="font-medium text-foreground/70">Transport types:</span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-sky-500" />
                    <span>Remote — vendor-hosted, zero containers</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-indigo-500" />
                    <span>Hub — shared in mcp-hub namespace</span>
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-amber-500" />
                    <span>Sidecar — pod-local container per agent</span>
                  </span>
                </div>
              </CardContent>
            </Card>

            {/* Server Grid */}
            {filteredServers.length === 0 ? (
              <Card className="border-dashed border-border/70 bg-gradient-to-br from-background/80 to-muted/20 shadow-sm shadow-black/5">
                <CardContent className="flex flex-col items-center justify-center py-16 text-center">
                  <Search className="h-8 w-8 text-muted-foreground/50 mb-3" />
                  <p className="font-medium text-foreground">No servers match your filters</p>
                  <p className="text-sm text-muted-foreground mt-1">Try adjusting the transport type, category, or search query.</p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-5">
                {readyServers.length > 0 ? (
                  <section className="space-y-3">
                    <div className="flex flex-wrap items-end justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-foreground">Ready now</p>
                        <p className="text-xs text-muted-foreground">Published endpoints or managed runtimes that can be attached immediately.</p>
                      </div>
                      <Badge variant="outline" className="border-border/60 bg-background/70 text-[10px] text-muted-foreground">
                        {readyServers.length} server{readyServers.length === 1 ? "" : "s"}
                      </Badge>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                      {readyServers.map((server) => (
                        <McpServerCard
                          key={server.id}
                          server={server}
                          isSelected={selectedServer?.id === server.id}
                          onSelect={() => setSelectedServer(selectedServer?.id === server.id ? null : server)}
                        />
                      ))}
                    </div>
                  </section>
                ) : null}

                {deferredServers.length > 0 ? (
                  <section className="space-y-3">
                    <div className="rounded-2xl border border-border/60 bg-muted/15 px-4 py-3 shadow-sm shadow-black/5">
                      <p className="text-sm font-medium text-foreground">Needs extra setup or runtime support</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        Keep these entries in the catalog for docs, auth prep, and self-hosted examples. They either need your own endpoint URL, provider-specific sign-in metadata, or a runtime adapter that is still pending.
                      </p>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                      {deferredServers.map((server) => (
                        <McpServerCard
                          key={server.id}
                          server={server}
                          isSelected={selectedServer?.id === server.id}
                          onSelect={() => setSelectedServer(selectedServer?.id === server.id ? null : server)}
                        />
                      ))}
                    </div>
                  </section>
                ) : null}
              </div>
            )}

            {/* Detail Panel */}
            {selectedServer && (
              <McpServerDetail
                server={selectedServer}
                onClose={() => setSelectedServer(null)}
                onCreateConnection={handleStartNewConnection}
              />
            )}
          </TabsContent>

            {/* ── Saved Connections Tab ── */}
            <TabsContent value="connections" className="animate-fade-in space-y-5">
              <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <CardTitle className="text-sm">Saved MCP connections</CardTitle>
                        <CardDescription>Reusable namespace-scoped bindings for remote endpoints, hub services, and managed sidecar defaults in {namespace}.</CardDescription>
                      </div>
                      <Button variant="outline" size="sm" onClick={() => handleStartNewConnection()}>
                        New connection
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="rounded-2xl border border-border/60 bg-muted/15 px-3 py-3 text-xs leading-5 text-muted-foreground shadow-sm shadow-black/5">
                      Saved connections are the reusable source of truth for MCP setup. Agents now attach remote endpoints, shared hub routes, and sidecar defaults directly from these connections instead of maintaining a separate toolkit picker.
                    </div>
                    {connections.length === 0 ? (
                      <div className="rounded-2xl border border-dashed border-border/70 bg-background/60 px-4 py-6 text-sm text-muted-foreground">
                        No saved MCP connections exist in this namespace yet. Create one here after you pick a registry entry and confirm its endpoint and auth model.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {connections.map((connection) => (
                          <button
                            key={connection.id}
                            type="button"
                            onClick={() => setSelectedConnectionId(connection.id)}
                            className={`flex w-full items-start justify-between gap-3 rounded-xl border px-3 py-3 text-left transition ${
                              selectedConnectionId === connection.id
                                ? "border-primary/25 bg-primary/5 shadow-sm shadow-primary/10"
                                : "border-border/60 bg-background/70 hover:border-primary/20 hover:bg-accent/30"
                            }`}
                          >
                            <div className="flex min-w-0 items-start gap-3">
                              <McpServerBadgeIcon
                                serverId={connection.server_id}
                                serverName={connection.server_name ?? connection.server_id}
                                transport={connection.transport}
                                size="sm"
                              />
                              <div className="min-w-0">
                                <p className="text-sm font-medium text-foreground">{connection.name}</p>
                                <p className="mt-1 text-xs text-muted-foreground">{connection.server_name ?? connection.server_id}</p>
                                <div className="mt-2 flex flex-wrap gap-1.5">
                                  <Badge variant="outline" className={`text-[10px] ${TRANSPORT_STYLES[connection.transport].border} ${TRANSPORT_STYLES[connection.transport].bg} ${TRANSPORT_STYLES[connection.transport].color}`}>
                                    {TRANSPORT_STYLES[connection.transport].label}
                                  </Badge>
                                  {connection.auth_type !== "none" ? (
                                    <Badge variant="outline" className="text-[10px] border-border/60 bg-background/80 text-foreground/70">
                                      {formatAuthLabel(connection.auth_type)}
                                    </Badge>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                            <div className="flex shrink-0 flex-col items-end gap-1">
                              <Badge variant="outline" className={`text-[10px] ${SUPPORT_STYLES[connection.support_level]}`}>
                                {formatSupportLabel(connection.support_level)}
                              </Badge>
                              <Badge variant="secondary" className="text-[10px]">
                                {connection.validation.status}
                              </Badge>
                              {connection.auth_type === "oauth" && connection.oauth ? (
                                <Badge variant="outline" className={`text-[10px] ${OAUTH_STATE_STYLES[connection.oauth.state]}`}>
                                  {formatOauthStateLabel(connection.oauth.state)}
                                </Badge>
                              ) : null}
                              <span className="text-[10px] text-muted-foreground">{connection.binding_count} binding{connection.binding_count === 1 ? "" : "s"}</span>
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <CardTitle className="text-sm">Connection editor</CardTitle>
                        <CardDescription>Confirm the endpoint, store credentials once, and reuse the saved connection from agents instead of copying raw MCP strings around.</CardDescription>
                      </div>
                      {selectedConnection ? (
                        <Badge variant="outline" className={`${SUPPORT_STYLES[selectedConnection.support_level]}`}>
                          {formatSupportLabel(selectedConnection.support_level)}
                        </Badge>
                      ) : null}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {error ? (
                      <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        {error}
                      </div>
                    ) : null}

                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label className="text-xs">Connection name</Label>
                        <Input
                          value={connectionDraft.name}
                          onChange={(event) => {
                            const nextName = event.target.value;
                            setConnectionNameMode(nextName.trim() ? "manual" : "auto");
                            setConnectionDraft((current) => ({ ...current, name: nextName }));
                          }}
                          placeholder={suggestedConnectionName || "gmail-prod"}
                        />
                        {selectedConnectionServer && !connectionDraft.id ? (
                          <p className="text-[11px] text-muted-foreground">
                            Filled from the selected registry server. Edit it only if you want an environment-specific label.
                          </p>
                        ) : null}
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs">Registry server</Label>
                        <Select value={connectionDraft.serverId} onValueChange={handleConnectionServerSelection}>
                          <SelectTrigger className="h-10 w-full rounded-lg border border-border/60 bg-background px-3 text-sm text-foreground">
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
                                    <span className="text-[11px] text-muted-foreground">
                                      {server.transport} • {server.tools_count} tool{server.tools_count === 1 ? "" : "s"}
                                    </span>
                                  </div>
                                </div>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    {selectedConnectionServer ? (
                      <div className="rounded-2xl border border-border/60 bg-muted/15 p-3 text-xs text-muted-foreground shadow-sm shadow-black/5">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className={`${TRANSPORT_STYLES[selectedConnectionServer.transport].border} ${TRANSPORT_STYLES[selectedConnectionServer.transport].bg} ${TRANSPORT_STYLES[selectedConnectionServer.transport].color}`}>
                            {selectedConnectionServer.transport}
                          </Badge>
                          <Badge variant="outline" className={`${SUPPORT_STYLES[selectedConnectionServer.support_level]}`}>
                            {formatSupportLabel(selectedConnectionServer.support_level)}
                          </Badge>
                          <span>{selectedConnectionServer.description}</span>
                        </div>
                        {selectedConnectionServer.status_reason ? (
                          <p className="mt-2 leading-5">{selectedConnectionServer.status_reason}</p>
                        ) : null}
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="text-[10px] border-border/60">
                            {getProtocolLabel(selectedConnectionServer)}
                          </Badge>
                          <Badge variant="outline" className="text-[10px] border-border/60">
                            {getDeploymentModelLabel(selectedConnectionServer)}
                          </Badge>
                        </div>
                        {selectedConnectionServer.connection_notes ? (
                          <p className="mt-2 leading-5">{selectedConnectionServer.connection_notes}</p>
                        ) : null}
                        {(selectedConnectionServer.docs_url || selectedConnectionServer.repository_url) ? (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {selectedConnectionServer.docs_url ? (
                              <RegistryLinkButton href={selectedConnectionServer.docs_url} label="Official docs" />
                            ) : null}
                            {selectedConnectionServer.repository_url ? (
                              <RegistryLinkButton href={selectedConnectionServer.repository_url} label="Source repo" />
                            ) : null}
                          </div>
                        ) : null}
                        {selectedConnectionServer.transport === "remote" ? (
                          selectedConnectionServer.endpoint ? (
                            <div className="mt-3 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                              <p className="text-[11px] font-medium text-foreground">
                                Registry-managed endpoint
                              </p>
                              <code className="mt-1 block break-all rounded bg-muted px-2 py-1 text-[11px] font-mono text-foreground">
                                {selectedConnectionServer.endpoint}
                              </code>
                              <p className="mt-1 text-[11px] text-muted-foreground">
                                This value is published by the registry and will be reused automatically when the connection is validated and attached.
                              </p>
                            </div>
                          ) : effectiveConnectionEndpoint ? (
                            <div className="mt-3 rounded-lg border border-border/60 bg-background/80 p-3">
                              <p className="text-[11px] font-medium text-foreground">Configured self-hosted endpoint</p>
                              <code className="mt-1 block break-all rounded bg-muted px-2 py-1 text-[11px] font-mono text-foreground">
                                {effectiveConnectionEndpoint}
                              </code>
                              <p className="mt-1 text-[11px] text-muted-foreground">
                                This URL is stored on the saved connection and will be reused for validation and runtime routing.
                              </p>
                            </div>
                          ) : selectedConnectionServer.suggested_endpoint ? (
                            <div className="mt-3 rounded-lg border border-border/60 bg-background/80 p-3">
                              <p className="text-[11px] font-medium text-foreground">Suggested self-hosted endpoint</p>
                              <code className="mt-1 block break-all rounded bg-muted px-2 py-1 text-[11px] font-mono text-foreground">
                                {selectedConnectionServer.suggested_endpoint}
                              </code>
                              <p className="mt-1 text-[11px] text-muted-foreground">
                                This example comes from the published docs. Use it as a starting point, then replace it if your deployment exposes a different URL.
                              </p>
                            </div>
                          ) : (
                            <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-500">
                              This server has no published vendor-hosted MCP endpoint. Use it only when you run your own remote deployment and can provide its endpoint URL.
                            </div>
                          )
                        ) : null}
                        {selectedConnectionAuthPreview ? (
                          <div className="mt-3 rounded-lg border border-border/60 bg-background/80 p-3">
                            <p className="text-[11px] font-medium text-foreground">{selectedConnectionAuthPreview.label}</p>
                            <code className="mt-1 block break-all rounded bg-muted px-2 py-1 text-[11px] font-mono text-foreground">
                              {selectedConnectionAuthPreview.value}
                            </code>
                            <p className="mt-1 text-[11px] text-muted-foreground">
                              {selectedConnectionAuthPreview.help}
                            </p>
                          </div>
                        ) : null}
                        {selectedConnectionServer.auth_type === "oauth" && selectedConnectionServer.oauth_scopes?.length ? (
                          <div className="mt-3 rounded-lg border border-border/60 bg-background/80 p-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-[11px] font-medium text-foreground">Requested OAuth scopes</p>
                              <span className="text-[11px] text-muted-foreground">{selectedConnectionServer.oauth_scopes.length} scope{selectedConnectionServer.oauth_scopes.length === 1 ? "" : "s"}</span>
                            </div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {selectedConnectionServer.oauth_scopes.map((scope) => (
                                <Badge key={scope} variant="outline" className="rounded-full px-2.5 py-0.5 text-[10px] border-border/60 text-muted-foreground">
                                  {formatOauthScopeLabel(scope)}
                                </Badge>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        <div className="mt-3 rounded-lg border border-border/60 bg-background/80 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-[11px] font-medium text-foreground">
                              {selectedConnectionServer.tool_names.length >= selectedConnectionServer.tools_count ? "Published tools" : "Published tool highlights"}
                            </p>
                            <span className="text-[11px] text-muted-foreground">{selectedConnectionServer.tools_count} total</span>
                          </div>
                          {selectedConnectionServer.tool_names.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {selectedConnectionServer.tool_names.map((toolName) => (
                                <Badge key={toolName} variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px]">
                                  {toolName}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <p className="mt-2 text-[11px] text-muted-foreground">
                              This registry entry reports the tool count, but the detailed tool catalog has not been published yet.
                            </p>
                          )}
                        </div>
                      </div>
                    ) : null}

                    {selectedConnectionServer?.auth_type === "oauth" ? (
                      <McpOAuthSessionCard
                        server={selectedConnectionServer}
                        connection={selectedConnection}
                        busy={oauthBusy}
                        onStart={() => void handleStartSelectedConnectionOAuth()}
                        onRefresh={() => void handleRefreshSelectedConnectionOAuth()}
                      />
                    ) : null}

                    {connectionFields.length > 0 ? (
                      <div className="grid gap-4 md:grid-cols-2">
                        {connectionFields.map((field) => {
                          const value = field.is_credential
                            ? (connectionDraft.credentials[field.key] ?? "")
                            : (connectionDraft.config[field.key] ?? "");
                          const configured = selectedConnection?.credential_metadata.find((item) => item.key === field.key)?.configured;
                          const onChange = (nextValue: string) => {
                            if (field.is_credential) {
                              setConnectionDraft((current) => ({
                                ...current,
                                credentials: { ...current.credentials, [field.key]: nextValue },
                              }));
                              return;
                            }
                            setConnectionDraft((current) => ({
                              ...current,
                              config: { ...current.config, [field.key]: nextValue },
                            }));
                          };
                          return (
                            <div key={field.key} className={`space-y-1.5 ${field.type === "textarea" ? "md:col-span-2" : ""}`}>
                              <Label className="text-xs">{field.label}</Label>
                              {field.type === "textarea" ? (
                                <Textarea
                                  rows={4}
                                  value={value}
                                  onChange={(event) => onChange(event.target.value)}
                                  placeholder={field.placeholder}
                                />
                              ) : (
                                <Input
                                  type={field.type === "password" ? "password" : "text"}
                                  value={value}
                                  onChange={(event) => onChange(event.target.value)}
                                  placeholder={field.placeholder}
                                />
                              )}
                              <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                                {field.required ? <span>Required</span> : <span>Optional</span>}
                                {field.is_credential && configured ? <span>Stored in secret</span> : null}
                                {field.help ? <span>{field.help}</span> : null}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : selectedConnectionServer ? (
                      <div className="rounded-xl border border-dashed border-border/70 bg-background/40 px-3 py-4 text-sm text-muted-foreground">
                        This connection does not require extra fields. Save it directly or validate it now.
                      </div>
                    ) : null}

                    <div className="flex flex-wrap gap-2">
                      <Button onClick={() => void handleSaveConnection(false)} disabled={connectionBusy || oauthBusy || !connectionDraft.serverId.trim()}>
                        Save connection
                      </Button>
                      <Button variant="outline" onClick={() => void handleSaveConnection(true)} disabled={connectionBusy || oauthBusy || !connectionDraft.serverId.trim()}>
                        Save + validate
                      </Button>
                      <Button variant="outline" onClick={() => void handleValidateSelectedConnection()} disabled={connectionBusy || oauthBusy || !selectedConnectionId}>
                        Validate now
                      </Button>
                      <Button variant="outline" onClick={() => handleStartNewConnection()} disabled={connectionBusy || oauthBusy}>
                        Reset draft
                      </Button>
                      <Button variant="destructive" onClick={() => void handleDeleteSelectedConnection()} disabled={connectionBusy || oauthBusy || !selectedConnectionId}>
                        Delete
                      </Button>
                    </div>

                    {selectedConnection ? (
                      <div className="rounded-2xl border border-border/60 bg-muted/15 p-3 shadow-sm shadow-black/5">
                        <p className="text-xs font-medium text-foreground">Credential metadata</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {selectedConnection.credential_metadata.length > 0 ? selectedConnection.credential_metadata.map((field) => (
                            <Badge key={field.key} variant="outline" className="text-[10px]">
                              {field.label}: {field.configured ? "configured" : "not set"}
                            </Badge>
                          )) : <span className="text-xs text-muted-foreground">No credential fields for this registry server.</span>}
                        </div>
                        {selectedConnection.validation.message ? (
                          <p className="mt-3 text-xs text-muted-foreground">{selectedConnection.validation.message}</p>
                        ) : null}
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </div>

              <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">Agent bindings</CardTitle>
                  <CardDescription>See which agents currently depend on the selected saved connection.</CardDescription>
                </CardHeader>
                <CardContent>
                  {!selectedConnection ? (
                    <p className="text-sm text-muted-foreground">Select a saved connection to inspect current bindings.</p>
                  ) : connectionBindings.length === 0 ? (
                    <p className="text-sm text-muted-foreground">This saved connection is not bound to any agents yet.</p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {connectionBindings.map((binding) => (
                        <Badge key={`${binding.namespace}-${binding.agent_name}`} variant="outline" className="px-3 py-1 text-xs">
                          {binding.namespace}/{binding.agent_name}
                        </Badge>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

          {/* ── Profiles Tab ── */}
          <TabsContent value="profiles" className="animate-fade-in space-y-5">
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardContent className="space-y-2 p-5">
                <h2 className="text-base font-semibold text-foreground">Curated MCP Profiles</h2>
                <p className="text-sm leading-6 text-muted-foreground">
                  Pre-configured server bundles for common workflows. Apply a profile when creating an agent to instantly equip it with the right tools.
                </p>
              </CardContent>
            </Card>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {profiles.map((profile) => (
                <McpProfileCard key={profile.id} profile={profile} />
              ))}
            </div>
          </TabsContent>

          {/* ── Architecture Tab ── */}
          <TabsContent value="architecture" className="animate-fade-in space-y-5">
            <div className="grid gap-6 lg:grid-cols-2">
              <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-sky-500/25 bg-sky-500/10 text-sky-500">
                      <Globe className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Remote MCP Servers</CardTitle>
                      <CardDescription>Zero container overhead</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-muted-foreground">
                  <p>
                    Vendor-hosted services accessed over HTTPS. The agent runtime connects directly via streamable HTTP transport. No pods, no images, just an API key.
                  </p>
                  <div className="rounded-xl border border-border/60 bg-background/60 p-3 font-mono text-xs">
                    <span className="text-sky-400">Agent Pod</span> → <span className="text-muted-foreground">HTTPS</span> → <span className="text-sky-400">api.github.com/mcp</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary" className="text-[10px]">GitHub</Badge>
                    <Badge variant="secondary" className="text-[10px]">Context7</Badge>
                    <Badge variant="secondary" className="text-[10px]">Brave Search</Badge>
                    <Badge variant="secondary" className="text-[10px]">Azure</Badge>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-violet-500/25 bg-violet-500/10 text-violet-500">
                      <Server className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Hub Servers</CardTitle>
                      <CardDescription>Shared across all agents</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-muted-foreground">
                  <p>
                    Centrally deployed in the <code className="rounded bg-muted px-1.5 py-0.5 text-xs">mcp-hub</code> namespace. One instance serves all agents through the operator-managed NetworkPolicy. Ideal for shared databases and internal APIs.
                  </p>
                  <div className="rounded-xl border border-border/60 bg-background/60 p-3 font-mono text-xs">
                    <span className="text-violet-400">Agent Pod</span> → <span className="text-muted-foreground">ClusterIP</span> → <span className="text-violet-400">github.mcp-hub.svc:8080</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary" className="text-[10px]">GitHub Hub</Badge>
                    <Badge variant="secondary" className="text-[10px]">PostgreSQL</Badge>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-amber-500/25 bg-amber-500/10 text-amber-500">
                      <Box className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Sidecar Containers</CardTitle>
                      <CardDescription>Per-agent pod isolation</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-muted-foreground">
                  <p>
                    Run inside the agent's own pod as additional containers. Full isolation with localhost-only networking. Best for browser automation, local filesystem, and compute-intensive tasks.
                  </p>
                  <div className="rounded-xl border border-border/60 bg-background/60 p-3 font-mono text-xs">
                    <span className="text-amber-400">Agent Container</span> → <span className="text-muted-foreground">localhost:8093</span> → <span className="text-amber-400">Playwright Sidecar</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary" className="text-[10px]">Playwright</Badge>
                    <Badge variant="secondary" className="text-[10px]">Filesystem</Badge>
                    <Badge variant="secondary" className="text-[10px]">Docker</Badge>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-emerald-500/25 bg-emerald-500/10 text-emerald-500">
                      <Shield className="h-4 w-4" />
                    </div>
                    <div>
                      <CardTitle className="text-sm">Security Model</CardTitle>
                      <CardDescription>Per-agent NetworkPolicy enforcement</CardDescription>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-muted-foreground">
                  <p>
                    Each agent gets a Kubernetes NetworkPolicy restricting egress to only its declared MCP servers. Sidecar traffic stays on localhost. Hub traffic uses Kubernetes service DNS. Remote traffic is allowed to specific external endpoints.
                  </p>
                  <ul className="space-y-1.5 list-disc list-inside text-xs">
                    <li>Agent policies gate <code className="rounded bg-muted px-1 py-0.5">allowed_mcp_servers</code></li>
                    <li>HITL toggle per policy for tool approval</li>
                    <li>Credentials stored as Kubernetes Secrets</li>
                    <li>gVisor sandbox optional for untrusted workloads</li>
                  </ul>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </ScrollArea>
  );
}

function McpOAuthSessionCard({
  server,
  connection,
  busy,
  onStart,
  onRefresh,
}: {
  server: McpRegistryServer;
  connection: McpConnection | null;
  busy: boolean;
  onStart: () => void;
  onRefresh: () => void;
}) {
  const oauth = connection?.oauth ?? null;
  const expiryLabel = formatOauthExpiry(oauth?.expires_at);

  return (
    <div className="rounded-2xl border border-border/60 bg-background/75 p-4 shadow-sm shadow-black/5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border/60 bg-background/80 text-foreground/80">
            <Link2 className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-foreground">OAuth session</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {!server.attachable
                ? "This provider still needs extra OAuth support before agents can attach it. Keep the saved connection as a draft for now."
                : !connection
                  ? "Save the connection first, then complete the browser sign-in once to store the runtime token on this namespace-scoped connection."
                  : oauth?.state === "connected"
                    ? "The saved connection has a usable OAuth token. Reconnect if you need a different account or refresh if the provider issues renewable sessions."
                    : oauth?.state === "expired"
                      ? "The saved OAuth session expired. Refresh it if a refresh token is available, or reconnect through the browser sign-in flow."
                      : "This saved connection still needs a browser-based OAuth sign-in before it can be attached to agents."}
            </p>
          </div>
        </div>
        {server.attachable ? (
          <Badge variant="outline" className={`text-[10px] ${OAUTH_STATE_STYLES[oauth?.state ?? "required"]}`}>
            {formatOauthStateLabel(oauth?.state ?? "required")}
          </Badge>
        ) : null}
      </div>

      {oauth?.scope.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {oauth.scope.map((scope) => (
            <Badge key={scope} variant="outline" className="rounded-full px-2.5 py-0.5 text-[10px] border-border/60 text-muted-foreground">
              {formatOauthScopeLabel(scope)}
            </Badge>
          ))}
        </div>
      ) : null}

      {expiryLabel ? (
        <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
          <span>Current token expiry: {expiryLabel}</span>
        </div>
      ) : null}

      {connection?.binding_count ? (
        <p className="mt-3 text-[11px] leading-5 text-muted-foreground">
          Refreshing or reconnecting restarts bound agents so they pick up the updated token.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {connection && server.attachable ? (
          <>
            <Button onClick={onStart} disabled={busy} className="gap-1.5">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Link2 className="h-3.5 w-3.5" />}
              {oauth?.connected ? "Reconnect OAuth" : "Connect OAuth"}
            </Button>
            {oauth?.refresh_available ? (
              <Button variant="outline" onClick={onRefresh} disabled={busy} className="gap-1.5">
                <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
                Refresh session
              </Button>
            ) : null}
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-border/70 bg-background/40 px-3 py-2 text-[11px] text-muted-foreground">
            {server.attachable ? "Save this connection before launching OAuth." : "OAuth actions will appear here once this provider is attachable."}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Server Card ── */

function McpServerCard({
  server,
  isSelected,
  onSelect,
}: {
  server: McpRegistryServer;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const transport = TRANSPORT_STYLES[server.transport];
  const categoryStyle = CATEGORY_COLORS[server.category] ?? CATEGORY_STYLE;
  const isDeferred = server.support_level !== "ready";

  return (
    <Card
      className={`group cursor-pointer overflow-hidden transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg ${
        isSelected
          ? "border-primary/35 bg-primary/5 ring-1 ring-primary/20 shadow-md shadow-primary/10"
          : isDeferred
            ? "border-border/60 bg-background/70 hover:border-border/80"
            : "border-border/60 bg-background/80 hover:border-primary/20"
      }`}
      onClick={onSelect}
    >
      <CardContent className="space-y-4 p-4">
        <div className="flex items-start gap-3">
          <McpServerBadgeIcon
            serverId={server.id}
            serverName={server.name}
            transport={server.transport}
            iconName={server.icon}
            size="sm"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-sm text-foreground truncate">{server.name}</h3>
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${transport.bg} ${transport.color} ${transport.border}`}>
                {transport.label}
              </Badge>
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${SUPPORT_STYLES[server.support_level]}`}>
                {formatSupportLabel(server.support_level)}
              </Badge>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground line-clamp-2">{server.description}</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline" className={`text-[10px] ${categoryStyle}`}>{server.category}</Badge>
            {server.auth_type !== "none" && (
              <Badge variant="outline" className="text-[10px] border-border/60">{server.auth_type}</Badge>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Wrench className="h-3 w-3" />
            <span className="tabular-nums">{server.tools_count} tools</span>
          </div>
        </div>

        {server.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {server.tags.slice(0, 4).map((tag) => (
              <span key={tag} className="rounded-full bg-muted/60 px-2 py-0.5 text-[10px] text-muted-foreground">
                {tag}
              </span>
            ))}
            {server.tags.length > 4 && (
              <span className="rounded-full bg-muted/60 px-2 py-0.5 text-[10px] text-muted-foreground">
                +{server.tags.length - 4}
              </span>
            )}
          </div>
        )}

        {server.tool_names.length > 0 && (
          <div className="rounded-xl border border-border/50 bg-background/50 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Tool preview</p>
              <span className="text-[10px] text-muted-foreground">
                {server.tool_names.length >= server.tools_count ? "Full list" : `${server.tool_names.length} shown`}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {server.tool_names.slice(0, 5).map((toolName) => (
                <Badge key={toolName} variant="secondary" className="rounded-full px-2 py-0.5 text-[10px]">
                  {toolName}
                </Badge>
              ))}
              {server.tool_names.length > 5 && (
                <Badge variant="outline" className="rounded-full px-2 py-0.5 text-[10px]">
                  +{server.tool_names.length - 5} more
                </Badge>
              )}
            </div>
          </div>
        )}

        {server.status_reason && (
          <p className="text-[11px] leading-5 text-muted-foreground line-clamp-2">{server.status_reason}</p>
        )}
      </CardContent>
    </Card>
  );
}

/* ── Server Detail Panel ── */

function McpServerDetail({
  server,
  onClose,
  onCreateConnection,
}: {
  server: McpRegistryServer;
  onClose: () => void;
  onCreateConnection: (serverId?: string) => void;
}) {
  const transport = TRANSPORT_STYLES[server.transport];
  const hasFullToolCatalog = server.tool_names.length >= server.tools_count;
  const authPreview = buildAuthPreview(server);

  return (
    <Card className="animate-fade-in border-border/60 bg-background/90 shadow-xl shadow-black/10">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <McpServerBadgeIcon
              serverId={server.id}
              serverName={server.name}
              transport={server.transport}
              iconName={server.icon}
              size="md"
            />
            <div>
              <CardTitle className="text-base">{server.name}</CardTitle>
              <CardDescription>{server.description}</CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {server.attachable ? (
              <Button size="sm" onClick={() => onCreateConnection(server.id)} className="text-xs">
                Create saved connection
              </Button>
            ) : null}
            <Button variant="ghost" size="sm" onClick={onClose} className="text-xs">
              Close
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Transport</p>
            <p className={`mt-1 font-medium ${transport.color}`}>{transport.label}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Protocol</p>
            <p className="mt-1 font-medium text-foreground">{getProtocolLabel(server)}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Readiness</p>
            <Badge variant="outline" className={`mt-2 ${SUPPORT_STYLES[server.support_level]}`}>
              {formatSupportLabel(server.support_level)}
            </Badge>
          </div>
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Authentication</p>
            <p className="mt-1 font-medium text-foreground">{formatAuthLabel(server.auth_type)}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Tools</p>
            <p className="mt-1 font-medium text-foreground">{server.tools_count}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Category</p>
            <p className="mt-1 font-medium text-foreground capitalize">{server.category.replace("-", " ")}</p>
          </div>
        </div>

        <div className="rounded-xl border border-border/60 bg-background/60 p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Connection model</p>
              <p className="mt-1 text-sm font-medium text-foreground">{getDeploymentModelLabel(server)}</p>
              {server.connection_notes ? (
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{server.connection_notes}</p>
              ) : null}
            </div>
            {(server.docs_url || server.repository_url) ? (
              <div className="flex flex-wrap gap-2">
                {server.docs_url ? <RegistryLinkButton href={server.docs_url} label="Official docs" /> : null}
                {server.repository_url ? <RegistryLinkButton href={server.repository_url} label="Source repo" /> : null}
              </div>
            ) : null}
          </div>
        </div>

        {server.endpoint && (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70 mb-1">Registry endpoint</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-muted px-2 py-1 text-xs font-mono">{server.endpoint}</code>
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Saved connections prefill this value automatically. You usually only add credentials on top.
            </p>
          </div>
        )}

        {!server.endpoint && server.transport === "remote" && server.suggested_endpoint && (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="mb-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Suggested endpoint</p>
            <code className="block rounded bg-muted px-2 py-1 text-xs font-mono text-foreground">{server.suggested_endpoint}</code>
            <p className="text-xs leading-5 text-muted-foreground">
              This example comes from the published docs for self-hosted use. Replace it if your deployment exposes the MCP URL somewhere else.
            </p>
          </div>
        )}

        {!server.endpoint && server.transport === "remote" && !server.suggested_endpoint && (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="mb-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Endpoint</p>
            <p className="text-xs leading-5 text-muted-foreground">
              No default endpoint is published for this MCP. Create a saved connection only if you run your own remote deployment and can provide its MCP URL.
            </p>
          </div>
        )}

        {authPreview ? (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70 mb-1">{authPreview.label}</p>
            <code className="block rounded bg-muted px-2 py-1 text-xs font-mono text-foreground">{authPreview.value}</code>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">{authPreview.help}</p>
          </div>
        ) : null}

        {server.auth_type === "oauth" && server.oauth_scopes?.length ? (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Requested OAuth scopes</p>
              <span className="text-[10px] text-muted-foreground">{server.oauth_scopes.length} total</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {server.oauth_scopes.map((scope) => (
                <Badge key={scope} variant="outline" className="rounded-full px-2.5 py-0.5 text-[10px] border-border/60 text-muted-foreground">
                  {formatOauthScopeLabel(scope)}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}

        {server.sidecar_image && (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70 mb-1">Managed Sidecar Runtime</p>
            <p className="text-sm font-medium text-foreground">{formatContainerImageDisplay(server.sidecar_image)}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              KubeSynth provides the default sidecar build for this toolkit. Override the image only when you need a custom runtime.
              {server.sidecar_port ? ` The default pod-local port is ${server.sidecar_port}.` : ""}
            </p>
          </div>
        )}

        {server.status_reason && (
          <div className="rounded-xl border border-border/60 bg-background/60 p-3">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70 mb-1">Current support</p>
            <p className="text-xs leading-5 text-muted-foreground">{server.status_reason}</p>
          </div>
        )}

        <div className="rounded-xl border border-border/60 bg-background/60 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
              {hasFullToolCatalog ? "Published Tools" : "Published Tool Highlights"}
            </p>
            <span className="text-[11px] text-muted-foreground">{server.tools_count} total</span>
          </div>
          {server.tool_names.length > 0 ? (
            <ScrollArea className="mt-3 max-h-40 pr-3">
              <div className="flex flex-wrap gap-1.5">
                {server.tool_names.map((toolName) => (
                  <Badge key={toolName} variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px]">
                    {toolName}
                  </Badge>
                ))}
              </div>
            </ScrollArea>
          ) : (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              This registry entry reports the number of tools, but the detailed tool catalog is not published in the registry metadata yet.
            </p>
          )}
        </div>

        {server.config_schema && server.config_schema.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-foreground">Configuration required</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {server.config_schema.map((field) => (
                <div key={field.key} className="rounded-xl border border-border/60 bg-background/60 p-3">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-medium text-foreground">{field.label}</p>
                    {field.required && <Badge variant="destructive" className="text-[9px] px-1 py-0">Required</Badge>}
                    {field.is_credential && <Badge variant="outline" className="text-[9px] px-1 py-0">Secret</Badge>}
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{field.type} • {field.group ?? "general"}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {server.tags.map((tag) => (
            <Badge key={tag} variant="secondary" className="rounded-full px-2.5 py-0.5 text-[10px]">{tag}</Badge>
          ))}
        </div>

        <Separator />
        <div className="text-xs text-muted-foreground">
          <p>
            <strong>How to use:</strong>{" "}
            {!server.attachable && "Keep this entry as a catalog reference for now. It should not be attached to agents until the remaining MCP management and runtime work lands."}
            {server.attachable && server.transport === "hub" && "This server is attachable through the shared mcp-hub namespace. Create a saved connection for it, then attach that connection to an agent when you want the hub route available."}
            {server.attachable && server.transport === "sidecar" && "This server will be deployed as a container in the agent's pod. Create a saved connection for it, then attach that connection to the agent so the sidecar launches automatically."}
            {server.attachable && server.transport === "remote" && (server.endpoint
              ? "This server is modeled as a direct remote MCP endpoint. Saved connections default to the published registry URL; add credentials or connection-specific overrides only when needed."
              : "This server is modeled as a self-hosted remote MCP integration. Create a saved connection only if you operate your own deployment and can provide its MCP endpoint URL.")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Profile Card ── */

function McpProfileCard({ profile }: { profile: McpProfile }) {
  const colors = PROFILE_COLORS[profile.color] ?? PROFILE_COLORS.sky;
  const Icon = resolveIcon(profile.icon);

  return (
    <Card className={`${colors.border} ${colors.bg} border bg-background/80 shadow-sm shadow-black/5 transition-all hover:-translate-y-0.5 hover:shadow-lg`}>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-start gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${colors.border} bg-background/80`}>
            <Icon className={`h-5 w-5 ${colors.accent}`} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold text-sm text-foreground">{profile.name}</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{profile.description}</p>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-border/40 bg-background/60 p-2 text-center">
            <p className="text-lg font-bold tabular-nums text-foreground">{profile.resolved_servers.length}</p>
            <p className="text-[10px] text-muted-foreground">Servers</p>
          </div>
          <div className="rounded-lg border border-border/40 bg-background/60 p-2 text-center">
            <p className="text-lg font-bold tabular-nums text-foreground">{profile.total_tools}</p>
            <p className="text-[10px] text-muted-foreground">Tools</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline" className={`text-[10px] px-2 py-0.5 ${SUPPORT_STYLES[profile.support_level]}`}>
            {profile.attachable_servers.length}/{profile.resolved_servers.length} attachable now
          </Badge>
          {profile.blocked_servers.length > 0 && (
            <Badge variant="outline" className="text-[10px] px-2 py-0.5 border-amber-500/20 bg-amber-500/5 text-amber-500">
              {profile.blocked_servers.length} blocked
            </Badge>
          )}
        </div>

        <div className="space-y-2">
          <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">Included servers</p>
          <div className="flex flex-wrap gap-1.5">
            {profile.resolved_servers.map((s) => {
              const tStyle = TRANSPORT_STYLES[s.transport];
              return (
                <Badge
                  key={s.id}
                  variant="outline"
                  className={`text-[10px] px-2 py-0.5 ${tStyle.bg} ${tStyle.color} ${tStyle.border}`}
                >
                  {s.name}
                </Badge>
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap gap-1">
          {profile.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-background/60 px-2 py-0.5 text-[10px] text-muted-foreground">{tag}</span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
