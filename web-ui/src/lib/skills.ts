import type { TextFileDraft } from "../types";

type SkillFiles = Record<string, string>;

function createDraftId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function createSkillFileDraft(initial?: Partial<TextFileDraft>): TextFileDraft {
  return {
    id: initial?.id ?? createDraftId(),
    path: initial?.path ?? "skills/new-skill/SKILL.md",
    content:
      initial?.content ??
      [
        "---",
        "name: new-skill",
        "description: Describe when this skill should steer the agent.",
        "---",
        "Add precise operating instructions for this skill.",
        "Document the expected output, decision boundaries, and any coordination rules.",
        "",
      ].join("\n"),
  };
}

function normalizeSkillPath(rawPath: string): string {
  const normalizedPath = rawPath.replace(/\\+/g, "/").trim();
  if (!normalizedPath) {
    throw new Error("Skill file paths must not be blank.");
  }
  if (/^(?:[A-Za-z]:[\\/]|\/)/.test(normalizedPath)) {
    throw new Error("Skill file paths must be relative.");
  }

  const segments = normalizedPath.split("/").filter((segment) => segment.length > 0);
  if (segments.length === 0 || segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error(`Skill file path '${rawPath}' is invalid.`);
  }

  const candidate = segments.join("/");
  if (!candidate.toLowerCase().endsWith(".md")) {
    throw new Error(`Skill file path '${candidate}' must end in .md.`);
  }
  return candidate;
}

export function skillFileDraftsFromFiles(value: SkillFiles | null | undefined): TextFileDraft[] {
  if (!value || Object.keys(value).length === 0) {
    return [];
  }

  return Object.entries(value)
    .sort(([leftPath], [rightPath]) => leftPath.localeCompare(rightPath))
    .map(([path, content]) =>
      createSkillFileDraft({
        path,
        content,
      }),
    );
}

export function buildSkillFiles(drafts: TextFileDraft[]): SkillFiles {
  const normalized: SkillFiles = {};

  for (const draft of drafts) {
    const rawPath = draft.path.trim();
    const rawContent = draft.content.replace(/\r\n/g, "\n");
    if (!rawPath && !rawContent.trim()) {
      continue;
    }
    if (!rawPath) {
      throw new Error("Each skill file needs a relative Markdown path.");
    }
    const normalizedPath = normalizeSkillPath(rawPath);
    if (normalized[normalizedPath]) {
      throw new Error(`Skill file path '${normalizedPath}' is duplicated.`);
    }
    if (!rawContent.trim()) {
      throw new Error(`Skill file '${normalizedPath}' must not be blank.`);
    }
    normalized[normalizedPath] = rawContent;
  }

  return normalized;
}