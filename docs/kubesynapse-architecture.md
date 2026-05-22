%% KubeSynapse platform architecture
%% Editable Mermaid source paired with docs/kubesynth-architectureold.drawio.

flowchart LR
    Browser["Browser"]
    CLI["agentctl / SDKs"]
    Apps["External apps"]
    Hooks["Webhook senders"]
    GitOps["kubectl / GitOps"]

    subgraph Cluster["Kubernetes Cluster"]
        direction TB

        subgraph EdgeLane["Edge and Application Backend"]
            direction LR
            WebUI["Web UI<br/>React + Nginx"]
            GW["API Gateway<br/>Auth, CRUD, invoke, stream, A2A, webhooks, traces"]
        end

        subgraph ControlPlane["CRD Control Plane"]
            direction LR
            K8S["Kubernetes API"]
            AgentCRDs["Agent CRDs<br/>AIAgent, AgentPolicy, AgentApproval,<br/>AgentWorkflow, AgentTenant"]
            IntegrationCRDs["Integration CRDs<br/>McpConnection, WebhookReceiver, WorkflowTrigger"]
            ObsCRDs["Observability CRDs<br/>ConnectorPlugin, ObservationTarget,<br/>ObservationPolicy, ObservationReport"]
        end

        subgraph ReconcileLane["Operator Reconciliation"]
            direction LR
            Operator["Operator"]
            CoreCtrls["Core controllers<br/>agent_controller, workflow_controller,<br/>status_projection, signal_watch"]
            IntegrationCtrls["Integration controllers<br/>mcp_connection_controller,<br/>webhook_controller"]
            GovernanceCtrls["Governance controllers<br/>approval_controller, tenant_controller,<br/>policy_controller, observation_controller"]
        end

        subgraph ExecuteLane["Execution Plane"]
            direction LR
            Runtime["Agent runtime StatefulSets<br/>singleton sandboxes: opencode, pi, mistral-vibe"]
            Services["Per-agent Services<br/>invoke / stream / cancel"]
            PVCs["State PVCs<br/>session and runtime state"]
            Netpol["Per-agent NetworkPolicies<br/>A2A and MCP isolation"]
            Sidecars["Optional MCP sidecars<br/>localhost tool servers"]
            Jobs["Workflow worker Jobs<br/>AgentWorkflow execution"]
            Artifacts["Artifacts and journals<br/>run evidence and status projection"]
        end

        subgraph SharedLane["Shared Services"]
            direction LR
            PG["PostgreSQL<br/>auth, sessions, traces,<br/>trigger rows, MCP metadata"]
            LiteLLM["LiteLLM<br/>model gateway"]
            Redis["Redis<br/>cache"]
            Qdrant["Qdrant<br/>retrieval"]
            NATS["NATS<br/>async bus"]
            MCPHub["Shared MCP hub<br/>optional shared tool path"]
            SecretWiring["Secret wiring<br/>External Secrets / stores"]
        end

        subgraph InsightLane["Execution Observatory and Security"]
            direction LR
            Observatory["Execution Observatory<br/>trace ingest, runtime events, query APIs"]
            SignalWatch["signal_watch<br/>deterministic anomaly detection"]
            Reports["ObservationReport CRs<br/>severity and health output"]
            SysAgents["System agents<br/>optional explanation"]
            ServiceMonitors["Optional ServiceMonitors"]
            Collector["Optional collector DaemonSet"]
            Security["Security overlays<br/>hybrid auth | tightened RBAC | restricted pods | per-agent NetworkPolicy | webhook HMAC/IP/rate/payload controls"]
        end
    end

    subgraph Providers["External Providers"]
        direction TB
        LLMProviders["LLM providers"]
        IdP["Enterprise IdP<br/>OIDC / SAML / LDAP"]
        SecretBackends["Secret backends<br/>Vault / cloud secret stores"]
    end

    Browser -->|HTTPS| WebUI
    WebUI -->|same-host /api| GW
    CLI -->|REST / SSE| GW
    Apps -->|REST / A2A| GW
    Hooks -->|public webhook invoke| GW
    GitOps -->|apply CRDs| K8S

    GW -->|CRUD, reads, status| K8S
    K8S --> AgentCRDs
    K8S --> IntegrationCRDs
    K8S --> ObsCRDs

    Operator -->|runs| CoreCtrls
    Operator -. loads when CRDs exist .-> IntegrationCtrls
    Operator -. loads when CRDs exist .-> GovernanceCtrls

    AgentCRDs -. watch .-> CoreCtrls
    IntegrationCRDs -. watch .-> IntegrationCtrls
    ObsCRDs -. watch .-> GovernanceCtrls

    CoreCtrls -. reconcile AIAgent .-> Runtime
    CoreCtrls -. provision runtime access .-> Services
    CoreCtrls -. provision runtime state .-> PVCs
    CoreCtrls -. provision isolation .-> Netpol
    CoreCtrls -. reconcile AgentWorkflow .-> Jobs

    IntegrationCtrls -. McpConnection mirror / trigger scan .-> PG
    IntegrationCtrls -. launch from trigger rows .-> Jobs

    Jobs -->|write workflow evidence| Artifacts
    GW -->|invoke / stream / cancel| Services
    Runtime -->|state| PVCs
    Runtime -->|localhost tools| Sidecars
    Runtime -. optional .-> MCPHub
    Runtime -->|model calls| LiteLLM
    LiteLLM -->|cache| Redis
    Runtime -->|retrieval| Qdrant

    GW -->|auth, sessions, traces, trigger rows| PG
    GW -. federated auth .-> IdP
    LiteLLM -->|provider calls| LLMProviders
    SecretBackends -. optional .-> SecretWiring

    Jobs -->|workflow traces| Observatory
    Runtime -->|runtime events| Observatory
    Jobs -->|runtime events| Observatory
    Observatory -->|indexed events| PG
    Observatory -->|scan pipeline| SignalWatch
    SignalWatch -->|ObservationReport| Reports
    SignalWatch -. optional explanation .-> SysAgents

    ServiceMonitors -. scrape .-> GW
    ServiceMonitors -. scrape .-> Operator
    ServiceMonitors -. scrape .-> LiteLLM

    Security -. auth and webhook controls .-> GW
    Security -. restricted pod security .-> Runtime
    Security -. network isolation .-> Netpol

    classDef actor fill:#F3E5F5,stroke:#7E57C2,color:#4A148C,stroke-width:1.5px;
    classDef edgeNode fill:#E8F5E9,stroke:#43A047,color:#1B5E20,stroke-width:1.5px;
    classDef controlNode fill:#E3F2FD,stroke:#1E88E5,color:#0D47A1,stroke-width:1.5px;
    classDef operatorNode fill:#E8EAF6,stroke:#3949AB,color:#1A237E,stroke-width:1.5px;
    classDef execNode fill:#E8F5E9,stroke:#2E7D32,color:#1B5E20,stroke-width:1.5px;
    classDef sharedNode fill:#ECEFF1,stroke:#546E7A,color:#263238,stroke-width:1.5px;
    classDef insightNode fill:#FFF8E1,stroke:#F9A825,color:#6D4C41,stroke-width:1.5px;
    classDef provider fill:#FBE9E7,stroke:#F4511E,color:#BF360C,stroke-width:1.5px;
    classDef securityNode fill:#FFF3E0,stroke:#FB8C00,color:#BF360C,stroke-width:2px;

    class Browser,CLI,Apps,Hooks,GitOps actor;
    class WebUI,GW edgeNode;
    class K8S,AgentCRDs,IntegrationCRDs,ObsCRDs controlNode;
    class Operator,CoreCtrls,IntegrationCtrls,GovernanceCtrls operatorNode;
    class Runtime,Services,PVCs,Netpol,Sidecars,Jobs,Artifacts execNode;
    class PG,LiteLLM,Redis,Qdrant,NATS,MCPHub,SecretWiring sharedNode;
    class Observatory,SignalWatch,Reports,SysAgents,ServiceMonitors,Collector insightNode;
    class LLMProviders,IdP,SecretBackends provider;
    class Security securityNode;

    style Cluster fill:#FAFAFA,stroke:#BDBDBD,stroke-width:2px,stroke-dasharray:8 4
    style EdgeLane fill:#F1F8E9,stroke:#81C784,stroke-width:1px
    style ControlPlane fill:#EFF8FF,stroke:#90CAF9,stroke-width:1px
    style ReconcileLane fill:#EEF2FF,stroke:#9FA8DA,stroke-width:1px
    style ExecuteLane fill:#F1F8E9,stroke:#81C784,stroke-width:1px
    style SharedLane fill:#F5F7FA,stroke:#B0BEC5,stroke-width:1px
    style InsightLane fill:#FFFDE7,stroke:#FFD54F,stroke-width:1px
    style Providers fill:#FFF3E0,stroke:#FFAB91,stroke-width:1px
