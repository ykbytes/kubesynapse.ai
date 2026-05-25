export type UnifiedDiffLineKind = "context" | "added" | "removed";

export interface UnifiedDiffLine {
  kind: UnifiedDiffLineKind;
  text: string;
}

export interface UnifiedDiffHunk {
  header: string;
  oldStart: number;
  oldCount: number;
  newStart: number;
  newCount: number;
  lines: UnifiedDiffLine[];
}

export interface UnifiedDiffFile {
  key: string;
  path: string;
  oldPath: string | null;
  newPath: string | null;
  status: "added" | "deleted" | "modified";
  patch: string;
  hunks: UnifiedDiffHunk[];
  addedCount: number;
  removedCount: number;
}

function stripQuotes(value: string): string {
  return value.replace(/^"|"$/g, "");
}

function normalizePath(rawPath: string | null): string | null {
  if (!rawPath) return null;
  const stripped = stripQuotes(rawPath.trim());
  if (!stripped || stripped === "/dev/null") return null;
  const normalizedSlashes = stripped.replace(/\\/g, "/");
  if (normalizedSlashes.startsWith("a/") || normalizedSlashes.startsWith("b/")) {
    return normalizedSlashes.slice(2);
  }
  if (normalizedSlashes.startsWith("./")) {
    return normalizedSlashes.slice(2);
  }
  return normalizedSlashes;
}

function parseDiffHeader(line: string): { oldPath: string | null; newPath: string | null } {
  const raw = line.slice("diff --git ".length).trim();
  const parts = raw.split(/ (?=(?:[^"]*"[^"]*")*[^"]*$)/).map((part) => stripQuotes(part));
  if (parts.length >= 2) {
    return {
      oldPath: normalizePath(parts[0]),
      newPath: normalizePath(parts[1]),
    };
  }
  return { oldPath: null, newPath: null };
}

export function parseUnifiedDiff(input: string): UnifiedDiffFile[] {
  if (!input.trim()) return [];

  const files: UnifiedDiffFile[] = [];
  const lines = input.replace(/\r\n/g, "\n").split("\n");

  let current: UnifiedDiffFile | null = null;
  let currentPatchLines: string[] = [];
  let currentHunk: UnifiedDiffHunk | null = null;

  const commitHunk = () => {
    if (!current || !currentHunk) return;
    current.hunks.push(currentHunk);
    currentHunk = null;
  };

  const commitFile = () => {
    if (!current) return;
    commitHunk();
    current.patch = currentPatchLines.join("\n").trimEnd();
    current.path = current.newPath ?? current.oldPath ?? current.path;
    if (current.oldPath === null) current.status = "added";
    else if (current.newPath === null) current.status = "deleted";
    else current.status = current.status || "modified";
    files.push(current);
    current = null;
    currentPatchLines = [];
  };

  for (const line of lines) {
    if (line.startsWith("diff --git ")) {
      commitFile();
      const paths = parseDiffHeader(line);
      current = {
        key: `${paths.newPath ?? paths.oldPath ?? `diff-${files.length}`}`,
        path: paths.newPath ?? paths.oldPath ?? "",
        oldPath: paths.oldPath,
        newPath: paths.newPath,
        status: "modified",
        patch: "",
        hunks: [],
        addedCount: 0,
        removedCount: 0,
      };
      currentPatchLines = [line];
      continue;
    }

    if (!current) continue;
    currentPatchLines.push(line);

    if (line.startsWith("new file mode ")) {
      current.status = "added";
      continue;
    }

    if (line.startsWith("deleted file mode ")) {
      current.status = "deleted";
      continue;
    }

    if (line.startsWith("--- ")) {
      current.oldPath = normalizePath(line.slice(4));
      continue;
    }

    if (line.startsWith("+++ ")) {
      current.newPath = normalizePath(line.slice(4));
      continue;
    }

    const hunkMatch = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
    if (hunkMatch) {
      commitHunk();
      currentHunk = {
        header: line,
        oldStart: Number.parseInt(hunkMatch[1], 10),
        oldCount: Number.parseInt(hunkMatch[2] ?? "1", 10),
        newStart: Number.parseInt(hunkMatch[3], 10),
        newCount: Number.parseInt(hunkMatch[4] ?? "1", 10),
        lines: [],
      };
      continue;
    }

    if (!currentHunk || line.startsWith("\\ No newline at end of file")) continue;

    const prefix = line[0];
    const text = line.slice(1);
    if (prefix === " ") {
      currentHunk.lines.push({ kind: "context", text });
    } else if (prefix === "+") {
      currentHunk.lines.push({ kind: "added", text });
      current.addedCount += 1;
    } else if (prefix === "-") {
      currentHunk.lines.push({ kind: "removed", text });
      current.removedCount += 1;
    }
  }

  commitFile();
  return files;
}

export function resolveDiffForArtifactPath(artifactPath: string, files: UnifiedDiffFile[]): UnifiedDiffFile | null {
  const normalizedArtifact = artifactPath.replace(/\\/g, "/");
  for (const file of files) {
    const candidates = [file.path, file.newPath, file.oldPath].filter((value): value is string => Boolean(value));
    if (candidates.some((candidate) => normalizedArtifact === candidate || normalizedArtifact.endsWith(`/${candidate}`))) {
      return file;
    }
  }
  return null;
}

export function reconstructOriginalText(modifiedText: string, diffFile: UnifiedDiffFile): string {
  if (diffFile.status === "added") return "";

  const normalizedText = modifiedText.replace(/\r\n/g, "\n");
  const lines = normalizedText.split("\n");
  const hunks = [...diffFile.hunks].reverse();

  for (const hunk of hunks) {
    const originalLines: string[] = [];
    for (const line of hunk.lines) {
      if (line.kind !== "added") {
        originalLines.push(line.text);
      }
    }
    const startIndex = Math.max(0, hunk.newStart - 1);
    lines.splice(startIndex, hunk.newCount, ...originalLines);
  }

  return lines.join("\n");
}