import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Cable,
  FileCode2,
  HeartPulse,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useConnection } from "@/contexts/ConnectionContext";
import {
  apiErrorMessage,
  createConnectorPlugin,
  createObservationPolicy,
  createObservationTarget,
  deleteConnectorPlugin,
  deleteObservationPolicy,
  deleteObservationTarget,
  fetchConnectorPlugin,
  fetchObservationPolicy,
  fetchObservationTarget,
  fetchObservabilityOverview,
  updateConnectorPlugin,
  updateObservationPolicy,
  updateObservationTarget,
  type CreateConnectorPluginPayload,
  type CreateObservationPolicyPayload,
  type CreateObservationTargetPayload,
  type ObservabilityConnector,
  type ObservabilityConnectorDetail,
  type ObservabilityOverview,
  type ObservabilityPolicy,
  type ObservabilityPolicyDetail,
  type ObservabilityReport,
  type ObservabilityTargetDetail,
  type ObservabilityTargetSummary,
  type UpdateConnectorPluginPayload,
  type UpdateObservationPolicyPayload,
  type UpdateObservationTargetPayload,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ResourceTab = "targets" | "reports" | "connectors" | "policies";
type EditableResourceTab = Exclude<ResourceTab, "reports">;
type EditorView = "form" | "raw";

type SelectedResourceDetail =
  | { kind: "targets"; resource: ObservabilityTargetDetail }
  | { kind: "policies"; resource: ObservabilityPolicyDetail }
  | { kind: "connectors"; resource: ObservabilityConnectorDetail }
  | { kind: "reports"; resource: ObservabilityReport };

type EditorState = {
  kind: EditableResourceTab;
  mode: "create" | "edit";
} | null;

type SummaryCardConfig = {
  key: string;
  label: string;
  value: string;
  helper: string;
  accent: string;
  icon: typeof Activity;
};

type EditorGuide = {
  title: string;
  summary: string;
  steps: string[];
};

type TargetFormState = {
  name: string;
  description: string;
  targetType: string;
  connectorRef: string;
  endpoint: string;
  scrapeInterval: string;
  policyRef: string;
  labelsJson: string;
  selectorJson: string;
  credentialsJson: string;
  tlsConfigJson: string;
};

type PolicyFormState = {
  name: string;
  description: string;
  retentionDays: string;
  downsamplingAfter: string;
  downsamplingResolution: string;
  anomalyEnabled: string;
  anomalyAlgorithm: string;
  sensitivity: string;
  windowSize: string;
  evaluationInterval: string;
  metricsCsv: string;
  webhookUrl: string;
  natsSubject: string;
  alertRulesJson: string;
};

type ConnectorFormState = {
  name: string;
  description: string;
  image: string;
  protocol: string;
  port: string;
  capabilitiesCsv: string;
  healthEndpoint: string;
  secretRef: string;
  requestsCpu: string;
  requestsMemory: string;
  limitsCpu: string;
  limitsMemory: string;
  envJson: string;
};

const TARGET_TYPES = ["prometheus", "kubernetes-api", "snmp", "gnmi", "nats", "custom"] as const;
const POLICY_ALGORITHMS = ["ensemble", "isolation-forest", "prophet"] as const;
const CONNECTOR_PROTOCOLS = ["grpc", "http"] as const;
const EMPTY_OPTION = "__none__";

const EDITOR_GUIDES: Record<EditableResourceTab, EditorGuide> = {
  targets: {
    title: "Targets tell the platform what to watch",
    summary: "A target points at the real thing you care about, such as the Kubernetes API, a Prometheus endpoint, or another system. The connector collects the data, and the policy decides how the platform should interpret it.",
    steps: [
      "Pick the target type so kubesynapse knows what kind of system you are observing.",
      "Attach a connector that can actually talk to that system and collect data from it.",
      "Optionally attach a policy so the collected signals get retained, analyzed, and turned into reports or alerts.",
    ],
  },
  policies: {
    title: "Policies explain how telemetry should be interpreted",
    summary: "A policy does not collect data by itself. Instead, it defines how long telemetry is retained, which anomalies to detect, and how alerting or notifications should behave after data arrives from a target.",
    steps: [
      "Set retention so the platform knows how long to keep the data and when to downsample it.",
      "Choose anomaly settings so the platform can detect unusual patterns instead of relying only on static thresholds.",
      "Add notification outputs so findings can leave the observability pipeline and reach humans or automations.",
    ],
  },
  connectors: {
    title: "Connectors explain how kubesynapse reaches a source system",
    summary: "A connector is the collector plugin. It knows the protocol, image, port, and capabilities required to talk to an external source and normalize that source into observability data kubesynapse can work with.",
    steps: [
      "Choose the image that implements the protocol you need, such as the Kubernetes API or Prometheus scraping.",
      "Declare capabilities so operators can see what kinds of targets this connector supports.",
      "Add health, secret, and environment settings only when the connector needs extra runtime context.",
    ],
  },
};

const EMPTY_TARGET_FORM: TargetFormState = {
  name: "",
  description: "Describe the system this target watches, why it matters, and what kind of health or behavior you expect kubesynapse to evaluate.",
  targetType: "kubernetes-api",
  connectorRef: "",
  endpoint: "",
  scrapeInterval: "30s",
  policyRef: "",
  labelsJson: "",
  selectorJson: "",
  credentialsJson: "",
  tlsConfigJson: JSON.stringify({ insecureSkipVerify: true }, null, 2),
};

const EMPTY_POLICY_FORM: PolicyFormState = {
  name: "",
  description: "Describe how this policy should interpret collected telemetry, what it should retain, and which kinds of anomalies or alerts it is responsible for.",
  retentionDays: "30",
  downsamplingAfter: "7d",
  downsamplingResolution: "5m",
  anomalyEnabled: "true",
  anomalyAlgorithm: "ensemble",
  sensitivity: "0.7",
  windowSize: "1h",
  evaluationInterval: "5m",
  metricsCsv: "",
  webhookUrl: "",
  natsSubject: "aiops.alerts",
  alertRulesJson: "[]",
};

const EMPTY_CONNECTOR_FORM: ConnectorFormState = {
  name: "",
  description: "Describe what this connector talks to, how it collects data, and what kinds of targets it is meant to support inside the observability pipeline.",
  image: "",
  protocol: "grpc",
  port: "9090",
  capabilitiesCsv: "kubernetes-api",
  healthEndpoint: "/healthz",
  secretRef: "",
  requestsCpu: "50m",
  requestsMemory: "64Mi",
  limitsCpu: "200m",
  limitsMemory: "256Mi",
  envJson: "[]",
};

function titleCase(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function createTargetDraftSpec(form: TargetFormState = EMPTY_TARGET_FORM): Record<string, unknown> {
  const labels = parseOptionalJson(form.labelsJson, "Labels");
  const selector = parseOptionalJson(form.selectorJson, "Selector");
  const credentials = parseOptionalJson(form.credentialsJson, "Credentials");
  const tlsConfig = parseOptionalJson(form.tlsConfigJson, "TLS config");

  return {
    description: form.description.trim() || undefined,
    targetType: form.targetType.trim() || EMPTY_TARGET_FORM.targetType,
    connectorRef: form.connectorRef.trim() || "",
    endpoint: form.endpoint.trim() || undefined,
    scrapeInterval: form.scrapeInterval.trim() || EMPTY_TARGET_FORM.scrapeInterval,
    policyRef: form.policyRef.trim() || undefined,
    labels: labels && !Array.isArray(labels) ? labels : undefined,
    selector: selector && !Array.isArray(selector) ? selector : undefined,
    credentials: credentials && !Array.isArray(credentials) ? credentials : undefined,
    tlsConfig: tlsConfig && !Array.isArray(tlsConfig) ? tlsConfig : { insecureSkipVerify: true },
  };
}

function createPolicyDraftSpec(form: PolicyFormState = EMPTY_POLICY_FORM): Record<string, unknown> {
  const alertRules = parseOptionalJson(form.alertRulesJson, "Alert rules");
  const sensitivity = parseNumericInput(form.sensitivity, "Sensitivity");
  const retentionDays = parseNumericInput(form.retentionDays, "Retention days");
  const metrics = form.metricsCsv
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  return {
    description: form.description.trim() || undefined,
    retention: {
      days: retentionDays ?? 30,
      downsampling: {
        after: form.downsamplingAfter.trim() || "7d",
        resolution: form.downsamplingResolution.trim() || "5m",
      },
    },
    anomalyDetection: {
      enabled: form.anomalyEnabled === "true",
      algorithm: form.anomalyAlgorithm || "ensemble",
      sensitivity: sensitivity ?? 0.7,
      windowSize: form.windowSize.trim() || "1h",
      evaluationInterval: form.evaluationInterval.trim() || "5m",
      metrics: metrics.length > 0 ? metrics : undefined,
    },
    notifications: {
      webhookUrl: form.webhookUrl.trim() || undefined,
      natsSubject: form.natsSubject.trim() || "aiops.alerts",
    },
    alertRules: Array.isArray(alertRules) ? alertRules : [],
  };
}

function createConnectorDraftSpec(form: ConnectorFormState = EMPTY_CONNECTOR_FORM): Record<string, unknown> {
  const env = parseOptionalJson(form.envJson, "Environment entries");
  const port = parseNumericInput(form.port, "Port");
  const capabilities = form.capabilitiesCsv
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  return {
    description: form.description.trim() || undefined,
    image: form.image.trim() || undefined,
    protocol: form.protocol || EMPTY_CONNECTOR_FORM.protocol,
    port: port ?? 9090,
    capabilities: capabilities.length > 0 ? capabilities : ["kubernetes-api"],
    healthEndpoint: form.healthEndpoint.trim() || "/healthz",
    secretRef: form.secretRef.trim() || undefined,
    resources: {
      requests: {
        cpu: form.requestsCpu.trim() || "50m",
        memory: form.requestsMemory.trim() || "64Mi",
      },
      limits: {
        cpu: form.limitsCpu.trim() || "200m",
        memory: form.limitsMemory.trim() || "256Mi",
      },
    },
    env: Array.isArray(env) ? env : [],
  };
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function safeJsonStringify(value: unknown): string {
  if (value == null || value === "") return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "";
  }
}

function parseOptionalJson(value: string, label: string): Record<string, unknown> | Array<unknown> | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed) as Record<string, unknown> | Array<unknown>;
  } catch {
    throw new Error(`${label} must be valid JSON`);
  }
}

function parseNumericInput(value: string, label: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) throw new Error(`${label} must be numeric`);
  return parsed;
}

function getStatusBadgeVariant(status: string | null | undefined): "default" | "secondary" | "destructive" | "outline" {
  const normalized = (status ?? "").toLowerCase();
  if (normalized.includes("fail") || normalized.includes("error") || normalized.includes("critical")) return "destructive";
  if (normalized.includes("degrad") || normalized.includes("warning") || normalized.includes("pending")) return "secondary";
  if (normalized.includes("active") || normalized.includes("healthy") || normalized.includes("ready") || normalized.includes("complete")) return "default";
  return "outline";
}

function findConnectorTargetCount(overview: ObservabilityOverview | null, connectorName: string): number {
  if (!overview) return 0;
  return overview.targets.filter((target) => target.connectorRef === connectorName).length;
}

function findPolicyTargetCount(overview: ObservabilityOverview | null, policyName: string): number {
  if (!overview) return 0;
  return overview.targets.filter((target) => target.policyRef === policyName).length;
}

function findTargetReportCount(overview: ObservabilityOverview | null, targetName: string): number {
  if (!overview) return 0;
  return overview.reports.filter((report) => report.targetRef === targetName).length;
}

function buildTargetPurposeText(resource: ObservabilityTargetDetail): string {
  const endpoint = resource.spec.endpoint ? ` at ${resource.spec.endpoint}` : "";
  const policy = resource.spec.policyRef ? ` It is evaluated by policy ${resource.spec.policyRef}.` : " No policy is attached yet, so this target currently defines scope more than evaluation rules.";
  const selector = resource.spec.selector?.matchLabels && Object.keys(resource.spec.selector.matchLabels).length > 0
    ? ` Discovery is narrowed by labels ${Object.entries(resource.spec.selector.matchLabels).map(([key, value]) => `${key}=${value}`).join(", ")}.`
    : "";
  return `${resource.metadata.name} watches ${resource.spec.targetType} telemetry through connector ${resource.spec.connectorRef}${endpoint}.${policy}${selector}`;
}

function buildPolicyPurposeText(resource: ObservabilityPolicyDetail): string {
  const retentionDays = resource.spec.retention?.days ?? 30;
  const algorithm = resource.spec.anomalyDetection?.enabled
    ? resource.spec.anomalyDetection?.algorithm ?? "ensemble"
    : "manual-only";
  const ruleCount = resource.spec.alertRules?.length ?? 0;
  const destination = resource.spec.notifications?.natsSubject
    ? ` Findings are routed to ${resource.spec.notifications.natsSubject}.`
    : resource.spec.notifications?.webhookUrl
      ? ` Findings are posted to ${resource.spec.notifications.webhookUrl}.`
      : " No outbound notification channel is configured yet.";
  return `${resource.metadata.name} keeps telemetry for ${retentionDays} days, evaluates it with ${algorithm}, and currently defines ${ruleCount} explicit alert rule${ruleCount === 1 ? "" : "s"}.${destination}`;
}

function buildConnectorPurposeText(resource: ObservabilityConnectorDetail): string {
  const capabilities = resource.spec.capabilities.length > 0
    ? resource.spec.capabilities.join(", ")
    : "custom sources";
  return `${resource.metadata.name} is the collection plugin. It exposes ${resource.spec.protocol.toUpperCase()} on port ${resource.spec.port ?? 9090}, runs image ${resource.spec.image}, and is intended to collect ${capabilities} telemetry.`;
}

function buildReportSummaryText(resource: ObservabilityReport): string {
  if (resource.summary) return resource.summary;
  if (resource.findingsCount > 0) {
    return `${resource.name} contains ${resource.findingsCount} finding${resource.findingsCount === 1 ? "" : "s"} for target ${resource.targetRef}. Open the finding cards below to see what drift was detected and what action is recommended.`;
  }
  return `${resource.name} is the evaluation output for target ${resource.targetRef}. This is where the observability flow publishes its result after a policy inspects collected telemetry.`;
}

function targetFormFromDetail(detail?: ObservabilityTargetDetail): TargetFormState {
  if (!detail) return EMPTY_TARGET_FORM;
  return {
    name: detail.metadata.name,
    description: detail.spec.description ?? EMPTY_TARGET_FORM.description,
    targetType: detail.spec.targetType,
    connectorRef: detail.spec.connectorRef,
    endpoint: detail.spec.endpoint ?? "",
    scrapeInterval: detail.spec.scrapeInterval ?? "30s",
    policyRef: detail.spec.policyRef ?? "",
    labelsJson: safeJsonStringify(detail.spec.labels),
    selectorJson: safeJsonStringify(detail.spec.selector),
    credentialsJson: safeJsonStringify(detail.spec.credentials),
    tlsConfigJson: safeJsonStringify(detail.spec.tlsConfig),
  };
}

function policyFormFromDetail(detail?: ObservabilityPolicyDetail): PolicyFormState {
  if (!detail) return EMPTY_POLICY_FORM;
  return {
    name: detail.metadata.name,
    description: detail.spec.description ?? EMPTY_POLICY_FORM.description,
    retentionDays: String(detail.spec.retention?.days ?? 30),
    downsamplingAfter: detail.spec.retention?.downsampling?.after ?? "",
    downsamplingResolution: detail.spec.retention?.downsampling?.resolution ?? "",
    anomalyEnabled: String(detail.spec.anomalyDetection?.enabled ?? true),
    anomalyAlgorithm: detail.spec.anomalyDetection?.algorithm ?? "ensemble",
    sensitivity: String(detail.spec.anomalyDetection?.sensitivity ?? 0.7),
    windowSize: detail.spec.anomalyDetection?.windowSize ?? "1h",
    evaluationInterval: detail.spec.anomalyDetection?.evaluationInterval ?? "5m",
    metricsCsv: (detail.spec.anomalyDetection?.metrics ?? []).join(", "),
    webhookUrl: detail.spec.notifications?.webhookUrl ?? "",
    natsSubject: detail.spec.notifications?.natsSubject ?? "",
    alertRulesJson: safeJsonStringify(detail.spec.alertRules ?? []),
  };
}

function connectorFormFromDetail(detail?: ObservabilityConnectorDetail): ConnectorFormState {
  if (!detail) return EMPTY_CONNECTOR_FORM;
  return {
    name: detail.metadata.name,
    description: detail.spec.description ?? EMPTY_CONNECTOR_FORM.description,
    image: detail.spec.image,
    protocol: detail.spec.protocol,
    port: String(detail.spec.port ?? 9090),
    capabilitiesCsv: detail.spec.capabilities.join(", "),
    healthEndpoint: detail.spec.healthEndpoint ?? "/healthz",
    secretRef: detail.spec.secretRef ?? "",
    requestsCpu: detail.spec.resources?.requests?.cpu ?? "",
    requestsMemory: detail.spec.resources?.requests?.memory ?? "",
    limitsCpu: detail.spec.resources?.limits?.cpu ?? "",
    limitsMemory: detail.spec.resources?.limits?.memory ?? "",
    envJson: safeJsonStringify(detail.spec.env ?? []),
  };
}

function buildTargetPayload(form: TargetFormState): CreateObservationTargetPayload | UpdateObservationTargetPayload {
  const connectorRef = form.connectorRef.trim();
  if (!connectorRef) throw new Error("Connector is required");
  const targetType = form.targetType.trim();
  if (!targetType) throw new Error("Target type is required");

  return {
    name: form.name.trim(),
    description: form.description.trim() || undefined,
    targetType,
    connectorRef,
    endpoint: form.endpoint.trim() || undefined,
    scrapeInterval: form.scrapeInterval.trim() || undefined,
    policyRef: form.policyRef.trim() || undefined,
    labels: parseOptionalJson(form.labelsJson, "Labels") as Record<string, string> | undefined,
    selector: parseOptionalJson(form.selectorJson, "Selector") as CreateObservationTargetPayload["selector"],
    credentials: parseOptionalJson(form.credentialsJson, "Credentials") as CreateObservationTargetPayload["credentials"],
    tlsConfig: parseOptionalJson(form.tlsConfigJson, "TLS config") as CreateObservationTargetPayload["tlsConfig"],
  };
}

function buildPolicyPayload(form: PolicyFormState): CreateObservationPolicyPayload | UpdateObservationPolicyPayload {
  const alertRules = parseOptionalJson(form.alertRulesJson, "Alert rules");
  const metrics = form.metricsCsv
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  return {
    name: form.name.trim(),
    description: form.description.trim() || undefined,
    retention: {
      days: parseNumericInput(form.retentionDays, "Retention days"),
      downsampling: form.downsamplingAfter.trim() || form.downsamplingResolution.trim()
        ? {
            after: form.downsamplingAfter.trim() || undefined,
            resolution: form.downsamplingResolution.trim() || undefined,
          }
        : undefined,
    },
    alertRules: Array.isArray(alertRules) ? alertRules as CreateObservationPolicyPayload["alertRules"] : undefined,
    anomalyDetection: {
      enabled: form.anomalyEnabled === "true",
      algorithm: form.anomalyAlgorithm || undefined,
      sensitivity: parseNumericInput(form.sensitivity, "Sensitivity"),
      windowSize: form.windowSize.trim() || undefined,
      evaluationInterval: form.evaluationInterval.trim() || undefined,
      metrics: metrics.length > 0 ? metrics : undefined,
    },
    notifications: {
      webhookUrl: form.webhookUrl.trim() || undefined,
      natsSubject: form.natsSubject.trim() || undefined,
    },
  };
}

function buildConnectorPayload(form: ConnectorFormState): CreateConnectorPluginPayload | UpdateConnectorPluginPayload {
  const image = form.image.trim();
  if (!image) throw new Error("Image is required");
  const capabilities = form.capabilitiesCsv
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (capabilities.length === 0) throw new Error("At least one capability is required");

  const env = parseOptionalJson(form.envJson, "Environment entries");
  const port = parseNumericInput(form.port, "Port");

  return {
    name: form.name.trim(),
    description: form.description.trim() || undefined,
    image,
    protocol: form.protocol,
    port,
    capabilities,
    healthEndpoint: form.healthEndpoint.trim() || undefined,
    secretRef: form.secretRef.trim() || undefined,
    resources: {
      requests: form.requestsCpu.trim() || form.requestsMemory.trim()
        ? { cpu: form.requestsCpu.trim() || undefined, memory: form.requestsMemory.trim() || undefined }
        : undefined,
      limits: form.limitsCpu.trim() || form.limitsMemory.trim()
        ? { cpu: form.limitsCpu.trim() || undefined, memory: form.limitsMemory.trim() || undefined }
        : undefined,
    },
    env: Array.isArray(env) ? env as CreateConnectorPluginPayload["env"] : undefined,
  };
}

function ResourceStatCard({ config }: { config: SummaryCardConfig }) {
  const Icon = config.icon;
  return (
    <Card className="overflow-hidden border-border/60 bg-background/80 shadow-sm shadow-black/5 transition-transform duration-200 hover:-translate-y-0.5">
      <CardContent className="flex items-center justify-between gap-4 p-4">
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{config.label}</div>
          <div className="text-3xl font-semibold text-foreground">{config.value}</div>
          <div className="text-xs text-muted-foreground">{config.helper}</div>
        </div>
        <div className={cn("rounded-2xl border p-3 shadow-inner", config.accent)}>
          <Icon className="h-5 w-5" />
        </div>
      </CardContent>
    </Card>
  );
}

function EmptySelection({ title, description }: { title: string; description: string }) {
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center rounded-3xl border border-dashed border-border/70 bg-gradient-to-br from-background/80 to-muted/20 p-8 text-center shadow-sm shadow-black/5">
      <div className="max-w-md space-y-3">
        <div className="text-lg font-semibold text-foreground">{title}</div>
        <div className="text-sm leading-6 text-muted-foreground">{description}</div>
      </div>
    </div>
  );
}

function FieldHint({ children }: { children: string }) {
  return <p className="text-xs leading-5 text-muted-foreground">{children}</p>;
}

function EditorGuideCard({ kind }: { kind: EditableResourceTab }) {
  const guide = EDITOR_GUIDES[kind];

  return (
    <Card className="border-border/60 bg-background/75 shadow-sm shadow-black/5">
      <CardContent className="space-y-4 p-5">
        <div className="space-y-1.5">
          <div className="text-sm font-semibold text-foreground">{guide.title}</div>
          <p className="text-sm leading-6 text-muted-foreground">{guide.summary}</p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {guide.steps.map((step, index) => (
            <div key={step} className="rounded-2xl border border-border/60 bg-muted/15 p-3 shadow-sm shadow-black/5">
              <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Step {index + 1}</div>
              <p className="mt-2 text-sm leading-6 text-foreground">{step}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function DetailMetricCard({
  label,
  value,
  mono = false,
  breakAll = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  breakAll?: boolean;
}) {
  return (
    <Card className="border-border/60 bg-background/75 shadow-sm shadow-black/5">
      <CardContent className="space-y-2 p-4">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
        <div className={cn("text-sm font-semibold text-foreground", mono && "font-mono text-[13px]", breakAll && "break-all")}>
          {value}
        </div>
      </CardContent>
    </Card>
  );
}

export function ObservabilityDashboard() {
  const { token, namespace, canMutate } = useConnection();
  const [overview, setOverview] = useState<ObservabilityOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<ResourceTab>("targets");
  const [query, setQuery] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<SelectedResourceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [editorState, setEditorState] = useState<EditorState>(null);
  const [editorView, setEditorView] = useState<EditorView>("form");
  const [rawSpecJson, setRawSpecJson] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const [targetForm, setTargetForm] = useState<TargetFormState>(EMPTY_TARGET_FORM);
  const [policyForm, setPolicyForm] = useState<PolicyFormState>(EMPTY_POLICY_FORM);
  const [connectorForm, setConnectorForm] = useState<ConnectorFormState>(EMPTY_CONNECTOR_FORM);

  const filteredTargets = useMemo(() => {
    const items = overview?.targets ?? [];
    const term = query.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => [item.name, item.description, item.targetType, item.connectorRef, item.endpoint].join(" ").toLowerCase().includes(term));
  }, [overview?.targets, query]);

  const filteredReports = useMemo(() => {
    const items = overview?.reports ?? [];
    const term = query.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => [item.name, item.targetRef, item.reportType, item.summary].join(" ").toLowerCase().includes(term));
  }, [overview?.reports, query]);

  const filteredConnectors = useMemo(() => {
    const items = overview?.connectors ?? [];
    const term = query.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => [item.name, item.description, item.image, item.protocol, item.capabilities.join(" ")].join(" ").toLowerCase().includes(term));
  }, [overview?.connectors, query]);

  const filteredPolicies = useMemo(() => {
    const items = overview?.policies ?? [];
    const term = query.trim().toLowerCase();
    if (!term) return items;
    return items.filter((item) => [item.name, item.description, item.anomalyAlgorithm].join(" ").toLowerCase().includes(term));
  }, [overview?.policies, query]);

  const activeItems = useMemo(() => {
    switch (activeTab) {
      case "targets":
        return filteredTargets.map((item) => ({ name: item.name }));
      case "reports":
        return filteredReports.map((item) => ({ name: item.name }));
      case "connectors":
        return filteredConnectors.map((item) => ({ name: item.name }));
      case "policies":
        return filteredPolicies.map((item) => ({ name: item.name }));
      default:
        return [];
    }
  }, [activeTab, filteredConnectors, filteredPolicies, filteredReports, filteredTargets]);

  const selectedReport = useMemo(() => {
    if (activeTab !== "reports" || !selectedName) return null;
    return filteredReports.find((item) => item.name === selectedName) ?? null;
  }, [activeTab, filteredReports, selectedName]);

  const summaryCards = useMemo<SummaryCardConfig[]>(() => {
    if (!overview) return [];
    return [
      {
        key: "targets",
        label: "Targets",
        value: String(overview.summary.targets.total),
        helper: `${overview.summary.targets.active} active · ${overview.summary.targets.degraded} degraded · ${overview.summary.targets.failed} failed`,
        accent: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
        icon: Activity,
      },
      {
        key: "health",
        label: "Avg health",
        value: `${overview.summary.reports.avgHealthScore}%`,
        helper: `${overview.summary.reports.total} reports evaluated`,
        accent: "border-sky-500/25 bg-sky-500/10 text-sky-300",
        icon: HeartPulse,
      },
      {
        key: "findings",
        label: "Findings",
        value: String(overview.summary.reports.totalFindings),
        helper: "Anomalies and rule breaches waiting for attention",
        accent: "border-amber-500/25 bg-amber-500/10 text-amber-300",
        icon: AlertTriangle,
      },
      {
        key: "connectors",
        label: "Connectors",
        value: `${overview.summary.connectors.ready}/${overview.summary.connectors.total}`,
        helper: "Ready plugins available to collect data",
        accent: "border-violet-500/25 bg-violet-500/10 text-violet-300",
        icon: Cable,
      },
      {
        key: "agents",
        label: "Agent pods",
        value: `${overview.summary.agents.ready}/${overview.summary.agents.total}`,
        helper: `${overview.summary.agents.notReady} not ready in this namespace`,
        accent: "border-rose-500/25 bg-rose-500/10 text-rose-300",
        icon: Bot,
      },
    ];
  }, [overview]);

  const refreshOverview = useCallback(async (silent = false) => {
    if (!token) return;
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    try {
      const next = await fetchObservabilityOverview(token, namespace);
      setOverview(next);
      setError("");
    } catch (err) {
      const message = apiErrorMessage(err);
      setError(message);
      if (!silent) toast.error(message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [namespace, token]);

  useEffect(() => {
    void refreshOverview();
  }, [refreshOverview]);

  useEffect(() => {
    if (!autoRefresh || !token) return undefined;
    const handle = window.setInterval(() => {
      void refreshOverview(true);
    }, 30000);
    return () => window.clearInterval(handle);
  }, [autoRefresh, refreshOverview, token]);

  useEffect(() => {
    if (activeItems.length === 0) {
      setSelectedName(null);
      setSelectedDetail(null);
      setDetailError("");
      return;
    }
    if (!selectedName || !activeItems.some((item) => item.name === selectedName)) {
      setSelectedName(activeItems[0].name);
    }
  }, [activeItems, selectedName]);

  useEffect(() => {
    let cancelled = false;
    async function loadDetail() {
      if (!selectedName) {
        setSelectedDetail(null);
        setDetailError("");
        return;
      }
      if (activeTab === "reports") {
        setSelectedDetail(selectedReport ? { kind: "reports", resource: selectedReport } : null);
        setDetailError(selectedReport ? "" : "Selected report could not be found in the current overview payload.");
        return;
      }
      setDetailLoading(true);
      setDetailError("");
      try {
        if (activeTab === "targets") {
          const resource = await fetchObservationTarget(token, namespace, selectedName);
          if (!cancelled) setSelectedDetail({ kind: "targets", resource });
        } else if (activeTab === "policies") {
          const resource = await fetchObservationPolicy(token, namespace, selectedName);
          if (!cancelled) setSelectedDetail({ kind: "policies", resource });
        } else if (activeTab === "connectors") {
          const resource = await fetchConnectorPlugin(token, namespace, selectedName);
          if (!cancelled) setSelectedDetail({ kind: "connectors", resource });
        }
      } catch (err) {
        if (!cancelled) {
          setSelectedDetail(null);
          setDetailError(apiErrorMessage(err));
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    }
    if (!token) return undefined;
    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [activeTab, namespace, selectedName, selectedReport, token]);

  const selectedRelationships = useMemo(() => {
    if (!overview || !selectedDetail) return [] as Array<{ label: string; value: string }>;
    if (selectedDetail.kind === "targets") {
      return [
        { label: "Connector", value: selectedDetail.resource.spec.connectorRef },
        { label: "Policy", value: selectedDetail.resource.spec.policyRef ?? "Not attached" },
        { label: "Reports", value: String(findTargetReportCount(overview, selectedDetail.resource.metadata.name)) },
      ];
    }
    if (selectedDetail.kind === "policies") {
      return [
        { label: "Targets", value: String(findPolicyTargetCount(overview, selectedDetail.resource.metadata.name)) },
        { label: "Active alerts", value: String(selectedDetail.resource.status?.activeAlerts ?? 0) },
        { label: "Algorithm", value: selectedDetail.resource.spec.anomalyDetection?.algorithm ?? "Disabled" },
      ];
    }
    if (selectedDetail.kind === "connectors") {
      return [
        { label: "Targets", value: String(findConnectorTargetCount(overview, selectedDetail.resource.metadata.name)) },
        { label: "Capabilities", value: String(selectedDetail.resource.spec.capabilities.length) },
        { label: "Protocol", value: selectedDetail.resource.spec.protocol },
      ];
    }
    return [
      { label: "Target", value: selectedDetail.resource.targetRef },
      { label: "Findings", value: String(selectedDetail.resource.findingsCount) },
      { label: "Health score", value: selectedDetail.resource.healthScore == null ? "N/A" : `${selectedDetail.resource.healthScore}%` },
    ];
  }, [overview, selectedDetail]);

  const initializeEditor = useCallback((state: EditorState, detail?: SelectedResourceDetail | null) => {
    setEditorState(state);
    setEditorView("form");
    if (!state) return;
    if (state.kind === "targets") {
      const resource = detail?.kind === "targets" ? detail.resource : undefined;
      setTargetForm(targetFormFromDetail(resource));
      setRawSpecJson(JSON.stringify(resource?.spec ?? createTargetDraftSpec(), null, 2));
      return;
    }
    if (state.kind === "policies") {
      const resource = detail?.kind === "policies" ? detail.resource : undefined;
      setPolicyForm(policyFormFromDetail(resource));
      setRawSpecJson(JSON.stringify(resource?.spec ?? createPolicyDraftSpec(), null, 2));
      return;
    }
    const resource = detail?.kind === "connectors" ? detail.resource : undefined;
    setConnectorForm(connectorFormFromDetail(resource));
    setRawSpecJson(JSON.stringify(resource?.spec ?? createConnectorDraftSpec(), null, 2));
  }, []);

  const openCreateEditor = useCallback((kind: EditableResourceTab) => {
    initializeEditor({ kind, mode: "create" }, null);
  }, [initializeEditor]);

  const openEditEditor = useCallback(() => {
    if (!selectedDetail || selectedDetail.kind === "reports") return;
    initializeEditor({ kind: selectedDetail.kind, mode: "edit" }, selectedDetail);
  }, [initializeEditor, selectedDetail]);

  useEffect(() => {
    if (!editorState || editorView !== "raw") return;
    try {
      if (editorState.kind === "targets") {
        setRawSpecJson(JSON.stringify(createTargetDraftSpec(targetForm), null, 2));
        return;
      }
      if (editorState.kind === "policies") {
        setRawSpecJson(JSON.stringify(createPolicyDraftSpec(policyForm), null, 2));
        return;
      }
      setRawSpecJson(JSON.stringify(createConnectorDraftSpec(connectorForm), null, 2));
    } catch {
      // Keep the last valid raw JSON visible while the operator fixes invalid structured input.
    }
  }, [connectorForm, editorState, editorView, policyForm, targetForm]);

  const handleSave = useCallback(async () => {
    if (!editorState) return;
    setSaving(true);
    try {
      if (editorState.kind === "targets") {
        const built = editorView === "raw"
          ? JSON.parse(rawSpecJson) as UpdateObservationTargetPayload
          : buildTargetPayload(targetForm);
        const name = editorState.mode === "create" ? targetForm.name.trim() : selectedDetail?.kind === "targets" ? selectedDetail.resource.metadata.name : "";
        if (!name) throw new Error("Target name is required");
        if (editorState.mode === "create") {
          await createObservationTarget(token, namespace, { ...(built as CreateObservationTargetPayload), name });
          toast.success(`Created target ${name}`);
        } else {
          await updateObservationTarget(token, namespace, name, built as UpdateObservationTargetPayload);
          toast.success(`Updated target ${name}`);
        }
        setSelectedName(name);
      } else if (editorState.kind === "policies") {
        const built = editorView === "raw"
          ? JSON.parse(rawSpecJson) as UpdateObservationPolicyPayload
          : buildPolicyPayload(policyForm);
        const name = editorState.mode === "create" ? policyForm.name.trim() : selectedDetail?.kind === "policies" ? selectedDetail.resource.metadata.name : "";
        if (!name) throw new Error("Policy name is required");
        if (editorState.mode === "create") {
          await createObservationPolicy(token, namespace, { ...(built as CreateObservationPolicyPayload), name });
          toast.success(`Created policy ${name}`);
        } else {
          await updateObservationPolicy(token, namespace, name, built as UpdateObservationPolicyPayload);
          toast.success(`Updated policy ${name}`);
        }
        setSelectedName(name);
      } else {
        const built = editorView === "raw"
          ? JSON.parse(rawSpecJson) as UpdateConnectorPluginPayload
          : buildConnectorPayload(connectorForm);
        const name = editorState.mode === "create" ? connectorForm.name.trim() : selectedDetail?.kind === "connectors" ? selectedDetail.resource.metadata.name : "";
        if (!name) throw new Error("Connector name is required");
        if (editorState.mode === "create") {
          await createConnectorPlugin(token, namespace, { ...(built as CreateConnectorPluginPayload), name });
          toast.success(`Created connector ${name}`);
        } else {
          await updateConnectorPlugin(token, namespace, name, built as UpdateConnectorPluginPayload);
          toast.success(`Updated connector ${name}`);
        }
        setSelectedName(name);
      }
      setEditorState(null);
      await refreshOverview(true);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [connectorForm, editorState, editorView, namespace, policyForm, rawSpecJson, refreshOverview, selectedDetail, targetForm, token]);

  const handleDelete = useCallback(async () => {
    if (!selectedDetail || selectedDetail.kind === "reports") return;
    try {
      const name = selectedDetail.resource.metadata.name;
      if (selectedDetail.kind === "targets") {
        await deleteObservationTarget(token, namespace, name);
        toast.success(`Deleted target ${name}`);
      } else if (selectedDetail.kind === "policies") {
        await deleteObservationPolicy(token, namespace, name);
        toast.success(`Deleted policy ${name}`);
      } else {
        await deleteConnectorPlugin(token, namespace, name);
        toast.success(`Deleted connector ${name}`);
      }
      setSelectedName(null);
      setSelectedDetail(null);
      await refreshOverview(true);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    }
  }, [namespace, refreshOverview, selectedDetail, token]);

  const detailTitle = useMemo(() => {
    if (!selectedDetail) return "Select a resource";
    if (selectedDetail.kind === "reports") return selectedDetail.resource.name;
    return selectedDetail.resource.metadata.name;
  }, [selectedDetail]);

  const detailStatus = useMemo(() => {
    if (!selectedDetail) return "";
    if (selectedDetail.kind === "targets") return selectedDetail.resource.status?.phase ?? "Pending";
    if (selectedDetail.kind === "policies") return selectedDetail.resource.status?.activeAlerts ? `${selectedDetail.resource.status.activeAlerts} active alerts` : "Policy configured";
    if (selectedDetail.kind === "connectors") return selectedDetail.resource.status?.ready ?? "Unknown";
    return selectedDetail.resource.phase;
  }, [selectedDetail]);

  const renderResourceList = () => {
    const items = activeTab === "targets"
      ? filteredTargets
      : activeTab === "reports"
        ? filteredReports
        : activeTab === "connectors"
          ? filteredConnectors
          : filteredPolicies;

    if (items.length === 0) {
      return (
        <div className="p-4">
          <div className="flex min-h-[220px] items-center justify-center rounded-2xl border border-dashed border-border/70 bg-gradient-to-br from-background/80 to-muted/20 p-6 text-center shadow-sm shadow-black/5">
            <div className="max-w-sm space-y-2">
              <div className="text-sm font-semibold text-foreground">No {activeTab} match this view</div>
              <div className="text-sm leading-6 text-muted-foreground">
                Adjust the filter or create a new resource in namespace {namespace}.
              </div>
            </div>
          </div>
        </div>
      );
    }

    return items.map((item) => {
      const name = item.name;
      const isSelected = name === selectedName;
      const status = activeTab === "targets"
        ? (item as ObservabilityTargetSummary).phase
        : activeTab === "reports"
          ? (item as ObservabilityReport).phase
          : activeTab === "connectors"
            ? (item as ObservabilityConnector).ready
            : (item as ObservabilityPolicy).activeAlerts > 0
              ? `${(item as ObservabilityPolicy).activeAlerts} alerts`
              : "Ready";
      const helper = activeTab === "targets"
        ? `${(item as ObservabilityTargetSummary).targetType} · ${(item as ObservabilityTargetSummary).connectorRef}`
        : activeTab === "reports"
          ? `${(item as ObservabilityReport).targetRef} · ${(item as ObservabilityReport).reportType}`
          : activeTab === "connectors"
            ? `${(item as ObservabilityConnector).protocol.toUpperCase()} · ${(item as ObservabilityConnector).capabilities.join(", ")}`
            : `${(item as ObservabilityPolicy).anomalyAlgorithm} · ${(item as ObservabilityPolicy).alertRulesCount} rules`;
      const description = activeTab === "targets"
        ? (item as ObservabilityTargetSummary).description
        : activeTab === "connectors"
          ? (item as ObservabilityConnector).description
          : activeTab === "policies"
            ? (item as ObservabilityPolicy).description
            : "";

      return (
        <button
          key={name}
          type="button"
          onClick={() => setSelectedName(name)}
          className={cn(
            "mx-3 my-2 flex w-auto flex-col gap-3 rounded-2xl border px-4 py-3 text-left shadow-sm shadow-black/5 transition",
            isSelected
              ? "border-primary/25 bg-primary/5 shadow-primary/10"
              : "border-border/60 bg-background/70 hover:border-primary/15 hover:bg-accent/30",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-foreground">{name}</div>
              <div className="truncate text-xs text-muted-foreground">{helper}</div>
              {description ? <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground/90">{description}</div> : null}
            </div>
            <Badge variant={getStatusBadgeVariant(status)}>{status}</Badge>
          </div>
        </button>
      );
    });
  };

  const renderDetailBody = () => {
    if (detailLoading) {
      return (
        <div className="flex min-h-[360px] items-center justify-center text-sm text-muted-foreground">
          <LoaderCircle className="mr-2 h-4 w-4 animate-spin" /> Loading resource details...
        </div>
      );
    }
    if (detailError) {
      return <EmptySelection title="Resource unavailable" description={detailError} />;
    }
    if (!selectedDetail) {
      return <EmptySelection title="Select a resource" description="Choose a target, connector, policy, or report to inspect its health, configuration, and relationships." />;
    }

    const rawPayload = selectedDetail.kind === "reports"
      ? selectedDetail.resource
      : selectedDetail.resource;

    return (
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="h-auto rounded-2xl border border-border/60 bg-background/75 p-1">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="raw">Raw JSON</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="space-y-4">
          {selectedDetail.kind === "targets" && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <DetailMetricCard label="Endpoint" value={selectedDetail.resource.spec.endpoint || "Inherited or discovered"} breakAll />
              <DetailMetricCard label="Scrape interval" value={selectedDetail.resource.spec.scrapeInterval || "30s"} />
              <DetailMetricCard label="Metrics collected" value={selectedDetail.resource.status?.metricsCollected ?? 0} />
              <DetailMetricCard label="Last scrape" value={formatTimestamp(selectedDetail.resource.status?.lastScrapeTime)} />
            </div>
          )}
          {selectedDetail.kind === "policies" && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <DetailMetricCard label="Retention" value={`${selectedDetail.resource.spec.retention?.days ?? 30} days`} />
              <DetailMetricCard label="Algorithm" value={selectedDetail.resource.spec.anomalyDetection?.algorithm ?? "Disabled"} />
              <DetailMetricCard label="Sensitivity" value={selectedDetail.resource.spec.anomalyDetection?.sensitivity ?? "N/A"} />
              <DetailMetricCard label="Alert rules" value={selectedDetail.resource.spec.alertRules?.length ?? 0} />
            </div>
          )}
          {selectedDetail.kind === "connectors" && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <DetailMetricCard label="Image" value={selectedDetail.resource.spec.image} breakAll />
              <DetailMetricCard label="Protocol" value={selectedDetail.resource.spec.protocol.toUpperCase()} />
              <DetailMetricCard label="Port" value={selectedDetail.resource.spec.port ?? 9090} />
              <DetailMetricCard label="Last health check" value={formatTimestamp(selectedDetail.resource.status?.lastHealthCheck)} />
            </div>
          )}
          {selectedDetail.kind === "reports" && (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <DetailMetricCard label="Health score" value={selectedDetail.resource.healthScore == null ? "N/A" : `${selectedDetail.resource.healthScore}%`} />
              <DetailMetricCard label="Findings" value={selectedDetail.resource.findingsCount} />
              <DetailMetricCard label="Target" value={selectedDetail.resource.targetRef} />
              <DetailMetricCard label="Last evaluated" value={formatTimestamp(selectedDetail.resource.lastEvaluated)} />
            </div>
          )}

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardHeader className="p-4">
                <CardTitle className="text-base">Operational context</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 p-4 pt-0">
                {selectedDetail.kind === "reports" ? (
                  <>
                    <div className="rounded-2xl border border-border/60 bg-muted/15 p-4 text-sm leading-6 text-muted-foreground shadow-sm shadow-black/5">{buildReportSummaryText(selectedDetail.resource)}</div>
                    <div className="space-y-3">
                      {selectedDetail.resource.findings.length === 0 ? (
                        <div className="rounded-2xl border border-dashed border-border/70 bg-background/60 p-4 text-sm text-muted-foreground">No findings were attached to this report.</div>
                      ) : (
                        selectedDetail.resource.findings.map((finding) => (
                          <div key={finding.id} className="rounded-2xl border border-border/60 bg-background/75 p-4 shadow-sm shadow-black/5">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-semibold text-foreground">{finding.metric}</div>
                              <Badge variant={getStatusBadgeVariant(finding.severity)}>{finding.severity}</Badge>
                            </div>
                            <div className="mt-2 text-sm text-muted-foreground">{finding.description}</div>
                            <div className="mt-3 grid gap-2 text-xs text-muted-foreground md:grid-cols-3">
                              <div>Observed: <span className="font-medium text-foreground">{finding.value}</span></div>
                              <div>Expected: <span className="font-medium text-foreground">{finding.expected}</span></div>
                              <div>Deviation: <span className="font-medium text-foreground">{finding.deviation}</span></div>
                            </div>
                            <div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/8 p-3 text-sm text-amber-100">{finding.recommendation}</div>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <div className="space-y-4">
                    <div className="rounded-2xl border border-border/60 bg-muted/15 p-4 shadow-sm shadow-black/5">
                      <div className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">Purpose</div>
                      <p className="text-sm leading-6 text-muted-foreground">
                        {selectedDetail.resource.spec.description || (
                          selectedDetail.kind === "targets"
                            ? buildTargetPurposeText(selectedDetail.resource)
                            : selectedDetail.kind === "policies"
                              ? buildPolicyPurposeText(selectedDetail.resource)
                              : buildConnectorPurposeText(selectedDetail.resource)
                        )}
                      </p>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      {selectedRelationships.map((entry) => (
                        <div key={entry.label} className="rounded-2xl border border-border/60 bg-background/75 p-4 shadow-sm shadow-black/5">
                          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{entry.label}</div>
                          <div className="mt-1 text-sm font-medium text-foreground">{entry.value}</div>
                        </div>
                      ))}
                    </div>
                    <div className="rounded-2xl border border-border/60 bg-background/75 p-4 shadow-sm shadow-black/5">
                      <div className="mb-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">Structured configuration snapshot</div>
                      <Textarea className="min-h-[240px] border-border/60 bg-background/90 font-mono text-xs" readOnly value={safeJsonStringify(selectedDetail.resource.spec)} />
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardHeader className="p-4">
                <CardTitle className="text-base">Operator actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 p-4 pt-0">
                <div className="space-y-2">
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Mode</div>
                  <Badge variant={canMutate ? "default" : "outline"}>{canMutate ? "Operator controls enabled" : "Read-only session"}</Badge>
                </div>
                {canMutate ? (
                  <div className="grid gap-2">
                    <Button variant="outline" onClick={() => openCreateEditor("targets")}><Plus className="h-4 w-4" /> New target</Button>
                    <Button variant="outline" onClick={() => openCreateEditor("connectors")}><Plus className="h-4 w-4" /> New connector</Button>
                    <Button variant="outline" onClick={() => openCreateEditor("policies")}><Plus className="h-4 w-4" /> New policy</Button>
                  </div>
                ) : (
                  <div className="rounded-2xl border border-border/60 bg-muted/15 p-4 text-sm text-muted-foreground shadow-sm shadow-black/5">This session can inspect observability resources, but only operator users can create, edit, or delete them.</div>
                )}
                {selectedDetail && selectedDetail.kind !== "reports" && canMutate && (
                  <div className="grid gap-2">
                    <Button onClick={openEditEditor}><Pencil className="h-4 w-4" /> Edit configuration</Button>
                    <Button variant="destructive" onClick={() => setConfirmDeleteOpen(true)}><Trash2 className="h-4 w-4" /> Delete resource</Button>
                  </div>
                )}
                <Separator />
                <div className="space-y-2">
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">Raw payload</div>
                  <Textarea className="min-h-[260px] border-border/60 bg-background/90 font-mono text-xs" readOnly value={JSON.stringify(rawPayload, null, 2)} />
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="raw">
          <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
            <CardContent className="p-4">
              <Textarea className="min-h-[520px] border-border/60 bg-background/90 font-mono text-xs" readOnly value={JSON.stringify(rawPayload, null, 2)} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    );
  };

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border/60 bg-gradient-to-br from-background/95 via-background/90 to-muted/35 p-5 shadow-sm shadow-black/5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="border-border/60 bg-background/80">Namespace: {namespace}</Badge>
              <Badge
                variant={error ? "destructive" : "outline"}
                className={cn(!error && "border-emerald-500/20 bg-emerald-500/10 text-emerald-500")}
              >
                {error ? "Gateway degraded" : "Observability control plane"}
              </Badge>
              <Badge variant="outline" className="border-border/60 bg-background/80">Auto-refresh {autoRefresh ? "on" : "off"}</Badge>
            </div>
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">Observability workspace</h2>
              <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                Manage observation targets, connectors, and policies from one place, then drill into reports and findings without leaving the product.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" className="bg-background/80" onClick={() => setAutoRefresh((current) => !current)}>
              {autoRefresh ? "Pause auto-refresh" : "Resume auto-refresh"}
            </Button>
            <Button variant="outline" className="bg-background/80" onClick={() => void refreshOverview(true)} disabled={refreshing || loading}>
              {refreshing || loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Refresh
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-5">
        {summaryCards.map((config) => <ResourceStatCard key={config.key} config={config} />)}
      </div>

      {loading && !overview ? (
        <EmptySelection title="Loading observability data" description="The workspace is waiting for the gateway to return targets, connectors, policies, reports, and agent health." />
      ) : error && !overview ? (
        <EmptySelection title="Observability data unavailable" description={error} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="overflow-hidden border-border/60 bg-background/80 shadow-sm shadow-black/5">
            <CardHeader className="space-y-4 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="space-y-1">
                  <CardTitle className="text-base">Resource explorer</CardTitle>
                  <p className="text-xs leading-5 text-muted-foreground">
                    Browse targets, reports, connectors, and policies in the current namespace.
                  </p>
                </div>
                {canMutate && activeTab !== "reports" && (
                  <Button size="sm" variant="outline" onClick={() => openCreateEditor(activeTab)}>
                    <Plus className="h-4 w-4" /> New
                  </Button>
                )}
              </div>
              <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as ResourceTab)}>
                <TabsList className="grid h-auto w-full grid-cols-2 rounded-2xl border border-border/60 bg-background/75 p-1 sm:grid-cols-4">
                  <TabsTrigger value="targets">Targets</TabsTrigger>
                  <TabsTrigger value="reports">Reports</TabsTrigger>
                  <TabsTrigger value="connectors">Connectors</TabsTrigger>
                  <TabsTrigger value="policies">Policies</TabsTrigger>
                </TabsList>
              </Tabs>
              <div className="space-y-2">
                <Label htmlFor="observability-search">Filter resources</Label>
                <Input id="observability-search" placeholder={`Search ${activeTab}...`} value={query} onChange={(event) => setQuery(event.target.value)} />
              </div>
            </CardHeader>
            <Separator />
            <ScrollArea className="h-[720px]">{renderResourceList()}</ScrollArea>
          </Card>

          <div className="space-y-4">
            <Card className="border-border/60 bg-background/80 shadow-sm shadow-black/5">
              <CardHeader className="flex flex-row items-start justify-between gap-4 p-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="border-border/60 bg-background/80">{titleCase(activeTab.slice(0, -1) || activeTab)}</Badge>
                    {selectedDetail && <Badge variant={getStatusBadgeVariant(detailStatus)}>{detailStatus}</Badge>}
                  </div>
                  <div>
                    <CardTitle className="text-xl">{detailTitle}</CardTitle>
                    {selectedDetail && selectedDetail.kind !== "reports" && (
                      <div className="mt-1 space-y-1 text-sm text-muted-foreground">
                        <div>Created {formatTimestamp(selectedDetail.resource.metadata.creationTimestamp)}</div>
                        <p className="max-w-2xl leading-6 text-muted-foreground/90">
                          {selectedDetail.resource.spec.description || (
                            selectedDetail.kind === "targets"
                              ? buildTargetPurposeText(selectedDetail.resource)
                              : selectedDetail.kind === "policies"
                                ? buildPolicyPurposeText(selectedDetail.resource)
                                : buildConnectorPurposeText(selectedDetail.resource)
                          )}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
                {selectedDetail && selectedDetail.kind !== "reports" && canMutate && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="outline" onClick={openEditEditor}><Pencil className="h-4 w-4" /> Edit</Button>
                    <Button variant="destructive" onClick={() => setConfirmDeleteOpen(true)}><Trash2 className="h-4 w-4" /> Delete</Button>
                  </div>
                )}
              </CardHeader>
            </Card>
            {renderDetailBody()}
          </div>
        </div>
      )}

      <Sheet
        open={Boolean(editorState)}
        onOpenChange={(open) => {
          if (!open) setEditorState(null);
        }}
      >
        <SheetContent side="right" className="w-full overflow-y-auto border-l border-border/60 bg-background/95 shadow-2xl sm:max-w-3xl">
          <SheetHeader>
            <SheetTitle>
              {editorState?.mode === "create" ? "Create" : "Edit"} {editorState ? titleCase(editorState.kind.slice(0, -1)) : "resource"}
            </SheetTitle>
            <SheetDescription>
              Use structured fields for the common workflow, or switch to raw JSON to edit the spec directly.
            </SheetDescription>
          </SheetHeader>

          {editorState && (
            <div className="mt-6 space-y-4">
              <Tabs value={editorView} onValueChange={(value) => setEditorView(value as EditorView)}>
                <TabsList className="h-auto rounded-2xl border border-border/60 bg-background/75 p-1">
                  <TabsTrigger value="form">Form</TabsTrigger>
                  <TabsTrigger value="raw">Raw JSON</TabsTrigger>
                </TabsList>
              </Tabs>

              {editorView === "form" ? (
                <div className="space-y-6">
                  <EditorGuideCard kind={editorState.kind} />

                  {editorState.kind === "targets" && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="target-name">Name</Label>
                        <Input id="target-name" value={targetForm.name} disabled={editorState.mode === "edit"} onChange={(event) => setTargetForm((current) => ({ ...current, name: event.target.value }))} />
                        <FieldHint>Use a stable operator-facing name. This becomes the Kubernetes resource name and is what policies, reports, and teammates will reference.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="target-description">Description</Label>
                        <Textarea
                          id="target-description"
                          value={targetForm.description}
                          onChange={(event) => setTargetForm((current) => ({ ...current, description: event.target.value }))}
                          placeholder="Explain what this target watches, why it matters, and what a healthy result should look like."
                        />
                        <FieldHint>Describe the system being observed, the operational goal, and any context another operator would need before changing it.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label>Target type</Label>
                        <Select value={targetForm.targetType} onValueChange={(value) => setTargetForm((current) => ({ ...current, targetType: value }))}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>{TARGET_TYPES.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
                        </Select>
                        <FieldHint>Choose the integration model the connector expects. For example, kubernetes targets usually discover resources by selector instead of a fixed endpoint.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label>Connector</Label>
                        {(overview?.connectors.length ?? 0) > 0 ? (
                          <Select value={targetForm.connectorRef || EMPTY_OPTION} onValueChange={(value) => setTargetForm((current) => ({ ...current, connectorRef: value === EMPTY_OPTION ? "" : value }))}>
                            <SelectTrigger><SelectValue placeholder="Select connector" /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value={EMPTY_OPTION}>Select connector</SelectItem>
                              {(overview?.connectors ?? []).map((connector) => <SelectItem key={connector.name} value={connector.name}>{connector.name}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        ) : (
                          <Input value={targetForm.connectorRef} onChange={(event) => setTargetForm((current) => ({ ...current, connectorRef: event.target.value }))} placeholder="kubernetes-connector" />
                        )}
                        <FieldHint>This is the plugin that knows how to talk to the remote system and collect telemetry for this target.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="target-endpoint">Endpoint</Label>
                        <Input id="target-endpoint" value={targetForm.endpoint} onChange={(event) => setTargetForm((current) => ({ ...current, endpoint: event.target.value }))} placeholder="https://kubernetes.default.svc:443" />
                        <FieldHint>Use an explicit URL when the connector should hit one endpoint directly. Leave it blank when the connector discovers targets from labels or selectors.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="target-interval">Scrape interval</Label>
                        <Input id="target-interval" value={targetForm.scrapeInterval} onChange={(event) => setTargetForm((current) => ({ ...current, scrapeInterval: event.target.value }))} placeholder="30s" />
                        <FieldHint>How often to collect or evaluate data for this target. Faster intervals increase fidelity but also increase load.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label>Policy</Label>
                        {(overview?.policies.length ?? 0) > 0 ? (
                          <Select value={targetForm.policyRef || EMPTY_OPTION} onValueChange={(value) => setTargetForm((current) => ({ ...current, policyRef: value === EMPTY_OPTION ? "" : value }))}>
                            <SelectTrigger><SelectValue placeholder="Optional policy" /></SelectTrigger>
                            <SelectContent>
                              <SelectItem value={EMPTY_OPTION}>No policy</SelectItem>
                              {(overview?.policies ?? []).map((policy) => <SelectItem key={policy.name} value={policy.name}>{policy.name}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        ) : (
                          <Input value={targetForm.policyRef} onChange={(event) => setTargetForm((current) => ({ ...current, policyRef: event.target.value }))} placeholder="cluster-monitoring-policy" />
                        )}
                        <FieldHint>Attach a policy when you want retention rules, anomaly detection, or alert routing applied automatically to this target.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="target-labels">Labels JSON</Label>
                        <Textarea id="target-labels" className="min-h-[120px] font-mono text-xs" value={targetForm.labelsJson} onChange={(event) => setTargetForm((current) => ({ ...current, labelsJson: event.target.value }))} placeholder='{"environment":"dev"}' />
                        <FieldHint>Operator metadata for grouping, ownership, or environment tagging. These labels do not decide discovery by themselves.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="target-selector">Selector JSON</Label>
                        <Textarea id="target-selector" className="min-h-[120px] font-mono text-xs" value={targetForm.selectorJson} onChange={(event) => setTargetForm((current) => ({ ...current, selectorJson: event.target.value }))} placeholder='{"matchLabels":{"app":"api-gateway"}}' />
                        <FieldHint>Use selectors when the connector should dynamically find many resources, such as pods, services, or namespaces that match labels.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="target-credentials">Credentials JSON</Label>
                        <Textarea id="target-credentials" className="min-h-[120px] font-mono text-xs" value={targetForm.credentialsJson} onChange={(event) => setTargetForm((current) => ({ ...current, credentialsJson: event.target.value }))} placeholder='{"secretRef":"k8s-observer"}' />
                        <FieldHint>Reference credentials only when the connector needs extra auth beyond its own runtime identity.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="target-tls">TLS config JSON</Label>
                        <Textarea id="target-tls" className="min-h-[120px] font-mono text-xs" value={targetForm.tlsConfigJson} onChange={(event) => setTargetForm((current) => ({ ...current, tlsConfigJson: event.target.value }))} placeholder='{"insecureSkipVerify":true}' />
                        <FieldHint>Only relax TLS verification for internal bootstrap scenarios. Prefer proper CA bundles or cluster trust wherever possible.</FieldHint>
                      </div>
                    </div>
                  )}

                  {editorState.kind === "policies" && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="policy-name">Name</Label>
                        <Input id="policy-name" value={policyForm.name} disabled={editorState.mode === "edit"} onChange={(event) => setPolicyForm((current) => ({ ...current, name: event.target.value }))} />
                        <FieldHint>Use a reusable policy name that clearly conveys the operating model, such as cluster-baseline, ingress-slo, or payment-api-critical.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="policy-description">Description</Label>
                        <Textarea
                          id="policy-description"
                          value={policyForm.description}
                          onChange={(event) => setPolicyForm((current) => ({ ...current, description: event.target.value }))}
                          placeholder="Explain what this policy is trying to detect, how aggressive it should be, and where alerts should go."
                        />
                        <FieldHint>Document the monitoring intent in plain language so anyone attaching the policy understands its blast radius and sensitivity.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-retention">Retention days</Label>
                        <Input id="policy-retention" value={policyForm.retentionDays} onChange={(event) => setPolicyForm((current) => ({ ...current, retentionDays: event.target.value }))} />
                        <FieldHint>How long raw observations should be kept before aging out. Shorter retention saves storage, longer retention improves investigation depth.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label>Algorithm</Label>
                        <Select value={policyForm.anomalyAlgorithm} onValueChange={(value) => setPolicyForm((current) => ({ ...current, anomalyAlgorithm: value }))}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>{POLICY_ALGORITHMS.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
                        </Select>
                        <FieldHint>Select the detection approach the runtime should use when evaluating this target's signals.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label>Anomaly detection</Label>
                        <Select value={policyForm.anomalyEnabled} onValueChange={(value) => setPolicyForm((current) => ({ ...current, anomalyEnabled: value }))}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="true">Enabled</SelectItem>
                            <SelectItem value="false">Disabled</SelectItem>
                          </SelectContent>
                        </Select>
                        <FieldHint>Disable anomaly detection when you only want retention and routing behavior, or when another system already handles anomaly analysis.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-sensitivity">Sensitivity</Label>
                        <Input id="policy-sensitivity" value={policyForm.sensitivity} onChange={(event) => setPolicyForm((current) => ({ ...current, sensitivity: event.target.value }))} />
                        <FieldHint>Higher values usually mean more alerts and less tolerance for drift. Tune this against false positives, not just ideal behavior.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-window">Window size</Label>
                        <Input id="policy-window" value={policyForm.windowSize} onChange={(event) => setPolicyForm((current) => ({ ...current, windowSize: event.target.value }))} />
                        <FieldHint>The period of historical data the detector should compare against when deciding whether behavior is abnormal.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-eval-interval">Evaluation interval</Label>
                        <Input id="policy-eval-interval" value={policyForm.evaluationInterval} onChange={(event) => setPolicyForm((current) => ({ ...current, evaluationInterval: event.target.value }))} />
                        <FieldHint>How often the policy runs its checks. This is separate from the target scrape interval and should reflect the urgency of the workload.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-downsampling-after">Downsampling after</Label>
                        <Input id="policy-downsampling-after" value={policyForm.downsamplingAfter} onChange={(event) => setPolicyForm((current) => ({ ...current, downsamplingAfter: event.target.value }))} />
                        <FieldHint>After this age, data can be compacted to reduce storage pressure while preserving broader trends.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-downsampling-resolution">Downsampling resolution</Label>
                        <Input id="policy-downsampling-resolution" value={policyForm.downsamplingResolution} onChange={(event) => setPolicyForm((current) => ({ ...current, downsamplingResolution: event.target.value }))} />
                        <FieldHint>Choose the coarser resolution used after downsampling starts, such as 5m or 15m buckets.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="policy-metrics">Anomaly metrics</Label>
                        <Input id="policy-metrics" value={policyForm.metricsCsv} onChange={(event) => setPolicyForm((current) => ({ ...current, metricsCsv: event.target.value }))} placeholder="metric_one, metric_two, metric_three" />
                        <FieldHint>Optional allow-list of metrics that matter most for anomaly detection. Leave blank to let the runtime evaluate all supported metrics.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-webhook">Webhook URL</Label>
                        <Input id="policy-webhook" value={policyForm.webhookUrl} onChange={(event) => setPolicyForm((current) => ({ ...current, webhookUrl: event.target.value }))} />
                        <FieldHint>Where to send HTTP alerts if you want external incident tooling or chatops to receive findings from this policy.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="policy-nats">NATS subject</Label>
                        <Input id="policy-nats" value={policyForm.natsSubject} onChange={(event) => setPolicyForm((current) => ({ ...current, natsSubject: event.target.value }))} />
                        <FieldHint>Use a subject when alerts should flow into an internal event bus instead of or in addition to webhooks.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="policy-alerts">Alert rules JSON</Label>
                        <Textarea id="policy-alerts" className="min-h-[180px] font-mono text-xs" value={policyForm.alertRulesJson} onChange={(event) => setPolicyForm((current) => ({ ...current, alertRulesJson: event.target.value }))} />
                        <FieldHint>Define explicit thresholds or routing rules here when anomaly detection alone is not enough for the operating model.</FieldHint>
                      </div>
                    </div>
                  )}

                  {editorState.kind === "connectors" && (
                    <div className="grid gap-4 md:grid-cols-2">
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="connector-name">Name</Label>
                        <Input id="connector-name" value={connectorForm.name} disabled={editorState.mode === "edit"} onChange={(event) => setConnectorForm((current) => ({ ...current, name: event.target.value }))} />
                        <FieldHint>Name the connector after the platform or integration it provides so target authors can find it quickly.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="connector-description">Description</Label>
                        <Textarea
                          id="connector-description"
                          value={connectorForm.description}
                          onChange={(event) => setConnectorForm((current) => ({ ...current, description: event.target.value }))}
                          placeholder="Explain what this connector can reach, what telemetry it understands, and any assumptions it makes."
                        />
                        <FieldHint>Use this to explain the collection mechanism and supported target types so operators know when to reuse or replace the connector.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="connector-image">Image</Label>
                        <Input id="connector-image" value={connectorForm.image} onChange={(event) => setConnectorForm((current) => ({ ...current, image: event.target.value }))} placeholder="docker.io/your-org/connector-kubernetes:latest" />
                        <FieldHint>The runtime image for the plugin sidecar or workload. It must exist and be pullable by the cluster.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label>Protocol</Label>
                        <Select value={connectorForm.protocol} onValueChange={(value) => setConnectorForm((current) => ({ ...current, protocol: value }))}>
                          <SelectTrigger><SelectValue /></SelectTrigger>
                          <SelectContent>{CONNECTOR_PROTOCOLS.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent>
                        </Select>
                        <FieldHint>Protocol used by the platform when it talks to the connector service.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-port">Port</Label>
                        <Input id="connector-port" value={connectorForm.port} onChange={(event) => setConnectorForm((current) => ({ ...current, port: event.target.value }))} />
                        <FieldHint>Listening port exposed by the connector container or service.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="connector-capabilities">Capabilities</Label>
                        <Input id="connector-capabilities" value={connectorForm.capabilitiesCsv} onChange={(event) => setConnectorForm((current) => ({ ...current, capabilitiesCsv: event.target.value }))} placeholder="kubernetes-api, prometheus" />
                        <FieldHint>Comma-separated verbs or domains this connector supports. Targets and operators use these to understand fit.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-health-endpoint">Health endpoint</Label>
                        <Input id="connector-health-endpoint" value={connectorForm.healthEndpoint} onChange={(event) => setConnectorForm((current) => ({ ...current, healthEndpoint: event.target.value }))} />
                        <FieldHint>Path the control plane can poll to decide whether the connector is ready to serve traffic.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-secret">Secret ref</Label>
                        <Input id="connector-secret" value={connectorForm.secretRef} onChange={(event) => setConnectorForm((current) => ({ ...current, secretRef: event.target.value }))} />
                        <FieldHint>Optional Kubernetes secret name containing credentials or tokens the connector needs at runtime.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-requests-cpu">Requests CPU</Label>
                        <Input id="connector-requests-cpu" value={connectorForm.requestsCpu} onChange={(event) => setConnectorForm((current) => ({ ...current, requestsCpu: event.target.value }))} />
                        <FieldHint>Baseline CPU reservation for scheduling. Set this to what the connector typically needs, not its worst case.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-requests-memory">Requests memory</Label>
                        <Input id="connector-requests-memory" value={connectorForm.requestsMemory} onChange={(event) => setConnectorForm((current) => ({ ...current, requestsMemory: event.target.value }))} />
                        <FieldHint>Baseline memory reservation used by the scheduler to place the connector workload.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-limits-cpu">Limits CPU</Label>
                        <Input id="connector-limits-cpu" value={connectorForm.limitsCpu} onChange={(event) => setConnectorForm((current) => ({ ...current, limitsCpu: event.target.value }))} />
                        <FieldHint>Maximum CPU the connector can burst to before Kubernetes throttles it.</FieldHint>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="connector-limits-memory">Limits memory</Label>
                        <Input id="connector-limits-memory" value={connectorForm.limitsMemory} onChange={(event) => setConnectorForm((current) => ({ ...current, limitsMemory: event.target.value }))} />
                        <FieldHint>Maximum memory allowed before the connector is at risk of eviction or OOM kill.</FieldHint>
                      </div>
                      <div className="space-y-2 md:col-span-2">
                        <Label htmlFor="connector-env">Environment JSON</Label>
                        <Textarea id="connector-env" className="min-h-[180px] font-mono text-xs" value={connectorForm.envJson} onChange={(event) => setConnectorForm((current) => ({ ...current, envJson: event.target.value }))} />
                        <FieldHint>Advanced runtime configuration for the connector container. Keep secrets in Secret refs instead of embedding them here.</FieldHint>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label>Spec JSON</Label>
                    <Textarea className="min-h-[520px] font-mono text-xs" value={rawSpecJson} onChange={(event) => setRawSpecJson(event.target.value)} />
                  </div>
                </div>
              )}
            </div>
          )}

          <SheetFooter className="mt-6">
            <Button variant="outline" onClick={() => setEditorState(null)}>Cancel</Button>
            <Button onClick={() => void handleSave()} disabled={saving}>
              {saving ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileCode2 className="h-4 w-4" />}
              {editorState?.mode === "create" ? "Create resource" : "Save changes"}
            </Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      <ConfirmDialog
        open={confirmDeleteOpen}
        onOpenChange={setConfirmDeleteOpen}
        title={`Delete ${selectedDetail?.kind === "reports" || !selectedDetail ? "resource" : selectedDetail.resource.metadata.name}?`}
        description="This action removes the resource from the namespace. Use the raw JSON inspector first if you need to preserve the current configuration."
        confirmLabel="Delete resource"
        variant="destructive"
        onConfirm={() => void handleDelete()}
      />
    </div>
  );
}

export default ObservabilityDashboard;