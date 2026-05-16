import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  Github,
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

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
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
import { Textarea } from "@/components/ui/textarea";
import {
  addProviderModel,
  createOrUpdateCustomProvider,
  deleteCustomProvider,
  deleteLLMModel,
  fetchConnectedProviders,
  fetchLLMHealth,
  fetchLLMProviders,
  fetchProviderSuggestions,
  getCopilotAuthStatus,
  initiateCopilotAuth,
  pollCopilotAuth,
  updateLLMKeys,
  updateProviderCredential,
} from "@/lib/api";
import type { ConnectedProvider, LLMProvider, ModelSuggestion } from "@/types";

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
  GITHUB_COPILOT_TOKEN: "Authenticated via GitHub",
};

const PANEL_CARD_CLASS = "border-border/70 bg-background/75 shadow-sm backdrop-blur-sm";
const METRIC_CARD_CLASS = "rounded-[1.15rem] border px-2.5 py-1.5 shadow-sm backdrop-blur-sm";

interface SettingsPanelProps {
  token: string;
  isAdmin: boolean;
}

function statusTone(configured: boolean | null): string {
  if (configured === true) return "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";
  if (configured === false) return "text-muted-foreground";
  return "bg-amber-500/10 text-amber-400 border-amber-500/30";
}

function connectedTone(connected: boolean): string {
  return connected
    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
    : "bg-muted/30 text-muted-foreground border-border/60";
}

function headersToText(headers: Record<string, string>): string {
  return Object.entries(headers)
    .map(([name, value]) => `${name}: ${value}`)
    .join("\n");
}

function modelsToText(provider: ConnectedProvider | null): string {
  if (!provider) return "";
  return provider.models.map((model) => model.id).join("\n");
}

function parseHeadersInput(value: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const rawLine of value.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const separator = line.indexOf(":");
    if (separator <= 0) {
      throw new Error(`Header \"${line}\" must use the format Name: Value`);
    }
    const name = line.slice(0, separator).trim();
    const headerValue = line.slice(separator + 1).trim();
    if (!name || !headerValue) {
      throw new Error(`Header \"${line}\" must use the format Name: Value`);
    }
    headers[name] = headerValue;
  }
  return headers;
}

export function SettingsPanel({ token, isAdmin }: SettingsPanelProps) {
  const [connectedProviders, setConnectedProviders] = useState<ConnectedProvider[]>([]);
  const [connectedLoading, setConnectedLoading] = useState(true);
  const [providerFilter, setProviderFilter] = useState("");
  const [providerKeyDraftByProvider, setProviderKeyDraftByProvider] = useState<Record<string, string>>({});
  const [providerKeyVisibleByProvider, setProviderKeyVisibleByProvider] = useState<Record<string, boolean>>({});
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [deletingCustomProviderId, setDeletingCustomProviderId] = useState<string | null>(null);

  const [litellmProviders, setLitellmProviders] = useState<LLMProvider[]>([]);
  const [litellmLoading, setLitellmLoading] = useState(true);
  const [health, setHealth] = useState<{ status: string; litellm_status?: number; error?: string } | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [selectedLiteLLMProviderKey, setSelectedLiteLLMProviderKey] = useState("");
  const [litellmFilter, setLitellmFilter] = useState("");
  const [litellmKeyDraftByProvider, setLitellmKeyDraftByProvider] = useState<Record<string, string>>({});
  const [litellmKeyVisibleByProvider, setLitellmKeyVisibleByProvider] = useState<Record<string, boolean>>({});
  const [savingLiteLLMKeyProvider, setSavingLiteLLMKeyProvider] = useState<string | null>(null);
  const [addDialogProvider, setAddDialogProvider] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<ModelSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const [selectedModelId, setSelectedModelId] = useState("");
  const [addBusy, setAddBusy] = useState(false);

  const [customDialogOpen, setCustomDialogOpen] = useState(false);
  const [editingCustomProviderId, setEditingCustomProviderId] = useState<string | null>(null);
  const [customProviderId, setCustomProviderId] = useState("");
  const [customProviderName, setCustomProviderName] = useState("");
  const [customProviderBaseUrl, setCustomProviderBaseUrl] = useState("");
  const [customProviderDescription, setCustomProviderDescription] = useState("");
  const [customProviderApiKey, setCustomProviderApiKey] = useState("");
  const [customProviderHeaders, setCustomProviderHeaders] = useState("");
  const [customProviderModels, setCustomProviderModels] = useState("");
  const [customProviderSaving, setCustomProviderSaving] = useState(false);

  const [copilotConnected, setCopilotConnected] = useState<boolean | null>(null);
  const [copilotFlowActive, setCopilotFlowActive] = useState(false);
  const [copilotUserCode, setCopilotUserCode] = useState("");
  const [copilotVerificationUri, setCopilotVerificationUri] = useState("");
  const copilotPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshConnected = useCallback(async () => {
    setConnectedLoading(true);
    try {
      setConnectedProviders(await fetchConnectedProviders(token));
    } catch {
      toast.error("Failed to load providers");
    } finally {
      setConnectedLoading(false);
    }
  }, [token]);

  const refreshLiteLLM = useCallback(async () => {
    setLitellmLoading(true);
    try {
      setLitellmProviders(await fetchLLMProviders(token));
    } catch {
      toast.error("Failed to load LiteLLM providers");
    } finally {
      setLitellmLoading(false);
    }
  }, [token]);

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      setHealth(await fetchLLMHealth(token));
    } catch {
      setHealth({ status: "unreachable", error: "Failed to check" });
    } finally {
      setHealthLoading(false);
    }
  }, [token]);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshConnected(), refreshLiteLLM(), refreshHealth()]);
  }, [refreshConnected, refreshHealth, refreshLiteLLM]);

  useEffect(() => {
    void refreshAll();
    if (isAdmin) {
      getCopilotAuthStatus(token)
        .then((status) => setCopilotConnected(status.connected))
        .catch(() => {});
    }
  }, [isAdmin, refreshAll, token]);

  useEffect(() => {
    if (litellmProviders.length === 0) {
      setSelectedLiteLLMProviderKey("");
      return;
    }
    if (!litellmProviders.some((provider) => provider.key_name === selectedLiteLLMProviderKey)) {
      setSelectedLiteLLMProviderKey(litellmProviders[0].key_name);
    }
  }, [litellmProviders, selectedLiteLLMProviderKey]);

  useEffect(() => {
    if (!addDialogProvider) return;
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    setSuggestionsLoading(true);
    const delay = modelSearch ? 300 : 0;
    searchTimerRef.current = setTimeout(async () => {
      try {
        const result = await fetchProviderSuggestions(token, addDialogProvider, modelSearch || undefined);
        setSuggestions(result);
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

  useEffect(() => {
    return () => {
      if (copilotPollRef.current) clearInterval(copilotPollRef.current);
      if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    };
  }, []);

  const filteredProviders = useMemo(() => {
    const query = providerFilter.trim().toLowerCase();
    if (!query) return connectedProviders;
    return connectedProviders.filter((provider) => {
      if (provider.label.toLowerCase().includes(query)) return true;
      if (provider.id.toLowerCase().includes(query)) return true;
      return provider.models.some((model) => model.id.toLowerCase().includes(query));
    });
  }, [connectedProviders, providerFilter]);

  const filteredLiteLLMProviders = useMemo(() => {
    const query = litellmFilter.trim().toLowerCase();
    if (!query) return litellmProviders;
    return litellmProviders.filter((provider) => {
      if (provider.label.toLowerCase().includes(query)) return true;
      if (provider.key_name.toLowerCase().includes(query)) return true;
      return provider.models.some((model) => model.model_name.toLowerCase().includes(query));
    });
  }, [litellmFilter, litellmProviders]);

  const selectedLiteLLMProvider = useMemo(
    () => litellmProviders.find((provider) => provider.key_name === selectedLiteLLMProviderKey) ?? null,
    [litellmProviders, selectedLiteLLMProviderKey],
  );

  const connectedCount = useMemo(
    () => connectedProviders.filter((provider) => provider.connected).length,
    [connectedProviders],
  );
  const customProviderCount = useMemo(
    () => connectedProviders.filter((provider) => provider.kind === "custom").length,
    [connectedProviders],
  );
  const mainModelCount = useMemo(
    () => connectedProviders.reduce((count, provider) => count + provider.models.length, 0),
    [connectedProviders],
  );
  const litellmConfiguredCount = useMemo(
    () => litellmProviders.filter((provider) => provider.is_configured === true).length,
    [litellmProviders],
  );
  const litellmModelCount = useMemo(
    () => litellmProviders.reduce((count, provider) => count + provider.models.length, 0),
    [litellmProviders],
  );

  function getProviderDraft(providerId: string): string {
    return providerKeyDraftByProvider[providerId] ?? "";
  }

  function setProviderDraft(providerId: string, value: string) {
    setProviderKeyDraftByProvider((previous) => ({ ...previous, [providerId]: value }));
  }

  function isProviderKeyVisible(providerId: string): boolean {
    return providerKeyVisibleByProvider[providerId] ?? false;
  }

  function getLiteLLMDraft(providerKey: string): string {
    return litellmKeyDraftByProvider[providerKey] ?? "";
  }

  function setLiteLLMDraft(providerKey: string, value: string) {
    setLitellmKeyDraftByProvider((previous) => ({ ...previous, [providerKey]: value }));
  }

  function isLiteLLMKeyVisible(providerKey: string): boolean {
    return litellmKeyVisibleByProvider[providerKey] ?? false;
  }

  const toggleProviderKeyVisible = useCallback((providerId: string) => {
    setProviderKeyVisibleByProvider((previous) => ({ ...previous, [providerId]: !(previous[providerId] ?? false) }));
  }, []);

  const toggleLiteLLMKeyVisible = useCallback((providerKey: string) => {
    setLitellmKeyVisibleByProvider((previous) => ({ ...previous, [providerKey]: !(previous[providerKey] ?? false) }));
  }, []);

  const saveProviderCredential = useCallback(
    async (providerId: string, label: string) => {
      const draft = getProviderDraft(providerId).trim();
      if (!draft) return;
      setSavingProviderId(providerId);
      try {
        await updateProviderCredential(token, providerId, draft);
        toast.success(`${label} credential updated`);
        setProviderDraft(providerId, "");
        setProviderKeyVisibleByProvider((previous) => ({ ...previous, [providerId]: false }));
        await refreshAll();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to update provider credential");
      } finally {
        setSavingProviderId(null);
      }
    },
    [refreshAll, token],
  );

  const saveLiteLLMKey = useCallback(
    async (providerKey: string) => {
      const draft = getLiteLLMDraft(providerKey).trim();
      if (!draft) return;
      setSavingLiteLLMKeyProvider(providerKey);
      try {
        await updateLLMKeys(token, { [providerKey]: draft });
        const provider = litellmProviders.find((item) => item.key_name === providerKey);
        toast.success(`${provider?.label ?? providerKey} key updated`);
        setLiteLLMDraft(providerKey, "");
        setLitellmKeyVisibleByProvider((previous) => ({ ...previous, [providerKey]: false }));
        await refreshAll();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to update LiteLLM key");
      } finally {
        setSavingLiteLLMKeyProvider(null);
      }
    },
    [litellmProviders, refreshAll, token],
  );

  const handleDeleteModel = useCallback(
    async (modelId: string, modelName: string) => {
      try {
        await deleteLLMModel(token, modelId);
        toast.success(`Model \"${modelName}\" removed`);
        await refreshLiteLLM();
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to remove model");
      }
    },
    [refreshLiteLLM, token],
  );

  function stopCopilotPolling() {
    if (copilotPollRef.current) {
      clearInterval(copilotPollRef.current);
      copilotPollRef.current = null;
    }
  }

  async function startCopilotDeviceFlow() {
    stopCopilotPolling();
    setCopilotFlowActive(true);
    setCopilotUserCode("");
    setCopilotVerificationUri("");
    try {
      const flow = await initiateCopilotAuth(token);
      setCopilotUserCode(flow.user_code);
      setCopilotVerificationUri(flow.verification_uri);
      const interval = (flow.interval + 3) * 1000;
      copilotPollRef.current = setInterval(async () => {
        try {
          const result = await pollCopilotAuth(token);
          if (result.status === "success") {
            stopCopilotPolling();
            setCopilotFlowActive(false);
            setCopilotConnected(true);
            toast.success("GitHub Copilot connected");
            await refreshAll();
          } else if (result.status === "error") {
            stopCopilotPolling();
            setCopilotFlowActive(false);
            toast.error(result.error || "Copilot authorization failed");
          }
        } catch {
          stopCopilotPolling();
          setCopilotFlowActive(false);
          toast.error("Failed to check authorization status");
        }
      }, interval);
    } catch (error) {
      setCopilotFlowActive(false);
      toast.error(error instanceof Error ? error.message : "Failed to start Copilot auth");
    }
  }

  function openCustomProviderDialog(provider?: ConnectedProvider) {
    setEditingCustomProviderId(provider?.kind === "custom" ? provider.id : null);
    setCustomProviderId(provider?.id ?? "");
    setCustomProviderName(provider?.label ?? "");
    setCustomProviderBaseUrl(provider?.base_url ?? "");
    setCustomProviderDescription(provider?.kind === "custom" ? provider.description : "");
    setCustomProviderApiKey("");
    setCustomProviderHeaders(headersToText(provider?.headers ?? {}));
    setCustomProviderModels(modelsToText(provider ?? null));
    setCustomDialogOpen(true);
  }

  async function saveCustomProvider() {
    try {
      setCustomProviderSaving(true);
      const providerId = (editingCustomProviderId ?? customProviderId).trim().toLowerCase();
      const models = customProviderModels
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean);
      await createOrUpdateCustomProvider(token, {
        provider_id: providerId,
        name: customProviderName.trim(),
        base_url: customProviderBaseUrl.trim(),
        description: customProviderDescription.trim(),
        api_key: customProviderApiKey.trim() || undefined,
        headers: parseHeadersInput(customProviderHeaders),
        models,
      });
      toast.success(editingCustomProviderId ? "Custom provider updated" : "Custom provider created");
      setCustomDialogOpen(false);
      setCustomProviderApiKey("");
      await refreshConnected();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save custom provider");
    } finally {
      setCustomProviderSaving(false);
    }
  }

  async function removeCustomProvider(providerId: string) {
    if (!window.confirm(`Delete custom provider \"${providerId}\"?`)) return;
    setDeletingCustomProviderId(providerId);
    try {
      await deleteCustomProvider(token, providerId);
      toast.success("Custom provider deleted");
      await refreshConnected();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to delete custom provider");
    } finally {
      setDeletingCustomProviderId(null);
    }
  }

  async function handleAddModel() {
    if (!addDialogProvider || !selectedModelId.trim()) return;
    setAddBusy(true);
    try {
      await addProviderModel(token, addDialogProvider, selectedModelId.trim());
      toast.success(`Model \"${selectedModelId}\" added`);
      setAddDialogProvider(null);
      await refreshLiteLLM();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to add model");
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

  const addDialogProviderObj = litellmProviders.find((provider) => provider.key_name === addDialogProvider);

  return (
    <ScrollArea className="flex-1">
      <div className="mx-auto w-full max-w-[84rem] space-y-3 p-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-base font-semibold tracking-tight">Providers</h1>
            <p className="text-sm text-muted-foreground">
              Manage OpenCode-native providers in the main section and keep raw LiteLLM controls under Advanced.
            </p>
          </div>
          <Button variant="outline" size="sm" className="h-9 gap-1.5" onClick={() => void refreshAll()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>

        {!isAdmin ? (
          <div className="rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
            Provider configuration is restricted to admins. You can still view connection status and available models.
          </div>
        ) : null}

        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <div className={`${METRIC_CARD_CLASS} border-primary/20 bg-primary/5`}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-primary/75">Connected</p>
              <p className="text-lg font-semibold text-foreground">{connectedCount}</p>
            </div>
          </div>
          <div className={`${METRIC_CARD_CLASS} border-sky-500/20 bg-sky-500/5`}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-sky-300/80">Providers</p>
              <p className="text-lg font-semibold text-foreground">{connectedProviders.length}</p>
            </div>
          </div>
          <div className={`${METRIC_CARD_CLASS} border-violet-500/20 bg-violet-500/5`}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-violet-300/80">Custom providers</p>
              <p className="text-lg font-semibold text-foreground">{customProviderCount}</p>
            </div>
          </div>
          <div className={`${METRIC_CARD_CLASS} border-emerald-500/20 bg-emerald-500/5`}>
            <div className="flex items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.16em] text-emerald-300/80">Catalog models</p>
              <p className="text-lg font-semibold text-foreground">{mainModelCount}</p>
            </div>
          </div>
        </div>

        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="px-4 py-3 pb-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle className="text-sm font-semibold">OpenCode Providers</CardTitle>
                <p className="text-xs text-muted-foreground">
                  Zen, Go, GitHub Copilot, and custom OpenAI-compatible providers.
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative w-full min-w-[220px] sm:w-[260px]">
                  <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={providerFilter}
                    onChange={(event) => setProviderFilter(event.target.value)}
                    placeholder="Filter providers or models..."
                    className="h-9 pl-8"
                  />
                </div>
                {isAdmin ? (
                  <Button size="sm" className="h-9 gap-1.5" onClick={() => openCustomProviderDialog()}>
                    <Plus className="h-3.5 w-3.5" />
                    Custom provider
                  </Button>
                ) : null}
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-4 py-3">
            {connectedLoading ? (
              <div className="grid gap-2 lg:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-56 w-full rounded-2xl" />
                ))}
              </div>
            ) : filteredProviders.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-border/70 px-4 py-8 text-center text-sm text-muted-foreground">
                No providers match "{providerFilter}".
              </div>
            ) : (
              <div className="grid gap-2 lg:grid-cols-2 xl:grid-cols-3">
                {filteredProviders.map((provider) => {
                  const providerModels = provider.models.slice(0, 6);
                  const isCopilot = provider.id === "github-copilot";
                  const isSavingCredential = savingProviderId === provider.id;
                  const isDeletingCustom = deletingCustomProviderId === provider.id;
                  const emptyModelsMessage = provider.connected
                    ? "No live models returned for this provider yet. Refresh or reconnect to try again."
                    : isCopilot
                      ? "Connect with GitHub to load available models."
                      : "Connect this provider to load its live model catalog.";
                  return (
                    <Card key={provider.id} className="rounded-[1.25rem] border-border/70 bg-background/70 shadow-sm">
                      <CardHeader className="px-4 py-3 pb-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <CardTitle className="truncate text-sm font-semibold">{provider.label}</CardTitle>
                              <Badge variant="outline" className="text-[10px] uppercase tracking-[0.14em]">
                                {provider.kind}
                              </Badge>
                            </div>
                            <p className="text-xs text-muted-foreground">{provider.id}</p>
                          </div>
                          <Badge variant="outline" className={`text-[10px] ${connectedTone(provider.connected)}`}>
                            {provider.connected ? "Connected" : "Not connected"}
                          </Badge>
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-3 px-4 py-3 text-sm">
                        <p className="min-h-[40px] text-muted-foreground">{provider.description}</p>

                        <div className="flex flex-wrap gap-1.5">
                          <Badge variant="secondary" className="text-[10px]">
                            {provider.models.length} model{provider.models.length === 1 ? "" : "s"}
                          </Badge>
                          {provider.base_url ? (
                            <Badge variant="outline" className="max-w-full truncate text-[10px]">
                              {provider.base_url}
                            </Badge>
                          ) : null}
                        </div>

                        {provider.docs_url ? (
                          <a
                            href={provider.docs_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-primary underline"
                          >
                            Provider docs
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : null}

                        {isCopilot ? (
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">GitHub Copilot Authentication</Label>
                            {copilotFlowActive && copilotUserCode ? (
                              <div className="rounded-xl border border-primary/30 bg-primary/5 p-3 text-xs">
                                <p className="text-muted-foreground">
                                  Open{" "}
                                  <a
                                    href={copilotVerificationUri}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="font-medium text-primary underline"
                                  >
                                    {copilotVerificationUri}
                                  </a>{" "}
                                  and enter this code.
                                </p>
                                <div className="mt-2 flex items-center gap-2">
                                  <code className="rounded bg-background px-3 py-1.5 text-sm font-bold tracking-widest">
                                    {copilotUserCode}
                                  </code>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8"
                                    onClick={() => {
                                      navigator.clipboard.writeText(copilotUserCode);
                                      toast.success("Code copied");
                                    }}
                                    aria-label="Copy user code"
                                  >
                                    <Copy className="h-4 w-4" />
                                  </Button>
                                </div>
                                <div className="mt-2 flex items-center gap-2 text-muted-foreground">
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  Waiting for authorization...
                                </div>
                              </div>
                            ) : copilotConnected || provider.connected ? (
                              <div className="space-y-2">
                                <div className="flex items-center gap-2 text-emerald-500">
                                  <CheckCircle2 className="h-4 w-4" />
                                  <span className="text-sm font-medium">Connected</span>
                                </div>
                                {isAdmin ? (
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-8 gap-1.5 text-xs"
                                    onClick={() => void startCopilotDeviceFlow()}
                                  >
                                    <Github className="h-3.5 w-3.5" />
                                    Reconnect
                                  </Button>
                                ) : null}
                              </div>
                            ) : isAdmin ? (
                              <Button
                                size="sm"
                                className="h-8 gap-1.5 text-xs"
                                onClick={() => void startCopilotDeviceFlow()}
                                disabled={copilotFlowActive}
                              >
                                {copilotFlowActive ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Github className="h-3.5 w-3.5" />
                                )}
                                Connect with GitHub
                              </Button>
                            ) : (
                              <p className="text-xs text-muted-foreground">Admin access is required to connect Copilot.</p>
                            )}
                          </div>
                        ) : isAdmin ? (
                          <div className="space-y-1.5">
                            <Label className="text-xs text-muted-foreground">Credential</Label>
                            <div className="relative">
                              <Input
                                type={isProviderKeyVisible(provider.id) ? "text" : "password"}
                                value={getProviderDraft(provider.id)}
                                onChange={(event) => setProviderDraft(provider.id, event.target.value)}
                                placeholder={provider.key_placeholder ?? "Paste API key..."}
                                className="h-9 pr-9 font-mono text-xs"
                              />
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute right-0 top-0 h-full w-9"
                                onClick={() => toggleProviderKeyVisible(provider.id)}
                                tabIndex={-1}
                                aria-label={isProviderKeyVisible(provider.id) ? "Hide credential" : "Show credential"}
                              >
                                {isProviderKeyVisible(provider.id) ? (
                                  <EyeOff className="h-3.5 w-3.5" />
                                ) : (
                                  <Eye className="h-3.5 w-3.5" />
                                )}
                              </Button>
                            </div>
                            <Button
                              size="sm"
                              className="h-8 text-xs"
                              onClick={() => void saveProviderCredential(provider.id, provider.label)}
                              disabled={isSavingCredential || !getProviderDraft(provider.id).trim()}
                            >
                              {isSavingCredential ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                              {provider.connected ? "Update credential" : "Connect provider"}
                            </Button>
                          </div>
                        ) : null}

                        {provider.editable && isAdmin ? (
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-8 text-xs"
                              onClick={() => openCustomProviderDialog(provider)}
                            >
                              Edit custom provider
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 text-xs text-destructive hover:text-destructive"
                              onClick={() => void removeCustomProvider(provider.id)}
                              disabled={isDeletingCustom}
                            >
                              {isDeletingCustom ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                              Delete
                            </Button>
                          </div>
                        ) : null}

                        <div className="space-y-1.5">
                          <Label className="text-xs text-muted-foreground">Models</Label>
                          {providerModels.length === 0 ? (
                            <p className="text-xs text-muted-foreground">{emptyModelsMessage}</p>
                          ) : (
                            <div className="space-y-1.5">
                              {providerModels.map((model) => (
                                <div
                                  key={model.id}
                                  className="rounded-xl border border-border/70 bg-background/70 px-3 py-2"
                                >
                                  <p className="truncate text-sm font-medium">{model.name}</p>
                                  <p className="truncate text-[11px] text-muted-foreground">{model.id}</p>
                                </div>
                              ))}
                              {provider.models.length > providerModels.length ? (
                                <p className="text-[11px] text-muted-foreground">
                                  +{provider.models.length - providerModels.length} more models
                                </p>
                              ) : null}
                            </div>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <Accordion type="single" collapsible className="rounded-2xl border border-border/70 bg-background/60 px-4">
          <AccordionItem value="advanced-litellm" className="border-none">
            <AccordionTrigger className="py-4 text-sm font-medium">Advanced / LiteLLM</AccordionTrigger>
            <AccordionContent className="space-y-3">
              <Card className="overflow-hidden border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.04),rgba(255,255,255,0.01))] shadow-[0_24px_80px_-48px_rgba(0,0,0,0.65)]">
                <CardHeader className="px-4 py-3 pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Server className="h-4 w-4 text-muted-foreground" />
                      <CardTitle className="text-sm font-semibold">LiteLLM Proxy</CardTitle>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => void refreshHealth()}
                      disabled={healthLoading}
                      aria-label="Refresh health"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${healthLoading ? "animate-spin" : ""}`} />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="px-4 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    {healthLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    ) : (
                      <HealthIcon className={`h-4 w-4 ${healthColor}`} />
                    )}
                    <span className="text-sm font-medium capitalize">
                      {healthLoading ? "Checking..." : health?.status ?? "unknown"}
                    </span>
                    <Badge variant="outline" className="text-[11px]">
                      {litellmConfiguredCount}/{litellmProviders.length} keys configured
                    </Badge>
                    <Badge variant="outline" className="text-[11px]">
                      {litellmModelCount} enabled models
                    </Badge>
                    {health?.error ? <span className="text-xs text-muted-foreground">- {health.error}</span> : null}
                  </div>
                </CardContent>
              </Card>

              {!isAdmin ? (
                <div className="rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-sm text-muted-foreground">
                  LiteLLM configuration is visible here for reference, but only admins can edit keys and models.
                </div>
              ) : null}

              {litellmLoading ? (
                <div className="grid gap-2 lg:grid-cols-[260px_1fr]">
                  <Skeleton className="h-[420px] w-full rounded-2xl" />
                  <Skeleton className="h-[420px] w-full rounded-2xl" />
                </div>
              ) : litellmProviders.length === 0 ? (
                <Card className={PANEL_CARD_CLASS}>
                  <CardContent className="flex flex-col items-center gap-2 px-4 py-8">
                    <Server className="h-8 w-8 text-muted-foreground/40" />
                    <p className="text-sm text-muted-foreground">No LiteLLM providers found</p>
                  </CardContent>
                </Card>
              ) : (
                <div className="grid gap-2 lg:grid-cols-[260px_1fr]">
                  <Card className={`h-[420px] flex flex-col ${PANEL_CARD_CLASS}`}>
                    <CardHeader className="px-4 py-3 pb-2">
                      <CardTitle className="text-sm font-semibold">LiteLLM Providers</CardTitle>
                      <div className="relative mt-1">
                        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                        <Input
                          value={litellmFilter}
                          onChange={(event) => setLitellmFilter(event.target.value)}
                          placeholder="Filter providers or models..."
                          className="h-9 pl-8"
                        />
                      </div>
                    </CardHeader>
                    <CardContent className="min-h-0 flex-1 px-4 pt-0">
                      <ScrollArea className="h-full pr-2">
                        <div className="space-y-1.5">
                          {filteredLiteLLMProviders.map((provider) => {
                            const isSelected = selectedLiteLLMProviderKey === provider.key_name;
                            return (
                              <button
                                key={provider.key_name}
                                type="button"
                                onClick={() => setSelectedLiteLLMProviderKey(provider.key_name)}
                                className={`w-full rounded-[1rem] border px-2.5 py-2 text-left transition-all duration-200 ${
                                  isSelected
                                    ? "border-primary/35 bg-primary/10 shadow-sm shadow-primary/10"
                                    : "border-border/70 bg-background/70 hover:-translate-y-px hover:border-primary/20 hover:bg-primary/5"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <div className="min-w-0">
                                    <p className="truncate text-sm font-medium">{provider.label}</p>
                                    <p className="truncate text-[11px] text-muted-foreground">{provider.key_name}</p>
                                  </div>
                                  <Badge
                                    variant={provider.is_configured ? "default" : "outline"}
                                    className={`text-[10px] ${statusTone(provider.is_configured)}`}
                                  >
                                    {provider.is_configured ? "Key set" : "No key"}
                                  </Badge>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      </ScrollArea>
                    </CardContent>
                  </Card>

                  <Card className={`min-h-[420px] ${PANEL_CARD_CLASS}`}>
                    {!selectedLiteLLMProvider ? (
                      <CardContent className="flex h-full min-h-[420px] flex-col items-center justify-center gap-2 px-4 py-4 text-center">
                        <Info className="h-8 w-8 text-muted-foreground/40" />
                        <p className="text-sm text-muted-foreground">Select a LiteLLM provider to inspect keys and models.</p>
                      </CardContent>
                    ) : (
                      <>
                        <CardHeader className="px-4 py-3 pb-2">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                              <CardTitle className="text-sm font-semibold">{selectedLiteLLMProvider.label}</CardTitle>
                              <p className="text-xs text-muted-foreground">{selectedLiteLLMProvider.key_name}</p>
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              <Badge
                                variant={selectedLiteLLMProvider.is_configured ? "default" : "outline"}
                                className={`text-[10px] ${statusTone(selectedLiteLLMProvider.is_configured)}`}
                              >
                                {selectedLiteLLMProvider.is_configured ? "Key set" : "No key"}
                              </Badge>
                              <Badge variant="secondary" className="text-[10px]">
                                {selectedLiteLLMProvider.model_count} model
                                {selectedLiteLLMProvider.model_count === 1 ? "" : "s"}
                              </Badge>
                            </div>
                          </div>
                        </CardHeader>
                        <CardContent className="space-y-3 px-4 py-3">
                          {isAdmin ? (
                            <div className="space-y-1.5">
                              <Label className="text-xs text-muted-foreground">API Key</Label>
                              <div className="relative">
                                <Input
                                  type={isLiteLLMKeyVisible(selectedLiteLLMProvider.key_name) ? "text" : "password"}
                                  value={getLiteLLMDraft(selectedLiteLLMProvider.key_name)}
                                  onChange={(event) => setLiteLLMDraft(selectedLiteLLMProvider.key_name, event.target.value)}
                                  placeholder={KEY_PLACEHOLDERS[selectedLiteLLMProvider.key_name] ?? "Paste API key..."}
                                  className="h-9 pr-9 font-mono text-xs"
                                />
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="absolute right-0 top-0 h-full w-9"
                                  onClick={() => toggleLiteLLMKeyVisible(selectedLiteLLMProvider.key_name)}
                                  tabIndex={-1}
                                  aria-label={
                                    isLiteLLMKeyVisible(selectedLiteLLMProvider.key_name)
                                      ? "Hide API key"
                                      : "Show API key"
                                  }
                                >
                                  {isLiteLLMKeyVisible(selectedLiteLLMProvider.key_name) ? (
                                    <EyeOff className="h-3.5 w-3.5" />
                                  ) : (
                                    <Eye className="h-3.5 w-3.5" />
                                  )}
                                </Button>
                              </div>
                              <Button
                                size="sm"
                                className="h-8 text-xs"
                                onClick={() => void saveLiteLLMKey(selectedLiteLLMProvider.key_name)}
                                disabled={
                                  savingLiteLLMKeyProvider === selectedLiteLLMProvider.key_name ||
                                  !getLiteLLMDraft(selectedLiteLLMProvider.key_name).trim()
                                }
                              >
                                {savingLiteLLMKeyProvider === selectedLiteLLMProvider.key_name ? (
                                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                ) : null}
                                {selectedLiteLLMProvider.is_configured ? "Update key" : "Set key"}
                              </Button>
                            </div>
                          ) : null}

                          <div className="space-y-1.5">
                            <div className="flex items-center justify-between gap-2">
                              <Label className="text-xs text-muted-foreground">Enabled Models</Label>
                              {isAdmin ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 gap-1 text-xs"
                                  onClick={() => {
                                    setAddDialogProvider(selectedLiteLLMProvider.key_name);
                                    setModelSearch("");
                                    setSelectedModelId("");
                                    setSuggestions([]);
                                  }}
                                >
                                  <Plus className="h-3 w-3" />
                                  Add model
                                </Button>
                              ) : null}
                            </div>

                            {selectedLiteLLMProvider.models.length === 0 ? (
                              <p className="py-2 text-sm text-muted-foreground">No models enabled for this provider yet.</p>
                            ) : (
                              <div className="space-y-1.5">
                                {selectedLiteLLMProvider.models.map((model) => (
                                  <div
                                    key={model.id || model.model_name}
                                    className="flex items-center gap-2 rounded-[1rem] border border-border/70 bg-background/70 px-2.5 py-2 text-sm shadow-sm"
                                  >
                                    <span className="flex-1 truncate font-medium">{model.model_name}</span>
                                    <Badge variant="outline" className="text-[10px] uppercase tracking-[0.12em]">
                                      Enabled
                                    </Badge>
                                    {isAdmin && model.id ? (
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                                        onClick={() => void handleDeleteModel(model.id, model.model_name)}
                                        aria-label="Remove model"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                      </Button>
                                    ) : null}
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
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>

      <Dialog open={customDialogOpen} onOpenChange={setCustomDialogOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingCustomProviderId ? "Edit Custom Provider" : "Add Custom Provider"}</DialogTitle>
            <DialogDescription>
              Create an OpenAI-compatible provider that stays in the OpenCode provider catalog.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Provider ID</Label>
              <Input
                value={customProviderId}
                onChange={(event) => setCustomProviderId(event.target.value)}
                placeholder="my-provider"
                disabled={Boolean(editingCustomProviderId)}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Display name</Label>
              <Input
                value={customProviderName}
                onChange={(event) => setCustomProviderName(event.target.value)}
                placeholder="My Provider"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label className="text-xs">Base URL</Label>
              <Input
                value={customProviderBaseUrl}
                onChange={(event) => setCustomProviderBaseUrl(event.target.value)}
                placeholder="https://api.example.com/v1"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label className="text-xs">Description</Label>
              <Input
                value={customProviderDescription}
                onChange={(event) => setCustomProviderDescription(event.target.value)}
                placeholder="OpenAI-compatible provider for internal workloads"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label className="text-xs">API key</Label>
              <Input
                value={customProviderApiKey}
                onChange={(event) => setCustomProviderApiKey(event.target.value)}
                placeholder="Optional: set or rotate the provider API key"
                type="password"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Headers</Label>
              <Textarea
                rows={6}
                value={customProviderHeaders}
                onChange={(event) => setCustomProviderHeaders(event.target.value)}
                placeholder={`Authorization: Bearer token\nX-Example: value`}
                className="font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Models</Label>
              <Textarea
                rows={6}
                value={customProviderModels}
                onChange={(event) => setCustomProviderModels(event.target.value)}
                placeholder={`my-model\nmy-second-model`}
                className="font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCustomDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => void saveCustomProvider()}
              disabled={
                customProviderSaving ||
                !(editingCustomProviderId ?? customProviderId).trim() ||
                !customProviderName.trim() ||
                !customProviderBaseUrl.trim()
              }
            >
              {customProviderSaving ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Plus className="mr-1 h-3 w-3" />}
              Save Provider
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={addDialogProvider !== null} onOpenChange={(open) => (!open ? setAddDialogProvider(null) : null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Model - {addDialogProviderObj?.label ?? ""}</DialogTitle>
            <DialogDescription>Pick a model to enable, or type a custom model ID.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Model ID</Label>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={selectedModelId}
                  onChange={(event) => {
                    setSelectedModelId(event.target.value);
                    setModelSearch(event.target.value);
                  }}
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
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion.model_id}
                      type="button"
                      className={`flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-muted/60 ${
                        selectedModelId === suggestion.model_id ? "bg-primary/10 ring-1 ring-primary/30" : ""
                      }`}
                      onClick={() => {
                        setSelectedModelId(suggestion.model_id);
                        setModelSearch("");
                      }}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium">{suggestion.display_name}</p>
                        {suggestion.description ? (
                          <p className="mt-0.5 text-[11px] text-muted-foreground">{suggestion.description}</p>
                        ) : null}
                      </div>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            ) : (
              <p className="py-2 text-center text-xs text-muted-foreground">
                {modelSearch
                  ? `No suggestions match. You can still add "${modelSearch}" as a custom model.`
                  : "No live suggestions are available right now. You can still type a custom model ID."}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogProvider(null)}>
              Cancel
            </Button>
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
