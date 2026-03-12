type JsonRecord = Record<string, unknown>;

export const MCP_SERVERS_PLACEHOLDER = "github\npostgres-readonly";

export const MCP_SIDECARS_PLACEHOLDER = `[
  {
    "name": "custom-http-adapter",
    "image": "your-registry.example.com/compatible-mcp-adapter:latest",
    "port": 8000
  }
]`;

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

export function formatMcpSidecarLabel(sidecar: Record<string, unknown>, index: number): string {
  const rawName = sidecar.name;
  const rawPort = sidecar.port;
  const rawImage = sidecar.image;

  const name = typeof rawName === "string" && rawName.trim() ? rawName.trim() : `sidecar-${index + 1}`;
  const port =
    typeof rawPort === "number" && Number.isFinite(rawPort)
      ? String(rawPort)
      : typeof rawPort === "string" && rawPort.trim()
        ? rawPort.trim()
        : "";
  const image = typeof rawImage === "string" && rawImage.trim() ? rawImage.trim() : "";

  if (port && image) {
    return `${name}:${port} · ${image}`;
  }
  if (port) {
    return `${name}:${port}`;
  }
  if (image) {
    return `${name} · ${image}`;
  }
  return name;
}