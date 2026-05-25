import {
  Activity,
  AlertTriangle,
  BookOpen,
  Box,
  Brain,
  Cloud,
  Code,
  Database,
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
  Search,
  Server,
  Sparkles,
  Users,
} from "lucide-react";

import type { ConfigField, McpConnection, McpRegistryServer, McpTransport } from "@/types";

/* ── Icon mapping ── */

export const ICON_MAP: Record<string, typeof Code> = {
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

export function resolveIcon(iconName: string): typeof Code {
  return ICON_MAP[iconName] ?? Plug;
}

/* ── Transport styling ── */

export const CATEGORY_STYLE = "border-border/60 bg-background/75 text-foreground/70";
export const PROFILE_STYLE = {
  border: "border-amber-500/25",
  bg: "bg-amber-500/8",
  accent: "text-amber-500",
};

export const TRANSPORT_STYLES: Record<
  McpTransport,
  { label: string; color: string; bg: string; border: string }
> = {
  remote: { label: "Remote", color: "text-sky-500", bg: "bg-sky-500/10", border: "border-sky-500/25" },
  hub: { label: "Hub", color: "text-indigo-500", bg: "bg-indigo-500/10", border: "border-indigo-500/25" },
  sidecar: { label: "Sidecar", color: "text-amber-500", bg: "bg-amber-500/10", border: "border-amber-500/25" },
};

export const CATEGORY_COLORS: Record<string, string> = {
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

export const PROFILE_COLORS: Record<string, { border: string; bg: string; accent: string }> = {
  sky: PROFILE_STYLE,
  violet: PROFILE_STYLE,
  emerald: PROFILE_STYLE,
  amber: PROFILE_STYLE,
  rose: PROFILE_STYLE,
  fuchsia: PROFILE_STYLE,
};

export const SUPPORT_STYLES = {
  ready: "border-emerald-500/25 bg-emerald-500/10 text-emerald-500",
  limited: "border-amber-500/25 bg-amber-500/10 text-amber-500",
  planned: "border-border/60 bg-background/70 text-foreground/70",
} as const;

export const OAUTH_STATE_STYLES = {
  connected: "border-emerald-500/25 bg-emerald-500/10 text-emerald-500",
  expired: "border-amber-500/25 bg-amber-500/10 text-amber-500",
  required: "border-border/60 bg-background/70 text-foreground/70",
} as const;

export const VALIDATION_STYLES: Record<string, string> = {
  valid: "bg-emerald-500",
  warning: "bg-amber-500",
  invalid: "bg-red-500",
  draft: "bg-muted-foreground",
};

export function formatSupportLabel(level: McpRegistryServer["support_level"]): string {
  return level === "ready" ? "Ready now" : level === "limited" ? "Needs setup" : "Planned";
}

export function formatOauthStateLabel(state: "required" | "connected" | "expired"): string {
  return state === "connected" ? "OAuth connected" : state === "expired" ? "OAuth expired" : "OAuth required";
}

export function formatOauthScopeLabel(scope: string): string {
  return scope
    .replace(/^https?:\/\/www\.googleapis\.com\/auth\//, "google:")
    .replace(/^https?:\/\//, "")
    .replace(/^openid$/, "openid")
    .replace(/^profile$/, "profile")
    .replace(/^email$/, "email");
}

export function formatOauthExpiry(value?: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleString();
}

export function getProtocolLabel(server: Pick<McpRegistryServer, "protocol_label" | "transport">): string {
  if (server.protocol_label?.trim()) return server.protocol_label;
  if (server.transport === "remote") return "Streamable HTTP";
  if (server.transport === "hub") return "Cluster service HTTP";
  return "Pod-local HTTP";
}

export function getDeploymentModelLabel(
  server: Pick<McpRegistryServer, "deployment_model" | "transport" | "endpoint">,
): string {
  if (server.deployment_model?.trim()) return server.deployment_model;
  if (server.transport === "remote") return server.endpoint ? "Vendor-hosted remote" : "Self-hosted remote";
  if (server.transport === "hub") return "Shared hub service";
  return "Per-agent sidecar";
}

export function formatAuthLabel(authType: McpRegistryServer["auth_type"]): string {
  if (authType === "none") return "None required";
  return authType.replace(/_/g, " ");
}

export function buildAuthPreview(
  server: Pick<
    McpRegistryServer,
    | "auth_type"
    | "auth_header_name"
    | "auth_header_prefix"
    | "config_schema"
    | "attachable"
    | "oauth_scopes"
  >,
): { label: string; value: string; help: string } | null {
  if (server.auth_type === "none") return null;

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

  const headerName =
    server.auth_header_name?.trim() ||
    (server.auth_type === "bearer" ? "Authorization" : server.auth_type === "api_key" ? "X-API-Key" : "");
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
    help: "Store the secret on the saved connection. kubesynapse passes it to the runtime without exposing it in agent specs.",
  };
}

/* ── Connection helpers ── */

export interface McpConnectionDraft {
  id: string | null;
  name: string;
  serverId: string;
  config: Record<string, string>;
  credentials: Record<string, string>;
}

export function normalizeConnectionName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function buildSuggestedConnectionName(
  server: McpRegistryServer | null,
  connections: McpConnection[],
  currentId?: string | null,
): string {
  if (!server) return "";

  const baseName = server.name.trim() || server.id;
  const usedNames = new Set(
    connections
      .filter((connection) => connection.id !== currentId)
      .map((connection) => normalizeConnectionName(connection.name))
      .filter(Boolean),
  );

  const normalizedBase = normalizeConnectionName(baseName);
  if (!normalizedBase || !usedNames.has(normalizedBase)) return baseName;

  let suffix = 2;
  while (usedNames.has(normalizeConnectionName(`${baseName} ${suffix}`))) {
    suffix += 1;
  }
  return `${baseName} ${suffix}`;
}

export function resolveEffectiveRemoteEndpoint(
  server: McpRegistryServer | null,
  config: Record<string, string>,
): string | null {
  if (!server || server.transport !== "remote") return null;
  const configuredEndpoint = String(config.endpoint_url ?? "").trim();
  if (configuredEndpoint) return configuredEndpoint;
  const registryEndpoint = String(server.endpoint ?? "").trim();
  return registryEndpoint || null;
}

export function buildConnectionFields(server: McpRegistryServer | null): ConfigField[] {
  if (!server) return [];
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

export function draftFromConnection(connection: McpConnection): McpConnectionDraft {
  return {
    id: connection.id,
    name: connection.name,
    serverId: connection.server_id,
    config: Object.fromEntries(Object.entries(connection.config ?? {}).map(([key, value]) => [key, String(value ?? "")])),
    credentials: {},
  };
}

export function trimRecordValues(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(values)
      .map(([key, value]) => [key, value.trim()])
      .filter(([, value]) => value.length > 0),
  );
}

/* ── Validation label ── */

export function formatValidationLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}
