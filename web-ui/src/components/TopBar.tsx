import { Check, CheckCircle2, ChevronDown, LayoutPanelTop, Loader2, Palette, XCircle } from "lucide-react";
import { useRef, useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { StatusBadge } from "./StatusBadge";
import { ConnectionDialog } from "./ConnectionDialog";
import { NotificationCenter } from "./NotificationCenter";
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
  dark: "bg-zinc-700",
  light: "bg-zinc-200",
  midnight: "bg-blue-700",
  forest: "bg-emerald-700",
};

function ThemePicker() {
  const { theme, setTheme, labelFor } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="icon" className="h-8 w-8 border-border/60 text-foreground hover:bg-accent" onClick={() => setOpen((v) => !v)} aria-label="Change theme">
            <Palette className="h-4 w-4" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="bottom">Theme</TooltipContent>
      </Tooltip>
      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-50 min-w-[160px] rounded-xl border border-border/50 bg-popover/95 backdrop-blur-md p-1.5 shadow-lg animate-scale-in">
          {THEMES.map((t) => (
            <button
              key={t}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs text-popover-foreground transition-all duration-150 hover:bg-accent ${t === theme ? "bg-accent font-medium shadow-sm" : ""}`}
              onClick={() => { setTheme(t); setOpen(false); }}
            >
              <span className={`inline-block h-3.5 w-3.5 rounded-full border-2 border-border shadow-sm transition-transform duration-200 hover:scale-125 ${THEME_SWATCHES[t]}`} />
              {labelFor(t)}
            </button>
          ))}
        </div>
      )}
    </div>
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
          className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-transparent px-2 py-1 font-mono text-xs text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {namespace}
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52 p-1" sideOffset={6}>
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
                className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-accent ${
                  ns === namespace ? "bg-accent font-medium" : ""
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

  const healthStatusVariant = isHealthy ? "success" : gatewayStatus === "offline" ? "error" : isLoading ? "neutral" : "warning";
  const HealthIcon = isHealthy ? CheckCircle2 : gatewayStatus === "offline" ? XCircle : Loader2;

  return (
    <TooltipProvider delayDuration={200}>
      <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-border/50 bg-sidebar/80 backdrop-blur-md px-4 shadow-sm animate-slide-from-left">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 text-primary shadow-md shadow-primary/15 transition-transform duration-300 hover:scale-110 hover:rotate-3">
            <LayoutPanelTop className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {BRAND.name}
            </span>
            <span className="text-sm font-semibold text-foreground">{BRAND.tagline}</span>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <span>
                <StatusBadge icon={HealthIcon} status={healthStatusVariant} className={isLoading ? "[&>svg]:animate-spin" : ""}>
                  {gatewayStatus}
                </StatusBadge>
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom">Gateway health: {gatewayStatus}</TooltipContent>
          </Tooltip>
          {token.trim() && (
            <NamespaceSwitcher
              token={token}
              namespace={namespace}
              currentUser={currentUser}
              onNamespaceChange={onNamespaceChange}
            />
          )}
          {currentUser ? <Badge variant="secondary">{currentUser.role}</Badge> : null}
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
