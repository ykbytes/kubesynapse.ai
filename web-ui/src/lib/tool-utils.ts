import {
  BookMarked,
  Bot,
  Code2,
  FilePenLine,
  FileText,
  Globe,
  ListTodo,
  MessageCircleQuestion,
  PencilLine,
  ScanSearch,
  Search,
  Sparkles,
  TerminalSquare,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface ToolMeta {
  icon: LucideIcon;
  label: string;
  category: ToolCategory;
  color: string;
}

export type ToolCategory =
  | "edit"
  | "read"
  | "search"
  | "shell"
  | "skill"
  | "plan"
  | "agent"
  | "web"
  | "question"
  | "other";

const CATEGORY_COLORS: Record<ToolCategory, string> = {
  edit: "text-sky-400",
  read: "text-emerald-400",
  search: "text-violet-400",
  shell: "text-amber-400",
  skill: "text-pink-400",
  plan: "text-blue-400",
  agent: "text-cyan-400",
  web: "text-orange-400",
  question: "text-rose-400",
  other: "text-muted-foreground",
};

const TOOL_REGISTRY: Record<string, ToolMeta> = {
  apply_patch: {
    icon: FilePenLine,
    label: "Edit files",
    category: "edit",
    color: CATEGORY_COLORS.edit,
  },
  edit: {
    icon: PencilLine,
    label: "Edit files",
    category: "edit",
    color: CATEGORY_COLORS.edit,
  },
  read: {
    icon: FileText,
    label: "Read file",
    category: "read",
    color: CATEGORY_COLORS.read,
  },
  grep: {
    icon: Search,
    label: "Search content",
    category: "search",
    color: CATEGORY_COLORS.search,
  },
  glob: {
    icon: ScanSearch,
    label: "Find files",
    category: "search",
    color: CATEGORY_COLORS.search,
  },
  bash: {
    icon: TerminalSquare,
    label: "Run shell",
    category: "shell",
    color: CATEGORY_COLORS.shell,
  },
  skill: {
    icon: Sparkles,
    label: "Load skill",
    category: "skill",
    color: CATEGORY_COLORS.skill,
  },
  question: {
    icon: MessageCircleQuestion,
    label: "Ask operator",
    category: "question",
    color: CATEGORY_COLORS.question,
  },
  task: {
    icon: Bot,
    label: "Run subagent",
    category: "agent",
    color: CATEGORY_COLORS.agent,
  },
  todowrite: {
    icon: ListTodo,
    label: "Update plan",
    category: "plan",
    color: CATEGORY_COLORS.plan,
  },
  webfetch: {
    icon: Globe,
    label: "Fetch URL",
    category: "web",
    color: CATEGORY_COLORS.web,
  },
  "microsoft-learn_microsoft_docs_search": {
    icon: BookMarked,
    label: "Microsoft Learn Docs",
    category: "search",
    color: CATEGORY_COLORS.search,
  },
  "microsoft-learn_microsoft_code_sample_search": {
    icon: Code2,
    label: "Microsoft Learn Samples",
    category: "search",
    color: CATEGORY_COLORS.search,
  },
};

const FALLBACK_META: ToolMeta = {
  icon: Wrench,
  label: "Tool call",
  category: "other",
  color: CATEGORY_COLORS.other,
};

export function resolveToolMeta(rawName: string | null | undefined): ToolMeta {
  if (!rawName) return FALLBACK_META;
  const key = rawName.trim().toLowerCase();
  return TOOL_REGISTRY[key] ?? FALLBACK_META;
}

export function toolCallPreview(
  rawName: string | null | undefined,
  inputPreview: string | null | undefined,
): string {
  const meta = resolveToolMeta(rawName);
  const preview = inputPreview?.trim();
  if (!preview) return meta.label;
  switch (meta.category) {
    case "search":
      return preview.length > 80 ? `${preview.slice(0, 80)}…` : preview;
    case "shell":
      return preview.length > 60 ? `$ ${preview.slice(0, 60)}…` : `$ ${preview}`;
    case "web":
      return preview.length > 60 ? `${preview.slice(0, 60)}…` : preview;
    case "read":
      return preview.length > 60 ? `${preview.slice(0, 60)}…` : preview;
    default:
      return meta.label;
  }
}

export interface ToolCallGroup {
  tool: string;
  count: number;
  statuses: Set<string>;
  inputPreviews: string[];
  meta: ToolMeta;
}

export function groupToolCalls(
  calls: Array<{ tool?: string | null; status?: string | null; inputPreview?: string | null }> | null | undefined,
): ToolCallGroup[] {
  if (!calls || calls.length === 0) return [];
  const groups = new Map<string, ToolCallGroup>();
  for (const tc of calls) {
    const raw = tc.tool?.trim() ?? "";
    const key = raw.toLowerCase() || "__empty__";
    let group = groups.get(key);
    if (!group) {
      group = {
        tool: raw,
        count: 0,
        statuses: new Set(),
        inputPreviews: [],
        meta: resolveToolMeta(raw),
      };
      groups.set(key, group);
    }
    group.count += 1;
    if (tc.status) group.statuses.add(tc.status);
    if (tc.inputPreview) {
      if (!group.inputPreviews.includes(tc.inputPreview)) {
        group.inputPreviews.push(tc.inputPreview);
      }
    }
  }
  return Array.from(groups.values()).sort((a, b) => b.count - a.count);
}

export function dominantStatus(statuses: Set<string>): string {
  if (statuses.has("error")) return "error";
  if (statuses.has("failed")) return "failed";
  if (statuses.has("running")) return "running";
  if (statuses.size === 0) return "unknown";
  return "completed";
}
