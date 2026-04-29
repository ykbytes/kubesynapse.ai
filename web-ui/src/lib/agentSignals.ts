import {
  Activity,
  Bot,
  Brain,
  Cloud,
  Code,
  Database,
  FileText,
  GitBranch,
  Globe,
  LayoutList,
  Mail,
  Monitor,
  Palette,
  Radar,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { ALPHA_RUNTIMES, type AgentMcpConnection, type GitConfig, type GitHubConfig, type RuntimeKind } from "@/types";

export interface AgentSignalSource {
  runtime_kind?: RuntimeKind | null;
  mcp_connections?: AgentMcpConnection[];
  mcp_sidecars?: Array<Record<string, unknown>>;
  mcp_servers?: string[];
  policy_ref?: string | null;
  enable_gvisor?: boolean;
  git_config?: GitConfig | null;
  github_config?: GitHubConfig | null;
}

export interface AgentRuntimeSignal {
  id: RuntimeKind | "unknown";
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  tone: string;
  alpha: boolean;
}

export interface AgentCapabilitySignal {
  id: string;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  tone: string;
  priority: number;
}

export interface AgentAccessSignal {
  label: string;
  description: string;
  icon: LucideIcon;
  tone: string;
}

export interface AgentVisualSignals {
  runtime: AgentRuntimeSignal;
  access: AgentAccessSignal;
  capabilities: AgentCapabilitySignal[];
}

const UNKNOWN_RUNTIME_TONE = "border-border/60 bg-background/60 text-muted-foreground";
const FALLBACK_CAPABILITY_TONE = "border-border/60 bg-background/70 text-muted-foreground";

const RUNTIME_META: Record<RuntimeKind, Omit<AgentRuntimeSignal, "id" | "alpha">> = {
  opencode: {
    label: "OpenCode",
    shortLabel: "OpenCode",
    icon: Code,
    tone: "border-emerald-500/20 bg-emerald-500/5 text-emerald-200",
  },
  pi: {
    label: "Pi",
    shortLabel: "Pi",
    icon: Code,
    tone: "border-violet-500/20 bg-violet-500/5 text-violet-200",
  },
};

const CAPABILITY_META: Record<string, Omit<AgentCapabilitySignal, "id">> = {
  kubernetes: {
    label: "Kubernetes",
    shortLabel: "Kube",
    icon: Server,
    tone: "border-sky-500/20 bg-sky-500/5 text-sky-200",
    priority: 100,
  },
  "code-exec": {
    label: "Code Exec",
    shortLabel: "Code",
    icon: Code,
    tone: "border-amber-500/20 bg-amber-500/5 text-amber-200",
    priority: 96,
  },
  database: {
    label: "Database",
    shortLabel: "DB",
    icon: Database,
    tone: "border-teal-500/20 bg-teal-500/5 text-teal-200",
    priority: 88,
  },
  git: {
    label: "Git",
    shortLabel: "Git",
    icon: GitBranch,
    tone: "border-emerald-500/20 bg-emerald-500/5 text-emerald-200",
    priority: 86,
  },
  github: {
    label: "GitHub",
    shortLabel: "GitHub",
    icon: GitBranch,
    tone: "border-zinc-500/20 bg-zinc-500/5 text-zinc-200",
    priority: 84,
  },
  "github-adapter": {
    label: "GitHub",
    shortLabel: "GitHub",
    icon: GitBranch,
    tone: "border-zinc-500/20 bg-zinc-500/5 text-zinc-200",
    priority: 84,
  },
  cloud: {
    label: "Cloud",
    shortLabel: "Cloud",
    icon: Cloud,
    tone: "border-cyan-500/20 bg-cyan-500/5 text-cyan-200",
    priority: 83,
  },
  "project-management": {
    label: "Projects",
    shortLabel: "Projects",
    icon: LayoutList,
    tone: "border-indigo-500/20 bg-indigo-500/5 text-indigo-200",
    priority: 82,
  },
  browser: {
    label: "Browser",
    shortLabel: "Browser",
    icon: Monitor,
    tone: "border-slate-500/20 bg-slate-500/5 text-slate-200",
    priority: 80,
  },
  documents: {
    label: "Docs",
    shortLabel: "Docs",
    icon: FileText,
    tone: "border-orange-500/20 bg-orange-500/5 text-orange-200",
    priority: 78,
  },
  "web-search": {
    label: "Web Search",
    shortLabel: "Search",
    icon: Globe,
    tone: "border-blue-500/20 bg-blue-500/5 text-blue-200",
    priority: 76,
  },
  rag: {
    label: "RAG",
    shortLabel: "RAG",
    icon: Brain,
    tone: "border-fuchsia-500/20 bg-fuchsia-500/5 text-fuchsia-200",
    priority: 74,
  },
  messaging: {
    label: "Messaging",
    shortLabel: "Msg",
    icon: Mail,
    tone: "border-violet-500/20 bg-violet-500/5 text-violet-200",
    priority: 72,
  },
  observability: {
    label: "Observability",
    shortLabel: "Observe",
    icon: Activity,
    tone: "border-teal-500/20 bg-teal-500/5 text-teal-200",
    priority: 71,
  },
  collector: {
    label: "Intel",
    shortLabel: "Intel",
    icon: Radar,
    tone: "border-lime-500/20 bg-lime-500/5 text-lime-200",
    priority: 68,
  },
  design: {
    label: "Design",
    shortLabel: "Design",
    icon: Palette,
    tone: "border-rose-500/20 bg-rose-500/5 text-rose-200",
    priority: 66,
  },
  "shared-mcp": {
    label: "Shared MCP",
    shortLabel: "MCP",
    icon: Sparkles,
    tone: "border-slate-500/20 bg-slate-500/5 text-slate-200",
    priority: 60,
  },
};

const MCP_CAPABILITY_ALIASES: Record<string, string> = {
  "aws-kb-retrieval": "cloud",
  "azure-mcp": "cloud",
  "brave-search": "web-search",
  context7: "documents",
  datadog: "observability",
  discord: "messaging",
  exa: "web-search",
  figma: "design",
  firecrawl: "web-search",
  gmail: "messaging",
  github_hub: "github",
  github_remote: "github",
  "github-hub": "github",
  "github-remote": "github",
  grafana: "observability",
  linear: "project-management",
  "memory-sidecar": "rag",
  "microsoft-learn": "documents",
  "netdata-cloud": "observability",
  notion: "documents",
  "notion-remote": "documents",
  "playwright-sidecar": "browser",
  "postgres-hub": "database",
  "puppeteer-sidecar": "browser",
  qdrant: "database",
  sentry: "observability",
  "sentry-remote": "observability",
  slack: "messaging",
  tavily: "web-search",
  "atlassian-rovo": "project-management",
};

function humanizeCapabilityId(id: string): string {
  return id
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function readSidecarName(sidecar: Record<string, unknown>): string {
  const rawName = sidecar.name;
  return typeof rawName === "string" ? rawName.trim() : "";
}

function normalizeCapabilityToken(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function resolveOpenCapabilityId(value: string): string {
  const normalized = normalizeCapabilityToken(value);
  if (!normalized) return "";
  return MCP_CAPABILITY_ALIASES[normalized] ?? normalized;
}

function resolveMcpCapabilityId(value: string): string {
  const resolved = resolveOpenCapabilityId(value);
  if (!resolved) return "";
  return CAPABILITY_META[resolved] ? resolved : "shared-mcp";
}

export function getRuntimeSignal(runtimeKind?: RuntimeKind | null): AgentRuntimeSignal {
  if (!runtimeKind) {
    return {
      id: "unknown",
      label: "Unknown runtime",
      shortLabel: "Unknown",
      icon: Bot,
      tone: UNKNOWN_RUNTIME_TONE,
      alpha: false,
    };
  }

  const meta = RUNTIME_META[runtimeKind];
  return {
    id: runtimeKind,
    label: meta.label,
    shortLabel: meta.shortLabel,
    icon: meta.icon,
    tone: meta.tone,
    alpha: ALPHA_RUNTIMES.has(runtimeKind),
  };
}

export function getCapabilitySignal(id: string): AgentCapabilitySignal {
  const normalizedId = resolveOpenCapabilityId(id) || id.trim();
  const meta = CAPABILITY_META[normalizedId];
  if (meta) return { id: normalizedId, ...meta };
  const label = humanizeCapabilityId(normalizedId || "tool");
  return {
    id: normalizedId,
    label,
    shortLabel: label,
    icon: Wrench,
    tone: FALLBACK_CAPABILITY_TONE,
    priority: 40,
  };
}

export function extractMcpCapabilityIds(source: AgentSignalSource): string[] {
  const ids = new Set<string>();

  for (const sidecar of source.mcp_sidecars ?? []) {
    const sidecarName = readSidecarName(sidecar);
    const resolvedSidecarName = resolveOpenCapabilityId(sidecarName);
    if (resolvedSidecarName) ids.add(resolvedSidecarName);
  }

  for (const serverName of source.mcp_servers ?? []) {
    const resolvedServerName = resolveMcpCapabilityId(serverName);
    if (resolvedServerName) ids.add(resolvedServerName);
  }

  for (const connection of source.mcp_connections ?? []) {
    const resolvedConnectionId = resolveMcpCapabilityId(connection.server_id || connection.server_name || connection.name);
    if (resolvedConnectionId) ids.add(resolvedConnectionId);
  }

  return [...ids];
}

export function extractAgentCapabilityIds(source: AgentSignalSource): string[] {
  const ids = new Set<string>(extractMcpCapabilityIds(source));

  if (source.github_config) ids.add("github");
  if (source.git_config?.repo_url?.trim()) ids.add("git");

  return [...ids];
}

export function getAccessSignal(source: AgentSignalSource): AgentAccessSignal {
  const capabilityIds = new Set(extractAgentCapabilityIds(source));
  const hasMcpAttachments = extractMcpCapabilityIds(source).length > 0;
  const hasElevatedAccess = capabilityIds.has("kubernetes") || capabilityIds.has("code-exec");
  const hasConnectedSystems = hasElevatedAccess || hasMcpAttachments || capabilityIds.has("database") || capabilityIds.has("git") || capabilityIds.has("github") || capabilityIds.has("github-adapter");

  if (hasElevatedAccess) {
    return {
      label: "Elevated",
      description: "Cluster or execution access attached",
      icon: ShieldAlert,
      tone: "border-amber-500/20 bg-amber-500/5 text-amber-200",
    };
  }

  if (hasConnectedSystems) {
    return {
      label: "Connected",
      description: "External systems are attached",
      icon: Shield,
      tone: "border-sky-500/20 bg-sky-500/5 text-sky-200",
    };
  }

  if ((source.policy_ref ?? "").trim() || source.enable_gvisor) {
    return {
      label: "Guarded",
      description: "Policy or sandbox protections are enabled",
      icon: ShieldCheck,
      tone: "border-emerald-500/20 bg-emerald-500/5 text-emerald-200",
    };
  }

  return {
    label: "Standard",
    description: "Core runtime without elevated attachments",
    icon: Shield,
    tone: UNKNOWN_RUNTIME_TONE,
  };
}

export function deriveAgentVisualSignals(source: AgentSignalSource): AgentVisualSignals {
  const capabilities = extractAgentCapabilityIds(source)
    .map((id) => getCapabilitySignal(id))
    .sort((left, right) => right.priority - left.priority || left.label.localeCompare(right.label));

  return {
    runtime: getRuntimeSignal(source.runtime_kind),
    access: getAccessSignal(source),
    capabilities,
  };
}