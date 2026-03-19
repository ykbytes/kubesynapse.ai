import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  EyeOff,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Server,
  Trash2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

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
import { Skeleton } from "@/components/ui/skeleton";

import {
  addProviderModel,
  deleteLLMModel,
  fetchLLMHealth,
  fetchLLMProviders,
  fetchProviderSuggestions,
  updateLLMKeys,
} from "@/lib/api";
import type { LLMProvider, ModelSuggestion } from "@/types";

const KEY_PLACEHOLDERS: Record<string, string> = {
  OPENAI_API_KEY: "sk-...",
  OPENROUTER_API_KEY: "sk-or-...",
  ANTHROPIC_API_KEY: "sk-ant-...",
  AZURE_API_KEY: "...",
  GOOGLE_API_KEY: "AIza...",
  MISTRAL_API_KEY: "...",
  COHERE_API_KEY: "...",
  GROQ_API_KEY: "gsk_...",
  DEEPSEEK_API_KEY: "sk-...",
  TOGETHER_API_KEY: "...",
  FIREWORKS_API_KEY: "...",
};

interface SettingsPanelProps {
  token: string;
  isAdmin: boolean;
}

function statusTone(configured: boolean | null): string {
  if (configured === true) return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  if (configured === false) return "text-muted-foreground";
  return "bg-amber-500/10 text-amber-400 border-amber-500/30";
}

export function SettingsPanel({ token, isAdmin }: SettingsPanelProps) {
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [health, setHealth] = useState<{ status: string; litellm_status?: number; error?: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [healthLoading, setHealthLoading] = useState(true);

  const [selectedProviderKey, setSelectedProviderKey] = useState("");
  const [providerFilter, setProviderFilter] = useState("");

  const [keyDraftByProvider, setKeyDraftByProvider] = useState<Record<string, string>>({});
  const [keyVisibleByProvider, setKeyVisibleByProvider] = useState<Record<string, boolean>>({});
  const [savingKeyProvider, setSavingKeyProvider] = useState<string | null>(null);

  const [addDialogProvider, setAddDialogProvider] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ModelSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [selectedModelId, setSelectedModelId] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const p = await fetchLLMProviders(token).catch(() => [] as LLMProvider[]);
      setProviders(p);
    } finally {
      setLoading(false);
    }
  }, [token]);

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const h = await fetchLLMHealth(token);
      setHealth(h);
    } catch {
      setHealth({ status: "unreachable", error: "Failed to check" });
    } finally {
      setHealthLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
    void refreshHealth();
  }, [refresh, refreshHealth]);

  useEffect(() => {
    if (providers.length === 0) {
      setSelectedProviderKey("");
      return;
    }
    if (!providers.some((p) => p.key_name === selectedProviderKey)) {
      setSelectedProviderKey(providers[0].key_name);
    }
  }, [providers, selectedProviderKey]);

  const filteredProviders = useMemo(() => {
    const q = providerFilter.trim().toLowerCase();
    if (!q) return providers;
    return providers.filter((p) => {
      if (p.label.toLowerCase().includes(q)) return true;
      if (p.key_name.toLowerCase().includes(q)) return true;
      if (p.models.some((m) => m.model_name.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [providerFilter, providers]);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.key_name === selectedProviderKey) ?? null,
    [providers, selectedProviderKey],
  );

  const configuredCount = useMemo(
    () => providers.filter((p) => p.is_configured === true).length,
    [providers],
  );

  function getKeyDraft(providerKey: string): string {
    return keyDraftByProvider[providerKey] ?? "";
  }

  function setKeyDraft(providerKey: string, value: string) {
    setKeyDraftByProvider((prev) => ({ ...prev, [providerKey]: value }));
  }

  function isKeyVisible(providerKey: string): boolean {
    return keyVisibleByProvider[providerKey] ?? false;
  }

  function toggleKeyVisible(providerKey: string) {
    setKeyVisibleByProvider((prev) => ({ ...prev, [providerKey]: !(prev[providerKey] ?? false) }));
  }

  async function handleSaveKey(keyName: string) {
    const draft = getKeyDraft(keyName).trim();
    if (!draft) return;
    setSavingKeyProvider(keyName);
    try {
      await updateLLMKeys(token, { [keyName]: draft });
      const prov = providers.find((p) => p.key_name === keyName);
      toast.success(`${prov?.label ?? keyName} key updated`);
      setKeyDraft(keyName, "");
      setKeyVisibleByProvider((prev) => ({ ...prev, [keyName]: false }));
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update key");
    } finally {
      setSavingKeyProvider(null);
    }
  }

  async function handleDeleteModel(modelId: string, modelName: string) {
    try {
      await deleteLLMModel(token, modelId);
      toast.success(`Model "${modelName}" removed`);
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to remove model");
    }
  }

  function openAddDialog(providerKeyName: string) {
    setAddDialogProvider(providerKeyName);
    setModelSearch("");
    setSelectedModelId("");
    setSuggestions([]);
  }

  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!addDialogProvider) return;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    setSuggestionsLoading(true);
    const delay = modelSearch ? 300 : 0;
    searchTimerRef.current = setTimeout(async () => {
      try {
        const s = await fetchProviderSuggestions(token, addDialogProvider, modelSearch || undefined);
        setSuggestions(s);
      } catch {
        setSuggestions([]);
      } finally {
        setSuggestionsLoading(false);
      }
    }, delay);
    return () => {
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, [addDialogProvider, modelSearch, token]);

  async function handleAddModel() {
    if (!addDialogProvider || !selectedModelId.trim()) return;
    setAddBusy(true);
    try {
      await addProviderModel(token, addDialogProvider, selectedModelId.trim());
      toast.success(`Model "${selectedModelId}" added`);
      setAddDialogProvider(null);
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to add model");
    } finally {
      setAddBusy(false);
    }
  }

  const healthColor =
    health?.status === "healthy"
      ? "text-emerald-500"
      : health?.status === "unhealthy"
        ? "text-amber-500"
        : "text-red-500";

  const HealthIcon =
    health?.status === "healthy"
      ? CheckCircle2
      : health?.status === "unhealthy"
        ? AlertTriangle
        : XCircle;

  const addDialogProviderObj = providers.find((p) => p.key_name === addDialogProvider);

  return (
    <ScrollArea className="flex-1">
      <div className="mx-auto w-full max-w-7xl space-y-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">LLM Providers</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Configure API keys, browse models, and manage which models are available to agents.
            </p>
          </div>
          <Button variant="outline" size="sm" className="h-9 gap-1.5" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server className="h-4 w-4 text-muted-foreground" />
                <CardTitle className="text-base">LiteLLM Proxy</CardTitle>
              </div>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => void refreshHealth()} disabled={healthLoading}>
                <RefreshCw className={`h-3.5 w-3.5 ${healthLoading ? "animate-spin" : ""}`} />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2">
              {healthLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : (
                <HealthIcon className={`h-4 w-4 ${healthColor}`} />
              )}
              <span className="text-sm font-medium capitalize">{healthLoading ? "Checking..." : health?.status ?? "unknown"}</span>
              <Badge variant="outline" className="text-[11px]">
                {configuredCount}/{providers.length} keys configured
              </Badge>
              {health?.error && <span className="text-xs text-muted-foreground">- {health.error}</span>}
            </div>
          </CardContent>
        </Card>

        {loading ? (
          <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <Card className="h-[540px]">
              <CardHeader className="pb-2">
                <Skeleton className="h-8 w-full rounded" />
              </CardHeader>
              <CardContent className="space-y-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-14 w-full rounded" />
                ))}
              </CardContent>
            </Card>
            <Card className="h-[540px]">
              <CardHeader className="pb-2">
                <Skeleton className="h-6 w-52 rounded" />
              </CardHeader>
              <CardContent className="space-y-3">
                <Skeleton className="h-9 w-full rounded" />
                <Skeleton className="h-10 w-32 rounded" />
                <Skeleton className="h-4 w-24 rounded" />
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-9 w-full rounded" />
                ))}
              </CardContent>
            </Card>
          </div>
        ) : providers.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-2 py-12">
              <Server className="h-8 w-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No providers found</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
            <Card className="h-[540px] flex flex-col">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Providers</CardTitle>
                <div className="relative mt-1">
                  <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={providerFilter}
                    onChange={(e) => setProviderFilter(e.target.value)}
                    placeholder="Filter providers or models..."
                    className="h-9 pl-8"
                  />
                </div>
              </CardHeader>
              <CardContent className="min-h-0 flex-1 pt-0">
                <ScrollArea className="h-full pr-2">
                  <div className="space-y-2">
                    {filteredProviders.length === 0 ? (
                      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                        No providers match "{providerFilter}".
                      </div>
                    ) : (
                      filteredProviders.map((prov) => {
                        const isSelected = selectedProviderKey === prov.key_name;
                        return (
                          <button
                            key={prov.key_name}
                            type="button"
                            onClick={() => setSelectedProviderKey(prov.key_name)}
                            className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                              isSelected
                                ? "border-primary/40 bg-primary/5"
                                : "border-border bg-background hover:bg-muted/40"
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-medium">{prov.label}</p>
                                <p className="truncate text-[11px] text-muted-foreground">{prov.key_name}</p>
                              </div>
                              <Badge
                                variant={prov.is_configured ? "default" : "outline"}
                                className={`text-[10px] ${statusTone(prov.is_configured)}`}
                              >
                                {prov.is_configured === null ? "Unknown" : prov.is_configured ? "Key set" : "No key"}
                              </Badge>
                            </div>
                            <div className="mt-1 flex items-center gap-2">
                              <Badge variant="secondary" className="text-[10px]">
                                {prov.model_count} model{prov.model_count !== 1 ? "s" : ""}
                              </Badge>
                            </div>
                          </button>
                        );
                      })
                    )}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>

            <Card className="min-h-[540px]">
              {!selectedProvider ? (
                <CardContent className="flex h-full min-h-[540px] flex-col items-center justify-center gap-2 text-center">
                  <Info className="h-8 w-8 text-muted-foreground/40" />
                  <p className="text-sm text-muted-foreground">Select a provider to manage keys and models.</p>
                </CardContent>
              ) : (
                <>
                  <CardHeader className="pb-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <CardTitle className="text-lg">{selectedProvider.label}</CardTitle>
                        <p className="text-xs text-muted-foreground">{selectedProvider.key_name}</p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant={selectedProvider.is_configured ? "default" : "outline"}
                          className={`text-[10px] ${statusTone(selectedProvider.is_configured)}`}
                        >
                          {selectedProvider.is_configured === null ? "Unknown" : selectedProvider.is_configured ? "Key set" : "No key"}
                        </Badge>
                        <Badge variant="secondary" className="text-[10px]">
                          {selectedProvider.model_count} model{selectedProvider.model_count !== 1 ? "s" : ""}
                        </Badge>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    {isAdmin && (
                      <div className="space-y-2">
                        <Label className="text-xs text-muted-foreground">API Key</Label>
                        <div className="relative">
                          <Input
                            type={isKeyVisible(selectedProvider.key_name) ? "text" : "password"}
                            value={getKeyDraft(selectedProvider.key_name)}
                            onChange={(e) => setKeyDraft(selectedProvider.key_name, e.target.value)}
                            placeholder={KEY_PLACEHOLDERS[selectedProvider.key_name] ?? "Paste API key..."}
                            className="h-10 pr-9 font-mono text-xs"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            className="absolute right-0 top-0 h-full w-9"
                            onClick={() => toggleKeyVisible(selectedProvider.key_name)}
                            tabIndex={-1}
                          >
                            {isKeyVisible(selectedProvider.key_name) ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                          </Button>
                        </div>
                        <Button
                          size="sm"
                          className="h-9 text-xs"
                          onClick={() => void handleSaveKey(selectedProvider.key_name)}
                          disabled={savingKeyProvider === selectedProvider.key_name || !getKeyDraft(selectedProvider.key_name).trim()}
                        >
                          {savingKeyProvider === selectedProvider.key_name ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                          {selectedProvider.is_configured ? "Update key" : "Set key"}
                        </Button>
                      </div>
                    )}

                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <Label className="text-xs text-muted-foreground">Enabled Models</Label>
                        {isAdmin && (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 gap-1 text-xs"
                            onClick={() => void openAddDialog(selectedProvider.key_name)}
                          >
                            <Plus className="h-3 w-3" />
                            Add model
                          </Button>
                        )}
                      </div>

                      {selectedProvider.models.length === 0 ? (
                        <p className="py-3 text-sm text-muted-foreground">No models enabled for this provider yet.</p>
                      ) : (
                        <div className="space-y-1.5">
                          {selectedProvider.models.map((m) => (
                            <div
                              key={m.id || m.model_name}
                              className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
                            >
                              <span className="flex-1 truncate font-medium">{m.model_name}</span>
                              {isAdmin && m.id && (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                                  onClick={() => void handleDeleteModel(m.id, m.model_name)}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </>
              )}
            </Card>
          </div>
        )}
      </div>

      <Dialog open={addDialogProvider !== null} onOpenChange={(open) => { if (!open) setAddDialogProvider(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Model - {addDialogProviderObj?.label ?? ""}</DialogTitle>
            <DialogDescription>
              Pick a model to enable, or type a custom model ID.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Model ID</Label>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={selectedModelId}
                  onChange={(e) => { setSelectedModelId(e.target.value); setModelSearch(e.target.value); }}
                  placeholder="Search or type model ID..."
                  className="pl-8 text-sm"
                  autoFocus
                />
              </div>
            </div>

            {suggestionsLoading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            ) : suggestions.length > 0 ? (
              <ScrollArea className="max-h-52">
                <div className="space-y-0.5">
                  {suggestions.map((s) => (
                    <button
                      key={s.model_id}
                      type="button"
                      className={`flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-muted/60 ${
                        selectedModelId === s.model_id ? "bg-primary/10 ring-1 ring-primary/30" : ""
                      }`}
                      onClick={() => { setSelectedModelId(s.model_id); setModelSearch(""); }}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium">{s.display_name}</p>
                        {s.description && <p className="mt-0.5 text-[11px] text-muted-foreground">{s.description}</p>}
                      </div>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            ) : modelSearch ? (
              <p className="py-2 text-center text-xs text-muted-foreground">
                No suggestions match. You can still add "{modelSearch}" as a custom model.
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogProvider(null)}>Cancel</Button>
            <Button onClick={() => void handleAddModel()} disabled={addBusy || !selectedModelId.trim()}>
              {addBusy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Plus className="mr-1 h-3 w-3" />}
              Add Model
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ScrollArea>
  );
}
