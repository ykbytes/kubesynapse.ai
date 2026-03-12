import { useCallback, useEffect, useState } from "react";
import { fetchGatewayHealth } from "@/lib/api";
import type { GatewayHealth } from "@/types";

const TOKEN_STORAGE_KEY = "ai-agent-sandbox/token";
const NAMESPACE_STORAGE_KEY = "ai-agent-sandbox/namespace";

export function useConnection() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? "");
  const [namespace, setNamespace] = useState(() => localStorage.getItem(NAMESPACE_STORAGE_KEY) ?? "default");
  const [health, setHealth] = useState<GatewayHealth | null>(null);
  const [gatewayError, setGatewayError] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);

  useEffect(() => {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }, [token]);

  useEffect(() => {
    localStorage.setItem(NAMESPACE_STORAGE_KEY, namespace);
  }, [namespace]);

  const refreshHealth = useCallback(async (silent = false) => {
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

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(true), 15000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  const connect = useCallback(async () => {
    setIsConnecting(true);
    await refreshHealth();
    setIsConnecting(false);
  }, [refreshHealth]);

  return {
    token,
    setToken,
    namespace,
    setNamespace,
    health,
    gatewayError,
    isConnecting,
    connect,
    refreshHealth,
  };
}
