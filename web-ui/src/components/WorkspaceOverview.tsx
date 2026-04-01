import {
  Activity,
  ArrowRight,
  Bot,
  CheckCircle2,
  FlaskConical,
  GitBranch,
  LayoutPanelTop,
  Plus,
  Settings2,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { AuthenticatedUser } from "@/types";

interface WorkspaceOverviewProps {
  namespace: string;
  gatewayStatus: string;
  authMode: string;
  currentUser: AuthenticatedUser | null;
  agentCount: number;
  workflowCount: number;
  evalCount: number;
  policyCount: number;
  hasConversation: boolean;
  onCreateAgent: () => void;
  onOpenCatalog: () => void;
  onOpenWorkflowBuilder: () => void;
  onOpenEvals: () => void;
  onOpenOperations: () => void;
}

type ChecklistItem = {
  label: string;
  done: boolean;
  detail: string;
};

function gatewayTone(status: string) {
  if (status === "ok" || status === "healthy") {
    return {
      badge: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
      title: "Platform healthy",
      description: "Gateway, auth, and workspace controls are ready for normal operation.",
    };
  }
  if (status === "loading") {
    return {
      badge: "border-amber-500/30 bg-amber-500/10 text-amber-400",
      title: "Checking platform posture",
      description: "The console is still validating connectivity and current control-plane status.",
    };
  }
  return {
    badge: "border-red-500/30 bg-red-500/10 text-red-400",
    title: "Connectivity needs attention",
    description: "The console is authenticated, but the gateway or upstream health signal is degraded.",
  };
}

function ResourceStat({
  label,
  value,
  description,
  tone = "default",
  icon: Icon,
}: {
  label: string;
  value: number;
  description: string;
  tone?: "default" | "success" | "warning";
  icon: typeof Bot;
}) {
  return (
    <div className="rounded-2xl border border-border/60 bg-background/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight text-foreground">{value}</div>
        </div>
        <div
          className={cn(
            "flex h-10 w-10 items-center justify-center rounded-xl border",
            tone === "success"
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
              : tone === "warning"
                ? "border-amber-500/20 bg-amber-500/10 text-amber-400"
                : "border-primary/20 bg-primary/10 text-primary",
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{description}</p>
    </div>
  );
}

export function WorkspaceOverview({
  namespace,
  gatewayStatus,
  authMode,
  currentUser,
  agentCount,
  workflowCount,
  evalCount,
  policyCount,
  hasConversation,
  onCreateAgent,
  onOpenCatalog,
  onOpenWorkflowBuilder,
  onOpenEvals,
  onOpenOperations,
}: WorkspaceOverviewProps) {
  const posture = gatewayTone(gatewayStatus);
  const checklist: ChecklistItem[] = [
    {
      label: "Gateway connected",
      done: gatewayStatus === "ok" || gatewayStatus === "healthy",
      detail: "The control plane can authenticate and surface live workspace data.",
    },
    {
      label: "First agent provisioned",
      done: agentCount > 0,
      detail: "Create an agent so the runtime, inspector, and chat surfaces have something real to operate on.",
    },
    {
      label: "Live conversation started",
      done: hasConversation,
      detail: "Run a real chat session to validate session continuity, tools, approvals, and runtime behavior.",
    },
    {
      label: "Workflow automation defined",
      done: workflowCount > 0,
      detail: "Model one repeatable orchestration path instead of operating agents one request at a time.",
    },
    {
      label: "Evaluation coverage added",
      done: evalCount > 0,
      detail: "Back the platform with regression checks before teams rely on it in production.",
    },
  ];
  const completed = checklist.filter((item) => item.done).length;
  const completionPercent = Math.round((completed / checklist.length) * 100);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(22rem,1fr)]">
      <Card className="overflow-hidden border-primary/15 bg-[linear-gradient(180deg,rgba(45,212,191,0.08),rgba(0,0,0,0)_9rem)] shadow-lg shadow-black/5">
        <CardHeader className="space-y-4 pb-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-primary/25 bg-primary/10 text-primary">
              Control plane
            </Badge>
            <Badge variant="outline" className="font-mono text-[10px]">
              {namespace}
            </Badge>
            <Badge variant="outline" className="capitalize">
              {currentUser?.role ?? "viewer"}
            </Badge>
            <Badge variant="outline" className="capitalize">
              Auth {authMode || "unknown"}
            </Badge>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
                <LayoutPanelTop className="h-5 w-5" />
              </div>
              <div>
                <CardTitle className="text-xl tracking-tight">Operational command center</CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  Give new operators one place to understand platform posture, next actions, and current capacity.
                </p>
              </div>
            </div>
            <div className="rounded-2xl border border-border/60 bg-background/70 p-3 text-sm text-muted-foreground">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className={posture.badge}>{gatewayStatus}</Badge>
                <span className="font-medium text-foreground">{posture.title}</span>
              </div>
              <p className="mt-2 leading-relaxed">{posture.description}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                Signed in as <span className="font-medium text-foreground">{currentUser?.display_name || currentUser?.username || "operator"}</span>. Use the actions below to move from setup into repeatable operations.
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button className="gap-1.5" onClick={onCreateAgent}>
              <Plus className="h-3.5 w-3.5" />
              {agentCount === 0 ? "Create first agent" : "Create agent"}
            </Button>
            <Button variant="outline" className="gap-1.5" onClick={onOpenCatalog}>
              <ShieldCheck className="h-3.5 w-3.5" />
              Browse catalog
            </Button>
            <Button variant="outline" className="gap-1.5" onClick={onOpenWorkflowBuilder}>
              <GitBranch className="h-3.5 w-3.5" />
              Design workflow
            </Button>
            <Button variant="outline" className="gap-1.5" onClick={onOpenOperations}>
              <Activity className="h-3.5 w-3.5" />
              Open operations
            </Button>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <ResourceStat
              label="Agents"
              value={agentCount}
              description={agentCount === 0 ? "No runtimes are provisioned yet." : "Live runtime surfaces available for chat and management."}
              tone={agentCount > 0 ? "success" : "warning"}
              icon={Bot}
            />
            <ResourceStat
              label="Workflows"
              value={workflowCount}
              description={workflowCount === 0 ? "No orchestrated automation paths yet." : "Repeatable orchestration exists beyond ad hoc prompts."}
              tone={workflowCount > 0 ? "success" : "default"}
              icon={GitBranch}
            />
            <ResourceStat
              label="Evaluations"
              value={evalCount}
              description={evalCount === 0 ? "Quality coverage is still manual." : "Regression checks are defined for agent quality."}
              tone={evalCount > 0 ? "success" : "default"}
              icon={FlaskConical}
            />
            <ResourceStat
              label="Policies"
              value={policyCount}
              description={policyCount === 0 ? "Guardrails are relying on defaults only." : "Governance and model controls are in place."}
              tone={policyCount > 0 ? "success" : "default"}
              icon={ShieldAlert}
            />
          </div>
        </CardContent>
      </Card>

      <Card className="border-border/70 bg-card/80">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base tracking-tight">Activation checklist</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {completed} of {checklist.length} milestones complete
              </p>
            </div>
            <Badge variant="outline" className="font-mono text-[10px]">
              {completionPercent}%
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="h-1.5 overflow-hidden rounded-full bg-border/40">
            <div className="h-full rounded-full bg-primary transition-all duration-300" style={{ width: `${completionPercent}%` }} />
          </div>

          <div className="space-y-2.5">
            {checklist.map((item) => (
              <div key={item.label} className="flex items-start gap-3 rounded-2xl border border-border/60 bg-background/60 px-3 py-3">
                <div className="mt-0.5 shrink-0 text-primary">
                  {item.done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  ) : (
                    <Activity className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-foreground">{item.label}</div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.detail}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-2xl border border-border/60 bg-background/60 p-3">
            <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
              <Settings2 className="h-3.5 w-3.5" />
              Next best move
            </div>
            <p className="mt-2 text-sm text-foreground">
              {agentCount === 0
                ? "Provision the first agent so the platform has a live runtime to inspect and chat with."
                : !hasConversation
                  ? "Use an existing agent to validate live chat, session continuity, and tool execution."
                  : workflowCount === 0
                    ? "Turn a successful manual agent flow into a workflow so the platform starts to feel operational, not manual."
                    : evalCount === 0
                      ? "Add one evaluation suite to move from demo-grade usage into measurable quality control."
                      : "Open operations to review health and governance posture before broadening adoption."}
            </p>
            <Button variant="ghost" size="sm" className="mt-3 gap-1 px-0 text-primary hover:bg-transparent hover:text-primary/90" onClick={evalCount === 0 ? onOpenEvals : onOpenOperations}>
              {evalCount === 0 ? "Open evaluations" : "Review operations"}
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}