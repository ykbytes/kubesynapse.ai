import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  Database,
  Eye,
  GitBranch,
  Globe,
  LayoutPanelTop,
  Lock,
  MessageSquare,
  Network,
  Play,
  RefreshCw,
  Server,
  Shield,
  Sparkles,
  Timer,
  Workflow,
  Zap,
} from "lucide-react";
import { BRAND } from "@/lib/brand";

// ─── Types ───

interface LandingPageProps {
  onLogin: () => void;
}

// ─── Reusable sub-components ───

function AnnouncementBar() {
  return (
    <div className="relative overflow-hidden border-b border-border/30 bg-primary/5 px-4 py-2 text-center">
      <div className="flex items-center justify-center gap-2 text-xs font-medium text-primary">
        <Sparkles className="h-3.5 w-3.5" />
        <span>New: Durable Memory, Session Continuity & Tool Governance are live</span>
        <ChevronRight className="h-3 w-3" />
      </div>
    </div>
  );
}

function Navbar({ onLogin }: { onLogin: () => void }) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className={`glass-navbar sticky top-0 z-50 transition-all duration-300 ${scrolled ? "shadow-lg" : ""}`}
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <LayoutPanelTop className="h-5 w-5" />
          </div>
          <div>
            <span className="text-base font-bold tracking-tight text-foreground">
              {BRAND.name}
            </span>
            <span className="ml-2 hidden text-xs font-medium text-muted-foreground sm:inline">
              {BRAND.tagline}
            </span>
          </div>
        </div>

        <div className="hidden items-center gap-8 text-sm font-medium text-muted-foreground md:flex">
          <a href="#features" className="transition-colors hover:text-foreground">Features</a>
          <a href="#scenarios" className="transition-colors hover:text-foreground">Use Cases</a>
          <a href="#workflows" className="transition-colors hover:text-foreground">Workflows</a>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onLogin}
            className="rounded-lg px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Sign In
          </button>
          <button
            onClick={onLogin}
            className="glow-button rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
          >
            Get Started
          </button>
        </div>
      </div>
    </nav>
  );
}

// ─── Hero Section ───

function HeroSection({ onLogin }: { onLogin: () => void }) {
  return (
    <section className="relative overflow-hidden px-6 pb-20 pt-24 md:pb-32 md:pt-36">
      {/* Decorative glow orbs */}
      <div
        className="glow-orb -top-32 left-1/4 h-[500px] w-[500px] bg-primary/20"
        style={{ animation: "glow-breathe 6s ease-in-out infinite" }}
      />
      <div
        className="glow-orb -right-20 top-20 h-[400px] w-[400px]"
        style={{
          background: "oklch(0.65 0.16 250 / 0.15)",
          animation: "glow-breathe 8s ease-in-out infinite 2s",
        }}
      />
      <div
        className="glow-orb bottom-0 left-1/2 h-[300px] w-[300px] -translate-x-1/2"
        style={{
          background: "oklch(0.55 0.2 300 / 0.08)",
          animation: "glow-breathe 7s ease-in-out infinite 4s",
        }}
      />

      <div className="relative mx-auto max-w-5xl text-center">
        {/* Pill badge */}
        <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-border/50 bg-card/50 px-4 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur-sm animate-fade-in">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500" />
          Kubernetes-native AI Agent Orchestration
        </div>

        {/* Main heading */}
        <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl md:text-6xl lg:text-7xl animate-slide-up">
          Orchestrate{" "}
          <span className="text-shimmer">AI Agents</span>
          <br />
          <span className="text-gradient-hero">That Actually Work</span>
        </h1>

        {/* Subtitle */}
        <p className="mx-auto mt-6 max-w-2xl text-base text-muted-foreground sm:text-lg md:text-xl animate-slide-up" style={{ animationDelay: "0.1s" }}>
          Deploy autonomous agents with durable memory, strict governance, and enterprise-grade
          workflow orchestration. From incident response to compliance — agents that remember,
          reason, and recover.
        </p>

        {/* CTAs */}
        <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center animate-slide-up" style={{ animationDelay: "0.2s" }}>
          <button
            onClick={onLogin}
            className="glow-button group flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground transition-all"
          >
            Initialize Workspace
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          <button
            onClick={() => document.getElementById("workflows")?.scrollIntoView({ behavior: "smooth" })}
            className="flex items-center gap-2 rounded-xl border border-border/50 bg-card/30 px-6 py-3 text-sm font-medium text-foreground backdrop-blur-sm transition-colors hover:bg-card/60"
          >
            <Play className="h-4 w-4 text-primary" />
            Watch Demo
          </button>
        </div>
      </div>
    </section>
  );
}

// ─── Mock UI Preview ───

function MockUIPreview() {
  const [activeChat, setActiveChat] = useState(0);
  const chatMessages = [
    { role: "user", text: "Deploy the incident-triage agent to production namespace" },
    { role: "agent", text: "Deploying agent 'incident-triage' with MCP sidecars: kubernetes, messaging, git. Runtime: opencode. Memory policy: persistent." },
    { role: "system", text: "Agent running. 3 tools loaded. Session recovered from checkpoint #47." },
  ];

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveChat((prev) => (prev < chatMessages.length - 1 ? prev + 1 : prev));
    }, 2000);
    return () => clearInterval(interval);
  }, [chatMessages.length]);

  return (
    <section className="relative px-6 pb-20 md:pb-32">
      <div className="mx-auto max-w-5xl">
        <div
          className="mock-window animate-scale-in"
          style={{ animationDelay: "0.3s", animation: "float 6s ease-in-out infinite" }}
        >
          {/* Title bar */}
          <div className="mock-titlebar">
            <div className="mock-dot" style={{ background: "oklch(0.60 0.20 27)" }} />
            <div className="mock-dot" style={{ background: "oklch(0.75 0.15 85)" }} />
            <div className="mock-dot" style={{ background: "oklch(0.65 0.15 145)" }} />
            <div className="ml-4 flex-1 rounded-md bg-background/50 px-3 py-1 text-[11px] text-muted-foreground">
              kubemininions.io/workspace
            </div>
          </div>

          {/* Mock UI content */}
          <div className="flex min-h-[340px] md:min-h-[420px]">
            {/* Sidebar */}
            <div className="hidden w-14 flex-shrink-0 flex-col items-center gap-3 border-r border-border/30 bg-sidebar/50 py-4 sm:flex">
              <div className="h-7 w-7 rounded-lg bg-primary/15 p-1 text-primary"><Bot className="h-full w-full" /></div>
              <div className="h-7 w-7 rounded-lg bg-muted/50 p-1 text-muted-foreground"><Workflow className="h-full w-full" /></div>
              <div className="h-7 w-7 rounded-lg bg-muted/50 p-1 text-muted-foreground"><Shield className="h-full w-full" /></div>
              <div className="h-7 w-7 rounded-lg bg-muted/50 p-1 text-muted-foreground"><Eye className="h-full w-full" /></div>
            </div>

            {/* Agent list */}
            <div className="hidden w-48 flex-shrink-0 flex-col border-r border-border/30 bg-card/30 md:flex">
              <div className="border-b border-border/20 px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Agents
              </div>
              {["incident-triage", "compliance-auditor", "cost-optimizer", "deploy-guardian"].map((name, i) => (
                <div
                  key={name}
                  className={`flex items-center gap-2 border-b border-border/10 px-3 py-2 text-[11px] ${i === 0 ? "bg-primary/5 text-foreground border-l-2 border-l-primary" : "text-muted-foreground"}`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${i === 0 ? "bg-emerald-500" : i === 3 ? "bg-amber-500" : "bg-muted-foreground/50"}`} />
                  {name}
                </div>
              ))}
            </div>

            {/* Chat area */}
            <div className="flex flex-1 flex-col">
              <div className="flex items-center gap-2 border-b border-border/20 px-4 py-2.5">
                <Bot className="h-3.5 w-3.5 text-primary" />
                <span className="text-[11px] font-semibold text-foreground">incident-triage</span>
                <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[9px] font-medium text-emerald-400">
                  <span className="h-1 w-1 rounded-full bg-emerald-500" /> running
                </span>
              </div>
              <div className="flex-1 space-y-3 overflow-hidden p-4">
                {chatMessages.slice(0, activeChat + 1).map((msg, i) => (
                  <div key={i} className={`flex gap-2 animate-slide-up ${msg.role === "user" ? "justify-end" : ""}`} style={{ animationDelay: `${i * 0.15}s` }}>
                    {msg.role !== "user" && (
                      <div className={`mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md ${msg.role === "agent" ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>
                        {msg.role === "agent" ? <Bot className="h-3 w-3" /> : <Server className="h-3 w-3" />}
                      </div>
                    )}
                    <div className={`max-w-[85%] rounded-lg px-3 py-2 text-[11px] leading-relaxed ${msg.role === "user" ? "bg-primary/15 text-foreground" : "bg-muted/50 text-muted-foreground"}`}>
                      {msg.text}
                    </div>
                  </div>
                ))}
                {activeChat < chatMessages.length - 1 && (
                  <div className="flex gap-2">
                    <div className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md bg-primary/15 text-primary">
                      <Bot className="h-3 w-3" />
                    </div>
                    <div className="streaming-dots flex items-center gap-1 rounded-lg bg-muted/50 px-3 py-2">
                      <span /><span /><span />
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Inspector panel */}
            <div className="hidden w-56 flex-shrink-0 flex-col border-l border-border/30 bg-card/20 lg:flex">
              <div className="border-b border-border/20 px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Inspector
              </div>
              <div className="space-y-3 p-3">
                <div>
                  <div className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">Memory</div>
                  <div className="mt-1 space-y-1">
                    <div className="flex items-center gap-1.5 rounded bg-muted/30 px-2 py-1 text-[10px] text-muted-foreground">
                      <Database className="h-3 w-3 text-primary/60" /> 23 records persisted
                    </div>
                    <div className="flex items-center gap-1.5 rounded bg-muted/30 px-2 py-1 text-[10px] text-muted-foreground">
                      <RefreshCw className="h-3 w-3 text-emerald-500/60" /> Session #47 recovered
                    </div>
                  </div>
                </div>
                <div>
                  <div className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">Tools</div>
                  <div className="mt-1 space-y-1">
                    {["kubernetes", "messaging", "git"].map((tool) => (
                      <div key={tool} className="flex items-center gap-1.5 rounded bg-muted/30 px-2 py-1 text-[10px] text-muted-foreground">
                        <CheckCircle2 className="h-3 w-3 text-emerald-500/60" /> {tool}
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="text-[9px] font-medium uppercase tracking-wider text-muted-foreground">Governance</div>
                  <div className="mt-1 rounded bg-amber-500/5 border border-amber-500/20 px-2 py-1 text-[10px] text-amber-400">
                    <Lock className="mr-1 inline h-3 w-3" /> Approval required for kubectl exec
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Enterprise Scenarios ───

const SCENARIOS = [
  {
    icon: Zap,
    title: "Incident Response Automation",
    description: "Agents query Kubernetes clusters, search logs, correlate alerts via web-search, and execute remediation runbooks — with human approval gates for destructive actions.",
    tags: ["kubernetes", "messaging", "web-search", "code-exec"],
    metrics: { label: "Capability", value: "Parallel Fan-Out" },
  },
  {
    icon: Shield,
    title: "Continuous Compliance Auditing",
    description: "Deploy agents that scan cluster configurations, diff against policy baselines in Git, generate remediation PRs, and maintain audit trails with durable memory.",
    tags: ["git", "kubernetes", "documents", "rag"],
    metrics: { label: "Capability", value: "Full Audit Trail" },
  },
  {
    icon: GitBranch,
    title: "CI/CD Pipeline Intelligence",
    description: "Agents monitor GitHub repositories, analyze build patterns with code-exec, auto-rollback bad deploys via Kubernetes, and notify teams with root cause analysis.",
    tags: ["github-adapter", "git", "code-exec"],
    metrics: { label: "Capability", value: "DAG Pipelines" },
  },
  {
    icon: Database,
    title: "Cost Optimization at Scale",
    description: "Agents analyze resource utilization across clusters, query usage databases, research pricing with browser, and track savings over time with persistent memory.",
    tags: ["kubernetes", "database", "browser"],
    metrics: { label: "Capability", value: "Persistent Memory" },
  },
];

function EnterpriseScenariosSection() {
  return (
    <section id="scenarios" className="relative px-6 py-20 md:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Enterprise Use Cases</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Built for <span className="text-shimmer">Real Operations</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground">
            Not another chatbot wrapper. These are autonomous agents designed for the workflows
            that keep enterprises running — with memory, governance, and accountability baked in.
          </p>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          {SCENARIOS.map((scenario, i) => {
            const Icon = scenario.icon;
            return (
              <div
                key={scenario.title}
                className="landing-card group relative rounded-xl p-6 animate-slide-up"
                style={{ animationDelay: `${i * 0.1}s` }}
              >
                <div className="flex items-start gap-4">
                  <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold text-foreground">{scenario.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{scenario.description}</p>
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {scenario.tags.map((tag) => (
                        <span key={tag} className="rounded-full border border-border/40 bg-muted/30 px-2.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                {/* Metric badge */}
                <div className="absolute right-6 top-6 text-right">
                  <div className="text-xl font-bold text-primary">{scenario.metrics.value}</div>
                  <div className="text-[10px] text-muted-foreground">{scenario.metrics.label}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Feature Bento Grid ───

const FEATURES = [
  {
    icon: BrainCircuit,
    title: "Durable Memory",
    description: "Agents persist knowledge across sessions. Memory records survive restarts, pod evictions, and cluster upgrades. Promote, edit, or revoke any memory.",
    span: "md:col-span-2",
  },
  {
    icon: RefreshCw,
    title: "Session Continuity",
    description: "Pause an agent mid-conversation, come back hours later. The exact state, context window, and tool results are restored from checkpoint.",
  },
  {
    icon: Lock,
    title: "Tool Governance",
    description: "Define fine-grained policies: which tools an agent can invoke, which require human approval, and which are forbidden. RBAC at the tool level.",
  },
  {
    icon: Network,
    title: "MCP Sidecar Ecosystem",
    description: "Attach Model Context Protocol servers as sidecars. Kubernetes, Git, GitHub, Messaging, Browser, RAG — agents compose tools at runtime.",
  },
  {
    icon: Workflow,
    title: "Visual Workflow Composer",
    description: "Build multi-agent pipelines with a drag-and-drop DAG editor. Chain agents, add approval gates, fan-out parallel steps.",
  },
  {
    icon: Eye,
    title: "Real-Time Observability",
    description: "Stream logs, inspect memory, trace tool calls, and monitor token usage. Every agent action is auditable and attributable.",
    span: "md:col-span-2",
  },
];

function FeatureBentoSection() {
  return (
    <section id="features" className="relative px-6 py-20 md:py-32">
      {/* Background glow */}
      <div
        className="glow-orb left-1/2 top-1/2 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2"
        style={{ background: "oklch(0.65 0.13 175 / 0.05)" }}
      />

      <div className="relative mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Platform Features</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Everything You Need to <span className="text-shimmer">Ship Agents</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground">
            From development to production. A complete control plane for Kubernetes-native AI agent operations.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map((feature, i) => {
            const Icon = feature.icon;
            return (
              <div
                key={feature.title}
                className={`landing-card group rounded-xl p-6 ${feature.span || ""} animate-slide-up`}
                style={{ animationDelay: `${i * 0.08}s` }}
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-foreground">{feature.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{feature.description}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Animated Workflow Demo ───

interface WorkflowStep {
  id: string;
  label: string;
  sublabel: string;
  icon: typeof Bot;
  x: number;
  y: number;
}

const WORKFLOW_STEPS: WorkflowStep[] = [
  { id: "trigger", label: "Alert Received", sublabel: "Webhook trigger", icon: Zap, x: 50, y: 150 },
  { id: "triage", label: "Triage Agent", sublabel: "Analyze & correlate", icon: BrainCircuit, x: 280, y: 80 },
  { id: "metrics", label: "Fetch Logs", sublabel: "kubernetes + web-search", icon: Eye, x: 280, y: 220 },
  { id: "decision", label: "Approval Gate", sublabel: "Human review required", icon: Shield, x: 510, y: 150 },
  { id: "remediate", label: "Remediate", sublabel: "Execute runbook", icon: Workflow, x: 740, y: 100 },
  { id: "notify", label: "Notify Team", sublabel: "messaging sidecar", icon: MessageSquare, x: 740, y: 200 },
];

const WORKFLOW_EDGES: [string, string][] = [
  ["trigger", "triage"],
  ["trigger", "metrics"],
  ["triage", "decision"],
  ["metrics", "decision"],
  ["decision", "remediate"],
  ["decision", "notify"],
];

function WorkflowDemo() {
  const [activeStep, setActiveStep] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setActiveStep((prev) => (prev + 1) % WORKFLOW_STEPS.length);
    }, 2000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const stepMap = new Map(WORKFLOW_STEPS.map((s) => [s.id, s]));

  return (
    <section id="workflows" className="relative px-6 py-20 md:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Workflow Orchestration</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Agent Pipelines <span className="text-shimmer">in Action</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground">
            Real incident response workflow: from alert to resolution. Each node is an autonomous
            agent with its own memory, tools, and governance policy.
          </p>
        </div>

        <div className="landing-card mx-auto max-w-4xl overflow-hidden rounded-2xl p-4 md:p-8">
          {/* SVG workflow diagram */}
          <div className="relative overflow-x-auto">
            <svg
              viewBox="0 0 850 300"
              className="mx-auto h-auto w-full max-w-[850px]"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* Edges */}
              {WORKFLOW_EDGES.map(([fromId, toId]) => {
                const from = stepMap.get(fromId)!;
                const to = stepMap.get(toId)!;
                const fromX = from.x + 90;
                const fromY = from.y + 25;
                const toX = to.x;
                const toY = to.y + 25;
                const midX = (fromX + toX) / 2;
                const isActive =
                  WORKFLOW_STEPS[activeStep]?.id === fromId ||
                  WORKFLOW_STEPS[activeStep]?.id === toId;

                return (
                  <path
                    key={`${fromId}-${toId}`}
                    d={`M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`}
                    stroke={isActive ? "oklch(0.65 0.13 175)" : "oklch(0.30 0.012 274)"}
                    strokeWidth={isActive ? 2 : 1.5}
                    strokeDasharray={isActive ? "6 4" : "none"}
                    className={isActive ? "connector-animated" : ""}
                    opacity={isActive ? 1 : 0.5}
                  />
                );
              })}

              {/* Nodes */}
              {WORKFLOW_STEPS.map((step, i) => {
                const Icon = step.icon;
                const isActive = activeStep === i;
                return (
                  <g key={step.id}>
                    {/* Pulse ring when active */}
                    {isActive && (
                      <rect
                        x={step.x - 4}
                        y={step.y - 4}
                        width={98}
                        height={58}
                        rx={14}
                        fill="none"
                        stroke="oklch(0.65 0.13 175 / 0.4)"
                        strokeWidth={2}
                        style={{ animation: "landing-pulse 2s ease-out infinite" }}
                      />
                    )}
                    {/* Node background */}
                    <rect
                      x={step.x}
                      y={step.y}
                      width={90}
                      height={50}
                      rx={10}
                      fill={isActive ? "oklch(0.22 0.020 274)" : "oklch(0.185 0.011 274)"}
                      stroke={isActive ? "oklch(0.65 0.13 175 / 0.6)" : "oklch(0.30 0.012 274 / 0.6)"}
                      strokeWidth={isActive ? 1.5 : 1}
                    />
                    {/* Icon */}
                    <foreignObject x={step.x + 8} y={step.y + 8} width={16} height={16}>
                      <Icon
                        className={`h-4 w-4 ${isActive ? "text-primary" : "text-muted-foreground"}`}
                        style={{ display: "block" }}
                      />
                    </foreignObject>
                    {/* Label */}
                    <text
                      x={step.x + 30}
                      y={step.y + 20}
                      fill={isActive ? "oklch(0.95 0.006 274)" : "oklch(0.70 0.015 274)"}
                      fontSize={9}
                      fontWeight={600}
                      fontFamily="var(--font-sans)"
                    >
                      {step.label}
                    </text>
                    {/* Sublabel */}
                    <text
                      x={step.x + 10}
                      y={step.y + 38}
                      fill="oklch(0.50 0.010 274)"
                      fontSize={7.5}
                      fontFamily="var(--font-sans)"
                    >
                      {step.sublabel}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>

          {/* Status bar */}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-4 rounded-lg border border-border/30 bg-background/50 px-4 py-3">
            <div className="flex items-center gap-6 text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Timer className="h-3.5 w-3.5 text-primary" />
                Execution: 4m 23s
              </span>
              <span className="flex items-center gap-1.5">
                <Bot className="h-3.5 w-3.5 text-primary" />
                4 agents active
              </span>
              <span className="flex items-center gap-1.5">
                <Lock className="h-3.5 w-3.5 text-amber-500" />
                1 approval pending
              </span>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-3 py-1 text-[11px] font-medium text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-breathe-pulse" />
              Pipeline Running
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Metrics Strip ───

const METRICS = [
  { value: "10", label: "MCP Sidecars" },
  { value: "42+", label: "Tools Available" },
  { value: "4", label: "Kubernetes CRDs" },
  { value: "2-Layer", label: "Durable Memory" },
];

function MetricsStrip() {
  return (
    <section className="relative border-y border-border/30 px-6 py-16">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4">
        {METRICS.map((metric, i) => (
          <div key={metric.label} className="text-center animate-slide-up" style={{ animationDelay: `${i * 0.1}s` }}>
            <div className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">{metric.value}</div>
            <div className="mt-1 text-xs font-medium text-muted-foreground">{metric.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

// ─── Architecture Strip ───

function ArchitectureStrip() {
  const layers = [
    { icon: Globe, label: "API Gateway", description: "Unified routing, auth, rate limiting" },
    { icon: Bot, label: "Agent Runtimes", description: "OpenCode, Goose, A2A" },
    { icon: BrainCircuit, label: "Memory Engine", description: "Persistent, searchable, governed" },
    { icon: Server, label: "Kubernetes Operator", description: "CRD-native, self-healing" },
  ];

  return (
    <section className="relative px-6 py-20 md:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Architecture</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
            Kubernetes-Native <span className="text-shimmer">from the Ground Up</span>
          </h2>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {layers.map((layer, i) => {
            const Icon = layer.icon;
            return (
              <div
                key={layer.label}
                className="landing-card group flex flex-col items-center rounded-xl p-6 text-center animate-slide-up"
                style={{ animationDelay: `${i * 0.1}s` }}
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                  <Icon className="h-6 w-6" />
                </div>
                <h3 className="mt-4 text-sm font-semibold text-foreground">{layer.label}</h3>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{layer.description}</p>

                {/* Connector arrow (except last) */}
                {i < layers.length - 1 && (
                  <div className="absolute -right-2 top-1/2 hidden -translate-y-1/2 text-border/60 lg:block">
                    <ChevronRight className="h-4 w-4" />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Bottom CTA ───

function BottomCTA({ onLogin }: { onLogin: () => void }) {
  return (
    <section className="relative overflow-hidden px-6 py-24 md:py-36">
      {/* Glow */}
      <div
        className="glow-orb left-1/2 top-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2"
        style={{ background: "oklch(0.65 0.13 175 / 0.08)" }}
      />

      <div className="relative mx-auto max-w-3xl text-center">
        <h2 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
          Ready to <span className="text-shimmer">Orchestrate</span>?
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base text-muted-foreground">
          Initialize your workspace, deploy your first agent, and let it handle the toil.
          From incident triage to compliance auditing — in minutes, not months.
        </p>
        <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
          <button
            onClick={onLogin}
            className="glow-button group flex items-center gap-2 rounded-xl bg-primary px-8 py-3.5 text-sm font-semibold text-primary-foreground"
          >
            Get Started Free
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          <button
            onClick={() => document.getElementById("scenarios")?.scrollIntoView({ behavior: "smooth" })}
            className="flex items-center gap-2 rounded-xl border border-border/50 bg-card/30 px-6 py-3.5 text-sm font-medium text-foreground backdrop-blur-sm transition-colors hover:bg-card/60"
          >
            <Globe className="h-4 w-4 text-primary" />
            Explore Use Cases
          </button>
        </div>
      </div>
    </section>
  );
}

// ─── Footer ───

function Footer() {
  return (
    <footer className="border-t border-border/30 px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 sm:flex-row">
        <div className="flex items-center gap-2">
          <LayoutPanelTop className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">{BRAND.name}</span>
        </div>
        <div className="flex items-center gap-6 text-xs text-muted-foreground">
          <a href="#" className="transition-colors hover:text-foreground">Documentation</a>
          <a href="#" className="transition-colors hover:text-foreground">GitHub</a>
          <a href="#" className="transition-colors hover:text-foreground">Status</a>
        </div>
        <p className="text-xs text-muted-foreground">
          &copy; {new Date().getFullYear()} {BRAND.name}. All rights reserved.
        </p>
      </div>
    </footer>
  );
}

// ─── Main LandingPage ───

export function LandingPage({ onLogin }: LandingPageProps) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <AnnouncementBar />
      <Navbar onLogin={onLogin} />
      <HeroSection onLogin={onLogin} />
      <MockUIPreview />
      <EnterpriseScenariosSection />
      <FeatureBentoSection />
      <WorkflowDemo />
      <MetricsStrip />
      <ArchitectureStrip />
      <BottomCTA onLogin={onLogin} />
      <Footer />
    </div>
  );
}

export default LandingPage;
