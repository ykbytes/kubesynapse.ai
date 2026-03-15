import type { TextFileDraft } from "../types";

type GooseConfigFiles = Record<string, unknown>;

function createDraftId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function createGooseConfigFileDraft(initial?: Partial<TextFileDraft>): TextFileDraft {
  return {
    id: initial?.id ?? createDraftId(),
    path: initial?.path ?? "config.yaml",
    content:
      initial?.content ??
      [
        "GOOSE_MODE: smart_approve",
        "GOOSE_AUTO_COMPACT_THRESHOLD: 0.8",
        "",
      ].join("\n"),
  };
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

export function gooseConfigFileDraftsFromFiles(value: GooseConfigFiles | null | undefined): TextFileDraft[] {
  if (!value || Object.keys(value).length === 0) {
    return [];
  }

  return Object.entries(value)
    .sort(([leftPath], [rightPath]) => leftPath.localeCompare(rightPath))
    .map(([path, content]) =>
      createGooseConfigFileDraft({
        path,
        content: typeof content === "string" ? content : JSON.stringify(content, null, 2),
      }),
    );
}

export function buildGooseConfigFiles(drafts: TextFileDraft[]): GooseConfigFiles {
  const normalized: GooseConfigFiles = {};

  for (const draft of drafts) {
    const rawPath = draft.path.trim();
    const rawContent = draft.content.replace(/\r\n/g, "\n");
    if (!rawPath && !rawContent.trim()) {
      continue;
    }
    if (!rawPath) {
      throw new Error("Each Goose config file needs a relative path.");
    }
    const normalizedPath = normalizeGooseConfigPath(rawPath);
    if (normalizedPath in normalized) {
      throw new Error(`Goose config file path '${normalizedPath}' is duplicated.`);
    }
    normalized[normalizedPath] = rawContent;
  }

  return normalized;
}