import { useEffect, useRef, useState } from "react";
import { motion, useInView, AnimatePresence } from "framer-motion";
import {
  ArrowRight, Bot, BrainCircuit, CheckCircle2, Database, GitBranch,
  Globe, LayoutPanelTop, Lock, MessageSquare, Network, Play, RefreshCw,
  Server, Shield, Timer, Workflow, Zap, Terminal, Copy,
  Boxes, Code, Puzzle, Moon, Sun,
} from "lucide-react";
import { BRAND } from "@/lib/brand";

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
    transition: { duration: 0.55, ease: "easeOut" as const },
  },
};

const fadeIn = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.5 } },
};

// ─── Terminal Component ───

interface TerminalLine {
  text: string;
  color?: string;
  prefix?: string;
  type?: "input" | "output" | "blank";
}



// ─── Navbar ───

function Navbar({ onLogin, darkMode, onToggleDark }: { onLogin: () => void; darkMode: boolean; onToggleDark: () => void }) {
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
          ? darkMode
            ? "border-slate-700/80 bg-slate-900/90 shadow-sm backdrop-blur-md"
            : "border-slate-200/80 bg-white/90 shadow-sm backdrop-blur-md"
          : darkMode
            ? "border-transparent bg-slate-900/60 backdrop-blur-sm"
            : "border-transparent bg-white/60 backdrop-blur-sm"
      }`}
    >
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm">
            <LayoutPanelTop className="h-5 w-5" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-bold tracking-tight text-slate-900">
              {BRAND.name}
            </span>
            <span className="hidden text-xs font-medium text-slate-500 sm:inline">
              {BRAND.tagline}
            </span>
          </div>
        </div>

        <div className="hidden items-center gap-8 text-sm font-medium text-slate-600 md:flex">
          <a href="#features" className="transition-colors hover:text-slate-900">Features</a>
          <a href="#architecture" className="transition-colors hover:text-slate-900">Architecture</a>
          <a href="#workflows" className="transition-colors hover:text-slate-900">Workflows</a>
          <a href="#install" className="transition-colors hover:text-slate-900">Install</a>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onToggleDark}
            className={`rounded-lg p-2 text-sm font-medium transition-colors ${darkMode ? "text-slate-300 hover:text-white" : "text-slate-600 hover:text-slate-900"}`}
            aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
            title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
          >
            {darkMode ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
          <button
            onClick={onLogin}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${darkMode ? "text-slate-300 hover:text-white" : "text-slate-600 hover:text-slate-900"}`}
          >
            Sign In
          </button>
          <button
            onClick={onLogin}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-all hover:bg-blue-700 hover:shadow-md active:scale-[0.98]"
          >
            Get Started
          </button>
        </div>
      </div>
    </nav>
  );
}

// ─── Animated Cluster Visualization ───

function AnimatedCluster() {
  return (
    <div className="relative mx-auto mb-8 h-48 max-w-xl overflow-hidden md:h-56">
      {/* K8s control plane node */}
      <motion.div
        className="absolute left-1/2 top-2 flex -translate-x-1/2 items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 shadow-sm"
        animate={{ y: [0, -4, 0] }}
        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
      >
        <Server className="h-3 w-3 text-blue-600" />
        <span className="text-[10px] font-semibold text-blue-700">kube-apiserver</span>
      </motion.div>

      {/* Floating agent pods */}
      {[
        { x: "15%", y: "40%", label: "agent-0", color: "emerald", delay: 0 },
        { x: "35%", y: "30%", label: "agent-1", color: "blue", delay: 1 },
        { x: "65%", y: "25%", label: "agent-2", color: "purple", delay: 0.5 },
        { x: "80%", y: "45%", label: "agent-3", color: "cyan", delay: 1.5 },
        { x: "25%", y: "65%", label: "worker-0", color: "orange", delay: 2 },
        { x: "55%", y: "70%", label: "worker-1", color: "pink", delay: 0.8 },
        { x: "75%", y: "65%", label: "litellm", color: "indigo", delay: 1.2 },
      ].map((pod) => {
        const colorMap: Record<string, string> = {
          emerald: "border-emerald-300 bg-emerald-50 text-emerald-700",
          blue: "border-blue-300 bg-blue-50 text-blue-700",
          purple: "border-purple-300 bg-purple-50 text-purple-700",
          cyan: "border-cyan-300 bg-cyan-50 text-cyan-700",
          orange: "border-orange-300 bg-orange-50 text-orange-700",
          pink: "border-pink-300 bg-pink-50 text-pink-700",
          indigo: "border-indigo-300 bg-indigo-50 text-indigo-700",
        };
        return (
          <motion.div
            key={pod.label}
            className={`absolute rounded-full border px-2.5 py-1 text-[9px] font-semibold shadow-sm ${colorMap[pod.color]}`}
            style={{ left: pod.x, top: pod.y }}
            animate={{
              y: [0, -8, 0, 6, 0],
              x: [0, 3, -3, 2, 0],
              scale: [1, 1.03, 0.97, 1.02, 1],
            }}
            transition={{
              duration: 4 + pod.delay,
              repeat: Infinity,
              ease: "easeInOut",
              delay: pod.delay,
            }}
          >
            <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-current opacity-60" />
            {pod.label}
          </motion.div>
        );
      })}

      {/* Connection lines (subtle) */}
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 500 220" fill="none">
        {[
          { x1: 250, y1: 20, x2: 120, y2: 100 },
          { x1: 250, y1: 20, x2: 200, y2: 70 },
          { x1: 250, y1: 20, x2: 350, y2: 60 },
          { x1: 250, y1: 20, x2: 420, y2: 110 },
          { x1: 120, y1: 100, x2: 150, y2: 150 },
          { x1: 350, y1: 60, x2: 300, y2: 155 },
        ].map((line, i) => (
          <motion.line
            key={i}
            x1={line.x1}
            y1={line.y1}
            x2={line.x2}
            y2={line.y2}
            stroke="#cbd5e1"
            strokeWidth={0.5}
            strokeDasharray="4 3"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.15, 0.35, 0.15] }}
            transition={{ duration: 3, repeat: Infinity, delay: i * 0.4 }}
          />
        ))}
      </svg>
    </div>
  );
}

// ─── GitHub Stars Counter ───

function GitHubStars() {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    fetch("https://api.github.com/repos/ykbytes/kubemininions")
      .then((r) => r.json())
      .then((data) => {
        if (data.stargazers_count != null) setStars(data.stargazers_count);
      })
      .catch(() => {});
  }, []);

  if (stars == null) return null;

  const formatter = Intl.NumberFormat("en", { notation: "compact" });

  return (
    <motion.a
      href="https://github.com/ykbytes/kubemininions"
      target="_blank"
      rel="noopener noreferrer"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 1 }}
      className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 shadow-sm transition-all hover:bg-amber-100"
    >
      <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
      </svg>
      {formatter.format(stars)} GitHub stars
    </motion.a>
  );
}

// ─── Hero Section ───

function HeroSection({ onLogin }: { onLogin: () => void }) {
  return (
    <section className="relative overflow-hidden bg-white px-6 pb-20 pt-20 md:pb-28 md:pt-32">
      {/* Subtle grid background */}
      <div className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #0f172a 1px, transparent 1px), linear-gradient(to bottom, #0f172a 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      <div className="relative mx-auto max-w-5xl text-center">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-6 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-4 py-1.5 text-xs font-semibold text-slate-600 shadow-sm"
        >
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-emerald-500/20" />
          Kubernetes-Native AI Agent Orchestration
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl md:text-6xl lg:text-7xl"
        >
          Deploy AI Agents on{" "}
          <span className="bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">
            Kubernetes
          </span>
          <br />
          <span className="text-slate-700">That Actually Ship</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mx-auto mt-6 max-w-2xl text-base text-slate-600 sm:text-lg md:text-xl leading-relaxed"
        >
          The production-grade platform for running autonomous AI agents as StatefulSets.
          Declarative CRDs, policy-driven governance, A2A-ready workflows — installed with Helm.
        </motion.p>

        <AnimatedCluster />

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="mt-6 flex flex-col items-center gap-4 sm:flex-row sm:justify-center"
        >
          <button
            onClick={onLogin}
            className="group flex items-center gap-2 rounded-xl bg-blue-600 px-7 py-3.5 text-sm font-semibold text-white shadow-lg shadow-blue-600/20 transition-all hover:bg-blue-700 hover:shadow-xl active:scale-[0.98]"
          >
            Initialize Workspace
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </button>
          <a
            href="#install"
            className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-7 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-all hover:bg-slate-50 hover:border-slate-300"
          >
            <Terminal className="h-4 w-4 text-blue-600" />
            Deploy with Helm
          </a>
        </motion.div>

        <GitHubStars />
      </div>
    </section>
  );
}

// ─── Ecosystem Cloud ───

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
    <section className="border-y border-slate-100 bg-slate-50/50 px-6 py-12">
      <div className="mx-auto max-w-6xl">
        <p className="mb-8 text-center text-xs font-semibold uppercase tracking-widest text-slate-400">
          Built for the Kubernetes Ecosystem
        </p>
        <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-6">
          {tools.map((tool) => {
            const Icon = tool.icon;
            return (
              <div key={tool.name} className="flex items-center gap-2 text-slate-400">
                <Icon className="h-5 w-5" />
                <span className="text-sm font-medium">{tool.name}</span>
              </div>
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
      icon: Server,
      title: "Stateful Agents Are Hard",
      description:
        "AI agents need memory, sessions, and checkpoints. Running them as ephemeral pods loses state on every restart.",
    },
    {
      icon: Lock,
      title: "No Built-In Governance",
      description:
        "Tool usage, token budgets, and output guardrails are afterthoughts. You need policy-as-code at the cluster level.",
    },
    {
      icon: GitBranch,
      title: "Orchestration Is Manual",
      description:
        "Multi-agent workflows require complex DAG logic, approval gates, and failure recovery — none of which come out-of-the-box.",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section className="bg-white px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            The Challenge
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Managing AI Agents on K8s Is <span className="text-slate-500">Hard</span>
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
                className="group rounded-2xl border border-slate-200 bg-white p-8 shadow-sm transition-all hover:border-blue-200 hover:shadow-md"
              >
                <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100 transition-colors group-hover:bg-blue-100">
                  <Icon className="h-6 w-6" />
                </div>
                <h3 className="text-lg font-semibold text-slate-900">{p.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-slate-600">{p.description}</p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Install / Terminal Showcase ───

type TabKey = "install" | "agent" | "workflow" | "operate";

function InstallSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const [activeTab, setActiveTab] = useState<TabKey>("install");
  const [hasTyped, setHasTyped] = useState<Record<TabKey, boolean>>({ install: false, agent: false, workflow: false, operate: false });

  const tabs: { key: TabKey; label: string; icon: typeof Terminal }[] = [
    { key: "install", label: "Install", icon: Terminal },
    { key: "agent", label: "AIAgent", icon: Bot },
    { key: "workflow", label: "Workflow", icon: Workflow },
    { key: "operate", label: "Operate", icon: Play },
  ];

  const tabLines: Record<TabKey, TerminalLine[]> = {
    install: [
      { text: "helm repo add kubesynapse https://charts.kubesynapse.ai", color: "command", prefix: "$", type: "input" },
      { text: "helm repo update", color: "command", prefix: "$", type: "input" },
      { text: "helm install kubesynapse kubesynapse/kubesynapse \\", color: "command", prefix: "$", type: "input" },
      { text: "  --namespace kubesynapse --create-namespace \\", color: "command", prefix: "", type: "input" },
      { text: "  --set gateway.replicas=2", color: "command", prefix: "", type: "input" },
      { text: "", type: "blank" },
      { text: "NAME: kubesynapse", color: "output", type: "output" },
      { text: "NAMESPACE: kubesynapse", color: "output", type: "output" },
      { text: "STATUS: deployed", color: "string", type: "output" },
      { text: "REVISION: 1", color: "output", type: "output" },
    ],
    agent: [
      { text: "apiVersion: kubesynapse.ai/v1alpha1", color: "yamlKey", type: "input" },
      { text: "kind: AIAgent", color: "yamlKey", type: "input" },
      { text: "metadata:", color: "yamlKey", type: "input" },
      { text: "  name: incident-triage", color: "yamlVal", type: "input" },
      { text: "  namespace: production", color: "yamlVal", type: "input" },
      { text: "spec:", color: "yamlKey", type: "input" },
      { text: "  runtime:", color: "yamlKey", type: "input" },
      { text: "    name: opencode", color: "yamlVal", type: "input" },
      { text: "    model: claude-sonnet-4", color: "yamlVal", type: "input" },
      { text: "    temperature: 0.1", color: "yamlVal", type: "input" },
      { text: "  systemPrompt: |", color: "yamlKey", type: "input" },
      { text: "    You are an expert SRE agent. When an alert", color: "string", type: "input" },
      { text: "    fires, correlate logs, check pod status, and", color: "string", type: "input" },
      { text: "    suggest remediation steps. Always ask before", color: "string", type: "input" },
      { text: "    executing destructive commands.", color: "string", type: "input" },
      { text: "  memory:", color: "yamlKey", type: "input" },
      { text: "    strategy: persistent", color: "yamlVal", type: "input" },
      { text: "    ttl: 24h", color: "yamlVal", type: "input" },
      { text: "  mcpSidecars:", color: "yamlKey", type: "input" },
      { text: "    - name: kubernetes", color: "yamlVal", type: "input" },
      { text: "      config:", color: "yamlVal", type: "input" },
      { text: "        namespace: production", color: "yamlVal", type: "input" },
      { text: "    - name: web-search", color: "yamlVal", type: "input" },
      { text: "    - name: messaging", color: "yamlVal", type: "input" },
      { text: "  governance:", color: "yamlKey", type: "input" },
      { text: "    approvalRequired:", color: "yamlVal", type: "input" },
      { text: "      - kubectl delete", color: "list", type: "input" },
      { text: "      - kubectl exec", color: "list", type: "input" },
      { text: "    maxTokensPerRun: 50000", color: "yamlVal", type: "input" },
    ],
    workflow: [
      { text: "apiVersion: kubesynapse.ai/v1alpha1", color: "yamlKey", type: "input" },
      { text: "kind: AgentWorkflow", color: "yamlKey", type: "input" },
      { text: "metadata:", color: "yamlKey", type: "input" },
      { text: "  name: incident-response", color: "yamlVal", type: "input" },
      { text: "  namespace: production", color: "yamlVal", type: "input" },
      { text: "spec:", color: "yamlKey", type: "input" },
      { text: "  trigger:", color: "yamlKey", type: "input" },
      { text: "    type: webhook", color: "yamlVal", type: "input" },
      { text: "    source: prometheus", color: "yamlVal", type: "input" },
      { text: "  dag:", color: "yamlKey", type: "input" },
      { text: "    - id: triage", color: "yamlVal", type: "input" },
      { text: "      agentRef:", color: "yamlVal", type: "input" },
      { text: "        name: incident-triage", color: "yamlVal", type: "input" },
      { text: "      inputs:", color: "yamlVal", type: "input" },
      { text: "        alert: ${{ trigger.payload }}", color: "string", type: "input" },
      { text: "      next: [correlate, notify]", color: "yamlVal", type: "input" },
      { text: "", type: "blank" },
      { text: "    - id: correlate", color: "yamlVal", type: "input" },
      { text: "      agentRef:", color: "yamlVal", type: "input" },
      { text: "        name: log-analyzer", color: "yamlVal", type: "input" },
      { text: "      next: [remediate]", color: "yamlVal", type: "input" },
      { text: "", type: "blank" },
      { text: "    - id: remediate", color: "yamlVal", type: "input" },
      { text: "      agentRef:", color: "yamlVal", type: "input" },
      { text: "        name: incident-triage", color: "yamlVal", type: "input" },
      { text: "      approvalGate:", color: "yamlVal", type: "input" },
      { text: "        timeout: 10m", color: "yamlVal", type: "input" },
      { text: "      next: [notify]", color: "yamlVal", type: "input" },
      { text: "", type: "blank" },
      { text: "    - id: notify", color: "yamlVal", type: "input" },
      { text: "      agentRef:", color: "yamlVal", type: "input" },
      { text: "        name: slack-bot", color: "yamlVal", type: "input" },
      { text: "      inputs:", color: "yamlVal", type: "input" },
      { text: "        channel: #incidents", color: "string", type: "input" },
    ],
    operate: [
      { text: "kubectl apply -f agent.yaml", color: "command", prefix: "$", type: "input" },
      { text: "aiagent.kubesynapse.ai/incident-triage created", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "kubectl apply -f workflow.yaml", color: "command", prefix: "$", type: "input" },
      { text: "agentworkflow.kubesynapse.ai/incident-response created", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "kubectl get aiagents -n production", color: "command", prefix: "$", type: "input" },
      { text: "NAME            STATUS    AGE", color: "output", type: "output" },
      { text: "incident-triage Running   3m", color: "string", type: "output" },
      { text: "", type: "blank" },
      { text: "agentctl workflow run incident-response --watch", color: "command", prefix: "$", type: "input" },
      { text: "▶ Trigger: Alert received from Prometheus", color: "output", type: "output" },
      { text: "▶ TriageAgent: Correlating logs...", color: "output", type: "output" },
      { text: "▶ ApprovalGate: Waiting for human review", color: "flag", type: "output" },
    ],
  };

  const handleTabChange = (tab: TabKey) => {
    setActiveTab(tab);
    if (!hasTyped[tab]) {
      setHasTyped((prev) => ({ ...prev, [tab]: true }));
    }
  };

  // Auto-start typing for first tab when in view
  useEffect(() => {
    if (inView && !hasTyped.install) {
      const timer = setTimeout(() => {
        setHasTyped((prev) => ({ ...prev, install: true }));
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [inView, hasTyped.install]);

  return (
    <section id="install" className="bg-slate-50 px-4 py-24 sm:px-6 md:py-32" ref={ref}>
      <div className="mx-auto max-w-5xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-12 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            Quick Start
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Deploy in <span className="text-blue-600">5 Minutes</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-slate-600">
            One Helm install gives you the entire control plane. Then declare agents with YAML and control them with kubectl.
          </motion.p>
        </motion.div>

        {/* Tabbed Terminal */}
        <motion.div
          variants={itemVariants}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="overflow-hidden rounded-xl bg-slate-900 shadow-2xl shadow-slate-900/30 ring-1 ring-slate-700/50"
        >
          {/* Tabs */}
          <div className="flex border-b border-slate-700/50 bg-slate-800/80">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  onClick={() => handleTabChange(tab.key)}
                  className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-all ${
                    isActive
                      ? "bg-slate-900 text-sky-400 border-t-2 border-t-sky-500"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
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
                const text = tabLines[activeTab].map((l) => `${l.prefix || ""}${l.text}`).join("\n");
                navigator.clipboard.writeText(text).catch(() => {});
              }}
              className="px-4 py-3 text-slate-500 hover:text-slate-300 transition-colors"
              title="Copy"
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
                  transition={{ delay: i * 0.06, duration: 0.3 }}
                  className="min-h-[1.5rem]"
                >
                  {line.text === "" ? (
                    <span>&nbsp;</span>
                  ) : (
                    <span className={`whitespace-pre ${colorMap[line.color || "output"] || "text-slate-300"}`}>
                      {line.prefix && (
                        <span className="select-none text-emerald-500/80">{line.prefix} </span>
                      )}
                      {line.text}
                    </span>
                  )}
                </motion.div>
              ))}
            </motion.div>
          </AnimatePresence>
        </motion.div>

        {/* Feature pills below terminal */}
        <motion.div
          variants={itemVariants}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="mt-8 flex flex-wrap justify-center gap-3"
        >
          {["Helm Chart", "CRDs", "kubectl", "agentctl CLI", "A2A JSON-RPC"].map((item) => (
            <span
              key={item}
              className="rounded-full border border-slate-200 bg-white px-4 py-1.5 text-xs font-medium text-slate-600 shadow-sm"
            >
              {item}
            </span>
          ))}
        </motion.div>
      </div>
    </section>
  );
}

const colorMap: Record<string, string> = {
  comment: "text-slate-500",
  command: "text-sky-400",
  string: "text-emerald-400",
  flag: "text-amber-400",
  output: "text-slate-400",
  yamlKey: "text-fuchsia-400",
  yamlVal: "text-slate-300",
  prompt: "text-emerald-500",
  list: "text-slate-300",
};

// ─── Features Grid ───

function FeaturesSection() {
  const features = [
    {
      icon: Server,
      title: "Kubernetes-Native Orchestration",
      description:
        "Agents, policies, workflows, and tenants are first-class CRDs reconciled by a production Kopf operator.",
      tags: ["CRDs", "Operator", "Helm"],
    },
    {
      icon: MessageSquare,
      title: "A2A Protocol Support",
      description:
        "Native JSON-RPC and Server-Sent Events for agent-to-agent delegation, streaming, and real-time collaboration.",
      tags: ["JSON-RPC", "SSE", "A2A"],
    },
    {
      icon: Terminal,
      title: "OpenCode Runtime",
      description:
        "Purpose-built FastAPI wrapper around opencode serve with session persistence and checkpoint recovery.",
      tags: ["StatefulSet", "PVC", "Checkpoints"],
    },
    {
      icon: Puzzle,
      title: "MCP Tool Ecosystem",
      description:
        "Attach Model Context Protocol servers as sidecars. Kubernetes ops, web search, browser automation, RAG, and more.",
      tags: ["11 Sidecars", "Hot Attach", "Tools"],
    },
    {
      icon: Shield,
      title: "Policy-Driven Governance",
      description:
        "AgentPolicy CRDs enforce input/output guardrails, token caps, PII masking, and allowed model lists.",
      tags: ["Guardrails", "RBAC", "Approval"],
    },
    {
      icon: Workflow,
      title: "Visual Workflow Engine",
      description:
        "Build multi-agent pipelines with a drag-and-drop DAG editor. Approval gates, parallel execution, and retries.",
      tags: ["DAG", "Retries", "Approval Gates"],
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section id="features" className="bg-white px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            Platform Features
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Everything You Need to <span className="text-blue-600">Ship Agents</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-slate-600">
            From development to production. A complete control plane for Kubernetes-native AI agent operations.
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
                className="group rounded-2xl border border-slate-200 bg-white p-7 shadow-sm transition-all hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md"
              >
                <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100 transition-colors group-hover:bg-blue-100">
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-base font-semibold text-slate-900">{feature.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{feature.description}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  {feature.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-medium text-slate-600"
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
      description: "Write an AIAgent CRD with your system prompt, model, memory policy, and MCP sidecars. Apply it with kubectl.",
      gradient: "from-blue-500 to-indigo-600",
      bgGradient: "from-blue-50 to-indigo-50",
    },
    {
      num: "02",
      icon: RefreshCw,
      title: "Reconcile",
      description: "The Kopf operator watches your CRD and provisions a StatefulSet, Service, PVC, and ConfigMap automatically.",
      gradient: "from-indigo-500 to-purple-600",
      bgGradient: "from-indigo-50 to-purple-50",
    },
    {
      num: "03",
      icon: Bot,
      title: "Execute",
      description: "Invoke via agentctl, the web UI, or A2A JSON-RPC. The runtime persists memory, enforces policies, and routes model calls through LiteLLM.",
      gradient: "from-purple-500 to-pink-600",
      bgGradient: "from-purple-50 to-pink-50",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section className="bg-white px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            How It Works
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            From YAML to <span className="bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">Running Agent</span>
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
                      <div className="h-px w-6 bg-gradient-to-r from-slate-300 to-slate-200" />
                      <motion.div
                        className="h-2 w-2 rounded-full bg-blue-400"
                        animate={{ scale: [1, 1.3, 1], opacity: [0.5, 1, 0.5] }}
                        transition={{ duration: 2, repeat: Infinity, delay: i * 0.5 }}
                      />
                    </motion.div>
                  </div>
                )}

                <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-8 transition-all duration-300 hover:shadow-xl hover:shadow-blue-900/5 hover:-translate-y-1">
                  {/* Background gradient blob */}
                  <div className={`absolute -right-10 -top-10 h-32 w-32 rounded-full bg-gradient-to-br ${step.bgGradient} opacity-60 blur-2xl transition-opacity group-hover:opacity-100`} />

                  {/* Step number badge */}
                  <div className="relative mb-6 flex items-center justify-between">
                    <div className={`flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br ${step.gradient} text-white shadow-lg shadow-blue-500/20`}>
                      <Icon className="h-7 w-7" />
                    </div>
                    <span className={`text-5xl font-black bg-gradient-to-br ${step.gradient} bg-clip-text text-transparent opacity-20`}>
                      {step.num}
                    </span>
                  </div>

                  {/* Content */}
                  <div className="relative">
                    <h3 className="text-xl font-bold text-slate-900">{step.title}</h3>
                    <p className="mt-3 text-sm leading-relaxed text-slate-600">
                      {step.description}
                    </p>
                  </div>

                  {/* Bottom accent line */}
                  <div className={`absolute bottom-0 left-0 h-1 w-0 bg-gradient-to-r ${step.gradient} transition-all duration-500 group-hover:w-full rounded-b-2xl`} />
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

// ─── Stunning Workflow Animation ───

function WorkflowAnimation() {
  const [stage, setStage] = useState(0);
  const totalStages = 6;

  useEffect(() => {
    const interval = setInterval(() => {
      setStage((s) => (s + 1) % totalStages);
    }, 2800);
    return () => clearInterval(interval);
  }, []);

  const nodes = [
    { id: "ingress", label: "Ingress", sub: "A2A / Webhook", x: 60, y: 140, icon: Globe },
    { id: "gateway", label: "API Gateway", sub: "FastAPI + Auth", x: 220, y: 140, icon: Server },
    { id: "operator", label: "Operator", sub: "Kopf Engine", x: 400, y: 140, icon: RefreshCw },
    { id: "runtime", label: "Runtime", sub: "OpenCode STS", x: 580, y: 70, icon: Bot },
    { id: "mcp", label: "MCP Sidecars", sub: "Tool Pods", x: 580, y: 210, icon: Puzzle },
    { id: "llm", label: "LiteLLM", sub: "Model Router", x: 760, y: 140, icon: BrainCircuit },
  ];

  const edges = [
    { from: "ingress", to: "gateway", id: 0 },
    { from: "gateway", to: "operator", id: 1 },
    { from: "operator", to: "runtime", id: 2 },
    { from: "operator", to: "mcp", id: 3 },
    { from: "runtime", to: "llm", id: 4 },
    { from: "mcp", to: "llm", id: 5 },
  ];

  const stageMap: Record<number, { active: string[]; packet?: { edgeId: number } }> = {
    0: { active: ["ingress"], packet: { edgeId: 0 } },
    1: { active: ["gateway"], packet: { edgeId: 1 } },
    2: { active: ["operator"], packet: { edgeId: 2 } },
    3: { active: ["runtime"], packet: { edgeId: 4 } },
    4: { active: ["llm"], packet: { edgeId: 4 } },
    5: { active: ["runtime", "mcp"], packet: { edgeId: 5 } },
  };

  const activeIds = stageMap[stage]?.active || [];
  const packetEdge = stageMap[stage]?.packet;

  const getNode = (id: string) => nodes.find((n) => n.id === id)!;

  const getPathPoints = (edgeId: number) => {
    const edge = edges[edgeId];
    const from = getNode(edge.from);
    const to = getNode(edge.to);
    // Node dimensions in SVG coords
    const nw = 120;
    const nh = 56;
    const startX = from.x + nw;
    const startY = from.y + nh / 2;
    const endX = to.x;
    const endY = to.y + nh / 2;
    const midX = (startX + endX) / 2;
    return [
      { x: startX, y: startY },
      { x: midX, y: startY },
      { x: midX, y: endY },
      { x: endX, y: endY },
    ];
  };

  return (
    <section id="workflows" className="bg-white px-6 py-24 md:py-32">
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: "-80px" }}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            Live Pipeline
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Kubernetes Pipeline <span className="text-blue-600">in Motion</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-slate-600">
            Watch requests flow from ingress to runtime. Every node is a real Kubernetes resource
            reconciled by the operator.
          </motion.p>
        </motion.div>

        <motion.div
          variants={fadeIn}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
          className="relative overflow-hidden rounded-2xl border border-slate-200 bg-slate-50 p-6 shadow-sm md:p-10"
        >
          <svg
            viewBox="0 0 900 300"
            className="mx-auto h-auto w-full max-w-[900px]"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <linearGradient id="connGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#3b82f6">
                  <animate attributeName="stop-color" values="#3b82f6;#06b6d4;#3b82f6" dur="3s" repeatCount="indefinite" />
                </stop>
                <stop offset="100%" stopColor="#06b6d4">
                  <animate attributeName="stop-color" values="#06b6d4;#3b82f6;#06b6d4" dur="3s" repeatCount="indefinite" />
                </stop>
              </linearGradient>
              <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            {/* Connection Lines */}
            {edges.map((edge) => {
              const from = getNode(edge.from);
              const to = getNode(edge.to);
              const nw = 120;
              const nh = 56;
              const x1 = from.x + nw;
              const y1 = from.y + nh / 2;
              const x2 = to.x;
              const y2 = to.y + nh / 2;
              const mx = (x1 + x2) / 2;
              const isPacketActive = packetEdge?.edgeId === edge.id;

              return (
                <g key={edge.id}>
                  <path
                    d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                    stroke="#cbd5e1"
                    strokeWidth={2}
                    fill="none"
                  />
                  <motion.path
                    d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                    stroke="url(#connGradient)"
                    strokeWidth={2.5}
                    fill="none"
                    strokeDasharray="8 5"
                    initial={{ strokeDashoffset: 0 }}
                    animate={{ strokeDashoffset: isPacketActive ? -26 : 0 }}
                    transition={isPacketActive ? { duration: 0.8, repeat: Infinity, ease: "linear" } : {}}
                    opacity={isPacketActive ? 1 : 0.6}
                  />
                </g>
              );
            })}

            {/* Data Packet */}
            {packetEdge && (
              <PacketCircle path={getPathPoints(packetEdge.edgeId)} />
            )}

            {/* Nodes */}
            {nodes.map((node) => {
              const Icon = node.icon;
              const isActive = activeIds.includes(node.id);
              return (
                <g key={node.id}>
                  {/* Pulse ring */}
                  {isActive && (
                    <motion.rect
                      x={node.x - 4}
                      y={node.y - 4}
                      width={128}
                      height={64}
                      rx={14}
                      fill="none"
                      stroke="#3b82f6"
                      strokeWidth={2}
                      initial={{ opacity: 0.6, scale: 1 }}
                      animate={{ opacity: 0, scale: 1.15 }}
                      transition={{ duration: 1.5, repeat: Infinity }}
                      style={{ transformOrigin: `${node.x + 60}px ${node.y + 28}px` }}
                    />
                  )}
                  {/* Node body */}
                  <foreignObject x={node.x} y={node.y} width={120} height={56}>
                    <motion.div
                      className={`flex h-full w-full flex-col items-center justify-center rounded-xl border bg-white shadow-sm ${
                        isActive ? "border-blue-400 shadow-blue-200" : "border-slate-200"
                      }`}
                      animate={
                        isActive
                          ? {
                              boxShadow: [
                                "0 0 0 0 rgba(59,130,246,0)",
                                "0 0 20px 2px rgba(59,130,246,0.25)",
                                "0 0 0 0 rgba(59,130,246,0)",
                              ],
                            }
                          : {}
                      }
                      transition={{ duration: 2, repeat: Infinity }}
                    >
                      <div className="flex items-center gap-2">
                        <Icon className={`h-4 w-4 ${isActive ? "text-blue-600" : "text-slate-500"}`} />
                        <div className="flex flex-col">
                          <span className="text-[11px] font-bold text-slate-900 leading-tight">{node.label}</span>
                          <span className="text-[9px] text-slate-500 leading-tight">{node.sub}</span>
                        </div>
                      </div>
                    </motion.div>
                  </foreignObject>
                  {/* Status dot */}
                  <circle
                    cx={node.x + 112}
                    cy={node.y + 10}
                    r={3}
                    fill={isActive ? "#10b981" : "#cbd5e1"}
                  >
                    {isActive && (
                      <animate attributeName="opacity" values="1;0.4;1" dur="2s" repeatCount="indefinite" />
                    )}
                  </circle>
                </g>
              );
            })}
          </svg>

          {/* Status bar */}
          <div className="mt-8 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white px-5 py-3.5 shadow-sm">
            <div className="flex flex-wrap items-center gap-6 text-xs text-slate-600">
              <span className="flex items-center gap-1.5">
                <Timer className="h-3.5 w-3.5 text-blue-600" />
                Reconcile: 1.2s
              </span>
              <span className="flex items-center gap-1.5">
                <Bot className="h-3.5 w-3.5 text-blue-600" />
                3 agents active
              </span>
              <span className="flex items-center gap-1.5">
                <Shield className="h-3.5 w-3.5 text-amber-500" />
                1 approval gate
              </span>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Pipeline Healthy
            </span>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

function PacketCircle({ path }: { path: { x: number; y: number }[] }) {
  return (
    <motion.circle
      r={5}
      fill="#06b6d4"
      filter="url(#glow)"
      initial={{ cx: path[0].x, cy: path[0].y, opacity: 0 }}
      animate={{
        cx: path.map((p) => p.x),
        cy: path.map((p) => p.y),
        opacity: [0, 1, 1, 0],
      }}
      transition={{ duration: 1.4, ease: "easeInOut" }}
    />
  );
}

// ─── Architecture Preview ───

function ArchitectureSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  const components = [
    { label: "Control Plane", items: ["Kubernetes API", "Operator (Kopf)", "API Gateway", "CRDs v1alpha1"] },
    { label: "Execution Plane", items: ["OpenCode Runtime", "MCP Sidecars", "Worker Jobs", "StatefulSets"] },
    { label: "Shared Services", items: ["LiteLLM Proxy", "Qdrant", "Redis", "PostgreSQL", "NATS"] },
  ];

  return (
    <section id="architecture" className="bg-slate-50 px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            Architecture
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Built for <span className="text-blue-600">Production</span>
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-2xl text-base text-slate-600">
            Separation of control plane and execution plane. Every agent is an isolated StatefulSet
            with its own persistent volume and policy envelope.
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
              className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
            >
              <h3 className="mb-4 text-sm font-bold uppercase tracking-wider text-slate-500">{col.label}</h3>
              <div className="space-y-3">
                {col.items.map((item) => (
                  <div
                    key={item}
                    className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700"
                  >
                    <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-blue-600" />
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

// ─── Testimonials ───

function TestimonialsSection() {
  const quotes = [
    {
      quote:
        "kubesynapse finally let us treat AI agents like any other Kubernetes workload. CRDs, Helm, kubectl — it fits into our existing GitOps pipeline without friction.",
      role: "Platform Engineer",
      org: "Fortune 500 Infrastructure Team",
    },
    {
      quote:
        "The policy engine is a game changer. We can enforce token budgets and tool guardrails at the cluster level. No more worrying about runaway agent spend.",
      role: "SRE Lead",
      org: "Cloud-Native SaaS Startup",
    },
    {
      quote:
        "Running agents as StatefulSets with persistent memory means our incident-response bot actually remembers previous outages. The checkpoint recovery is rock solid.",
      role: "Kubernetes Contributor",
      org: "Open Source Community",
    },
  ];

  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });

  return (
    <section className="bg-white px-6 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-7xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-16 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-600">
            Community
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Trusted by <span className="text-blue-600">Operators</span>
          </motion.h2>
        </motion.div>

        <div className="grid gap-6 md:grid-cols-3">
          {quotes.map((q, i) => (
            <motion.div
              key={i}
              variants={itemVariants}
              initial="hidden"
              animate={inView ? "visible" : "hidden"}
              transition={{ delay: i * 0.1 }}
              className="relative rounded-2xl border border-slate-200 bg-white p-7 shadow-sm"
            >
              <div className="mb-4 text-blue-600">
                <MessageSquare className="h-6 w-6" />
              </div>
              <p className="text-sm leading-relaxed text-slate-700">&ldquo;{q.quote}&rdquo;</p>
              <div className="mt-6 border-t border-slate-100 pt-4">
                <p className="text-sm font-semibold text-slate-900">{q.role}</p>
                <p className="text-xs text-slate-500">{q.org}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}

// ─── Comparison Matrix ───

function ComparisonStrip() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });

  const columns = ["kubesynapse", "LangChain", "CrewAI", "Kubiya"];
  const rows = [
    { label: "Kubernetes Native", kubesynapse: "✅", langchain: "❌", crewai: "❌", kubiya: "⚠️" },
    { label: "Self-Hosted (Helm)", kubesynapse: "✅", langchain: "❌", crewai: "❌", kubiya: "❌ SaaS" },
    { label: "CRD Governance", kubesynapse: "✅", langchain: "❌", crewai: "❌", kubiya: "❌" },
    { label: "A2A Protocol", kubesynapse: "✅ JSON-RPC/SSE", langchain: "❌", crewai: "❌", kubiya: "⚠️ REST" },
    { label: "MCP Tool Ecosystem", kubesynapse: "✅ 11 sidecars", langchain: "✅ Tools", crewai: "✅ Tools", kubiya: "⚠️ Built-in" },
    { label: "HITL Approval Gates", kubesynapse: "✅ CRD", langchain: "⚠️ Manual", crewai: "⚠️ Manual", kubiya: "✅" },
    { label: "Token Budget Enforcement", kubesynapse: "✅ CRD", langchain: "❌ LangSmith $", crewai: "❌", kubiya: "✅" },
    { label: "Multi-Tenancy", kubesynapse: "✅ Namespaces", langchain: "❌", crewai: "❌", kubiya: "⚠️ Org-based" },
    { label: "Stateful Agents (PVC)", kubesynapse: "✅ StatefulSet", langchain: "❌", crewai: "❌", kubiya: "❌" },
    { label: "Workflow DAG Engine", kubesynapse: "✅ CRD", langchain: "✅ LCEL", crewai: "✅ Process", kubiya: "✅" },
    { label: "Built-in Auth", kubesynapse: "✅ OIDC + Token", langchain: "❌", crewai: "❌", kubiya: "✅ SaaS" },
    { label: "Open Source (Apache 2)", kubesynapse: "✅", langchain: "✅ MIT", crewai: "✅ MIT", kubiya: "❌ Proprietary" },
  ];

  const cellStyle = (text: string) => {
    if (text.startsWith("✅")) return "text-emerald-400";
    if (text.startsWith("❌")) return "text-slate-500";
    return "text-amber-400";
  };

  return (
    <section className="bg-slate-900 px-4 py-24 md:py-32" ref={ref}>
      <div className="mx-auto max-w-6xl">
        <motion.div
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          variants={containerVariants}
          className="mb-12 text-center"
        >
          <motion.p variants={itemVariants} className="text-xs font-semibold uppercase tracking-widest text-blue-400">
            Comparison Matrix
          </motion.p>
          <motion.h2 variants={itemVariants} className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            kubesynapse vs The Alternatives
          </motion.h2>
          <motion.p variants={itemVariants} className="mx-auto mt-4 max-w-xl text-sm text-slate-400">
            kubesynapse is the only platform purpose-built for production Kubernetes — not a Python library with a K8s deployment guide.
          </motion.p>
        </motion.div>

        <motion.div
          variants={fadeIn}
          initial="hidden"
          animate={inView ? "visible" : "hidden"}
          className="overflow-x-auto rounded-2xl border border-slate-700 bg-slate-800/50"
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="px-4 py-4 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">Capability</th>
                {columns.map((col) => (
                  <th key={col} className={`px-4 py-4 text-center text-xs font-bold uppercase tracking-wider ${col === "kubesynapse" ? "text-blue-400" : "text-slate-500"}`}>
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.label} className={i < rows.length - 1 ? "border-b border-slate-700/50" : ""}>
                  <td className="px-4 py-3.5 text-slate-300 font-medium">{row.label}</td>
                  <td className={`px-4 py-3.5 text-center font-medium ${cellStyle(row.kubesynapse)}`}>
                    {row.kubesynapse}
                  </td>
                  <td className={`px-4 py-3.5 text-center ${cellStyle(row.langchain)}`}>
                    {row.langchain}
                  </td>
                  <td className={`px-4 py-3.5 text-center ${cellStyle(row.crewai)}`}>
                    {row.crewai}
                  </td>
                  <td className={`px-4 py-3.5 text-center ${cellStyle(row.kubiya)}`}>
                    {row.kubiya}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>

        <p className="mt-6 text-center text-xs text-slate-500">
          ✅ = Native support &nbsp;|&nbsp; ⚠️ = Partial / requires setup &nbsp;|&nbsp; ❌ = Not available
        </p>
      </div>
    </section>
  );
}

// ─── Bottom CTA ───

function BottomCTA({ onLogin }: { onLogin: () => void }) {
  return (
    <section className="bg-white px-6 py-24 md:py-32">
      <div className="mx-auto max-w-4xl text-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.6 }}
          className="rounded-3xl border border-slate-200 bg-slate-50 p-10 md:p-16 shadow-sm"
        >
          <div className="mx-auto mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-lg shadow-blue-600/20">
            <Workflow className="h-7 w-7" />
          </div>
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl md:text-5xl">
            Ready to <span className="text-blue-600">Orchestrate</span>?
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-base text-slate-600">
            Initialize your workspace and deploy your first agent in minutes.
            Start with incident triage, compliance auditing, or bring your own workflow.
          </p>
          <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <button
              onClick={onLogin}
              className="group flex items-center gap-2 rounded-xl bg-slate-900 px-8 py-3.5 text-sm font-semibold text-white shadow-lg transition-all hover:bg-slate-800 hover:shadow-xl active:scale-[0.98]"
            >
              Get Started Free
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </button>
            <a
              href="https://github.com/kubesynapse/kubesynapse"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-8 py-3.5 text-sm font-semibold text-slate-700 shadow-sm transition-all hover:bg-slate-50 hover:border-slate-300"
            >
              <GitBranch className="h-4 w-4 text-blue-600" />
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
    <footer className="border-t border-slate-200 bg-white px-6 py-14">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
          <div className="sm:col-span-2 lg:col-span-1">
            <div className="flex items-center gap-2">
              <LayoutPanelTop className="h-5 w-5 text-blue-600" />
              <span className="text-sm font-bold text-slate-900">{BRAND.name}</span>
            </div>
            <p className="mt-3 max-w-[260px] text-xs leading-relaxed text-slate-500">
              Kubernetes-native AI agent orchestration with durable memory, governance,
              and enterprise workflow automation. Open source under Apache 2.0.
            </p>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Product</h4>
            <ul className="mt-4 space-y-2.5 text-sm text-slate-600">
              <li><a href="#features" className="transition-colors hover:text-slate-900">Features</a></li>
              <li><a href="#architecture" className="transition-colors hover:text-slate-900">Architecture</a></li>
              <li><a href="#workflows" className="transition-colors hover:text-slate-900">Workflows</a></li>
              <li><a href="#install" className="transition-colors hover:text-slate-900">Quick Start</a></li>
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Resources</h4>
            <ul className="mt-4 space-y-2.5 text-sm text-slate-600">
              <li><a href="#" className="transition-colors hover:text-slate-900">Documentation</a></li>
              <li><a href="https://github.com/kubesynapse/kubesynapse" target="_blank" rel="noopener noreferrer" className="transition-colors hover:text-slate-900">GitHub</a></li>
              <li><a href="#" className="transition-colors hover:text-slate-900">Changelog</a></li>
              <li><a href="#" className="transition-colors hover:text-slate-900">Helm Charts</a></li>
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Community</h4>
            <ul className="mt-4 space-y-2.5 text-sm text-slate-600">
              <li><a href="#" className="transition-colors hover:text-slate-900">Contributing</a></li>
              <li><a href="#" className="transition-colors hover:text-slate-900">Security</a></li>
              <li><a href="#" className="transition-colors hover:text-slate-900">License</a></li>
              <li><a href="#" className="transition-colors hover:text-slate-900">Status</a></li>
            </ul>
          </div>
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-slate-100 pt-8 sm:flex-row">
          <p className="text-xs text-slate-500">
            &copy; {new Date().getFullYear()} {BRAND.name}. Open source under Apache 2.0.
          </p>
          <div className="flex items-center gap-6 text-xs text-slate-500">
            <a href="#" className="transition-colors hover:text-slate-900">Privacy</a>
            <a href="#" className="transition-colors hover:text-slate-900">Terms</a>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ─── Main LandingPage ───

export function LandingPage({ onLogin }: LandingPageProps) {
  const [darkMode, setDarkMode] = useState(() => {
    if (typeof window !== "undefined") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e: MediaQueryListEvent) => setDarkMode(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return (
    <div className={`min-h-screen transition-colors duration-300 ${darkMode ? "bg-slate-900 text-slate-100" : "bg-white text-slate-900"}`}>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-lg focus:bg-blue-600 focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-white"
      >
        Skip to main content
      </a>
      <Navbar onLogin={onLogin} darkMode={darkMode} onToggleDark={() => setDarkMode((v) => !v)} />
      <main id="main-content">
        <HeroSection onLogin={onLogin} />
        <EcosystemCloud />
        <ProblemSection />
        <InstallSection />
        <FeaturesSection />
        <HowItWorks />
        <WorkflowAnimation />
        <ArchitectureSection />
        <TestimonialsSection />
        <ComparisonStrip />
        <BottomCTA onLogin={onLogin} />
      </main>
      <Footer />
    </div>
  );
}

export default LandingPage;
