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
} from "lucide-react";
import { CodeBlock, Callout, DocsTable, QuickRefCard, StepGuide, SectionHeading } from "./shared";
import { MermaidDiagram } from "../MermaidDiagram";
import type { DocSection } from "./types";

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
          { label: "API Base", value: "/api" },
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
            ["Kubernetes", "1.25+", "Any CNCF-certified distribution (EKS, GKE, AKS, Kind, k3s)."],
            ["Helm", "3.12+", "Required for chart installation and upgrades."],
            ["kubectl", "1.25+", "Must be configured to target your cluster."],
            ["LLM API Key", "—", "OpenAI, Anthropic, or another LiteLLM-compatible provider."],
            ["Container Runtime", "—", "Docker or Podman for local image builds."],
          ]}
        />
        <Callout variant="info" title="Resource Recommendations">
          For production deployments, allocate at least 4 vCPU and 8 GiB RAM for the control plane namespace. Each agent
          runtime requests 500m CPU and 512Mi RAM by default.
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
kubectl wait --for=condition=ready pod -n kubesynapse -l app=kubesynapse-api-gateway --timeout=120s

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
                  The first bootstrap creates an admin user. Follow the on-screen instructions to set a password, or
                  configure OIDC/SAML in the settings page.
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
                <CodeBlock code={`agentctl invoke my-first-agent --prompt "Hello, what can you do for me?"`} lang="bash" />
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
          { label: "Control Plane", value: "CRDs + Operator + Gateway" },
          { label: "Execution Plane", value: "StatefulSet + PVC + Sidecars" },
          { label: "Operator", value: "Kopf-based Python controller" },
          { label: "Runtime", value: "OpenCode (FastAPI wrapper)" },
          { label: "Min K8s", value: "1.25+" },
        ]}
      />
      <div id="arch-overview">
        <SectionHeading icon={Layers}>System Overview</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          kubesynapse separates the <strong>control plane</strong> (CRDs, operator, gateway) from the{" "}
          <strong>execution plane</strong> (per-agent runtimes and sidecars). All desired state is stored in the
          Kubernetes API and reconciled by a Kopf-based operator.
        </p>
        <MermaidDiagram
          chart={`flowchart TB
    subgraph Clients
        UI[Web UI React 18 + Vite]
        CLI[agentctl CLI]
        EXT[External Clients]
    end
    subgraph CP[Control Plane]
        GW[API Gateway FastAPI]
        OP[Operator Kopf]
        K8S[Kubernetes API Server]
        UI_SRV[Web UI Server]
    end
    subgraph EP[Execution Plane]
        STS[OpenCode StatefulSet]
        MCP[MCP Sidecars]
        PVC[State PVC]
    end
    UI --> GW
    CLI --> GW
    EXT --> GW
    GW --> K8S
    GW --> OP
    GW --> UI_SRV
    OP --> K8S
    K8S --> STS
    STS --> MCP
    STS --> PVC`}
        />
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
          ]}
        />
        <MermaidDiagram
          chart={`erDiagram
    AIAgent ||--o{ AgentPolicy : references
    AIAgent ||--o{ AgentApproval : creates
    AgentWorkflow ||--o{ AIAgent : steps_use
    AgentWorkflow ||--o{ AgentApproval : gates_with
    AIAgent ||--o{ ConnectorPlugin : observes_via
    ConnectorPlugin ||--o{ ObservationTarget : targets
    ObservationTarget ||--o{ ObservationPolicy : evaluates_with
    ObservationPolicy ||--o{ ObservationReport : produces`}
        />
      </div>
      <div id="arch-execution">
        <SectionHeading icon={Server}>Execution Plane</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Each agent runs as an isolated singleton StatefulSet backed by the <strong>OpenCode runtime</strong> — a
          FastAPI wrapper around <code>opencode serve</code> with session persistence and checkpoint recovery.
          Optional <strong>MCP sidecars</strong> run alongside the runtime to provide tools such as code execution,
          web search, browser automation, and database access.
        </p>
        <MermaidDiagram
          chart={`flowchart TB
    subgraph Pod[Agent Pod]
        RT[OpenCode Runtime<br/>FastAPI + opencode serve]
        SC1[MCP Sidecar<br/>e.g., Code Execution]
        SC2[MCP Sidecar<br/>e.g., Web Search]
        PVC[(State PVC<br/>Sessions + Artifacts)]
    end
    RT <-->|localhost| SC1
    RT <-->|localhost| SC2
    RT -->|read/write| PVC`}
        />
      </div>
      <div id="arch-gateway">
        <SectionHeading icon={Globe}>API Gateway Responsibilities</SectionHeading>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          <li>Authentication and authorization (Bearer tokens, OIDC, SAML, local auth)</li>
          <li>RESTful CRUD for agents, workflows, policies, and tenants</li>
          <li>A2A JSON-RPC and Server-Sent Events (SSE) for real-time streaming</li>
          <li>Workflow triggers and approval decisions</li>
          <li>LLM routing through LiteLLM with model fallbacks and cost tracking</li>
        </ul>
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
          { label: "Required Fields", value: "metadata.name, spec.model, spec.runtime.kind" },
          { label: "API Endpoint", value: "POST /api/v1/agents" },
          { label: "Runtime", value: "opencode" },
          { label: "Storage Default", value: "1Gi PVC" },
        ]}
      />
      <div id="agent-crd">
        <SectionHeading icon={FileCode}>AIAgent CRD Reference</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          The <code>AIAgent</code> custom resource is the core unit of kubesynapse. The operator watches these resources
          and provisions matching StatefulSets, PVCs, and ConfigMaps.
        </p>
        <DocsTable
          headers={["Field", "Type", "Required", "Description"]}
          rows={[
            ["spec.model", "string", "Yes", "LLM model identifier routed through LiteLLM (e.g., gpt-4o)."],
            ["spec.systemPrompt", "string", "No", "The system instruction that defines behavior and responsibilities."],
            ["spec.runtime.kind", "string", "Yes", "Runtime image contract. Default: opencode."],
            ["spec.storage.size", "string", "No", "Persistent volume claim size (e.g., 1Gi, 5Gi)."],
            ["spec.policyRef", "string", "No", "Name of an AgentPolicy in the same namespace."],
            ["spec.enableGVisor", "boolean", "No", "Run the runtime inside a gVisor sandbox."],
            ["spec.mcpConnections", "array", "No", "Structured MCP connection references."],
            ["spec.skills.files", "map", "No", "Inline file-backed context keyed by filename."],
            ["spec.a2a.allowedCallers", "array", "No", "Peers permitted to call this agent via A2A."],
            ["spec.gitConfig.repoUrl", "string", "No", "Git repository for autonomous file operations."],
            ["spec.githubConfig.credentialSecretRef", "string", "No", "Secret reference for GitHub API access."],
          ]}
        />
      </div>
      <div id="agent-example">
        <SectionHeading icon={FileCode}>Complete YAML Example</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          This manifest demonstrates every major field of the AIAgent CRD with inline documentation.
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
  storage:
    size: 2Gi
  enableGVisor: false
  policyRef: strict-policy
  mcpConnections:
    - connectionId: conn-github-prod
    - connectionId: conn-k8s-prod
  skills:
    files:
      review-guide.md: |
        # Review Guide
        - Check for SQL injection
        - Verify error handling
        - Prefer early returns
  a2a:
    allowedCallers:
      - name: planner-agent
        namespace: default
  gitConfig:
    repoUrl: https://github.com/acme/platform
    defaultBranch: main
    pushPolicy: on-approval
    authMethod: token
    credentialSecretRef: git-credentials`}
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
        { label: "Storage", value: "PostgreSQL + runtime thread state" },
      ]} />
      <div id="chat-basics">
        <SectionHeading icon={MessageSquare}>Chat Session Basics</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          Live responses and saved history are related but separate. Invoke calls hit the agent runtime,
          while chat-session history is stored by the gateway and listed per <code>agent_name</code> and namespace.
        </p>
        <CodeBlock code={`# List sessions for one agent
curl "http://localhost:8080/api/v1/chat-sessions?agent_name=my-agent&namespace=default" \
  -H "Authorization: Bearer $TOKEN"

# Replace the full stored message list for a session
curl -X PUT http://localhost:8080/api/v1/chat-sessions/session-123/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"message_id":"msg-1","role":"user","content":"Explain Kubernetes controllers","status":"complete"}]}'

# Stream a live invoke
curl -N -X POST http://localhost:8080/api/v1/agents/my-agent/invoke/stream \
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"message":"Explain Kubernetes controllers"}'`} lang="bash" />
        <Callout variant="info" title="Persistence semantics">
          Saving chat messages replaces the stored message array for that session. Session saves can also
          auto-promote a durable memory summary, while the runtime continues to manage its own thread state.
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
        kubesynapse now uses a layered memory model. The user-visible durable recall path lives in the
        API gateway, while the OpenCode runtime still keeps its own local memory store for thread continuity
        and optional semantic retrieval.
      </p>
      <DocsTable headers={["Component", "Technology", "Purpose"]} rows={[
        ["Gateway durable memory", "PostgreSQL memory_records", "Cross-session promoted recall and ranking"],
        ["Runtime-local memory", "JSONL under OPENCODE_MEMORY_DIR", "Thread continuity and handoff inside the runtime pod"],
        ["Semantic provider", "Optional Qdrant", "Runtime-local semantic retrieval when enabled"],
        ["Policy layer", "AgentPolicy.memoryPolicy", "Controls maxInjectedMemories, maxInjectedChars, and auto-promotion"],
      ]} />
      <Callout variant="info" title="Stream parity">
        Durable memory is injected on both sync and streamed invokes. If the gateway needs to assemble a
        memory-heavy system prompt first, it can preserve parity by emitting SSE from a non-stream runtime invoke.
      </Callout>
    </div>
  );
}

function WorkflowsSection() {
  return (
    <div className="space-y-8">
      <QuickRefCard title="Workflows Quick Reference" items={[
        { label: "CRD Kind", value: "AgentWorkflow" },
        { label: "Max Steps", value: "50" },
        { label: "Approval Gates", value: "Optional" },
      ]} />
      <div id="wf-overview">
        <SectionHeading icon={ListOrdered}>Workflow Overview</SectionHeading>
        <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
          AgentWorkflow defines a multi-step DAG where each step uses one or more AIAgents.
          Steps can run sequentially or in parallel, with optional human-approval gates.
        </p>
        <CodeBlock code={`apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: code-review-pipeline
spec:
  steps:
    - name: lint
      agentRef: linter-agent
    - name: review
      agentRef: reviewer-agent
      dependsOn: [lint]
    - name: approve
      type: approval
      dependsOn: [review]`} lang="yaml" />
      </div>
    </div>
  );
}

function McpSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Plug}>MCP (Model Context Protocol)</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        MCP connections provide tool surfaces to agents. kubesynapse supports shared hub-backed servers,
        direct remote MCP endpoints, and sidecar-local tool containers, all managed from the catalog and
        agent editors.
      </p>
      <DocsTable headers={["Transport", "Use Case", "Security"]} rows={[
        ["remote", "External MCP servers and SaaS bridges", "Stored credentials; some servers require a shared bearer token"],
        ["hub", "Shared in-cluster MCP services", "Enabled with mcpHub.enabled and reused across agents"],
        ["sidecar", "Per-agent local tool containers", "localhost-only, strongest isolation boundary"],
      ]} />
      <Callout variant="tip" title="Choose the transport intentionally">
        Use sidecars for the most sensitive tools, hub connections for shared internal services, and remote
        connections for external systems that cannot run in-cluster. The gateway manages connection records,
        while the operator/runtime enforce the actual auth and mount behavior.
      </Callout>
    </div>
  );
}

function A2aSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Bot}>Agent-to-Agent (A2A)</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        A2A enables agents to call each other for specialized tasks. Configure <code>allowedCallers</code> on
        the target agent and define <code>allowedA2ATargets</code> in policies or skills.
      </p>
      <CodeBlock code={`# Agent A calling Agent B via A2A
curl -X POST http://localhost:8080/a2a/invoke \\
  -H "Authorization: Bearer $TOKEN" \\
  -d '{"targetAgent":"agent-b","message":"Analyze this dataset"}'`} lang="bash" />
    </div>
  );
}

function PoliciesSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={ShieldCheck}>Agent Policies</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        AgentPolicy defines guardrails: allowed models, token caps, cross-namespace access rules, and
        tool restrictions. Attach policies to agents via <code>policyRef</code>.
      </p>
      <DocsTable headers={["Policy Field", "Description"]} rows={[
        ["allowedModels", "Whitelist of permitted LLM models"],
        ["maxTokensPerRequest", "Hard cap on token consumption per invocation"],
        ["allowedNamespaces", "Controls cross-namespace A2A access"],
        ["a2a.allowedTargets", "Explicit list of agents this agent may call"],
        ["requireApproval", "Force human approval for high-risk actions"],
      ]} />
    </div>
  );
}

function ObservabilitySection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Eye}>Observability</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        kubesynapse exposes OpenTelemetry traces, Prometheus metrics, and structured JSON logs across all components.
      </p>
      <DocsTable headers={["Component", "Metrics", "Traces", "Logs"]} rows={[
        ["API Gateway", "/metrics (Prometheus)", "OpenTelemetry spans", "JSON structured"],
        ["Operator", "/metrics (built-in HTTP)", "OpenTelemetry spans", "JSON structured"],
        ["LiteLLM", "LLM usage, latency, errors", "Request traces", "Provider logs"],
        ["Agent Runtime", "Tool calls, token usage", "Per-request spans", "Worker logs"],
      ]} />
    </div>
  );
}

function CliSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Terminal}>CLI Reference (agentctl)</SectionHeading>
      <p className="mt-2 text-base leading-7 text-[oklch(0.80_0.01_264)]">
        <code>agentctl</code> is the official CLI for managing kubesynapse agents from the terminal.
      </p>
      <CodeBlock code={`# List all agents
agentctl list agents

# Create an agent from a YAML file
agentctl create -f agent.yaml

# Invoke an agent
agentctl invoke my-agent --prompt "Summarize this PR"

# Check system health
agentctl health`} lang="bash" />
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
      <DocsTable headers={["Method", "Path", "Description"]} rows={[
        ["GET", "/api/v1/health", "Health check"],
        ["GET", "/api/v1/agents", "List agents"],
        ["POST", "/api/v1/agents", "Create agent"],
        ["GET", "/api/v1/agents/{name}", "Get agent details"],
        ["POST", "/api/v1/agents/{name}/invoke", "Invoke agent synchronously"],
        ["POST", "/api/v1/agents/{name}/invoke/stream", "Invoke agent as SSE"],
        ["GET", "/api/v1/chat-sessions?agent_name=...", "List saved sessions for one agent"],
        ["PATCH", "/api/v1/memory/{record_id}", "Edit a durable memory record"],
        ["GET", "/api/v1/providers", "List provider registry entries"],
        ["GET", "/api/v1/llm/providers/{provider}/suggestions", "Fetch live provider model suggestions"],
        ["POST", "/api/v1/admin/users", "Create a local user and reconcile dedicated tenant access"],
        ["GET", "/api/v1/workflows", "List workflows"],
        ["GET", "/api/v1/mcp/connections", "List MCP connections"],
      ]} />
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
        Export agent configurations, policies, and workflows as portable YAML bundles for migration between clusters.
      </p>
      <CodeBlock code={`# Export an agent with all dependencies
agentctl export agent my-agent --include-policies --include-workflows > bundle.yaml

# Import into another cluster
kubectl apply -f bundle.yaml`} lang="bash" />
    </div>
  );
}

function TroubleshootingSection() {
  return (
    <div className="space-y-8">
      <SectionHeading icon={Bug}>Troubleshooting</SectionHeading>
      <DocsTable headers={["Issue", "Symptom", "Resolution"]} rows={[
        ["Agent stuck in Pending", "Pod never starts", "Check resource quotas and node capacity"],
        ["Provider suggestions are empty", "Settings shows no models", "Configure the provider credential first, then reload suggestions"],
        ["Durable memory is not recalled", "Saved history exists but the agent forgets", "Verify memoryPolicy is enabled, then inspect gateway memory_records for the right user, namespace, and agent"],
        ["Local fix does not show up", "Kind still serves old code after loading :dev", "Run kubectl rollout restart on the touched deployment when the image tag did not change"],
        ["MCP tool unavailable", "Tool call timeouts", "Check sidecar logs or the remote MCP endpoint auth configuration"],
        ["Workflow never completes", "Step stuck in Running", "Verify approval was submitted"],
      ]} />
      <Callout variant="troubleshoot" title="Debug Commands">
        <div className="space-y-2">
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl describe aiagent &lt;name&gt; -n &lt;ns&gt;
          </code>
          <code className="block rounded-md bg-background/70 px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words">
            kubectl logs -l app=operator -n kubesynapse
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
          <p className="mt-1 text-[oklch(0.80_0.01_264)]">kubesynapse is designed for self-hosting. Enterprise support and managed offerings are available. Contact the maintainers for details.</p>
        </div>
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
    searchText: "memory context durable recall postgres memory records runtime local jsonl qdrant semantic retrieval injected system prompt",
    content: <MemorySection />,
  },
  {
    id: "workflows",
    title: "Workflows",
    icon: ListOrdered,
    searchText: "workflows multi-step dag orchestration automation approval gates dependencies parallel execution job scheduling",
    subsections: [{ id: "wf-overview", title: "Workflow Overview" }],
    content: <WorkflowsSection />,
  },
  {
    id: "mcp",
    title: "MCP Connections",
    icon: Plug,
    searchText: "mcp model context protocol tools sidecars remote hub connections shared bearer token catalog runtime metadata",
    content: <McpSection />,
  },
  {
    id: "a2a",
    title: "Agent-to-Agent (A2A)",
    icon: Bot,
    searchText: "a2a agent to agent communication peering delegation subagents cross-namespace json-rpc sse streaming",
    content: <A2aSection />,
  },
  {
    id: "policies",
    title: "Policies & Governance",
    icon: ShieldCheck,
    searchText: "policies governance guardrails allowed models token caps cross-namespace access a2a targets approval requirements security compliance",
    content: <PoliciesSection />,
  },
  {
    id: "observability",
    title: "Observability",
    icon: Eye,
    searchText: "observability monitoring telemetry metrics traces logs opentelemetry prometheus grafana alerting structured logging",
    content: <ObservabilitySection />,
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
    searchText: "api reference rest endpoints openapi swagger agents invoke stream chat sessions memory providers admin users workflows",
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
    id: "troubleshooting",
    title: "Troubleshooting",
    icon: Bug,
    searchText: "troubleshooting debugging memory recall provider suggestions kind rollout restart logs diagnostics health check support",
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
