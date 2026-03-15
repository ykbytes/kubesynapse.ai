import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import {
  buildOidcLoginUrl,
  buildSamlLoginUrl,
  fetchAuthConfig,
  fetchCurrentUser,
  fetchGatewayHealth,
  loginWithPassword,
  logoutSession,
  refreshAuthSession,
  registerWithPassword,
  setOnTokenRefreshed,
} from "@/lib/api";
import type { AuthConfig, AuthenticatedUser, GatewayHealth } from "@/types";
import { toast } from "sonner";

const TOKEN_STORAGE_KEY = "ai-agent-sandbox/token";
const NAMESPACE_STORAGE_KEY = "ai-agent-sandbox/namespace";

function resolveNamespaceForUser(user: AuthenticatedUser | null, currentNamespace: string): string {
  if (!user) return currentNamespace || "default";
  const namespaces = user.allowed_namespaces ?? [];
  if (namespaces.includes("*") || namespaces.includes(currentNamespace)) return currentNamespace || "default";
  return namespaces[0] ?? "default";
}

// ── Context value type ──

export interface ConnectionContextValue {
  token: string;
  namespace: string;
  health: GatewayHealth | null;
  gatewayError: string;
  isConnecting: boolean;
  authConfig: AuthConfig | null;
  currentUser: AuthenticatedUser | null;
  authBusy: boolean;

  // Auth form fields
  authUsername: string;
  authPassword: string;
  authEmail: string;
  authDisplayName: string;
  authPasswordConfirm: string;
  passwordProvider: "local" | "ldap";
  registerMode: boolean;

  // Connection-specific error (e.g. connect/login failures)
  connectionError: string;

  // True once initializeAuth has finished (prevents flash of login page)
  authReady: boolean;

  // Setters
  setToken: (value: string) => void;
  setNamespace: (value: string) => void;
  setAuthUsername: (value: string) => void;
  setAuthPassword: (value: string) => void;
  setAuthEmail: (value: string) => void;
  setAuthDisplayName: (value: string) => void;
  setAuthPasswordConfirm: (value: string) => void;
  setPasswordProvider: (value: "local" | "ldap") => void;
  setRegisterMode: (value: boolean) => void;
  setConnectionError: (value: string) => void;

  // Actions
  handleConnect: () => Promise<boolean>;
  handlePasswordAuth: () => Promise<boolean>;
  handleLogout: () => Promise<void>;
  handleOidcStart: (providerId: string) => void;
  handleSamlStart: (providerId: string) => void;
  refreshHealth: (silent?: boolean) => Promise<GatewayHealth | null>;
  refreshCurrentUserProfile: (activeToken?: string) => Promise<{ user: AuthenticatedUser; namespace: string } | null>;
}

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

// ── Provider ──

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [namespace, setNamespace] = useState(() => localStorage.getItem(NAMESPACE_STORAGE_KEY) ?? "default");
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [gatewayError, setGatewayError] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [currentUser, setCurrentUser] = useState<AuthenticatedUser | null>(null);
  const [authBusy, setAuthBusy] = useState(false);

  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [authDisplayName, setAuthDisplayName] = useState("");
  const [authPasswordConfirm, setAuthPasswordConfirm] = useState("");
  const [passwordProvider, setPasswordProvider] = useState<"local" | "ldap">("local");
  const [registerMode, setRegisterMode] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [authReady, setAuthReady] = useState(false);

  // Persist token/namespace
  useEffect(() => { localStorage.setItem(TOKEN_STORAGE_KEY, token); }, [token]);
  useEffect(() => { localStorage.setItem(NAMESPACE_STORAGE_KEY, namespace); }, [namespace]);

  // Keep React state in sync when fetchAuthenticated silently refreshes the token
  useEffect(() => {
    setOnTokenRefreshed((newToken) => setToken(newToken));
    return () => setOnTokenRefreshed(null);
  }, []);

  // ── Internal helpers ──

  function applyAuthenticatedUser(nextUser: AuthenticatedUser, nextToken: string) {
    setToken(nextToken);
    setCurrentUser(nextUser);
    const nextNamespace = resolveNamespaceForUser(nextUser, namespace);
    if (nextNamespace !== namespace) setNamespace(nextNamespace);
    return nextNamespace;
  }

  async function refreshAuthConfiguration() {
    try {
      const nextConfig = await fetchAuthConfig();
      setAuthConfig(nextConfig);
      return nextConfig;
    } catch (err) {
      setAuthConfig(null);
      setConnectionError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  async function restoreBrowserSession(options?: { silent?: boolean }) {
    try {
      const session = await refreshAuthSession();
      applyAuthenticatedUser(session.user, session.access_token);
      setAuthPassword("");
      return { token: session.access_token, user: session.user };
    } catch (err) {
      if (!options?.silent) setConnectionError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  const doRefreshHealth = useCallback(async (silent = false) => {
    try {
      const nextHealth = await fetchGatewayHealth();
      setHealth(nextHealth);
      setGatewayError("");
      return nextHealth;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setGatewayError(message);
      if (!silent) setHealth(null);
      return null;
    }
  }, []);

  const doRefreshCurrentUserProfile = useCallback(
    async (activeToken = token) => {
      if (!activeToken.trim()) { setCurrentUser(null); return null; }
      const nextUser = await fetchCurrentUser(activeToken);
      const nextNamespace = applyAuthenticatedUser(nextUser, activeToken);
      return { user: nextUser, namespace: nextNamespace };
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [token, namespace],
  );

  // ── Effects ──

  // Health polling
  useEffect(() => {
    void doRefreshHealth();
    const timer = window.setInterval(() => void doRefreshHealth(true), 15_000);
    return () => window.clearInterval(timer);
  }, [doRefreshHealth]);

  // Auth init
  useEffect(() => {
    let cancelled = false;
    async function initializeAuth() {
      try {
        const nextConfig = await refreshAuthConfiguration();
        if (cancelled) return;
        if (nextConfig) {
          if (token.trim()) {
            try {
              const refreshed = await doRefreshCurrentUserProfile(token);
              if (!cancelled && !refreshed) setCurrentUser(null);
            } catch {
              const restored = nextConfig.browser_auth_enabled ? await restoreBrowserSession({ silent: true }) : null;
              if (!restored && !cancelled) { setToken(""); setCurrentUser(null); }
            }
          } else if (nextConfig.browser_auth_enabled) {
            await restoreBrowserSession({ silent: true });
          }
        }
        const params = new URLSearchParams(window.location.search);
        if (params.has("auth")) {
          const authStatus = params.get("auth");
          if (authStatus === "success") toast.success("Single sign-on session established.");
          else if (authStatus === "error") toast.error("Single sign-on failed.");
          window.history.replaceState({}, document.title, window.location.pathname);
        }
      } finally {
        if (!cancelled) setAuthReady(true);
      }
    }
    void initializeAuth();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auth config sync
  useEffect(() => {
    const providers = authConfig?.password_providers ?? [];
    if (providers.length > 0 && !providers.includes(passwordProvider))
      setPasswordProvider(providers.includes("ldap") ? "ldap" : "local");
    if (!authConfig?.registration_enabled && registerMode) setRegisterMode(false);
    if (authConfig && !authConfig.bootstrap_complete && authConfig.registration_enabled && !registerMode) setRegisterMode(true);
  }, [authConfig, passwordProvider, registerMode]);

  // Namespace resolve on user change
  useEffect(() => {
    if (!currentUser) return;
    const nextNamespace = resolveNamespaceForUser(currentUser, namespace);
    if (nextNamespace !== namespace) setNamespace(nextNamespace);
  }, [currentUser, namespace]);

  // ── Handlers ──

  const handleConnect = useCallback(async (): Promise<boolean> => {
    if (!token.trim()) { setConnectionError("Enter a bearer token or sign in with a managed account."); return false; }
    setIsConnecting(true);
    setConnectionError("");
    try {
      await doRefreshHealth();
      await doRefreshCurrentUserProfile(token);
      return true;
    } catch (err) {
      setCurrentUser(null);
      setConnectionError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setIsConnecting(false);
    }
  }, [token, doRefreshHealth, doRefreshCurrentUserProfile, setConnectionError]);

  const handlePasswordAuth = useCallback(async (): Promise<boolean> => {
    setAuthBusy(true);
    setConnectionError("");
    try {
      const wasRegistering = registerMode && passwordProvider === "local";
      const session = wasRegistering
        ? await registerWithPassword(authUsername, authPassword, authEmail, authDisplayName || authUsername)
        : await loginWithPassword(authUsername, authPassword, passwordProvider);
      applyAuthenticatedUser(session.user, session.access_token);
      setAuthPassword("");
      setAuthPasswordConfirm("");
      if (wasRegistering) { setRegisterMode(false); setAuthEmail(""); setAuthDisplayName(""); }
      await doRefreshHealth(true);
      toast.success(wasRegistering ? "Account created." : "Signed in.");
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setConnectionError(message);
      toast.error(message);
      return false;
    } finally {
      setAuthBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authUsername, authPassword, authEmail, authDisplayName, passwordProvider, registerMode, doRefreshHealth, setConnectionError]);

  const handleLogout = useCallback(async () => {
    setAuthBusy(true);
    try { await logoutSession(token); } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setAuthBusy(false);
      setToken("");
      setCurrentUser(null);
      setAuthPassword("");
      setConnectionError("");
    }
  }, [token, setConnectionError]);

  const handleOidcStart = useCallback((providerId: string) => {
    window.location.assign(buildOidcLoginUrl(providerId, window.location.pathname));
  }, []);

  const handleSamlStart = useCallback((providerId: string) => {
    window.location.assign(buildSamlLoginUrl(providerId, window.location.pathname));
  }, []);

  return (
    <ConnectionContext.Provider
      value={{
        token, namespace, health, gatewayError, isConnecting,
        authConfig, currentUser, authBusy, connectionError, authReady,
        authUsername, authPassword, authEmail, authDisplayName, authPasswordConfirm,
        passwordProvider, registerMode,
        setToken, setNamespace,
        setAuthUsername, setAuthPassword, setAuthEmail, setAuthDisplayName, setAuthPasswordConfirm,
        setPasswordProvider, setRegisterMode, setConnectionError,
        handleConnect, handlePasswordAuth, handleLogout,
        handleOidcStart, handleSamlStart,
        refreshHealth: doRefreshHealth,
        refreshCurrentUserProfile: doRefreshCurrentUserProfile,
      }}
    >
      {children}
    </ConnectionContext.Provider>
  );
}

// ── Hook ──

export function useConnection() {
  const ctx = useContext(ConnectionContext);
  if (!ctx) throw new Error("useConnection must be used within ConnectionProvider");
  return ctx;
}
