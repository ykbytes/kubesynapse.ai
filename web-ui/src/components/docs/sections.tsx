import {
  Terminal,
  Server,
  Bot,
  MessageSquare,
  GitBranch,
  ShieldCheck,
  Plug,
  Eye,
  Wrench,
  Globe,
  Bug,
  Rocket,
  Settings,
  Zap,
  ListOrdered,
  FileCode,
  Layers,
  Lightbulb,
  Radio,
  Clock,
  Cpu,
} from "lucide-react";
import { CodeBlock, Callout, DocsTable, QuickRefCard, StepGuide, SectionHeading } from "./shared";
import { MermaidDiagram } from "../shared/MermaidDiagram";
import type { DocSection } from "./types";
import architectureOverviewChart from "../../content/docs/kubesynapse-architecture.mmd?raw";

// ---------------------------------------------------------------------------
// Section content components (one per doc section, each <200 lines)
// ---------------------------------------------------------------------------

function GettingStartedSection() {
  return (
    <div className="space-y-8">
      <QuickRefCard
        title="Quick Start Reference"
        items={[
          { label: "Min Kubernetes", value: "1.25+" },
          { label: "Min Helm", value: "3.12+" },
          { label: "Runtime", value: "OpenCode" },
          { label: "CRD Kind", value: "AIAgent" },
          { label: "API Base", value: "/api/v1" },
        ]}
      />
      <div id="gs-prerequisites">
        <SectionHeading icon={Layers}>Prerequisites</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Before installing kubesynapse, ensure your environment meets the following requirements:
        </p>
        <DocsTable
          headers={["Requirement", "Version", "Notes"]}
          rows={[
            ["Kubernetes", "1.25+ (recommended)", "Any CNCF-certified distribution (EKS, GKE, AKS, Kind, k3s). The chart does not pin a kubeVersion constraint, so older versions may work but are untested."],
            ["Helm", "3.12+ (recommended)", "Required for chart installation and upgrades."],
            ["kubectl", "1.25+ (recommended)", "Must be configured to target your cluster."],
            ["LLM API Key", "—", "OpenAI, Anthropic, OpenRouter, Mistral, OpenCode, or OpenCode Go — any LiteLLM-compatible provider. Wire multiple keys via <code>platformSecrets.native</code> in <code>values.yaml</code>."],
            ["Container Runtime", "—", "Docker or Podman for local image builds."],
          ]}
        />
        <Callout variant="info" title="Resource Recommendations">
          For production deployments, allocate at least 4 vCPU and 8 GiB RAM for the control plane namespace. Each agent
          runtime requests 100m CPU and 256Mi RAM by default (configurable via the <code>AGENT_CPU_REQUEST</code> and
          <code>AGENT_MEMORY_REQUEST</code> env vars on the operator).
        </Callout>
      </div>

      <div id="gs-install">
        <SectionHeading icon={Rocket}>Step 1: Install kubesynapse</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          For local development, use the checked-in Kind helper. For shared clusters, start from the
          cluster values example and install with Helm.
        </p>
        <CodeBlock
          code={`# Local Kind quickstart (PowerShell)
pwsh ./scripts/deploy-kind.ps1

# Cluster install
# 1. Copy the example values file and edit it locally
cp ./deploy/values.cluster.example.yaml ./deploy/values.cluster.yaml

# 2. Deploy with Helm
helm upgrade --install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse \
  --create-namespace \
  -f ./deploy/values.cluster.yaml

# 3. Wait for pods to become ready
kubectl wait --for=condition=ready pod -n kubesynapse -l app=kubesynapse-api-gateway --timeout=300s

# 4. Verify health
curl http://localhost:8080/api/v1/health`}
          lang="bash"
        />
        <Callout variant="config" title="Namespace">
          By default, kubesynapse installs into the <code>kubesynapse</code> namespace. Use <code>--namespace</code> and
          <code>--create-namespace</code> flags to override.
        </Callout>
      </div>

      <div id="gs-secrets">
        <SectionHeading icon={Settings}>Step 2: Configure Secrets</SectionHeading>
        <CodeBlock
          code={`# Edit your local copy of the cluster values file
platformSecrets:
  mode: native
  native:
    openaiApiKey: "sk-..."
    litellmMasterKey: "replace-with-a-long-random-string"
    apiGatewaySharedToken: "replace-with-a-long-random-bearer-token"`}
          lang="yaml"
        />
        <Callout variant="warning" title="Never commit secrets to Git">
          Use external secret operators (e.g., External Secrets Operator, Sealed Secrets, or Vault CSI) for production.
        </Callout>
        <Callout variant="info" title="Helm Values Path">
          The checked-in examples under <code>deploy/</code> match the current chart schema. Use them as the starting point
          for cluster installs instead of older local-only overlays.
        </Callout>
      </div>

      <div id="gs-access">
        <SectionHeading icon={Globe}>Step 3: Access the UI</SectionHeading>
        <StepGuide
          steps={[
            {
              title: "Port-forward the gateway",
              children: (
                <>
                  <CodeBlock code={`kubectl port-forward svc/kubesynapse-api-gateway 8080:8080 -n kubesynapse
kubectl port-forward svc/kubesynapse-web-ui 3000:80 -n kubesynapse`} lang="bash" />
                  <p>Open http://localhost:3000 in your browser.</p>
                </>
              ),
            },
            {
              title: "Configure an Ingress (production)",
              children: (
                <p>
                  Expose the gateway through your cluster ingress controller. The Helm chart supports annotations for
                  cert-manager, NGINX, and Traefik out of the box.
                </p>
              ),
            },
            {
              title: "Log in",
              children: (
                <p>
                  The first install seeds an admin user from the <code>AUTH_BOOTSTRAP_ADMIN_USERNAME</code> and
                  <code>AUTH_BOOTSTRAP_ADMIN_PASSWORD</code> values. Sign in at the login page; configure OIDC or
                  SAML by setting <code>platformSecrets.native.oidcProvidersJson</code> /
                  <code>samlProvidersJson</code> and re-installing or upgrading.
                </p>
              ),
            },
          ]}
        />
      </div>

      <div id="gs-first-agent">
        <SectionHeading icon={Bot}>Step 4: Create Your First Agent</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Apply an <code>AIAgent</code> manifest. The operator provisions a StatefulSet, PVC, and OpenCode runtime
          container for each resource.
        </p>
        <CodeBlock
          code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: my-first-agent
  namespace: default
spec:
  model: gpt-4o
  systemPrompt: |
    You are a helpful assistant running inside kubesynapse.
    Use available tools when needed and stay concise.
  runtime:
    kind: opencode
  storage:
    size: 1Gi`}
          lang="yaml"
        />
        <CodeBlock code={`kubectl apply -f agent.yaml
# Verify
kubectl get aiagent my-first-agent -n default`} lang="bash" />
        <Callout variant="tip" title="Tip">
          Use <code>agentctl health</code> after creating your first agent to verify gateway connectivity and runtime
          status.
        </Callout>
      </div>

      <div id="gs-test">
        <SectionHeading icon={Zap}>Step 5: Test with a Prompt</SectionHeading>
        <StepGuide
          steps={[
            {
              title: "Via the Web UI",
              children: (
                <p>
                  Navigate to <strong>Agents</strong> → Click <strong>my-first-agent</strong> → Select the <strong>Chat</strong> tab → Type a message and send.
                </p>
              ),
            },
            {
              title: "Via the CLI",
              children: (
                <CodeBlock code={`agentctl invoke my-first-agent "Hello, what can you do for me?"
agentctl agents invoke my-first-agent --stream "Stream this response"`} lang="bash" />
              ),
            },
            {
              title: "Via the API",
              children: (
                <CodeBlock
                  code={`curl -X POST http://localhost:8080/api/v1/agents/my-first-agent/invoke \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"Hello, what can you do for me?"}'`}
                  lang="bash"
                />
              ),
            },
          ]}
        />
        <Callout variant="tip" title="Next: Architecture">
          Once KubeSynapse is running, continue to <strong>Architecture</strong> to learn how the
          control plane, 13 CRDs, execution plane, and multi-tenancy with <code>AgentTenant</code> fit together.
        </Callout>
      </div>
    </div>
  );
}

function ArchitectureSection() {
  return (
    <div className="space-y-8">
      <QuickRefCard
        title="Architecture Quick Reference"
        items={[
          { label: "Control Plane", value: "13 CRDs + Operator + Gateway" },
          { label: "Execution Plane", value: "StatefulSets + Jobs + MCP" },
          { label: "Model Path", value: "Runtime -> LiteLLM" },
          { label: "Operator", value: "Kopf-based Python controller" },
          { label: "Runtime", value: "OpenCode (production)" },
        ]}
      />
      <div id="arch-overview">
        <SectionHeading icon={Layers}>System Overview</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          kubesynapse separates the <strong>control plane</strong> (13 CRDs, operator, gateway) from the{" "}
          <strong>execution plane</strong> (per-agent runtimes, worker Jobs, and MCP access). The gateway owns auth,
          CRUD, durable memory, and trace APIs, while the runtime makes the primary LiteLLM model calls.
        </p>
        <MermaidDiagram chart={architectureOverviewChart} />
      </div>
      <div id="arch-tenant">
        <SectionHeading icon={Layers}>Multi-Tenancy — AgentTenant</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          <code>AgentTenant</code> is a cluster-scoped CRD that carves out a namespace, resource
          quota, model allow-list, and admin roster for a team. The operator and gateway both
          enforce tenant boundaries — agents outside a tenant cannot reference its policies,
          and the operator caps concurrent workflow steps at <code>resourceQuota.maxParallelSteps</code>,
          throttling (not refusing) the worker pool when the cap is reached.
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["tenantName", "string (required)", "Human-readable name (e.g. <code>data-science-team</code>)"],
          ["namespace", "string (required)", "Kubernetes namespace that this tenant owns"],
          ["resourceQuota.maxCPU / maxMemory / maxPods / maxGPU", "string / string / integer / string", "Hard caps applied to the tenant's namespace"],
          ["resourceQuota.maxParallelSteps", "integer (min: 1, default: 4)", "Maximum parallel workflow steps per execution for this tenant. Default is a documented convention — the CRD does not set a server-side default."],
          ["allowedModels", "string[]", "LLM model identifiers this tenant may use (e.g. <code>gpt-4o</code>, <code>claude-3-5-sonnet</code>)"],
          ["adminUsers", "string[]", "OIDC usernames or groups who can manage agents in this tenant"],
        ]} />
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AgentTenant
metadata:
  name: data-science-team
spec:
  tenantName: Data Science
  namespace: ds-team
  resourceQuota:
    maxCPU: "16"
    maxMemory: "32Gi"
    maxPods: 50
    maxGPU: "2"
    maxParallelSteps: 8
  allowedModels:
    - gpt-4o
    - claude-3-5-sonnet-20241022
  adminUsers:
    - ds-admins@example.com`} lang="yaml" />
      </div>

      <div id="arch-control">
        <SectionHeading icon={FileCode}>Control Plane — CRDs</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          The platform installs and reconciles the following custom resources:
        </p>
        <DocsTable
          headers={["CRD", "Scope", "Purpose"]}
          rows={[
            ["AIAgent", "Namespaced", "Defines an agent model, system prompt, policy reference, MCP integrations, and storage."],
            ["AgentPolicy", "Namespaced", "Defines input/output guardrails, per-request token caps, and allowed models."],
            ["AgentApproval", "Namespaced", "Represents human approval requests for high-risk actions."],
            ["AgentWorkflow", "Namespaced", "Defines multi-step agent DAGs with dependencies and optional approval gates."],
            ["AgentTenant", "Cluster", "Defines namespace isolation, quotas, allowed models, and tenant admins."],
            ["ConnectorPlugin", "Namespaced", "Declares how observability data is collected."],
            ["ObservationTarget", "Namespaced", "Declares what is being observed."],
            ["ObservationPolicy", "Namespaced", "Declares how collected telemetry is evaluated."],
            ["ObservationReport", "Namespaced", "Stores the resulting health or anomaly output."],
            ["McpConnection", "Namespaced", "Defines a connection to an MCP server (transport, auth, capabilities)."],
            ["WebhookReceiver", "Namespaced", "Receives external webhook events with signature verification, IP filtering, and provider-specific adapters."],
            ["WorkflowTrigger", "Namespaced", "Triggers workflows or agents based on webhook events, AgentEvents, or schedule criteria."],
            ["AgentIncident", "Namespaced", "Actionable alert managed by the operator; integrates with Alertmanager and auto-triggers remediation workflows."],
          ]}
        />
        <MermaidDiagram
          chart={`erDiagram
    AgentPolicy ||--o{ AIAgent : referenced_by
    McpConnection ||--o{ AIAgent : used_by
    AIAgent ||--o{ AgentWorkflow : referenced_by
    AgentWorkflow ||--o{ AgentApproval : creates
    WebhookReceiver ||--o{ WorkflowTrigger : feeds
    WorkflowTrigger ||--o{ AgentWorkflow : starts
    AgentTenant ||--o{ AIAgent : scopes
    AgentTenant ||--o{ AgentWorkflow : scopes
    ConnectorPlugin ||--o{ ObservationTarget : collects_for
    ObservationPolicy ||--o{ ObservationTarget : evaluates
    ObservationPolicy ||--o{ ObservationReport : produces`}
        />
      </div>
      <div id="arch-execution">
        <SectionHeading icon={Server}>Execution Plane</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Each agent runs as an isolated singleton StatefulSet backed by the <strong>OpenCode</strong> runtime
          with session persistence and checkpoint recovery. Additional runtimes (Pi, Mistral Vibe) are available in
          alpha but not recommended for production. Workflow runs use short-lived Jobs whose detailed evidence lives in
          artifacts and logs. MCP access can come from 10 bundled tool sidecars plus a separate collector sidecar, or
          shared MCP hub connections.
        </p>
        <MermaidDiagram
          chart={`flowchart TB
    subgraph Pod[Agent Pod]
        RT[OpenCode Runtime<br/>FastAPI + opencode serve]
        SC1[Tool Sidecar<br/>e.g., Code Execution]
        SC2[Collector Sidecar<br/>optional]
        PVC[(State PVC<br/>Sessions + Workspace)]
    end
    HUB[MCP Hub<br/>shared services]
    RT <-->|localhost| SC1
    RT <-->|localhost| SC2
    RT -.->|remote connection| HUB
    RT -->|read/write| PVC`}
        />
      </div>
      <div id="arch-gateway">
        <SectionHeading icon={Globe}>API Gateway Responsibilities</SectionHeading>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          <li>Authentication and authorization (Bearer tokens, OIDC, SAML, LDAP, local auth)</li>
          <li>RESTful CRUD for agents, workflows, policies, tenants, MCP connections, and observability resources</li>
          <li>Invoke routing, workflow triggers, approval decisions, and webhook dispatch</li>
          <li>A2A JSON-RPC 2.0 and Server-Sent Events (SSE) for real-time streaming</li>
          <li>Durable chat sessions, memory recall, trace storage, and UI-facing runtime metadata</li>
          <li>Provider and admin APIs for LiteLLM-backed model discovery and configuration</li>
        </ul>
        <Callout variant="info" title="Security hardening (updated 2026-05-24)">
          The gateway runs with a dedicated service account and least-privilege ClusterRole.
          Key hardening measures include:
          <code>pods/exec</code> removed, <code>hmac.compare_digest</code> for constant-time
          token comparison, argon2id password hashing, per-agent NetworkPolicies, auto-generated
          Redis/NATS credentials, and separate collector token (no longer shares JWT_SECRET).
          Cross-namespace secrets and <code>pods/log</code> access for the gateway SA have been
          enabled. API rate limiting protects the agent invoke endpoint (60 req/min per user).
        </Callout>
      </div>
    </div>
  );
}

function AgentsSection() {
  return (
    <div className="space-y-8">
      <QuickRefCard
        title="Agent Quick Reference"
        items={[
          { label: "CRD Kind", value: "AIAgent" },
          { label: "Required Fields", value: "name, model, runtime.kind" },
          { label: "Runtimes", value: "opencode (production)" },
          { label: "API Endpoint", value: "POST /api/v1/agents" },
          { label: "Storage Default", value: "1Gi PVC" },
        ]}
      />
      <div id="agent-crd">
        <SectionHeading icon={FileCode}>AIAgent CRD Reference</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          The <code>AIAgent</code> custom resource is the core unit of KubeSynapse. The operator provisions
          a dedicated StatefulSet, PVC, and runtime container for each agent.
        </p>

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Core Fields</h3>
        <DocsTable
          headers={["Field", "Type", "Required", "Description"]}
          rows={[
            ["spec.model", "string", "Yes", "LLM model identifier routed through LiteLLM (e.g., gpt-4o, claude-3-sonnet)."],
            ["spec.systemPrompt", "string", "No", "System instruction defining behavior, responsibilities, and output format."],
            ["spec.runtime.kind", "string", "Yes", "Runtime engine: opencode (production), pi (alpha), or mistral-vibe (alpha)."],
            ["spec.policyRef", "string", "No", "AgentPolicy name in the same namespace (or namespace/name for cross-namespace)."],
            ["spec.enableGVisor", "boolean", "No", "Run the runtime container inside a gVisor sandbox for additional isolation."],
            ["spec.storage.size", "string", "No", "PVC size (e.g., 1Gi, 5Gi). Default: 1Gi."],
            ["spec.storage.storageClassName", "string", "No", "StorageClass for the agent's PVC."],
            ["spec.resources.requests.cpu", "string", "No", "CPU request (e.g., 500m)."],
            ["spec.resources.requests.memory", "string", "No", "Memory request (e.g., 512Mi)."],
            ["spec.resources.limits.cpu", "string", "No", "CPU limit."],
            ["spec.resources.limits.memory", "string", "No", "Memory limit."],
          ]}
        />

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Runtime Configuration</h3>
        <DocsTable
          headers={["Field", "Type", "Description"]}
          rows={[
            ["runtime.kind", "opencode | pi | mistral-vibe", "Runtime engine selector. opencode is the production runtime (pi and mistral-vibe are alpha)."],
            ["runtime.opencode.configFiles", "object", "Inline ConfigMap-style files injected into the OpenCode runtime (max 64 files, ~64 KB per file, ~256 KB total; paths ≤ 256 chars)."],
            ["runtime.pi.provider", "string", "Pi runtime: provider override (e.g., <code>anthropic</code>, <code>openai</code>)."],
            ["runtime.pi.model", "string", "Pi runtime: model override (e.g., <code>claude-3-sonnet</code>)."],
            ["runtime.pi.thinkingLevel", "low | medium | high", "Pi runtime: chain-of-thought depth."],
            ["runtime.pi.noTools", "boolean", "Pi runtime: disable all tool calls (pure chat)."],
            ["runtime.pi.tools", "string[]", "Pi runtime: allow-list of tool names."],
            ["runtime.pi.noSession", "boolean", "Pi runtime: skip session persistence."],
            ["runtime.pi.permissionLevel", "ask | allow | deny", "Pi runtime: default permission ceiling for tool calls."],
            ["runtime.mistralVibe.model", "string", "Mistral Vibe runtime: model override."],
            ["runtime.mistralVibe.noSession", "boolean", "Mistral Vibe runtime: skip session persistence."],
          ]}
        />

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Git & GitHub Configuration</h3>
        <DocsTable
          headers={["Field", "Type", "Required", "Description"]}
          rows={[
            ["gitConfig.repoUrl", "string", "Yes*", "Git repository URL for autonomous file operations."],
            ["gitConfig.defaultBranch", "string", "No", "Default branch name (e.g., main)."],
            ["gitConfig.branch", "string", "No", "Specific branch to work on."],
            ["gitConfig.pushPolicy", "after-each-commit | end-of-session | on-approval | never", "No", "When to push changes. The CRD does not set a default — the web-UI form initializes new agents to <code>on-approval</code>."],
            ["gitConfig.authMethod", "token | basic | ssh", "Yes*", "Authentication method."],
            ["gitConfig.credentialSecretRef", "string", "Yes*", "K8s Secret holding the credential."],
            ["githubConfig.credentialSecretRef", "string", "Yes*", "Secret for GitHub API access (GitHub MCP)."],
          ]}
        />
        <Callout variant="info" title="Required when gitConfig is present">
          Fields marked with * are required only when the parent object is specified.
        </Callout>

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">MCP Configuration</h3>
        <DocsTable
          headers={["Field", "Type", "Description"]}
          rows={[
            ["mcpConnections[].connectionId", "string", "Opaque identifier of a saved <code>McpConnection</code> (matches the gateway DB row)."],
            ["mcpConnections[].name", "string", "Display name for this connection."],
            ["mcpConnections[].slug", "string", "URL-safe slug used as the gateway-side routing key."],
            ["mcpConnections[].serverId", "string", "Registry server ID or name (remote transport)."],
            ["mcpConnections[].transport", "remote | hub | sidecar", "Connection transport type."],
            ["mcpConnections[].source", "string", "Origin of the connection definition."],
            ["mcpServers", "string[]", "Legacy MCP server name references."],
            ["mcpSidecars[].name", "string", "Sidecar container name."],
            ["mcpSidecars[].image", "string", "Sidecar container image."],
            ["mcpSidecars[].port", "integer", "Sidecar listening port."],
          ]}
        />

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">A2A & Namespace Access</h3>
        <DocsTable
          headers={["Field", "Type", "Default", "Description"]}
          rows={[
            ["a2a.allowedCallers[].name", "string", "—", "Peer agent name permitted to call this agent."],
            ["a2a.allowedCallers[].namespace", "string", "—", "Peer agent namespace."],
            ["allowedNamespaces.from", "Same | All | Selector", "Same", "Which namespaces may reference this agent's policy."],
            ["allowedNamespaces.selector", "object", "—", "Label selector when from=Selector."],
          ]}
        />

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Skills</h3>
        <DocsTable
          headers={["Field", "Type", "Description"]}
          rows={[
            ["skills.files", "object (string → string)", "Map of relative .md file paths to content. Max 24 files, 16 KB each, 64 KB total; paths ≤ 256 chars."],
            ["skills.configMapRef", "string", "Reference to a ConfigMap containing skill files."],
          ]}
        />

        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">OPA Policy Enforcement</h3>
        <DocsTable
          headers={["Field", "Type", "Description"]}
          rows={[
            ["opa.enabled", "boolean", "Enable Open Policy Agent evaluation for this agent."],
            ["opa.policies", "string[]", "Policy names to evaluate."],
            ["opa.configMapRef", "string", "ConfigMap containing Rego policies."],
          ]}
        />
      </div>
      <div id="agent-example">
        <SectionHeading icon={FileCode}>Complete YAML Example</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          This manifest demonstrates every major field of the AIAgent CRD.
        </p>
        <CodeBlock
          code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: code-reviewer
  namespace: default
  labels:
    team: platform
    env: production
spec:
  model: gpt-4o
  systemPrompt: |
    You are a senior platform engineer. Review code diffs
    for correctness, security, and performance.
  runtime:
    kind: opencode
    opencode:
      configFiles:
        review-rules.md: |
          # Review Rules
          - Check for SQL injection
          - Verify error handling
  storage:
    size: 2Gi
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: "2"
      memory: 2Gi
  enableGVisor: false
  policyRef: strict-policy
  allowedNamespaces:
    from: Same
  mcpConnections:
    - connectionId: conn-github-prod
      name: GitHub Production
      transport: hub
    - connectionId: conn-k8s-prod
      name: Kubernetes API
      transport: remote
  mcpSidecars:
    - name: code-exec
      image: kubesynapse/mcp-code-exec:latest
      port: 8000
  skills:
    files:
      review-guide.md: |
        # Review Guide
        - Prefer early returns
        - Use descriptive variable names
    configMapRef: shared-review-rules
  a2a:
    allowedCallers:
      - name: planner-agent
        namespace: default
  gitConfig:
    repoUrl: https://github.com/acme/platform
    defaultBranch: main
    pushPolicy: on-approval
    authMethod: token
    credentialSecretRef: git-credentials
  githubConfig:
    credentialSecretRef: github-token
  opa:
    enabled: true
    policies:
      - require-code-review
    configMapRef: opa-policies`}
          lang="yaml"
        />
      </div>
      <div id="agent-prompt">
        <SectionHeading icon={Lightbulb}>System Prompt Best Practices</SectionHeading>
        <Callout variant="tip" title="Write prompts like job descriptions">
          A high-quality system prompt defines the agent's <strong>mission</strong>,{" "}
          <strong>responsibilities</strong>, <strong>non-responsibilities</strong>, and <strong>output format</strong>.
          Avoid vague one-liners for non-trivial agents.
        </Callout>
        <StepGuide
          steps={[
            { title: "Define the business objective", children: <p>Start with why the agent exists and what outcome it produces.</p> },
            { title: "Set clear responsibilities", children: <p>List specific tasks the agent is expected to perform and tools it should use.</p> },
            { title: "Define non-responsibilities", children: <p>Explicitly state what the agent must NOT do to prevent scope creep.</p> },
            { title: "Specify output formatting", children: <p>Request structured output when downstream systems consume the result.</p> },
            { title: "Add failure handling guidance", children: <p>Tell the agent how to behave when tools fail or inputs are ambiguous.</p> },
          ]}
        />
      </div>
      <div id="agent-storage">
        <SectionHeading icon={Server}>Storage Configuration</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          The <code>storage.size</code> field controls the PVC attached to the agent's StatefulSet. This volume stores:
        </p>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          <li>Conversation session checkpoints</li>
          <li>Sandbox artifacts and tool outputs</li>
          <li>Git clones and working directories</li>
          <li>Runtime configuration caches</li>
        </ul>
        <Callout variant="info" title="Resizing">
          Edit the <code>storage.size</code> field and re-apply the manifest. The operator will attempt a PVC resize if
          your storage class supports volume expansion.
        </Callout>
      </div>
      <div id="agent-skills">
        <SectionHeading icon={FileCode}>Skills (File-Backed)</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Skills are file-backed context packages attached to an agent. You can embed Markdown guides, JSON schemas,
          or example conversations directly in the manifest.
        </p>
        <CodeBlock
          code={`spec:
  skills:
    files:
      api-style-guide.md: |
        # REST API Style Guide
        - Use kebab-case for URLs
        - Return 409 Conflict for duplicate resources
      openapi-schema.json: |
        { "openapi": "3.0.0", ... }`}
          lang="yaml"
        />
      </div>
      <div id="agent-create-guide">
        <SectionHeading icon={Rocket}>How to Create Your First Agent</SectionHeading>
        <StepGuide
          steps={[
            { title: "Choose a model", children: <p>Open <strong>Settings → Models</strong> and verify your desired model is connected via LiteLLM.</p> },
            { title: "Navigate to Agents", children: <p>Click <strong>Agents</strong> in the sidebar, then click <strong>Create Agent</strong>.</p> },
            { title: "Fill required fields", children: <p>Name must be DNS-label safe (lowercase, alphanumeric, hyphens). Select model and write system prompt.</p> },
            { title: "Configure optional settings", children: <p>Storage size (default 1Gi), policy, and MCP connections.</p> },
            { title: "Save and verify", children: <p>The operator provisions the StatefulSet within 10–30 seconds. Watch the status indicator turn green.</p> },
            { title: "Test in chat", children: <p>Select the agent and open the <strong>Chat</strong> tab. Send a test prompt to confirm.</p> },
          ]}
        />
      </div>
    </div>
  );
}

/* Remaining sections follow the same pattern — each <200 lines of JSX content */
function ChatSessionsSection() {
  return (
    <div className="space-y-8">
      <QuickRefCard title="Chat Reference" items={[
        { label: "History API", value: "GET /api/v1/chat-sessions" },
        { label: "Streaming Invoke", value: "POST /api/v1/agents/{name}/invoke/stream" },
        { label: "Storage", value: "PostgreSQL (default) or SQLite (local dev fallback at <code>$TMP/kubesynapse-gateway.db</code>)" },
      ]} />
      <div id="chat-basics">
        <SectionHeading icon={MessageSquare}>Chat Session Basics</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Live responses and saved history are related but separate. Invoke calls hit the agent runtime,
          while chat-session history is stored by the gateway and listed per <code>agent_name</code> and namespace.
        </p>
        <CodeBlock code={`# List sessions for one agent
curl "http://localhost:8080/api/v1/chat-sessions?agent_name=my-agent&namespace=default" \\
  -H "Authorization: Bearer $TOKEN"

# Create a session
curl -X POST "http://localhost:8080/api/v1/chat-sessions?namespace=default" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"agent_name": "my-agent", "title": "Incident triage"}'

# Replace the full stored message list for a session
curl -X PUT http://localhost:8080/api/v1/chat-sessions/session-123/messages \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"messages":[{"message_id":"msg-1","role":"user","content":"Explain Kubernetes controllers","status":"complete"}]}'

# Patch a session (rename title)
curl -X PATCH "http://localhost:8080/api/v1/chat-sessions/session-123" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"title": "Renamed session"}'

# Delete a session
curl -X DELETE "http://localhost:8080/api/v1/chat-sessions/session-123" \\
  -H "Authorization: Bearer $TOKEN"

# Stream a live invoke
curl -N -X POST http://localhost:8080/api/v1/agents/my-agent/invoke/stream \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"prompt":"Explain Kubernetes controllers"}'`} lang="bash" />
        <Callout variant="info" title="Persistence semantics">
          Saving chat messages replaces the stored message array for that session. Memory auto-promotion happens
          from runtime invoke outcomes (workflow step results, HITL responses), not from this endpoint —
          the runtime continues to manage its own thread state independently.
        </Callout>
        <Callout variant="tip" title="Related: Memory & Context">
          Chat sessions feed into the durable memory system. See <strong>Memory & Context</strong> for how
          conversation highlights are promoted to persistent recall, the auto-promotion scoring formula,
          and supported memory types (<code>procedural</code>, <code>episodic</code>).
        </Callout>
      </div>
    </div>
  );
}

function MemorySection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={GitBranch}>Memory & Context</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        KubeSynapse uses a two-tier memory model: <strong>durable memory</strong> in PostgreSQL managed by
        the gateway, and <strong>runtime-local memory</strong> (file-based JSONL + optional Qdrant semantic
        search) inside each agent pod.
      </p>

      <div id="memory-overview">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Architecture</h3>
        <DocsTable headers={["Component", "Technology", "Purpose"]} rows={[
          ["Gateway durable memory", "PostgreSQL memory_records", "Cross-session promoted recall and ranking"],
          ["Runtime-local memory", "JSONL under OPENCODE_MEMORY_DIR", "Thread continuity (100 thread / 50 workspace entries)"],
          ["Semantic retrieval", "Optional Qdrant", "Cosine distance search (768-dim) with LONG_TERM / PERMANENT retention"],
          ["Policy layer", "AgentPolicy.memoryPolicy", "Controls maxInjectedMemories, maxInjectedChars, allowedMemoryTypes, and auto-promotion"],
        ]} />
      </div>

      <div id="memory-promotion">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Auto-Promotion & Ranking</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Memory records are promoted from ephemeral conversation context to durable recall when they
          meet a quality threshold. The gateway ranks promoted memories before injecting them into the agent context.
        </p>
        <DocsTable headers={["Mechanism", "Detail"]} rows={[
          ["Auto-promotion threshold", "Score >= 4.0 triggers automatic promotion. Records below this can be manually promoted."],
          ["Fallback retrieval", "When no promoted records exist, the gateway falls back to records with score >= 3.5 (up to 20, or up to the caller's <code>limit</code> parameter — default 8)."],
          ["Ranking formula", "token_overlap * 3.0 + procedural_type_bonus (2.0 for procedural, 0.5 for other kinds) + recency_bonus + stored_score"],
          ["SHA-256 dedup", "New memory content is hashed and checked against existing records to avoid duplicates."],
          ["Injection format", 'Memory is prepended to the system prompt as a 3-part block: a header line ("You have persistent memory from prior conversations…"), a bullet "- [{topic}] {content[:280]}" per record, and a footer line. The runtime context window also has 5 retention tiers: EPHEMERAL, SESSION, WORKSPACE, LONG_TERM, PERMANENT (LONG_TERM and PERMANENT go to Qdrant semantic store; SESSION and WORKSPACE go to JSONL).'],
          ["Memory types", "Two kind values: <code>procedural</code> (recurring how-to patterns) and <code>episodic</code> (time-bounded events). Each record also carries a free-form <code>topic</code> string — common values are <code>response-summary</code>, <code>assistant-summary</code>, <code>repo-convention</code>, <code>workflow-outcome</code>, <code>workflow-success</code>, <code>workflow-failure</code>, <code>tool-usage</code>; default is <code>note</code>."],
          ["Retention", "Records are stored in PostgreSQL <code>memory_records</code>. The operator-driven GC enforces the configured retention policy."],
          ["Default policy", "Gateway normalizes missing fields: <code>maxInjectedMemories=8</code>, <code>maxInjectedChars=2400</code>, <code>autoPromote=true</code> (CRD default is <code>false</code> — gateway overrides to true at the API boundary)."],
        ]} />
      </div>

      <div id="memory-policy">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Memory Policy Controls</h3>
        <DocsTable headers={["Field", "Type", "Default", "Description"]} rows={[
          ["memoryPolicy.maxInjectedMemories", "integer", "8", "Maximum promoted records injected per request"],
          ["memoryPolicy.maxInjectedChars", "integer", "2400", "Total character limit for injected memory (prevents context-window blowout)"],
          ["memoryPolicy.allowedMemoryTypes", "string[]", "empty (allow all)", "Optional allow-list of memory types (e.g. procedural, episodic)"],
          ["memoryPolicy.autoPromote", "boolean", "true", "Whether high-signal memories are auto-promoted without manual pinning"],
        ]} />
      </div>

      <div id="memory-sources">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">How Memory Is Created</h3>
        <DocsTable headers={["Source", "Mechanism"]} rows={[
          ["Runtime-emitted", "OpenCode runtime emits metadata.memory in invoke responses → gateway calls record_runtime_memory()"],
          ["Chat summarization", "Chat session message batches are analyzed → candidates recorded → auto-promoted at score >= 4.0"],
          ["Workflow outcomes", "Completed/failed workflows produce episodic/procedural memory entries via record_workflow_outcome_memory()"],
        ]} />
        <Callout variant="info" title="Stream parity">
          Durable memory is injected on both sync and streamed invokes. If the gateway needs to assemble a
          memory-heavy system prompt first, it can preserve parity by emitting SSE from a non-stream runtime invoke.
        </Callout>
        <Callout variant="tip" title="Related: Chat Sessions & Agent Policies">
          Durable memory is promoted from chat session context (see <strong>Chat Sessions</strong>).
          Auto-promotion thresholds, max-injected counts, and allowed memory types are governed by
          <code>AgentPolicy.memoryPolicy</code> (see <strong>Agent Policies → Memory Policy</strong>).
        </Callout>
      </div>
    </div>
  );
}

function WorkflowsSection() {
  return (
    <div className="space-y-8">
      <QuickRefCard title="Workflows Quick Reference" items={[
        { label: "CRD Kind", value: "AgentWorkflow" },
        { label: "Max Steps", value: "100" },
        { label: "Parallelism", value: "DAG wave-based" },
        { label: "Phases", value: "pending → queued → running → (waiting-approval) → completed / failed / cancelled" },
      ]} />
      <div id="wf-overview">
        <SectionHeading icon={ListOrdered}>Workflow Overview</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          An <code>AgentWorkflow</code> defines a multi-step DAG. The operator topologically sorts steps
          and dispatches them in waves — all frontier steps with no unsatisfied dependencies run in parallel
          (capped at <code>maxParallelSteps</code> per tenant; the cap is on concurrent worker tasks, not the
          number of steps queued in the frontier). Failed steps fail-fast by default, cancelling siblings.
        </p>
      </div>

      <div id="wf-step-types">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Step Types</h3>
        <DocsTable headers={["Type", "Behavior", "When to Use"]} rows={[
          ["agent", "Prompt rendering → agent invoke → JSON output extraction → optional verification retry loop", "Standard agent call with prompt templates and output constraints"],
          ["loop", "Work plan generation → iteration loop with circuit breaker and exit conditions", "Batch processing, checklist-backed automation, multi-item workflows"],
          ["conditional", "Expression evaluation against dependency outputs → branch to thenSteps or elseSteps", "Decision trees, quality gates, A/B routing"],
          ["review", "Review prompt → agent invocation → APPROVED/REJECTED verdict parsing", "Human-like review gate when approval CR is not needed"],
        ]} />
      </div>

      <div id="wf-step-config">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Step Configuration</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["name", "string (required)", "Step identifier, must be unique within the workflow"],
          ["type", "agent | loop | conditional | review", "Step type (default: agent)"],
          ["agentRef", "string", "AIAgent CR name to execute. Required for agent / loop / review types."],
          ["prompt", "string", "Template supporting {{input}}, {{previous_output}}, and {{stepname.path}} references"],
          ["dependsOn", "string[]", "Step names that must complete before this step can start"],
          ["requireApproval", "boolean", "Pause for HITL approval via AgentApproval CR before execution"],
          ["verify", "string", "Verification prompt; step fails if the verification response is not PASS"],
          ["reviewCriteria", "string", "Required for <code>type: review</code> steps — criteria the reviewer checks"],
          ["execution.timeoutSeconds", "integer", "Per-step deadline (min: 1)"],
          ["execution.maxAttempts", "integer", "Retry limit (min: 1)"],
          ["execution.backoffSeconds", "integer", "Delay between retries (min: 0)"],
          ["execution.retryable", "boolean", "Whether the step is eligible for auto-retry"],
          ["execution.continueOnError", "boolean", "Continue workflow even if this step fails"],
          ["execution.maxTurns", "integer", "Max agent turns per step (0 = unlimited)"],
          ["execution.preAuthorizedActions", "string[]", "Actions allowed without HITL (e.g. read-only commands)"],
          ["execution.sessionGroup", "string", "Group key for sharing sandbox sessions across steps"],
          ["execution.verifyRetries", "integer", "Max verification attempts (min: 0)"],
          ["execution.requiredJsonPaths", "string[]", "JSON paths that must exist in the step output"],
        ]} />
      </div>

      <div id="wf-loop-config">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Loop Configuration (type: loop)</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["loopConfig.maxIterations", "integer", "Safety ceiling on loop passes (min: 1)"],
          ["loopConfig.planSource", "inline | prompt", "inline: use the plan field. prompt: have the agent generate the plan."],
          ["loopConfig.plan", "string", "Markdown checkbox items for inline plan source"],
          ["loopConfig.commitAfterEachItem", "boolean", "Commit git changes after each checklist item"],
          ["loopConfig.circuitBreaker.noProgressThreshold", "integer", "Consecutive passes with no progress before opening the circuit (min: 1)"],
          ["loopConfig.circuitBreaker.cooldownMinutes", "integer", "Cooldown before the circuit can half-open (min: 1)"],
          ["loopConfig.exitConditions.planComplete", "boolean", "Exit when all checklist items are done"],
          ["loopConfig.exitConditions.completionSignalCount", "integer", "Number of completion signals required (min: 1)"],
        ]} />
      </div>

      <div id="wf-conditional">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Conditional Branching</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["conditionExpr", "string", "Safe condition expression against dependency output paths. Operators: <code>contains</code>, <code>equals</code>, <code>not_equals</code>, <code>starts_with</code>, <code>ends_with</code>, <code>length_gt</code>, <code>length_lt</code>, <code>is_empty</code>, <code>not_empty</code>, <code>matches</code>; combine with <code>and</code> / <code>or</code> / <code>not</code> and string/numeric literals."],
          ["thenSteps", "string[]", "Step names to activate when the condition is true"],
          ["elseSteps", "string[]", "Step names to activate when the condition is false"],
        ]} />
        <Callout variant="tip" title="Conditional steps skip agentRef">
          Conditional steps do not invoke agents directly — they evaluate expressions against previous step
          outputs and activate or skip downstream steps accordingly. Use them for quality gates, decision
          trees, and A/B routing without consuming LLM tokens.
        </Callout>
      </div>

      <div id="wf-auto-retry">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Workflow-Level Auto-Retry</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["autoRetry.enabled", "boolean", "Enable periodic watchdog retry for failed workflows"],
          ["autoRetry.maxAttempts", "integer", "Maximum total retry attempts (min: 0)"],
          ["autoRetry.retryableFailureClasses", "string[]", "Error classes that trigger a retry (e.g. TimeoutError, ReadTimeout)"],
          ["autoRetry.nonRetryableFailureClasses", "string[]", "Error classes that permanently block retry (e.g. ReviewRejectedError)"],
        ]} />
        <Callout variant="info" title="Default retryable errors">
          TimeoutError, ConnectTimeout, ReadTimeout, PoolTimeout, RemoteProtocolError, ConnectError,
          ReadError, ApiException. Approval denials, verification failures, and review rejections are
          non-retryable by default.
        </Callout>
      </div>

      <div id="wf-example">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Complete Example</h3>
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: incident-response
spec:
  description: Automated security incident triage and remediation
  input: "Suspicious outbound connection from prod-web-03"
  autoRetry:
    enabled: true
    maxAttempts: 3
  messageBus: in-memory
  steps:
    - name: triage
      agentRef: security-analyst
      prompt: "Analyze severity: {{input}}"
    - name: collect-evidence
      agentRef: forensics
      prompt: "Collect logs and captures for {{input}}"
      dependsOn: [triage]
    - name: assess-impact
      agentRef: security-analyst
      prompt: "Assess blast radius: {{previous_output}}"
      dependsOn: [triage, collect-evidence]
      execution:
        timeoutSeconds: 300
        maxTurns: 8
    - name: quality-gate
      type: conditional
      conditionExpr: "contains(assess-impact, 'critical')"
      thenSteps: [contain]
      elseSteps: [document]
      dependsOn: [assess-impact]
    - name: contain
      agentRef: incident-response
      prompt: "Contain the threat based on: {{assess-impact}}"
      requireApproval: true
      dependsOn: [quality-gate]
      verify: "Did containment succeed with no collateral damage?"
    - name: document
      agentRef: doc-writer
      prompt: "Generate incident report from: {{triage}} and {{assess-impact}}"
      dependsOn: [contain, quality-gate]
    - name: batch-patches
      type: loop
      agentRef: patch-applier
      dependsOn: [document]
      loopConfig:
        maxIterations: 10
        planSource: inline
        plan: |
          - [ ] Patch CVE-2024-001 on prod-web-01
          - [ ] Patch CVE-2024-001 on prod-web-02
          - [ ] Patch CVE-2024-001 on prod-web-03
          - [ ] Verify patch application via kubectl get pods
        commitAfterEachItem: true
        circuitBreaker:
          noProgressThreshold: 3
          cooldownMinutes: 5
        exitConditions:
          planComplete: true`} lang="yaml" />
      </div>
    </div>
  );
}

function McpSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Plug}>MCP (Model Context Protocol)</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        MCP connections provide tool surfaces to agents. KubeSynapse supports three transport models
        and ships 10 bundled MCP tool sidecars plus a separate <code>collector</code> sidecar in the current chart values.
      </p>

      <div id="mcp-transports">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Transport Models</h3>
        <DocsTable headers={["Transport", "Use Case", "Security"]} rows={[
          ["remote", "External MCP servers and SaaS bridges", "Stored credentials; 7 auth types (none, bearer, basic, oauth2, apiKey, mTLS, token)"],
          ["hub", "Shared in-cluster MCP services in mcp-hub namespace", "Bearer token auth; default-deny NetworkPolicies; allow ingress from <code>app=ai-agent</code> pods in namespaces labelled <code>kubesynapse.ai/tenant=true</code>"],
          ["sidecar", "Per-agent local tool containers", "localhost-only; strongest isolation; non-root UID 1000; readOnlyRootFilesystem; drop ALL capabilities"],
        ]} />
      </div>

      <div id="mcp-sidecars">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Bundled Sidecars</h3>
        <DocsTable headers={["Sidecar", "Capability"]} rows={[
          ["code-exec", "Sandboxed Python, Node.js, and Bash execution"],
          ["web-search", "Web search with summarization"],
          ["browser", "Headless browser, screenshots, form interaction"],
          ["database", "SQL and NoSQL queries"],
          ["git", "Clone, diff, commit, branch operations"],
          ["github-adapter", "PRs, issues, releases, repo management"],
          ["kubernetes", "In-cluster resource queries and constrained mutations"],
          ["messaging", "Slack, Discord, email integrations"],
          ["rag", "Retrieval-augmented generation with vector search"],
          ["documents", "PDF, DOCX, Markdown parsing"],
        ]} />
      </div>

      <div id="mcp-connection">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Connection Management</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["serverId", "string (required)", "Registry server ID or name"],
          ["transport", "remote | hub | sidecar (required)", "Connection transport type"],
          ["endpoint", "string (uri)", "Server endpoint URL (remote transports)"],
          ["authType", "none | bearer | basic | oauth2 | apiKey | mTLS | token", "Authentication method (default: none)"],
          ["credentialSecretRef", "object", "K8s Secret reference with credential keys"],
          ["displayName", "string", "Human-readable name (max 128 chars)"],
        ]} />
        <Callout variant="info" title="Connection validation">
          Remote connections are validated via HTTP GET to the endpoint with resolved headers. Hub connections
          check <code>http://{'{release}'}-mcp-{'{server}'}.mcp-hub.svc.cluster.local:8000/mcp</code>
          (port 8000, path <code>/mcp</code>; <code>{'{release}'}</code> is the Helm release name, default prefix
          <code>kubesynapse-mcp-</code>). Sidecar connections are accepted as valid at save time — reachability
          is confirmed when the agent pod first starts.
        </Callout>
      </div>

      <div id="mcp-hub">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">MCP Hub Architecture</h3>
        <DocsTable headers={["Aspect", "Detail"]} rows={[
          ["Namespace", "Dedicated mcp-hub namespace with kubesynapse.ai/mcp-hub: true label"],
          ["Per-server isolation", "Each MCP server gets its own Deployment + ClusterIP Service. NetworkPolicies are namespace-wide with pod-selector scoping."],
          ["Security", "Non-root UID 1000, readOnlyRootFilesystem, drop ALL capabilities, automountServiceAccountToken: false, default-deny NetworkPolicies"],
          ["Auth", "MCP_BEARER_TOKEN mounted from Opaque Secret; agents present bearer token on every MCP call"],
          ["Included server", "GitHub MCP adapter (pulls, issues, releases)"],
        ]} />
      </div>
    </div>
  );
}

function A2aSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Bot}>Agent-to-Agent (A2A)</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        KubeSynapse implements the <strong>Google A2A v1.0 protocol over JSON-RPC 2.0</strong>. Agents can
        call each other for specialized tasks using either synchronous (<code>message/send</code>) or streaming
        (<code>message/stream</code>) invocations. The operator generates per-agent NetworkPolicies to enforce
        allowed callers and targets at the network layer.
      </p>

      <div id="a2a-config-crd">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">CRD Configuration</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          A2A is configured on two CRDs — <code>AIAgent</code> for inbound callers and <code>AgentPolicy</code> for outbound targets.
        </p>
        <DocsTable headers={["CRD", "Field", "Type", "Purpose"]} rows={[
          ["AIAgent", "a2a.allowedCallers[].name", "string", "Agent name permitted to call this agent (inbound)"],
          ["AIAgent", "a2a.allowedCallers[].namespace", "string", "Namespace of the permitted caller agent"],
          ["AgentPolicy", "a2a.allowedTargets[].name", "string", "Target agent this policy permits the runtime to invoke (outbound)"],
          ["AgentPolicy", "a2a.allowedTargets[].namespace", "string", "Target agent namespace"],
          ["AgentPolicy", "a2a.maxTimeoutSeconds", "number", "Maximum HTTP timeout for outbound A2A calls (min: 1)"],
          ["AgentPolicy", "a2a.requireHitl", "boolean", "When true, A2A calls must pass through the HITL gate (default: false)"],
        ]} />
      </div>

      <div id="a2a-network">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">NetworkPolicies</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          The operator generates two NetworkPolicies per agent to enforce A2A boundaries at the network layer.
          The podSelector is <code>app=ai-agent</code> + <code>agent-name</code>; the namespaceSelector matches
          the agent's namespace by metadata name.
        </p>
        <DocsTable headers={["Policy", "Selects", "Allows"]} rows={[
          ["{agent}-a2a-egress", "All agent pods", "Outbound to each allowed target pod (by namespace label + agent-name selector)"],
          ["{agent}-a2a-ingress", "All agent pods", "Inbound from each allowed caller pod (by namespace label + agent-name selector)"],
        ]} />
      </div>

      <div id="a2a-runtime">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Runtime Injection</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Every agent invocation receives a collaboration system note with its available peers and
          delegation instructions. The operator injects these environment variables into every runtime pod
          (note: the A2A endpoints are the only routes served outside <code>/api/v1</code> — they are mounted
          at the gateway root):
        </p>
        <DocsTable headers={["Env Var", "Source", "Purpose"]} rows={[
          ["A2A_ALLOWED_CALLERS_JSON", "AIAgent.spec.a2a.allowedCallers", "Who can call this agent"],
          ["A2A_ALLOWED_TARGETS_JSON", "AgentPolicy.spec.a2a.allowedTargets", "Which peers this agent can delegate to"],
          ["A2A_REQUIRE_HITL", "AgentPolicy.spec.a2a.requireHitl", "Whether A2A calls require approval"],
          ["A2A_MAX_TIMEOUT_SECONDS", "AgentPolicy.spec.a2a.maxTimeoutSeconds", "Outbound call timeout"],
          ["API_GATEWAY_INTERNAL_URL", "Helm value", "Gateway URL for A2A HTTP calls"],
        ]} />
      </div>

      <div id="a2a-api">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">A2A API Endpoints</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/.well-known/agent-card.json?assistant_id={id}&namespace={ns}", "A2A capability card (skills, interfaces, auth schemes). <code>assistant_id</code> is a required query parameter; <code>namespace</code> is optional (defaults to the gateway's default namespace). Served at the gateway root, no <code>/a2a</code> prefix."],
          ["POST", "/a2a/{assistant_id}?namespace={ns}", "JSON-RPC 2.0 dispatcher — methods: message/send, message/stream, tasks/get"],
        ]} />
      </div>

      <div id="a2a-example">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">JSON-RPC Invocation Example</h3>
        <CodeBlock code={`# Synchronous A2A call via JSON-RPC 2.0
curl -X POST http://localhost:8080/a2a/doc-writer?namespace=default \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "jsonrpc": "2.0",
    "id": "req-001",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "messageId": "msg-1",
        "parts": [{"text": "Summarize the incident report"}]
      },
      "metadata": {
        "KubeSynapseInvoke": {
          "callerAgentName": "security-analyst",
          "callerAgentNamespace": "default"
        }
      }
    }
  }'

# Streaming A2A call (SSE)
curl -N -X POST http://localhost:8080/a2a/doc-writer?namespace=default \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"jsonrpc":"2.0","id":"req-002","method":"message/stream",...}'`} lang="bash" />
      </div>

      <div id="a2a-policy-example">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Policy Example</h3>
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AgentPolicy
metadata:
  name: a2a-policy
spec:
  a2a:
    allowedTargets:
      - name: doc-writer
        namespace: default
      - name: forensics
        namespace: default
    maxTimeoutSeconds: 60
    requireHitl: true`} lang="yaml" />
      </div>
        <Callout variant="tip" title="Related: A2A & Agent Policies">
          Agent-to-Agent communication is governed by both the <code>AIAgent</code> spec (<code>a2a.allowedCallers</code>)
          and <code>AgentPolicy</code> (<code>a2a.allowedTargets</code>, <code>a2a.maxTimeoutSeconds</code>,
          <code>a2a.requireHitl</code>). The operator generates per-agent NetworkPolicies to enforce A2A
          boundaries at the network layer. See <strong>Agent Policies → A2A Policy</strong> for details.
        </Callout>
      </div>
    );
  }

  function PoliciesSection() {
    return (
    <div className="space-y-8">
      <SectionHeading icon={ShieldCheck}>Agent Policies</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        An <code>AgentPolicy</code> is a namespaced CRD that attaches governance guardrails to agents
        via <code>policyRef</code>. Every field is enforced by the operator at runtime, and optional
        Gatekeeper constraints add admission-time protection for sealed policies and invalid policy
        references.
      </p>

      {/* Input Guardrails */}
      <div id="policy-input">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Input Guardrails</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Applied before the user prompt reaches the LLM.
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["inputGuardrails.blockPromptInjection", "boolean", "Block known prompt-injection patterns (jailbreak, role-override, token smuggling)"],
          ["inputGuardrails.blockedPatterns", "string[]", "Custom regex patterns to reject in user input"],
          ["inputGuardrails.maxInputTokens", "integer", "Hard limit on submitted token count per invocation"],
        ]} />
      </div>

      {/* Output Guardrails */}
      <div id="policy-output">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Output Guardrails</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Applied to the LLM response before it is returned to the caller.
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["outputGuardrails.maskPII", "boolean", "Automatically redact SSNs, credit card numbers, emails, and phone numbers. Enforced at runtime by the api-gateway (not at the CRD/admission layer)."],
          ["outputGuardrails.blockedOutputPatterns", "string[]", "Custom regex patterns to redact from LLM output"],
          ["outputGuardrails.maxOutputTokens", "integer", "Hard limit on token count in the LLM response"],
        ]} />
      </div>

      {/* Budget */}
      <div id="policy-budget">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Budget (Reserved for Future)</h3>
        <Callout variant="warning" title="Not yet enforced">
          <code>spec.budget</code> fields (<code>maxTokensPerHour</code>, <code>maxRequestsPerMinute</code>,
          <code>maxCostPerDayUSD</code>) are reserved for distributed budget enforcement. The CRD
          includes a CEL validation that <strong>rejects</strong> any policy containing these fields
          so they cannot silently advertise limits the runtime does not enforce.
        </Callout>
      </div>

      {/* Allowed Models */}
      <div id="policy-models">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Allowed Models</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["allowedModels", "string[]", "Whitelist of permitted LLM model IDs (e.g. gpt-4, claude-3-sonnet). Empty means all models are blocked."],
        ]} />
      </div>

      {/* Namespace Access */}
      <div id="policy-namespaces">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Cross-Namespace Access</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Controls which namespaces may reference this policy from their AIAgent resources.
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["allowedNamespaces.from", "Same | All | Selector", "Same (default): only the policy namespace. All: any namespace. Selector: namespaces matching a label selector."],
          ["allowedNamespaces.selector", "object", "Namespace label selector used when from=Selector"],
        ]} />
      </div>

      {/* MCP Access Control */}
      <div id="policy-mcp">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">MCP Server Access Control</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["allowedMcpServers", "string[]", "Whitelist of MCP server type labels the agent may call (e.g. ['github', 'filesystem']). Empty = no MCP access. Enforced by the gateway at invoke time; per-agent NetworkPolicy egress rules targeting <code>mcp.kubesynapse.ai/type</code> labels reinforce at the network layer."],
          ["mcpRequireHitl", "boolean", "When true (default), every MCP tool call must pass through the HITL gate and requires AgentApproval before execution."],
        ]} />
      </div>

      {/* Tool Policy */}
      <div id="policy-tools">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Tool Policy</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["toolPolicy.maxDelegationDepth", "integer", "Maximum delegation depth for agent-to-agent tool calls"],
          ["toolPolicy.allowedToolPrefixes", "string[]", "Whitelist of tool name prefixes (e.g. 'local.command.', 'filesystem.')"],
          ["toolPolicy.blockedToolNames", "string[]", "Explicitly blocked tools including MCP-qualified names like 'github/create_issue'"],
          ["toolPolicy.requireApprovalFor", "string[]", "Tool names that always require human approval before execution"],
          ["toolPolicy.adminToolCeiling", "object", "Per-tool ceiling applied by the operator via OPENCODE_ADMIN_PERMISSION_CEILING_JSON. Use values like allow, ask, or deny to cap runtime permissions even when the global preset is more permissive."],
        ]} />
        <Callout variant="info" title="Admission-time validation">
          When <code>gatekeeper.enabled=true</code>, the chart installs constraints that validate
          <code>adminToolCeiling</code> entries, require valid policy references, prevent deleting policies
          still referenced by live agents, and block changes to sealed policies.
        </Callout>
      </div>

      <div id="policy-seal">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Policy Seal</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["sealed", "boolean", "Marks the policy immutable. CRD default: <code>false</code>. The operator hashes the policy and injects <code>KUBESYNAPSE_POLICY_HASH</code> and <code>KUBESYNAPSE_POLICY_NAME</code> env vars into the agent pod for sealed-policy attestation. Gatekeeper blocks UPDATE and DELETE operations when sealing is enabled."],
        ]} />
      </div>

      {/* Memory Policy */}
      <div id="policy-memory">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Memory Policy</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Controls how durable memory is retrieved from PostgreSQL and injected into the agent context.
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["memoryPolicy.maxInjectedMemories", "integer", "Maximum number of promoted memory records injected per request"],
          ["memoryPolicy.maxInjectedChars", "integer", "Maximum total characters of injected memory context (prevents context-window blowout)"],
          ["memoryPolicy.allowedMemoryTypes", "string[]", "Optional allow-list of memory types eligible for retrieval (e.g. procedural, episodic)"],
          ["memoryPolicy.autoPromote", "boolean", "When true, the platform may auto-promote high-signal memories without a manual pin action. CRD default: <code>false</code>; the api-gateway normalizes this to <code>true</code> at the API boundary."],
        ]} />
      </div>

      {/* A2A Policy */}
      <div id="policy-a2a">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Agent-to-Agent (A2A) Policy</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Controls outbound peer agent invocations. Applied when the runtime calls other agents
          via the internal <code>/invoke</code> API.
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["a2a.allowedTargets", "object[]", "Explicit list of peer agents this policy permits. Each entry requires name and namespace."],
          ["a2a.maxTimeoutSeconds", "number", "Maximum HTTP timeout allowed for outbound A2A calls (min 1)"],
          ["a2a.requireHitl", "boolean", "When true, direct A2A calls must pass through the HITL gate even without an explicit require_approval flag"],
        ]} />
      </div>

      {/* Quick Example */}
      <div id="policy-example">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Minimal Example</h3>
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AgentPolicy
metadata:
  name: strict-policy
  namespace: default
spec:
  sealed: true
  inputGuardrails:
    blockPromptInjection: true
    maxInputTokens: 8192
  outputGuardrails:
    maskPII: true
    maxOutputTokens: 4096
  allowedModels:
    - gpt-4
    - claude-3-sonnet
  allowedMcpServers:
    - filesystem
  mcpRequireHitl: true
  toolPolicy:
    maxDelegationDepth: 3
    allowedToolPrefixes:
      - "local.command."
    blockedToolNames:
      - "github/delete_repo"
    adminToolCeiling:
      bash: deny
      external_directory: deny
      webfetch: ask
  memoryPolicy:
    maxInjectedMemories: 10
    maxInjectedChars: 8000
    autoPromote: false
  a2a:
    allowedTargets:
      - name: doc-writer
        namespace: default
    maxTimeoutSeconds: 30
    requireHitl: true`} lang="yaml" />
      </div>
    </div>
  );
}

function ObservabilitySection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Eye}>Observability</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        KubeSynapse exposes OpenTelemetry traces, Prometheus metrics, and structured JSON logs across
        all components. The Observability subsystem adds CRD-based monitoring of external targets
        through ConnectorPlugins.
      </p>

      <div id="obs-telemetry">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Built-in Telemetry</h3>
        <DocsTable headers={["Component", "Metrics", "Traces", "Logs"]} rows={[
          ["API Gateway", "/metrics (Prometheus)", "OpenTelemetry spans", "JSON structured"],
          ["Operator", "/metrics (built-in HTTP)", "OpenTelemetry spans", "JSON structured"],
          ["LiteLLM", "LLM usage, latency, errors", "Request traces", "Provider logs"],
          ["Agent Runtime", "Tool calls, token usage", "Per-request spans", "Worker logs"],
        ]} />
      </div>

      <div id="obs-crds">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Observation Subsystem CRDs</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Beyond built-in telemetry, KubeSynapse provides CRDs for observing infrastructure targets
          through connectors that collect Prometheus, Kubernetes API, SNMP, gNMI, and NATS metrics.
        </p>
        <DocsTable headers={["CRD", "Kind", "Purpose"]} rows={[
          ["ObservationTarget", "observationtargets", "Defines a monitoring target (connector, endpoint, scrape interval, credentials)"],
          ["ConnectorPlugin", "connectorplugins", "Defines a collection plugin (image, protocol, capabilities, health endpoint)"],
          ["ObservationPolicy", "observationpolicies", "Defines retention, alert rules, anomaly detection, and notifications"],
          ["ObservationReport", "observationreports", "Auto-generated status with health score, findings, and alert summaries"],
        ]} />
      </div>

      <div id="obs-target">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">ObservationTarget</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["targetType", "prometheus | kubernetes-api | snmp | gnmi | nats | custom", "What kind of data to collect"],
          ["connectorRef", "string (required)", "ConnectorPlugin CR that performs the collection"],
          ["endpoint", "string", "Target URL or DSN"],
          ["scrapeInterval", "string", "How often to scrape (default: 30s)"],
          ["policyRef", "string", "ObservationPolicy that governs this target"],
          ["selector", "object", "Label-based filter for what this target observes"],
          ["credentials.secretRef", "string", "K8s Secret with target credentials"],
          ["tlsConfig.insecureSkipVerify", "boolean", "Skip TLS verification (default: false)"],
        ]} />
      </div>

      <div id="obs-policy">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">ObservationPolicy</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["retention.days", "integer", "How long to keep observations (min: 1, max: 365, default: 30)"],
          ["retention.downsampling.after", "string", "When to start downsampling (default: 7d)"],
          ["alertRules[].name", "string (required)", "Alert rule identifier"],
          ["alertRules[].expr", "string (required)", "PromQL expression for the alert condition"],
          ["alertRules[].severity", "info | warning | critical", "Alert severity (default: warning)"],
          ["anomalyDetection.enabled", "boolean", "Enable ML-based anomaly detection (default: false)"],
          ["anomalyDetection.algorithm", "isolation-forest | prophet | ensemble", "Detection algorithm (default: ensemble)"],
          ["anomalyDetection.sensitivity", "number", "Detection sensitivity 0.0–1.0 (default: 0.7)"],
          ["notifications.webhookUrl", "string", "Webhook URL for alert notifications"],
          ["notifications.natsSubject", "string", "NATS subject for alert publishing (default: aiops.alerts)"],
        ]} />
      </div>

      <div id="obs-report">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">ObservationReport</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Reports are auto-generated by the observation controller. Each <code>ObservationTarget</code> reconciliation
          creates or patches a corresponding <code>ObservationReport</code> with an OwnerReference.
        </p>
        <DocsTable headers={["Status Field", "Type", "Description"]} rows={[
          ["phase", "Pending | Evaluating | Complete | Error", "Current evaluation state"],
          ["healthScore", "integer", "0–100 composite health score"],
          ["findingsCount", "integer", "Number of findings in this report"],
          ["findings[].severity", "info | warning | critical", "Per-finding severity"],
          ["findings[].metric", "string", "Metric name the finding relates to"],
          ["findings[].value", "number", "Observed value that triggered the finding"],
          ["findings[].expected", "number", "Expected/reference value"],
        ]} />
      </div>
    </div>
  );
}

function CliSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Terminal}>CLI Reference (agentctl)</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        <code>agentctl</code> is the official CLI for managing KubeSynapse agents, workflows, and policies from the terminal.
        Install with <code>pip install -e ./cli</code> and enable tab-completion for your shell:
      </p>
      <CodeBlock
        code={`# bash (~/.bashrc)
eval "$(agentctl completion bash)"

# zsh (~/.zshrc)
eval "$(agentctl completion zsh)"

# fish
agentctl completion fish > ~/.config/fish/completions/agentctl.fish

# PowerShell ($PROFILE)
agentctl completion pwsh | Out-String | Invoke-Expression`}
        lang="bash"
      />
      <p className="mt-2 text-sm text-[oklch(0.60_0.01_264)]">
        After installing completion, tab-completion works for all commands, subcommands, and options.
      </p>

      <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Agent Commands</h3>
      <CodeBlock
        code={`agentctl agents list                     # List all agents
agentctl agents show my-agent              # Get agent details
agentctl agents create -f agent.yaml       # Create from YAML/JSON
agentctl agents update my-agent -f a.yaml  # Update from file
agentctl agents delete my-agent -y         # Delete an agent
agentctl agents discover my-agent          # Show A2A peer discovery
agentctl agents invoke my-agent "Prompt"   # Sync invoke
agentctl agents invoke my-agent --stream "Prompt"  # SSE streaming invoke
agentctl agents logs my-agent --tail 100   # Get pod logs
agentctl agents logs my-agent -f           # Stream logs (follow)
agentctl agents live-events my-agent       # SSE real-time agent events`}
        lang="bash"
      />

      <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Workflow Commands</h3>
      <CodeBlock
        code={`agentctl workflows list                # List workflows
agentctl workflows show my-wf              # Workflow details
agentctl workflows create -f wf.yaml       # Create from YAML/JSON
agentctl workflows update my-wf -f wf.yaml # Update from file
agentctl workflows delete my-wf -y         # Delete a workflow
agentctl workflows trigger my-wf           # Trigger execution
agentctl workflows status my-wf            # Show run status & step states
agentctl workflows cancel my-wf -y         # Cancel running workflow
agentctl workflows logs my-wf --tail 200   # Get workflow logs`}
        lang="bash"
      />

      <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Approvals, Policies & Governance</h3>
      <CodeBlock
        code={`agentctl runs approvals                # List pending approvals
agentctl runs approve <name>               # Approve a request
agentctl runs deny <name>                  # Deny a request
agentctl runs policies                     # List policies
agentctl runs policy-show my-policy        # Show policy details
agentctl runs policy-delete my-policy -y   # Delete a policy
agentctl runs apply -f policy.yaml         # Create/update a policy`}
        lang="bash"
      />

      <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Observability & Chat</h3>
      <CodeBlock
        code={`agentctl observatory metrics --window 24h  # Usage & cost metrics
agentctl observatory traces --limit 20     # Execution traces
agentctl observatory trace <trace-id>      # Full trace detail
agentctl observatory alerts --all          # Anomaly alerts
agentctl observatory signals --limit 10    # Runtime signal events
agentctl observatory export -o traces.json # Export traces to file
agentctl observatory health                # Platform health check

agentctl chat send my-agent "Hello"        # Send a message
agentctl chat send my-agent --stream "..."  # Stream response
agentctl chat threads --agent my-agent     # List chat sessions
agentctl chat history <thread-id>          # Show message history
agentctl chat interactive my-agent         # REPL-style session`}
        lang="bash"
      />

      <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Auth, Admin & Management</h3>
      <CodeBlock
        code={`agentctl auth login -u admin -p "pass"   # Login
agentctl auth logout                        # Revoke session
agentctl auth register                      # Self-register
agentctl auth me                            # Current principal
agentctl auth config                        # Auth configuration

agentctl admin users                        # List users (admin only)
agentctl admin user-create -u dev -p "..."  # Create user
agentctl admin user-update <id> --role op   # Update user
agentctl admin user-delete <id> -y          # Delete user

agentctl profile list                       # List profiles
agentctl profile create demo -g http://...  # Create profile
agentctl profile use demo                   # Switch profile
agentctl profile login demo -u admin -p ... # Login into profile

agentctl credentials git-show my-agent      # Show git credentials
agentctl credentials git-set my-agent -t ... # Set git credentials
agentctl credentials github-show my-agent   # Show GitHub credentials

agentctl skills list                        # Available skills
agentctl skills tools --agent my-agent      # Tools for an agent
agentctl providers list                     # LLM provider registry
agentctl webhooks list                      # Webhook receivers
agentctl webhooks dispatch my-webhook       # Invoke a webhook
agentctl webhooks triggers                  # List workflow triggers
agentctl webhooks trigger-show <name>       # Show trigger detail`}
        lang="bash"
      />

      <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Top-Level Shortcuts</h3>
      <CodeBlock
        code={`agentctl health                # API gateway health check
agentctl invoke my-agent "Prompt"  # Shortcut for agents invoke
agentctl logs my-agent --tail 100 # Shortcut for agents logs
agentctl apply -f resource.yaml   # Auto-detect kind, create/update`}
        lang="bash"
      />

      <Callout variant="tip" title="Shell completion">
        Tab-completion is available for bash, zsh, fish, and PowerShell. Run{" "}
        <code>agentctl completion &lt;shell&gt;</code> to generate the install script. Once installed,
        <code>agentctl &lt;TAB&gt;</code> shows all commands, <code>agentctl agents &lt;TAB&gt;</code> shows subcommands,
        and <code>agentctl --&lt;TAB&gt;</code> shows global options.
      </Callout>
    </div>
  );
}

function ApiReferenceSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Wrench}>API Reference</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        All REST endpoints are available under <code>/api/v1/</code>. OpenAPI docs at <code>/api/v1/docs</code>.
      </p>

      <div id="api-agents">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Agents</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/agents", "List AIAgents in namespace"],
          ["POST", "/api/v1/agents", "Create AIAgent CRD"],
          ["GET", "/api/v1/agents/{name}", "Get agent details (model, MCP connections, skills)"],
          ["PATCH", "/api/v1/agents/{name}", "Update agent spec"],
          ["DELETE", "/api/v1/agents/{name}", "Delete agent CRD"],
          ["POST", "/api/v1/agents/{name}/clone", "Clone agent into a new CRD"],
          ["POST", "/api/v1/agents/{name}/invoke", "Sync invoke the agent runtime"],
          ["POST", "/api/v1/agents/{name}/invoke/stream", "SSE streaming invoke"],
          ["GET", "/api/v1/agents/{name}/todo", "Fetch agent todo list (ETag conditional polling)"],
          ["GET", "/api/v1/agents/{name}/diff", "Get unified diff of file changes"],
          ["GET", "/api/v1/agents/{name}/question", "List pending question requests"],
          ["POST", "/api/v1/agents/{name}/question/{id}/reply", "Reply to a pending question"],
          ["GET", "/api/v1/agents/{name}/logs", "Get pod logs (tail)"],
          ["GET", "/api/v1/agents/{name}/logs/stream", "SSE stream pod logs (follow)"],
          ["GET", "/api/v1/agents/{name}/artifacts/list", "List workspace files"],
          ["GET", "/api/v1/agents/{name}/artifacts/download", "Download a single artifact"],
          ["GET", "/api/v1/agents/{name}/artifacts/zip", "Download full workspace as ZIP"],
          ["GET", "/api/v1/agents/{name}/memory", "List persisted memory records"],
          ["POST", "/api/v1/agents/{name}/git-credentials", "Set git credentials"],
          ["POST", "/api/v1/agents/{name}/github-credentials", "Set GitHub MCP credentials"],
        ]} />
      </div>

      <div id="api-workflows">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Workflows</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/workflows", "List workflows"],
          ["POST", "/api/v1/workflows", "Create workflow CRD"],
          ["GET", "/api/v1/workflows/{name}", "Get workflow detail"],
          ["PATCH", "/api/v1/workflows/{name}", "Update workflow spec"],
          ["DELETE", "/api/v1/workflows/{name}", "Delete workflow"],
          ["POST", "/api/v1/workflows/{name}/trigger", "Trigger a workflow run"],
          ["POST", "/api/v1/workflows/{name}/retry-failed", "Retry only failed steps"],
          ["POST", "/api/v1/workflows/{name}/cancel", "Cancel a running/queued workflow"],
          ["GET", "/api/v1/workflows/{name}/runs", "List recent run history"],
          ["GET", "/api/v1/workflows/{name}/runs/{id}/trace", "Get full trace for a run"],
          ["GET", "/api/v1/workflows/{name}/status/stream", "SSE stream workflow status updates"],
          ["GET", "/api/v1/workflows/{name}/activities/stream", "SSE stream real-time journal events"],
          ["GET", "/api/v1/workflows/{name}/logs", "Get worker job logs"],
          ["GET", "/api/v1/workflows/{name}/next-action", "Suggest next action from state"],
        ]} />
      </div>

      <div id="api-traces">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Traces & Run History</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["POST", "/api/v1/traces/batch", "Ingest batch of trace events"],
          ["GET", "/api/v1/traces/executions", "List workflow executions"],
          ["GET", "/api/v1/traces/executions/{id}", "Full execution detail with LLM/tool calls"],
          ["GET", "/api/v1/traces/executions/{id}/events", "Raw trace events from durable storage"],
          ["GET", "/api/v1/traces/steps/{id}", "Step detail with LLM and tool records"],
          ["POST", "/api/v1/traces/executions/{id}/export/json", "Export execution as JSON"],
          ["GET", "/api/v1/traces/executions/{id}/export/html", "Export as self-contained HTML report"],
          ["GET", "/api/v1/traces/{id}/timeline", "Semantic event timeline for a run"],
          ["GET", "/api/v1/traces/runtime-events", "Query runtime events across runs"],
          ["POST", "/api/v1/traces/runtime-events", "Ingest runtime events for Run Intelligence"],
        ]} />
      </div>

      <div id="api-chat">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Chat Sessions & Memory</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/chat-sessions?agent_name=X", "List sessions for an agent"],
          ["POST", "/api/v1/chat-sessions", "Create a chat session"],
          ["GET", "/api/v1/chat-sessions/{id}/messages", "Get all messages for a session"],
          ["PUT", "/api/v1/chat-sessions/{id}/messages", "Replace stored messages for a session"],
          ["PATCH", "/api/v1/chat-sessions/{id}", "Update session title"],
          ["DELETE", "/api/v1/chat-sessions/{id}", "Delete session and all messages"],
          ["PATCH", "/api/v1/memory/{record_id}", "Update a memory record (promote, topic, content)"],
          ["DELETE", "/api/v1/memory/{record_id}", "Delete a memory record"],
          ["GET", "/api/v1/notifications/stream", "SSE stream agent/workflow status change events"],
        ]} />
      </div>

      <div id="api-auth">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Auth</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/auth/config", "Public auth configuration"],
          ["POST", "/api/v1/auth/login", "Login (local/LDAP)"],
          ["POST", "/api/v1/auth/refresh", "Rotate refresh token"],
          ["POST", "/api/v1/auth/logout", "Revoke session"],
          ["GET", "/api/v1/auth/me", "Current user principal"],
          ["GET", "/api/v1/auth/oidc/start/{provider}", "Start OIDC login flow (PKCE)"],
          ["GET", "/api/v1/auth/oidc/callback/{provider}", "OIDC callback"],
          ["GET", "/api/v1/auth/saml/start/{provider}", "Start SAML login flow"],
          ["GET", "/api/v1/auth/saml/metadata/{provider}", "SAML SP metadata XML"],
        ]} />
      </div>

      <div id="api-providers">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">LLM Providers</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/providers", "List provider registry"],
          ["PUT", "/api/v1/providers/{id}/credentials", "Store provider API key"],
          ["GET", "/api/v1/providers/{id}/models", "Get model entries for a provider"],
          ["POST", "/api/v1/providers/custom", "Create custom OpenAI-compatible provider"],
          ["GET", "/api/v1/llm/providers", "Unified provider view with key status"],
          ["GET", "/api/v1/llm/providers/{provider}/suggestions", "Live model suggestions"],
          ["PUT", "/api/v1/llm/keys", "Update LLM API key values"],
          ["POST", "/api/v1/copilot/auth/device", "Initiate GitHub Copilot device flow"],
          ["POST", "/api/v1/copilot/auth/poll", "Poll for Copilot device flow completion"],
        ]} />
      </div>

      <div id="api-webhooks">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Webhooks & Triggers</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/webhooks", "List webhook receivers"],
          ["POST", "/api/v1/webhooks", "Create webhook receiver"],
          ["PUT", "/api/v1/webhooks/{name}", "Update webhook receiver"],
          ["DELETE", "/api/v1/webhooks/{name}", "Delete webhook receiver"],
          ["POST", "/api/v1/webhooks/{name}/invoke?namespace={namespace}", "Public webhook invocation (HMAC-signed)"],
          ["POST", "/api/v1/webhooks/{name}/generate-secret", "Generate new HMAC secret for webhook"],
          ["GET", "/api/v1/workflow-triggers", "List workflow triggers"],
          ["POST", "/api/v1/workflow-triggers", "Create workflow trigger"],
          ["PUT", "/api/v1/workflow-triggers/{name}", "Update workflow trigger"],
          ["DELETE", "/api/v1/workflow-triggers/{name}", "Delete workflow trigger"],
          ["GET", "/api/v1/webhooks/dispatched/pending", "List pending trigger executions awaiting claim"],
          ["POST", "/api/v1/webhooks/dispatched/{execution_id}/claim", "Atomically claim a pending execution (compare-and-set to queued)"],
          ["PATCH", "/api/v1/webhooks/dispatched/{execution_id}/status", "Update execution status and lineage metadata"],
        ]} />
      </div>

      <div id="api-mcp">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">MCP & Catalog</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/mcp/registry", "Full MCP server registry (filterable)"],
          ["GET", "/api/v1/mcp/profiles", "Curated MCP profiles with resolved statuses"],
          ["GET", "/api/v1/mcp/categories", "Categories with counts"],
          ["GET", "/api/v1/mcp/connections", "List saved MCP connections"],
          ["POST", "/api/v1/mcp/connections", "Create MCP connection"],
          ["POST", "/api/v1/mcp/connections/{id}/validate", "Validate connection"],
          ["POST", "/api/v1/mcp/connections/{id}/oauth/start", "Start OAuth2 flow for connection"],
        ]} />
      </div>

      <div id="api-incidents">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Incidents</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/incidents", "List incidents"],
          ["POST", "/api/v1/incidents", "Create incident"],
          ["PUT", "/api/v1/incidents/{name}", "Upsert incident (idempotent)"],
          ["PATCH", "/api/v1/incidents/{name}", "Update incident status (acknowledge, resolve, close)"],
          ["GET", "/api/v1/incidents/{name}", "Get incident details"],
          ["POST", "/api/v1/incidents/{name}/escalate", "Escalate incident"],
          ["GET", "/api/v1/incidents/{name}/timeline", "Get incident timeline"],
          ["POST", "/api/v1/webhooks/alertmanager", "Alertmanager webhook receiver"],
        ]} />
      </div>

      <div id="api-intelligence">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Intelligence & Collectors</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/intelligence/collectors", "List collectors"],
          ["POST", "/api/v1/intelligence/collectors", "Register collector"],
          ["DELETE", "/api/v1/intelligence/collectors/{id}", "Unregister collector"],
          ["POST", "/api/v1/intelligence/collect", "Trigger collection on all collectors"],
          ["GET", "/api/v1/intelligence/tasks", "List collection tasks"],
          ["GET", "/api/v1/intelligence/tasks/{id}", "Get task details"],
          ["DELETE", "/api/v1/intelligence/tasks/{id}", "Delete task"],
          ["POST", "/api/v1/intelligence/schedules", "Create schedule"],
          ["PUT", "/api/v1/intelligence/schedules/{id}", "Update schedule"],
          ["DELETE", "/api/v1/intelligence/schedules/{id}", "Delete schedule"],
          ["POST", "/api/v1/intelligence/alerts", "Create alert rule"],
          ["PUT", "/api/v1/intelligence/alerts/{id}", "Update alert rule"],
          ["DELETE", "/api/v1/intelligence/alerts/{id}", "Delete alert rule"],
          ["POST", "/api/v1/intelligence/prompt-context", "Fetch intelligence output as prompt context"],
        ]} />
      </div>

      <div id="api-skills">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Skills Catalog</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/skills/catalog", "List available skills"],
          ["GET", "/api/v1/skills/catalog/{id}", "Get skill details"],
          ["POST", "/api/v1/skills/catalog/refresh", "Refresh skills catalog"],
          ["GET", "/api/v1/skills/tools", "List available tools"],
        ]} />
      </div>

      <div id="api-admin">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Admin & System</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/health", "Root health check (no auth)"],
          ["GET", "/api/v1/health", "Health check (auth mode, service status)"],
          ["GET", "/api/v1/ready", "Readiness check (DB connectivity)"],
          ["GET", "/api/v1/system/health", "Comprehensive system health (DB, K8s, CRD counts, NATS, Qdrant)"],
          ["GET", "/api/v1/namespaces", "List accessible namespaces"],
          ["GET", "/api/v1/policies", "List AgentPolicies"],
          ["POST", "/api/v1/policies", "Create AgentPolicy"],
          ["PATCH", "/api/v1/policies/{name}", "Update AgentPolicy"],
          ["DELETE", "/api/v1/policies/{name}", "Delete AgentPolicy"],
          ["GET", "/api/v1/approvals/{name}", "Get AgentApproval"],
          ["PATCH", "/api/v1/approvals/{name}", "Record approve/deny decision"],
          ["GET", "/api/v1/export/bundle?namespace=default", "Export agents, workflows, and policies as YAML bundle"],
          ["POST", "/api/v1/import/bundle", "Import YAML bundle"],
        ]} />
      </div>
    </div>
  );
}

function LlmProvidersSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Zap}>LLM Providers</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        The Settings workspace is provider-centric. The left rail comes from the gateway provider registry,
        and live model suggestions come from provider-specific gateway integrations once credentials are configured.
      </p>
      <DocsTable headers={["Provider", "Credential", "Live Suggestions", "Notes"]} rows={[
        ["OpenRouter", "OPENROUTER_API_KEY", "Yes", "Queries the live OpenRouter catalog"],
        ["OpenCode Zen", "OPENCODE_API_KEY", "Yes", "Uses the OpenCode provider suggestions endpoint"],
        ["OpenCode Go", "OPENCODE_GO_API_KEY", "Yes", "Uses the OpenCode Go provider suggestions endpoint"],
        ["GitHub Copilot", "Stored device-flow token", "Yes", "Suggestions appear after sign-in succeeds"],
        ["Static LiteLLM providers", "Provider-specific secret", "Usually no", "Add models manually when the upstream catalog is not queried live"],
      ]} />
      <Callout variant="info" title="Why suggestions may be empty">
        If the provider has no configured credential yet, the gateway returns no live suggestions. Check the
        provider detail pane first before assuming the frontend is broken.
      </Callout>
    </div>
  );
}

function ExportImportSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Globe}>Export & Import</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        Export agent configurations, policies, and workflows as portable YAML bundles for migration between
        clusters. You can use the <code>agentctl</code> CLI or the REST API directly.
      </p>

      <div id="ei-cli">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Export / Import</h3>
        <CodeBlock code={`# Export via REST API
curl -X GET "http://localhost:8080/api/v1/export/bundle?namespace=default" \\
  -H "Authorization: Bearer $TOKEN" > bundle.yaml

# Import via REST API
curl -X POST http://localhost:8080/api/v1/import/bundle \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/x-yaml" \\
  --data-binary @bundle.yaml

# Or apply the exported YAML directly via kubectl
kubectl apply -f bundle.yaml`} lang="bash" />
      </div>

      <div id="ei-api">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">REST API Bundle Endpoints</h3>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/export/bundle?namespace=default", "Exports agents, workflows, and policies as a multi-doc YAML bundle"],
          ["POST", "/api/v1/import/bundle", "Imports a multi-doc YAML bundle, creating or updating resources"],
        ]} />
        <CodeBlock code={`# Export via REST API
curl -X GET "http://localhost:8080/api/v1/export/bundle?namespace=default" \\
  -H "Authorization: Bearer $TOKEN" > bundle.yaml

# Import via REST API
curl -X POST http://localhost:8080/api/v1/import/bundle \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/x-yaml" \\
  --data-binary @bundle.yaml`} lang="bash" />
      </div>
    </div>
  );
}

function TroubleshootingSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Bug}>Troubleshooting</SectionHeading>

      <div id="ts-general">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">General Issues</h3>
        <DocsTable headers={["Issue", "Symptom", "Resolution"]} rows={[
          ["Agent stuck in Pending", "Pod never starts", "Check resource quotas and node capacity"],
          ["Provider suggestions are empty", "Settings shows no models", "Configure the provider credential first, then reload suggestions"],
          ["Durable memory is not recalled", "Saved history exists but the agent forgets", "Verify memoryPolicy is enabled, then inspect gateway memory_records for the right user, namespace, and agent"],
          ["Local fix does not show up", "Kind still serves old code after loading :dev", "Run kubectl rollout restart on the touched deployment when the image tag did not change"],
          ["MCP tool unavailable", "Tool call timeouts", "Check sidecar logs or the remote MCP endpoint auth configuration"],
          ["Webhook dispatch stuck in pending", "Execution never transitions to queued", "Check operator logs for claim errors. Verify NATS connection (kubectl logs -l app=operator -n kubesynapse). The timer fallback reclaims pending records every 30s."],
          ["Duplicate webhook events not caught", "Same event triggers twice", "Verify event_id is set in the incoming payload. Dedup uses (namespace, trigger_name, event_id). If the sender does not set event_id, the gateway generates one per request."],
          ["Claim conflict 409 on webhook", "Second operator replica logs 409", "Expected — the first operator to claim wins. The second skips dispatch. This is normal in multi-replica deployments."],
          ["Webhook HMAC validation fails", "Invoke returns 401", "Verify the secret key in the referenced K8s Secret matches what the caller uses. Check that the X-kubesynapse-Timestamp is within 5 minutes of the server clock."],
        ]} />
      </div>

      <div id="ts-workflows">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Workflow Issues</h3>
        <DocsTable headers={["Issue", "Symptom", "Resolution"]} rows={[
          ["Workflow never completes", "Step stuck in Running", "Verify approval was submitted via AgentApproval CR. Check worker pod logs for the step."],
          ["Step keeps failing and retrying", "execution.maxAttempts exhausted", "Inspect the step output artifact for error messages. Check verification prompt produces valid PASS/FAIL responses."],
          ["Loop step stalled", "Circuit breaker opened", "Check circuitBreaker.noProgressThreshold — increase it or the cooldownMinutes. Verify plan items are being marked complete."],
          ["Conditional branch not taken", "Expected branch skipped", "Verify the conditionExpr syntax and that the referenced step output path exists. Use <code>agentctl workflows logs &lt;workflow-name&gt;</code> to trace evaluation."],
          ["Wave parallelism not working", "Steps run sequentially despite no dependsOn", "Check AgentTenant.resourceQuota.maxParallelSteps (default: 4) and MAX_PARALLEL_STEPS env on the operator."],
          ["Verification fails repeatedly", "verifyRetries exhausted", "Simplify the verification prompt to produce unambiguous PASS/FAIL. Check the step output format."],
        ]} />
      </div>

      <div id="ts-a2a">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">A2A Issues</h3>
        <DocsTable headers={["Issue", "Symptom", "Resolution"]} rows={[
          ["A2A call returns 403", "Caller not authorized", "Verify the caller agent name+namespace is listed in AIAgent.spec.a2a.allowedCallers on the target. Check NetworkPolicies."],
          ["A2A call times out", "No response from target", "Increase AgentPolicy.spec.a2a.maxTimeoutSeconds. Verify API_GATEWAY_INTERNAL_URL is reachable from the caller pod."],
          ["A2A task stuck in TASK_STATE_AUTH_REQUIRED", "HITL gate blocked", "Check AgentPolicy.spec.a2a.requireHitl. If true, an AgentApproval CR must be approved before the task proceeds."],
        ]} />
      </div>

      <div id="ts-approval">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Approval Issues</h3>
        <DocsTable headers={["Issue", "Symptom", "Resolution"]} rows={[
          ["Approval pending forever", "Step status is waiting-approval", "Create a PATCH to /api/v1/approvals/{name} with decision: 'approved'. The approval controller watches for this."],
          ["Denied step stops workflow", "Workflow shows failed", "This is expected behavior. Copy the step output, fix the issue, and use retry-failed to restart from the failed step."],
        ]} />
      </div>

      <div id="ts-backup">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Backup & Restore</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          KubeSynapse includes a built-in PostgreSQL backup CronJob (disabled by default).
          Enable it in <code>values.yaml</code> with <code>backup.enabled: true</code>.
        </p>
        <DocsTable headers={["Operation", "Command"]} rows={[
          ["List backups", "kubectl get cronjob -n kubesynapse kubesynapse-postgresql-backup\nkubectl get jobs -n kubesynapse -l app=postgresql-backup"],
          ["Find backup file", "kubectl exec -n kubesynapse <backup-pod> -- ls /backup/"],
          ["Download backup", "kubectl cp kubesynapse/<pod>:/backup/<file>.sql.gz ./backup.sql.gz"],
          ["Decompress", "gunzip backup.sql.gz"],
          ["Restore", "kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- psql -U kubesynapse -d kubesynapse < backup.sql"],
          ["Verify restore", "kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- psql -U kubesynapse -c 'SELECT count(*) FROM users;'"],
        ]} />
      </div>

      <Callout variant="troubleshoot" title="Debug Commands">
        <div className="space-y-2">
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl describe aiagent &lt;name&gt; -n &lt;ns&gt;
          </code>
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl logs -l app=operator -n kubesynapse
          </code>
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl logs -l app=agent-runtime,agent-name=&lt;name&gt; -n &lt;ns&gt; --tail=100
          </code>
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl describe agentworkflow &lt;name&gt; -n &lt;ns&gt;
          </code>
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl exec -n kubesynapse kubesynapse-postgresql-0 -- psql -U kubesynapse -c "SELECT namespace, agent_name, topic, promoted, username FROM memory_records ORDER BY id DESC LIMIT 10;"
          </code>
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl rollout restart deploy/kubesynapse-api-gateway -n kubesynapse
          </code>
        </div>
      </Callout>
    </div>
  );
}

function WebhooksSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Radio}>Webhooks & Triggers</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        KubeSynapse can react to external events through webhook receivers and workflow triggers.
        External systems POST signed payloads; the gateway validates HMAC signatures, rate limits,
        and IP allowlists before creating a trigger execution record. The operator then claims the
        record atomically and dispatches to the target workflow or agent.
      </p>

      <div id="wh-receiver">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">WebhookReceiver</h3>
        <DocsTable headers={["Field", "Type", "Default", "Description"]} rows={[
          ["secretRef", "string (required)", "—", "K8s Secret reference. Two formats: <code>namespace/name#key</code> (reads the key from a Secret in that namespace) or <code>NAME#KEY</code> (falls back to reading the upper-cased token from an environment variable)"],
          ["additionalSecrets", "object (key-id → string)", "{}", "Map of key-id → <code>namespace/name#key</code> references for zero-downtime HMAC key rotation"],
          ["provider", "generic | github | slack | stripe | pagerduty | grafana", "generic", "Provider adapter — auto-selects header and signature algorithm"],
          ["apiKeyEnabled", "boolean", "false", "Allow <code>X-API-Key</code> header authentication alongside HMAC"],
          ["ipAllowlist", "string[]", "[] (allow all)", "CIDR allowlist restricting which IPs can invoke this webhook"],
          ["rateLimit", "integer", "60", "Requests per minute (min: 1). Per-receiver limit, separate from the global invoke rate limit."],
          ["maxConcurrent", "integer", "0 (unlimited)", "Maximum concurrent invocations (min: 0)"],
          ["maxPayloadBytes", "integer", "1048576 (1 MiB)", "Maximum allowed payload size in bytes (min: 1, max: 16 MiB)"],
          ["responseTimeoutSeconds", "integer", "30", "Webhook response timeout in seconds (min: 1, max: 300)"],
          ["payloadSchema", "object (JSON Schema)", "{}", "Optional JSON Schema validated against the inbound payload before HMAC check"],
          ["enabled", "boolean", "true", "Whether the webhook receiver accepts invocations"],
        ]} />
        <Callout variant="info" title="Public invoke endpoint">
          External systems call <code>POST /api/v1/webhooks/{'{'}name{'}'}/invoke?namespace=default</code> with HMAC-SHA256
          signatures in the <code>X-kubesynapse-Signature</code> header and a unix timestamp in
          <code>X-kubesynapse-Timestamp</code>. The timestamp must be within 5 minutes of the server clock.
        </Callout>
      </div>

      <div id="wh-trigger">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">WorkflowTrigger</h3>
        <p className="mb-3 text-sm text-[oklch(0.80_0.01_264)]">
          A trigger requires exactly one of <code>workflowRef</code> (run a multi-step workflow) or
          <code>agentRef</code> (invoke a single agent directly).
        </p>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["sourceRef", "string (required)", "Name of the source resource (WebhookReceiver or AgentEvent)"],
          ["sourceKind", "WebhookReceiver | AgentEvent", "Kind of source resource"],
          ["eventFilter", "object", "JSON filter applied to the event payload before triggering"],
          ["workflowRef.name / .namespace", "string (mutually exclusive with agentRef)", "AgentWorkflow to execute"],
          ["agentRef.name / .namespace", "string (mutually exclusive with workflowRef)", "AIAgent to invoke directly"],
          ["payloadMapping", "object", "Map webhook payload fields to workflow input or step prompts"],
          ["maxRetries", "integer", "Retry count on trigger failure (min: 0, default: 0)"],
          ["backoffSeconds", "integer", "Delay between retries (min: 0, default: 60)"],
          ["notifications_on_success", "string[]", "Notification channels (e.g. <code>slack:#oncall</code>) fired when the trigger succeeds"],
          ["notifications_on_failure", "string[]", "Notification channels fired when the trigger fails (after all retries)"],
          ["enabled", "boolean", "Whether the trigger is active (default: true)"],
        ]} />
      </div>

      <div id="wh-execution-model">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Execution Model</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          When the gateway receives a valid webhook invocation and a matching WorkflowTrigger exists, it creates a
          <code>trigger_executions</code> record in <code>pending</code> state and publishes a NATS message.
          The operator claims the record atomically before dispatching, ensuring each execution is handled exactly once
          even when multiple operator replicas compete.
        </p>
        <DocsTable headers={["Aspect", "Detail"]} rows={[
          ["State machine", "pending → queued → processing → completed | failed | dead_letter"],
          ["Claim mechanism", "Atomic compare-and-set: only <code>pending</code> records can be claimed as <code>queued</code>. A second operator claiming the same record gets HTTP 409."],
          ["Dispatch paths", "NATS (primary, sub-5s latency) or timer-based reconciliation fallback (every 30s)"],
          ["Dedup", "Duplicate events with matching <code>(namespace, trigger_name, event_id)</code> return the existing record instead of creating a duplicate. The first claim wins."],
          ["Lineage metadata", "workflow_run_id, workflow_generation, job_name, session_id, operator_instance, dispatch_path — persisted on every status update"],
        ]} />
        <Callout variant="info" title="Claim-first dispatch">
          Both the NATS handler and the timer reconciliation path attempt to claim the execution before dispatching.
          This ensures idempotency — the first operator wins, and subsequent attempts skip the already-claimed record.
        </Callout>
      </div>

      <div id="wh-example">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Example</h3>
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: WebhookReceiver
metadata:
  name: github-webhook
  namespace: default
spec:
  # secretRef supports two formats:
  #   1. namespace/name#key  → reads from a K8s Secret (recommended)
  #   2. NAME#KEY            → falls back to env var (upper-cased, dashes → underscores)
  secretRef: default/github-webhook-secret#hmac-key
  provider: github
  apiKeyEnabled: false
  ipAllowlist:
    - 140.82.112.0/20
  rateLimit: 120
  maxPayloadBytes: 4194304
  responseTimeoutSeconds: 30
---
apiVersion: kubesynapse.ai/v1alpha1
kind: WorkflowTrigger
metadata:
  name: pr-review-trigger
  namespace: default
spec:
  sourceRef: github-webhook
  sourceKind: WebhookReceiver
  eventFilter:
    event: pull_request
    action: opened
  workflowRef:
    name: code-review-pipeline
    namespace: default
  payloadMapping:
    input: 'Review PR #{{number}}: {{title}}'
    pr_number: "{{number}}"
  notifications_on_success:
    - slack:#code-review
  notifications_on_failure:
    - slack:#oncall`} lang="yaml" />
      </div>
    </div>
  );
}

function TracesSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Clock}>Traces & Run History</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        Every agent invocation and workflow step produces trace events — LLM calls, tool executions,
        A2A delegations — stored in the durable trace store. The traces API provides full visibility
        into what happened, when, and how long it took.
      </p>

      <div id="traces-overview">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Trace Lifecycle</h3>
        <DocsTable headers={["Stage", "Description"]} rows={[
          ["Emission", "Worker jobs emit execution trace batches to POST /api/v1/traces/batch during execution, while runtimes and workers also send semantic runtime events for Run Intelligence"],
          ["Indexing", "Events are indexed by execution_id, step_id, and event_type for querying; execution detail includes full tool and LLM records"],
          ["Runtime events", "A separate runtime-events store indexes operational events (errors, warnings, metrics) for the Run Intelligence layer"],
          ["Export", "Full executions can be exported as JSON or self-contained HTML reports"],
        ]} />
      </div>

      <div id="traces-observatory-ui">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Execution Observatory UI</h3>
        <DocsTable headers={["Surface", "Behavior"]} rows={[
          ["Overview", "Run metrics, waterfall timing, cost, token totals, and signal warnings, plus run-level insight charts: Recent Run Trend (duration sparkline across the workflow's last runs, color-toned by phase), Step Contribution (share bars showing which steps dominate total runtime), Step Variability (min/median/max range per step with a current-run marker), Tool Mix (time-weighted MCP tool usage with failure counts, weighted by per-tool duration_ms from OpenCode's state.time), Model Efficiency (token-vs-latency scatter, bubble by cost), and Quality Flags (warning/error events, tool failures, longest quiet gap, missing token data; runs can complete green but still be flagged shaky)"],
          ["Token Breakdown", "Stacked token bar per LLM call showing prompt, completion, cache_read, cache_write, and reasoning tokens, plus a cache hit ratio indicator"],
          ["Steps", "Per-step inspector with LLM calls, tool rows, latency, and status"],
          ["Logs", "Live or archived worker logs with filters, JSON formatting, wrapping, and fullscreen mode"],
          ["Models & Tools", "Expandable tool calls with icon mapping, ArgsCard field extraction, Prism JSON highlighting, per-tool duration, and diff-aware rendering for patch output"],
          ["Compare", "Side-by-side execution comparison across status, duration, and tool or LLM counts"],
        ]} />
      </div>

      <div id="traces-endpoints">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Key Endpoints</h3>
        <DocsTable headers={["Endpoint", "Purpose"]} rows={[
          ["GET /api/v1/traces/executions", "List workflow executions with filters (namespace, workflow_name, agent_name, status)"],
          ["GET /api/v1/traces/executions/{id}", "Full execution detail: steps, LLM calls, tool calls, timeline events"],
          ["GET /api/v1/traces/executions/{id}/events", "Raw trace events from durable storage"],
          ["GET /api/v1/traces/steps/{id}", "Per-step detail with LLM and tool call records"],
          ["GET /api/v1/traces/{id}/timeline", "Ordered semantic timeline for a run"],
          ["GET /api/v1/traces/runtime-events", "Query runtime events (filter by namespace, event_type, agent, severity, time range)"],
          ["POST /api/v1/traces/executions/{id}/export/json", "Export execution as downloadable JSON"],
          ["GET /api/v1/traces/executions/{id}/export/html", "Export as self-contained HTML report"],
        ]} />
      </div>

      <div id="traces-runtime">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Runtime Events</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Runtime events are a separate indexed store for operational telemetry — error spikes, cost outliers,
          token usage, stuck runs. The signal-watch controller consumes these to drive automated analysis.
        </p>
        <h4 className="text-base font-semibold text-[oklch(0.95_0.005_264)] mb-2">Event types</h4>
        <DocsTable headers={["Category", "Event types"]} rows={[
          ["Run lifecycle (runtime)", "<code>run.started</code>, <code>run.completed</code>, <code>run.error</code>"],
          ["Tool calls (runtime)", "<code>tool.started</code>, <code>tool.completed</code>, <code>tool.failed</code>"],
          ["LLM calls (runtime)", "<code>llm.call</code> (includes prompt/completion/cache/reasoning tokens and cost)"],
          ["A2A delegations (operator)", "<code>agent.call.started</code>, <code>agent.call.completed</code>, <code>agent.call.failed</code>"],
          ["Workflow steps (operator)", "<code>step.started</code>, <code>step.completed</code>, <code>step.failed</code>"],
          ["Human-in-the-loop (runtime)", "<code>human.question</code> (HITL prompts raised by the agent)"],
          ["Plan progress (runtime)", "<code>todo.updated</code> (loop checklist state)"],
        ]} />
        <h4 className="text-base font-semibold text-[oklch(0.95_0.005_264)] mb-2 mt-4">Common event fields</h4>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["event_id", "string", "Unique event ID (upsert key)"],
          ["namespace", "string", "Namespace of the agent or workflow"],
          ["runtime_kind", "string", "<code>opencode</code> | <code>pi</code> | <code>mistral-vibe</code>"],
          ["event_type", "string", "One of 15 event types — 9 emitted by the OpenCode runtime (run.*, tool.*, llm.call, human.question, todo.updated) and 6 emitted by the operator (agent.call.*, step.*)"],
          ["agent_name", "string", "Agent that produced the event"],
          ["session_id", "string", "Session this event belongs to"],
          ["severity", "string", "<code>info</code> | <code>warning</code> | <code>error</code> | <code>critical</code>"],
          ["duration_ms", "integer", "Latency of the originating action (tool/llm/agent/step)"],
          ["payload", "object", "Event-type-specific structured payload"],
        ]} />
        <Callout variant="info" title="Tool result payloads &amp; the 40K cap">
          Full <code>tool_result</code> payloads rendered in the Observatory come from the runtime's final
          response payload and are forwarded by the operator. They are not carried in the live runtime status events.
          The OpenCode runtime truncates extracted tool output to <strong>40,000 characters</strong> at
          <code>opencode-runtime/analysis.py</code> before forwarding into the trace pipeline — this prevents
          single tool calls from flooding the trace store.
        </Callout>
      </div>
    </div>
  );
}

function IntelligenceSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Cpu}>Intelligence &amp; Collectors</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        The Run Intelligence layer collects operational data, runs automated analysis scripts,
        and can proactively invoke agents when anomalies are detected. Collectors are registered
        agents that execute scheduled or on-demand intelligence tasks.
      </p>

      <div id="intel-run-intel">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Run Intelligence Layer</h3>
        <p className="mb-3 text-sm text-[oklch(0.80_0.01_264)]">
          A dedicated <code>signal_watch</code> controller inside the operator watches the runtime-events
          store and fires three bundled <strong>system agents</strong> when deterministic thresholds are crossed.
          System agents are installed as Helm <code>post-install</code> / <code>post-upgrade</code> hooks into
          the <code>kubesynapse-system</code> namespace. LLM agents are only invoked for
          explanation/escalation — cheap SQL / rule checks fire first.
        </p>
        <DocsTable headers={["System agent", "Trigger", "Purpose"]} rows={[
          ["<code>ks-run-inspector</code>", "Workflow step failure rate &gt; 30% or ≥ 3 errors in window", "Root-cause analysis on failed runs with actionable remediation steps"],
          ["<code>ks-signal-summarizer</code>", "Deterministic anomaly check fires within last 30 min", "Correlates signals into a human-readable incident brief with severity suggestion"],
          ["<code>ks-spend-reviewer</code>", "Spend &gt; <code>$10</code> in window or token usage 3× rolling average", "Reviews cost outliers, recommends budget or runtime changes"],
        ]} />
        <h4 className="text-base font-semibold text-[oklch(0.95_0.005_264)] mb-2 mt-4">Run Intelligence endpoints</h4>
        <DocsTable headers={["Method", "Path", "Description"]} rows={[
          ["GET", "/api/v1/agent-graph", "Per-agent run graph — workflow fan-in/out, dependency edges, recent activity heatmap"],
          ["GET", "/api/v1/spend", "Aggregated token + cost spend breakdown by agent, namespace, model, and time window"],
        ]} />
        <Callout variant="info" title="Tunable thresholds">
          Each system agent exposes its own trigger thresholds in <code>values.yaml</code>:
          <code>systemAgents.runInspector.triggers.{'{}'}{'{ minFailureRate, minErrorCount }'}</code>,
          <code>systemAgents.signalSummarizer.triggers.maxSignalAgeMinutes</code>, and
          <code>systemAgents.spendReviewer.triggers.{'{}'}{'{ costThresholdUsd, tokenSpikeMultiplier }'}</code>.
          Disable individual agents via <code>systemAgents.runInspector.enabled: false</code> (or
          <code>signalSummarizer.enabled: false</code> / <code>spendReviewer.enabled: false</code>) — they
          ship enabled by default.
        </Callout>
      </div>

      <div id="intel-collectors">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Collectors</h3>
        <DocsTable headers={["Field", "Description"]} rows={[
          ["name", "Collector identifier (displayed in the dashboard)"],
          ["url", "HTTP endpoint of the collector (receives task POSTs)"],
          ["token", "Shared bearer token for authenticating to the collector"],
          ["cluster", "Optional cluster label for multi-cluster setups"],
          ["tags", "Optional tags for filtering and categorization"],
        ]} />
      </div>

      <div id="intel-tasks">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Collection Tasks</h3>
        <DocsTable headers={["Field", "Description"]} rows={[
          ["builtin", "Pre-defined analysis script (e.g. error-spike-analysis, cost-outlier-detection)"],
          ["script", "Custom bash or Python script to execute on the collector"],
          ["type", "Script type: bash (default) or python"],
          ["timeout", "Max execution time in seconds (default: 30, max: 60 for custom scripts)"],
          ["collector_id", "Target collector ID, or 'all' to broadcast to every registered collector"],
        ]} />
        <Callout variant="warning" title="Built-in safety">
          Write operations (delete, apply, rm, exec) in custom scripts are automatically blocked.
          Built-in scripts are pre-vetted and run with higher privilege.
        </Callout>
      </div>

      <div id="intel-schedules">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Schedules</h3>
        <DocsTable headers={["Field", "Description"]} rows={[
          ["name", "Schedule identifier"],
          ["cron", "Cron expression defining the recurring interval"],
          ["collector_id", "Target collector ID"],
          ["builtin / script", "Analysis to execute on the schedule"],
          ["agent_name", "Optional agent to invoke with the collection output as prompt-context"],
          ["enabled", "Whether the schedule is active"],
        ]} />
      </div>

      <div id="intel-alerts">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Alert Rules</h3>
        <DocsTable headers={["Field", "Description"]} rows={[
          ["name", "Alert rule identifier"],
          ["condition_type", "What condition to check (e.g. threshold, pattern, anomaly)"],
          ["condition_value", "Threshold value or pattern to match against"],
          ["action", "notify (send notification) or invoke_agent (call an agent with the finding)"],
          ["agent_name", "Agent to invoke when action=invoke_agent"],
          ["prompt_template", "Prompt template for agent invocation with {output} placeholder"],
        ]} />
      </div>

      <div id="intel-prompt-context">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Prompt Context Injection</h3>
        <p className="mb-3 text-[oklch(0.80_0.01_264)]">
          Use <code>POST /api/v1/intelligence/prompt-context</code> to fetch the latest intelligence
          output formatted for system prompt injection. This enables autonomous agents to consume
          real-time operational data without manual context assembly.
        </p>
        <CodeBlock code={`# Fetch latest collector output as prompt context
curl -X POST http://localhost:8080/api/v1/intelligence/prompt-context \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"collector_id": "prod-collector", "builtin": "error-spike-analysis"}'`} lang="bash" />
      </div>
    </div>
  );
}

function IncidentsSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Bug}>Incidents</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        Incidents are actionable alerts managed through the <code>AgentIncident</code> CRD. They
        can be created manually via the REST API or automatically via the Alertmanager webhook.
        The operator watches incidents and can escalate, acknowledge, resolve, and auto-trigger
        remediation workflows.
      </p>

      <div id="incident-crd">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">AgentIncident CRD</h3>
        <DocsTable headers={["Field", "Type", "Description"]} rows={[
          ["title", "string (required)", "Human-readable incident title"],
          ["description", "string", "Detailed incident description"],
          ["severity", "critical | warning | info (required)", "Incident severity level"],
          ["source", "alertmanager | manual | k8s-event | webhook", "How the incident was created (default: manual)"],
          ["status", "firing | acknowledged | diagnosing | remediating | resolved | closed | escalated", "State machine (default: firing)"],
          ["labels", "object (string → string)", "Key-value labels for filtering and correlation"],
          ["annotations", "object (string → string)", "Rich metadata"],
          ["assignedAgent", "string", "AIAgent name to auto-trigger for diagnosis / remediation"],
          ["escalationTimeout", "string (pattern <code>^[0-9]+(m|h)$</code>)", "Duration before auto-escalation (e.g. <code>15m</code>, <code>2h</code>). Default 15m for critical, 30m for warning, 1h for info."],
          ["escalated", "boolean", "Whether this incident has been escalated (default: false)"],
          ["autoAcknowledge", "boolean", "Auto-acknowledge on creation (default: true)"],
          ["workflowRef.name / .namespace", "string", "AgentWorkflow reference for auto-remediation"],
          ["acknowledgedAt / resolvedAt / closedAt / escalatedAt", "date-time", "Lifecycle timestamps"],
        ]} />
      </div>

      <div id="incident-lifecycle">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Lifecycle</h3>
        <DocsTable headers={["Transition", "Mechanism"]} rows={[
          ["firing → acknowledged", "PATCH /api/v1/incidents/{name} with status=acknowledged"],
          ["acknowledged → diagnosing", "PATCH with status=diagnosing (operator or assigned agent begins triage)"],
          ["diagnosing → remediating", "PATCH with status=remediating (workflow has started)"],
          ["remediating → resolved", "PATCH with status=resolved, Alertmanager resolve event, or workflow success"],
          ["resolved → closed", "PATCH with status=closed"],
          ["Auto-escalation", "After <code>escalationTimeout</code> the operator sets status=escalated"],
        ]} />
        <Callout variant="info" title="Alertmanager ingestion">
          Alertmanager posts to <code>POST /api/v1/webhooks/alertmanager</code>. The gateway fingerprints the
          alert payload, creates or updates an <code>AgentIncident</code>, and emits a runtime event. The
          operator's incident controller reconciles the state machine. Resolve events auto-transition to
          <code>resolved</code>.
        </Callout>
      </div>

      <div id="incident-example">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Example</h3>
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AgentIncident
metadata:
  name: prod-outage-001
spec:
  severity: critical
  source: alertmanager
  title: High CPU on node-3
  status: firing
  assignedAgent: remediation-bot
  escalationTimeout: 15m
  workflowRef:
    name: auto-remediate
    namespace: default`} lang="yaml" />
      </div>
    </div>
  );
}

function FaqSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={MessageSquare}>FAQ</SectionHeading>
      <div className="space-y-6">
        <div>
          <h4 className="font-bold text-[oklch(0.95_0.005_264)]">What makes kubesynapse different from other AI agent frameworks?</h4>
          <p className="mt-1 text-[oklch(0.80_0.01_264)]">kubesynapse is Kubernetes-native from day one — agents are CRDs managed by a Kopf operator, not Python objects running outside the cluster. It provides multi-tenancy, RBAC, audit logging, policy enforcement, and GitOps-ready workflows out of the box.</p>
        </div>
        <div>
          <h4 className="font-bold text-[oklch(0.95_0.005_264)]">Can I use my own LLM models?</h4>
          <p className="mt-1 text-[oklch(0.80_0.01_264)]">Yes. Configure any LiteLLM-compatible provider (Ollama, vLLM, etc.) in the Helm values.</p>
        </div>
        <div>
          <h4 className="font-bold text-[oklch(0.95_0.005_264)]">What is the minimum cluster size?</h4>
          <p className="mt-1 text-[oklch(0.80_0.01_264)]">For development: 4 vCPU, 8 GiB RAM (Kind/Minikube). Production: 8+ vCPU, 16+ GiB RAM with 3 nodes for HA.</p>
        </div>
        <div>
          <h4 className="font-bold text-[oklch(0.95_0.005_264)]">How do I upgrade between versions?</h4>
          <p className="mt-1 text-[oklch(0.80_0.01_264)]">Use <code>helm upgrade</code>. The operator handles CRD schema migrations automatically. Always back up the database before upgrading major versions.</p>
        </div>
        <div>
          <h4 className="font-bold text-[oklch(0.95_0.005_264)]">Is there a hosted/SaaS version?</h4>
          <p className="mt-1 text-[oklch(0.80_0.01_264)]">No. KubeSynapse is a fully self-hosted, open-source project under Apache 2.0. No telemetry, no vendor lock-in, no commercial tier. Your cluster, your data — always.</p>
        </div>
      </div>
    </div>
  );
}

function SecuritySection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={ShieldCheck}>Security Model</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        KubeSynapse enforces security across multiple layers — from authentication to container runtime isolation.
      </p>

      <div id="sec-auth">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Authentication & Tokens</h3>
        <DocsTable headers={["Mechanism", "Implementation", "Detail"]} rows={[
          ["Bearer tokens", "hmac.compare_digest", "Constant-time comparison prevents timing attacks"],
          ["JWT (local auth)", "JWT_SECRET signing key", "Separate from collector token by default — but the collector token encryption key falls back to JWT_SECRET when INTELLIGENCE_COLLECTOR_TOKEN_KEY is unset (the chart does not set it by default). Set INTELLIGENCE_COLLECTOR_TOKEN_KEY to a unique value to fully separate the keys."],
          ["Shared token mode", "Single bearer token", "Development only — use local or OIDC for production"],
          ["OIDC", "PKCE flow", "Google, GitHub, Azure AD, custom providers"],
          ["SAML", "SP-initiated", "Enterprise SSO integration"],
          ["Refresh tokens", "384-bit random + <code>SHA-256(JWT_SECRET ‖ token)</code> (key-prefix; NOT HMAC)", "Stored hashed; rotation on use. The construction is key-prefix SHA-256 (<code>auth_store.py:1867</code>), not a proper MAC — do not reuse this pattern for new code."],
          ["Password hashing", "argon2id (pbkdf2_sha256 fallback)", "Auto-upgrades on next login"],
        ]} />
      </div>

      <div id="sec-rbac">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">RBAC & Service Accounts</h3>
        <DocsTable headers={["Service Account", "Scope", "Permissions"]} rows={[
          ["Gateway SA", "ClusterRole", "CRUD on AIAgent/Workflow/Policy; read secrets + pods/log cross-namespace"],
          ["Operator SA", "ClusterRole", "Full CRD reconciliation; StatefulSet/Job creation; secret provisioning"],
          ["Worker SA", "ClusterRole", "Workflow read/patch; pods/log; configmap create; restricted"],
          ["Runtime SA", "Namespace Role (per-agent)", "Read-only CRDs; create AgentApprovals; read pods/log"],
          ["MCP Hub SA", "Dedicated namespace", "automountServiceAccountToken: false; no K8s API access"],
        ]} />
      </div>

      <div id="sec-network">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Network Security</h3>
        <DocsTable headers={["Layer", "Control"]} rows={[
          ["Agent isolation", "Single <code>app: ai-agent</code> NetworkPolicy: allow-list egress to DNS (53), LiteLLM (4000), Qdrant (6333), OTLP collector (4317), Kubernetes API (443/6443), and MCP servers (8000)"],
          ["MCP hub", "Dedicated <code>mcp-hub</code> namespace with default-deny NetworkPolicy; agent ingress on port 8000 only from <code>app=ai-agent</code> pods in namespaces labelled <code>kubesynapse.ai/tenant=true</code>; DNS + HTTPS egress, plus sandbox egress to Prometheus (9090), Grafana (3000), Qdrant (6333), LiteLLM (4000) within the release namespace"],
          ["A2A policies", "Operator generates per-agent A2A egress/ingress NetworkPolicies scoped to <code>allowedCallers</code> / <code>allowedTargets</code>"],
          ["Service exposure", "All services are ClusterIP — no LoadBalancer or NodePort by default"],
          ["Ingress", "TLS enforced via cert-manager; HSTS, X-Frame-Options, X-Content-Type-Options headers"],
        ]} />
      </div>

      <div id="sec-container">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Container & Runtime Security</h3>
        <DocsTable headers={["Control", "Detail"]} rows={[
          ["Non-root", "All containers: runAsNonRoot: true, runAsUser: 999 or 1000"],
          ["Read-only rootfs", "Read-only root filesystem; /tmp as emptyDir only writable mount"],
          ["Capabilities", "Drop ALL capabilities; no privilege escalation"],
          ["Seccomp", "RuntimeDefault seccomp profile on all pods"],
          ["gVisor", "Optional sandbox via enableGVisor: true in AIAgent spec"],
          ["pods/exec", "Removed from gateway SA — artifact reads use sidecar pattern"],
          ["ServiceAccount tokens", "MCP hub: automountServiceAccountToken: false"],
        ]} />
      </div>

      <div id="sec-secrets">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Secret Management</h3>
        <DocsTable headers={["Secret", "Source", "Auto-generated?"]} rows={[
          ["JWT_SECRET", "platformSecrets.native.jwtSecret", "Required — must be set on install"],
          ["COLLECTOR_TOKEN", "platformSecrets.native.collectorToken", "Yes — randAscii(48) if empty"],
          ["DATABASE_PASSWORD", "platformSecrets.native.databasePassword", "Required — must be set on install"],
          ["Redis password", "platformSecrets.native.redisPassword", "Yes — randAscii(32) if empty"],
          ["NATS token", "platformSecrets.native.natsToken", "Yes — randAscii(32) if empty"],
          ["MCP bearer token", "mcpHub.auth.bearerToken", "Yes — randAscii(48) on first install"],
        ]} />
        <h4 className="text-base font-semibold text-[oklch(0.95_0.005_264)] mb-2 mt-4">External secret backends</h4>
        <p className="mb-3 text-sm text-[oklch(0.80_0.01_264)]">
          The chart supports <code>platformSecrets.mode: external-secrets</code> to render a first-class
          <code>ExternalSecret</code> resource that syncs LLM API keys from a pre-configured
          <code>ClusterSecretStore</code>. Set <code>platformSecrets.externalSecrets.refreshInterval</code>
          (default <code>1h</code>) and <code>platformSecrets.externalSecrets.createClusterSecretStore</code>
          (default <code>true</code>) to control sync. The <code>native</code> mode (default) stores
          secrets in Kubernetes Secrets within the release namespace.
        </p>
        <DocsTable headers={["Backend", "Configuration", "Notes"]} rows={[
          ["External Secrets Operator", "<code>platformSecrets.mode: external-secrets</code>", "Reference AWS Secrets Manager, GCP Secret Manager, Azure Key Vault, or any ESO provider via a <code>ClusterSecretStore</code>. The chart renders the <code>ExternalSecret</code> and consumes the synced Secret."],
          ["Vault / Sealed Secrets / SOPS", "Out-of-band, bring your own", "Render the LLM API keys Secret manually with your preferred tool, then leave <code>platformSecrets.mode: native</code>. The chart re-uses the existing Secret data on upgrade."],
        ]} />
        <Callout variant="warning" title="Never commit secrets">
          Treat the <code>native</code> mode as a development convenience only. For production, set
          <code>platformSecrets.mode: external-secrets</code> and ensure the required
          <code>litellmMasterKey</code>, <code>apiGatewaySharedToken</code>, <code>databasePassword</code>, and
          <code>jwtSecret</code> are present in the backing store. The chart fails the install with a clear
          error if any of these are empty on first install.
        </Callout>
      </div>

      <div id="sec-rate-limit">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Rate Limiting</h3>
        <DocsTable headers={["Endpoint", "Limit", "Keyed By"]} rows={[
          ["POST /auth/login", "5 attempts / 60s", "IP + username"],
          ["POST /agents/{name}/invoke", "60 req/min", "Username (from token)"],
          ["Webhook invoke", "Per-webhook configurable", "IP + webhook name"],
        ]} />
        <p className="mt-2 text-sm text-[oklch(0.60_0.01_264)]">
          Rate-limited requests return HTTP 429. Configure via env vars:
          <code>AUTH_LOGIN_RATE_LIMIT_ATTEMPTS</code> and <code>API_INVOKE_RATE_LIMIT_PER_MINUTE</code>.
        </p>
      </div>

      <div id="sec-runtime-hardening">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">OpenCode Runtime Hardening</h3>
        <p className="text-sm text-[oklch(0.80_0.01_264)] mb-4">
          Every agent runtime ships with four defense layers enabled by default.
        </p>
        <DocsTable headers={["Layer", "Mechanism", "Default"]} rows={[
          ["Plugin isolation", "OPENCODE_DISABLE_DEFAULT_PLUGINS", "true — blocks auto-discovery of .opencode/plugin/*.ts"],
          ["Immutable baseline", "ConfigMap at /etc/kubesynapse/opencode.json", "plugin: [], restrictive permissions, blocked external skills"],
          ["Traffic enforcement", "OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON", "Force all LLM traffic through LiteLLM proxy"],
          ["Model governance", "OPENCODE_ADMIN_MODEL_OVERRIDE_JSON", "Global model allowlist at runtime"],
        ]} />
        <Callout variant="info" title="Admin overrides">
          Configure via <code>opencodeRuntime.admin</code> in values.yaml. These env vars are injected into every
          agent pod and cannot be overridden by agent CRDs. See the Helm chart README for examples.
        </Callout>
      </div>

      <div id="sec-gc">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Garbage Collection & Retention</h3>
        <DocsTable headers={["Resource", "Policy", "Default"]} rows={[
          ["Audit logs", "Auto-purge via daily CronJob", "90-day retention (configurable via apiGateway.auditRetentionDays)"],
          ["Expired sessions", "Daily cleanup via GC CronJob", "Enabled by default (gc.enabled: true)"],
          ["PostgreSQL backups", "Optional CronJob with PVC or S3 backend", "Disabled by default (backup.enabled: false)"],
          ["Revision history", "revisionHistoryLimit on all deployments", "3 revisions kept"],
          ["Orphan PVCs", "Operator prune on agent delete", "Enabled by default (ORPHAN_PRUNING_ENABLED: true)"],
        ]} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Composer & Workspace
// ---------------------------------------------------------------------------

function ComposerSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={FileCode}>Composer & Workspace</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        The Workflow Composer provides a visual drag-and-drop editor for building multi-agent pipelines,
        plus built-in tools for inspecting and downloading agent workspace output.
      </p>

      <div id="composer-overview">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Visual Workflow Builder</h3>
        <p className="text-sm text-[oklch(0.80_0.01_264)] mb-4">
          Build DAG-based workflows by dragging agent steps onto a canvas. Connect steps with dependency edges.
          Each step can reference any agent in your namespace.
        </p>
        <DocsTable headers={["Feature", "Description"]} rows={[
          ["Drag & drop", "Pull agents from the left palette onto the canvas"],
          ["Dependencies", "Draw edges between steps to define execution order"],
          ["Approval gates", "Mark any step as requiring human approval before execution"],
          ["Loop steps", "Configure iterative execution with loop config"],
          ["Conditional branching", "Route execution based on step output conditions"],
          ["YAML export", "Export the canvas to a complete AgentWorkflow YAML for git-tracked authoring — retry/backoff/timeout fields are configurable in YAML, not in the visual composer."],
        ]} />
      </div>

      <div id="composer-files">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Workspace File Browser</h3>
        <p className="text-sm text-[oklch(0.80_0.01_264)] mb-4">
          After running a workflow, use the Workspace Files panel to inspect what each agent produced.
          The file browser appears at the bottom of the composer when an agent step node is selected.
          Text files (Markdown, YAML, JSON, Python, TypeScript, etc.) render in a Monaco preview with syntax
          highlighting. Image files render inline (PNG, JPG, JPEG, GIF, SVG, WebP, BMP, ICO).
        </p>
        <DocsTable headers={["Action", "How"]} rows={[
          ["Browse files", "Expand the Workspace Files panel at the bottom of the composer"],
          ["Preview files", "Click any file to see its contents in the preview pane"],
          ["Text files", "Markdown, YAML, JSON, Python, TypeScript, and more render inline"],
          ["Image files", "PNG, JPG, GIF, SVG render directly in the preview"],
          ["Refresh", "Click the refresh button to reload after workflow runs produce new files"],
        ]} />
      </div>

      <div id="composer-download">
        <h3 className="text-lg font-bold text-[oklch(0.95_0.005_264)] mb-3">Downloading Results</h3>
        <DocsTable headers={["Method", "Description"]} rows={[
          ["Download ZIP", "Click the archive icon in the file browser header to download the entire workspace as a ZIP"],
          ["Download file", "Click the download icon next to any file in the preview header"],
          ["Artifact API", "Use the CLI: agentctl artifacts list &lt;agent&gt; and agentctl artifacts download &lt;agent&gt; &lt;path&gt;"],
          ["ZIP API", "GET /api/v1/agents/{name}/artifacts/zip to download the full workspace archive"],
        ]} />
        <Callout variant="info" title="Agent must be running">
          The file browser and download features require the agent runtime pod to be running.
          If the agent is in "unknown" or "failed" state, restart it first.
        </Callout>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unified sections registry
// ---------------------------------------------------------------------------

export const SECTIONS: DocSection[] = [
  {
    id: "getting-started",
    title: "Getting Started",
    icon: Terminal,
    searchText: "getting started quick start install helm kind local development first agent yaml opencode runtime kubernetes cluster prerequisites secrets configure ui access",
    subsections: [
      { id: "gs-prerequisites", title: "Prerequisites" },
      { id: "gs-install", title: "Install kubesynapse" },
      { id: "gs-secrets", title: "Configure Secrets" },
      { id: "gs-access", title: "Access the UI" },
      { id: "gs-first-agent", title: "Create Your First Agent" },
      { id: "gs-test", title: "Test with a Prompt" },
    ],
    content: <GettingStartedSection />,
  },
  {
    id: "architecture",
    title: "Architecture",
    icon: Server,
    searchText: "architecture system overview control plane execution plane api gateway crd operator opencode runtime mcp sidecars kubernetes data flow",
    subsections: [
      { id: "arch-overview", title: "System Overview" },
      { id: "arch-control", title: "Control Plane" },
      { id: "arch-tenant", title: "Multi-Tenancy" },
      { id: "arch-execution", title: "Execution Plane" },
      { id: "arch-gateway", title: "API Gateway" },
    ],
    content: <ArchitectureSection />,
  },
  {
    id: "agents",
    title: "Agents",
    icon: Bot,
    searchText: "agents creating agent yaml manifest configuration model system prompt storage skills context file-backed skills configmap runtime opencode session persistence a2a subagents",
    subsections: [
      { id: "agent-crd", title: "AIAgent CRD Reference" },
      { id: "agent-example", title: "Complete YAML Example" },
      { id: "agent-prompt", title: "System Prompt Best Practices" },
      { id: "agent-storage", title: "Storage Configuration" },
      { id: "agent-skills", title: "Skills (File-Backed)" },
      { id: "agent-create-guide", title: "How to Create Your First Agent" },
    ],
    content: <AgentsSection />,
  },
  {
    id: "chat-sessions",
    title: "Chat Sessions",
    icon: MessageSquare,
    searchText: "chat sessions conversation streaming sse message history session persistence invoke stream postgres saved messages",
    subsections: [{ id: "chat-basics", title: "Chat Session Basics" }],
    content: <ChatSessionsSection />,
  },
  {
    id: "memory",
    title: "Memory & Context",
    icon: GitBranch,
    searchText: "memory context durable recall postgres memory records runtime local jsonl qdrant semantic retrieval injected system prompt auto-promotion ranking injection",
    subsections: [
      { id: "memory-overview", title: "Architecture" },
      { id: "memory-promotion", title: "Auto-Promotion & Ranking" },
      { id: "memory-policy", title: "Memory Policy Controls" },
      { id: "memory-sources", title: "How Memory Is Created" },
    ],
    content: <MemorySection />,
  },
  {
    id: "workflows",
    title: "Workflows",
    icon: ListOrdered,
    searchText: "workflows multi-step dag orchestration automation approval gates dependencies parallel execution job scheduling",
    subsections: [
      { id: "wf-overview", title: "Workflow Overview" },
      { id: "wf-step-types", title: "Step Types" },
      { id: "wf-step-config", title: "Step Configuration" },
      { id: "wf-loop-config", title: "Loop Configuration" },
      { id: "wf-conditional", title: "Conditional Branching" },
      { id: "wf-auto-retry", title: "Auto-Retry" },
      { id: "wf-example", title: "Complete Example" },
    ],
    content: <WorkflowsSection />,
  },
  {
    id: "composer",
    title: "Composer & Workspace",
    icon: FileCode,
    searchText: "composer workflow builder visual editor drag drop file browser workspace files zip download artifacts preview file tree agent output",
    subsections: [
      { id: "composer-overview", title: "Visual Workflow Builder" },
      { id: "composer-files", title: "Workspace File Browser" },
      { id: "composer-download", title: "Downloading Results" },
    ],
    content: <ComposerSection />,
  },
  {
    id: "mcp",
    title: "MCP Connections",
    icon: Plug,
    searchText: "mcp model context protocol tools sidecars remote hub connections shared bearer token catalog runtime metadata validation auth sidecars list",
    subsections: [
      { id: "mcp-transports", title: "Transport Models" },
      { id: "mcp-sidecars", title: "Bundled Sidecars" },
      { id: "mcp-connection", title: "Connection Management" },
      { id: "mcp-hub", title: "MCP Hub Architecture" },
    ],
    content: <McpSection />,
  },
  {
    id: "a2a",
    title: "Agent-to-Agent (A2A)",
    icon: Bot,
    searchText: "a2a agent to agent communication peering delegation subagents cross-namespace json-rpc sse streaming protocol network policies allowed callers targets",
    subsections: [
      { id: "a2a-config-crd", title: "CRD Configuration" },
      { id: "a2a-network", title: "NetworkPolicies" },
      { id: "a2a-runtime", title: "Runtime Injection" },
      { id: "a2a-api", title: "A2A API Endpoints" },
      { id: "a2a-example", title: "JSON-RPC Example" },
      { id: "a2a-policy-example", title: "Policy Example" },
    ],
    content: <A2aSection />,
  },
  {
    id: "policies",
    title: "Policies & Governance",
    icon: ShieldCheck,
    searchText: "policies governance guardrails allowed models token caps cross-namespace access a2a targets approval requirements security compliance input output guardrails budget mcp tool memory policy",
    subsections: [
      { id: "policy-input", title: "Input Guardrails" },
      { id: "policy-output", title: "Output Guardrails" },
      { id: "policy-budget", title: "Budget" },
      { id: "policy-models", title: "Allowed Models" },
      { id: "policy-namespaces", title: "Cross-Namespace Access" },
      { id: "policy-mcp", title: "MCP Access Control" },
      { id: "policy-tools", title: "Tool Policy" },
      { id: "policy-memory", title: "Memory Policy" },
      { id: "policy-a2a", title: "A2A Policy" },
      { id: "policy-example", title: "Minimal Example" },
    ],
    content: <PoliciesSection />,
  },
  {
    id: "security",
    title: "Security Model",
    icon: ShieldCheck,
    searchText: "security authentication authorization tokens jwt bearer rbac network policies container secrets rate limiting argon2 constant-time hmac collector token service accounts",
    subsections: [
      { id: "sec-auth", title: "Authentication & Tokens" },
      { id: "sec-rbac", title: "RBAC & Service Accounts" },
      { id: "sec-network", title: "Network Security" },
      { id: "sec-container", title: "Container & Runtime Security" },
      { id: "sec-secrets", title: "Secret Management" },
      { id: "sec-rate-limit", title: "Rate Limiting" },
      { id: "sec-runtime-hardening", title: "Runtime Hardening" },
      { id: "sec-gc", title: "Garbage Collection" },
    ],
    content: <SecuritySection />,
  },
  {
    id: "observability",
    title: "Observability",
    icon: Eye,
    searchText: "observability monitoring telemetry metrics traces logs opentelemetry prometheus grafana alerting structured logging observation policy target report connector anomaly detection",
    subsections: [
      { id: "obs-telemetry", title: "Built-in Telemetry" },
      { id: "obs-crds", title: "Observation Subsystem CRDs" },
      { id: "obs-target", title: "ObservationTarget" },
      { id: "obs-policy", title: "ObservationPolicy" },
      { id: "obs-report", title: "ObservationReport" },
    ],
    content: <ObservabilitySection />,
  },
  {
    id: "incidents",
    title: "Incidents",
    icon: Bug,
    searchText: "incidents alerts agentincident crd alertmanager webhook escalation severity status acknowledge resolve lifecycle remediation workflow",
    subsections: [
      { id: "incident-crd", title: "AgentIncident CRD" },
      { id: "incident-lifecycle", title: "Lifecycle" },
      { id: "incident-example", title: "Example" },
    ],
    content: <IncidentsSection />,
  },
  {
    id: "cli",
    title: "CLI Reference",
    icon: Terminal,
    searchText: "cli agentctl command line interface kubectl plugin shell terminal tool invocation management",
    content: <CliSection />,
  },
  {
    id: "api-reference",
    title: "API Reference",
    icon: Wrench,
    searchText: "api reference rest endpoints openapi swagger agents invoke stream chat sessions memory providers admin users workflows traces webhooks mcp auth llm",
    subsections: [
      { id: "api-agents", title: "Agents" },
      { id: "api-workflows", title: "Workflows" },
      { id: "api-traces", title: "Traces & Run History" },
      { id: "api-chat", title: "Chat Sessions & Memory" },
      { id: "api-auth", title: "Auth" },
      { id: "api-providers", title: "LLM Providers" },
      { id: "api-webhooks", title: "Webhooks & Triggers" },
      { id: "api-mcp", title: "MCP & Catalog" },
      { id: "api-incidents", title: "Incidents" },
      { id: "api-intelligence", title: "Intelligence" },
      { id: "api-skills", title: "Skills Catalog" },
      { id: "api-admin", title: "Admin & System" },
    ],
    content: <ApiReferenceSection />,
  },
  {
    id: "llm-providers",
    title: "LLM Providers",
    icon: Zap,
    searchText: "llm providers litellm provider registry openrouter opencode opencode go github copilot live suggestions api keys",
    content: <LlmProvidersSection />,
  },
  {
    id: "export-import",
    title: "Export & Import",
    icon: Globe,
    searchText: "export import migration backup transfer bundles portable yaml configuration agent workflows policies cross-cluster",
    content: <ExportImportSection />,
  },
  {
    id: "webhooks",
    title: "Webhooks & Triggers",
    icon: Radio,
    searchText: "webhooks triggers events external invocation hmac signature rate limiting ip allowlist workflow trigger webhook receiver payload mapping workflow trigger",
    subsections: [
      { id: "wh-receiver", title: "WebhookReceiver" },
      { id: "wh-trigger", title: "WorkflowTrigger" },
      { id: "wh-execution-model", title: "Execution Model" },
      { id: "wh-example", title: "Example" },
    ],
    content: <WebhooksSection />,
  },
  {
    id: "traces",
    title: "Traces & Run History",
    icon: Clock,
    searchText: "traces run history execution timeline events llm calls tool calls debug export json html report runtime events signal watch batch",
    subsections: [
      { id: "traces-overview", title: "Trace Lifecycle" },
      { id: "traces-endpoints", title: "Key Endpoints" },
      { id: "traces-runtime", title: "Runtime Events" },
    ],
    content: <TracesSection />,
  },
  {
    id: "intelligence",
    title: "Intelligence & Collectors",
    icon: Cpu,
    searchText: "intelligence collectors run analysis automation schedules alerts cron scripts anomaly detection prompt context system agents collection tasks signal watch run inspector spend reviewer",
    subsections: [
      { id: "intel-run-intel", title: "Run Intelligence Layer" },
      { id: "intel-collectors", title: "Collectors" },
      { id: "intel-tasks", title: "Collection Tasks" },
      { id: "intel-schedules", title: "Schedules" },
      { id: "intel-alerts", title: "Alert Rules" },
      { id: "intel-prompt-context", title: "Prompt Context Injection" },
    ],
    content: <IntelligenceSection />,
  },
  {
    id: "troubleshooting",
    title: "Troubleshooting",
    icon: Bug,
    searchText: "troubleshooting debugging memory recall provider suggestions kind rollout restart logs diagnostics health check support workflows approval a2a loop circuit breaker conditional",
    subsections: [
      { id: "ts-general", title: "General Issues" },
      { id: "ts-workflows", title: "Workflow Issues" },
      { id: "ts-a2a", title: "A2A Issues" },
      { id: "ts-approval", title: "Approval Issues" },
      { id: "ts-backup", title: "Backup & Restore" },
    ],
    content: <TroubleshootingSection />,
  },
  {
    id: "faq",
    title: "FAQ",
    icon: MessageSquare,
    searchText: "faq frequently asked questions common questions answers troubleshooting getting help support community",
    content: <FaqSection />,
  },
];
