type JsonRecord = Record<string, unknown>;

const MCP_SERVER_BRAND_ICON_MAP: Record<string, string> = {
  "aws-kb-retrieval": "/mcp-icons/aws.ico",
  "azure-mcp": "/mcp-icons/azure.svg",
  "brave-search": "/mcp-icons/brave.svg",
  context7: "/mcp-icons/context7.ico",
  datadog: "/mcp-icons/datadog.svg",
  discord: "/mcp-icons/discord.svg",
  docker: "/mcp-icons/docker.svg",
  exa: "/mcp-icons/exa.png",
  figma: "/mcp-icons/figma.svg",
  firecrawl: "/mcp-icons/firecrawl.ico",
  gmail: "/mcp-icons/gmail.svg",
  grafana: "/mcp-icons/grafana.svg",
  "github-hub": "/mcp-icons/github.svg",
  "github-remote": "/mcp-icons/github.svg",
  "kubernetes-mcp": "/mcp-icons/kubernetes.svg",
  linear: "/mcp-icons/linear.svg",
  notion: "/mcp-icons/notion.svg",
  "playwright-sidecar": "/mcp-icons/playwright.svg",
  "postgres-hub": "/mcp-icons/postgresql.svg",
  puppeteer: "/mcp-icons/puppeteer.svg",
  "puppeteer-sidecar": "/mcp-icons/puppeteer.svg",
  qdrant: "/mcp-icons/qdrant.ico",
  sentry: "/mcp-icons/sentry.svg",
  slack: "/mcp-icons/slack.svg",
  sqlite: "/mcp-icons/sqlite.svg",
  tavily: "/mcp-icons/tavily.ico",
};

export const MCP_SERVERS_PLACEHOLDER = "github\npostgres-readonly";

export const MCP_SIDECARS_PLACEHOLDER = `[
  {
    "name": "custom-http-adapter",
    "image": "your-registry.example.com/compatible-mcp-adapter:latest",
    "port": 8000
  }
]`;

export function getMcpServerBrandIconPath(serverId: string): string | null {
  return MCP_SERVER_BRAND_ICON_MAP[serverId] ?? null;
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function stringifyMcpServers(servers: string[] | null | undefined): string {
  return (servers ?? [])
    .map((server) => server.trim())
    .filter(Boolean)
    .join("\n");
}

export function parseMcpServersText(text: string): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();

  for (const line of text.split(/\r?\n/)) {
    const value = line.trim();
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    normalized.push(value);
  }

  return normalized;
}

export function stringifyMcpSidecars(sidecars: Array<Record<string, unknown>> | null | undefined): string {
  if (!sidecars || sidecars.length === 0) {
    return "";
  }
  return JSON.stringify(sidecars, null, 2);
}

export function parseMcpSidecarsText(text: string): Array<Record<string, unknown>> {
  const trimmed = text.trim();
  if (!trimmed) {
    return [];
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error("MCP sidecars must be valid JSON.");
  }

  if (!Array.isArray(parsed) || parsed.some((item) => !isRecord(item))) {
    throw new Error("MCP sidecars must be a JSON array of objects.");
  }

  return parsed;
}

const MCP_IDENTIFIER_OVERRIDES: Record<string, string> = {
  ai: "AI",
  api: "API",
  llm: "LLM",
  mcp: "MCP",
  rag: "RAG",
  sql: "SQL",
};

function humanizeMcpIdentifier(value: string): string {
  const normalized = value.trim().replace(/^mcp[-_]/i, "");
  if (!normalized) {
    return "MCP Sidecar";
  }

  const parts = normalized.split(/[-_]+/).filter(Boolean);
  if (parts.length === 0) {
    return normalized;
  }

  return parts
    .map((part) => {
      const lower = part.toLowerCase();
      if (MCP_IDENTIFIER_OVERRIDES[lower]) {
        return MCP_IDENTIFIER_OVERRIDES[lower];
      }
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(" ");
}

function getImageAssetName(image: string): { name: string; tag: string } {
  const trimmed = image.trim();
  if (!trimmed) {
    return { name: "", tag: "" };
  }

  const withoutDigest = trimmed.split("@")[0] ?? trimmed;
  const lastSegment = withoutDigest.split("/").pop() ?? withoutDigest;
  const [name, tag] = lastSegment.split(":", 2);
  return { name: name ?? "", tag: tag ?? "" };
}

export function formatContainerImageDisplay(image: string): string {
  const { name, tag } = getImageAssetName(image);
  if (!name) {
    return "Managed sidecar";
  }

  const label = humanizeMcpIdentifier(name);
  if (!tag || tag === "latest" || tag.startsWith("deploy-")) {
    return label;
  }
  return `${label} (${tag})`;
}

export function formatMcpSidecarLabel(sidecar: Record<string, unknown>, index: number): string {
  const rawName = sidecar.name;
  const rawPort = sidecar.port;
  const rawImage = sidecar.image;

  const image = typeof rawImage === "string" && rawImage.trim() ? rawImage.trim() : "";
  const derivedImageName = getImageAssetName(image).name;
  const name = typeof rawName === "string" && rawName.trim() ? rawName.trim() : derivedImageName || `sidecar-${index + 1}`;
  const port =
    typeof rawPort === "number" && Number.isFinite(rawPort)
      ? String(rawPort)
      : typeof rawPort === "string" && rawPort.trim()
        ? rawPort.trim()
        : "";
  const label = humanizeMcpIdentifier(name);

  if (port) {
    return `${label} · Port ${port}`;
  }
  if (label) {
    return label;
  }
  if (image) {
    return formatContainerImageDisplay(image);
  }
  return `Sidecar ${index + 1}`;
}