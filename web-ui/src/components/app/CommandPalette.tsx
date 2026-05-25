import { useCallback, useEffect, useState } from "react";
import {
  BookOpen,
  Bot,
  GitBranch,
  Blocks,
  MessageSquare,
  Package,
  ShieldAlert,
  Settings,
  ShieldCheck,
  Palette,
  Plus,
  Download,
  Upload,
  type LucideIcon,
} from "lucide-react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import type { WorkspaceView } from "@/types";

interface CommandAction {
  id: string;
  label: string;
  icon: LucideIcon;
  group: string;
  keywords?: string;
  action: () => void;
}

interface CommandPaletteProps {
  onNavigate: (view: WorkspaceView) => void;
  onCreateAgent?: () => void;
  onCreateWorkflow?: () => void;
  onToggleTheme?: () => void;
  onExportBundle?: () => void;
  onImportBundle?: () => void;
}

const NAV_ITEMS: { view: WorkspaceView; label: string; icon: LucideIcon; keywords: string }[] = [
  { view: "agents", label: "Go to Agents", icon: Bot, keywords: "agent list bots" },
  { view: "chat", label: "Go to Chat", icon: MessageSquare, keywords: "chat conversation messages agent" },
  { view: "workflows", label: "Go to Workflows", icon: GitBranch, keywords: "workflow pipeline" },
  { view: "composer", label: "Go to Composer", icon: Blocks, keywords: "compose dag" },
  { view: "catalog", label: "Go to Catalog", icon: Package, keywords: "catalog skills mcp" },
  { view: "policies", label: "Go to Policies", icon: ShieldAlert, keywords: "policy guard" },
  { view: "settings", label: "Go to Settings", icon: Settings, keywords: "settings config provider" },
  { view: "admin", label: "Go to Admin", icon: ShieldCheck, keywords: "admin users" },
  { view: "docs", label: "Open Documentation", icon: BookOpen, keywords: "docs documentation help guide" },
];

export function CommandPalette({
  onNavigate,
  onCreateAgent,
  onCreateWorkflow,
  onToggleTheme,
  onExportBundle,
  onImportBundle,
}: CommandPaletteProps) {
  const [open, setOpen] = useState(false);

  // Ctrl+K / Cmd+K shortcut
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  const run = useCallback(
    (fn: () => void) => {
      setOpen(false);
      fn();
    },
    [],
  );

  const actions: CommandAction[] = [
    // Navigation
    ...NAV_ITEMS.map((item) => ({
      id: `nav-${item.view}`,
      label: item.label,
      icon: item.icon,
      group: "Navigation",
      keywords: item.keywords,
      action: () => run(() => onNavigate(item.view)),
    })),
    // Quick actions
    ...(onCreateAgent
      ? [
          {
            id: "create-agent",
            label: "Create new Agent",
            icon: Plus,
            group: "Actions",
            keywords: "new agent create",
            action: () => run(onCreateAgent),
          },
        ]
      : []),
    ...(onCreateWorkflow
      ? [
          {
            id: "create-workflow",
            label: "Create new Workflow",
            icon: Plus,
            group: "Actions",
            keywords: "new workflow create",
            action: () => run(onCreateWorkflow),
          },
        ]
      : []),
    ...(onToggleTheme
      ? [
          {
            id: "toggle-theme",
            label: "Toggle theme",
            icon: Palette,
            group: "Preferences",
            keywords: "theme dark light",
            action: () => run(onToggleTheme),
          },
        ]
      : []),
    ...(onExportBundle
      ? [
          {
            id: "export-bundle",
            label: "Export workspace bundle",
            icon: Download,
            group: "Actions",
            keywords: "export download yaml bundle backup",
            action: () => run(onExportBundle),
          },
        ]
      : []),
    ...(onImportBundle
      ? [
          {
            id: "import-bundle",
            label: "Import workspace bundle",
            icon: Upload,
            group: "Actions",
            keywords: "import upload yaml bundle restore",
            action: () => run(onImportBundle),
          },
        ]
      : []),
  ];

  const groups = [...new Set(actions.map((a) => a.group))];

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Type a command or search..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        {groups.map((group, gi) => (
          <div key={group}>
            {gi > 0 && <CommandSeparator />}
            <CommandGroup heading={group}>
              {actions
                .filter((a) => a.group === group)
                .map((a) => (
                  <CommandItem
                    key={a.id}
                    value={`${a.label} ${a.keywords ?? ""}`}
                    onSelect={a.action}
                  >
                    <a.icon className="mr-2 h-4 w-4" />
                    <span>{a.label}</span>
                  </CommandItem>
                ))}
            </CommandGroup>
          </div>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
