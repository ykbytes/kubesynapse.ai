import { useState, useMemo } from "react";
import { AlertCircle, Check, KeyRound, LayoutPanelTop, Loader2, UserPlus, X } from "lucide-react";
import { useConnection } from "@/contexts/ConnectionContext";
import { BRAND } from "@/lib/brand";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

type AuthTab = "password" | "token";

const EMAIL_RE = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

export function AuthPage() {
  const conn = useConnection();
  const [activeTab, setActiveTab] = useState<AuthTab>("password");
  const [registerError, setRegisterError] = useState("");

  const passwordProviders = conn.authConfig?.password_providers ?? [];
  const oidcProviders = conn.authConfig?.oidc_providers ?? [];
  const samlProviders = conn.authConfig?.saml_providers ?? [];
  const hasPasswordProviders = passwordProviders.length > 0;
  const hasSsoProviders = oidcProviders.length > 0 || samlProviders.length > 0;

  const isBootstrapping =
    conn.authConfig != null &&
    !conn.authConfig.bootstrap_complete &&
    conn.authConfig.registration_enabled;

  // Inline password strength checks
  const passwordChecks = useMemo(() => {
    const p = conn.authPassword;
    return {
      length: p.length >= 8,
      upper: /[A-Z]/.test(p),
      lower: /[a-z]/.test(p),
      digit: /\d/.test(p),
      get valid() { return this.length && this.upper && this.lower && this.digit; },
    };
  }, [conn.authPassword]);

  const passwordsMatch = conn.authPassword === conn.authPasswordConfirm;
  const emailValid = !conn.authEmail || EMAIL_RE.test(conn.authEmail);

  async function handlePasswordSubmit() {
    setRegisterError("");
    conn.setConnectionError("");

    if (conn.registerMode && conn.passwordProvider === "local") {
      if (conn.authUsername.trim().length < 3) {
        setRegisterError("Username must be at least 3 characters.");
        return;
      }
      if (!passwordChecks.valid) {
        setRegisterError("Password must be at least 8 characters with an uppercase letter, a lowercase letter, and a digit.");
        return;
      }
      if (!passwordsMatch) {
        setRegisterError("Passwords do not match.");
        return;
      }
      if (conn.authEmail && !emailValid) {
        setRegisterError("Please enter a valid email address.");
        return;
      }
    }

    await conn.handlePasswordAuth();
  }

  async function handleTokenConnect() {
    await conn.handleConnect();
  }

  const displayError = registerError || conn.connectionError;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background p-4">
      {/* Logo + title */}
      <div className="mb-8 flex flex-col items-center gap-3 animate-fade-in">
        <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10 text-primary animate-bounce-in">
          <LayoutPanelTop className="h-8 w-8" />
        </div>
        <div className="text-center">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{BRAND.name}</h1>
          <p className="text-sm text-muted-foreground">{BRAND.tagline}</p>
        </div>
      </div>

      {/* Auth card */}
      <div className="w-full max-w-md animate-scale-in" style={{ animationDelay: "0.1s" }}>
        <div className="rounded-xl border border-border bg-card p-6 shadow-lg">
          {/* Bootstrapping banner */}
          {isBootstrapping && (
            <div className="mb-4 rounded-md border border-primary/30 bg-primary/5 px-3 py-3 text-sm">
              <div className="flex items-center gap-2 font-medium text-primary">
                <UserPlus className="h-4 w-4" />
                Welcome — create the first admin account
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                No users exist yet. Register below to become the administrator.
              </p>
            </div>
          )}

          {/* Tab switcher: Password vs Token */}
          {(hasPasswordProviders || hasSsoProviders) && (
            <div className="mb-4 flex rounded-lg border border-border bg-muted/30 p-1">
              <button
                type="button"
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${activeTab === "password" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setActiveTab("password")}
              >
                Sign In
              </button>
              <button
                type="button"
                className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${activeTab === "token" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                onClick={() => setActiveTab("token")}
              >
                <span className="flex items-center justify-center gap-1.5">
                  <KeyRound className="h-3.5 w-3.5" />
                  API Token
                </span>
              </button>
            </div>
          )}

          {/* ─── Password / SSO tab ─── */}
          {activeTab === "password" && (hasPasswordProviders || hasSsoProviders) ? (
            <div className="grid gap-4">
              {/* Register / Sign-in toggle */}
              {hasPasswordProviders && (
                <>
                  <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold text-foreground">
                      {conn.registerMode ? "Create Account" : "Sign In"}
                    </h2>
                    {passwordProviders.includes("local") && conn.authConfig?.registration_enabled && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => { setRegisterError(""); conn.setRegisterMode(!conn.registerMode); }}
                      >
                        {conn.registerMode ? "Sign in instead" : "Create account"}
                      </Button>
                    )}
                  </div>

                  {/* Provider selector (local vs LDAP) */}
                  {passwordProviders.length > 1 && (
                    <div className="flex gap-2">
                      {passwordProviders.map((provider) => {
                        const v = provider === "ldap" ? "ldap" as const : "local" as const;
                        return (
                          <Button
                            key={provider}
                            type="button"
                            variant={conn.passwordProvider === v ? "default" : "outline"}
                            size="sm"
                            onClick={() => conn.setPasswordProvider(v)}
                          >
                            {v === "ldap" ? "LDAP / AD" : "Local"}
                          </Button>
                        );
                      })}
                    </div>
                  )}

                  {/* Username */}
                  <div className="grid gap-1.5">
                    <Label htmlFor="auth-username">Username</Label>
                    <Input
                      id="auth-username"
                      value={conn.authUsername}
                      onChange={(e) => conn.setAuthUsername(e.target.value)}
                      placeholder={conn.passwordProvider === "ldap" ? "directory username" : "username"}
                      autoComplete="username"
                      onKeyDown={(e) => { if (e.key === "Enter" && !conn.registerMode) void handlePasswordSubmit(); }}
                    />
                  </div>

                  {/* Email (register only) */}
                  {conn.registerMode && conn.passwordProvider === "local" && (
                    <div className="grid gap-1.5">
                      <Label htmlFor="auth-email">Email</Label>
                      <Input
                        id="auth-email"
                        type="email"
                        value={conn.authEmail}
                        onChange={(e) => conn.setAuthEmail(e.target.value)}
                        placeholder="name@example.com"
                        autoComplete="email"
                      />
                      {conn.authEmail && !emailValid && (
                        <p className="text-xs text-destructive">Please enter a valid email address.</p>
                      )}
                    </div>
                  )}

                  {/* Display name (register only) */}
                  {conn.registerMode && conn.passwordProvider === "local" && (
                    <div className="grid gap-1.5">
                      <Label htmlFor="auth-display-name">Display Name</Label>
                      <Input
                        id="auth-display-name"
                        value={conn.authDisplayName}
                        onChange={(e) => conn.setAuthDisplayName(e.target.value)}
                        placeholder="How you want to be known (optional)"
                      />
                    </div>
                  )}

                  {/* Password */}
                  <div className="grid gap-1.5">
                    <Label htmlFor="auth-password">Password</Label>
                    <Input
                      id="auth-password"
                      type="password"
                      value={conn.authPassword}
                      onChange={(e) => conn.setAuthPassword(e.target.value)}
                      placeholder={conn.registerMode ? "Min 8 chars, upper, lower, digit" : "Enter password"}
                      autoComplete={conn.registerMode ? "new-password" : "current-password"}
                      onKeyDown={(e) => { if (e.key === "Enter" && !conn.registerMode) void handlePasswordSubmit(); }}
                    />
                    {conn.registerMode && conn.passwordProvider === "local" && conn.authPassword.length > 0 && (
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                        {(["length", "upper", "lower", "digit"] as const).map((k) => {
                          const ok = passwordChecks[k];
                          const label = { length: "8+ chars", upper: "Uppercase", lower: "Lowercase", digit: "Digit" }[k];
                          return (
                            <span key={k} className={`flex items-center gap-0.5 ${ok ? "text-emerald-600" : "text-muted-foreground"}`}>
                              {ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                              {label}
                            </span>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* Confirm password (register only) */}
                  {conn.registerMode && conn.passwordProvider === "local" && (
                    <div className="grid gap-1.5">
                      <Label htmlFor="auth-password-confirm">Confirm Password</Label>
                      <Input
                        id="auth-password-confirm"
                        type="password"
                        value={conn.authPasswordConfirm}
                        onChange={(e) => conn.setAuthPasswordConfirm(e.target.value)}
                        placeholder="Re-enter your password"
                        autoComplete="new-password"
                        onKeyDown={(e) => { if (e.key === "Enter") void handlePasswordSubmit(); }}
                      />
                      {conn.authPasswordConfirm && !passwordsMatch && (
                        <p className="text-xs text-destructive">Passwords do not match.</p>
                      )}
                    </div>
                  )}

                  {/* Submit */}
                  <Button onClick={() => void handlePasswordSubmit()} disabled={conn.authBusy} className="w-full gap-2">
                    {conn.authBusy && <Loader2 className="h-4 w-4 animate-spin" />}
                    {conn.authBusy
                      ? "Working..."
                      : conn.registerMode && conn.passwordProvider === "local"
                        ? "Create account"
                        : "Sign in"}
                  </Button>
                </>
              )}

              {/* SSO providers */}
              {hasSsoProviders && (
                <>
                  {hasPasswordProviders && (
                    <div className="flex items-center gap-3">
                      <Separator className="flex-1" />
                      <span className="text-xs text-muted-foreground">or continue with</span>
                      <Separator className="flex-1" />
                    </div>
                  )}
                  <div className="flex flex-wrap gap-2">
                    {oidcProviders.map((p) => (
                      <Button key={p.id} variant="outline" className="flex-1" onClick={() => conn.handleOidcStart(p.id)}>
                        {p.name}
                      </Button>
                    ))}
                    {samlProviders.map((p) => (
                      <Button key={p.id} variant="outline" className="flex-1" onClick={() => conn.handleSamlStart(p.id)}>
                        {p.name} (SAML)
                      </Button>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : (
            /* ─── Token tab (or fallback when no password providers) ─── */
            <div className="grid gap-4">
              <h2 className="text-lg font-semibold text-foreground">Connect with API Token</h2>
              <div className="grid gap-1.5">
                <Label htmlFor="namespace">Namespace</Label>
                <Input
                  id="namespace"
                  value={conn.namespace}
                  onChange={(e) => conn.setNamespace(e.target.value)}
                  placeholder="default"
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="token">Bearer Token</Label>
                <Input
                  id="token"
                  type="password"
                  value={conn.token}
                  onChange={(e) => conn.setToken(e.target.value)}
                  placeholder="Paste your API token"
                  autoComplete="off"
                  onKeyDown={(e) => { if (e.key === "Enter") void handleTokenConnect(); }}
                />
              </div>
              <Button onClick={() => void handleTokenConnect()} disabled={conn.isConnecting} className="w-full gap-2">
                {conn.isConnecting && <Loader2 className="h-4 w-4 animate-spin" />}
                {conn.isConnecting ? "Connecting..." : "Connect"}
              </Button>
            </div>
          )}

          {/* Error display */}
          {displayError && (
            <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {displayError}
            </div>
          )}
        </div>

        {/* Gateway status footer */}
        <div className="mt-4 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <span className={`h-2 w-2 rounded-full ${conn.gatewayError ? "bg-destructive" : conn.health ? "bg-emerald-500" : "bg-muted-foreground"}`} />
          {conn.gatewayError
            ? "Gateway unreachable"
            : conn.health
              ? `Gateway ${conn.health.status} · ${conn.health.auth_mode} auth`
              : "Connecting to gateway..."}
        </div>
      </div>
    </div>
  );
}
