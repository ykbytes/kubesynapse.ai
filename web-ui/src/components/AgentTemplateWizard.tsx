import { useState } from "react";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Code,
  Search,
  Database,
  Container,
  Globe,
  Terminal,
  FileCode,
  MessageSquare,
  ChevronRight,
  Sparkles,
  ArrowLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { RuntimeKind } from "@/types";

/* ── Template definitions (inline to avoid fetch) ── */

interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
  runtime_kind: RuntimeKind;
  model: string;
  system_prompt: string;
  mcp_sidecars: string[];
  mcp_servers: string[];
}

const TEMPLATES: AgentTemplate[] = [
  {
    id: "code-assistant",
    name: "Code Assistant",
    description: "A general-purpose coding assistant with access to code execution and git tools.",
    icon: "Code",
    category: "development",
    runtime_kind: "langgraph",
    model: "gpt-4o",
    system_prompt: "You are a senior software engineer. Help users write, debug, and review code. Follow best practices and write clean, maintainable code. Always explain your reasoning.",
    mcp_sidecars: ["code-exec", "git"],
    mcp_servers: [],
  },
  {
    id: "research-analyst",
    name: "Research Analyst",
    description: "An agent that searches the web and analyzes documents for research tasks.",
    icon: "Search",
    category: "research",
    runtime_kind: "langgraph",
    model: "gpt-4o",
    system_prompt: "You are a research analyst. Search the web, read documents, and synthesize information into clear, well-structured reports. Cite your sources.",
    mcp_sidecars: ["web-search", "documents", "rag"],
    mcp_servers: [],
  },
  {
    id: "data-engineer",
    name: "Data Engineer",
    description: "An agent for database queries, data analysis, and pipeline development.",
    icon: "Database",
    category: "data",
    runtime_kind: "langgraph",
    model: "gpt-4o",
    system_prompt: "You are a data engineer. Help users write SQL queries, design schemas, build data pipelines, and analyze datasets.",
    mcp_sidecars: ["database", "code-exec"],
    mcp_servers: [],
  },
  {
    id: "devops-agent",
    name: "DevOps Agent",
    description: "Manages Kubernetes resources, CI/CD, and infrastructure automation.",
    icon: "Container",
    category: "operations",
    runtime_kind: "langgraph",
    model: "gpt-4o",
    system_prompt: "You are a DevOps engineer specializing in Kubernetes and cloud infrastructure. Help users manage deployments, troubleshoot pods, and automate CI/CD.",
    mcp_sidecars: ["kubernetes", "git", "code-exec"],
    mcp_servers: [],
  },
  {
    id: "browser-agent",
    name: "Browser Agent",
    description: "An agent that can browse the web, interact with pages, and extract data.",
    icon: "Globe",
    category: "automation",
    runtime_kind: "langgraph",
    model: "gpt-4o",
    system_prompt: "You are a web automation agent. Navigate websites, fill forms, extract data, and take screenshots.",
    mcp_sidecars: ["browser", "web-search"],
    mcp_servers: [],
  },
  {
    id: "goose-developer",
    name: "Goose Developer",
    description: "A Goose-runtime coding agent for autonomous software development.",
    icon: "Terminal",
    category: "development",
    runtime_kind: "goose",
    model: "gpt-4o",
    system_prompt: "",
    mcp_sidecars: [],
    mcp_servers: [],
  },
  {
    id: "opencode-agent",
    name: "OpenCode Agent",
    description: "An OpenCode-runtime agent for code editing and project management.",
    icon: "FileCode",
    category: "development",
    runtime_kind: "opencode",
    model: "gpt-4o",
    system_prompt: "",
    mcp_sidecars: [],
    mcp_servers: [],
  },
  {
    id: "messaging-bot",
    name: "Messaging Bot",
    description: "An agent that integrates with Slack and messaging platforms.",
    icon: "MessageSquare",
    category: "communication",
    runtime_kind: "langgraph",
    model: "gpt-4o",
    system_prompt: "You are a helpful messaging assistant. Respond concisely and professionally.",
    mcp_sidecars: ["messaging"],
    mcp_servers: [],
  },
];

const ICON_MAP: Record<string, typeof Code> = {
  Code,
  Search,
  Database,
  Container,
  Globe,
  Terminal,
  FileCode,
  MessageSquare,
};

const CATEGORY_COLORS: Record<string, string> = {
  development: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  research: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  data: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  operations: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  automation: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  communication: "bg-pink-500/10 text-pink-400 border-pink-500/20",
};

interface AgentTemplateWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AgentTemplateWizard({ open, onOpenChange }: AgentTemplateWizardProps) {
  const ws = useWorkspace();
  const [step, setStep] = useState<"pick" | "customize">("pick");
  const [selected, setSelected] = useState<AgentTemplate | null>(null);
  const [agentName, setAgentName] = useState("");
  const [model, setModel] = useState("");
  const [filterCategory, setFilterCategory] = useState<string | null>(null);

  const categories = [...new Set(TEMPLATES.map((t) => t.category))];
  const filtered = filterCategory
    ? TEMPLATES.filter((t) => t.category === filterCategory)
    : TEMPLATES;

  const handleSelect = (template: AgentTemplate) => {
    setSelected(template);
    setAgentName(template.id);
    setModel(template.model);
    setStep("customize");
  };

  const handleApply = () => {
    if (!selected) return;
    ws.setCreateAgentName(agentName || selected.id);
    ws.setCreateAgentModel(model || selected.model);
    ws.setCreateAgentSystemPrompt(selected.system_prompt);
    ws.setCreateAgentRuntimeKind(selected.runtime_kind);
    if (selected.mcp_sidecars.length > 0) {
      ws.setCreateAgentMcpSidecarsText(selected.mcp_sidecars.join(", "));
    }
    if (selected.mcp_servers.length > 0) {
      ws.setCreateAgentMcpServersText(selected.mcp_servers.join("\n"));
    }
    // Switch to agent create mode
    ws.setActiveView("agents");
    ws.setAgentCreateMode(true);
    onOpenChange(false);
    // Reset wizard state
    setStep("pick");
    setSelected(null);
    setAgentName("");
    setModel("");
    setFilterCategory(null);
  };

  const handleClose = () => {
    onOpenChange(false);
    setStep("pick");
    setSelected(null);
    setAgentName("");
    setModel("");
    setFilterCategory(null);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-primary" />
            {step === "pick" ? "Choose Agent Template" : "Customize Agent"}
          </DialogTitle>
          <DialogDescription>
            {step === "pick"
              ? "Select a pre-configured template to quickly create a new agent."
              : `Customize "${selected?.name}" before creating.`}
          </DialogDescription>
        </DialogHeader>

        {step === "pick" && (
          <div className="flex-1 overflow-auto space-y-3 py-2">
            {/* Category filter */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <Button
                variant={filterCategory === null ? "default" : "outline"}
                size="sm"
                className="h-6 text-[10px] px-2 cursor-pointer"
                onClick={() => setFilterCategory(null)}
              >
                All
              </Button>
              {categories.map((cat) => (
                <Button
                  key={cat}
                  variant={filterCategory === cat ? "default" : "outline"}
                  size="sm"
                  className="h-6 text-[10px] px-2 capitalize cursor-pointer"
                  onClick={() => setFilterCategory(cat)}
                >
                  {cat}
                </Button>
              ))}
            </div>

            {/* Template grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {filtered.map((template) => {
                const Icon = ICON_MAP[template.icon] ?? Code;
                return (
                  <button
                    key={template.id}
                    type="button"
                    onClick={() => handleSelect(template)}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 text-left transition-all cursor-pointer",
                      "hover:bg-accent/50 hover:border-primary/30 hover:shadow-md",
                      "focus:outline-none focus:ring-2 focus:ring-primary/40",
                    )}
                  >
                    <div className="shrink-0 rounded-lg bg-primary/10 p-2">
                      <Icon className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-sm font-semibold truncate">{template.name}</span>
                        <Badge variant="outline" className={cn("text-[9px] h-4 px-1.5 border", CATEGORY_COLORS[template.category] ?? "")}>
                          {template.category}
                        </Badge>
                      </div>
                      <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed">
                        {template.description}
                      </p>
                      <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                        <Badge variant="secondary" className="text-[9px] h-4 px-1.5">{template.runtime_kind}</Badge>
                        {template.mcp_sidecars.map((s) => (
                          <Badge key={s} variant="outline" className="text-[9px] h-4 px-1.5">{s}</Badge>
                        ))}
                      </div>
                    </div>
                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0 mt-1" />
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {step === "customize" && selected && (
          <div className="flex-1 overflow-auto space-y-4 py-2">
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs gap-1 cursor-pointer"
              onClick={() => setStep("pick")}
            >
              <ArrowLeft className="h-3 w-3" /> Back to templates
            </Button>

            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Agent Name</Label>
                <Input
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="my-code-assistant"
                  className="h-8 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Model</Label>
                <Input
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="gpt-4o"
                  className="h-8 text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Runtime</Label>
                <div className="text-sm text-muted-foreground bg-muted/30 rounded-md px-3 py-1.5">
                  {selected.runtime_kind}
                </div>
              </div>
              {selected.system_prompt && (
                <div className="space-y-1.5">
                  <Label className="text-xs">System Prompt (preview)</Label>
                  <div className="text-[11px] text-muted-foreground bg-muted/30 rounded-md px-3 py-2 max-h-24 overflow-auto">
                    {selected.system_prompt}
                  </div>
                </div>
              )}
              {selected.mcp_sidecars.length > 0 && (
                <div className="space-y-1.5">
                  <Label className="text-xs">MCP Sidecars</Label>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {selected.mcp_sidecars.map((s) => (
                      <Badge key={s} variant="outline" className="text-xs">{s}</Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} className="cursor-pointer">Cancel</Button>
          {step === "customize" && (
            <Button onClick={handleApply} disabled={!agentName.trim()} className="cursor-pointer">
              Create Agent
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
