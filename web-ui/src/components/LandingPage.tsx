import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Bot,
  BrainCircuit,
  CheckCircle2,
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
    <div className="border-b border-border/20 bg-card/30 px-4 py-2 text-center">
      <a
        href="#features"
        className="group inline-flex items-center gap-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">New</span>
        <span>Durable Memory, Session Continuity & Tool Governance are live</span>
        <ArrowRight className="h-3 w-3 text-primary transition-transform group-hover:translate-x-0.5" />
      </a>
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
      {/* Decorative glow orbs — teal brand palette only */}
      <div
        className="glow-orb -top-32 left-1/4 h-[500px] w-[500px]"
        style={{
          background: "oklch(0.65 0.13 175 / 0.12)",
          animation: "glow-breathe 8s ease-in-out infinite",
        }}
      />
      <div
        className="glow-orb -right-20 top-20 h-[350px] w-[350px]"
        style={{
          background: "oklch(0.60 0.10 190 / 0.08)",
          animation: "glow-breathe 10s ease-in-out infinite 3s",
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
          <span className="text-gradient-hero">That Actually Ship</span>
        </h1>

        {/* Subtitle */}
        <p className="mx-auto mt-6 max-w-2xl text-base text-muted-foreground sm:text-lg md:text-xl animate-slide-up" style={{ animationDelay: "0.1s" }}>
          Deploy autonomous AI agents on Kubernetes with durable memory, governance guardrails,
          and workflow orchestration — from incident response to compliance.
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
        <p className="mb-6 text-center text-xs font-semibold uppercase tracking-widest text-primary animate-fade-in">
          Live Preview
        </p>
        <div
          className="mock-window animate-scale-in"
          style={{ animationDelay: "0.3s" }}
        >
          {/* Title bar */}
          <div className="mock-titlebar">
            <div className="mock-dot bg-muted-foreground/30" />
            <div className="mock-dot bg-muted-foreground/30" />
            <div className="mock-dot bg-muted-foreground/30" />
            <div className="ml-4 flex-1 rounded-md bg-background/50 px-3 py-1 text-[11px] text-muted-foreground">
              kubesynth.io/workspace
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
    metrics: { label: "MTTR reduction", value: "80%" },
  },
  {
    icon: Shield,
    title: "Continuous Compliance Auditing",
    description: "Deploy agents that scan cluster configurations, diff against policy baselines in Git, generate remediation PRs, and maintain audit trails with durable memory.",
    tags: ["git", "kubernetes", "documents", "rag"],
    metrics: { label: "Coverage", value: "24/7" },
  },
  {
    icon: GitBranch,
    title: "CI/CD Pipeline Intelligence",
    description: "Agents monitor GitHub repositories, analyze build patterns with code-exec, auto-rollback bad deploys via Kubernetes, and notify teams with root cause analysis.",
    tags: ["github-adapter", "git", "code-exec"],
    metrics: { label: "Pipelines", value: "Multi-Stage" },
  },
  {
    icon: Database,
    title: "Cost Optimization at Scale",
    description: "Agents analyze resource utilization across clusters, query usage databases, research pricing with browser, and track savings over time with persistent memory.",
    tags: ["kubernetes", "database", "browser"],
    metrics: { label: "Savings tracked", value: "Ongoing" },
  },
];

function EnterpriseScenariosSection() {
  return (
    <section id="scenarios" className="relative px-6 py-20 md:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Enterprise Use Cases</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Built for <span className="text-primary">Real Operations</span>
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
                style={{ animationDelay: `${i * 0.08}s` }}
              >
                <div className="flex items-start gap-4">
                  <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/20">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center justify-between gap-3">
                      <h3 className="text-lg font-semibold text-foreground">{scenario.title}</h3>
                      <span className="flex-shrink-0 rounded-full border border-primary/20 bg-primary/5 px-2.5 py-0.5 text-[10px] font-semibold text-primary">
                        {scenario.metrics.value}
                      </span>
                    </div>
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
        className="glow-orb left-1/2 top-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2"
        style={{ background: "oklch(0.65 0.13 175 / 0.03)" }}
      />

      <div className="relative mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Platform Features</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Everything You Need to <span className="text-primary">Ship Agents</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground">
            From development to production. A complete control plane for Kubernetes-native AI agent operations.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map((feature, i) => {
            const Icon = feature.icon;
            const isHero = !!feature.span;
            return (
              <div
                key={feature.title}
                className={`landing-card group rounded-xl p-6 ${feature.span || ""} animate-slide-up ${isHero ? "border-primary/10" : ""}`}
                style={{ animationDelay: `${i * 0.08}s` }}
              >
                <div className="flex items-start gap-4">
                  <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg transition-colors group-hover:bg-primary/20 ${isHero ? "bg-primary/15 ring-1 ring-primary/20" : "bg-primary/10"} text-primary`}>
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-base font-semibold text-foreground">{feature.title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{feature.description}</p>
                  </div>
                </div>
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
  kind: "trigger" | "agent" | "gate" | "action";
}

const NODE_W = 175;
const NODE_H = 66;

const WORKFLOW_STEPS: WorkflowStep[] = [
  { id: "trigger", label: "Alert Received", sublabel: "Webhook trigger", icon: Zap, x: 20, y: 122, kind: "trigger" },
  { id: "triage", label: "Triage Agent", sublabel: "Analyze & correlate", icon: BrainCircuit, x: 250, y: 30, kind: "agent" },
  { id: "metrics", label: "Fetch Logs", sublabel: "kubernetes + web-search", icon: Eye, x: 250, y: 214, kind: "agent" },
  { id: "decision", label: "Approval Gate", sublabel: "Human review required", icon: Shield, x: 500, y: 122, kind: "gate" },
  { id: "remediate", label: "Remediate", sublabel: "Execute runbook", icon: Workflow, x: 760, y: 42, kind: "action" },
  { id: "notify", label: "Notify Team", sublabel: "messaging sidecar", icon: MessageSquare, x: 760, y: 202, kind: "action" },
];

const WORKFLOW_EDGES: [string, string][] = [
  ["trigger", "triage"],
  ["trigger", "metrics"],
  ["triage", "decision"],
  ["metrics", "decision"],
  ["decision", "remediate"],
  ["decision", "notify"],
];

const NODE_COLORS: Record<WorkflowStep["kind"], { bg: string; bgActive: string; border: string; borderActive: string }> = {
  trigger:  { bg: "oklch(0.185 0.011 274)", bgActive: "oklch(0.22 0.018 274)", border: "oklch(0.30 0.012 274 / 0.6)", borderActive: "oklch(0.65 0.13 175 / 0.7)" },
  agent:    { bg: "oklch(0.185 0.011 274)", bgActive: "oklch(0.22 0.018 274)", border: "oklch(0.30 0.012 274 / 0.6)", borderActive: "oklch(0.65 0.13 175 / 0.7)" },
  gate:     { bg: "oklch(0.19 0.015 50)",   bgActive: "oklch(0.23 0.025 50)",  border: "oklch(0.35 0.03 50 / 0.5)",   borderActive: "oklch(0.72 0.12 85 / 0.6)" },
  action:   { bg: "oklch(0.185 0.011 274)", bgActive: "oklch(0.22 0.018 274)", border: "oklch(0.30 0.012 274 / 0.6)", borderActive: "oklch(0.65 0.13 175 / 0.7)" },
};

function WorkflowDemo() {
  const [activeStep, setActiveStep] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setActiveStep((prev) => (prev + 1) % WORKFLOW_STEPS.length);
    }, 2500);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const stepMap = new Map(WORKFLOW_STEPS.map((s) => [s.id, s]));

  return (
    <section id="workflows" className="relative px-6 py-20 md:py-32">
      <div className="mx-auto max-w-7xl">
        <div className="mb-16 text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-primary">Workflow Orchestration</p>
          <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
            Agent Pipelines <span className="text-primary">in Action</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base text-muted-foreground">
            Real incident response workflow: from alert to resolution. Each node is an autonomous
            agent with its own memory, tools, and governance policy.
          </p>
        </div>

        <div className="landing-card mx-auto max-w-5xl overflow-hidden rounded-2xl p-6 md:p-10">
          {/* SVG workflow diagram */}
          <div className="relative overflow-x-auto">
            <svg
              viewBox="0 0 960 310"
              className="mx-auto h-auto w-full max-w-[960px]"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              role="img"
              aria-label="Animated workflow diagram showing an incident response pipeline with 6 steps"
            >
              <defs>
                <filter id="node-glow">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>

              {/* Edges */}
              {WORKFLOW_EDGES.map(([fromId, toId]) => {
                const from = stepMap.get(fromId)!;
                const to = stepMap.get(toId)!;
                const fromX = from.x + NODE_W;
                const fromY = from.y + NODE_H / 2;
                const toX = to.x;
                const toY = to.y + NODE_H / 2;
                const midX = (fromX + toX) / 2;
                const isActive =
                  WORKFLOW_STEPS[activeStep]?.id === fromId ||
                  WORKFLOW_STEPS[activeStep]?.id === toId;

                return (
                  <g key={`${fromId}-${toId}`}>
                    {/* Base edge */}
                    <path
                      d={`M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`}
                      stroke="oklch(0.28 0.010 274)"
                      strokeWidth={2}
                      opacity={0.6}
                    />
                    {/* Active glow overlay */}
                    {isActive && (
                      <path
                        d={`M ${fromX} ${fromY} C ${midX} ${fromY}, ${midX} ${toY}, ${toX} ${toY}`}
                        stroke="oklch(0.65 0.13 175)"
                        strokeWidth={2.5}
                        strokeDasharray="8 6"
                        className="connector-animated"
                        opacity={0.8}
                      />
                    )}
                  </g>
                );
              })}

              {/* Nodes */}
              {WORKFLOW_STEPS.map((step, i) => {
                const Icon = step.icon;
                const isActive = activeStep === i;
                const colors = NODE_COLORS[step.kind];
                const isGate = step.kind === "gate";

                return (
                  <g key={step.id}>
                    {/* Active glow shadow */}
                    {isActive && (
                      <rect
                        x={step.x - 2}
                        y={step.y - 2}
                        width={NODE_W + 4}
                        height={NODE_H + 4}
                        rx={14}
                        fill="none"
                        stroke={isGate ? "oklch(0.72 0.12 85 / 0.3)" : "oklch(0.65 0.13 175 / 0.3)"}
                        strokeWidth={2}
                        filter="url(#node-glow)"
                      />
                    )}

                    {/* Node body */}
                    <rect
                      x={step.x}
                      y={step.y}
                      width={NODE_W}
                      height={NODE_H}
                      rx={12}
                      fill={isActive ? colors.bgActive : colors.bg}
                      stroke={isActive ? colors.borderActive : colors.border}
                      strokeWidth={isActive ? 1.5 : 1}
                    />

                    {/* Icon circle */}
                    <circle
                      cx={step.x + 24}
                      cy={step.y + NODE_H / 2 - 3}
                      r={14}
                      fill={isActive
                        ? (isGate ? "oklch(0.72 0.12 85 / 0.12)" : "oklch(0.65 0.13 175 / 0.12)")
                        : "oklch(0.25 0.010 274 / 0.6)"}
                    />
                    <foreignObject x={step.x + 14} y={step.y + NODE_H / 2 - 13} width={20} height={20}>
                      <Icon
                        className={`h-5 w-5 ${isActive ? (isGate ? "text-amber-400" : "text-primary") : "text-muted-foreground"}`}
                        style={{ display: "block" }}
                      />
                    </foreignObject>

                    {/* Label */}
                    <text
                      x={step.x + 46}
                      y={step.y + 27}
                      fill={isActive ? "oklch(0.95 0.006 274)" : "oklch(0.72 0.012 274)"}
                      fontSize={11.5}
                      fontWeight={600}
                      fontFamily="var(--font-sans)"
                    >
                      {step.label}
                    </text>

                    {/* Sublabel */}
                    <text
                      x={step.x + 46}
                      y={step.y + 44}
                      fill={isActive ? "oklch(0.55 0.010 274)" : "oklch(0.45 0.008 274)"}
                      fontSize={9.5}
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
          <div className="mt-8 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border/20 bg-background/40 px-5 py-3.5">
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
  { value: "10+", label: "MCP Sidecars", icon: Server },
  { value: "42+", label: "Tools Available", icon: Zap },
  { value: "4", label: "Kubernetes CRDs", icon: Network },
  { value: "100%", label: "Open Source", icon: Globe },
];

function MetricsStrip() {
  return (
    <section className="relative border-y border-border/30 px-6 py-16">
      <div className="mx-auto grid max-w-5xl grid-cols-2 gap-8 md:grid-cols-4">
        {METRICS.map((metric, i) => {
          const Icon = metric.icon;
          return (
            <div key={metric.label} className="text-center animate-slide-up" style={{ animationDelay: `${i * 0.08}s` }}>
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon className="h-5 w-5" />
              </div>
              <div className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">{metric.value}</div>
              <div className="mt-1 text-xs font-medium text-muted-foreground">{metric.label}</div>
            </div>
          );
        })}
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
        className="glow-orb left-1/2 top-1/2 h-[400px] w-[400px] -translate-x-1/2 -translate-y-1/2"
        style={{ background: "oklch(0.65 0.13 175 / 0.06)" }}
      />

      <div className="relative mx-auto max-w-3xl text-center">
        <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
          <Workflow className="h-7 w-7" />
        </div>
        <h2 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl md:text-5xl">
          Ready to <span className="text-primary">Orchestrate</span>?
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-base text-muted-foreground">
          Initialize your workspace and deploy your first agent in minutes.
          Start with incident triage, compliance, or bring your own workflow.
        </p>
        <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
          <button
            onClick={onLogin}
            className="glow-button group flex items-center gap-2 rounded-xl bg-primary px-8 py-3.5 text-sm font-semibold text-primary-foreground"
          >
            Get Started Free
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          <a
            href="https://github.com/kubemininions/kubemininions"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl border border-border/50 bg-card/30 px-6 py-3.5 text-sm font-medium text-foreground backdrop-blur-sm transition-colors hover:bg-card/60"
          >
            <GitBranch className="h-4 w-4 text-primary" />
            View on GitHub
          </a>
        </div>
      </div>
    </section>
  );
}

// ─── Footer ───

function Footer() {
  return (
    <footer className="border-t border-border/30 px-6 py-12">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {/* Brand */}
          <div className="sm:col-span-2 lg:col-span-1">
            <div className="flex items-center gap-2">
              <LayoutPanelTop className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold text-foreground">{BRAND.name}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground max-w-[240px]">
              Kubernetes-native AI agent orchestration with durable memory, governance, and enterprise workflow automation.
            </p>
          </div>

          {/* Product */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Product</h4>
            <ul className="mt-3 space-y-2 text-xs text-muted-foreground">
              <li><a href="#features" className="transition-colors hover:text-foreground">Features</a></li>
              <li><a href="#scenarios" className="transition-colors hover:text-foreground">Use Cases</a></li>
              <li><a href="#workflows" className="transition-colors hover:text-foreground">Workflows</a></li>
            </ul>
          </div>

          {/* Resources */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Resources</h4>
            <ul className="mt-3 space-y-2 text-xs text-muted-foreground">
              <li><a href="#" className="transition-colors hover:text-foreground">Documentation</a></li>
              <li><a href="https://github.com/kubemininions/kubemininions" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-foreground">GitHub</a></li>
              <li><a href="#" className="transition-colors hover:text-foreground">Changelog</a></li>
            </ul>
          </div>

          {/* Community */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Community</h4>
            <ul className="mt-3 space-y-2 text-xs text-muted-foreground">
              <li><a href="#" className="transition-colors hover:text-foreground">Contributing</a></li>
              <li><a href="#" className="transition-colors hover:text-foreground">Security</a></li>
              <li><a href="#" className="transition-colors hover:text-foreground">License</a></li>
            </ul>
          </div>
        </div>

        <div className="mt-10 flex items-center justify-between border-t border-border/20 pt-6">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} {BRAND.name}. Open source under Apache 2.0.
          </p>
          <a href="#" className="text-xs text-muted-foreground transition-colors hover:text-foreground">Status</a>
        </div>
      </div>
    </footer>
  );
}

// ─── Main LandingPage ───

export function LandingPage({ onLogin }: LandingPageProps) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground focus:text-sm focus:font-medium">
        Skip to main content
      </a>
      <AnnouncementBar />
      <Navbar onLogin={onLogin} />
      <main id="main-content">
        <HeroSection onLogin={onLogin} />
        <MockUIPreview />
        <div className="mx-auto max-w-5xl px-6"><hr className="border-border/15" /></div>
        <EnterpriseScenariosSection />
        <div className="mx-auto max-w-5xl px-6"><hr className="border-border/15" /></div>
        <FeatureBentoSection />
        <div className="mx-auto max-w-5xl px-6"><hr className="border-border/15" /></div>
        <WorkflowDemo />
        <MetricsStrip />
        <BottomCTA onLogin={onLogin} />
      </main>
      <Footer />
    </div>
  );
}

export default LandingPage;
