import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { motion, useInView, AnimatePresence } from "framer-motion";
import {
  ArrowRight, Bot, BrainCircuit, CheckCircle2, Database, GitBranch,
  LayoutPanelTop, Lock, Network, Play, RefreshCw,
  Server, Shield, Workflow, Zap, Terminal, Copy,
  Boxes, Code, Puzzle, Activity, FileCode2, Eye,
  BookOpen, Cpu, Gauge, AlertTriangle, Wrench,
  MonitorDot, Layers, Radio, FolderTree, ChevronRight,
} from "lucide-react";
import { BRAND } from "@/lib/brand";

const DocumentationPanel = lazy(() =>
  import("./DocumentationPanel").then((m) => ({ default: m.DocumentationPanel })),
);

// ─── Types ───

interface LandingPageProps {
  onLogin: () => void;
}

// ─── Animation Variants ───

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.05 },
  },
} as const;

const itemVariants = {
  hidden: { opacity: 0, y: 24 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.55, ease: [0.2, 0, 0.38, 0.9] as [number, number, number, number] },
  },
};

const fadeIn = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.5 } },
};

// ─── Terminal Types ───

interface TerminalLine {
  text: string;
  color?: string;
  prefix?: string;
  type?: "input" | "output" | "blank";
}

const colorMap: Record<string, string> = {
  comment: "text-[oklch(0.62_0.01_264)]",
  command: "text-[oklch(0.75_0.12_188)]",
  string: "text-[oklch(0.76_0.16_154)]",
  flag: "text-[oklch(0.82_0.16_84)]",
  output: "text-[oklch(0.82_0.01_264)]",
  yamlKey: "text-[oklch(0.75_0.12_308)]",
  yamlVal: "text-[oklch(0.85_0.01_264)]",
  prompt: "text-[oklch(0.76_0.16_154)]",
  list: "text-[oklch(0.85_0.01_264)]",
};

// ─── Navbar ───

function Navbar({
  onOpenDocs,
  docsMode,
  onBackToLanding,
  onSectionClick,
}: {
  onOpenDocs: () => void;
  docsMode: boolean;
  onBackToLanding: () => void;
  onSectionClick: (sectionId: string) => void;
}) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return (
    <nav
      className={`sticky top-0 z-50 border-b transition-all duration-300 ${
        scrolled
          ? "border-[oklch(0.3_0.01_264)] bg-[oklch(0.14_0.008_264/0.92)] shadow-lg shadow-black/20 backdrop-blur-xl"
          : "border-transparent bg-[oklch(0.14_0.008_264/0.6)] backdrop-blur-sm"
      }`}
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[oklch(0.708_0.101_188)] text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)]">
            <LayoutPanelTop className="h-5 w-5" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-bold tracking-tight text-[oklch(0.958_0.004_264)]">
              {BRAND.name}
            </span>
            <span className="hidden text-xs font-medium text-[oklch(0.72_0.01_264)] sm:inline">
              {BRAND.tagline}
            </span>
          </div>
        </div>

        <div className="hidden items-center gap-8 text-sm font-medium text-[oklch(0.82_0.01_264)] md:flex">
          <button type="button" onClick={() => onSectionClick("features")} className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Features</button>
          <button type="button" onClick={() => onSectionClick("architecture")} className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Architecture</button>
          <button type="button" onClick={() => onSectionClick("install")} className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Install</button>
          <button
            type="button"
            onClick={onOpenDocs}
            className={`transition-colors ${docsMode ? "text-[oklch(0.708_0.101_188)]" : "hover:text-[oklch(0.708_0.101_188)]"}`}
          >
            Docs
          </button>
        </div>

        <div className="flex items-center gap-3">
          {docsMode && (
            <button
              type="button"
              onClick={onBackToLanding}
              className="rounded-lg px-3 py-2 text-sm font-medium text-[oklch(0.82_0.01_264)] transition-colors hover:text-[oklch(0.958_0.004_264)]"
            >
              Back
            </button>
          )}
          <a
            href="https://github.com/ykbytes/kubesynapse.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg px-3 py-2 text-sm font-medium text-[oklch(0.82_0.01_264)] transition-colors hover:text-[oklch(0.958_0.004_264)]"
          >
            GitHub
          </a>
        </div>
      </div>
    </nav>
  );
}

// ─── Hero Section ───

function HeroSection({ onOpenDocs }: { onOpenDocs: () => void }) {
  return (
    <section className="relative overflow-hidden px-6 pb-20 pt-20 md:pb-28 md:pt-32">
      {/* Background grid */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(to right, oklch(0.958 0.004 264) 1px, transparent 1px), linear-gradient(to bottom, oklch(0.958 0.004 264) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
      />
      {/* Radial glow */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-0 h-[600px] w-[800px] -translate-x-1/2 -translate-y-1/3 rounded-full bg-[oklch(0.708_0.101_188/0.08)] blur-[100px]" />
      </div>

      <div className="relative mx-auto max-w-5xl text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-[oklch(0.708_0.101_188/0.3)] bg-[oklch(0.206_0.009_264/0.8)] px-4 py-1.5 text-xs font-semibold text-[oklch(0.708_0.101_188)] shadow-lg shadow-[oklch(0.708_0.101_188/0.1)] backdrop-blur-sm"
        >
          <span className="flex h-2 w-2 rounded-full bg-[oklch(0.76_0.16_154)] ring-2 ring-[oklch(0.76_0.16_154/0.3)]" />
          Kubernetes-Native AI Operations Platform
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="text-4xl font-extrabold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-5xl md:text-6xl lg:text-7xl"
        >
          Your Kubernetes Cluster&rsquo;s{" "}
          <span className="bg-gradient-to-r from-[oklch(0.708_0.101_188)] to-[oklch(0.742_0.132_233)] bg-clip-text text-transparent">
            AI Companion
          </span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mx-auto mt-6 max-w-2xl text-base text-[oklch(0.82_0.01_264)] sm:text-lg md:text-xl leading-relaxed"
        >
          The self-hosted command center for DevOps and IT operations.
          Deploy AI agents that automate incident response, infrastructure management,
          and deployment pipelines — all governed by Kubernetes-native CRDs.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="mt-6 flex flex-col items-center gap-4 sm:flex-row sm:justify-center"
        >
          <a
            href="#install"
            className="group flex items-center gap-2 rounded-xl bg-[oklch(0.708_0.101_188)] px-7 py-3.5 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)] transition-all hover:shadow-xl hover:shadow-[oklch(0.708_0.101_188/0.4)] active:scale-[0.98]"
          >
            <Terminal className="h-4 w-4" />
            Deploy with Helm
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </a>
          <button
            type="button"
            onClick={onOpenDocs}
            className="flex items-center gap-2 rounded-xl border border-[oklch(0.4_0.015_264)] bg-[oklch(0.206_0.009_264/0.8)] px-7 py-3.5 text-sm font-semibold text-[oklch(0.85_0.01_264)] shadow-sm backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.4)] hover:text-[oklch(0.958_0.004_264)]"
          >
            <BookOpen className="h-4 w-4 text-[oklch(0.708_0.101_188)]" />
            View Documentation
          </button>
        </motion.div>

        {/* Stats */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.8, duration: 0.6 }}
          className="mt-12 flex flex-wrap items-center justify-center gap-8 text-center"
        >
          {[
            { label: "CRD Types", value: "6" },
            { label: "MCP Sidecars", value: "11" },
            { label: "Runtimes", value: "2" },
            { label: "Self-Hosted", value: "100%" },
          ].map((stat) => (
            <div key={stat.label} className="flex flex-col">
              <span className="text-2xl font-bold text-[oklch(0.708_0.101_188)]">{stat.value}</span>
              <span className="text-xs text-[oklch(0.72_0.01_264)]">{stat.label}</span>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

// ─── Ecosystem Bar ───

function EcosystemCloud() {
  const tools = [
    { name: "Kubernetes", icon: Server },
    { name: "Helm", icon: Boxes },
    { name: "OpenCode", icon: Code },
    { name: "LiteLLM", icon: BrainCircuit },
    { name: "NATS", icon: Network },
    { name: "PostgreSQL", icon: Database },
    { name: "Redis", icon: Zap },
    { name: "Qdrant", icon: Database },
  ];

  return (
    <section className="border-y border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264/0.8)] px-6 py-12">
      <div className="mx-auto max-w-6xl">
        <p className="mb-8 text-center text-xs font-semibold uppercase tracking-widest text-[oklch(0.62_0.01_264)]">
          Built for the Kubernetes Ecosystem
        </p>
        <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-6">
          {tools.map((tool) => {
            const Icon = tool.icon;
            return (
              <motion.div
                key={tool.name}
                className="flex items-center gap-2 text-[oklch(0.68_0.01_264)]"
                whileHover={{ scale: 1.05, color: "oklch(0.708 0.101 188)" }}
                transition={{ duration: 0.2 }}
              >
                <Icon className="h-5 w-5" />
                <span className="text-sm font-medium">{tool.name}</span>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Problem Section ───

function ProblemSection() {
  const problems = [
    {
      icon: AlertTriangle,
      title: "Incidents Without Intelligence",
      description:
        "Alert fatigue is real. Your on-call team manually correlates logs, checks pod status, and guesses at root causes at 3 AM.",
    },
    {
      icon: Lock,
      title: "Ungoverned Automation",
      description:
        "AI tools without guardrails are dangerous in production. Token budgets, approval gates, and audit trails are afterthoughts.",
    },
    {
      icon: Layers,
      title: "Fragmented Tooling",
      description:
        "Deployment scripts, monitoring, security scanning, and capacity planning all live in separate silos with no unified intelligence layer.",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section className="px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            The Challenge
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Kubernetes Operations Deserve <span className="text-[oklch(0.72_0.01_264)]">Better</span>
          </motion.h2>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-3">
          {problems.map((p, i) => {
            const Icon = p.icon;
            return (
              <motion.div
                key={p.title}
                variants={itemVariants}
                initial="hidden"
                animate={inView ? "visible" : "hidden"}
                transition={{ delay: i * 0.1 }}
                className="group rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.6)] p-8 backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.4)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)]"
              >
                <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-[oklch(0.708_0.101_188/0.1)] text-[oklch(0.708_0.101_188)] ring-1 ring-[oklch(0.708_0.101_188/0.2)] transition-colors group-hover:bg-[oklch(0.708_0.101_188/0.15)]">
                  <Icon className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-semibold text-[oklch(0.958_0.004_264)]">{p.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-[oklch(0.82_0.01_264)]">{p.description}</p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── UI Preview Section ───

function UIPreviewSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [activeTab, setActiveTab] = useState<"composer" | "agents" | "activity" | "observatory">("composer");

  const tabs = [
    { key: "composer" as const, label: "Workflow Composer", icon: Workflow },
    { key: "agents" as const, label: "Agent Management", icon: Bot },
    { key: "activity" as const, label: "Live Activity", icon: Activity },
    { key: "observatory" as const, label: "Observatory", icon: Eye },
  ];

  return (
    <section className="px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-12 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            The Real Interface
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Operations Console Built for <span className="text-[oklch(0.708_0.101_188)]">Engineers</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            A faithful miniaturized replica of the real console: sticky glass top bar, workspace sidebar,
            and the same operational surfaces used for agents, workflows, live activity, and execution traces.
          </motion.p>
        </motion.div>

        <motion.div
          variants={itemVariants}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="mb-6 flex flex-wrap justify-center gap-2"
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium transition-all ${
                  isActive
                    ? "bg-[oklch(0.708_0.101_188/0.15)] text-[oklch(0.708_0.101_188)] ring-1 ring-[oklch(0.708_0.101_188/0.3)]"
                    : "text-[oklch(0.72_0.01_264)] hover:text-[oklch(0.85_0.01_264)] hover:bg-[oklch(0.252_0.010_264)]"
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </motion.div>

        <motion.div
          variants={fadeIn}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="overflow-hidden rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.164_0.007_264)] shadow-2xl shadow-black/30"
        >
          <div className="flex items-center gap-2 border-b border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264)] px-4 py-3">
            <div className="flex gap-1.5">
              <div className="h-3 w-3 rounded-full bg-[oklch(0.636_0.173_24/0.7)]" />
              <div className="h-3 w-3 rounded-full bg-[oklch(0.82_0.16_84/0.7)]" />
              <div className="h-3 w-3 rounded-full bg-[oklch(0.76_0.16_154/0.7)]" />
            </div>
            <span className="ml-4 text-xs text-[oklch(0.62_0.01_264)]">kubesynapse — console preview</span>
          </div>

          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3 }}
              className="min-h-[460px] p-1"
            >
              <ConsoleShowcase activeTab={activeTab} />
            </motion.div>
          </AnimatePresence>
        </motion.div>
      </div>
    </section>
  );
}

function ConsoleShowcase({ activeTab }: { activeTab: "composer" | "agents" | "activity" | "observatory" }) {
  return (
    <div className="flex h-[460px] overflow-hidden bg-[oklch(0.164_0.007_264)]">
      <div className="flex w-[15.5rem] shrink-0 flex-col border-r border-[oklch(0.296_0.011_264)] bg-[oklch(0.149_0.008_264/0.92)] backdrop-blur-xl">
        <div className="flex h-10 items-center justify-between border-b border-[oklch(0.296_0.011_264)] px-2.5">
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[oklch(0.72_0.012_264)]">Workspace</p>
            <p className="truncate text-sm font-semibold text-[oklch(0.952_0.004_264)]">
              {activeTab === "composer" ? "Composer" : activeTab === "agents" ? "Agents" : activeTab === "activity" ? "Workflows" : "Observatory"}
            </p>
          </div>
          <div className="h-8 w-8 rounded-xl border border-[oklch(0.32_0.011_264/0.7)] bg-[oklch(0.206_0.009_264/0.72)]" />
        </div>

        <div className="border-b border-[oklch(0.296_0.011_264)] px-1.5 py-1.5">
          <div className="space-y-0.5">
            {[
              { key: "agents", label: "Agents", icon: Bot, count: 12 },
              { key: "chat", label: "Chat", icon: Activity, count: 4 },
              { key: "workflows", label: "Workflows", icon: GitBranch, count: 8 },
              { key: "composer", label: "Composer", icon: Workflow, count: 3 },
              { key: "observatory", label: "Observatory", icon: Eye, count: 24 },
              { key: "docs", label: "Documentation", icon: BookOpen, count: 0 },
            ].map((view) => {
              const active =
                (activeTab === "composer" && view.key === "composer") ||
                (activeTab === "agents" && view.key === "agents") ||
                (activeTab === "activity" && view.key === "workflows") ||
                (activeTab === "observatory" && view.key === "observatory");
              const Icon = view.icon;
              return (
                <div
                  key={view.key}
                  className={`flex items-center gap-2 rounded-lg border px-2 py-1 text-xs font-medium ${
                    active
                      ? "border-[oklch(0.708_0.101_188/0.25)] bg-[oklch(0.708_0.101_188/0.14)] text-[oklch(0.952_0.004_264)] shadow-sm"
                      : "border-transparent text-[oklch(0.78_0.012_264)]"
                  }`}
                >
                  <Icon className={`h-4 w-4 shrink-0 ${active ? "text-[oklch(0.708_0.101_188)]" : "text-[oklch(0.78_0.012_264)]"}`} />
                  <span className="flex-1 text-left">{view.label}</span>
                  {view.count > 0 ? (
                    <span className={`flex h-5 min-w-[1.25rem] items-center justify-center rounded-full border px-1.5 text-[10px] font-semibold tabular-nums ${
                      active
                        ? "border-[oklch(0.708_0.101_188/0.25)] bg-[oklch(0.708_0.101_188/0.14)] text-[oklch(0.708_0.101_188)]"
                        : "border-[oklch(0.34_0.015_264)] bg-[oklch(0.252_0.01_264/0.7)] text-[oklch(0.78_0.012_264)]"
                    }`}>
                      {view.count}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex gap-1.5 border-b border-[oklch(0.296_0.011_264)] px-2.5 py-1.5">
          <div className="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-xl bg-[oklch(0.708_0.101_188)] text-[oklch(0.158_0.007_264)]">
            <span className="text-xs font-semibold">New</span>
          </div>
          <div className="h-8 w-8 rounded-xl border border-[oklch(0.38_0.015_264)] bg-[oklch(0.206_0.009_264/0.72)]" />
        </div>

        <div className="p-2.5">
          <div className="mb-2 rounded-xl border border-[oklch(0.38_0.015_264)] bg-[oklch(0.206_0.009_264/0.72)] px-3 py-2 text-[11px] text-[oklch(0.78_0.012_264)]">
            Search resources...
          </div>
          <div className="space-y-1.5">
            {[
              { title: "incident-triage", subtitle: "opencode • production", status: "running" },
              { title: "log-analyzer", subtitle: "pi • production", status: "running" },
              { title: "security-scan", subtitle: "opencode • security", status: activeTab === "agents" ? "pending" : "completed" },
            ].map((item, index) => (
              <div
                key={item.title}
                className={`rounded-xl border px-3 py-2 text-xs ${
                  index === 0
                    ? "border-[oklch(0.708_0.101_188/0.22)] bg-[oklch(0.708_0.101_188/0.08)]"
                    : "border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.46)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${
                    item.status === "running"
                      ? "bg-[oklch(0.76_0.16_154)]"
                      : item.status === "pending"
                        ? "bg-[oklch(0.82_0.16_84)]"
                        : "bg-[oklch(0.708_0.101_188)]"
                  }`} />
                  <span className="truncate font-medium text-[oklch(0.958_0.004_264)]">{item.title}</span>
                </div>
                <p className="mt-1 truncate text-[10px] text-[oklch(0.72_0.012_264)]">{item.subtitle}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-10 flex min-h-14 items-center justify-between gap-x-3 border-b border-[oklch(0.296_0.011_264)] bg-[oklch(0.149_0.008_264/0.88)] px-4 py-2 shadow-sm backdrop-blur-xl">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[calc(0.875rem+2px)] border border-[oklch(0.38_0.015_264)] bg-[oklch(0.206_0.009_264/0.72)] text-[oklch(0.708_0.101_188)] shadow-sm">
              <LayoutPanelTop className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-medium uppercase tracking-[0.24em] text-[oklch(0.72_0.012_264)]">Operations Console</p>
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-semibold text-[oklch(0.958_0.004_264)]">{BRAND.name}</span>
                <span className="hidden truncate text-xs text-[oklch(0.72_0.012_264)] lg:inline">{BRAND.tagline}</span>
              </div>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[oklch(0.76_0.16_154/0.2)] bg-[oklch(0.76_0.16_154/0.08)] px-2.5 py-1 text-[11px] font-medium text-[oklch(0.76_0.16_154)]">
              <span className="h-2 w-2 rounded-full bg-[oklch(0.76_0.16_154)]" />
              Healthy
            </span>
            <span className="inline-flex h-9 items-center rounded-xl border border-[oklch(0.38_0.015_264)] bg-[oklch(0.206_0.009_264/0.72)] px-3 font-mono text-[11px] text-[oklch(0.958_0.004_264)]">
              production
            </span>
            <div className="h-9 w-9 rounded-xl border border-[oklch(0.38_0.015_264)] bg-[oklch(0.206_0.009_264/0.72)]" />
            <div className="h-9 w-9 rounded-xl border border-[oklch(0.38_0.015_264)] bg-[oklch(0.206_0.009_264/0.72)]" />
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col p-3">
            {activeTab === "composer" && <FaithfulComposerPanel />}
            {activeTab === "agents" && <FaithfulAgentsPanel />}
            {activeTab === "activity" && <FaithfulActivityPanel />}
            {activeTab === "observatory" && <FaithfulObservatoryPanel />}
          </div>
          <div className="hidden w-[18rem] shrink-0 border-l border-[oklch(0.296_0.011_264)] bg-[oklch(0.149_0.008_264/0.72)] p-3 xl:block">
            <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[oklch(0.72_0.012_264)]">Inspector</p>
            <div className="mt-3 rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-4">
              <p className="text-xs font-semibold text-[oklch(0.958_0.004_264)]">
                {activeTab === "composer" ? "Selected Step" : activeTab === "agents" ? "Agent Detail" : activeTab === "activity" ? "Workflow Signal" : "Trace Summary"}
              </p>
              <div className="mt-3 space-y-2">
                {[
                  { label: activeTab === "composer" ? "Step" : activeTab === "agents" ? "Runtime" : activeTab === "activity" ? "Phase" : "Status", value: activeTab === "composer" ? "incident-triage" : activeTab === "agents" ? "opencode" : activeTab === "activity" ? "running" : "completed" },
                  { label: activeTab === "composer" ? "Depends On" : activeTab === "agents" ? "Model" : activeTab === "activity" ? "Connected" : "Duration", value: activeTab === "composer" ? "webhook-trigger" : activeTab === "agents" ? "claude-sonnet-4" : activeTab === "activity" ? "yes" : "2.4 s" },
                  { label: activeTab === "composer" ? "Approval" : activeTab === "agents" ? "Storage" : activeTab === "activity" ? "Events" : "Steps", value: activeTab === "composer" ? "required" : activeTab === "agents" ? "2Gi PVC" : activeTab === "activity" ? "18" : "4" },
                ].map((item) => (
                  <MetricChip key={item.label} label={item.label} value={item.value} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function FaithfulComposerPanel() {
  return (
    <div className="relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.164_0.007_264)]" style={{ backgroundImage: "radial-gradient(oklch(0.32 0.011 264 / 0.45) 1px, transparent 1px)", backgroundSize: "20px 20px" }}>
      {/* Floating toolbar */}
      <div className="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded-lg border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.9)] px-2 py-1.5 backdrop-blur-sm shadow-sm">
        <div className="flex h-6 w-6 items-center justify-center rounded border border-[oklch(0.38_0.015_264)] bg-[oklch(0.164_0.007_264)] text-[oklch(0.78_0.012_264)]">
          <Workflow className="h-3 w-3" />
        </div>
        <div className="h-4 w-px bg-[oklch(0.3_0.01_264)]" />
        <div className="flex h-6 w-6 items-center justify-center rounded border border-[oklch(0.38_0.015_264)] bg-[oklch(0.164_0.007_264)] text-[oklch(0.78_0.012_264)]">
          <RefreshCw className="h-3 w-3" />
        </div>
        <div className="flex h-6 w-6 items-center justify-center rounded border border-[oklch(0.38_0.015_264)] bg-[oklch(0.164_0.007_264)] text-[oklch(0.78_0.012_264)]">
          <Play className="h-3 w-3" />
        </div>
        <div className="h-4 w-px bg-[oklch(0.3_0.01_264)]" />
        <span className="text-[9px] font-medium text-[oklch(0.62_0.012_264)]">incident-response</span>
      </div>

      {/* Animated DAG edges */}
      <svg className="absolute inset-0 h-full w-full pointer-events-none" fill="none">
        {/* Trigger → incident-triage */}
        <motion.path d="M 165 200 C 230 200, 240 155, 310 155" stroke="oklch(0.708 0.101 188 / 0.5)" strokeWidth={2} strokeDasharray="6 4" animate={{ strokeDashoffset: [0, -20] }} transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }} />
        <circle cx="310" cy="155" r="3" fill="oklch(0.708 0.101 188 / 0.6)" />
        {/* Trigger → log-analyzer */}
        <motion.path d="M 165 200 C 230 200, 240 275, 310 275" stroke="oklch(0.708 0.101 188 / 0.5)" strokeWidth={2} strokeDasharray="6 4" animate={{ strokeDashoffset: [0, -20] }} transition={{ duration: 1.5, repeat: Infinity, ease: "linear", delay: 0.15 }} />
        <circle cx="310" cy="275" r="3" fill="oklch(0.708 0.101 188 / 0.6)" />
        {/* incident-triage → remediate */}
        <motion.path d="M 450 155 C 510 155, 520 215, 580 215" stroke="oklch(0.684 0.138 308 / 0.5)" strokeWidth={2} strokeDasharray="6 4" animate={{ strokeDashoffset: [0, -20] }} transition={{ duration: 1.5, repeat: Infinity, ease: "linear", delay: 0.3 }} />
        <circle cx="580" cy="215" r="3" fill="oklch(0.684 0.138 308 / 0.6)" />
        {/* log-analyzer → remediate */}
        <motion.path d="M 450 275 C 510 275, 520 215, 580 215" stroke="oklch(0.684 0.138 308 / 0.5)" strokeWidth={2} strokeDasharray="6 4" animate={{ strokeDashoffset: [0, -20] }} transition={{ duration: 1.5, repeat: Infinity, ease: "linear", delay: 0.45 }} />
      </svg>

      {/* Workflow Nodes — styled like real AgentNode cards */}
      <ComposerNode
        className="left-[40px] top-[170px]"
        icon={Radio}
        title="webhook-trigger"
        badge="trigger"
        badgeColor="bg-[oklch(0.82_0.16_84/0.15)] text-[oklch(0.82_0.16_84)] border-[oklch(0.82_0.16_84/0.25)]"
        borderColor="border-[oklch(0.82_0.16_84/0.4)]"
        iconColor="text-[oklch(0.82_0.16_84)]"
        subtitle="source: prometheus"
      />
      <ComposerNode
        className="left-[310px] top-[120px]"
        icon={Bot}
        title="incident-triage"
        badge="opencode"
        badgeColor="bg-[oklch(0.708_0.101_188/0.15)] text-[oklch(0.708_0.101_188)] border-[oklch(0.708_0.101_188/0.25)]"
        borderColor="border-[oklch(0.708_0.101_188/0.4)]"
        iconColor="text-[oklch(0.708_0.101_188)]"
        subtitle="claude-sonnet-4"
        status="running"
      />
      <ComposerNode
        className="left-[310px] top-[240px]"
        icon={Bot}
        title="log-analyzer"
        badge="pi"
        badgeColor="bg-[oklch(0.76_0.16_154/0.15)] text-[oklch(0.76_0.16_154)] border-[oklch(0.76_0.16_154/0.25)]"
        borderColor="border-[oklch(0.76_0.16_154/0.4)]"
        iconColor="text-[oklch(0.76_0.16_154)]"
        subtitle="gpt-4o"
        status="running"
      />
      <ComposerNode
        className="left-[580px] top-[180px]"
        icon={Shield}
        title="remediate"
        badge="approval"
        badgeColor="bg-[oklch(0.684_0.138_308/0.15)] text-[oklch(0.684_0.138_308)] border-[oklch(0.684_0.138_308/0.25)]"
        borderColor="border-[oklch(0.684_0.138_308/0.4)]"
        iconColor="text-[oklch(0.684_0.138_308)]"
        subtitle="requireApproval: true"
        status="waiting"
      />

      {/* Minimap in bottom-right */}
      <div className="absolute bottom-3 right-3 h-[60px] w-[100px] rounded-lg border border-[oklch(0.35_0.015_264)] bg-[oklch(0.149_0.008_264/0.85)] backdrop-blur-sm">
        <div className="p-1.5">
          <div className="h-1 w-3 rounded-sm bg-[oklch(0.82_0.16_84/0.4)]" style={{ marginLeft: "8px", marginTop: "16px" }} />
          <div className="flex gap-1" style={{ marginTop: "2px" }}>
            <div className="h-1 w-3 rounded-sm bg-[oklch(0.708_0.101_188/0.4)]" style={{ marginLeft: "24px" }} />
          </div>
          <div className="h-1 w-3 rounded-sm bg-[oklch(0.708_0.101_188/0.4)]" style={{ marginLeft: "24px", marginTop: "2px" }} />
          <div className="h-1 w-3 rounded-sm bg-[oklch(0.684_0.138_308/0.4)]" style={{ marginLeft: "44px", marginTop: "-4px" }} />
        </div>
      </div>

      {/* Zoom controls bottom-left */}
      <div className="absolute bottom-3 left-3 flex flex-col gap-0.5 rounded-lg border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.9)] backdrop-blur-sm">
        <div className="flex h-6 w-6 items-center justify-center text-[10px] font-bold text-[oklch(0.78_0.012_264)]">+</div>
        <div className="h-px bg-[oklch(0.3_0.01_264)]" />
        <div className="flex h-6 w-6 items-center justify-center text-[10px] font-bold text-[oklch(0.78_0.012_264)]">&minus;</div>
      </div>
    </div>
  );
}

function FaithfulAgentsPanel() {
  const agents = [
    { name: "incident-triage", status: "Running", runtime: "opencode", model: "claude-sonnet-4", age: "3h" },
    { name: "log-analyzer", status: "Running", runtime: "pi", model: "gpt-4o", age: "2h" },
    { name: "security-scanner", status: "Pending", runtime: "opencode", model: "gpt-4o", age: "8m" },
  ];

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[1.15fr_0.85fr] gap-3">
      <div className="rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-3">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[oklch(0.72_0.012_264)]">Agent Management</p>
            <p className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">Namespace: production</p>
          </div>
          <div className="rounded-xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)] px-3 py-2 text-xs text-[oklch(0.78_0.012_264)]">12 agents</div>
        </div>
        <div className="space-y-2">
          {agents.map((agent, i) => (
            <div key={agent.name} className={`rounded-2xl border p-4 ${i === 0 ? "border-[oklch(0.708_0.101_188/0.3)] bg-[oklch(0.708_0.101_188/0.08)]" : "border-[oklch(0.34_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)]"}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${agent.status === "Running" ? "bg-[oklch(0.76_0.16_154)]" : "bg-[oklch(0.82_0.16_84)]"}`} />
                    <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">{agent.name}</h3>
                  </div>
                  <p className="mt-1 text-xs text-[oklch(0.72_0.012_264)]">model: {agent.model}</p>
                </div>
                <div className="flex gap-2">
                  <span className="rounded-full border border-[oklch(0.708_0.101_188/0.25)] bg-[oklch(0.708_0.101_188/0.12)] px-2 py-0.5 text-[10px] font-semibold text-[oklch(0.708_0.101_188)]">{agent.runtime}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${agent.status === "Running" ? "bg-[oklch(0.76_0.16_154/0.12)] text-[oklch(0.76_0.16_154)]" : "bg-[oklch(0.82_0.16_84/0.12)] text-[oklch(0.82_0.16_84)]"}`}>{agent.status}</span>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2">
                <MetricChip label="Age" value={agent.age} />
                <MetricChip label="Storage" value="2Gi" />
                <MetricChip label="Access" value="governed" />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-4">
        <p className="text-[10px] font-medium uppercase tracking-[0.22em] text-[oklch(0.72_0.012_264)]">Selected Agent</p>
        <h3 className="mt-2 text-base font-semibold text-[oklch(0.958_0.004_264)]">incident-triage</h3>
        <div className="mt-4 grid grid-cols-2 gap-2">
          {[
            { label: "Runtime", value: "opencode" },
            { label: "Model", value: "claude-sonnet-4" },
            { label: "Storage", value: "2Gi PVC" },
            { label: "MCP", value: "kubernetes, web-search" },
            { label: "Budget", value: "50k / run" },
            { label: "Policy", value: "governed" },
          ].map((item) => (
            <MetricChip key={item.label} label={item.label} value={item.value} />
          ))}
        </div>
      </div>
    </div>
  );
}

function FaithfulActivityPanel() {
  const activities = [
    { agent: "incident-triage", text: "Correlating pod restart events with memory pressure...", time: "10:44:18", icon: BrainCircuit, color: "text-sky-400", bg: "bg-sky-500/5", border: "border-sky-500/20" },
    { agent: "incident-triage", text: "kubectl get pods -n production --field-selector=status.phase!=Running", time: "10:44:20", icon: Wrench, color: "text-amber-400", bg: "bg-amber-500/5", border: "border-amber-500/20" },
    { agent: "log-analyzer", text: "Generated report: /workspace/incident-2024-001.md", time: "10:44:23", icon: FileCode2, color: "text-emerald-400", bg: "bg-emerald-500/5", border: "border-emerald-500/20" },
    { agent: "log-analyzer", text: "Root cause identified: OOM kill on web-frontend-7f8d9", time: "10:44:25", icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/5", border: "border-emerald-500/20" },
    { agent: "security-scanner", text: "CVE detected in deploy/redis base image", time: "10:44:29", icon: AlertTriangle, color: "text-amber-400", bg: "bg-amber-500/5", border: "border-amber-500/20" },
  ];

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[1.1fr_0.9fr] gap-3">
      <div className="rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">LiveActivityStream</h3>
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[oklch(0.76_0.16_154)] animate-pulse" />
            <span className="text-[10px] text-[oklch(0.72_0.012_264)]">Connected</span>
          </div>
        </div>
        <div className="space-y-1.5">
          {activities.map((activity, i) => {
            const Icon = activity.icon;
            return (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.08 }}
                className={`flex items-start gap-3 rounded-lg border px-3 py-2.5 ${activity.bg} ${activity.border}`}
              >
                <Icon className={`mt-0.5 h-3.5 w-3.5 flex-shrink-0 ${activity.color}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold text-[oklch(0.708_0.101_188)]">{activity.agent}</span>
                    <span className="text-[9px] text-[oklch(0.72_0.012_264)]">{activity.time}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-[oklch(0.88_0.012_264)]">{activity.text}</p>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">Workflow Status</h3>
          <span className="rounded-full bg-[oklch(0.82_0.16_84/0.12)] px-2 py-0.5 text-[10px] font-semibold text-[oklch(0.82_0.16_84)]">running</span>
        </div>
        <div className="space-y-2">
          {[
            { step: "triage", status: "completed", color: "bg-emerald-500" },
            { step: "analyze-logs", status: "completed", color: "bg-emerald-500" },
            { step: "approval", status: "running", color: "bg-amber-500" },
            { step: "remediate", status: "waiting", color: "bg-[oklch(0.82_0.012_264/0.45)]" },
          ].map((item) => (
            <div key={item.step} className="flex items-center gap-3 rounded-xl border border-[oklch(0.33_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)] px-3 py-2">
              <span className={`h-2.5 w-2.5 rounded-full ${item.color}`} />
              <span className="flex-1 text-xs font-medium text-[oklch(0.958_0.004_264)]">{item.step}</span>
              <span className="text-[10px] text-[oklch(0.72_0.012_264)]">{item.status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function FaithfulObservatoryPanel() {
  const executions = [
    { workflow: "incident-response", status: "completed", duration: "2.4 s", agent: "incident-triage" },
    { workflow: "security-scan", status: "running", duration: "1.1 s", agent: "security-scanner" },
    { workflow: "capacity-check", status: "failed", duration: "3.0 s", agent: "capacity-planner" },
  ];

  return (
    <div className="grid min-h-0 flex-1 grid-cols-[0.95fr_1.05fr] gap-3">
      <div className="rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">Execution List</h3>
          <div className="rounded-xl border border-[oklch(0.33_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)] px-3 py-2 text-[11px] text-[oklch(0.78_0.012_264)]">Filters</div>
        </div>
        <div className="space-y-2">
          {executions.map((exec, i) => {
            const tone = exec.status === "completed" ? "bg-emerald-500" : exec.status === "failed" ? "bg-red-500" : "bg-amber-500";
            return (
              <div key={exec.workflow} className={`rounded-xl border px-3 py-3 ${i === 0 ? "border-[oklch(0.708_0.101_188/0.25)] bg-[oklch(0.708_0.101_188/0.08)]" : "border-[oklch(0.33_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)]"}`}>
                <div className="flex items-center gap-3">
                  <span className={`h-2.5 w-2.5 rounded-full ${tone}`} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-semibold text-[oklch(0.958_0.004_264)]">{exec.workflow}</p>
                    <p className="truncate text-[10px] text-[oklch(0.72_0.012_264)]">{exec.agent}</p>
                  </div>
                  <span className="text-[10px] text-[oklch(0.72_0.012_264)]">{exec.duration}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264/0.56)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">ExecutionTimeline / StepInspector</h3>
          <div className="flex gap-2">
            {[
              "overview",
              "timeline",
              "llm",
            ].map((tab, i) => (
              <span key={tab} className={`rounded px-2 py-0.5 text-[10px] font-medium ${i === 0 ? "bg-[oklch(0.708_0.101_188/0.15)] text-[oklch(0.708_0.101_188)]" : "text-[oklch(0.72_0.012_264)]"}`}>{tab}</span>
            ))}
          </div>
        </div>
        <div className="space-y-3">
          {[
            { label: "trigger", duration: "120 ms", color: "bg-emerald-500", width: "22%" },
            { label: "triage", duration: "860 ms", color: "bg-emerald-500", width: "58%" },
            { label: "analyze-logs", duration: "1.1 s", color: "bg-emerald-500", width: "72%" },
            { label: "approval", duration: "420 ms", color: "bg-amber-500", width: "34%" },
          ].map((item) => (
            <div key={item.label} className="rounded-xl border border-[oklch(0.33_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)] px-3 py-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${item.color}`} />
                  <span className="text-xs font-medium text-[oklch(0.958_0.004_264)]">{item.label}</span>
                </div>
                <span className="text-[10px] text-[oklch(0.72_0.012_264)]">{item.duration}</span>
              </div>
              <div className="h-2 rounded-full bg-[oklch(0.252_0.01_264)]">
                <div className="h-2 rounded-full bg-[oklch(0.708_0.101_188)]" style={{ width: item.width }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ComposerNode({
  className,
  icon: Icon,
  title,
  badge,
  badgeColor,
  borderColor,
  iconColor,
  subtitle,
  status,
}: {
  className: string;
  icon: typeof Bot;
  title: string;
  badge: string;
  badgeColor: string;
  borderColor: string;
  iconColor: string;
  subtitle: string;
  status?: "running" | "waiting" | "completed";
}) {
  return (
    <motion.div
      className={`absolute rounded-xl border bg-[oklch(0.206_0.009_264/0.95)] shadow-lg backdrop-blur-md ${borderColor} ${className}`}
      style={{ width: "auto", minWidth: "120px" }}
      animate={{ boxShadow: ["0 0 0 0 oklch(0.708 0.101 188 / 0)", "0 0 10px 1px oklch(0.708 0.101 188 / 0.1)", "0 0 0 0 oklch(0.708 0.101 188 / 0)"] }}
      transition={{ duration: 4, repeat: Infinity }}
    >
      {/* Handle dots (connection points) */}
      <div className="absolute -left-1.5 top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2 border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264)]" />
      <div className="absolute -right-1.5 top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2 border-[oklch(0.35_0.015_264)] bg-[oklch(0.206_0.009_264)]" />

      <div className="px-3 py-2.5">
        <div className="flex items-center gap-2">
          <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-[oklch(0.164_0.007_264)] ${iconColor}`}>
            <Icon className="h-3 w-3" />
          </div>
          <span className="text-[11px] font-semibold text-[oklch(0.958_0.004_264)]">{title}</span>
          {status && (
            <span className={`ml-auto h-2 w-2 rounded-full ${status === "running" ? "bg-[oklch(0.76_0.16_154)] animate-pulse" : status === "waiting" ? "bg-[oklch(0.82_0.16_84)]" : "bg-[oklch(0.76_0.16_154)]"}`} />
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[8px] font-semibold ${badgeColor}`}>{badge}</span>
          <span className="text-[9px] text-[oklch(0.62_0.012_264)]">{subtitle}</span>
        </div>
      </div>
    </motion.div>
  );
}

function MetricChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[oklch(0.33_0.015_264)] bg-[oklch(0.164_0.007_264/0.78)] px-3 py-2">
      <p className="text-[10px] text-[oklch(0.72_0.012_264)]">{label}</p>
      <p className="mt-0.5 text-xs font-medium text-[oklch(0.958_0.004_264)]">{value}</p>
    </div>
  );
}

// ─── Features Grid ───

function FeaturesSection() {
  const features = [
    {
      icon: Server,
      title: "Kubernetes-Native CRDs",
      description:
        "AIAgent, AgentWorkflow, AgentPolicy, AgentTenant — first-class custom resources reconciled by a production Kopf operator.",
      tags: ["CRDs", "Operator", "Helm"],
    },
    {
      icon: MonitorDot,
      title: "Incident Response Automation",
      description:
        "Agents correlate alerts, check pod health, analyze logs, and propose remediation — with human approval gates for destructive actions.",
      tags: ["SRE", "On-Call", "HITL"],
    },
    {
      icon: Puzzle,
      title: "MCP Tool Ecosystem",
      description:
        "11 bundled sidecars: Kubernetes ops, web search, browser automation, file system, messaging, and more. Hot-attach any MCP server.",
      tags: ["11 Sidecars", "Hot Attach", "Tools"],
    },
    {
      icon: Shield,
      title: "Policy-Driven Governance",
      description:
        "Enforce token budgets, allowed models, PII masking, tool whitelists, and output guardrails via AgentPolicy CRDs.",
      tags: ["Guardrails", "RBAC", "Budget"],
    },
    {
      icon: Workflow,
      title: "Visual DAG Workflows",
      description:
        "Build multi-agent pipelines with the drag-and-drop composer. Approval gates, parallel execution, retries, and artifact passing.",
      tags: ["DAG", "Retries", "Approval"],
    },
    {
      icon: Gauge,
      title: "Full Observability",
      description:
        "Execution Observatory with distributed traces, LLM call inspection, step timing, token usage, and real-time activity streaming.",
      tags: ["Traces", "Metrics", "Live Stream"],
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section id="features" className="px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            Platform Capabilities
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Everything Your Cluster <span className="text-[oklch(0.708_0.101_188)]">Needs</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            From incident triage to capacity planning. A complete AI operations layer for Kubernetes-native infrastructure.
          </motion.p>
        </motion.div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature, i) => {
            const Icon = feature.icon;
            return (
              <motion.div
                key={feature.title}
                variants={itemVariants}
                initial="hidden"
                animate={inView ? "visible" : "hidden"}
                transition={{ delay: i * 0.08 }}
                className="group rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-7 backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)]"
              >
                <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-[oklch(0.708_0.101_188/0.1)] text-[oklch(0.708_0.101_188)] ring-1 ring-[oklch(0.708_0.101_188/0.2)] transition-colors group-hover:bg-[oklch(0.708_0.101_188/0.15)]">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-base font-semibold text-[oklch(0.958_0.004_264)]">{feature.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-[oklch(0.82_0.01_264)]">{feature.description}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {feature.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-[oklch(0.252_0.010_264)] px-2.5 py-0.5 text-[11px] font-medium text-[oklch(0.82_0.01_264)]"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── How It Works ───

function HowItWorks() {
  const steps = [
    {
      num: "01",
      icon: GitBranch,
      title: "Declare",
      description: "Write an AIAgent CRD with your system prompt, model, memory policy, and MCP sidecars. Apply it with kubectl or Helm.",
    },
    {
      num: "02",
      icon: RefreshCw,
      title: "Reconcile",
      description: "The Kopf operator watches your CRD and provisions a StatefulSet, Service, PVC, and ConfigMap with full lifecycle management.",
    },
    {
      num: "03",
      icon: Bot,
      title: "Operate",
      description: "Invoke via the web console, agentctl CLI, or A2A JSON-RPC. Agents persist memory, enforce policies, and route calls through LiteLLM.",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section className="px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            How It Works
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            From YAML to{" "}
            <span className="bg-gradient-to-r from-[oklch(0.708_0.101_188)] to-[oklch(0.742_0.132_233)] bg-clip-text text-transparent">
              Running Agent
            </span>
          </motion.h2>
        </motion.div>

        <div className="grid gap-6 lg:grid-cols-3">
          {steps.map((step, i) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={step.num}
                variants={itemVariants}
                initial="hidden"
                animate={inView ? "visible" : "hidden"}
                transition={{ delay: i * 0.15 }}
                className="group relative"
              >
                {/* Connection line */}
                {i < steps.length - 1 && (
                  <div className="absolute -right-3 top-16 hidden lg:block">
                    <motion.div
                      className="flex items-center gap-1"
                      initial={{ opacity: 0, x: -10 }}
                      animate={inView ? { opacity: 1, x: 0 } : {}}
                      transition={{ delay: i * 0.15 + 0.3, duration: 0.5 }}
                    >
                      <div className="h-px w-6 bg-gradient-to-r from-[oklch(0.4_0.015_264)] to-[oklch(0.3_0.01_264)]" />
                      <motion.div
                        className="h-2 w-2 rounded-full bg-[oklch(0.708_0.101_188)]"
                        animate={{ scale: [1, 1.3, 1], opacity: [0.5, 1, 0.5] }}
                        transition={{ duration: 2, repeat: Infinity, delay: i * 0.5 }}
                      />
                    </motion.div>
                  </div>
                )}

                <div className="relative overflow-hidden rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-8 backdrop-blur-sm transition-all duration-300 hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)] hover:-translate-y-1">
                  {/* Step number badge */}
                  <div className="relative mb-6 flex items-center justify-between">
                    <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-[oklch(0.708_0.101_188/0.15)] text-[oklch(0.708_0.101_188)] shadow-lg shadow-[oklch(0.708_0.101_188/0.1)]">
                      <Icon className="h-7 w-7" />
                    </div>
                    <span className="text-5xl font-black text-[oklch(0.708_0.101_188/0.1)]">
                      {step.num}
                    </span>
                  </div>

                  <div className="relative">
                    <h3 className="text-xl font-bold text-[oklch(0.958_0.004_264)]">{step.title}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-[oklch(0.82_0.01_264)]">
                      {step.description}
                    </p>
                  </div>

                  {/* Bottom accent line */}
                  <div className="absolute bottom-0 left-0 h-1 w-0 rounded-b-2xl bg-gradient-to-r from-[oklch(0.708_0.101_188)] to-[oklch(0.742_0.132_233)] transition-all duration-500 group-hover:w-full" />
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Install Terminal Section ───

type TabKey = "install" | "agent" | "workflow" | "operate";

function InstallSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [activeTab, setActiveTab] = useState<TabKey>("install");

  const tabs: { key: TabKey; label: string; icon: typeof Terminal }[] = [
    { key: "install", label: "Install", icon: Terminal },
    { key: "agent", label: "AIAgent", icon: Bot },
    { key: "workflow", label: "Workflow", icon: Workflow },
    { key: "operate", label: "Operate", icon: Play },
  ];

  const tabLines: Record<TabKey, TerminalLine[]> = {
    install: [
      { text: "# Install KubeSynapse via Helm OCI", color: "comment", type: "input" },
      { text: "helm install kubesynapse \\", color: "command", prefix: "$", type: "input" },
      { text: "  oci://docker.io/kubesynapse/charts/kubesynapse \\", color: "command", type: "input" },
      { text: "  --namespace kubesynapse --create-namespace \\", color: "command", type: "input" },
      { text: "  --set platformSecrets.native.openaiApiKey=\"sk-...\"", color: "command", type: "input" },
      { text: "", type: "blank" },
      { text: "NAME: kubesynapse", color: "output", type: "output" },
      { text: "NAMESPACE: kubesynapse", color: "output", type: "output" },
      { text: "STATUS: deployed", color: "string", type: "output" },
      { text: "REVISION: 1", color: "output", type: "output" },
      { text: "", type: "blank" },
      { text: "kubectl port-forward svc/kubesynapse-api-gateway 8080:8080", color: "command", prefix: "$", type: "input" },
      { text: "Forwarding from 127.0.0.1:8080 -> 8080", color: "string", type: "output" },
    ],
    agent: [
      { text: "apiVersion: kubesynapse.ai/v1alpha1", color: "yamlKey", type: "input" },
      { text: "kind: AIAgent", color: "yamlKey", type: "input" },
      { text: "metadata:", color: "yamlKey", type: "input" },
      { text: "  name: incident-triage", color: "yamlVal", type: "input" },
      { text: "  namespace: production", color: "yamlVal", type: "input" },
      { text: "spec:", color: "yamlKey", type: "input" },
      { text: "  runtimeKind: opencode", color: "yamlVal", type: "input" },
      { text: "  model: claude-sonnet-4", color: "yamlVal", type: "input" },
      { text: "  storageSize: 2Gi", color: "yamlVal", type: "input" },
      { text: "  systemPrompt: |", color: "yamlKey", type: "input" },
      { text: "    You are an SRE agent. When an alert fires,", color: "string", type: "input" },
      { text: "    correlate logs, check pod status, and suggest", color: "string", type: "input" },
      { text: "    remediation. Ask before destructive commands.", color: "string", type: "input" },
      { text: "  mcpSidecars:", color: "yamlKey", type: "input" },
      { text: "    - name: kubernetes", color: "yamlVal", type: "input" },
      { text: "      config:", color: "yamlVal", type: "input" },
      { text: "        namespace: production", color: "yamlVal", type: "input" },
      { text: "    - name: web-search", color: "yamlVal", type: "input" },
      { text: "    - name: messaging", color: "yamlVal", type: "input" },
    ],
    workflow: [
      { text: "apiVersion: kubesynapse.ai/v1alpha1", color: "yamlKey", type: "input" },
      { text: "kind: AgentWorkflow", color: "yamlKey", type: "input" },
      { text: "metadata:", color: "yamlKey", type: "input" },
      { text: "  name: incident-response", color: "yamlVal", type: "input" },
      { text: "spec:", color: "yamlKey", type: "input" },
      { text: "  description: Automated incident response pipeline", color: "yamlVal", type: "input" },
      { text: "  steps:", color: "yamlKey", type: "input" },
      { text: "    - name: triage", color: "yamlVal", type: "input" },
      { text: "      agentRef: incident-triage", color: "yamlVal", type: "input" },
      { text: "      prompt: |", color: "yamlKey", type: "input" },
      { text: "        Analyze this alert and correlate with recent", color: "string", type: "input" },
      { text: "        pod events. Identify root cause.", color: "string", type: "input" },
      { text: "    - name: analyze-logs", color: "yamlVal", type: "input" },
      { text: "      agentRef: log-analyzer", color: "yamlVal", type: "input" },
      { text: "      dependsOn: [triage]", color: "yamlVal", type: "input" },
      { text: "      prompt: |", color: "yamlKey", type: "input" },
      { text: "        Deep-dive into logs for the affected pods.", color: "string", type: "input" },
      { text: "    - name: remediate", color: "yamlVal", type: "input" },
      { text: "      agentRef: incident-triage", color: "yamlVal", type: "input" },
      { text: "      dependsOn: [analyze-logs]", color: "yamlVal", type: "input" },
      { text: "      requireApproval: true", color: "flag", type: "input" },
      { text: "      prompt: |", color: "yamlKey", type: "input" },
      { text: "        Apply the recommended fix from the analysis.", color: "string", type: "input" },
    ],
    operate: [
      { text: "kubectl apply -f agent.yaml", color: "command", prefix: "$", type: "input" },
      { text: "aiagent.kubesynapse.ai/incident-triage created", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "kubectl apply -f workflow.yaml", color: "command", prefix: "$", type: "input" },
      { text: "agentworkflow.kubesynapse.ai/incident-response created", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "kubectl get aiagents -n production", color: "command", prefix: "$", type: "input" },
      { text: "NAME              RUNTIME    STATUS    AGE", color: "output", type: "output" },
      { text: "incident-triage   opencode   Running   2m", color: "string", type: "output" },
      { text: "log-analyzer      pi         Running   2m", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "agentctl workflow trigger incident-response", color: "command", prefix: "$", type: "input" },
      { text: "Workflow triggered: incident-response (run-4f2a)", color: "string", type: "output" },
      { text: "Step [triage]: running...", color: "output", type: "output" },
      { text: "Step [analyze-logs]: waiting on [triage]", color: "output", type: "output" },
      { text: "Step [remediate]: pending approval", color: "flag", type: "output" },
    ],
  };

  return (
    <section id="install" className="px-4 py-24 sm:px-6 md:py-32" ref={ref}>
      <div className="mx-auto max-w-5xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-12 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            Quick Start
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Deploy in <span className="text-[oklch(0.708_0.101_188)]">5 Minutes</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            One Helm install gives you the full control plane. Then declare agents with YAML and manage them with kubectl.
          </motion.p>
        </motion.div>

        {/* Tabbed Terminal */}
        <motion.div
          variants={itemVariants}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="overflow-hidden rounded-xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.12_0.006_264)] shadow-2xl shadow-black/40 ring-1 ring-[oklch(0.25_0.01_264)]"
        >
          {/* Tabs */}
          <div className="flex border-b border-[oklch(0.25_0.01_264)] bg-[oklch(0.149_0.008_264)]">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-all ${
                    isActive
                      ? "bg-[oklch(0.12_0.006_264)] text-[oklch(0.708_0.101_188)] border-t-2 border-t-[oklch(0.708_0.101_188)]"
                      : "text-[oklch(0.62_0.01_264)] hover:text-[oklch(0.82_0.01_264)] hover:bg-[oklch(0.18_0.008_264)]"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              );
            })}
            <div className="flex-1" />
            <button
              onClick={() => {
                const text = tabLines[activeTab].map((l) => `${l.prefix ? l.prefix + " " : ""}${l.text}`).join("\n");
                navigator.clipboard.writeText(text).catch(() => {});
              }}
              className="px-4 py-3 text-[oklch(0.4_0.01_264)] hover:text-[oklch(0.82_0.01_264)] transition-colors"
              title="Copy to clipboard"
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>

          {/* Terminal Content */}
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              className="p-5 font-mono text-[13px] leading-6"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              {tabLines[activeTab].map((line, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.04, duration: 0.25 }}
                  className="min-h-[1.5rem]"
                >
                  {line.text === "" ? (
                    <span>&nbsp;</span>
                  ) : (
                    <span className={`whitespace-pre ${colorMap[line.color || "output"] || "text-[oklch(0.82_0.01_264)]"}`}>
                      {line.prefix && (
                        <span className="select-none text-[oklch(0.76_0.16_154/0.8)]">{line.prefix} </span>
                      )}
                      {line.text}
                    </span>
                  )}
                </motion.div>
              ))}
            </motion.div>
          </AnimatePresence>
        </motion.div>

        {/* Feature pills */}
        <motion.div
          variants={itemVariants}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="mt-8 flex flex-wrap justify-center gap-3"
        >
          {["Helm OCI", "CRDs", "kubectl", "agentctl CLI", "A2A JSON-RPC", "SSE Streaming"].map((item) => (
            <span
              key={item}
              className="rounded-full border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.6)] px-4 py-1.5 text-xs font-medium text-[oklch(0.82_0.01_264)]"
            >
              {item}
            </span>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

// ─── Architecture Section ───

function ArchitectureSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  const components = [
    { label: "Control Plane", items: ["Kubernetes API Server", "Operator (Kopf)", "API Gateway (FastAPI)", "CRDs v1alpha1 (6 types)"] },
    { label: "Execution Plane", items: ["OpenCode Runtime (STS)", "Pi Runtime (STS)", "MCP Sidecars (11)", "Worker Jobs"] },
    { label: "Shared Services", items: ["LiteLLM (Model Router)", "PostgreSQL", "Redis", "NATS", "Qdrant"] },
  ];

  return (
    <section id="architecture" className="border-y border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264/0.5)] px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            Architecture
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Built for <span className="text-[oklch(0.708_0.101_188)]">Production</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            Separation of control plane and execution plane. Every agent is an isolated StatefulSet
            with its own persistent volume, network policy, and governance envelope.
          </motion.p>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-3">
          {components.map((col, i) => (
            <motion.div
              key={col.label}
              variants={itemVariants}
              initial="hidden"
              animate={inView ? "visible" : "hidden"}
              transition={{ delay: i * 0.1 }}
              className="rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-6 backdrop-blur-sm"
            >
              <h3 className="mb-4 text-sm font-bold uppercase tracking-wider text-[oklch(0.62_0.01_264)]">{col.label}</h3>
              <div className="space-y-3">
                {col.items.map((item) => (
                  <div
                    key={item}
                    className="flex items-center gap-3 rounded-lg border border-[oklch(0.3_0.01_264/0.5)] bg-[oklch(0.164_0.007_264/0.8)] px-4 py-3 text-sm font-medium text-[oklch(0.85_0.01_264)]"
                  >
                    <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-[oklch(0.708_0.101_188)]" />
                    {item}
                  </div>
                ))}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Documentation Section ───

function DocsSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  const docs = [
    { icon: BookOpen, title: "Getting Started", description: "5-minute tutorial from install to your first agent", href: "#install" },
    { icon: Layers, title: "Architecture Guide", description: "Control plane, execution plane, and data flow diagrams", href: "#architecture" },
    { icon: Code, title: "API Reference", description: "OpenAPI schema, REST endpoints, SSE streaming, A2A protocol", href: "#" },
    { icon: Boxes, title: "Helm Chart Docs", description: "Values reference, production examples, upgrade guides", href: "#" },
    { icon: Terminal, title: "CLI Reference", description: "agentctl commands for agent, workflow, and eval management", href: "#" },
    { icon: FolderTree, title: "CRD Schema", description: "AIAgent, AgentWorkflow, AgentPolicy, AgentTenant specifications", href: "#" },
    { icon: Shield, title: "Security Guide", description: "Network policies, RBAC, secret management, auth flows", href: "#" },
    { icon: GitBranch, title: "Contributing", description: "Development setup, PR process, coding standards", href: "https://github.com/ykbytes/kubesynapse.ai/blob/main/CONTRIBUTING.md" },
  ];

  return (
    <section id="docs" className="px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            Documentation
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Everything You Need to <span className="text-[oklch(0.708_0.101_188)]">Get Started</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            Comprehensive documentation for operators, developers, and contributors.
          </motion.p>
        </motion.div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {docs.map((doc, i) => {
            const Icon = doc.icon;
            return (
              <motion.a
                key={doc.title}
                href={doc.href}
                variants={itemVariants}
                initial="hidden"
                animate={inView ? "visible" : "hidden"}
                transition={{ delay: i * 0.06 }}
                className="group rounded-xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.4)] p-5 backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-md hover:shadow-[oklch(0.708_0.101_188/0.05)] hover:-translate-y-0.5"
              >
                <Icon className="mb-3 h-5 w-5 text-[oklch(0.708_0.101_188)]" />
                <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)] group-hover:text-[oklch(0.708_0.101_188)] transition-colors">
                  {doc.title}
                </h3>
                <p className="mt-1.5 text-xs leading-relaxed text-[oklch(0.72_0.01_264)]">{doc.description}</p>
                <ChevronRight className="mt-3 h-4 w-4 text-[oklch(0.4_0.01_264)] transition-all group-hover:text-[oklch(0.708_0.101_188)] group-hover:translate-x-1" />
              </motion.a>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Why KubeSynapse (replaces comparison matrix) ───

function WhySection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  const reasons = [
    {
      icon: Server,
      title: "Kubernetes-Native by Design",
      description: "Agents are CRDs, not Python objects. Managed by a Kopf operator with full lifecycle — create, reconcile, scale, and delete with kubectl.",
    },
    {
      icon: Lock,
      title: "Self-Hosted, Zero Telemetry",
      description: "Your cluster, your data. Deploy via Helm OCI in your own namespace with no external dependencies or phone-home behavior.",
    },
    {
      icon: Shield,
      title: "Governed from Day One",
      description: "Token budgets, approval gates, tool whitelists, PII masking, and audit trails enforced by AgentPolicy CRDs — not bolted on later.",
    },
    {
      icon: Layers,
      title: "Stateful Agents with PVCs",
      description: "Every agent gets its own StatefulSet, PersistentVolumeClaim, and network policy. Memory, workspace files, and context survive restarts.",
    },
  ];

  return (
    <section className="border-y border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264/0.5)] px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            Why KubeSynapse
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Purpose-Built for{" "}
            <span className="bg-gradient-to-r from-[oklch(0.708_0.101_188)] to-[oklch(0.742_0.132_233)] bg-clip-text text-transparent">
              Production
            </span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-xl text-base text-[oklch(0.82_0.01_264)]">
            Not a Python library with a deployment guide. A complete AI operations platform designed from day one for Kubernetes operators.
          </motion.p>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-2">
          {reasons.map((reason, i) => {
            const Icon = reason.icon;
            return (
              <motion.div
                key={reason.title}
                variants={itemVariants}
                initial="hidden"
                animate={inView ? "visible" : "hidden"}
                transition={{ delay: i * 0.1 }}
                className="group flex gap-5 rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-7 backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)]"
              >
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[oklch(0.708_0.101_188/0.1)] text-[oklch(0.708_0.101_188)] ring-1 ring-[oklch(0.708_0.101_188/0.2)] transition-colors group-hover:bg-[oklch(0.708_0.101_188/0.15)]">
                  <Icon className="h-6 w-6" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-[oklch(0.958_0.004_264)]">{reason.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-[oklch(0.82_0.01_264)]">{reason.description}</p>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Bottom CTA ───

function BottomCTA() {
  return (
    <section className="px-6 py-24 md:py-32">
      <div className="mx-auto max-w-4xl text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="rounded-3xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-10 shadow-2xl shadow-[oklch(0.708_0.101_188/0.05)] backdrop-blur-sm md:p-16"
        >
          <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-[oklch(0.708_0.101_188)] text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)]">
            <Cpu className="h-7 w-7" />
          </div>
          <h2 className="text-3xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Ready to <span className="text-[oklch(0.708_0.101_188)]">Automate</span>?
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-[oklch(0.82_0.01_264)]">
            Deploy KubeSynapse on your cluster and let AI agents handle incident response,
            infrastructure automation, and operational intelligence.
          </p>

          {/* Inline install command */}
          <div className="mx-auto mt-8 max-w-lg overflow-hidden rounded-lg border border-[oklch(0.3_0.01_264)] bg-[oklch(0.12_0.006_264)]">
            <div className="flex items-center justify-between px-4 py-2.5">
              <code className="text-xs text-[oklch(0.75_0.12_188)]">
                <span className="text-[oklch(0.76_0.16_154/0.8)]">$ </span>
                helm install kubesynapse oci://docker.io/kubesynapse/charts/kubesynapse
              </code>
              <button
                onClick={() => navigator.clipboard.writeText("helm install kubesynapse oci://docker.io/kubesynapse/charts/kubesynapse --namespace kubesynapse --create-namespace").catch(() => {})}
                className="ml-2 text-[oklch(0.4_0.01_264)] hover:text-[oklch(0.82_0.01_264)] transition-colors"
                title="Copy"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div className="mt-8 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <a
              href="#install"
              className="group flex items-center gap-2 rounded-xl bg-[oklch(0.708_0.101_188)] px-8 py-3.5 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)] transition-all hover:shadow-xl active:scale-[0.98]"
            >
              Deploy Now
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </a>
            <a
              href="https://github.com/ykbytes/kubesynapse.ai"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-xl border border-[oklch(0.4_0.015_264)] bg-[oklch(0.206_0.009_264/0.8)] px-8 py-3.5 text-sm font-semibold text-[oklch(0.85_0.01_264)] shadow-sm transition-all hover:border-[oklch(0.708_0.101_188/0.4)] hover:text-[oklch(0.958_0.004_264)]"
            >
              <GitBranch className="h-4 w-4 text-[oklch(0.708_0.101_188)]" />
              View on GitHub
            </a>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Footer ───

function Footer() {
  return (
    <footer className="border-t border-[oklch(0.3_0.01_264)] px-6 py-14">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="sm:col-span-2 lg:col-span-1">
            <div className="flex items-center gap-2">
              <LayoutPanelTop className="h-5 w-5 text-[oklch(0.708_0.101_188)]" />
              <span className="text-sm font-bold text-[oklch(0.958_0.004_264)]">{BRAND.name}</span>
            </div>
            <p className="mt-3 max-w-[260px] text-xs leading-relaxed text-[oklch(0.68_0.01_264)]">
              The AI-powered command center for Kubernetes operations.
              Self-hosted, open source under Apache 2.0.
            </p>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-[oklch(0.62_0.01_264)]">Platform</h4>
            <ul className="mt-4 space-y-2.5 text-sm text-[oklch(0.78_0.01_264)]">
              <li><a href="#features" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Features</a></li>
              <li><a href="#architecture" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Architecture</a></li>
              <li><a href="#install" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Quick Start</a></li>
              <li><a href="#docs" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Documentation</a></li>
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-[oklch(0.62_0.01_264)]">Resources</h4>
            <ul className="mt-4 space-y-2.5 text-sm text-[oklch(0.78_0.01_264)]">
              <li><a href="https://github.com/ykbytes/kubesynapse.ai" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">GitHub</a></li>
              <li><a href="https://github.com/ykbytes/kubesynapse.ai/blob/main/CHANGELOG.md" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Changelog</a></li>
              <li><a href="https://github.com/ykbytes/kubesynapse.ai/tree/main/charts/kubesynapse" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Helm Charts</a></li>
              <li><a href="https://github.com/ykbytes/kubesynapse.ai/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">License</a></li>
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-[oklch(0.62_0.01_264)]">Community</h4>
            <ul className="mt-4 space-y-2.5 text-sm text-[oklch(0.78_0.01_264)]">
              <li><a href="https://github.com/ykbytes/kubesynapse.ai/blob/main/CONTRIBUTING.md" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Contributing</a></li>
              <li><a href="https://github.com/ykbytes/kubesynapse.ai/security" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Security</a></li>
              <li><a href="https://github.com/ykbytes/kubesynapse.ai/issues" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Issue Tracker</a></li>
              <li><a href="mailto:team@kubesynapse.ai" className="transition-colors hover:text-[oklch(0.708_0.101_188)]">Contact</a></li>
            </ul>
          </div>
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-[oklch(0.25_0.01_264)] pt-8 sm:flex-row">
          <p className="text-xs text-[oklch(0.58_0.01_264)]">
            &copy; {new Date().getFullYear()} {BRAND.name}. Open source under Apache 2.0.
          </p>
          <div className="flex items-center gap-4 text-xs text-[oklch(0.58_0.01_264)]">
            <span>Self-hosted &middot; No telemetry &middot; Your cluster, your data</span>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ─── Main LandingPage ───

export function LandingPage({ onLogin: _onLogin }: LandingPageProps) {
  const [view, setView] = useState<"landing" | "docs">("landing");

  const handleSectionClick = useCallback((sectionId: string) => {
    if (view !== "landing") {
      setView("landing");
      requestAnimationFrame(() => {
        setTimeout(() => {
          document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth" });
        }, 80);
      });
      return;
    }

    document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth" });
  }, [view]);

  return (
    <div className="min-h-screen bg-[oklch(0.164_0.007_264)] text-[oklch(0.958_0.004_264)] font-sans">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-lg focus:bg-[oklch(0.708_0.101_188)] focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-[oklch(0.158_0.007_264)]"
      >
        Skip to main content
      </a>
      <Navbar
        onOpenDocs={() => setView("docs")}
        docsMode={view === "docs"}
        onBackToLanding={() => setView("landing")}
        onSectionClick={handleSectionClick}
      />
      {view === "docs" ? (
        <main id="main-content" className="h-[calc(100vh-4rem)]">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center">
                <div className="flex flex-col items-center gap-3 animate-fade-in">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  <p className="text-sm text-muted-foreground">Loading documentation...</p>
                </div>
              </div>
            }
          >
            <DocumentationPanel />
          </Suspense>
        </main>
      ) : (
        <>
          <main id="main-content">
            <HeroSection onOpenDocs={() => setView("docs")} />
            <EcosystemCloud />
            <ProblemSection />
            <UIPreviewSection />
            <FeaturesSection />
            <HowItWorks />
            <InstallSection />
            <ArchitectureSection />
            <DocsSection />
            <WhySection />
            <BottomCTA />
          </main>
          <Footer />
        </>
      )}
    </div>
  );
}

export default LandingPage;
