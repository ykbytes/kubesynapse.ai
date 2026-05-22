import { lazy, Suspense, useCallback, useEffect, useRef, useState, createElement } from "react";
import { motion, useInView, AnimatePresence } from "framer-motion";
import {
  ArrowRight, ArrowLeftRight, Bot, BrainCircuit, CheckCircle2, ChevronDown, Circle, Clock,
  Database, GitBranch, GripVertical, LayoutGrid, ListChecks, LoaderCircle, Lock,
  Maximize2, MessageSquare, PanelLeftClose, PanelLeftOpen, Play, Plus, Radio,
  RefreshCw, Save, Search, Server, Settings, Shield, ShieldCheck, Sparkles, Telescope, UserCheck,
  Workflow, XCircle,
  Terminal, Copy,
  Boxes, Code, Puzzle, Activity, Eye,
  BookOpen, Cpu, Gauge, AlertTriangle, Wrench,
  MonitorDot, Layers, FolderTree, ChevronRight,
  Check,
  Menu,
  X,
  Star,
  GitCommitHorizontal,
} from "lucide-react";
import { BRAND } from "@/lib/brand";
import { cn } from "@/lib/utils";
import { KubeSynapseLogo } from "@/components/shared/KubeSynapseLogo";

const DocumentationPanel = lazy(() =>
  import("../docs/DocumentationPanel").then((m) => ({ default: m.DocumentationPanel })),
);

// ─── Types ───

interface LandingPageProps {
  onLogin: () => void;
  showLogin?: boolean;
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

// ─── Section Divider ───

function SectionDivider() {
  return (
    <div className="flex items-center justify-center py-0">
      <div className="flex items-center gap-3">
        <div className="h-px w-16 bg-gradient-to-r from-transparent to-[oklch(0.708_0.101_188/0.2)]" />
        <div className="h-1.5 w-1.5 rounded-full bg-[oklch(0.708_0.101_188/0.3)]" />
        <div className="h-px w-16 bg-gradient-to-l from-transparent to-[oklch(0.708_0.101_188/0.2)]" />
      </div>
    </div>
  );
}

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
  onLogin,
  showLogin,
}: {
  onOpenDocs: () => void;
  docsMode: boolean;
  onBackToLanding: () => void;
  onSectionClick: (sectionId: string) => void;
  onLogin?: () => void;
  showLogin?: boolean;
}) {
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 12);
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const navLinks = [
    { label: "Features", id: "features" },
    { label: "Architecture", id: "architecture" },
    { label: "Install", id: "install" },
  ];

  return (
    <nav
      className={`sticky top-0 z-50 border-b transition-all duration-300 ${
        scrolled
          ? "border-[oklch(0.3_0.01_264)] bg-[oklch(0.14_0.008_264/0.92)] shadow-lg shadow-black/20 backdrop-blur-xl"
          : "border-transparent bg-[oklch(0.14_0.008_264/0.6)] backdrop-blur-sm"
      }`}
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3.5 sm:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[oklch(0.708_0.101_188)] text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)]">
            <KubeSynapseLogo className="h-5 w-5" animated />
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
          {navLinks.map((link) => (
            <button
              key={link.id}
              type="button"
              onClick={() => onSectionClick(link.id)}
              className="transition-colors hover:text-[oklch(0.708_0.101_188)]"
            >
              {link.label}
            </button>
          ))}
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
          {showLogin && onLogin && (
            <button
              type="button"
              onClick={onLogin}
              className="hidden rounded-lg bg-[oklch(0.708_0.101_188)] px-4 py-2 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.25)] transition-all hover:bg-[oklch(0.75_0.12_188)] hover:shadow-[oklch(0.708_0.101_188/0.4)] sm:inline-flex"
            >
              Open Console
            </button>
          )}
          <a
            href="https://github.com/ykbytes/kubesynapse.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-[oklch(0.82_0.01_264)] transition-colors hover:text-[oklch(0.958_0.004_264)] sm:flex"
          >
            <Star className="h-3.5 w-3.5" />
            GitHub
          </a>
          {/* Mobile menu button */}
          <button
            type="button"
            onClick={() => setMobileOpen(!mobileOpen)}
            className="inline-flex items-center justify-center rounded-lg p-2 text-[oklch(0.82_0.01_264)] transition-colors hover:text-[oklch(0.958_0.004_264)] md:hidden"
            aria-label="Toggle menu"
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden border-t border-[oklch(0.3_0.01_264)] md:hidden"
          >
            <div className="flex flex-col gap-1 px-4 py-3">
              {navLinks.map((link) => (
                <button
                  key={link.id}
                  type="button"
                  onClick={() => { onSectionClick(link.id); setMobileOpen(false); }}
                  className="rounded-lg px-3 py-2.5 text-left text-sm font-medium text-[oklch(0.82_0.01_264)] transition-colors hover:bg-[oklch(0.206_0.009_264)] hover:text-[oklch(0.708_0.101_188)]"
                >
                  {link.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => { onOpenDocs(); setMobileOpen(false); }}
                className="rounded-lg px-3 py-2.5 text-left text-sm font-medium text-[oklch(0.82_0.01_264)] transition-colors hover:bg-[oklch(0.206_0.009_264)] hover:text-[oklch(0.708_0.101_188)]"
              >
                Docs
              </button>
              <a
                href="https://github.com/ykbytes/kubesynapse.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 rounded-lg px-3 py-2.5 text-sm font-medium text-[oklch(0.82_0.01_264)] transition-colors hover:bg-[oklch(0.206_0.009_264)] hover:text-[oklch(0.958_0.004_264)]"
              >
                <Star className="h-3.5 w-3.5" />
                GitHub
              </a>
              {showLogin && onLogin && (
                <button
                  type="button"
                  onClick={() => { onLogin(); setMobileOpen(false); }}
                  className="mt-2 rounded-lg bg-[oklch(0.708_0.101_188)] px-4 py-2.5 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.25)]"
                >
                  Open Console
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </nav>
  );
}

// ─── Hero Section ───

function AnimatedCounter({ target, suffix = "" }: { target: number; suffix?: string }) {
  const [count, setCount] = useState(0);
  const ref = useRef(null);
  const inView = useInView(ref, { once: true });
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (!inView || hasAnimated.current) return;
    hasAnimated.current = true;
    const duration = 1200;
    const start = performance.now();
    const animate = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.round(eased * target));
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  }, [inView, target]);

  return (
    <span ref={ref} className="tabular-nums">
      {count}{suffix}
    </span>
  );
}

function HeroSection({ onOpenDocs }: { onOpenDocs: () => void }) {
  return (
    <section className="relative overflow-hidden px-4 pb-20 pt-16 sm:px-6 md:pb-28 md:pt-32">
      {/* Background grid */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(to right, oklch(0.958 0.004 264) 1px, transparent 1px), linear-gradient(to bottom, oklch(0.958 0.004 264) 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
      />
      {/* Animated gradient orbs */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="absolute left-1/4 top-0 h-[500px] w-[500px] rounded-full bg-[oklch(0.708_0.101_188/0.07)] blur-[120px] motion-safe:animate-[float-orb-1_18s_ease-in-out_infinite]"
        />
        <div
          className="absolute right-1/4 top-1/3 h-[400px] w-[400px] rounded-full bg-[oklch(0.742_0.132_233/0.06)] blur-[100px] motion-safe:animate-[float-orb-2_22s_ease-in-out_infinite]"
        />
        <div
          className="absolute left-1/2 -translate-x-1/2 -translate-y-1/3 h-[420px] w-[min(800px,100vw)] rounded-full bg-[oklch(0.708_0.101_188/0.08)] blur-[100px] sm:h-[600px]"
        />
      </div>

      <div className="relative mx-auto max-w-5xl text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-6 inline-flex max-w-full flex-wrap items-center justify-center gap-2 rounded-full border border-[oklch(0.708_0.101_188/0.3)] bg-[oklch(0.206_0.009_264/0.8)] px-4 py-1.5 text-center text-[11px] font-semibold text-[oklch(0.708_0.101_188)] shadow-lg shadow-[oklch(0.708_0.101_188/0.1)] backdrop-blur-sm sm:text-xs"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[oklch(0.76_0.16_154)] opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[oklch(0.76_0.16_154)]" />
          </span>
          Self-Hosted &middot; Open Source &middot; Apache 2.0
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="text-3xl font-extrabold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-5xl md:text-6xl lg:text-7xl"
        >
          Kubernetes-native{" "}
          <span className="bg-gradient-to-r from-[oklch(0.708_0.101_188)] to-[oklch(0.742_0.132_233)] bg-clip-text text-transparent">
            AI agent infrastructure
          </span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-[oklch(0.82_0.01_264)] sm:text-lg md:text-xl"
        >
          Self-hosted agent infrastructure for teams that want workflows, tools,
          memory, and observability to live inside the cluster. Deploy AI agents
          for incident response, infrastructure work, and research pipelines with
          Kubernetes-native CRDs and operator-managed runtimes.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="mt-8 flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-center"
        >
          <a
            href="#install"
            className="group relative flex w-full items-center justify-center gap-2 rounded-xl bg-[oklch(0.708_0.101_188)] px-7 py-3.5 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)] transition-all hover:shadow-xl hover:shadow-[oklch(0.708_0.101_188/0.45)] active:scale-[0.98] sm:w-auto"
          >
            <span className="absolute inset-0 -z-10 rounded-xl bg-[oklch(0.708_0.101_188)] opacity-0 blur-xl motion-safe:group-hover:opacity-50 transition-opacity" />
            <Terminal className="h-4 w-4" />
            Deploy with Helm
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </a>
          <button
            type="button"
            onClick={onOpenDocs}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-[oklch(0.4_0.015_264)] bg-[oklch(0.206_0.009_264/0.8)] px-7 py-3.5 text-sm font-semibold text-[oklch(0.85_0.01_264)] shadow-sm backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.4)] hover:text-[oklch(0.958_0.004_264)] sm:w-auto"
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
          className="mt-12 flex flex-wrap items-center justify-center gap-6 text-center sm:gap-8"
        >
          {[
            { label: "CRD Types", value: 12, suffix: "" },
            { label: "MCP Sidecars", value: 11, suffix: "" },
            { label: "Runtimes", value: 3, suffix: "" },
            { label: "Self-Hosted", value: 100, suffix: "%" },
          ].map((stat) => (
            <div key={stat.label} className="flex flex-col">
              <span className="text-2xl font-bold text-[oklch(0.708_0.101_188)]">
                <AnimatedCounter target={stat.value} suffix={stat.suffix} />
              </span>
              <span className="text-xs text-[oklch(0.72_0.01_264)]">{stat.label}</span>
            </div>
          ))}
        </motion.div>

        {/* Social proof */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.2, duration: 0.5 }}
          className="mt-6 flex items-center justify-center gap-3"
        >
          <a
            href="https://github.com/ykbytes/kubesynapse.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-full border border-[oklch(0.3_0.01_264)] bg-[oklch(0.18_0.009_264/0.8)] px-4 py-2 text-sm text-[oklch(0.78_0.01_264)] transition-all hover:border-[oklch(0.708_0.101_188/0.3)] hover:text-[oklch(0.958_0.004_264)]"
          >
            <Star className="h-4 w-4 text-[oklch(0.76_0.16_154)]" />
            <span className="font-medium">Star on GitHub</span>
            <span className="text-[oklch(0.5_0.01_264)]">·</span>
            <span className="font-semibold text-[oklch(0.958_0.004_264)]">Open Source</span>
          </a>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Ecosystem Bar ───

function EcosystemCloud() {
  const tools = [
    { name: "Kubernetes", style: "border-[#326CE5]/30 bg-[#326CE5]/8 text-[#7baaf7]" },
    { name: "Helm", style: "border-[#0F1689]/30 bg-[#0F1689]/8 text-[#8b9cf7]" },
    { name: "OpenCode", style: "border-emerald-500/30 bg-emerald-500/8 text-emerald-300" },
    { name: "LiteLLM", style: "border-violet-500/30 bg-violet-500/8 text-violet-300" },
    { name: "NATS", style: "border-sky-500/30 bg-sky-500/8 text-sky-300" },
    { name: "PostgreSQL", style: "border-blue-400/30 bg-blue-400/8 text-blue-300" },
    { name: "Redis", style: "border-red-400/30 bg-red-400/8 text-red-300" },
    { name: "Qdrant", style: "border-[#DC2C5C]/30 bg-[#DC2C5C]/8 text-[#f07090]" },
  ];

  return (
    <section className="border-y border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264/0.8)] px-4 py-12 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <p className="mb-8 text-center text-xs font-semibold uppercase tracking-widest text-[oklch(0.62_0.01_264)]">
          Built for the Kubernetes Ecosystem
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          {tools.map((tool) => (
            <motion.span
              key={tool.name}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-semibold backdrop-blur-sm transition-all hover:scale-105 ${tool.style}`}
              whileHover={{ y: -2 }}
              transition={{ duration: 0.15 }}
            >
              {tool.name}
            </motion.span>
          ))}
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
      accent: "border-l-amber-400/60",
    },
    {
      icon: Lock,
      title: "Ungoverned Automation",
      description:
        "AI tools without guardrails are dangerous in production. Token budgets, approval gates, and audit trails are afterthoughts.",
      accent: "border-l-red-400/60",
    },
    {
      icon: Layers,
      title: "Fragmented Tooling",
      description:
        "Deployment scripts, monitoring, security scanning, and capacity planning all live in separate silos with no unified intelligence layer.",
      accent: "border-l-[oklch(0.708_0.101_188)/60]",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section className="px-4 py-24 sm:px-6 md:py-32" ref={ref}>
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
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
                className={`group rounded-2xl border border-[oklch(0.3_0.01_264)] border-l-4 bg-[oklch(0.206_0.009_264/0.6)] p-6 backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.4)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)] sm:p-8 ${p.accent}`}
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
  const [activeTab, setActiveTab] = useState<"composer" | "workflow" | "agents" | "steps" | "policies" | "observatory">("composer");

  const tabs = [
    { id: "composer" as const, label: "Composer", icon: Workflow, desc: "Visual workflow builder" },
    { id: "workflow" as const, label: "Live Workflow", icon: Activity, desc: "Progress, steps & approval gates" },
    { id: "agents" as const, label: "Agents", icon: Bot, desc: "Management & configuration" },
    { id: "steps" as const, label: "Steps", icon: ListChecks, desc: "Execution & dependencies" },
    { id: "policies" as const, label: "Policies", icon: Shield, desc: "Guardrails & access control" },
    { id: "observatory" as const, label: "Observatory", icon: Telescope, desc: "Traces & LLM inspection" },
  ];

  useEffect(() => {
    if (!inView) return;
    const interval = setInterval(() => {
      setActiveTab((prev) => {
        const idx = tabs.findIndex((t) => t.id === prev);
        return tabs[(idx + 1) % tabs.length].id;
      });
    }, 8000);
    return () => clearInterval(interval);
  }, [inView]);

  return (
    <section ref={ref} className="relative overflow-hidden py-24">
      <div className="absolute inset-0 bg-gradient-to-b from-[oklch(0.145_0.022_264)] via-[oklch(0.13_0.02_264)] to-[oklch(0.18_0.025_264)]" />
      <div className="absolute inset-0 opacity-[0.03]" style={{ backgroundImage: "radial-gradient(oklch(0.72_0.012_264) 1px, transparent 1px)", backgroundSize: "32px 32px" }} />

      <div className="relative mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-[oklch(0.72_0.012_264)]/20 bg-[oklch(0.72_0.012_264)]/5 px-4 py-1.5">
            <Sparkles className="h-3.5 w-3.5 text-[oklch(0.72_0.012_264)]" />
            <span className="text-xs font-medium text-[oklch(0.72_0.012_264)]">Interactive Preview</span>
          </div>
          <h2 className="text-4xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-5xl">
            See the Console{" "}
            <span className="bg-gradient-to-r from-[oklch(0.72_0.012_264)] to-[oklch(0.65_0.018_264)] bg-clip-text text-transparent">
              In Action
            </span>
          </h2>
           <p className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.72_0.012_264)]">
             Explore live workflows, manage agents with CRD-native tooling, enforce security policies, and inspect execution traces — all from the console.
           </p>
        </div>

        <div className="mt-10 flex justify-center">
          <div className="inline-flex rounded-2xl border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)]/80 p-1.5 backdrop-blur-sm">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "relative flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium transition-all",
                    isActive
                      ? "bg-[oklch(0.72_0.012_264)]/15 text-[oklch(0.958_0.004_264)] shadow-lg shadow-[oklch(0.72_0.012_264)]/5"
                      : "text-[oklch(0.72_0.012_264)]/70 hover:text-[oklch(0.958_0.004_264)]"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={inView ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mt-12"
        >
          <ConsoleShowcase activeTab={activeTab} />
        </motion.div>
      </div>
    </section>
  );
}

// ─── Console Showcase (Mock Browser Window) ───

function ConsoleShowcase({ activeTab }: { activeTab: "composer" | "workflow" | "agents" | "steps" | "policies" | "observatory" }) {
  return (
    <div className="mx-auto max-w-7xl">
      {/* Mock Browser Chrome */}
      <div className="overflow-hidden rounded-2xl border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.22_0.018_264)] shadow-2xl shadow-black/50">
        {/* Browser Title Bar */}
        <div className="flex items-center gap-3 border-b border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.16_0.012_264)] px-4 py-2.5">
          <div className="flex gap-1.5">
            <div className="h-3 w-3 rounded-full bg-[oklch(0.55_0.02_264)]" />
            <div className="h-3 w-3 rounded-full bg-[oklch(0.55_0.02_264)]/60" />
            <div className="h-3 w-3 rounded-full bg-[oklch(0.55_0.02_264)]/40" />
          </div>
          <div className="flex-1 rounded-lg bg-[oklch(0.30_0.020_264)] px-3 py-1 text-center">
            <span className="text-[11px] font-semibold text-[oklch(0.92_0.004_264)]">kubesynapse.local — Console</span>
          </div>
        </div>

        {/* Console Content */}
        <div className="flex h-[600px]">
          {/* Sidebar */}
          <div className="flex w-56 flex-col border-r border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.16_0.012_264)]">
            {/* Brand */}
            <div className="flex items-center gap-2.5 px-3 py-3 border-b border-[oklch(0.72_0.012_264)]/30">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[oklch(0.708_0.101_188)]">
                <KubeSynapseLogo className="h-4 w-4" />
              </div>
              <div>
                <span className="text-sm font-bold text-[oklch(0.99_0.004_264)]">KubeSynapse</span>
                <span className="ml-1.5 text-[9px] text-[oklch(0.72_0.012_264)]">AI Agent Platform</span>
              </div>
            </div>

            {/* View Navigation */}
            <div className="space-y-0.5 px-2 py-2">
              {[
                { icon: Bot, label: "Agents", count: 4, active: activeTab === "agents" },
                { icon: MessageSquare, label: "Chat", count: 0, active: false },
                { icon: Workflow, label: "Workflows", count: 2, active: activeTab === "workflow" || activeTab === "steps" || activeTab === "composer" },
                { icon: Shield, label: "Policies", count: 3, active: activeTab === "policies" },
                { icon: Telescope, label: "Observatory", count: 0, active: activeTab === "observatory" },
                { icon: Settings, label: "Settings", count: 0, active: false },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div
                    key={item.label}
                    className={cn(
                      "flex items-center justify-between rounded-lg px-2.5 py-2 text-xs transition-colors",
                      item.active
                        ? "bg-[oklch(0.708_0.101_188)]/20 text-[oklch(0.99_0.004_264)]"
                        : "text-[oklch(0.80_0.01_264)] hover:bg-[oklch(0.72_0.012_264)]/10 hover:text-[oklch(0.92_0.004_264)]"
                    )}
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className="h-4 w-4" />
                      <span className="font-semibold">{item.label}</span>
                    </div>
                    {item.count > 0 && (
                      <span className="rounded-md bg-[oklch(0.72_0.012_264)]/20 px-1.5 py-0.5 text-[10px] font-bold text-[oklch(0.92_0.004_264)]">
                        {item.count}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="mx-2 my-1 h-px bg-[oklch(0.72_0.012_264)]/30" />

            {/* Resource List */}
            <div className="flex-1 overflow-hidden px-2">
              <div className="mb-1.5 px-1">
                <span className="text-[9px] font-bold text-[oklch(0.72_0.012_264)] uppercase tracking-wider">Resources</span>
              </div>
              <div className="space-y-0.5">
                {[
                  { name: "data-pipeline", status: "running", type: "agent" },
                  { name: "security-scan", status: "pending", type: "agent" },
                  { name: "deploy-prod", status: "completed", type: "workflow" },
                  { name: "backup-db", status: "failed", type: "workflow" },
                  { name: "guard-default", status: "active", type: "policy" },
                ].map((item) => (
                  <div key={item.name} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-[oklch(0.72_0.012_264)]/10 cursor-pointer">
                    <div
                      className={cn(
                        "h-2 w-2 rounded-full shrink-0",
                        item.status === "running" && "bg-emerald-400",
                        item.status === "pending" && "bg-amber-400",
                        item.status === "completed" && "bg-sky-400",
                        item.status === "failed" && "bg-red-400",
                        item.status === "active" && "bg-violet-400"
                      )}
                    />
                    <span className="truncate text-[11px] font-medium text-[oklch(0.92_0.004_264)]">{item.name}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* New Button */}
            <div className="border-t border-[oklch(0.72_0.012_264)]/30 p-2">
              <div className="flex items-center justify-center rounded-lg border border-dashed border-[oklch(0.72_0.012_264)]/30 py-2 text-[10px] font-semibold text-[oklch(0.80_0.01_264)] hover:border-[oklch(0.708_0.101_188)]/50 hover:text-[oklch(0.708_0.101_188)] cursor-pointer transition-colors">
                + New
              </div>
            </div>
          </div>

          {/* Main Content Area */}
          <div className="flex flex-1 flex-col bg-[oklch(0.21_0.015_264)]">
            {/* Top Bar */}
            <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.16_0.012_264)] px-4 py-2">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5 rounded-lg border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.30_0.020_264)] px-2.5 py-1">
                  <span className="text-[11px] text-[oklch(0.72_0.012_264)]">Namespace:</span>
                  <span className="text-[11px] font-bold text-[oklch(0.99_0.004_264)]">kubesynapse</span>
                  <ChevronDown className="h-3 w-3 text-[oklch(0.72_0.012_264)]" />
                </div>
                <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1">
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  <span className="text-[10px] font-bold text-emerald-300">Healthy</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 rounded-lg border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.30_0.020_264)] px-2.5 py-1">
                  <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  <span className="text-[10px] font-semibold text-[oklch(0.92_0.004_264)]">Connected</span>
                </div>
                <div className="h-7 w-7 rounded-full bg-[oklch(0.708_0.101_188)]" />
              </div>
            </div>

            {/* Panel Content */}
            <div className="flex-1 overflow-hidden">
              {activeTab === "composer" && <FaithfulComposerPanel />}
              {activeTab === "workflow" && <FaithfulWorkflowLivePanel />}
              {activeTab === "agents" && <FaithfulAgentManagementPanel />}
              {activeTab === "steps" && <FaithfulWorkflowStepsPanel />}
              {activeTab === "policies" && <FaithfulPolicyEditorPanel />}
              {activeTab === "observatory" && <FaithfulExecutionObservatoryPanel />}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Composer Panel (WorkflowComposer replica — Incident Response) ───

function FaithfulComposerPanel() {
  const [paletteCollapsed, setPaletteCollapsed] = useState(false);

  const CANVAS_W = 1180;
  const CANVAS_H = 430;
  const CANVAS_SCALE = 0.92;
  const NODE_W = 176;

  // Balanced layout so the workflow feels like a polished product preview,
  // not a zoomed-in editor screenshot.
  const nodes = [
    { id: "trigger", label: "Security Alert", x: 36, y: 184, h: 70, status: "completed", agent: "", runtime: "", prompt: "", approval: false },
    { id: "triage", label: "Triage Alert", x: 248, y: 48, h: 112, status: "completed", agent: "security-analyst", runtime: "opencode", prompt: "Analyze severity, affected systems, IOC indicators.", approval: false },
    { id: "collect", label: "Collect Evidence", x: 248, y: 270, h: 112, status: "completed", agent: "forensics", runtime: "opencode", prompt: "Collect logs, memory dumps, network captures.", approval: false },
    { id: "assess", label: "Assess Impact", x: 506, y: 159, h: 112, status: "running", agent: "security-analyst", runtime: "opencode", prompt: "Assess blast radius, data exposure, business impact.", approval: false },
    { id: "contain", label: "Contain Threat", x: 766, y: 48, h: 112, status: "waiting", agent: "incident-response", runtime: "pi", prompt: "Isolate systems, block IPs, revoke credentials.", approval: true },
    { id: "eradicate", label: "Eradicate & Recover", x: 766, y: 270, h: 112, status: "waiting", agent: "incident-response", runtime: "opencode", prompt: "Remove malware, patch vulns, restore backups.", approval: false },
    { id: "report", label: "Post-Incident Report", x: 980, y: 159, h: 112, status: "waiting", agent: "doc-writer", runtime: "mistral-vibe", prompt: "Generate report with timeline, root cause, remediation.", approval: false },
  ];

  const edges = [
    { from: "trigger", to: "triage" }, { from: "trigger", to: "collect" },
    { from: "triage", to: "assess" }, { from: "collect", to: "assess" },
    { from: "assess", to: "contain" }, { from: "assess", to: "eradicate" },
    { from: "contain", to: "report" }, { from: "eradicate", to: "report" },
  ];

  const paletteAgents = [
    { name: "security-analyst", runtime: "opencode", status: "Running" },
    { name: "forensics", runtime: "opencode", status: "Running" },
    { name: "incident-response", runtime: "pi", status: "Idle" },
    { name: "doc-writer", runtime: "mistral-vibe", status: "Idle" },
    { name: "network-monitor", runtime: "opencode", status: "Running" },
  ];

  function statusDotColor(s: string) {
    return s === "Running" ? "bg-emerald-400" : s === "Failed" ? "bg-red-400" : "bg-[oklch(0.72_0.012_264)]/60";
  }

  function nodeAccentColor(r: string) {
    switch (r) {
      case "opencode": return "border-l-emerald-400";
      case "pi": return "border-l-violet-400";
      case "mistral-vibe": return "border-l-fuchsia-400";
      default: return "border-l-[oklch(0.80_0.01_264)]";
    }
  }

  function nodeStatusBorder(s: string) {
    switch (s) {
      case "completed": return "border-emerald-400/50";
      case "running": return "border-amber-400/50";
      case "failed": return "border-red-400/50";
      default: return "border-[oklch(0.72_0.012_264)]/40";
    }
  }

  function edgeStroke(status: string) {
    switch (status) {
      case "running": return "#fcd34d";
      case "completed": return "#6ee7b7";
      default: return "#94a3b8";
    }
  }

  function edgeMarker(status: string) {
    switch (status) {
      case "running": return "url(#edgeArrowRunning)";
      case "completed": return "url(#edgeArrowActive)";
      default: return "url(#edgeArrowIdle)";
    }
  }

  function handleTone(status: string) {
    switch (status) {
      case "running": return "bg-amber-400/70";
      case "completed": return "bg-emerald-400/60";
      default: return "bg-[oklch(0.72_0.012_264)]/40";
    }
  }

  function statusBadge(s: string) {
    switch (s) {
      case "completed":
        return <span className="inline-flex items-center gap-1 rounded-full border border-emerald-400/30 bg-emerald-400/15 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-300"><CheckCircle2 className="h-2.5 w-2.5" />Done</span>;
      case "running":
        return <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/30 bg-amber-400/15 px-1.5 py-0.5 text-[9px] font-semibold text-amber-300"><LoaderCircle className="h-2.5 w-2.5 animate-spin" />Running</span>;
      case "waiting":
        return <span className="inline-flex items-center gap-1 rounded-full border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.72_0.012_264)]/10 px-1.5 py-0.5 text-[9px] font-semibold text-[oklch(0.80_0.01_264)]"><Clock className="h-2.5 w-2.5" />Waiting</span>;
      default: return null;
    }
  }

  function runtimeIcon(r: string) {
    switch (r) {
      case "opencode": return <Code className="h-3 w-3 text-emerald-400" />;
      case "pi": return <Cpu className="h-3 w-3 text-violet-400" />;
      case "mistral-vibe": return <Sparkles className="h-3 w-3 text-fuchsia-400" />;
      default: return <Cpu className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />;
    }
  }

  function nodeCenterY(node: typeof nodes[number]) {
    return node.y + node.h / 2;
  }

  // Curved connector that stops just before the target handle so the arrowhead
  // stays elegant instead of overlapping the cards.
  function edgePath(from: typeof nodes[0], to: typeof nodes[0]) {
    const fx = from.x + NODE_W + 2;
    const fy = nodeCenterY(from);
    const tx = to.x - 3;
    const ty = nodeCenterY(to);
    const span = Math.max(tx - fx, 88);
    const curve = Math.min(Math.max(span * 0.38, 54), 132);
    return `M ${fx} ${fy} C ${fx + curve} ${fy}, ${tx - curve} ${ty}, ${tx} ${ty}`;
  }

  return (
    <div className="flex h-full flex-col bg-[oklch(0.21_0.015_264)]">
      {/* ── Toolbar ── */}
      <div className="border-b border-[oklch(0.72_0.012_264)]/20 bg-[oklch(0.16_0.012_264)] shrink-0">
        <div className="flex items-center gap-2 px-3 py-2">
          <div className="flex items-center gap-2 shrink-0">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer">
              <ArrowRight className="h-4 w-4 rotate-180 text-[oklch(0.80_0.01_264)]" />
            </div>
            <div>
              <div className="text-[11px] font-bold text-[oklch(0.99_0.004_264)]">incident-response</div>
              <div className="text-[9px] text-[oklch(0.72_0.012_264)]/60">Automated incident response workflow</div>
            </div>
          </div>
          <div className="flex-1 min-w-0 ml-4">
            <div className="flex items-center gap-1.5">
              <span className="text-[8px] font-semibold text-[oklch(0.72_0.012_264)]/50 uppercase tracking-wider">Input</span>
            </div>
            <div className="mt-0.5 rounded-md border border-[oklch(0.72_0.012_264)]/25 bg-[oklch(0.28_0.018_264)] px-2 py-1 text-[10px] text-[oklch(0.92_0.004_264)] font-mono truncate">
              Alert: Suspicious outbound connection from prod-web-03 → 185.220.101.42:443
            </div>
            <div className="mt-0.5 text-[8px] text-[oklch(0.72_0.012_264)]/40 font-mono">
              Referenced as <span className="text-[oklch(0.70_0.14_175)]/70">{'{{input}}'}</span> in step prompts
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0 ml-auto">
            <span className="flex items-center gap-1 text-[9px] font-semibold text-amber-400">
              <Circle className="h-2 w-2 fill-current" /><span className="hidden sm:inline">Unsaved</span>
            </span>
            <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/25 bg-[oklch(0.28_0.018_264)] hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer" title="Auto-layout">
              <LayoutGrid className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />
            </div>
            <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/20 bg-[oklch(0.72_0.012_264)]/15 cursor-pointer" title="Layout direction">
              <ArrowLeftRight className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />
            </div>
            <div className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer relative" title="Live activity">
              <Radio className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />
              <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            </div>
            <div className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer" title="Maximize">
              <Maximize2 className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />
            </div>
            <div className="flex h-7 items-center gap-1 rounded-lg bg-[oklch(0.708_0.101_188)] px-2.5 hover:bg-[oklch(0.708_0.101_188)]/90 cursor-pointer">
              <Save className="h-3 w-3 text-[oklch(0.158_0.007_264)]" />
              <span className="text-[10px] font-bold text-[oklch(0.158_0.007_264)]">Save</span>
            </div>
            <div className="flex h-7 items-center gap-1 rounded-lg bg-emerald-500/20 border border-emerald-500/30 px-2.5 hover:bg-emerald-500/30 cursor-pointer">
              <Play className="h-3 w-3 text-emerald-300" />
              <span className="text-[10px] font-bold text-emerald-300">Run</span>
            </div>
          </div>
        </div>

        {/* Status bar */}
        <div className="flex items-center gap-3 px-3 py-1 border-t border-[oklch(0.72_0.012_264)]/20 bg-[oklch(0.12_0.012_264)] text-[10px]">
          <span className="flex items-center gap-1">
            <LoaderCircle className="h-3 w-3 animate-spin text-amber-400" />
            <span className="font-bold text-amber-400">running</span>
          </span>
          <span className="font-mono text-[oklch(0.80_0.01_264)]">#a3f8c2d1</span>
          <span className="inline-flex items-center rounded-full border border-[oklch(0.72_0.012_264)]/30 px-1.5 py-0.5 text-[9px] font-semibold text-[oklch(0.80_0.01_264)]">2/7 steps</span>
          <div className="flex-1 max-w-48 flex items-center gap-1.5">
            <div className="h-1.5 flex-1 rounded-full bg-[oklch(0.72_0.012_264)]/30 overflow-hidden">
              <div className="h-full w-[29%] rounded-full bg-amber-400 animate-pulse" />
            </div>
            <span className="text-[9px] font-mono text-[oklch(0.80_0.01_264)]">29%</span>
          </div>
        </div>
      </div>

      {/* ── Canvas ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* Node Palette */}
        <div className={cn("border-r border-[oklch(0.72_0.012_264)]/20 bg-[oklch(0.16_0.012_264)] flex flex-col shrink-0 transition-all duration-200", paletteCollapsed ? "w-10" : "w-44")}>
          {paletteCollapsed ? (
            <div className="flex flex-col items-center py-2 gap-2">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer" onClick={() => setPaletteCollapsed(false)}>
                <PanelLeftOpen className="h-3.5 w-3.5 text-[oklch(0.80_0.01_264)]" />
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/20 px-2 py-1.5">
                <span className="text-[9px] font-bold text-[oklch(0.80_0.01_264)] uppercase tracking-wider">Agents</span>
                <div className="flex items-center gap-1">
                  <div className="flex h-5 w-5 items-center justify-center rounded hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer">
                    <Plus className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />
                  </div>
                  <div className="flex h-5 w-5 items-center justify-center rounded hover:bg-[oklch(0.72_0.012_264)]/15 cursor-pointer" onClick={() => setPaletteCollapsed(true)}>
                    <PanelLeftClose className="h-3 w-3 text-[oklch(0.80_0.01_264)]" />
                  </div>
                </div>
              </div>
              <div className="px-2 py-1">
                <div className="flex items-center gap-1.5 rounded-md border border-[oklch(0.72_0.012_264)]/25 bg-[oklch(0.28_0.018_264)] px-2 py-1">
                  <Search className="h-2.5 w-2.5 text-[oklch(0.72_0.012_264)]" />
                  <span className="text-[9px] text-[oklch(0.72_0.012_264)]">Search...</span>
                </div>
              </div>
              <div className="flex-1 overflow-auto px-2 py-1">
                {[
                  { runtime: "opencode", icon: <Code className="h-2.5 w-2.5 text-emerald-400" /> },
                  { runtime: "pi", icon: <Cpu className="h-2.5 w-2.5 text-violet-400" /> },
                  { runtime: "mistral-vibe", icon: <Sparkles className="h-2.5 w-2.5 text-fuchsia-400" /> },
                ].map(group => {
                  const agents = paletteAgents.filter(a => a.runtime === group.runtime);
                  if (!agents.length) return null;
                  return (
                    <div key={group.runtime} className="mb-1">
                      <div className="flex items-center gap-1 px-1 py-0.5">
                        <ChevronDown className="h-2.5 w-2.5 text-[oklch(0.72_0.012_264)]" />
                        {group.icon}
                        <span className="text-[9px] font-semibold text-[oklch(0.80_0.01_264)]">{group.runtime}</span>
                      </div>
                      <div className="ml-2 space-y-0.5">
                        {agents.map(agent => (
                          <div key={agent.name} className="flex items-center gap-1.5 rounded-md px-1.5 py-1 hover:bg-[oklch(0.72_0.012_264)]/10 cursor-grab active:cursor-grabbing">
                            <GripVertical className="h-2.5 w-2.5 text-[oklch(0.72_0.012_264)]" />
                            <div className={cn("h-1.5 w-1.5 rounded-full shrink-0", statusDotColor(agent.status))} />
                            <span className="truncate text-[10px] font-medium text-[oklch(0.92_0.004_264)]">{agent.name}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {/* Canvas */}
        <div className="flex-1 overflow-auto bg-[oklch(0.21_0.015_264)]">
          <div className="flex min-h-full min-w-full items-start justify-center px-6 py-5">
            <div className="relative" style={{ width: CANVAS_W * CANVAS_SCALE, height: CANVAS_H * CANVAS_SCALE }}>
              <div
                className="absolute left-0 top-0 origin-top-left"
                style={{ width: CANVAS_W, height: CANVAS_H, transform: `scale(${CANVAS_SCALE})` }}
              >
                {/* Grid */}
                <div className="absolute inset-0 opacity-[0.06]" style={{ backgroundImage: "radial-gradient(oklch(0.72_0.012_264) 1px, transparent 1px)", backgroundSize: "24px 24px" }} />

                {/* SVG Edges */}
                <svg
                  className="absolute inset-0 pointer-events-none"
                  width={CANVAS_W}
                  height={CANVAS_H}
                  viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
                  style={{ zIndex: 1 }}
                >
                  <defs>
                    <marker id="edgeArrowIdle" markerWidth="8" markerHeight="8" refX="6.6" refY="4" orient="auto" markerUnits="userSpaceOnUse">
                      <path d="M0,0 L8,4 L0,8 Z" fill="#94a3b8" />
                    </marker>
                    <marker id="edgeArrowActive" markerWidth="8" markerHeight="8" refX="6.6" refY="4" orient="auto" markerUnits="userSpaceOnUse">
                      <path d="M0,0 L8,4 L0,8 Z" fill="#6ee7b7" />
                    </marker>
                    <marker id="edgeArrowRunning" markerWidth="8" markerHeight="8" refX="6.6" refY="4" orient="auto" markerUnits="userSpaceOnUse">
                      <path d="M0,0 L8,4 L0,8 Z" fill="#fcd34d" />
                    </marker>
                  </defs>
                  {edges.map((edge, i) => {
                    const fn = nodes.find(n => n.id === edge.from)!;
                    const tn = nodes.find(n => n.id === edge.to)!;
                    return (
                      <path
                        key={i}
                        d={edgePath(fn, tn)}
                        stroke={edgeStroke(fn.status)}
                        strokeWidth={fn.status === "running" ? 2.5 : 2.2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                        opacity={fn.status === "waiting" ? 0.7 : 0.92}
                        markerEnd={edgeMarker(fn.status)}
                        strokeDasharray={fn.status === "running" ? "7 6" : undefined}
                      />
                    );
                  })}
                </svg>

                {/* Nodes */}
                {nodes.map((node, i) => (
                  <motion.div
                    key={node.id}
                    initial={{ opacity: 0, scale: 0.85 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.1 + i * 0.06 }}
                    className={cn(
                      "absolute w-[176px] overflow-hidden rounded-2xl border border-l-2 bg-[oklch(0.22_0.018_264)] shadow-[0_12px_40px_rgba(0,0,0,0.45)] backdrop-blur-sm",
                      nodeAccentColor(node.runtime),
                      nodeStatusBorder(node.status),
                      node.status === "running" && "ring-2 ring-amber-400/40"
                    )}
                    style={{ left: node.x, top: node.y, height: node.h, zIndex: 2 }}
                  >
                    {node.status === "running" && (
                      <div className="absolute inset-0 rounded-2xl border-2 border-amber-400/30 pointer-events-none animate-pulse" />
                    )}

                    {/* Header */}
                    <div className="flex items-center gap-2 border-b border-[oklch(0.72_0.012_264)]/20 px-3 py-2">
                      {runtimeIcon(node.runtime)}
                      <span className="flex-1 truncate text-[11px] font-bold text-[oklch(0.99_0.004_264)]">{node.label}</span>
                      {statusBadge(node.status)}
                    </div>

                    {/* Body */}
                    <div className="space-y-1.5 px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className="inline-flex max-w-[112px] items-center truncate rounded-md border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.32_0.020_264)] px-1.5 py-0.5 text-[9px] font-semibold text-[oklch(0.92_0.004_264)]">
                          {node.agent || "unassigned"}
                        </span>
                        {node.status === "completed" && <span className="text-[9px] font-mono text-[oklch(0.72_0.012_264)]">1.2s</span>}
                        {node.status === "running" && <span className="text-[9px] font-mono text-amber-300">2.1s</span>}
                      </div>
                      {node.prompt && (
                        <p className="line-clamp-2 text-[9px] leading-tight text-[oklch(0.80_0.01_264)]">{node.prompt}</p>
                      )}
                      <div className="flex flex-wrap items-center gap-1">
                        {node.approval && (
                          <span className="inline-flex items-center gap-0.5 rounded-full border border-orange-400/30 bg-orange-400/15 px-1.5 py-0.5 text-[8px] font-semibold text-orange-300">
                            <UserCheck className="h-2 w-2" /> HITL
                          </span>
                        )}
                        {node.id === "assess" && (
                          <span className="inline-flex items-center gap-0.5 rounded-full border border-purple-400/30 bg-purple-400/15 px-1.5 py-0.5 text-[8px] font-semibold text-purple-300">
                            <GitBranch className="h-2 w-2" /> Conditional
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Connection handles */}
                    {node.id !== "trigger" && (
                      <div className={cn("absolute -left-1 top-1/2 h-4 w-1.5 -translate-y-1/2 rounded-full", handleTone(node.status))} />
                    )}
                    {node.id !== "report" && (
                      <div className={cn("absolute -right-1 top-1/2 h-4 w-1.5 -translate-y-1/2 rounded-full", handleTone(node.status))} />
                    )}
                  </motion.div>
                ))}

{/* Mini toolbar */}
                <div className="absolute bottom-3 left-4 flex items-center gap-1.5 rounded-lg border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.22_0.018_264)]/95 px-2 py-1.5 shadow-lg shadow-black/20">
                  <div className="rounded bg-[oklch(0.72_0.012_264)]/20 px-1.5 py-0.5 text-[9px] font-semibold text-[oklch(0.92_0.004_264)]">Trigger</div>
                  <div className="rounded bg-[oklch(0.72_0.012_264)]/20 px-1.5 py-0.5 text-[9px] font-semibold text-[oklch(0.92_0.004_264)]">Agent Step</div>
                </div>

                {/* Zoom controls */}
                <div className="absolute bottom-3 right-4 flex flex-col gap-1">
                  <div className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.22_0.018_264)]/95 hover:bg-[oklch(0.72_0.012_264)]/20">
                    <span className="text-[10px] font-bold text-[oklch(0.92_0.004_264)]">+</span>
                  </div>
                  <div className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.22_0.018_264)]/95 hover:bg-[oklch(0.72_0.012_264)]/20">
                    <span className="text-[10px] font-bold text-[oklch(0.92_0.004_264)]">−</span>
                  </div>
                  <div className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/30 bg-[oklch(0.22_0.018_264)]/95 hover:bg-[oklch(0.72_0.012_264)]/20">
                    <span className="text-[8px] font-semibold text-[oklch(0.80_0.01_264)]">Fit</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Live Workflow Panel (WorkflowLiveView replica) ───

function FaithfulWorkflowLivePanel() {
  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/10 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)]">
            <Workflow className="h-4 w-4 text-[oklch(0.72_0.012_264)]" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">data-pipeline</h3>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">Running · Started 2m ago</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-md bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-400">Running</div>
          <div className="rounded-md bg-[oklch(0.72_0.012_264)]/10 px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]">v1.2.0</div>
        </div>
      </div>

      {/* Progress Summary Bar */}
      <div className="border-b border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.12_0.018_264)] px-4 py-2">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            <span className="text-[11px] font-medium text-emerald-400">3</span>
            <span className="text-[10px] text-[oklch(0.72_0.012_264)]/50">done</span>
          </div>
          <div className="flex items-center gap-1.5">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin text-sky-400" />
            <span className="text-[11px] font-medium text-sky-400">1</span>
            <span className="text-[10px] text-[oklch(0.72_0.012_264)]/50">running</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3.5 w-3.5 text-[oklch(0.72_0.012_264)]/40" />
            <span className="text-[11px] font-medium text-[oklch(0.72_0.012_264)]/60">2</span>
            <span className="text-[10px] text-[oklch(0.72_0.012_264)]/50">waiting</span>
          </div>
          <div className="flex-1" />
          <div className="flex h-1.5 w-32 overflow-hidden rounded-full bg-[oklch(0.18_0.025_264)]">
            <div className="w-[50%] rounded-full bg-gradient-to-r from-emerald-500 to-emerald-400" />
            <div className="w-[17%] rounded-full bg-sky-400 animate-pulse" />
          </div>
        </div>
      </div>

      {/* Steps List */}
      <div className="flex-1 overflow-auto p-3">
        <div className="space-y-2">
          {[
            { name: "Fetch Source Data", status: "completed", agent: "data-pipeline", time: "1.2s", icon: CheckCircle2, color: "text-emerald-400" },
            { name: "Transform Records", status: "completed", agent: "data-pipeline", time: "3.4s", icon: CheckCircle2, color: "text-emerald-400" },
            { name: "Validate Schema", status: "completed", agent: "security-scan", time: "0.8s", icon: CheckCircle2, color: "text-emerald-400" },
            { name: "Load to Warehouse", status: "running", agent: "data-pipeline", time: "2.1s", icon: LoaderCircle, color: "text-sky-400" },
            { name: "Generate Reports", status: "waiting", agent: "data-pipeline", time: "—", icon: Clock, color: "text-[oklch(0.72_0.012_264)]/40" },
            { name: "Notify Team", status: "waiting", agent: "data-pipeline", time: "—", icon: Clock, color: "text-[oklch(0.72_0.012_264)]/40" },
          ].map((step, i) => {
            const Icon = step.icon;
            return (
              <div
                key={i}
                className={cn(
                  "flex items-center gap-3 rounded-lg border px-3 py-2 transition-colors",
                  step.status === "running"
                    ? "border-sky-500/20 bg-sky-500/5"
                    : "border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.12_0.018_264)]/50 hover:bg-[oklch(0.18_0.025_264)]/50"
                )}
              >
                <Icon className={cn("h-4 w-4 shrink-0", step.color, step.status === "running" && "animate-spin")} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">{step.name}</span>
                    <span className="rounded bg-[oklch(0.72_0.012_264)]/10 px-1.5 py-0.5 text-[9px] text-[oklch(0.72_0.012_264)]">{step.agent}</span>
                  </div>
                </div>
                <span className="text-[10px] font-mono text-[oklch(0.72_0.012_264)]/50">{step.time}</span>
              </div>
            );
          })}
        </div>

        {/* Approval Gate */}
        <div className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-amber-400" />
            <span className="text-[11px] font-medium text-amber-400">Approval Required</span>
            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-400">HITL</span>
          </div>
          <p className="mt-1 text-[10px] text-[oklch(0.72_0.012_264)]/60">Step "Generate Reports" requires human approval before execution.</p>
          <div className="mt-2 flex gap-2">
            <div className="rounded-md bg-emerald-500/10 px-2 py-1 text-[10px] font-medium text-emerald-400">Approve</div>
            <div className="rounded-md bg-red-500/10 px-2 py-1 text-[10px] font-medium text-red-400">Reject</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Agent Management Panel (AgentManagementPanel replica) ───

function FaithfulAgentManagementPanel() {
  const [activeTab, setActiveTab] = useState("basics");
  const [runtimeKind, setRuntimeKind] = useState("opencode");
  const agent = { name: "data-pipeline", model: "gpt-4o", status: "running", runtimeKind, systemPrompt: "You are a data pipeline agent. Fetch, transform, and load data from source systems to the warehouse. Validate schemas and handle errors gracefully.", policyRef: "data-guard-policy", capabilities: 3, accessLevel: "Connected" };

  const runtimeMeta: Record<string, { label: string; desc: string; tone: string }> = {
    opencode: { label: "OpenCode", desc: "Default persistent runtime with memory, skills, and workspace state", tone: "border-emerald-500/30 bg-emerald-500/5 text-emerald-200" },
    pi: { label: "Pi", desc: "Alternative lightweight runtime with streaming tool-use via pi bridge", tone: "border-violet-500/30 bg-violet-500/5 text-violet-200" },
    "mistral-vibe": { label: "Mistral Vibe", desc: "Mistral-backed runtime bridge with content generation focus", tone: "border-fuchsia-500/30 bg-fuchsia-500/5 text-fuchsia-200" },
  };

  const rt = runtimeMeta[runtimeKind];
  const RUNTIMES = ["opencode", "pi", "mistral-vibe"];

  return (
    <div className="h-full overflow-auto bg-[oklch(0.145_0.022_264)] p-4">
      <div className="rounded-2xl border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.12_0.018_264)] shadow-2xl overflow-hidden">
        {/* Card Header */}
        <div className="p-5 border-b border-[oklch(0.72_0.012_264)]/10">
          <div className="flex min-w-0 items-start gap-3">
            <div className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border shadow-inner ${rt.tone}`}>
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-start gap-2">
                <span className="text-base font-semibold text-[oklch(0.958_0.004_264)]">{agent.name}</span>
                <span className="inline-flex items-center rounded-full bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 text-[10px] font-medium text-emerald-400">running</span>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[oklch(0.72_0.012_264)]/60">
                <span>{agent.capabilities} capabilities</span>
                <span className="inline-flex items-center gap-1 text-emerald-400"><ShieldCheck className="h-3 w-3" />Policy attached</span>
              </div>
              <p className="text-[11px] text-[oklch(0.72_0.012_264)]/40">Edit model, runtime, policy, and capabilities. Saving updates the CRD spec and triggers operator reconcile.</p>
              <div className="flex flex-wrap gap-2">
                <span className="inline-flex rounded-full border border-[oklch(0.72_0.012_264)]/20 bg-[oklch(0.18_0.025_264)] px-2 py-0.5 text-[9px] font-medium text-[oklch(0.72_0.012_264)]/50 uppercase tracking-wider">Runtime: {rt.label}</span>
                <span className="inline-flex rounded-full border border-sky-500/25 bg-sky-500/10 px-2 py-0.5 text-[9px] font-medium text-sky-400 uppercase tracking-wider">{agent.accessLevel}</span>
                <span className="inline-flex rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[9px] font-medium text-emerald-400 uppercase tracking-wider">Policy Bound</span>
              </div>
            </div>
          </div>
        </div>

        {/* Metric Panels */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 p-4 border-b border-[oklch(0.72_0.012_264)]/10">
          <div className={`rounded-xl border p-3 ${rt.tone}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[9px] font-bold uppercase tracking-wider">Runtime</span>
              <span className="text-sm font-bold text-[oklch(0.958_0.004_264)]">{rt.label}</span>
            </div>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">Default persistent path</p>
          </div>
          <div className="rounded-xl border border-sky-500/30 bg-sky-500/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[9px] font-bold uppercase tracking-wider text-sky-400">MCP Connections</span>
              <span className="text-sm font-bold text-[oklch(0.958_0.004_264)]">3</span>
            </div>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">1 sidecar · 2 servers</p>
          </div>
          <div className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[9px] font-bold uppercase tracking-wider text-violet-400">Skills</span>
              <span className="text-sm font-bold text-[oklch(0.958_0.004_264)]">4</span>
            </div>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">2 catalog · 2 files</p>
          </div>
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[9px] font-bold uppercase tracking-wider text-amber-400">Access Level</span>
              <span className="text-sm font-bold text-[oklch(0.958_0.004_264)]">{agent.accessLevel}</span>
            </div>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">External systems attached</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="p-4">
          <div className="flex flex-wrap gap-1 rounded-2xl border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.10_0.015_264)] p-1.5 mb-4">
            {[
              { id: "basics", label: "Basics" },
              { id: "runtime", label: "Runtime" },
              { id: "behavior", label: "System Prompt" },
              { id: "mcp", label: "MCP & Tools" },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "rounded-xl px-3 py-1.5 text-[11px] font-medium transition-all",
                  activeTab === tab.id
                    ? "bg-[oklch(0.72_0.012_264)]/15 text-[oklch(0.958_0.004_264)] shadow-sm"
                    : "text-[oklch(0.72_0.012_264)]/50 hover:text-[oklch(0.72_0.012_264)]"
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          {activeTab === "basics" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)] p-4">
                <h4 className="text-sm font-semibold text-[oklch(0.958_0.004_264)] mb-1">Agent identity</h4>
                <p className="text-[10px] text-[oklch(0.72_0.012_264)]/50 mb-3">Model and policy govern how this agent responds and which guardrails apply.</p>
                <div className="space-y-3">
                  <div>
                    <span className="text-[10px] font-medium text-[oklch(0.72_0.012_264)]/60">Model</span>
                    <div className="mt-1 flex items-center justify-between rounded-lg border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-3 py-2">
                      <span className="text-[11px] text-[oklch(0.958_0.004_264)]">{agent.model}</span>
                      <ChevronDown className="h-3 w-3 text-[oklch(0.72_0.012_264)]/40" />
                    </div>
                  </div>
                  <div>
                    <span className="text-[10px] font-medium text-[oklch(0.72_0.012_264)]/60">Policy</span>
                    <div className="mt-1 flex items-center justify-between rounded-lg border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-3 py-2">
                      <span className="text-[11px] text-[oklch(0.958_0.004_264)]">{agent.policyRef}</span>
                      <ChevronDown className="h-3 w-3 text-[oklch(0.72_0.012_264)]/40" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === "runtime" && (
            <div className="rounded-xl border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)] p-4">
              <h4 className="text-sm font-semibold text-[oklch(0.958_0.004_264)] mb-1">Runtime profile</h4>
              <p className="text-[10px] text-[oklch(0.72_0.012_264)]/50 mb-3">Choose the agent runtime that fits your use case. Each runtime provides different capabilities and models.</p>
              <div className="space-y-1.5">
                {RUNTIMES.map(rid => {
                  const info = runtimeMeta[rid];
                  const selected = runtimeKind === rid;
                  return (
                    <div
                      key={rid}
                      onClick={() => setRuntimeKind(rid)}
                      className={cn(
                        "rounded-lg border px-3 py-2.5 cursor-pointer transition-all flex items-center justify-between",
                        selected ? info.tone : "border-[oklch(0.72_0.012_264)]/10 hover:border-[oklch(0.72_0.012_264)]/20"
                      )}
                    >
                      <div>
                        <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">{info.label}</span>
                        <p className="text-[9px] text-[oklch(0.72_0.012_264)]/40">{info.desc}</p>
                      </div>
                      {selected && <Check className="h-3.5 w-3.5" />}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {activeTab === "behavior" && (
            <div className="rounded-xl border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)] p-4">
              <h4 className="text-sm font-semibold text-[oklch(0.958_0.004_264)] mb-1">System prompt</h4>
              <p className="text-[10px] text-[oklch(0.72_0.012_264)]/50 mb-3">The system prompt defines the agent's persona, behavioral constraints, and tool-use instructions.</p>
              <div className="rounded-lg border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] p-3 font-mono text-[10px] text-[oklch(0.72_0.012_264)]/70 leading-relaxed min-h-[90px]">
                {agent.systemPrompt}
              </div>
              <div className="flex items-center gap-2 mt-3">
                <span className="text-[9px] text-[oklch(0.72_0.012_264)]/40">Max length: </span>
                <span className="rounded bg-[oklch(0.72_0.012_264)]/10 px-2 py-0.5 text-[10px] text-[oklch(0.72_0.012_264)]">12,000 chars</span>
                <span className="text-[9px] text-[oklch(0.72_0.012_264)]/40">· Rate limit: </span>
                <span className="rounded bg-[oklch(0.72_0.012_264)]/10 px-2 py-0.5 text-[10px] text-[oklch(0.72_0.012_264)]">Unlimited</span>
              </div>
            </div>
          )}

          {activeTab === "mcp" && (
            <div className="rounded-xl border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)] p-4">
              <h4 className="text-sm font-semibold text-[oklch(0.958_0.004_264)] mb-1">MCP & Tool Connections</h4>
              <p className="text-[10px] text-[oklch(0.72_0.012_264)]/50 mb-3">Agents discover and call tools through the Model Context Protocol — sidecars for local access, servers for shared tooling.</p>
              <div className="space-y-2">
                {[
                  { name: "code-exec", type: "sidecar", status: "healthy", desc: "Sandboxed code execution" },
                  { name: "database", type: "sidecar", status: "healthy", desc: "SQL query interface" },
                  { name: "web-search", type: "server", status: "healthy", desc: "Web search and retrieval" },
                ].map(mcp => (
                  <div key={mcp.name} className="flex items-center justify-between rounded-lg border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.18_0.025_264)]/50 px-3 py-2">
                    <div className="flex items-center gap-2.5">
                      <div className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                      <div>
                        <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">{mcp.name}</span>
                        <p className="text-[9px] text-[oklch(0.72_0.012_264)]/40">{mcp.desc}</p>
                      </div>
                    </div>
                    <span className="rounded bg-sky-500/10 px-2 py-0.5 text-[9px] font-medium text-sky-400">{mcp.type}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <div className="flex h-7 items-center gap-1 rounded-lg bg-[oklch(0.708_0.101_188)]/20 border border-[oklch(0.708_0.101_188)]/30 px-2 hover:bg-[oklch(0.708_0.101_188)]/30 cursor-pointer">
                  <Plus className="h-3 w-3 text-[oklch(0.708_0.101_188)]" />
                  <span className="text-[10px] font-medium text-[oklch(0.708_0.101_188)]">Add MCP connection</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="border-t border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)] p-3 flex items-center justify-between">
          <span className="text-[9px] text-[oklch(0.72_0.012_264)]/40">Unsaved changes — reconcile on save</span>
          <div className="flex items-center gap-2">
            <div className="flex h-7 items-center gap-1 rounded-lg bg-[oklch(0.708_0.101_188)] px-3 hover:bg-[oklch(0.708_0.101_188)]/90 cursor-pointer">
              <Save className="h-3 w-3 text-[oklch(0.158_0.007_264)]" />
              <span className="text-[10px] font-bold text-[oklch(0.158_0.007_264)]">Save Agent</span>
            </div>
            <div className="flex h-7 items-center gap-1 rounded-lg bg-emerald-500/20 border border-emerald-500/30 px-3 hover:bg-emerald-500/30 cursor-pointer">
              <Play className="h-3 w-3 text-emerald-300" />
              <span className="text-[10px] font-bold text-emerald-300">Test Run</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Workflow Steps Panel (WorkflowStepsList replica) ───

function FaithfulWorkflowStepsPanel() {
  const steps = [
    { name: "Fetch Source Data", agent: "data-pipeline", status: "completed", deps: [], time: "1.2s", output: "1,247 records" },
    { name: "Transform Records", agent: "data-pipeline", status: "completed", deps: ["Fetch Source Data"], time: "3.4s", output: "1,247 transformed" },
    { name: "Validate Schema", agent: "security-scan", status: "completed", deps: ["Transform Records"], time: "0.8s", output: "Schema valid" },
    { name: "Load to Warehouse", agent: "data-pipeline", status: "running", deps: ["Validate Schema"], time: "2.1s", output: "Loading..." },
    { name: "Generate Reports", agent: "data-pipeline", status: "waiting", deps: ["Load to Warehouse"], time: "—", output: "—" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/10 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)]">
            <ListChecks className="h-4 w-4 text-[oklch(0.72_0.012_264)]" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">Steps</h3>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">{steps.length} steps · model the sequence, assign agents, set dependencies</p>
          </div>
        </div>
        <div className="rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]">
          + Add step
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-1 border-b border-[oklch(0.72_0.012_264)]/10 px-3 py-1.5">
        {["all", "active", "attention", "activity", "complete"].map((tab, i) => (
          <button
            key={tab}
            className={cn(
              "rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors",
              i === 0 ? "bg-[oklch(0.72_0.012_264)]/10 text-[oklch(0.958_0.004_264)]" : "text-[oklch(0.72_0.012_264)]/50 hover:text-[oklch(0.72_0.012_264)]"
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Step Cards */}
      <div className="flex-1 overflow-auto p-3">
        <div className="space-y-2.5">
          {steps.map((step, i) => {
            const statusIcon = step.status === "completed" ? CheckCircle2 : step.status === "running" ? LoaderCircle : step.status === "failed" ? XCircle : Clock;
            const statusColor = step.status === "completed" ? "text-emerald-400" : step.status === "running" ? "text-sky-400" : step.status === "failed" ? "text-red-400" : "text-[oklch(0.72_0.012_264)]/40";
            const borderColor = step.status === "running" ? "border-sky-500/20" : "border-[oklch(0.72_0.012_264)]/10";

            return (
              <div key={i} className={cn("rounded-lg border bg-[oklch(0.12_0.018_264)]/50 p-2.5", borderColor)}>
                <div className="flex items-start gap-2.5">
                  <div className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-[oklch(0.18_0.025_264)]">
                    {createElement(statusIcon, { className: cn("h-3.5 w-3.5", statusColor, step.status === "running" && "animate-spin") })}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">{step.name}</span>
                      <span className="rounded bg-[oklch(0.72_0.012_264)]/10 px-1.5 py-0.5 text-[9px] text-[oklch(0.72_0.012_264)]">{step.agent}</span>
                    </div>
                    {step.deps.length > 0 && (
                      <div className="mt-1 flex items-center gap-1">
                        <GitBranch className="h-2.5 w-2.5 text-[oklch(0.72_0.012_264)]/30" />
                        <span className="text-[9px] text-[oklch(0.72_0.012_264)]/40">depends on: {step.deps.join(", ")}</span>
                      </div>
                    )}
                    <div className="mt-1.5 flex items-center gap-3">
                      <span className="text-[9px] font-mono text-[oklch(0.72_0.012_264)]/50">⏱ {step.time}</span>
                      <span className="text-[9px] text-[oklch(0.72_0.012_264)]/50">📦 {step.output}</span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Policy Editor Panel (PolicyEditor replica) ───

function FaithfulPolicyEditorPanel() {
  const [selectedPolicy, setSelectedPolicy] = useState(0);
  const policies = [
    { name: "guard-default", type: "guardrails", scope: "global" },
    { name: "access-restrict", type: "access", scope: "namespace" },
    { name: "tool-allowlist", type: "tools", scope: "agent" },
  ];

  return (
    <div className="flex h-full">
      {/* Policy Sidebar */}
      <div className="w-52 border-r border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)]">
        <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/10 px-3 py-2">
          <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">Policies</span>
          <div className="rounded-md bg-[oklch(0.72_0.012_264)]/10 px-1.5 py-0.5 text-[9px] text-[oklch(0.72_0.012_264)]">{policies.length}</div>
        </div>
        <div className="p-2">
          <div className="mb-2 rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]/50">
            🔍 Search policies...
          </div>
          <div className="space-y-1">
            {policies.map((policy, i) => (
              <button
                key={policy.name}
                onClick={() => setSelectedPolicy(i)}
                className={cn(
                  "w-full rounded-lg px-2.5 py-2 text-left transition-colors",
                  selectedPolicy === i ? "bg-[oklch(0.72_0.012_264)]/10" : "hover:bg-[oklch(0.72_0.012_264)]/5"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">{policy.name}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-1.5">
                  <span className="rounded bg-violet-500/10 px-1 py-0.5 text-[9px] text-violet-400">{policy.type}</span>
                  <span className="text-[9px] text-[oklch(0.72_0.012_264)]/40">{policy.scope}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Policy Editor */}
      <div className="flex-1 flex-col bg-[oklch(0.145_0.022_264)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/10 px-4 py-2.5">
          <div className="flex items-center gap-3">
            <Shield className="h-4 w-4 text-[oklch(0.72_0.012_264)]" />
            <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">{policies[selectedPolicy].name}</h3>
          </div>
          <div className="flex gap-2">
            <div className="rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]">Delete</div>
            <div className="rounded-md bg-[oklch(0.72_0.012_264)]/15 px-2 py-1 text-[10px] font-medium text-[oklch(0.958_0.004_264)]">Save</div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[oklch(0.72_0.012_264)]/10">
          {["Guardrails", "Access", "Tools", "Memory"].map((tab, i) => (
            <button
              key={tab}
              className={cn(
                "px-3 py-1.5 text-[11px] font-medium transition-colors",
                i === 0 ? "border-b-2 border-[oklch(0.72_0.012_264)] text-[oklch(0.958_0.004_264)]" : "text-[oklch(0.72_0.012_264)]/50 hover:text-[oklch(0.72_0.012_264)]"
              )}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Editor Content */}
        <div className="flex-1 overflow-auto p-3">
          <div className="space-y-2.5">
            {/* Rule 1 */}
            <div className="rounded-lg border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.12_0.018_264)] p-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">Block PII in prompts</span>
                </div>
                <div className="h-4 w-8 rounded-full bg-emerald-500/20 p-0.5">
                  <div className="h-3 w-3 rounded-full bg-emerald-400" />
                </div>
              </div>
              <p className="mt-1 text-[10px] text-[oklch(0.72_0.012_264)]/50">Detect and redact personally identifiable information in all agent prompts.</p>
            </div>

            {/* Rule 2 */}
            <div className="rounded-lg border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.12_0.018_264)] p-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
                  <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">Rate limit LLM calls</span>
                </div>
                <div className="h-4 w-8 rounded-full bg-emerald-500/20 p-0.5">
                  <div className="h-3 w-3 rounded-full bg-emerald-400" />
                </div>
              </div>
              <p className="mt-1 text-[10px] text-[oklch(0.72_0.012_264)]/50">Maximum 100 LLM calls per minute per agent.</p>
            </div>

            {/* Rule 3 */}
            <div className="rounded-lg border border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.12_0.018_264)] p-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <XCircle className="h-3.5 w-3.5 text-red-400" />
                  <span className="text-[11px] font-medium text-[oklch(0.958_0.004_264)]">Block dangerous tools</span>
                </div>
                <div className="h-4 w-8 rounded-full bg-[oklch(0.72_0.012_264)]/10 p-0.5">
                  <div className="h-3 w-3 rounded-full bg-[oklch(0.72_0.012_264)]/40 ml-4" />
                </div>
              </div>
              <p className="mt-1 text-[10px] text-[oklch(0.72_0.012_264)]/50">Prevent execution of rm -rf, DROP TABLE, and similar destructive commands.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Execution Observatory Panel (ExecutionObservatory replica) ───

function FaithfulExecutionObservatoryPanel() {
  const traces = [
    { id: "exec-001", workflow: "data-pipeline", status: "completed", duration: "12.4s", steps: 6, tokens: "4.2k", time: "2m ago" },
    { id: "exec-002", workflow: "security-scan", status: "failed", duration: "3.1s", steps: 2, tokens: "1.8k", time: "5m ago" },
    { id: "exec-003", workflow: "deploy-prod", status: "completed", duration: "45.2s", steps: 12, tokens: "12.1k", time: "12m ago" },
    { id: "exec-004", workflow: "backup-db", status: "running", duration: "8.7s", steps: 4, tokens: "3.5k", time: "1m ago" },
  ];

  const events = [
    { type: "EXECUTION_STARTED", time: "0.0s", msg: "Workflow data-pipeline started", color: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
    { type: "STEP_STARTED", time: "0.1s", msg: "Step: Fetch Source Data", color: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
    { type: "LLM_CALL_STARTED", time: "0.2s", msg: "LLM: gpt-4o → generate query", color: "border-violet-500/30 bg-violet-500/10 text-violet-300" },
    { type: "LLM_CALL_COMPLETED", time: "1.1s", msg: "LLM completed · 342 tokens", color: "border-violet-500/30 bg-violet-500/10 text-violet-300" },
    { type: "STEP_COMPLETED", time: "1.2s", msg: "Step completed · 1,247 records", color: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
    { type: "TOOL_CALL_STARTED", time: "1.3s", msg: "Tool: filesystem → write output", color: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300" },
    { type: "PROGRESS", time: "2.0s", msg: "Processing batch 2/5...", color: "border-primary/30 bg-primary/10 text-primary" },
    { type: "TODO_CREATED", time: "2.5s", msg: "TODO: Validate schema before load", color: "border-primary/30 bg-primary/10 text-primary" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[oklch(0.72_0.012_264)]/10 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)]">
            <Telescope className="h-4 w-4 text-[oklch(0.72_0.012_264)]" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[oklch(0.958_0.004_264)]">Observatory</h3>
            <p className="text-[10px] text-[oklch(0.72_0.012_264)]/60">Execution traces & LLM inspection</p>
          </div>
        </div>
        <div className="flex gap-2">
          <div className="rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]">Export JSON</div>
          <div className="rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]">Export HTML</div>
        </div>
      </div>

      {/* Execution List */}
      <div className="border-b border-[oklch(0.72_0.012_264)]/10 bg-[oklch(0.10_0.015_264)] px-3 py-2">
        <div className="mb-2 flex items-center gap-2">
          <div className="flex-1 rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]/50">
            🔍 Filter executions...
          </div>
          <div className="rounded-md border border-[oklch(0.72_0.012_264)]/15 bg-[oklch(0.18_0.025_264)] px-2 py-1 text-[10px] text-[oklch(0.72_0.012_264)]">
            Status ▾
          </div>
        </div>
        <div className="space-y-1">
          {traces.map((trace) => (
            <div key={trace.id} className="flex items-center justify-between rounded-md bg-[oklch(0.18_0.025_264)]/50 px-2.5 py-1.5 hover:bg-[oklch(0.18_0.025_264)]">
              <div className="flex items-center gap-2">
                <div
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    trace.status === "completed" && "bg-emerald-400",
                    trace.status === "failed" && "bg-red-400",
                    trace.status === "running" && "bg-sky-400 animate-pulse"
                  )}
                />
                <span className="text-[11px] font-mono text-[oklch(0.958_0.004_264)]">{trace.id}</span>
                <span className="text-[10px] text-[oklch(0.72_0.012_264)]/50">{trace.workflow}</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[10px] font-mono text-[oklch(0.72_0.012_264)]/50">{trace.duration}</span>
                <span className="text-[10px] text-[oklch(0.72_0.012_264)]/50">{trace.steps} steps</span>
                <span className="text-[10px] text-violet-400/70">{trace.tokens}</span>
                <span className="text-[10px] text-[oklch(0.72_0.012_264)]/40">{trace.time}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Trace Events */}
      <div className="flex-1 overflow-auto p-3">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-[10px] font-medium text-[oklch(0.958_0.004_264)]">Trace: exec-001</span>
          <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[9px] text-emerald-400">completed</span>
        </div>
        <div className="space-y-1">
          {events.map((event, i) => (
            <div key={i} className={cn("flex items-center gap-2 rounded-md border-l-2 px-2.5 py-1.5", event.color)}>
              <span className="w-10 text-right text-[9px] font-mono text-[oklch(0.72_0.012_264)]/50">{event.time}</span>
              <span className="text-[10px] font-medium">{event.type}</span>
              <span className="text-[10px] text-[oklch(0.72_0.012_264)]/70">{event.msg}</span>
            </div>
          ))}
        </div>

        {/* LLM Call Detail */}
        <div className="mt-3 rounded-lg border border-violet-500/20 bg-violet-500/5 p-2.5">
          <div className="flex items-center gap-2">
            <BrainCircuit className="h-3.5 w-3.5 text-violet-400" />
            <span className="text-[11px] font-medium text-violet-400">LLM Call Inspection</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <div className="rounded-md bg-[oklch(0.18_0.025_264)] p-1.5">
              <span className="text-[9px] text-[oklch(0.72_0.012_264)]/50">Model</span>
              <p className="text-[10px] font-medium text-[oklch(0.958_0.004_264)]">gpt-4o</p>
            </div>
            <div className="rounded-md bg-[oklch(0.18_0.025_264)] p-1.5">
              <span className="text-[9px] text-[oklch(0.72_0.012_264)]/50">Tokens</span>
              <p className="text-[10px] font-medium text-[oklch(0.958_0.004_264)]">342</p>
            </div>
            <div className="rounded-md bg-[oklch(0.18_0.025_264)] p-1.5">
              <span className="text-[9px] text-[oklch(0.72_0.012_264)]/50">Latency</span>
              <p className="text-[10px] font-medium text-[oklch(0.958_0.004_264)]">0.9s</p>
            </div>
          </div>
        </div>
      </div>
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
      title: "Cluster-Native Agent Workflows",
      description:
        "Orchestrate multi-agent pipelines for infrastructure tasks: pod diagnostics, log analysis, health checks, and deployment verification — with human approval gates.",
      tags: ["Workflows", "HITL", "Multi-Agent"],
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
      title: "Execution Traces & Run Intelligence",
      description:
        "Built-in trace store captures every LLM call, tool invocation, and step execution. Signal watch detects anomalies in failure rates, token spend, and run duration.",
      tags: ["Traces", "Signal Watch", "Cost Tracking"],
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section id="features" className="px-4 py-24 sm:px-6 md:py-32" ref={ref}>
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
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
                className="group rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-6 backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)] sm:p-7"
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

// ─── Trust Bar ───

function TrustBar() {
  const items = [
    { icon: Server, label: "Runs on your existing Kubernetes cluster" },
    { icon: Lock, label: "RBAC + NetworkPolicy built in" },
    { icon: Database, label: "Persistent agent state via PVCs" },
    { icon: Eye, label: "Human-in-the-loop approval gates" },
    { icon: Code, label: "Apache 2.0 — free forever" },
    { icon: Terminal, label: "Helm install in under 5 minutes" },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true });

  return (
    <section ref={ref} className="border-y border-[oklch(0.25_0.01_264)] bg-[oklch(0.17_0.008_264/0.5)] py-10">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-10 gap-y-3 px-4">
        {items.map((item, i) => {
          const Icon = item.icon;
          return (
            <motion.div
              key={item.label}
              initial={{ opacity: 0, y: 8 }}
              animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ delay: i * 0.08, duration: 0.4 }}
              className="flex items-center gap-2.5 text-xs font-medium text-[oklch(0.72_0.01_264)]"
            >
              <Icon className="h-4 w-4 text-[oklch(0.708_0.101_188)]" />
              {item.label}
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}

// ─── Use Cases Grid ───

function UseCasesSection() {
  const useCases = [
    {
      icon: AlertTriangle,
      title: "Automated Incident Remediation",
      tags: ["SRE", "On-Call"],
      description:
        "Agents detect pod crashes, analyze logs, check dependant services, and execute runbook steps — with mandatory human approval for destructive actions. Turn your runbooks into CRD workflows.",
    },
    {
      icon: GitBranch,
      title: "CI/CD Pipeline Intelligence",
      tags: ["DevOps", "GitOps"],
      description:
        "Agents monitor deployment rollouts, verify health checks across namespaces, and automate canary analysis. Triggered by webhooks from your existing CI/CD tools.",
    },
    {
      icon: BrainCircuit,
      title: "Context Engineering for LLMs",
      tags: ["RAG", "Memory"],
      description:
        "Inject Kubernetes context — pod specs, events, logs, metrics — directly into agent prompts. Agents reason about your cluster with real-time, accurate context instead of hallucinating.",
    },
    {
      icon: Wrench,
      title: "Harness Engineering via MCP",
      tags: ["Tools", "Sidecars"],
      description:
        "11 pre-built MCP sidecars give agents safe, governed access to kubectl, GitHub, web search, databases, messaging, and file systems. Hot-attach new tools without rebuilding images.",
    },
    {
      icon: Shield,
      title: "Security Policy Automation",
      tags: ["Guardrails", "Compliance"],
      description:
        "Define AgentPolicy CRDs that enforce model allowlists, PII masking, token budgets, and output blocklists before any prompt reaches an LLM. Audit every decision.",
    },
    {
      icon: Layers,
      title: "Multi-Cluster Fleet Management",
      tags: ["Fleet", "Observability"],
      description:
        "Deploy KubeSynapse on each cluster in your fleet. Collect traces, correlate incidents, and run cross-cluster diagnostics — all from a single pane of glass.",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section ref={ref} id="use-cases" className="px-4 py-24 sm:px-6 md:py-32">
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-14 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-[oklch(0.708_0.101_188)]">
            Use Cases
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            What You Can <span className="text-[oklch(0.708_0.101_188)]">Build</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            KubeSynapse plugs into your existing Kubernetes deployments. No new infrastructure required.
          </motion.p>
        </motion.div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {useCases.map((uc, i) => {
            const Icon = uc.icon;
            return (
              <motion.div
                key={uc.title}
                variants={itemVariants}
                initial="hidden"
                animate={inView ? "visible" : "hidden"}
                transition={{ delay: i * 0.07 }}
                className="group rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.4)] p-6 backdrop-blur-sm transition-all hover:-translate-y-0.5 hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)] sm:p-7"
              >
                <div className="mb-4 flex items-center justify-between">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[oklch(0.708_0.101_188/0.1)] text-[oklch(0.708_0.101_188)] ring-1 ring-[oklch(0.708_0.101_188/0.2)] transition-colors group-hover:bg-[oklch(0.708_0.101_188/0.15)]">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="flex gap-1.5">
                    {uc.tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-[oklch(0.252_0.010_264)] px-2 py-0.5 text-[10px] font-medium text-[oklch(0.82_0.01_264)]">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <h3 className="text-base font-semibold text-[oklch(0.958_0.004_264)]">{uc.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-[oklch(0.82_0.01_264)]">{uc.description}</p>
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
    <section className="px-4 py-24 sm:px-6 md:py-32" ref={ref}>
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
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
                      <div className="h-px w-6 border-t-2 border-dashed border-[oklch(0.708_0.101_188/0.4)]" />
                      <motion.div
                        className="h-2.5 w-2.5 rounded-full bg-[oklch(0.708_0.101_188)]"
                        animate={{ scale: [1, 1.4, 1], opacity: [0.6, 1, 0.6] }}
                        transition={{ duration: 2, repeat: Infinity, delay: i * 0.5 }}
                      />
                    </motion.div>
                  </div>
                )}

                <div className="relative overflow-hidden rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-6 backdrop-blur-sm transition-all duration-300 hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)] hover:-translate-y-1 sm:p-8">
                  {/* Step number badge */}
                  <div className="relative mb-6 flex items-center justify-between">
                    <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[oklch(0.708_0.101_188/0.15)] text-[oklch(0.708_0.101_188)] shadow-lg shadow-[oklch(0.708_0.101_188/0.1)] sm:h-14 sm:w-14">
                      <Icon className="h-6 w-6 sm:h-7 sm:w-7" />
                    </div>
                    <span className="text-4xl font-black text-[oklch(0.708_0.101_188/0.1)] sm:text-5xl">
                      {step.num}
                    </span>
                  </div>

                  <div className="relative">
                    <h3 className="text-lg font-bold text-[oklch(0.958_0.004_264)] sm:text-xl">{step.title}</h3>
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
  const [visibleLines, setVisibleLines] = useState(0);
  const prevTabRef = useRef<TabKey>(activeTab);

  useEffect(() => {
    if (prevTabRef.current !== activeTab) {
      setVisibleLines(0);
      prevTabRef.current = activeTab;
    }
    if (visibleLines < tabLines[activeTab].length) {
      const timer = setTimeout(() => setVisibleLines((v) => v + 1), 50);
      return () => clearTimeout(timer);
    }
  }, [activeTab, visibleLines]);

  const tabs: { key: TabKey; label: string; icon: typeof Terminal }[] = [
    { key: "install", label: "Install", icon: Terminal },
    { key: "agent", label: "AIAgent", icon: Bot },
    { key: "workflow", label: "Workflow", icon: Workflow },
    { key: "operate", label: "Operate", icon: Play },
  ];

  const tabLines: Record<TabKey, TerminalLine[]> = {
    install: [
      { text: "# Install KubeSynapse on your Kubernetes cluster", color: "comment", type: "input" },
      { text: "helm repo add kubesynapse https://kubesynapse.ai/charts", color: "command", prefix: "$", type: "input" },
      { text: "helm install kubesynapse kubesynapse/kubesynapse \\", color: "command", prefix: "$", type: "input" },
      { text: "  --namespace kubesynapse --create-namespace \\", color: "command", type: "input" },
      { text: "  --set platformSecrets.native.openaiApiKey=\"sk-...\"", color: "command", type: "input" },
      { text: "", type: "blank" },
      { text: "NAME: kubesynapse", color: "output", type: "output" },
      { text: "NAMESPACE: kubesynapse", color: "output", type: "output" },
      { text: "STATUS: deployed", color: "string", type: "output" },
      { text: "REVISION: 1", color: "output", type: "output" },
      { text: "", type: "blank" },
      { text: "kubectl port-forward -n kubesynapse \\", color: "command", prefix: "$", type: "input" },
      { text: "  svc/kubesynapse-api-gateway 8080:8080", color: "command", type: "input" },
      { text: "Forwarding from 127.0.0.1:8080 -> 8080", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "  Open http://localhost:8080 in your browser", color: "comment", type: "input" },
    ],
    agent: [
      { text: "apiVersion: kubesynapse.ai/v1alpha1", color: "yamlKey", type: "input" },
      { text: "kind: AIAgent", color: "yamlKey", type: "input" },
      { text: "metadata:", color: "yamlKey", type: "input" },
      { text: "  name: incident-triage", color: "yamlVal", type: "input" },
      { text: "  namespace: production", color: "yamlVal", type: "input" },
      { text: "spec:", color: "yamlKey", type: "input" },
      { text: "  model: claude-sonnet-4-20250514", color: "yamlVal", type: "input" },
      { text: "  runtime:", color: "yamlKey", type: "input" },
      { text: "    kind: opencode", color: "yamlVal", type: "input" },
      { text: "  storage:", color: "yamlKey", type: "input" },
      { text: "    size: 2Gi", color: "yamlVal", type: "input" },
      { text: "  systemPrompt: |", color: "yamlKey", type: "input" },
      { text: "    You are an SRE agent. When an alert fires,", color: "string", type: "input" },
      { text: "    correlate logs, check pod status, and suggest", color: "string", type: "input" },
      { text: "    remediation. Ask before destructive commands.", color: "string", type: "input" },
      { text: "  mcpServers:", color: "yamlKey", type: "input" },
      { text: "    - kubernetes", color: "yamlVal", type: "input" },
      { text: "    - web-search", color: "yamlVal", type: "input" },
      { text: "    - messaging", color: "yamlVal", type: "input" },
      { text: "  policyRef: sre-governed", color: "yamlVal", type: "input" },
    ],
    workflow: [
      { text: "apiVersion: kubesynapse.ai/v1alpha1", color: "yamlKey", type: "input" },
      { text: "kind: AgentWorkflow", color: "yamlKey", type: "input" },
      { text: "metadata:", color: "yamlKey", type: "input" },
      { text: "  name: incident-response", color: "yamlVal", type: "input" },
      { text: "spec:", color: "yamlKey", type: "input" },
      { text: "  description: Automated incident response pipeline", color: "yamlVal", type: "input" },
      { text: "  input: Alert payload from Prometheus webhook", color: "yamlVal", type: "input" },
      { text: "  autoRetry:", color: "yamlKey", type: "input" },
      { text: "    enabled: true", color: "flag", type: "input" },
      { text: "    maxAttempts: 1", color: "yamlVal", type: "input" },
      { text: "  steps:", color: "yamlKey", type: "input" },
      { text: "    - name: triage", color: "yamlVal", type: "input" },
      { text: "      agentRef: incident-triage", color: "yamlVal", type: "input" },
      { text: "      prompt: |", color: "yamlKey", type: "input" },
      { text: "        Analyze this alert and correlate with recent", color: "string", type: "input" },
      { text: "        pod events. Identify root cause.", color: "string", type: "input" },
      { text: "      execution:", color: "yamlKey", type: "input" },
      { text: "        timeoutSeconds: 180", color: "yamlVal", type: "input" },
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
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
          <div className="flex flex-wrap items-center border-b border-[oklch(0.25_0.01_264)] bg-[oklch(0.149_0.008_264)]">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  onClick={() => { setActiveTab(tab.key); setVisibleLines(0); }}
                    className={`flex shrink-0 items-center gap-2 px-4 py-3 text-sm font-medium transition-all sm:px-5 ${
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
            <button
              onClick={() => {
                const text = tabLines[activeTab].map((l) => `${l.prefix ? l.prefix + " " : ""}${l.text}`).join("\n");
                navigator.clipboard.writeText(text).catch(() => {});
              }}
              className="ml-auto px-4 py-3 text-[oklch(0.4_0.01_264)] transition-colors hover:text-[oklch(0.82_0.01_264)]"
              title="Copy to clipboard"
            >
              <Copy className="h-4 w-4" />
            </button>
          </div>

          {/* Terminal Content */}
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              className="overflow-x-auto p-4 font-mono text-[12px] leading-6 sm:p-5 sm:text-[13px]"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
            >
              {tabLines[activeTab].slice(0, visibleLines).map((line, i) => (
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
                    <span className={`whitespace-pre-wrap break-words sm:whitespace-pre ${colorMap[line.color || "output"] || "text-[oklch(0.82_0.01_264)]"}`}>
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

  const planes = [
    {
      label: "Control Plane",
      color: "border-[oklch(0.708_0.101_188)/40] bg-[oklch(0.708_0.101_188)/5]",
      iconColor: "text-[oklch(0.708_0.101_188)]",
      items: [
        { name: "Kubernetes API Server", sub: "CRD registration & admission" },
        { name: "Operator (Kopf)", sub: "Reconcile AIAgent, AgentWorkflow…" },
        { name: "API Gateway (FastAPI)", sub: "100+ REST & SSE endpoints" },
        { name: "12 CRD Types", sub: "v1alpha1 custom resources" },
      ],
    },
    {
      label: "Execution Plane",
      color: "border-violet-500/40 bg-violet-500/5",
      iconColor: "text-violet-400",
      items: [
        { name: "OpenCode Runtime", sub: "Persistent StatefulSet" },
        { name: "Pi Runtime", sub: "Streaming bridge" },
        { name: "MCP Sidecars (11)", sub: "Tools, search, browser…" },
        { name: "Worker Jobs", sub: "Workflow step execution" },
      ],
    },
    {
      label: "Shared Services",
      color: "border-amber-500/40 bg-amber-500/5",
      iconColor: "text-amber-400",
      items: [
        { name: "LiteLLM", sub: "Model routing & key rotation" },
        { name: "PostgreSQL", sub: "Trace store & auth" },
        { name: "Redis", sub: "SSE broker & caching" },
        { name: "NATS + Qdrant", sub: "Event bus & vector DB" },
      ],
    },
  ];

  return (
    <section id="architecture" className="border-y border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264/0.5)] px-4 py-24 sm:px-6 md:py-32" ref={ref}>
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
            Built for <span className="text-[oklch(0.708_0.101_188)]">Production</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-[oklch(0.82_0.01_264)]">
            Separation of control plane and execution plane. Every agent is an isolated StatefulSet
            with its own persistent volume, network policy, and governance envelope.
          </motion.p>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-3">
          {planes.map((plane, i) => (
            <motion.div
              key={plane.label}
              variants={itemVariants}
              initial="hidden"
              animate={inView ? "visible" : "hidden"}
              transition={{ delay: i * 0.1 }}
              className={`rounded-2xl border ${plane.color} p-6 backdrop-blur-sm`}
            >
              <h3 className="mb-4 text-sm font-bold uppercase tracking-wider text-[oklch(0.72_0.01_264)]">{plane.label}</h3>
              <div className="space-y-3">
                {plane.items.map((item) => (
                  <motion.div
                    key={item.name}
                    className="group flex items-start gap-3 rounded-lg border border-[oklch(0.3_0.01_264/0.5)] bg-[oklch(0.164_0.007_264/0.8)] px-4 py-3 text-sm transition-all hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-sm"
                    whileHover={{ x: 4 }}
                    transition={{ duration: 0.15 }}
                  >
                    <CheckCircle2 className={`mt-0.5 h-4 w-4 flex-shrink-0 ${plane.iconColor}`} />
                    <div>
                      <span className="font-medium text-[oklch(0.958_0.004_264)]">{item.name}</span>
                      <p className="text-[11px] text-[oklch(0.62_0.01_264)]">{item.sub}</p>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        {/* Flow arrows between planes */}
        <div className="mt-4 flex items-center justify-center gap-4 text-[oklch(0.5_0.01_264)]">
          <div className="flex items-center gap-2 text-xs font-medium">
            <GitCommitHorizontal className="h-4 w-4 text-[oklch(0.708_0.101_188)]" />
            <span>CRDs → Reconcile → Execute → Observe</span>
            <GitCommitHorizontal className="h-4 w-4 text-[oklch(0.708_0.101_188)]" />
          </div>
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
    <section id="docs" className="px-4 py-24 sm:px-6 md:py-32" ref={ref}>
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
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
    <section className="border-y border-[oklch(0.3_0.01_264)] bg-[oklch(0.149_0.008_264/0.5)] px-4 py-24 sm:px-6 md:py-32" ref={ref}>
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
          <motion.h2 variants={itemVariants} className="mt-3 text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
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
                className="group flex flex-col gap-4 rounded-2xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-6 backdrop-blur-sm transition-all hover:border-[oklch(0.708_0.101_188/0.3)] hover:shadow-lg hover:shadow-[oklch(0.708_0.101_188/0.05)] sm:flex-row sm:gap-5 sm:p-7"
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

function KubeMatrix() {
  const faces = [
    { axis: "rotateY(0deg)", tz: 60 },
    { axis: "rotateY(180deg)", tz: 60 },
    { axis: "rotateY(90deg)", tz: 60 },
    { axis: "rotateY(-90deg)", tz: 60 },
    { axis: "rotateX(90deg)", tz: 60 },
    { axis: "rotateX(-90deg)", tz: 60 },
  ];

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden" aria-hidden>
      <div className="absolute inset-0 bg-gradient-to-b from-[oklch(0.145_0.022_264)] via-transparent to-[oklch(0.145_0.022_264)]" style={{ zIndex: 1 }} />
      <div className="absolute" style={{ perspective: 800, perspectiveOrigin: "50% 50%" }}>
        <div style={{ transformStyle: "preserve-3d", animation: "kube-spin 25s linear infinite" }}>
          <div style={{ transformStyle: "preserve-3d" }}>
            {faces.map((f, i) => (
              <div
                key={i}
                className="border border-[oklch(0.708_0.101_188/0.12)]"
                style={{
                  position: "absolute",
                  width: 120,
                  height: 120,
                  transform: `${f.axis} translateZ(${f.tz}px)`,
                  backfaceVisibility: "hidden",
                }}
              />
            ))}
          </div>
        </div>
      </div>
      <div className="absolute" style={{ perspective: 800, perspectiveOrigin: "50% 50%" }}>
        <div style={{ transformStyle: "preserve-3d", animation: "kube-spin-reverse 35s linear infinite" }}>
          <div style={{ transformStyle: "preserve-3d" }}>
            {faces.map((f, i) => (
              <div
                key={i}
                className="border border-[oklch(0.742_0.132_233/0.08)]"
                style={{
                  position: "absolute",
                  width: 180,
                  height: 180,
                  transform: `${f.axis} translateZ(${90}px)`,
                  backfaceVisibility: "hidden",
                }}
              />
            ))}
          </div>
        </div>
      </div>
      <div className="absolute" style={{ perspective: 800, perspectiveOrigin: "50% 50%" }}>
        <div style={{ transformStyle: "preserve-3d", animation: "kube-spin 45s linear infinite" }}>
          <div style={{ transformStyle: "preserve-3d" }}>
            {faces.map((f, i) => (
              <div
                key={i}
                className="border border-[oklch(0.684_0.138_308/0.06)]"
                style={{
                  position: "absolute",
                  width: 260,
                  height: 260,
                  transform: `${f.axis} translateZ(${130}px)`,
                  backfaceVisibility: "hidden",
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function BottomCTA() {
  return (
    <section className="relative px-4 py-24 sm:px-6 md:py-32 overflow-hidden">
      <KubeMatrix />
      <div className="relative mx-auto max-w-4xl text-center" style={{ zIndex: 2 }}>
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="relative overflow-hidden rounded-3xl border border-[oklch(0.3_0.01_264)] bg-[oklch(0.206_0.009_264/0.5)] p-6 shadow-2xl shadow-[oklch(0.708_0.101_188/0.05)] backdrop-blur-sm sm:p-8 md:p-16"
        >
          {/* Animated gradient border effect */}
          <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-3xl">
            <div className="absolute -inset-[2px] animate-[rotate-gradient_8s_linear_infinite] rounded-3xl bg-[conic-gradient(from_0deg,oklch(0.708_0.101_188),oklch(0.742_0.132_233),oklch(0.684_0.138_308),oklch(0.708_0.101_188))]" style={{ mask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)", maskComposite: "exclude", WebkitMaskComposite: "xor", padding: "2px" }} />
          </div>

          <div className="relative">
            <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-[oklch(0.708_0.101_188)] text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)]">
              <KubeSynapseLogo className="h-7 w-7" animated />
            </div>
            <h2 className="text-2xl font-bold tracking-tight text-[oklch(0.958_0.004_264)] sm:text-4xl md:text-5xl">
              Ready to <span className="text-[oklch(0.708_0.101_188)]">Automate</span>?
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-base text-[oklch(0.82_0.01_264)]">
              Deploy KubeSynapse on your cluster and let AI agents handle incident response,
              infrastructure automation, and operational intelligence.
            </p>

            {/* Inline install command */}
            <div className="mx-auto mt-8 max-w-lg overflow-hidden rounded-lg border border-[oklch(0.3_0.01_264)] bg-[oklch(0.12_0.006_264)]">
              <div className="flex flex-col gap-2 px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0 overflow-x-auto">
                  <code className="block whitespace-nowrap text-[11px] text-[oklch(0.75_0.12_188)] sm:text-xs">
                    <span className="text-[oklch(0.76_0.16_154/0.8)]">$ </span>
                    helm install kubesynapse oci://docker.io/kubesynapse/charts/kubesynapse
                  </code>
                </div>
                <button
                  onClick={() => navigator.clipboard.writeText("helm install kubesynapse oci://docker.io/kubesynapse/charts/kubesynapse --namespace kubesynapse --create-namespace").catch(() => {})}
                  className="self-end text-[oklch(0.4_0.01_264)] transition-colors hover:text-[oklch(0.82_0.01_264)] sm:ml-2 sm:self-auto"
                  title="Copy"
                >
                  <Copy className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <div className="mt-8 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
              <a
                href="#install"
                className="group relative flex w-full items-center justify-center gap-2 rounded-xl bg-[oklch(0.708_0.101_188)] px-8 py-3.5 text-sm font-semibold text-[oklch(0.158_0.007_264)] shadow-lg shadow-[oklch(0.708_0.101_188/0.3)] transition-all hover:shadow-xl active:scale-[0.98] sm:w-auto"
              >
                <span className="absolute inset-0 -z-10 rounded-xl bg-[oklch(0.708_0.101_188)] opacity-0 blur-xl motion-safe:group-hover:opacity-50 transition-opacity" />
                Deploy Now
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </a>
              <a
                href="https://github.com/ykbytes/kubesynapse.ai"
                target="_blank"
                rel="noopener noreferrer"
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-[oklch(0.4_0.015_264)] bg-[oklch(0.206_0.009_264/0.8)] px-8 py-3.5 text-sm font-semibold text-[oklch(0.85_0.01_264)] shadow-sm transition-all hover:border-[oklch(0.708_0.101_188/0.4)] hover:text-[oklch(0.958_0.004_264)] sm:w-auto"
              >
                <GitBranch className="h-4 w-4 text-[oklch(0.708_0.101_188)]" />
                View on GitHub
              </a>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

// ─── Footer ───

function Footer() {
  return (
    <footer className="border-t border-[oklch(0.3_0.01_264)] px-4 py-14 sm:px-6">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="sm:col-span-2 lg:col-span-1">
            <div className="flex items-center gap-2">
              <KubeSynapseLogo className="h-5 w-5 text-[oklch(0.708_0.101_188)]" />
              <span className="text-sm font-bold text-[oklch(0.958_0.004_264)]">{BRAND.name}</span>
            </div>
            <p className="mt-3 max-w-sm text-xs leading-relaxed text-[oklch(0.68_0.01_264)]">
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
            &copy; {new Date().getFullYear()} {BRAND.name}. Open source under Apache 2.0. Built by{" "}
            <a href="https://www.linkedin.com/in/yakdhane/" target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-[oklch(0.708_0.101_188)]">
              Ahmed YAKDHANE
            </a>.
          </p>
          <div className="flex items-center gap-4 text-xs text-[oklch(0.58_0.01_264)]">
            <a href="/sitemap.xml" className="hover:text-[oklch(0.708_0.101_188)]">Sitemap</a>
            <span>Self-hosted &middot; No telemetry &middot; Your cluster, your data</span>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ─── Main LandingPage ───

export function LandingPage({ onLogin, showLogin }: LandingPageProps) {
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
        onLogin={onLogin}
        showLogin={showLogin}
      />
      {view === "docs" ? (
        <main id="main-content" className="h-[calc(100dvh-4rem)]">
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
            <SectionDivider />
            <ProblemSection />
            <SectionDivider />
            <UIPreviewSection />
            <SectionDivider />
            <FeaturesSection />
            <TrustBar />
            <SectionDivider />
            <UseCasesSection />
            <SectionDivider />
            <HowItWorks />
            <SectionDivider />
            <InstallSection />
            <SectionDivider />
            <ArchitectureSection />
            <DocsSection />
            <SectionDivider />
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
