import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Copy,
  Eye,
  EyeOff,
  FileCode2,
  Globe,
  HelpCircle,
  Laptop,
  List,
  LoaderCircle,
  Lock,
  Package,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Server,
  Shield,
  Sparkles,
  Terminal,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  apiErrorMessage,
  deleteCollectionTask,
  deleteCollectionTasks,
  fetchIntelligenceCollectors,
  registerIntelligenceCollector,
  unregisterIntelligenceCollector,
  submitCollectionTask,
  fetchCollectionTasks,
  type IntelligenceCollector,
  type CollectionTask,
  type CollectionTaskResult,
  type RegisterCollectorPayload,
  type SubmitCollectionPayload,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Script categories ────────────────────────────────────────────────────

type ScriptCategory = "health" | "workloads" | "security" | "config";

const SCRIPT_CATEGORIES: Record<ScriptCategory, { label: string; color: string }> = {
  health: { label: "Health & Status", color: "text-emerald-500" },
  workloads: { label: "Workloads & Resources", color: "text-blue-500" },
  security: { label: "Security & Compliance", color: "text-amber-500" },
  config: { label: "Configuration & State", color: "text-violet-500" },
};

const BUILTIN_SCRIPTS: Record<string, { label: string; description: string; icon: typeof Server; category: ScriptCategory }> = {
  cluster_overview: {
    label: "Cluster Overview",
    description: "K8s version, namespaces, resource counts, warning events",
    icon: Globe,
    category: "health",
  },
  node_health: {
    label: "Node Health",
    description: "Node status, resources, conditions, pressure indicators",
    icon: Server,
    category: "health",
  },
  pod_resources: {
    label: "Pod Resources",
    description: "Pod resource usage, status summary, non-running pods",
    icon: Activity,
    category: "workloads",
  },
  logs_collector: {
    label: "Logs & Events",
    description: "Pod restarts, warning events, CrashLoopBackOff, OOMKilled",
    icon: AlertTriangle,
    category: "workloads",
  },
  helm_releases: {
    label: "Helm Releases",
    description: "Helm release inventory, failed/pending releases",
    icon: Package,
    category: "workloads",
  },
  network_info: {
    label: "Network Info",
    description: "Services, ingresses, network policies, DNS config",
    icon: Radio,
    category: "config",
  },
  storage_info: {
    label: "Storage Info",
    description: "Storage classes, PVs, PVCs, disk usage",
    icon: Laptop,
    category: "config",
  },
  configmap_secrets: {
    label: "ConfigMaps & Secrets",
    description: "ConfigMap/Secret counts, large CMs, expiring TLS certs",
    icon: List,
    category: "config",
  },
  security_posture: {
    label: "Security Posture",
    description: "RBAC, service accounts, secrets, pod security standards",
    icon: Shield,
    category: "security",
  },
  crd_inventory: {
    label: "CRD Inventory",
    description: "Custom resource definitions and instance counts",
    icon: BookOpen,
    category: "config",
  },
};

const DEFAULT_COLLECTOR_TOKEN = "collector-dev-token";

// ─── Component ────────────────────────────────────────────────────────────

export function IntelligenceDashboard() {
  const { token, namespace, canMutate } = useConnection();

  // ── Data state ──
  const [collectors, setCollectors] = useState<IntelligenceCollector[]>([]);
  const [tasks, setTasks] = useState<CollectionTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // ── Selection state ──
  const [activeTab, setActiveTab] = useState<"collectors" | "tasks">("collectors");
  const [selectedCollector, setSelectedCollector] = useState<IntelligenceCollector | null>(null);
  const [selectedTask, setSelectedTask] = useState<CollectionTask | null>(null);
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([]);
  const [searchFilter, setSearchFilter] = useState("");

  // ── Dialog state ──
  const [showRegisterDialog, setShowRegisterDialog] = useState(false);
  const [showCollectDialog, setShowCollectDialog] = useState(false);
  const [showDeleteTasksDialog, setShowDeleteTasksDialog] = useState(false);

  // Register form
  const [regName, setRegName] = useState("");
  const [regUrl, setRegUrl] = useState("");
  const [regCluster, setRegCluster] = useState("");
  const [regToken, setRegToken] = useState(DEFAULT_COLLECTOR_TOKEN);
  const [regShowAdvanced, setRegShowAdvanced] = useState(false);
  const [regShowToken, setRegShowToken] = useState(false);
  const [regSaving, setRegSaving] = useState(false);

  // Collect form
  const [collectTarget, setCollectTarget] = useState("all");
  const [collectMode, setCollectMode] = useState<"builtin" | "custom">("builtin");
  const [collectBuiltin, setCollectBuiltin] = useState("cluster_overview");
  const [collectScript, setCollectScript] = useState("");
  const [collectScriptType, setCollectScriptType] = useState<"bash" | "python">("bash");
  const [collectTimeout, setCollectTimeout] = useState(30);
  const [collectRunning, setCollectRunning] = useState(false);
  const [scriptSearch, setScriptSearch] = useState("");

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<IntelligenceCollector | null>(null);

  // ── Data fetching ──

  const refresh = useCallback(async () => {
    if (!token) return;
    setRefreshing(true);
    try {
      const [collectorData, taskData] = await Promise.all([
        fetchIntelligenceCollectors(token, namespace),
        fetchCollectionTasks(token, 100, namespace),
      ]);
      setCollectors(collectorData.collectors);
      setTasks(taskData.tasks);
    } catch (err) {
      toast.error("Failed to load intelligence data", { description: apiErrorMessage(err) });
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, namespace]);

  useEffect(() => {
    refresh();
    const interval = setInterval(() => {
      // Pause auto-refresh when dialogs are open to avoid UI flicker
      if (!showRegisterDialog && !showCollectDialog) refresh();
    }, 15000);
    return () => clearInterval(interval);
  }, [refresh, showRegisterDialog, showCollectDialog]);

  useEffect(() => {
    const existingTaskIds = new Set(tasks.map((task) => task.task_id));
    setSelectedTaskIds((current) => current.filter((taskId) => existingTaskIds.has(taskId)));
    if (selectedTask && !existingTaskIds.has(selectedTask.task_id)) {
      setSelectedTask(null);
    }
  }, [tasks, selectedTask]);

  // ── Handlers ──

  const handleRegister = useCallback(async () => {
    if (!token || !regName.trim() || !regUrl.trim()) return;
    setRegSaving(true);
    try {
      const payload: RegisterCollectorPayload = {
        name: regName.trim(),
        url: regUrl.trim(),
        cluster: regCluster.trim() || undefined,
        token: regToken.trim() || undefined,
      };
      await registerIntelligenceCollector(token, payload, namespace);
      toast.success(`Collector "${regName}" registered`);
      setShowRegisterDialog(false);
      setRegName("");
      setRegUrl("");
      setRegCluster("");
      setRegToken(DEFAULT_COLLECTOR_TOKEN);
      setRegShowAdvanced(false);
      refresh();
    } catch (err) {
      toast.error("Failed to register collector", { description: apiErrorMessage(err) });
    } finally {
      setRegSaving(false);
    }
  }, [token, namespace, regName, regUrl, regCluster, regToken, refresh]);

  const handleUnregister = useCallback(async () => {
    if (!token || !deleteTarget) return;
    try {
      await unregisterIntelligenceCollector(token, deleteTarget.id, namespace);
      toast.success(`Collector "${deleteTarget.name}" unregistered`);
      setDeleteTarget(null);
      if (selectedCollector?.id === deleteTarget.id) setSelectedCollector(null);
      refresh();
    } catch (err) {
      toast.error("Failed to unregister collector", { description: apiErrorMessage(err) });
    }
  }, [token, namespace, deleteTarget, selectedCollector, refresh]);

  const handleCollect = useCallback(async () => {
    if (!token) return;
    setCollectRunning(true);
    try {
      const payload: SubmitCollectionPayload = {
        collector_id: collectTarget,
        timeout: collectTimeout,
      };
      if (collectMode === "builtin") {
        payload.builtin = collectBuiltin;
      } else {
        payload.script = collectScript;
        payload.type = collectScriptType;
      }
      const result = await submitCollectionTask(token, payload, namespace);
      toast.success(`Collection task ${result.task_id} completed (${result.completed}/${result.total} succeeded)`);
      setShowCollectDialog(false);
      setActiveTab("tasks");
      setSelectedTask(result);
      refresh();
    } catch (err) {
      toast.error("Collection failed", { description: apiErrorMessage(err) });
    } finally {
      setCollectRunning(false);
    }
  }, [token, namespace, collectTarget, collectMode, collectBuiltin, collectScript, collectScriptType, collectTimeout, refresh]);

  const handleQuickRun = useCallback(async (scriptKey: string) => {
    if (!token || collectors.length === 0) return;
    setCollectRunning(true);
    try {
      const result = await submitCollectionTask(token, {
        collector_id: "all",
        builtin: scriptKey,
        timeout: 30,
      }, namespace);
      toast.success(`${BUILTIN_SCRIPTS[scriptKey]?.label} completed (${result.completed}/${result.total})`);
      setActiveTab("tasks");
      setSelectedTask(result);
      refresh();
    } catch (err) {
      toast.error("Collection failed", { description: apiErrorMessage(err) });
    } finally {
      setCollectRunning(false);
    }
  }, [token, namespace, collectors.length, refresh]);

  const toggleTaskSelection = useCallback((taskId: string, checked: boolean) => {
    setSelectedTaskIds((current) => {
      if (checked) {
        return current.includes(taskId) ? current : [...current, taskId];
      }
      return current.filter((value) => value !== taskId);
    });
  }, []);

  const promptDeleteTasks = useCallback((taskId?: string) => {
    if (taskId) {
      setSelectedTaskIds((current) => (current.length > 1 && current.includes(taskId) ? current : [taskId]));
      setShowDeleteTasksDialog(true);
      return;
    }
    if (selectedTaskIds.length === 0) return;
    setShowDeleteTasksDialog(true);
  }, [selectedTaskIds.length]);

  const handleDeleteTasks = useCallback(async () => {
    if (!token || selectedTaskIds.length === 0) return;
    const taskIds = [...selectedTaskIds];
    try {
      if (taskIds.length === 1) {
        await deleteCollectionTask(token, taskIds[0], namespace);
      } else {
        await deleteCollectionTasks(token, taskIds, namespace);
      }
      toast.success(taskIds.length === 1 ? `Deleted task ${taskIds[0]}` : `Deleted ${taskIds.length} task runs`);
      setSelectedTaskIds([]);
      if (selectedTask && taskIds.includes(selectedTask.task_id)) {
        setSelectedTask(null);
      }
      await refresh();
    } catch (err) {
      toast.error("Failed to delete task runs", { description: apiErrorMessage(err) });
    }
  }, [namespace, refresh, selectedTask, selectedTaskIds, token]);

  // ── Computed ──

  const selectedTaskIdSet = useMemo(() => new Set(selectedTaskIds), [selectedTaskIds]);

  const onlineCollectors = collectors.filter((c) => c.status === "online").length;
  const totalTasks = tasks.length;
  const completedTasks = tasks.filter((t) => t.completed === t.total).length;

  const filteredCollectors = useMemo(() => {
    if (!searchFilter) return collectors;
    const q = searchFilter.toLowerCase();
    return collectors.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.cluster.toLowerCase().includes(q) ||
        c.status.includes(q),
    );
  }, [collectors, searchFilter]);

  const filteredTasks = useMemo(() => {
    if (!searchFilter) return tasks;
    const q = searchFilter.toLowerCase();
    return tasks.filter(
      (t) =>
        t.task_id.toLowerCase().includes(q) ||
        t.collector_id.toLowerCase().includes(q) ||
        JSON.stringify(t.payload).toLowerCase().includes(q),
    );
  }, [tasks, searchFilter]);

  const toggleAllFilteredTasks = useCallback((checked: boolean) => {
    const filteredIds = filteredTasks.map((task) => task.task_id);
    setSelectedTaskIds((current) => {
      if (checked) {
        const next = new Set(current);
        for (const taskId of filteredIds) {
          next.add(taskId);
        }
        return Array.from(next);
      }
      const removals = new Set(filteredIds);
      return current.filter((taskId) => !removals.has(taskId));
    });
  }, [filteredTasks]);

  const filteredScripts = useMemo(() => {
    if (!scriptSearch) return Object.entries(BUILTIN_SCRIPTS);
    const q = scriptSearch.toLowerCase();
    return Object.entries(BUILTIN_SCRIPTS).filter(
      ([key, meta]) =>
        key.includes(q) ||
        meta.label.toLowerCase().includes(q) ||
        meta.description.toLowerCase().includes(q),
    );
  }, [scriptSearch]);

  const allFilteredTasksSelected = filteredTasks.length > 0 && filteredTasks.every((task) => selectedTaskIdSet.has(task.task_id));

  // ── Render helpers ──

  function statusBadge(status: string) {
    const variant =
      status === "online" || status === "completed"
        ? "default"
        : status === "offline" || status === "error" || status === "rejected"
          ? "destructive"
          : "secondary";
    return <Badge variant={variant} className="text-[10px] px-1.5 py-0">{status}</Badge>;
  }

  function formatTimestamp(ts: string) {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return ts;
    }
  }

  // ── Loading ──

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoaderCircle className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════════════════

  return (
    <TooltipProvider delayDuration={300}>
        <div className="flex flex-col flex-1 min-h-0">
        {/* ── Header Bar ── */}
        <div className="shrink-0 border-b border-border/60 bg-gradient-to-br from-background/95 via-background/90 to-muted/35 px-3 py-2.5 shadow-sm shadow-black/5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-foreground">Cluster intelligence</h2>
              <div className="flex items-center gap-1.5">
                <Badge variant="outline" className="border-border/60 bg-background/80 text-[10px] px-1.5 py-0">Read-only</Badge>
                <Badge variant="outline" className="border-border/60 bg-background/80 text-[10px] px-1.5 py-0">{collectors.length} collector{collectors.length === 1 ? "" : "s"}</Badge>
                <Badge variant="outline" className="border-border/60 bg-background/80 text-[10px] px-1.5 py-0">Auto-refresh 15s</Badge>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="h-7 bg-background/80 text-[11px] px-2"
              onClick={refresh}
              disabled={refreshing}
            >
              <RefreshCw className={cn("h-3 w-3 mr-1", refreshing && "animate-spin")} />
              Refresh
            </Button>
          </div>

          <div className="mt-1.5 grid grid-cols-2 gap-2 md:grid-cols-4">
            <Card className="gap-0 border-border/60 bg-background/80 py-1.5 shadow-sm shadow-black/5">
              <CardHeader className="px-2.5 pb-0.5 pt-0">
                <CardTitle className="text-[10px] font-medium text-muted-foreground flex items-center gap-1">
                  <Server className="h-3 w-3" /> Collectors
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2.5 pb-0">
                <div className="text-base font-bold">{collectors.length}</div>
                <p className="text-[10px] text-muted-foreground">
                  {collectors.length === 0 ? "none" : `${onlineCollectors} online`}
                </p>
              </CardContent>
            </Card>
            <Card className="gap-0 border-border/60 bg-background/80 py-1.5 shadow-sm shadow-black/5">
              <CardHeader className="px-2.5 pb-0.5 pt-0">
                <CardTitle className="text-[10px] font-medium text-muted-foreground flex items-center gap-1">
                  <Zap className="h-3 w-3" /> Tasks
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2.5 pb-0">
                <div className="text-base font-bold">{totalTasks}</div>
                <p className="text-[10px] text-muted-foreground">{completedTasks} succeeded</p>
              </CardContent>
            </Card>
            <Card className="gap-0 border-border/60 bg-background/80 py-1.5 shadow-sm shadow-black/5">
              <CardHeader className="px-2.5 pb-0.5 pt-0">
                <CardTitle className="text-[10px] font-medium text-muted-foreground flex items-center gap-1">
                  <FileCode2 className="h-3 w-3" /> Scripts
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2.5 pb-0">
                <div className="text-base font-bold">{Object.keys(BUILTIN_SCRIPTS).length}</div>
                <p className="text-[10px] text-muted-foreground">ready to use</p>
              </CardContent>
            </Card>
            <Card className="gap-0 border-border/60 bg-background/80 py-1.5 shadow-sm shadow-black/5">
              <CardHeader className="px-2.5 pb-0.5 pt-0">
                <CardTitle className="text-[10px] font-medium text-muted-foreground flex items-center gap-1">
                  <Activity className="h-3 w-3" /> Status
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2.5 pb-0">
                <div className="flex items-center gap-1">
                  <div className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    onlineCollectors === collectors.length && collectors.length > 0
                      ? "bg-emerald-500"
                      : collectors.length === 0
                        ? "bg-muted-foreground/30"
                        : "bg-amber-500",
                  )} />
                  <span className="text-base font-bold">
                    {onlineCollectors === collectors.length && collectors.length > 0
                      ? "Healthy"
                      : collectors.length === 0
                        ? "Setup"
                        : "Degraded"}
                  </span>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  {collectors.length === 0 ? "connect a cluster" : "all systems"}
                </p>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* ── Main Content ── */}
        <div className="flex-1 min-h-0 flex">
          {/* ── Left Panel: Resource Explorer ── */}
          <div className="w-64 shrink-0 border-r border-border/60 bg-background/55 flex flex-col">
            <div className="p-2.5 space-y-1.5 shrink-0">
              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 flex-1 bg-background/80 text-[11px]"
                  onClick={() => setShowCollectDialog(true)}
                  disabled={collectors.length === 0}
                >
                  <Play className="h-3 w-3 mr-1" /> Run Script
                </Button>
                {canMutate && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-8 bg-background/80 text-[11px]"
                    onClick={() => setShowRegisterDialog(true)}
                  >
                    <Plus className="h-3 w-3 mr-1" /> Connect
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-8 w-8 p-0"
                  onClick={refresh}
                  disabled={refreshing}
                >
                  <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
                </Button>
              </div>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search..."
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  className="h-8 bg-background/80 pl-7 text-xs"
                />
              </div>
            </div>

            <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)} className="flex-1 flex flex-col min-h-0">
              <TabsList className="mx-2.5 mt-0.5 h-auto shrink-0 w-auto rounded-2xl border border-border/60 bg-background/80 p-1">
                <TabsTrigger value="collectors" className="text-[11px] cursor-pointer">
                  Collectors ({collectors.length})
                </TabsTrigger>
                <TabsTrigger value="tasks" className="text-[11px] cursor-pointer">
                  Tasks ({tasks.length})
                </TabsTrigger>
              </TabsList>

              <ScrollArea className="flex-1 min-h-0">
                <TabsContent value="collectors" className="mt-0 p-2 space-y-1">
                  {filteredCollectors.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-background/70 px-3 py-5 text-center text-xs text-muted-foreground shadow-sm shadow-black/5">
                      {collectors.length === 0 ? (
                        <div className="space-y-2 px-2">
                          <div className="mx-auto w-10 h-10 rounded-lg border border-border/60 bg-muted/20 flex items-center justify-center">
                            <Server className="h-5 w-5 text-muted-foreground/40" />
                          </div>
                          <p className="font-medium">No clusters connected</p>
                          <p className="text-[10px] leading-relaxed">
                            Connect a cluster to run read-only scripts.
                          </p>
                          {canMutate && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-7 text-[11px] bg-background/80"
                              onClick={() => setShowRegisterDialog(true)}
                            >
                              <Plus className="h-3 w-3 mr-1" /> Connect
                            </Button>
                          )}
                        </div>
                      ) : (
                        "No matching collectors"
                      )}
                    </div>
                  ) : (
                    filteredCollectors.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => {
                          setSelectedCollector(c);
                          setSelectedTask(null);
                        }}
                        className={cn(
                          "w-full text-left rounded-xl border px-3 py-2.5 text-xs shadow-sm shadow-black/5 transition-colors",
                          "hover:bg-accent/35",
                          selectedCollector?.id === c.id
                            ? "border-primary/30 bg-primary/5"
                            : "border-border/60 bg-background/75",
                        )}
                      >
                        <div className="flex items-center justify-between mb-0.5">
                          <div className="flex items-center gap-1.5 truncate">
                            <div className={cn(
                              "h-1.5 w-1.5 rounded-full shrink-0",
                              c.status === "online" ? "bg-emerald-500" : "bg-red-400",
                            )} />
                            <span className="font-medium truncate">{c.name}</span>
                          </div>
                          {statusBadge(c.status)}
                        </div>
                        <div className="text-[10px] text-muted-foreground truncate pl-3">
                          {c.cluster} · {c.node || "unknown node"}
                        </div>
                      </button>
                    ))
                  )}
                </TabsContent>

                <TabsContent value="tasks" className="mt-0 p-2 space-y-1">
                  {canMutate && tasks.length > 0 && (
                    <div className="mb-2 flex items-center justify-between gap-2 rounded-xl border border-border/60 bg-background/70 px-2.5 py-2 text-[11px] shadow-sm shadow-black/5">
                      <label className="flex items-center gap-2 text-muted-foreground">
                        <input
                          type="checkbox"
                          checked={allFilteredTasksSelected}
                          disabled={filteredTasks.length === 0}
                          onChange={(e) => toggleAllFilteredTasks(e.target.checked)}
                          className="h-3.5 w-3.5 rounded border-input"
                        />
                        <span>Select all {searchFilter ? "matching" : "visible"}</span>
                      </label>
                      <div className="flex items-center gap-1.5">
                        <span className="text-muted-foreground">{selectedTaskIds.length} selected</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-[11px]"
                          onClick={() => setSelectedTaskIds([])}
                          disabled={selectedTaskIds.length === 0}
                        >
                          Clear
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-[11px] text-destructive hover:text-destructive"
                          onClick={() => promptDeleteTasks()}
                          disabled={selectedTaskIds.length === 0}
                        >
                          <Trash2 className="h-3 w-3 mr-1" /> Delete
                        </Button>
                      </div>
                    </div>
                  )}
                  {filteredTasks.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-border/70 bg-background/70 px-3 py-5 text-center text-xs text-muted-foreground shadow-sm shadow-black/5">
                      {tasks.length === 0 ? (
                        <div className="space-y-2 px-2">
                          <div className="mx-auto w-10 h-10 rounded-lg border border-border/60 bg-muted/20 flex items-center justify-center">
                            <Terminal className="h-5 w-5 text-muted-foreground/40" />
                          </div>
                          <p className="font-medium">No tasks yet</p>
                          <p className="text-[10px] leading-relaxed">
                            Run a script to see results here.
                          </p>
                        </div>
                      ) : (
                        "No matching tasks"
                      )}
                    </div>
                  ) : (
                    filteredTasks.map((t) => (
                      <div
                        key={t.task_id}
                        className={cn(
                          "flex items-start gap-2 rounded-xl border px-2.5 py-2.5 text-xs shadow-sm shadow-black/5 transition-colors",
                          selectedTask?.task_id === t.task_id || selectedTaskIdSet.has(t.task_id)
                            ? "border-primary/30 bg-primary/5"
                            : "border-border/60 bg-background/75 hover:bg-accent/35",
                        )}
                      >
                        {canMutate && (
                          <input
                            type="checkbox"
                            checked={selectedTaskIdSet.has(t.task_id)}
                            onChange={(e) => toggleTaskSelection(t.task_id, e.target.checked)}
                            onClick={(e) => e.stopPropagation()}
                            className="mt-0.5 h-3.5 w-3.5 rounded border-input shrink-0"
                            aria-label={`Select task ${t.task_id}`}
                          />
                        )}
                        <button
                          onClick={() => {
                            setSelectedTask(t);
                            setSelectedCollector(null);
                          }}
                          className="min-w-0 flex-1 text-left"
                        >
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="font-mono font-medium">{t.task_id}</span>
                            <Badge
                              variant={t.completed === t.total ? "default" : "secondary"}
                              className="text-[10px] px-1.5 py-0"
                            >
                              {t.completed}/{t.total}
                            </Badge>
                          </div>
                          <div className="text-[10px] text-muted-foreground flex items-center gap-1">
                            <span>{t.collector_id}</span>
                            <span>·</span>
                            <span>{t.payload.builtin ? String(t.payload.builtin) : "custom"}</span>
                            <span>·</span>
                            <span>{formatTimestamp(t.submitted_at)}</span>
                          </div>
                        </button>
                      </div>
                    ))
                  )}
                </TabsContent>
              </ScrollArea>
            </Tabs>
          </div>

          {/* ── Right Panel: Detail View ── */}
          <div className="flex-1 min-h-0 overflow-auto bg-gradient-to-b from-transparent to-muted/10">
            {!selectedCollector && !selectedTask ? (
              /* ── Empty State / Quick Actions ── */
              collectors.length === 0 ? (
                <div className="p-3">
                  <div className="max-w-lg w-full space-y-2">
                    <div className="flex items-center gap-2">
                      <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-border/60 bg-gradient-to-br from-primary/10 to-primary/5 shadow-sm shadow-black/5">
                        <Sparkles className="h-4 w-4 text-primary/60" />
                      </div>
                      <h2 className="text-sm font-semibold">Cluster Intelligence</h2>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Run read-only scripts on your clusters to collect health, security, and resource data.
                    </p>

                    <div className="space-y-2">
                      <h3 className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">Getting Started</h3>
                      <div className="space-y-1.5">
                        <div className="flex items-start gap-2 rounded-xl border border-border/60 bg-background/80 p-2.5 shadow-sm shadow-black/5">
                          <div className="h-5 w-5 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                            <span className="text-[10px] font-bold text-primary">1</span>
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium">Connect a Cluster</p>
                            <p className="text-[10px] text-muted-foreground mt-0.5 leading-snug">
                              Deploy the collector agent, then register its endpoint.
                            </p>
                          </div>
                          {canMutate && (
                            <Button size="sm" className="h-6 text-[11px] px-2 shrink-0" onClick={() => setShowRegisterDialog(true)}>
                              Connect <ArrowRight className="h-3 w-3 ml-1" />
                            </Button>
                          )}
                        </div>
                        <div className="flex items-start gap-2 rounded-xl border border-border/60 bg-background/70 p-2.5 shadow-sm shadow-black/5">
                          <div className="h-5 w-5 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                            <span className="text-[10px] font-bold text-muted-foreground">2</span>
                          </div>
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-muted-foreground">Run a Script</p>
                            <p className="text-[10px] text-muted-foreground mt-0.5 leading-snug">
                              Choose from {Object.keys(BUILTIN_SCRIPTS).length} built-in scripts or write custom queries.
                            </p>
                          </div>
                        </div>
                        <div className="flex items-start gap-2 rounded-xl border border-border/60 bg-background/70 p-2.5 shadow-sm shadow-black/5">
                          <div className="h-5 w-5 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                            <span className="text-[10px] font-bold text-muted-foreground">3</span>
                          </div>
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-muted-foreground">Set Up Schedules & Alerts</p>
                            <p className="text-[10px] text-muted-foreground mt-0.5 leading-snug">
                              Automate collection with cron schedules and trigger AI agents on anomalies.
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="rounded-xl border border-dashed border-border/70 bg-muted/15 p-2.5 shadow-sm shadow-black/5">
                      <div className="flex items-start gap-2 text-[11px] text-muted-foreground">
                        <Lock className="h-3 w-3 shrink-0 mt-0.5" />
                        <p className="leading-snug">
                          <span className="font-medium">Read-only by design.</span> All scripts are sandboxed — write operations are automatically blocked.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                /* ── Quick Run panel when collectors exist ── */
                <div className="p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold">Quick Run</h3>
                      <p className="text-[11px] text-muted-foreground mt-0.5">
                        Run on all {collectors.length} collector{collectors.length !== 1 ? "s" : ""}
                      </p>
                    </div>
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="outline" className="h-7 text-[11px] px-2" onClick={() => setShowCollectDialog(true)}>
                        <Code2 className="h-3 w-3 mr-1" /> Custom
                      </Button>
                    </div>
                  </div>
                  <Separator />
                  {(Object.entries(SCRIPT_CATEGORIES) as [ScriptCategory, { label: string; color: string }][]).map(([catKey, cat]) => {
                    const scripts = Object.entries(BUILTIN_SCRIPTS).filter(([, m]) => m.category === catKey);
                    if (scripts.length === 0) return null;
                    return (
                      <div key={catKey} className="space-y-1.5">
                        <h4 className={cn("text-[11px] font-medium uppercase tracking-wider", cat.color)}>{cat.label}</h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5">
                          {scripts.map(([key, meta]) => {
                            const Icon = meta.icon;
                            return (
                              <button
                                key={key}
                                onClick={() => handleQuickRun(key)}
                                disabled={collectRunning}
                                className="group flex items-center gap-2.5 rounded-xl border border-border/60 bg-background/80 p-2.5 text-left text-xs shadow-sm shadow-black/5 transition-all hover:-translate-y-0.5 hover:border-primary/20 hover:bg-accent/35 hover:shadow-md"
                              >
                                <div className="h-7 w-7 rounded-lg bg-muted/50 flex items-center justify-center shrink-0 group-hover:bg-primary/10 transition-colors">
                                  <Icon className="h-3.5 w-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
                                </div>
                                <div className="flex-1 min-w-0">
                                  <div className="font-medium">{meta.label}</div>
                                  <div className="text-[10px] text-muted-foreground truncate">{meta.description}</div>
                                </div>
                                <Play className="h-3 w-3 text-muted-foreground/0 group-hover:text-primary transition-colors shrink-0" />
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )
            ) : selectedCollector ? (
              <CollectorDetail
                collector={selectedCollector}
                canMutate={canMutate}
                onDelete={() => setDeleteTarget(selectedCollector)}
                onCollect={() => {
                  setCollectTarget(selectedCollector.id);
                  setShowCollectDialog(true);
                }}
              />
            ) : selectedTask ? (
              <TaskDetail
                task={selectedTask}
                canMutate={canMutate}
                onDelete={() => promptDeleteTasks(selectedTask.task_id)}
              />
            ) : null}
          </div>
        </div>

        {/* ── Register Collector Dialog (centered) ── */}
        <Dialog open={showRegisterDialog} onOpenChange={setShowRegisterDialog}>
          <DialogContent className="border-border/60 bg-background/95 shadow-2xl sm:max-w-[480px]">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-base">
                <Server className="h-4 w-4" />
                Connect Cluster
              </DialogTitle>
              <DialogDescription className="text-xs">
                Register a collector agent running on a Kubernetes cluster or VM.
                The collector executes read-only scripts and returns results.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3 py-2">
              {/* Name */}
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Name</Label>
                <Input
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  placeholder="e.g. production-us-east"
                  className="h-9 text-sm"
                  autoFocus
                />
                <p className="text-[11px] text-muted-foreground">
                  A friendly name to identify this cluster in the dashboard.
                </p>
              </div>

              {/* URL */}
              <div className="space-y-1.5">
                <Label className="text-xs font-medium flex items-center gap-1.5">
                  Collector Endpoint
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-[240px] text-xs">
                      The HTTP endpoint of the collector agent. For in-cluster collectors, use the
                      Kubernetes service DNS name.
                    </TooltipContent>
                  </Tooltip>
                </Label>
                <Input
                  value={regUrl}
                  onChange={(e) => setRegUrl(e.target.value)}
                  placeholder="http://collector-svc.namespace.svc:9100"
                  className="h-9 text-sm font-mono"
                />
                <p className="text-[11px] text-muted-foreground">
                  In-cluster: <code className="bg-muted px-1 py-0.5 rounded text-[10px]">http://&lt;service&gt;.&lt;namespace&gt;.svc:9100</code>
                  {" "}or external: <code className="bg-muted px-1 py-0.5 rounded text-[10px]">http://&lt;ip&gt;:9100</code>
                </p>
              </div>

              {/* Cluster Name */}
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Cluster Name</Label>
                <Input
                  value={regCluster}
                  onChange={(e) => setRegCluster(e.target.value)}
                  placeholder="e.g. production, staging, dev"
                  className="h-9 text-sm"
                />
              </div>

              {/* Advanced section (collapsible) */}
              <div className="border rounded-lg overflow-hidden">
                <button
                  type="button"
                  onClick={() => setRegShowAdvanced(!regShowAdvanced)}
                  className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-accent/50 transition-colors"
                >
                  <span className="flex items-center gap-1.5">
                    <Lock className="h-3 w-3" />
                    Authentication
                  </span>
                  <ChevronDown className={cn("h-3 w-3 transition-transform", regShowAdvanced && "rotate-180")} />
                </button>
                {regShowAdvanced && (
                  <div className="px-3 pb-3 space-y-2 border-t">
                    <div className="pt-2 space-y-1.5">
                      <Label className="text-xs font-medium flex items-center gap-1.5">
                        Bearer Token
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <HelpCircle className="h-3 w-3 text-muted-foreground cursor-help" />
                          </TooltipTrigger>
                          <TooltipContent side="right" className="max-w-[240px] text-xs">
                            The token the gateway sends to authenticate with the collector agent.
                            Must match the COLLECTOR_TOKEN env var on the collector.
                            Default: <code>collector-dev-token</code>
                          </TooltipContent>
                        </Tooltip>
                      </Label>
                      <div className="relative">
                        <Input
                          value={regToken}
                          onChange={(e) => setRegToken(e.target.value)}
                          type={regShowToken ? "text" : "password"}
                          className="h-9 text-sm font-mono pr-16"
                        />
                        <div className="absolute right-1 top-1/2 -translate-y-1/2 flex gap-0.5">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-6 w-6 p-0"
                            onClick={() => setRegShowToken(!regShowToken)}
                          >
                            {regShowToken ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-6 w-6 p-0"
                            onClick={() => {
                              navigator.clipboard.writeText(regToken);
                              toast.success("Token copied");
                            }}
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        Pre-filled with the default dev token. Change this for production collectors.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <DialogFooter className="gap-2 sm:gap-0">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowRegisterDialog(false)}
                className="text-xs"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleRegister}
                disabled={regSaving || !regName.trim() || !regUrl.trim()}
                className="text-xs"
              >
                {regSaving ? (
                  <LoaderCircle className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Plus className="h-3 w-3 mr-1" />
                )}
                Connect Cluster
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* ── Run Script Dialog (centered) ── */}
        <Dialog open={showCollectDialog} onOpenChange={setShowCollectDialog}>
          <DialogContent className="flex max-h-[85vh] flex-col border-border/60 bg-background/95 shadow-2xl sm:max-w-[560px]">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-base">
                <Terminal className="h-4 w-4" />
                Run Script
              </DialogTitle>
              <DialogDescription className="text-xs">
                Execute a read-only script on your connected clusters. All write operations are blocked.
              </DialogDescription>
            </DialogHeader>

            <div className="flex-1 min-h-0 overflow-y-auto space-y-3 py-2 pr-1">
              {/* Target */}
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Target</Label>
                <Select value={collectTarget} onValueChange={setCollectTarget}>
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all" className="text-xs">
                      All Collectors ({collectors.length})
                    </SelectItem>
                    {collectors.map((c) => (
                      <SelectItem key={c.id} value={c.id} className="text-xs">
                        <span className="flex items-center gap-1.5">
                          <span className={cn(
                            "h-1.5 w-1.5 rounded-full inline-block",
                            c.status === "online" ? "bg-emerald-500" : "bg-red-400",
                          )} />
                          {c.name}
                          <span className="text-muted-foreground">({c.cluster})</span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Mode tabs */}
              <Tabs value={collectMode} onValueChange={(v) => setCollectMode(v as typeof collectMode)}>
                <TabsList className="w-full">
                  <TabsTrigger value="builtin" className="flex-1 text-xs cursor-pointer">
                    <FileCode2 className="h-3 w-3 mr-1" /> Built-in Scripts
                  </TabsTrigger>
                  <TabsTrigger value="custom" className="flex-1 text-xs cursor-pointer">
                    <Code2 className="h-3 w-3 mr-1" /> Custom Script
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="builtin" className="mt-2 space-y-2">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      placeholder="Search scripts..."
                      value={scriptSearch}
                      onChange={(e) => setScriptSearch(e.target.value)}
                      className="h-8 text-xs pl-8"
                    />
                  </div>
                  <ScrollArea className="max-h-[280px]">
                    <div className="grid grid-cols-1 gap-2 pr-2 sm:grid-cols-2">
                      {filteredScripts.map(([key, meta]) => {
                        const Icon = meta.icon;
                        const cat = SCRIPT_CATEGORIES[meta.category];
                        return (
                          <button
                            key={key}
                            onClick={() => setCollectBuiltin(key)}
                            className={cn(
                              "flex items-start gap-2 p-2.5 rounded-lg border text-left text-xs transition-all",
                              collectBuiltin === key
                                ? "border-primary/40 bg-primary/5 shadow-sm"
                                : "border-border hover:bg-accent/50 hover:border-primary/20",
                            )}
                          >
                            <div className={cn(
                              "h-7 w-7 rounded-md flex items-center justify-center shrink-0",
                              collectBuiltin === key ? "bg-primary/10" : "bg-muted/50",
                            )}>
                              <Icon className={cn(
                                "h-3.5 w-3.5",
                                collectBuiltin === key ? "text-primary" : "text-muted-foreground",
                              )} />
                            </div>
                            <div className="min-w-0">
                              <div className="font-medium leading-tight">{meta.label}</div>
                              <div className="text-[10px] text-muted-foreground mt-0.5 leading-snug">{meta.description}</div>
                              <Badge variant="outline" className={cn("text-[9px] px-1 py-0 mt-1", cat.color)}>
                                {cat.label}
                              </Badge>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </ScrollArea>
                </TabsContent>

                <TabsContent value="custom" className="mt-2 space-y-2">
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">Language</Label>
                    <Select value={collectScriptType} onValueChange={(v) => setCollectScriptType(v as typeof collectScriptType)}>
                      <SelectTrigger className="h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="bash" className="text-xs">Bash</SelectItem>
                        <SelectItem value="python" className="text-xs">Python</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-medium">Script</Label>
                    <Textarea
                      value={collectScript}
                      onChange={(e) => setCollectScript(e.target.value)}
                      placeholder={collectScriptType === "bash"
                        ? "kubectl get pods -A -o wide\n# Read-only commands only"
                        : "import subprocess\nresult = subprocess.run(['kubectl', 'get', 'pods', '-A'], capture_output=True, text=True)\nprint(result.stdout)"
                      }
                      className="font-mono text-xs min-h-[140px] resize-y"
                    />
                    <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                      <Lock className="h-3 w-3" />
                      Write operations (delete, apply, rm, exec) are automatically blocked.
                    </div>
                  </div>
                </TabsContent>
              </Tabs>

              {/* Timeout */}
              <div className="space-y-1.5">
                <Label className="text-xs font-medium">Timeout</Label>
                <div className="flex items-center gap-2">
                  <Input
                    type="number"
                    min={5}
                    max={60}
                    value={collectTimeout}
                    onChange={(e) => setCollectTimeout(Number(e.target.value))}
                    className="h-9 text-sm w-20"
                  />
                  <span className="text-xs text-muted-foreground">seconds (max 60)</span>
                </div>
              </div>
            </div>

            <DialogFooter className="gap-2 sm:gap-0 pt-2 border-t">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowCollectDialog(false)}
                className="text-xs"
              >
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleCollect}
                disabled={collectRunning || (collectMode === "custom" && !collectScript.trim())}
                className="text-xs"
              >
                {collectRunning ? (
                  <LoaderCircle className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Play className="h-3 w-3 mr-1" />
                )}
                Run Script
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* ── Delete Confirm ── */}
        <ConfirmDialog
          open={!!deleteTarget}
          onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
          title={`Disconnect "${deleteTarget?.name}"?`}
          description="This collector will be removed from the registry. You can reconnect it later."
          confirmLabel="Disconnect"
          variant="destructive"
          onConfirm={handleUnregister}
        />

        <ConfirmDialog
          open={showDeleteTasksDialog}
          onOpenChange={setShowDeleteTasksDialog}
          title={selectedTaskIds.length === 1 ? `Delete task ${selectedTaskIds[0]}?` : `Delete ${selectedTaskIds.length} task runs?`}
          description={selectedTaskIds.length === 1
            ? "This removes the saved script run from the dashboard and from the auto-injected intelligence context cache."
            : "This removes the selected script runs from the dashboard and from the auto-injected intelligence context cache."
          }
          confirmLabel={selectedTaskIds.length === 1 ? "Delete task" : "Delete selected"}
          variant="destructive"
          onConfirm={handleDeleteTasks}
        />
      </div>
    </TooltipProvider>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Collector Detail Sub-component
// ═════════════════════════════════════════════════════════════════════════════

function CollectorDetail({
  collector,
  canMutate,
  onDelete,
  onCollect,
}: {
  collector: IntelligenceCollector;
  canMutate: boolean;
  onDelete: () => void;
  onCollect: () => void;
}) {
  return (
    <div className="p-2.5 space-y-2.5">
      {/* Header */}
      <div className="flex items-start justify-between rounded-xl border border-border/60 bg-background/80 p-3 shadow-sm shadow-black/5">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Server className="h-4 w-4" />
            {collector.name}
            {collector.status === "online" ? (
              <Badge className="text-[10px] px-1.5 py-0 bg-emerald-500/10 text-emerald-600 border-emerald-500/20">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 mr-1" />
                online
              </Badge>
            ) : collector.status === "offline" ? (
              <Badge variant="destructive" className="text-[10px] px-1.5 py-0">offline</Badge>
            ) : (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{collector.status}</Badge>
            )}
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {collector.cluster} · {collector.node || "unknown"} · v{collector.version || "?"}
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onCollect}>
            <Play className="h-3 w-3 mr-1" /> Run Script
          </Button>
          {canMutate && (
            <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-destructive" onClick={onDelete}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      <Separator />

      {/* Info Grid */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <InfoCard label="Endpoint" value={collector.url} mono />
        <InfoCard label="Cluster" value={collector.cluster || "unknown"} />
        <InfoCard label="Node" value={collector.node || "unknown"} />
        <InfoCard label="Registered" value={collector.registered_at ? new Date(collector.registered_at).toLocaleString() : "—"} />
        <InfoCard label="Version" value={collector.version || "unknown"} />
        <InfoCard label="Max Timeout" value={collector.max_timeout ? `${collector.max_timeout}s` : "—"} />
      </div>

      {/* Capabilities */}
      {collector.capabilities && collector.capabilities.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Capabilities</h4>
          <div className="flex flex-wrap gap-1">
            {collector.capabilities.map((cap) => (
              <Badge key={cap} variant="outline" className="text-[10px]">{cap}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Built-in Scripts */}
      {collector.builtin_scripts && collector.builtin_scripts.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Built-in Scripts</h4>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {collector.builtin_scripts.map((s) => {
              const meta = BUILTIN_SCRIPTS[s];
              const Icon = meta?.icon || FileCode2;
              return (
                <div key={s} className="flex items-center gap-2 rounded-xl border border-border/60 bg-background/75 p-2 text-xs shadow-sm shadow-black/5">
                  <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <div>
                    <div className="font-medium">{meta?.label || s}</div>
                    {meta && <div className="text-[10px] text-muted-foreground">{meta.description}</div>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Error */}
      {collector.error && (
        <div className="p-2 rounded-md bg-destructive/5 border border-destructive/20 text-xs text-destructive">
          <AlertTriangle className="h-3.5 w-3.5 inline mr-1" />
          {collector.error}
        </div>
      )}

      {/* Tags */}
      {collector.tags && collector.tags.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-medium text-muted-foreground">Tags</h4>
          <div className="flex flex-wrap gap-1">
            {collector.tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="text-[10px]">{tag}</Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Task Detail Sub-component
// ═════════════════════════════════════════════════════════════════════════════

function TaskDetail({
  task,
  canMutate,
  onDelete,
}: {
  task: CollectionTask;
  canMutate: boolean;
  onDelete: () => void;
}) {
  const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set());

  const toggleResult = (key: string) => {
    setExpandedResults((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Auto-expand if there's only one result
  useEffect(() => {
    const keys = Object.keys(task.results);
    if (keys.length === 1) {
      setExpandedResults(new Set(keys));
    }
  }, [task.task_id]);

  const payloadBuiltin = task.payload.builtin as string | undefined;
  const payloadScript = task.payload.script as string | undefined;
  const payloadTimeout = task.payload.timeout as number | undefined;

  return (
    <div className="p-2.5 space-y-2.5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 rounded-xl border border-border/60 bg-background/80 p-3 shadow-sm shadow-black/5">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Terminal className="h-4 w-4" />
            Task {task.task_id}
            <Badge
              variant={task.completed === task.total ? "default" : "secondary"}
              className="text-[10px] px-1.5 py-0"
            >
              {task.completed}/{task.total} succeeded
            </Badge>
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {task.collector_id === "all" ? "All collectors" : task.collector_id}
            {" · "}
            {payloadBuiltin ? `Built-in: ${payloadBuiltin}` : "Custom script"}
            {" · "}
            {new Date(task.submitted_at).toLocaleString()}
          </p>
        </div>
        {canMutate && (
          <Button size="sm" variant="ghost" className="h-7 text-xs text-destructive hover:text-destructive" onClick={onDelete}>
            <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
          </Button>
        )}
      </div>

      <Separator />

      {/* Task Info */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <InfoCard label="Submitted by" value={task.submitted_by} />
        <InfoCard label="Target" value={task.collector_id} />
        <InfoCard label="Timeout" value={payloadTimeout != null ? `${payloadTimeout}s` : "—"} />
      </div>

      {/* Script payload */}
      {payloadScript && (
        <div className="space-y-1">
          <h4 className="text-xs font-medium text-muted-foreground">Script</h4>
          <pre className="max-h-32 overflow-x-auto overflow-y-auto rounded-xl border border-border/60 bg-background/80 p-2.5 text-[11px] font-mono whitespace-pre-wrap shadow-sm shadow-black/5">
            {payloadScript}
          </pre>
        </div>
      )}

      {/* Results per collector */}
      <div className="space-y-1.5">
        <h4 className="text-xs font-medium text-muted-foreground">
          Results ({Object.keys(task.results).length})
        </h4>
        {Object.entries(task.results).map(([collectorId, result]) => (
          <ResultCard
            key={collectorId}
            collectorId={collectorId}
            result={result}
            expanded={expandedResults.has(collectorId)}
            onToggle={() => toggleResult(collectorId)}
          />
        ))}
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Result Card sub-component
// ═════════════════════════════════════════════════════════════════════════════

function ResultCard({
  collectorId,
  result,
  expanded,
  onToggle,
}: {
  collectorId: string;
  result: CollectionTaskResult;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-background/80 shadow-sm shadow-black/5">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs hover:bg-accent/50 transition-colors"
      >
        <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")} />
        {result.status === "completed" ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
        ) : result.status === "timeout" ? (
          <Clock className="h-3.5 w-3.5 text-amber-500" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-red-500" />
        )}
        <span className="font-medium">{collectorId}</span>
        <Badge
          variant={result.status === "completed" ? "default" : result.status === "timeout" ? "secondary" : "destructive"}
          className="text-[10px] px-1.5 py-0 ml-auto"
        >
          {result.status}
        </Badge>
        {result.duration_ms != null && (
          <span className="text-[10px] text-muted-foreground">{result.duration_ms}ms</span>
        )}
      </button>
      {expanded && (
        <div className="border-t px-2.5 py-1.5 space-y-1.5">
          {/* Meta row */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
            {result.node && <span>Node: {result.node}</span>}
            {result.cluster && <span>Cluster: {result.cluster}</span>}
            {result.exit_code != null && <span>Exit: {result.exit_code}</span>}
            {result.timestamp && <span>{new Date(result.timestamp).toLocaleTimeString()}</span>}
          </div>

          {/* Error */}
          {result.error && (
            <div className="p-1.5 rounded-md bg-destructive/5 border border-destructive/20 text-[11px] text-destructive font-mono whitespace-pre-wrap">
              {result.error}
            </div>
          )}

          {/* Stdout */}
          {result.stdout && (
            <div className="space-y-0.5">
              <div className="text-[10px] font-medium text-muted-foreground">stdout</div>
              <pre className="p-1.5 rounded-md bg-muted/50 border text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-96 overflow-y-auto">
                {result.stdout}
              </pre>
            </div>
          )}

          {/* Stderr */}
          {result.stderr && result.stderr.trim() && (
            <div className="space-y-0.5">
              <div className="text-[10px] font-medium text-muted-foreground">stderr</div>
              <pre className="p-1.5 rounded-md bg-amber-500/5 border border-amber-500/20 text-[11px] font-mono whitespace-pre-wrap overflow-x-auto max-h-32 overflow-y-auto">
                {result.stderr}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════════════
// Info Card helper
// ═════════════════════════════════════════════════════════════════════════════

function InfoCard({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-border/60 bg-background/80 p-2.5 shadow-sm shadow-black/5">
      <div className="mb-1 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</div>
      <div className={cn("text-xs font-medium text-foreground", mono ? "font-mono break-all" : "break-words")}>{value}</div>
    </div>
  );
}
