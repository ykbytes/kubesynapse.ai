import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Webhook,
  Search,
  Plus,
  Trash2,
  Save,
  Copy,
  Check,
  Clock,
  Shield,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Key,
  Globe,
  Activity,
  AlertCircle,
  SkipForward,
  Zap,
  Github,
  MessageSquare,
  CreditCard,
  Radio,
  BarChart3,
  Skull,
} from "lucide-react";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  listWebhooks,
  createWebhook,
  updateWebhook,
  deleteWebhook,
  fetchWebhookHistory,
  generateWebhookSecret,
  fetchDeadLetterExecutions,
  replayDeadLetter,
  apiErrorMessage,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ConfirmDialog } from "../shared/ConfirmDialog";
import { EmptyState } from "../shared/EmptyState";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import type { WebhookReceiverInfo, WebhookInvocationInfo, WebhookProvider, TriggerExecutionInfo } from "../../types";

const PROVIDERS: { value: WebhookProvider; label: string; icon: typeof Globe; color: string }[] = [
  { value: "generic", label: "Generic", icon: Globe, color: "text-muted-foreground" },
  { value: "github", label: "GitHub", icon: Github, color: "text-foreground" },
  { value: "slack", label: "Slack", icon: MessageSquare, color: "text-[#4A154B]" },
  { value: "stripe", label: "Stripe", icon: CreditCard, color: "text-[#635BFF]" },
  { value: "pagerduty", label: "PagerDuty", icon: Radio, color: "text-[#06AC38]" },
  { value: "grafana", label: "Grafana", icon: BarChart3, color: "text-[#F46800]" },
];

const PROVIDER_HEADERS: Record<WebhookProvider, { header: string; example: string }> = {
  generic: { header: "X-kubesynapse-Signature", example: "sha256=..." },
  github: { header: "X-Hub-Signature-256", example: "sha256=..." },
  slack: { header: "X-Slack-Signature", example: "v0=a2114d57b48e89caf8d12..." },
  stripe: { header: "Stripe-Signature", example: "v1=..." },
  pagerduty: { header: "X-PD-Signature", example: "v1=..." },
  grafana: { header: "X-Grafana-Signature", example: "sha256=..." },
};

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45",
        checked ? "bg-primary" : "bg-muted-foreground/30"
      )}
      aria-label={label}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform duration-200",
          checked ? "translate-x-[18px]" : "translate-x-[2px]"
        )}
      />
    </button>
  );
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
}

function relativeTime(dateStr: string | null): string {
  if (!dateStr) return "never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function WebhookManager() {
  const { token, namespace, canMutate } = useConnection();

  const [webhooks, setWebhooks] = useState<WebhookReceiverInfo[]>([]);
  const [selectedWebhook, setSelectedWebhook] = useState<WebhookReceiverInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [history, setHistory] = useState<WebhookInvocationInfo[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [expandedPayloadId, setExpandedPayloadId] = useState<number | null>(null);
  const [detailTab, setDetailTab] = useState("overview");

  // Dead-letter
  const [deadLetter, setDeadLetter] = useState<TriggerExecutionInfo[]>([]);
  const [deadLetterLoading, setDeadLetterLoading] = useState(false);
  const [replayingId, setReplayingId] = useState<number | null>(null);

  // Secret generation
  const [generatedSecret, setGeneratedSecret] = useState<{ secret: string; key_id: string } | null>(null);
  const [generatingSecret, setGeneratingSecret] = useState(false);

  // Form state
  const [formName, setFormName] = useState("");
  const [formSecretRef, setFormSecretRef] = useState("");
  const [formIpAllowlist, setFormIpAllowlist] = useState("");
  const [formRateLimit, setFormRateLimit] = useState(60);
  const [formMaxPayload, setFormMaxPayload] = useState(1048576);
  const [formEnabled, setFormEnabled] = useState(true);
  const [formProvider, setFormProvider] = useState<WebhookProvider>("generic");
  const [formApiKeyEnabled, setFormApiKeyEnabled] = useState(false);

  const loadWebhooks = useCallback(async () => {
    if (!token || !namespace) return;
    setLoading(true);
    setError("");
    try {
      const data = await listWebhooks(token, namespace);
      setWebhooks(data);
      if (selectedWebhook && !data.find((w) => w.name === selectedWebhook.name)) {
        setSelectedWebhook(null);
        setIsCreating(false);
      }
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [token, namespace, selectedWebhook]);

  useEffect(() => {
    void loadWebhooks();
  }, [loadWebhooks]);

  useEffect(() => {
    if (!token || !namespace || !selectedWebhook) {
      setHistory([]);
      return;
    }
    let cancelled = false;
    setHistoryLoading(true);
    fetchWebhookHistory(token, namespace, selectedWebhook.name)
      .then((data) => { if (!cancelled) setHistory(data); })
      .catch(() => { if (!cancelled) setHistory([]); })
      .finally(() => { if (!cancelled) setHistoryLoading(false); });
    return () => { cancelled = true; };
  }, [token, namespace, selectedWebhook?.name]);

  useEffect(() => {
    if (!token || !namespace || !selectedWebhook || detailTab !== "dead-letter") {
      setDeadLetter([]);
      return;
    }
    let cancelled = false;
    setDeadLetterLoading(true);
    fetchDeadLetterExecutions(token, namespace, selectedWebhook.name)
      .then((data) => { if (!cancelled) setDeadLetter(data); })
      .catch(() => { if (!cancelled) setDeadLetter([]); })
      .finally(() => { if (!cancelled) setDeadLetterLoading(false); });
    return () => { cancelled = true; };
  }, [token, namespace, selectedWebhook?.name, detailTab]);

  useEffect(() => {
    if (selectedWebhook) {
      setFormName(selectedWebhook.name);
      setFormSecretRef(selectedWebhook.secret_ref);
      setFormIpAllowlist(selectedWebhook.ip_allowlist.join("\n"));
      setFormRateLimit(selectedWebhook.rate_limit);
      setFormMaxPayload(selectedWebhook.max_payload_bytes);
      setFormEnabled(selectedWebhook.enabled);
      setFormProvider(selectedWebhook.provider || "generic");
      setFormApiKeyEnabled(selectedWebhook.api_key_enabled);
      setIsCreating(false);
    } else if (isCreating) {
      setFormName("");
      setFormSecretRef("");
      setFormIpAllowlist("");
      setFormRateLimit(60);
      setFormMaxPayload(1048576);
      setFormEnabled(true);
      setFormProvider("generic");
      setFormApiKeyEnabled(false);
      setGeneratedSecret(null);
    }
  }, [selectedWebhook, isCreating]);

  const filteredWebhooks = useMemo(() => {
    if (!search.trim()) return webhooks;
    const lower = search.toLowerCase();
    return webhooks.filter(
      (w) => w.name.toLowerCase().includes(lower) || w.namespace.toLowerCase().includes(lower) || w.provider?.toLowerCase().includes(lower)
    );
  }, [webhooks, search]);

  const totalInvocations = useMemo(() => history.length, [history]);
  const recentFailures = useMemo(() => history.filter((h) => h.status === "failed" || h.status === "error").length, [history]);
  const lastInvocation = useMemo(() => history.length > 0 ? history[0].received_at : null, [history]);
  const latestInvocation = useMemo(() => history.length > 0 ? history[0] : null, [history]);

  const handleSelectWebhook = useCallback((webhook: WebhookReceiverInfo) => {
    setSelectedWebhook(webhook);
    setIsCreating(false);
    setError("");
    setDetailTab("overview");
    setGeneratedSecret(null);
  }, []);

  const handleCreateNew = useCallback(() => {
    setSelectedWebhook(null);
    setIsCreating(true);
    setError("");
    setGeneratedSecret(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (!token || !namespace) return;
    const name = formName.trim();
    if (!name) { setError("Webhook name is required."); return; }
    if (!formSecretRef.trim()) { setError("Secret reference is required."); return; }
    setSaving(true);
    setError("");
    try {
      const payload = {
        name,
        secret_ref: formSecretRef.trim(),
        ip_allowlist: formIpAllowlist.split("\n").map((s) => s.trim()).filter(Boolean),
        rate_limit: Math.max(0, formRateLimit),
        max_payload_bytes: Math.max(0, formMaxPayload),
        enabled: formEnabled,
        provider: formProvider,
        api_key_enabled: formApiKeyEnabled,
      };
      if (isCreating) {
        const created = await createWebhook(token, namespace, payload);
        setWebhooks((prev) => [...prev, created]);
        setSelectedWebhook(created);
        setIsCreating(false);
        toast.success("Webhook created");
      } else if (selectedWebhook) {
        const updated = await updateWebhook(token, namespace, selectedWebhook.name, payload);
        setWebhooks((prev) => prev.map((w) => (w.name === selectedWebhook.name ? updated : w)));
        setSelectedWebhook(updated);
        toast.success("Webhook saved");
      }
    } catch (err) {
      const msg = apiErrorMessage(err);
      setError(msg);
      toast.error("Failed to save webhook", { description: msg });
    } finally {
      setSaving(false);
    }
  }, [token, namespace, formName, formSecretRef, formIpAllowlist, formRateLimit, formMaxPayload, formEnabled, formProvider, formApiKeyEnabled, isCreating, selectedWebhook]);

  const handleDelete = useCallback(async () => {
    if (!token || !namespace || !selectedWebhook) return;
    setDeleting(true);
    setError("");
    try {
      await deleteWebhook(token, namespace, selectedWebhook.name);
      setWebhooks((prev) => prev.filter((w) => w.name !== selectedWebhook.name));
      setSelectedWebhook(null);
      setDeleteDialogOpen(false);
      toast.success("Webhook deleted");
    } catch (err) {
      setError(apiErrorMessage(err));
      toast.error("Failed to delete webhook", { description: apiErrorMessage(err) });
    } finally {
      setDeleting(false);
    }
  }, [token, namespace, selectedWebhook]);

  const handleGenerateSecret = useCallback(async () => {
    if (!token || !namespace || !selectedWebhook) return;
    setGeneratingSecret(true);
    try {
      const result = await generateWebhookSecret(token, namespace, selectedWebhook.name);
      setGeneratedSecret(result);
      toast.success("New webhook secret generated");
    } catch (err) {
      toast.error("Failed to generate secret", { description: apiErrorMessage(err) });
    } finally {
      setGeneratingSecret(false);
    }
  }, [token, namespace, selectedWebhook]);

  const handleReplay = useCallback(async (executionId: number) => {
    if (!token || !namespace) return;
    setReplayingId(executionId);
    try {
      await replayDeadLetter(token, namespace, executionId);
      setDeadLetter((prev) => prev.filter((e) => e.id !== executionId));
      toast.success("Execution re-queued for replay");
    } catch (err) {
      toast.error("Failed to replay execution", { description: apiErrorMessage(err) });
    } finally {
      setReplayingId(null);
    }
  }, [token, namespace]);

  const gatewayUrl = typeof window !== "undefined" ? window.location.origin : "";
  const provider = selectedWebhook?.provider || "generic";
  const providerInfo = PROVIDERS.find((p) => p.value === provider) || PROVIDERS[0];
  const sigHeader = PROVIDER_HEADERS[provider];
  const webhookUrl = selectedWebhook
    ? `${gatewayUrl}/api/v1/webhooks/${encodeURIComponent(selectedWebhook.name)}/invoke?namespace=${encodeURIComponent(selectedWebhook.namespace)}`
    : "";
  const curlExample = provider === "github"
    ? `curl -X POST "${webhookUrl}" \\\n  -H "Content-Type: application/json" \\\n  -H "X-GitHub-Event: push" \\\n  -H "${sigHeader.header}: <signature>" \\\n  -d '{"action":"opened","issue":{"id":1}}'`
    : provider === "slack"
      ? `curl -X POST "${webhookUrl}" \\\n  -H "Content-Type: application/json" \\\n  -H "${sigHeader.header}: v0=<computed>" \\\n  -d '{"event":{"type":"message","text":"hello","channel":"C123"}}'`
      : provider === "stripe"
        ? `curl -X POST "${webhookUrl}" \\\n  -H "Content-Type: application/json" \\\n  -H "${sigHeader.header}: v1=<signature>" \\\n  -d '{"type":"payment_intent.succeeded","data":{"object":{"id":"pi_123"}}}'`
        : `curl -X POST "${webhookUrl}" \\\n  -H "Content-Type: application/json" \\\n  -H "${sigHeader.header}: <signature>" \\\n  -d '{"key":"value"}'`;

  const canSubmit = Boolean(formName.trim()) && Boolean(formSecretRef.trim());

  const ProviderIcon = providerInfo.icon;

  return (
    <div className="grid h-full gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
      {/* ── Left column: webhook list ── */}
      <div className="flex min-h-0 flex-col gap-3">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search webhooks..."
              className="h-9 pl-8 text-xs"
              aria-label="Search webhooks"
            />
          </div>
          {canMutate && (
            <Button size="sm" className="h-9 gap-1.5 text-xs" onClick={handleCreateNew}>
              <Plus className="h-3.5 w-3.5" />
              New
            </Button>
          )}
        </div>
        <ScrollArea className="flex-1 rounded-[1.75rem] border border-border/70 bg-card/55">
          <div className="space-y-1 p-2">
            {loading && webhooks.length === 0 && (
              <>
                {[0, 1, 2].map((i) => (
                  <div key={i} className="space-y-2 rounded-xl px-3 py-2.5">
                    <Skeleton className="h-3.5 w-3/4 rounded" />
                    <Skeleton className="h-3 w-1/2 rounded" />
                  </div>
                ))}
              </>
            )}
            {!loading && filteredWebhooks.length === 0 && (
              <EmptyState
                icon={Webhook}
                title={search.trim() ? "No matches" : "No webhooks"}
                description={search.trim() ? `No webhooks match "${search}"` : "Create a webhook receiver to start accepting external events."}
                action={!search.trim() && canMutate ? { label: "Create Webhook", onClick: handleCreateNew } : undefined}
                className="py-8"
              />
            )}
            {filteredWebhooks.map((webhook) => {
              const isSelected = selectedWebhook?.name === webhook.name;
              const whProvider = PROVIDERS.find((p) => p.value === (webhook.provider || "generic")) || PROVIDERS[0];
              return (
                <button
                  key={webhook.name}
                  onClick={() => handleSelectWebhook(webhook)}
                  className={cn(
                    "flex w-full flex-col gap-1 rounded-[calc(var(--radius-lg)+2px)] border px-3 py-2.5 text-left transition-all duration-150 ease-productive",
                    isSelected
                      ? "border-border bg-card/90 shadow-sm"
                      : "border-transparent hover:border-border/60 hover:bg-card/70"
                  )}
                  aria-label={`${webhook.name} webhook`}
                  aria-pressed={isSelected}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0 flex-1">
                      <whProvider.icon className={cn("h-3 w-3 shrink-0", whProvider.color)} />
                      <span className="truncate text-[12.5px] font-medium text-foreground">
                        {webhook.name}
                      </span>
                    </div>
                    <Badge variant={webhook.enabled ? "default" : "secondary"} className="text-[10px] shrink-0">
                      {webhook.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="truncate">{webhook.namespace}</span>
                    <span className="text-border">·</span>
                    <span>{webhook.rate_limit}/min</span>
                    {webhook.failure_count > 0 && (
                      <>
                        <span className="text-border">·</span>
                        <span className="text-destructive">{webhook.failure_count} failed</span>
                      </>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </ScrollArea>
      </div>

      {/* ── Right column: detail/editor ── */}
      <div className="flex min-h-0 flex-col gap-4">
        {(selectedWebhook || isCreating) ? (
          <>
            {/* ── Health summary bar ── */}
            {!isCreating && selectedWebhook && (
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-xl border border-border/70 bg-card/55 px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Activity className="h-3 w-3" />
                    Invocations
                  </div>
                  <div className="mt-0.5 text-lg font-semibold text-foreground">{totalInvocations}</div>
                </div>
                <div className="rounded-xl border border-border/70 bg-card/55 px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <AlertCircle className={cn("h-3 w-3", recentFailures > 0 ? "text-destructive" : "")} />
                    Failures
                  </div>
                  <div className={cn("mt-0.5 text-lg font-semibold", recentFailures > 0 ? "text-destructive" : "text-foreground")}>
                    {recentFailures}
                  </div>
                </div>
                <div className="rounded-xl border border-border/70 bg-card/55 px-3 py-2.5">
                  <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    Last Invoked
                  </div>
                  <div className="mt-0.5 text-lg font-semibold text-foreground">{relativeTime(lastInvocation)}</div>
                </div>
              </div>
            )}

            {/* ── Editor card ── */}
            <Card className="border-border/70 bg-card/55">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {!isCreating && selectedWebhook && (
                        <ProviderIcon className={cn("h-4 w-4", providerInfo.color)} />
                      )}
                      <CardTitle className="text-base font-semibold">
                        {isCreating ? "New Webhook" : selectedWebhook?.name}
                      </CardTitle>
                      {!isCreating && selectedWebhook && (
                        <Badge variant={selectedWebhook.provider === "generic" ? "secondary" : "default"} className="text-[10px]">
                          {selectedWebhook.provider || "generic"}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {isCreating ? "Configure a new webhook receiver." : `Updated ${formatDate(selectedWebhook?.updated_at ?? "")}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {canMutate && !isCreating && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 gap-1.5 text-xs text-destructive hover:bg-destructive/10"
                        onClick={() => setDeleteDialogOpen(true)}
                        disabled={deleting}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </Button>
                    )}
                    <Button size="sm" className="h-8 gap-1.5 text-xs" onClick={handleSave} disabled={saving || !canSubmit}>
                      <Save className="h-3.5 w-3.5" />
                      {saving ? "Saving..." : "Save"}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {error && (
                  <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive" role="alert">
                    {error}
                  </div>
                )}

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="wh-name">Name</Label>
                    <Input id="wh-name" value={formName} onChange={(e) => setFormName(e.target.value)} disabled={!canMutate || !isCreating} placeholder="my-webhook" className="h-9 text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="wh-secret">Secret Reference</Label>
                    <Input id="wh-secret" value={formSecretRef} onChange={(e) => setFormSecretRef(e.target.value)} disabled={!canMutate} placeholder="namespace/secret-name#key" className="h-9 text-sm" />
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="wh-provider">Provider</Label>
                    <Select value={formProvider} onValueChange={(v) => setFormProvider(v as WebhookProvider)} disabled={!canMutate}>
                      <SelectTrigger id="wh-provider" className="h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PROVIDERS.map((p) => (
                          <SelectItem key={p.value} value={p.value}>
                            <span className="flex items-center gap-2">
                              <p.icon className="h-3.5 w-3.5" />
                              {p.label}
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="wh-rate">Rate Limit (req/min)</Label>
                    <Input id="wh-rate" type="number" value={formRateLimit} onChange={(e) => setFormRateLimit(Number(e.target.value))} disabled={!canMutate} min={0} className="h-9 text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="wh-payload">Max Payload Bytes</Label>
                    <Input id="wh-payload" type="number" value={formMaxPayload} onChange={(e) => setFormMaxPayload(Number(e.target.value))} disabled={!canMutate} min={0} className="h-9 text-sm" />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="wh-ips">IP Allowlist (one CIDR per line)</Label>
                  <Textarea id="wh-ips" value={formIpAllowlist} onChange={(e) => setFormIpAllowlist(e.target.value)} disabled={!canMutate} placeholder="0.0.0.0/0\n10.0.0.0/8" rows={3} className="text-xs" />
                </div>

                <div className="flex items-center gap-6">
                  <div className="flex items-center gap-3">
                    <Toggle checked={formEnabled} onChange={setFormEnabled} label="Enabled" />
                    <span className="text-sm text-muted-foreground">{formEnabled ? "Enabled" : "Disabled"}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <Toggle checked={formApiKeyEnabled} onChange={setFormApiKeyEnabled} label="API Key Auth" />
                    <span className="text-sm text-muted-foreground">{formApiKeyEnabled ? "API key" : "No API key"}</span>
                  </div>
                </div>

                {/* ── Webhook URL & cURL example ── */}
                {!isCreating && selectedWebhook && (
                  <>
                    <Separator />
                    <div className="space-y-3">
                      <div className="text-sm font-medium text-foreground">Webhook URL</div>
                      <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                        <code className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">{webhookUrl}</code>
                        <CopyButton value={webhookUrl} />
                      </div>
                      <div className="space-y-1">
                        <div className="flex items-center justify-between">
                          <div className="text-xs font-medium text-muted-foreground">cURL example</div>
                          <Badge variant="outline" className="text-[10px]">{providerInfo.label}</Badge>
                        </div>
                        <div className="relative rounded-xl border border-border/60 bg-background/60 px-3 py-2">
                          <pre className="overflow-x-auto text-[11px] text-muted-foreground"><code>{curlExample}</code></pre>
                          <div className="absolute right-2 top-2"><CopyButton value={curlExample} /></div>
                        </div>
                      </div>
                      {/* ── Generate Secret ── */}
                      <div className="flex items-center gap-3">
                        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs" onClick={handleGenerateSecret} disabled={generatingSecret}>
                          <Key className="h-3.5 w-3.5" />
                          {generatingSecret ? "Generating..." : "Generate New Secret"}
                        </Button>
                        {generatedSecret && (
                          <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5">
                            <span className="text-[11px] text-emerald-400 font-medium">Secret generated</span>
                            <code className="text-[10px] text-muted-foreground">key_id: {generatedSecret.key_id}</code>
                          </div>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* ── Detail tabs: Overview / History / Dead Letter ── */}
            {!isCreating && selectedWebhook && (
              <Card className="border-border/70 bg-card/55 flex-1">
                <CardHeader className="pb-0">
                  <Tabs value={detailTab} onValueChange={setDetailTab}>
                    <TabsList className="h-auto gap-1.5 rounded-lg border border-border/60 bg-card/40 p-1">
                      <TabsTrigger value="overview" className="gap-1.5 rounded-md px-3 py-1.5 text-[11px] data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none">
                        <Activity className="h-3 w-3" />
                        Overview
                      </TabsTrigger>
                      <TabsTrigger value="history" className="gap-1.5 rounded-md px-3 py-1.5 text-[11px] data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none">
                        <Clock className="h-3 w-3" />
                        History
                      </TabsTrigger>
                      <TabsTrigger value="dead-letter" className="gap-1.5 rounded-md px-3 py-1.5 text-[11px] data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none">
                        <Skull className="h-3 w-3" />
                        Dead Letter
                        {deadLetter.length > 0 && (
                          <span className="ml-1 rounded-full bg-destructive/20 px-1.5 py-0.5 text-[10px] text-destructive">{deadLetter.length}</span>
                        )}
                      </TabsTrigger>
                    </TabsList>
                  </Tabs>
                </CardHeader>
                <CardContent className="pt-3">
                  {/* ── Overview tab ── */}
                  {detailTab === "overview" && (
                    <div className="space-y-3">
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div className="rounded-lg border border-border/60 bg-background/40 p-3">
                          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <Shield className="h-3 w-3" />
                            Signature Verification
                          </div>
                          <div className="mt-1 text-sm font-medium text-foreground">
                            {selectedWebhook.provider === "generic" ? "HMAC-SHA256" : `${selectedWebhook.provider} native`}
                          </div>
                        </div>
                        <div className="rounded-lg border border-border/60 bg-background/40 p-3">
                          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <Key className="h-3 w-3" />
                            Active Keys
                          </div>
                          <div className="mt-1 text-sm font-medium text-foreground">{selectedWebhook.active_keys}</div>
                        </div>
                      </div>

                      {latestInvocation && (
                        <div className="rounded-lg border border-border/60 bg-background/40 p-3">
                          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                            <Zap className="h-3 w-3" />
                            Latest Invocation
                          </div>
                          <div className="mt-1 space-y-1">
                            <div className="flex items-center gap-2 text-xs">
                              <span className="font-medium text-foreground">{formatDate(latestInvocation.received_at)}</span>
                              <Badge variant={latestInvocation.signature_verified ? "default" : "destructive"} className="text-[10px]">
                                {latestInvocation.signature_verified ? "Verified" : "Unverified"}
                              </Badge>
                              <Badge variant="secondary" className="text-[10px]">
                                {latestInvocation.matched_triggers} trigger{latestInvocation.matched_triggers === 1 ? "" : "s"}
                              </Badge>
                            </div>
                            <div className="text-[11px] text-muted-foreground">
                              From {latestInvocation.source_ip} · Status: {latestInvocation.status}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* ── History tab ── */}
                  {detailTab === "history" && (
                    <>
                      {historyLoading && history.length === 0 ? (
                        <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10 w-full rounded-lg" />)}</div>
                      ) : history.length === 0 ? (
                        <EmptyState icon={Clock} title="No invocations yet" description="This webhook hasn't received any requests." className="py-6" />
                      ) : (
                        <ScrollArea className="max-h-80">
                          <div className="space-y-2">
                            {history.map((inv) => (
                              <div key={inv.id} className="rounded-xl border border-border/60 bg-background/40 px-3 py-2.5">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                                    <span>{formatDate(inv.received_at)}</span>
                                    <span className="text-border">·</span>
                                    <span>{inv.source_ip}</span>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <Badge variant={inv.signature_verified ? "default" : "destructive"} className="text-[10px]">
                                      {inv.signature_verified ? <span className="flex items-center gap-1"><Shield className="h-3 w-3" /> Verified</span> : <span className="flex items-center gap-1"><AlertTriangle className="h-3 w-3" /> Unverified</span>}
                                    </Badge>
                                    <Badge variant="secondary" className="text-[10px]">{inv.matched_triggers} trigger{inv.matched_triggers === 1 ? "" : "s"}</Badge>
                                  </div>
                                </div>
                                <div className="mt-1.5 flex items-center justify-between">
                                  <span className="text-[11px] font-medium text-foreground">Status: {inv.status}</span>
                                  <Button variant="ghost" size="sm" className="h-6 gap-1 text-[10px] text-muted-foreground" onClick={() => setExpandedPayloadId(expandedPayloadId === inv.id ? null : inv.id)}>
                                    {expandedPayloadId === inv.id ? <><ChevronUp className="h-3 w-3" /> Hide</> : <><ChevronDown className="h-3 w-3" /> Details</>}
                                  </Button>
                                </div>
                                {expandedPayloadId === inv.id && (
                                  <pre className="mt-2 max-h-40 overflow-auto rounded-lg border border-border/60 bg-background/80 p-2 text-[11px] text-muted-foreground">
                                    {JSON.stringify(inv, null, 2)}
                                  </pre>
                                )}
                              </div>
                            ))}
                          </div>
                        </ScrollArea>
                      )}
                    </>
                  )}

                  {/* ── Dead Letter tab ── */}
                  {detailTab === "dead-letter" && (
                    <>
                      {deadLetterLoading && deadLetter.length === 0 ? (
                        <div className="space-y-2">{[0, 1].map((i) => <Skeleton key={i} className="h-16 w-full rounded-lg" />)}</div>
                      ) : deadLetter.length === 0 ? (
                        <EmptyState icon={Skull} title="No dead-letter items" description="All executions have been processed successfully." className="py-6" />
                      ) : (
                        <ScrollArea className="max-h-80">
                          <div className="space-y-2">
                            {deadLetter.map((exec) => (
                              <div key={exec.id} className="rounded-xl border border-destructive/20 bg-destructive/5 px-3 py-2.5">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center gap-2 text-[11px]">
                                    <span className="text-muted-foreground">{formatDate(exec.executed_at)}</span>
                                    <Badge variant="destructive" className="text-[10px]">{exec.status}</Badge>
                                    <span className="text-muted-foreground">{exec.attempt_count} attempt{exec.attempt_count === 1 ? "" : "s"}</span>
                                  </div>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 gap-1 text-[10px]"
                                    onClick={() => handleReplay(exec.id)}
                                    disabled={replayingId === exec.id}
                                  >
                                    <SkipForward className="h-3 w-3" />
                                    {replayingId === exec.id ? "Replaying..." : "Replay"}
                                  </Button>
                                </div>
                                {exec.error_message && (
                                  <div className="mt-1.5 text-[11px] text-destructive">{exec.error_message}</div>
                                )}
                              </div>
                            ))}
                          </div>
                        </ScrollArea>
                      )}
                    </>
                  )}
                </CardContent>
              </Card>
            )}
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center rounded-3xl border border-dashed border-border/70 bg-card/30">
            <EmptyState
              icon={Webhook}
              title="Select a webhook"
              description="Choose a webhook from the list to view details, history, and dead-letter queue."
              action={canMutate ? { label: "Create Webhook", onClick: handleCreateNew } : undefined}
            />
          </div>
        )}

        <ConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={setDeleteDialogOpen}
          title="Delete webhook"
          description={`This will permanently delete the webhook "${selectedWebhook?.name}". This action cannot be undone.`}
          confirmLabel="Delete"
          variant="destructive"
          onConfirm={handleDelete}
        />
      </div>
    </div>
  );
}

function Label({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return <label htmlFor={htmlFor} className="text-sm font-medium text-foreground">{children}</label>;
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => { return () => { clearTimeout(timerRef.current); }; }, []);
  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1500);
  }, [value]);
  return (
    <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground transition-transform duration-150 active:scale-90" onClick={handleCopy} aria-label={copied ? "Copied" : "Copy to clipboard"}>
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </Button>
  );
}
