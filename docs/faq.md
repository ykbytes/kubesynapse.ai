# KubeSynapse Frequently Asked Questions

**Who is this for:** Anyone evaluating, deploying, or operating KubeSynapse.

---

## Table of Contents

- [General](#general)
- [Platform Comparison](#platform-comparison)
- [Models and Providers](#models-and-providers)
- [Kubernetes Requirements](#kubernetes-requirements)
- [Resources and Scaling](#resources-and-scaling)
- [Security and Compliance](#security-and-compliance)
- [Development and Customization](#development-and-customization)
- [Operations](#operations)
- [Community and Support](#community-and-support)

---

## General

### What is KubeSynapse?

KubeSynapse is a production-grade, Kubernetes-native AI agent platform. It deploys,
orchestrates, and governs AI agents using declarative custom resources (CRDs).
You define agents, workflows, policies, and approvals as YAML, and the platform
handles runtime provisioning, security, monitoring, and scaling.

### Who should use KubeSynapse?

- **Platform teams** who want to offer AI agents as a managed service
- **DevOps engineers** who need agents that interact with Kubernetes, Git, and cloud APIs
- **Enterprises** that require policy governance, audit trails, and multi-tenancy
- **AI developers** who want reproducible agent deployments with version control

### What does "Kubernetes-native" mean?

It means agents are first-class Kubernetes resources. You use `kubectl apply` to
create them, the operator reconciles desired state, and you get all Kubernetes
primitives for free: RBAC, NetworkPolicy, PodDisruptionBudgets, HPA, logging,
and metrics.

---

## Platform Comparison

### How is KubeSynapse different from LangChain or CrewAI?

LangChain and CrewAI are Python libraries. You write code to build agents.
KubeSynapse is a platform: you write YAML, and the platform runs the agents in
isolated sandboxes with built-in governance, observability, and multi-tenancy.

| Capability | KubeSynapse | LangChain | CrewAI |
|------------|-----------|-----------|--------|
| Deployment model | Helm chart on Kubernetes | Python library | Python library |
| Governance | CRD-based policies | Manual code | Manual code |
| Multi-tenancy | Native (`AgentTenant`) | Not built-in | Not built-in |
| A2A protocol | Native JSON-RPC/SSE | Not built-in | Not built-in |
| MCP tools | 11 bundled sidecars | Requires setup | Requires setup |
| Human-in-the-loop | `AgentApproval` CRD | External | External |

### How is KubeSynapse different from Dify or LangFlow?

Dify and LangFlow are visual workflow builders with self-hosted options.
KubeSynapse is operator-driven and GitOps-friendly. You manage agents as code,
not as GUI graphs, which makes CI/CD, review, and rollback natural.

### How is KubeSynapse different from Kubiya?

Kubiya focuses on conversational DevOps with a SaaS model. KubeSynapse is open-source, runs entirely in your cluster, and gives you full control over the runtime, policies, and data.

---

## Models and Providers

### Which LLM providers are supported?

Any provider supported by LiteLLM, which includes:

- OpenAI (GPT-4o, GPT-4o-mini, o1, etc.)
- Anthropic (Claude 3.5 Sonnet, Opus, etc.)
- Azure OpenAI
- Google (Gemini)
- Cohere
- Mistral
- Local models via vLLM, Ollama, or TGI

### Can I use multiple providers at once?

Yes. Configure multiple providers in LiteLLM, and use `AgentPolicy.allowedModels` to restrict which models an agent can call.

### Do you support fine-tuned models?

Yes. Add custom model definitions via the LiteLLM configuration or the `/api/v1/llm/models` endpoint.

---

## Kubernetes Requirements

### What Kubernetes version is required?

Kubernetes 1.25 or later. The platform uses features like CronJob v1, NetworkPolicy, and CRD subresources that require 1.25+.

### Does KubeSynapse work on managed Kubernetes?

Yes. Tested on EKS, GKE, AKS, and Kind. See [COMPATIBILITY.md](../COMPATIBILITY.md) for the full matrix.

### Does KubeSynapse work on OpenShift?

Partially. OpenShift's SecurityContextConstraints may conflict with the default security contexts. You may need to customize SCCs or disable restricted profiles.

### Does KubeSynapse work on GKE Autopilot or Fargate?

GKE Autopilot and Fargate have restrictions on privileged containers and DaemonSets. The collector DaemonSet may not run. Run the core platform without the observability collector on these environments.

---

## Resources and Scaling

### What are the minimum resource requirements?

For a single-node development deployment:

| Component | CPU | Memory |
|-----------|-----|--------|
| API Gateway | 250m | 512Mi |
| Operator | 250m | 512Mi |
| LiteLLM | 250m | 512Mi |
| PostgreSQL | 250m | 512Mi |
| Per-Agent Runtime | 100m | 256Mi |

**Total for platform + 1 agent:** approximately 1.5 CPU cores and 3Gi memory.

### How many agents can run on one cluster?

There is no hard limit. Each agent is a StatefulSet, so the limit is your
cluster's capacity for pods, CPU, memory, and PVCs. A 10-node cluster with
32 cores and 64Gi per node can comfortably run 50+ agents.

### Does KubeSynapse support GPU acceleration?

Yes. Set `runtimeClassName: nvidia` in the agent spec and ensure GPU nodes are available. The runtime will use the GPU for model inference if the underlying runtime supports it.

### Can I scale the gateway horizontally?

Yes. The gateway is stateless. Enable HPA in Helm values:

```yaml
autoscaling:
  enabled: true
  apiGateway:
    minReplicas: 3
    maxReplicas: 20
```

---

## Security and Compliance

### How is authentication handled?

KubeSynapse supports multiple auth modes: shared token, JWT, OIDC, SAML, LDAP, and hybrid. OIDC is recommended for production.

### How is authorization enforced?

Role-based access control with three roles: `viewer`, `operator`, and `admin`. Namespace access is scoped per user. See [RBAC Matrix](rbac-matrix.md).

### Is data encrypted at rest?

Agent state PVCs use the cluster's StorageClass encryption. PostgreSQL and trace storage should use encrypted storage classes. Secrets are stored in Kubernetes Secrets or External Secrets.

### Is data encrypted in transit?

Yes. All inter-service communication inside the cluster should use TLS where configured. External ingress should terminate TLS. Set `apiGateway.tls.enabled: true` in production.

### Does KubeSynapse support compliance frameworks?

The platform provides audit logging, approval gates, policy enforcement, and
namespace isolation, which map to SOC 2, ISO 27001, and NIST controls. You are
responsible for configuring them to match your specific compliance requirements.

---

## Development and Customization

### Can I use a custom runtime instead of OpenCode?

Currently, the supported in-tree runtime kinds are `opencode`, `pi`, and `mistral-vibe`. The architecture still allows additional runtimes in the future, but those three are the implemented and supported paths today.

### Can I build my own MCP tool?

Yes. MCP tools are standard containers that expose a local HTTP or stdio interface. Package your tool as a container, add it to the MCP registry, and attach it to agents via `mcpConnections`.

### How do I develop locally without cloud?

Use Kind or Minikube:

```bash
kind create cluster --name kubesynapse-dev
helm install KubeSynapse oci://docker.io/kubesynapse/charts/kubesynapse \
  --set platformSecrets.native.openaiApiKey="sk-..."
```

For offline development, use Ollama as the LLM provider:

```yaml
litellm:
  models:
    - model_name: local-llama
      litellm_params:
        model: ollama/llama3.1
        api_base: http://ollama:11434
```

### Can I extend the Web UI?

Yes. The Web UI is a React 18 + Vite application in `web-ui/`. It uses Tailwind CSS v4 and shadcn/ui. Fork and rebuild the image, or mount custom components in development.

---

## Operations

### What is the backup strategy?

Back up these components:

1. **Auth database** (PostgreSQL or SQLite) — daily `pg_dump`
2. **Agent state PVCs** — Velero or CSI snapshots
3. **CRD manifests** — `kubectl get` exports before upgrades
4. **Worker artifacts** — S3 sync or PVC snapshots

See [Backup and Recovery](backup-and-recovery.md) for the full guide.

### How do I upgrade KubeSynapse?

```bash
helm upgrade KubeSynapse oci://docker.io/kubesynapse/charts/kubesynapse \
  -n kubesynapse -f values-production.yaml
```

Review CRD changes and run smoke tests after upgrade. See [Operator Guide](operator-guide.md) for detailed procedures.

### How do I estimate cost?

Cost has two components:

1. **Infrastructure**: Kubernetes compute and storage. Use the capacity planning table in [Operator Guide](operator-guide.md) to estimate node requirements.
2. **LLM usage**: Token consumption per agent. Monitor `/api/v1/usage/summary` and set `AgentPolicy` token caps to control spend.

**Rule of thumb:** A team of 10 developers running 5 agents costs approximately $200-500/month in infrastructure (3-5 nodes on cloud) plus LLM provider charges.

---

## Community and Support

### How do I get help?

- **GitHub Issues**: Bug reports and feature requests
- **Pull Requests**: Proposed fixes, docs updates, and feature work
- **Email**: Private inquiries via `team@kubesynapse.ai`

### How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md). Good first issues are tagged `good first issue` and are designed to be completable in 1-4 hours.

### What is the license?

Apache License 2.0. See [LICENSE](../LICENSE).

### Is KubeSynapse going to be a CNCF project?

There is a roadmap item to submit KubeSynapse to the CNCF Sandbox. No timeline is committed yet. See [ROADMAP.md](../ROADMAP.md).

### Where can I find video tutorials?

See [docs/videos.md](videos.md) for a planned 5-video series with scripts and visual assets.

---

**Last Updated:** April 27, 2026  
**Platform Version:** 1.0.0
