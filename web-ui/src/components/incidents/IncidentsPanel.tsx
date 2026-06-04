import { useState, useCallback } from "react";
import { IncidentDashboard } from "./IncidentDashboard";
import { IncidentDetail } from "./IncidentDetail";
import {
  createIncident,
  escalateIncident,
  getIncident,
  getIncidentTimeline,
  listIncidents,
  updateIncidentStatus,
} from "../../lib/api";

interface IncidentsPanelProps {
  token: string;
  namespace: string;
}

export function IncidentsPanel({ token, namespace }: IncidentsPanelProps) {
  const [selectedIncident, setSelectedIncident] = useState<string | null>(null);

  const getToken = useCallback(() => token, [token]);
  const getNamespace = useCallback(() => namespace, [namespace]);

  const fireExampleAlert = useCallback(async () => {
    const fingerprint = `demo-${Date.now().toString(36)}`;
    const alertname = "DemoHighLatency";
    const now = new Date().toISOString();
    await createIncident(token, namespace, {
      name: `alert-${alertname}-${fingerprint.slice(-12)}`,
      title: "Demo: Checkout API p95 latency above 3s",
      description:
        "Synthetic Alertmanager v4 alert fired by the Incidents UI. Use this to validate the on-call workflow end-to-end.",
      severity: "warning",
      source: "alertmanager",
      labels: {
        alertname,
        severity: "warning",
        service: "checkout-api",
        environment: "demo",
        fingerprint,
      },
      annotations: {
        summary: "Checkout API p95 latency above 3s",
        description:
          "p95 latency 3.4s for checkout-api in prod-aks-eastus. Two OOMKilled restarts in the last 5m.",
        runbook_url: "https://runbooks.example.com/checkout-api/latency",
      },
      assigned_agent: "secure-incident-commander",
      escalation_timeout_minutes: 15,
      auto_acknowledge: true,
    });
    void now;
  }, [token, namespace]);

  if (selectedIncident) {
    return (
      <IncidentDetail
        name={selectedIncident}
        onBack={() => setSelectedIncident(null)}
        getToken={getToken}
        getNamespace={getNamespace}
        api={{
          getIncident,
          updateIncidentStatus,
          escalateIncident,
          getIncidentTimeline,
        }}
      />
    );
  }

  return (
    <IncidentDashboard
      setSelectedIncident={setSelectedIncident}
      getToken={getToken}
      getNamespace={getNamespace}
      onFireExampleAlert={fireExampleAlert}
      api={{
        listIncidents,
        updateIncidentStatus,
        createIncident,
      }}
    />
  );
}
