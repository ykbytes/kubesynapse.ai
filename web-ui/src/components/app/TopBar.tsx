import { Check, CheckCircle2, ChevronDown, LayoutPanelTop, Loader2, Palette, XCircle } from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { StatusBadge } from "../shared/StatusBadge";
import { ConnectionDialog } from "../auth/ConnectionDialog";
import { NotificationCenter } from "../admin/NotificationCenter";
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from "@/components/ui/tooltip";
import { useTheme, THEMES } from "@/contexts/ThemeContext";
import { BRAND } from "@/lib/brand";
import { fetchNamespaces } from "@/lib/api";
import type { AuthConfig, AuthenticatedUser, GatewayHealth } from "@/types";

interface TopBarProps {
  health: GatewayHealth | null;
  gatewayError: string;
  token: string;
  namespace: string;
  isConnecting: boolean;
  authConfig: AuthConfig | null;
  currentUser: AuthenticatedUser | null;
  authBusy: boolean;
  authUsername: string;
  authPassword: string;
  authEmail: string;
  authDisplayName: string;
  authPasswordConfirm: string;
  passwordProvider: "local" | "ldap";
  registerMode: boolean;
  onTokenChange: (value: string) => void;
  onNamespaceChange: (value: string) => void;
  onAuthUsernameChange: (value: string) => void;
  onAuthPasswordChange: (value: string) => void;
  onAuthEmailChange: (value: string) => void;
  onAuthDisplayNameChange: (value: string) => void;
  onAuthPasswordConfirmChange: (value: string) => void;
  onPasswordProviderChange: (value: "local" | "ldap") => void;
  onRegisterModeChange: (value: boolean) => void;
  connectionError: string;
  onClearConnectionError: () => void;
  onConnect: () => Promise<boolean>;
  onPasswordSubmit: () => Promise<boolean>;
  onStartOidc: (providerId: string) => void;
  onStartSaml: (providerId: string) => void;
  onLogout: () => void;
  onRefreshCurrentUser: () => Promise<void>;
}

const THEME_SWATCHES: Record<string, string> = {
  dark: "bg-zinc-500",
  light: "bg-stone-100",
  midnight: "bg-sky-500",
  forest: "bg-emerald-500",
};

function ThemePicker() {
  const { theme, setTheme, labelFor } = useTheme();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 gap-1 rounded-lg border-border/70 bg-card/72 px-2 text-[11px] text-foreground hover:bg-accent/70">
          <span className={`inline-block h-3 w-3 rounded-full border border-white/40 shadow-sm ${THEME_SWATCHES[theme]}`} aria-hidden="true" />
          <Palette className="h-3 w-3" />
          <span className="hidden sm:inline">{labelFor(theme)}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 rounded-[calc(var(--radius-xl)+2px)] border border-border/70 bg-popover/96 p-2 shadow-lg backdrop-blur-xl" sideOffset={8}>
        <div className="px-2 pb-2">
          <p className="text-[10px] font-medium uppercase tracking-[0.24em] text-muted-foreground">Theme</p>
        </div>
        <div className="space-y-1">
          {THEMES.map((t) => (
            <button
              key={t}
              className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2 text-left text-xs transition-colors duration-150 ease-productive ${t === theme ? "border-border bg-accent/78 text-accent-foreground shadow-sm" : "border-transparent text-popover-foreground hover:bg-accent/72 hover:text-accent-foreground"}`}
              onClick={() => setTheme(t)}
              aria-label={`Select ${labelFor(t)} theme`}
            >
              <span className={`inline-block h-4 w-4 rounded-full border border-white/40 shadow-sm ${THEME_SWATCHES[t]}`} aria-hidden="true" />
              <span className="flex-1">{labelFor(t)}</span>
              {t === theme ? <Check className="h-3.5 w-3.5 text-primary" /> : null}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function NamespaceSwitcher({
  token,
  namespace,
  currentUser,
  onNamespaceChange,
}: {
  token: string;
  namespace: string;
  currentUser: AuthenticatedUser | null;
  onNamespaceChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [namespaces, setNamespaces] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const loadNamespaces = useCallback(async () => {
    setLoading(true);
    try {
      const ns = await fetchNamespaces(token);
      setNamespaces(ns);
    } catch {
      // Fallback to user's allowed_namespaces if API fails
      const allowed = currentUser?.allowed_namespaces ?? [];
      if (allowed.length > 0 && !allowed.includes("*")) {
        setNamespaces(allowed);
      } else {
        setNamespaces([namespace]);
      }
    } finally {
      setLoading(false);
    }
  }, [token, currentUser, namespace]);

  useEffect(() => {
    if (open) void loadNamespaces();
  }, [open, loadNamespaces]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex h-7 max-w-[9rem] min-w-0 items-center gap-1 rounded-lg border border-border/70 bg-card/72 px-2 font-mono text-[10px] text-foreground transition-colors duration-150 ease-productive hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 sm:max-w-[12rem]"
        >
          <span className="truncate">{namespace}</span>
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 rounded-[calc(var(--radius-xl)+2px)] border border-border/70 bg-popover/96 p-1.5 shadow-lg backdrop-blur-xl" sideOffset={8}>
        {loading ? (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : namespaces.length === 0 ? (
          <p className="px-2 py-3 text-center text-xs text-muted-foreground">No namespaces available</p>
        ) : (
          <div className="max-h-56 overflow-y-auto">
            {namespaces.map((ns) => (
              <button
                key={ns}
                type="button"
                className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs transition-colors duration-150 ease-productive hover:bg-accent/72 ${
                  ns === namespace ? "bg-accent/82 font-medium shadow-sm" : ""
                }`}
                onClick={() => {
                  onNamespaceChange(ns);
                  setOpen(false);
                }}
              >
                <span className={`inline-flex h-3.5 w-3.5 items-center justify-center ${ns === namespace ? "text-primary" : "text-transparent"}`}>
                  <Check className="h-3 w-3" />
                </span>
                <span className="font-mono">{ns}</span>
              </button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

export function TopBar({
  health,
  gatewayError,
  token,
  namespace,
  isConnecting,
  authConfig,
  currentUser,
  authBusy,
  authUsername,
  authPassword,
  authEmail,
  authDisplayName,
  authPasswordConfirm,
  passwordProvider,
  registerMode,
  onTokenChange,
  onNamespaceChange,
  onAuthUsernameChange,
  onAuthPasswordChange,
  onAuthEmailChange,
  onAuthDisplayNameChange,
  onAuthPasswordConfirmChange,
  onPasswordProviderChange,
  onRegisterModeChange,
  connectionError,
  onClearConnectionError,
  onConnect,
  onPasswordSubmit,
  onStartOidc,
  onStartSaml,
  onLogout,
  onRefreshCurrentUser,
}: TopBarProps) {
  const gatewayStatus = gatewayError ? "offline" : health?.status ?? "loading";
  const isHealthy = gatewayStatus === "ok" || gatewayStatus === "healthy";
  const isLoading = gatewayStatus === "loading";
  const gatewayLabel = isHealthy ? "Healthy" : gatewayStatus === "offline" ? "Offline" : isLoading ? "Checking" : "Degraded";

  const healthStatusVariant = isHealthy ? "success" : gatewayStatus === "offline" ? "error" : isLoading ? "neutral" : "warning";
  const HealthIcon = isHealthy ? CheckCircle2 : gatewayStatus === "offline" ? XCircle : Loader2;

  return (
    <TooltipProvider delayDuration={200}>
      <header className="sticky top-0 z-50 flex h-10 flex-wrap items-center justify-between gap-x-2 gap-y-1 border-b border-sidebar-border/80 bg-sidebar/88 px-3 py-0 shadow-sm backdrop-blur-xl animate-slide-from-left md:flex-nowrap md:px-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-card/72 text-primary shadow-sm">
            <LayoutPanelTop className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0">
            <p className="text-[9px] font-medium uppercase tracking-[0.24em] text-muted-foreground">Operations Console</p>
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-xs font-semibold text-foreground">{BRAND.name}</span>
              <span className="hidden truncate text-[10px] text-muted-foreground lg:inline">{BRAND.tagline}</span>
            </div>
          </div>
        </div>

        <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <StatusBadge icon={HealthIcon} status={healthStatusVariant} className={isLoading ? "[&>svg]:animate-spin" : ""} aria-label={`Gateway status: ${gatewayLabel}`}>
                  {gatewayLabel}
                </StatusBadge>
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom">Gateway health: {gatewayStatus}</TooltipContent>
          </Tooltip>
          {token.trim() && (
            <div className="min-w-0 max-w-full">
              <NamespaceSwitcher
                token={token}
                namespace={namespace}
                currentUser={currentUser}
                onNamespaceChange={onNamespaceChange}
              />
            </div>
          )}
          {currentUser ? <Badge variant="outline" className="hidden h-5 bg-card/72 px-1.5 text-[10px] text-muted-foreground sm:inline-flex">{currentUser.role}</Badge> : null}
          <ThemePicker />
          <NotificationCenter />
          <ConnectionDialog
          connectionError={connectionError}
          onClearConnectionError={onClearConnectionError}
          token={token}
          namespace={namespace}
          isConnecting={isConnecting}
          authConfig={authConfig}
          currentUser={currentUser}
          authBusy={authBusy}
          authUsername={authUsername}
          authPassword={authPassword}
          authEmail={authEmail}
          authDisplayName={authDisplayName}
          authPasswordConfirm={authPasswordConfirm}
          passwordProvider={passwordProvider}
          registerMode={registerMode}
          onTokenChange={onTokenChange}
          onNamespaceChange={onNamespaceChange}
          onAuthUsernameChange={onAuthUsernameChange}
          onAuthPasswordChange={onAuthPasswordChange}
          onAuthEmailChange={onAuthEmailChange}
          onAuthDisplayNameChange={onAuthDisplayNameChange}
          onAuthPasswordConfirmChange={onAuthPasswordConfirmChange}
          onPasswordProviderChange={onPasswordProviderChange}
          onRegisterModeChange={onRegisterModeChange}
          onConnect={onConnect}
          onPasswordSubmit={onPasswordSubmit}
          onStartOidc={onStartOidc}
          onStartSaml={onStartSaml}
          onLogout={onLogout}
          onRefreshCurrentUser={onRefreshCurrentUser}
        />
        </div>
      </header>
    </TooltipProvider>
  );
}
