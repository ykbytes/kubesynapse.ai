import type { TextFileDraft } from "../types";

type OpenCodeConfigFiles = Record<string, unknown>;

function createDraftId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function createOpenCodeConfigFileDraft(initial?: Partial<TextFileDraft>): TextFileDraft {
  return {
    id: initial?.id ?? createDraftId(),
    path: initial?.path ?? "config.json",
    content:
      initial?.content ??
      [
        "{",
        '  "provider": "openai",',
        '  "model": "gpt-4"',
        "}",
        "",
      ].join("\n"),
  };
}

function normalizeOpenCodeConfigPath(rawPath: string): string {
  const normalizedPath = rawPath.replace(/\\+/g, "/").trim();
  if (!normalizedPath) {
    throw new Error("OpenCode config file paths must not be blank.");
  }
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(normalizedPath)) {
    throw new Error("OpenCode config file paths must be relative to the OpenCode config root.");
  }

  const segments = normalizedPath.split("/").filter((segment) => segment.length > 0);
  if (segments.length === 0 || segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error(`OpenCode config file path '${rawPath}' is invalid.`);
  }

  return segments.join("/");
}

export function opencodeConfigFileDraftsFromFiles(value: OpenCodeConfigFiles | null | undefined): TextFileDraft[] {
  if (!value || Object.keys(value).length === 0) {
    return [];
  }

  return Object.entries(value)
    .sort(([leftPath], [rightPath]) => leftPath.localeCompare(rightPath))
    .map(([path, content]) =>
      createOpenCodeConfigFileDraft({
        path,
        content: typeof content === "string" ? content : JSON.stringify(content, null, 2),
      }),
    );
}

export function buildOpenCodeConfigFiles(drafts: TextFileDraft[]): OpenCodeConfigFiles {
  const normalized: OpenCodeConfigFiles = {};

  for (const draft of drafts) {
    const rawPath = draft.path.trim();
    const rawContent = draft.content.replace(/\r\n/g, "\n");
    if (!rawPath && !rawContent.trim()) {
      continue;
    }
    if (!rawPath) {
      throw new Error("Each OpenCode config file needs a relative path.");
    }
    const normalizedPath = normalizeOpenCodeConfigPath(rawPath);
    if (normalizedPath in normalized) {
      throw new Error(`OpenCode config file path '${normalizedPath}' is duplicated.`);
    }
    normalized[normalizedPath] = rawContent;
  }

  return normalized;
}
