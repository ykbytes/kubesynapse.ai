type GooseConfigFiles = Record<string, unknown>;

export const GOOSE_CONFIG_FILES_PLACEHOLDER = `{
  "config.yaml": "GOOSE_MODE: smart_approve\\nGOOSE_AUTO_COMPACT_THRESHOLD: 0.8\\n",
  "prompts/review.md": "Review code conservatively and explain risks first.\\n"
}`;

function isRecord(value: unknown): value is GooseConfigFiles {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeGooseConfigPath(rawPath: string): string {
  const normalizedPath = rawPath.replace(/\\+/g, "/").trim();
  if (!normalizedPath) {
    throw new Error("Goose config file paths must not be blank.");
  }
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(normalizedPath)) {
    throw new Error("Goose config file paths must be relative to the Goose config root.");
  }

  const segments = normalizedPath.split("/").filter((segment) => segment.length > 0);
  if (segments.length === 0 || segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error(`Goose config file path '${rawPath}' is invalid.`);
  }

  const candidate = segments.join("/");
  if (candidate === "secrets.yaml") {
    throw new Error("Goose secrets.yaml is not supported here. Keep secrets in environment variables.");
  }
  if (segments[0] === "permissions") {
    throw new Error("Goose permissions/* files are runtime-managed and cannot be preseeded here.");
  }
  return candidate;
}

export function stringifyGooseConfigFiles(value: GooseConfigFiles | null | undefined): string {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

export function parseGooseConfigFilesText(rawText: string): GooseConfigFiles {
  const trimmed = rawText.trim();
  if (!trimmed) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error("Goose config files must be valid JSON keyed by relative config file paths.");
  }

  if (!isRecord(parsed)) {
    throw new Error("Goose config files must be a JSON object keyed by relative config file paths.");
  }

  const normalized: GooseConfigFiles = {};
  for (const [rawPath, rawContent] of Object.entries(parsed)) {
    const normalizedPath = normalizeGooseConfigPath(rawPath);
    if (rawContent === null) {
      throw new Error(`Goose config file '${normalizedPath}' must not be null.`);
    }
    normalized[normalizedPath] = rawContent;
  }
  return normalized;
}