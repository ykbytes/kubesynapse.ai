# Getting Started with KubeSynth

**Time to complete:** 5 minutes  
**Who is this for:** Platform engineers, DevOps teams, and AI developers who want to deploy their first agent on Kubernetes.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Step 1: Install KubeSynth via Helm OCI](#step-1-install-kubesynth-via-helm-oci)
- [Step 2: Port-Forward and Verify Health](#step-2-port-forward-and-verify-health)
- [Step 3: Create Your First Agent](#step-3-create-your-first-agent)
- [Step 4: Chat with the Agent](#step-4-chat-with-the-agent)
- [Step 5: Delegate to Another Agent via A2A](#step-5-delegate-to-another-agent-via-a2a)
- [Next Steps](#next-steps)

---

## Prerequisites

| Tool | Minimum Version | Verify Command |
|------|-----------------|----------------|
| Kubernetes | 1.25+ | `kubectl version --short` |
| Helm | 3.12+ | `helm version` |
| kubectl | 1.25+ | `kubectl version --client` |
| LLM API Key | Any supported provider | OpenAI, Anthropic, Azure, etc. |

You also need a running Kubernetes cluster. For local testing, use [Kind](https://kind.sigs.k8s.io/):

```bash
kind create cluster --name kubesynth
```

---

## Step 1: Install KubeSynth via Helm OCI

One command installs the entire platform:

```bash
helm install kubesynth oci://docker.io/kubesynth/charts/kubesynth \
  --namespace kubesynth --create-namespace \
  --set platformSecrets.native.openaiApiKey="sk-..." \
  --set litellm.masterKey="your-secure-litellm-key"
```

**What this does:**
- Deploys the API Gateway, Operator, Web UI, LiteLLM, Redis, Qdrant, PostgreSQL, and NATS
- Installs 11 CRDs into your cluster
- Creates the `kubesynth` namespace

**Expected output:**

```text
NAME: kubesynth
LAST DEPLOYED: Mon Apr 27 10:00:00 2026
NAMESPACE: kubesynth
STATUS: deployed
REVISION: 1
```

Wait for all pods to become ready:

```bash
kubectl wait --for=condition=ready pod --all -n kubesynth --timeout=300s
```

---

## Step 2: Port-Forward and Verify Health

Forward the API Gateway and Web UI to your local machine:

```bash
# Terminal 1 — API Gateway
kubectl port-forward -n kubesynth svc/kubesynth-api-gateway 8080:8080

# Terminal 2 — Web UI
kubectl port-forward -n kubesynth svc/kubesynth-web-ui 3000:80
```

Verify the gateway is healthy:

```bash
curl http://localhost:8080/api/health
```

**Expected response:**

```json
{
  "status": "healthy",
  "gateway": "kubesynth",
  "auth_mode": "shared_token",
  "browser_auth_enabled": true,
  "local_auth_enabled": true,
  "shared_token_enabled": true
}
```

Open the Web UI at [http://localhost:3000](http://localhost:3000).

---

## Step 3: Create Your First Agent

### Option A: Using `agentctl` CLI

```bash
# Install the CLI
pip install kubesynth-cli

# Create an agent
agentctl agent create \
  --name onboarding-bot \
  --namespace default \
  --model gpt-4o \
  --system-prompt "You are a friendly DevOps onboarding assistant."
```

### Option B: Using `kubectl` and YAML

Save this as `first-agent.yaml`:

```yaml
apiVersion: kubesynth.ai/v1alpha1
kind: AIAgent
metadata:
  name: onboarding-bot
  namespace: default
spec:
  runtimeKind: opencode
  systemPrompt: "You are a friendly DevOps onboarding assistant."
  model: gpt-4o
  storageSize: 1Gi
```

Apply it:

```bash
kubectl apply -f first-agent.yaml
```

**Verify the agent is running:**

```bash
kubectl get aiagent -n default
kubectl get pods -n default -l app.kubernetes.io/name=onboarding-bot
```

---

## Step 4: Chat with the Agent

### Via CLI

```bash
agentctl agent invoke onboarding-bot \
  --namespace default \
  --prompt "How do I rotate a Kubernetes secret?"
```

**Expected response:**

```json
{
  "response": "To rotate a Kubernetes secret, create a new secret with updated data...",
  "status": "completed",
  "thread_id": "abc123..."
}
```

### Via Web UI

1. Navigate to [http://localhost:3000](http://localhost:3000)
2. Click **Chat Workbench**
3. Select `onboarding-bot` from the agent dropdown
4. Type your message and press Enter

### Via cURL

```bash
curl -X POST http://localhost:8080/api/v1/agents/onboarding-bot/invoke \
  -H "Content-Type: application/json" \
  -d '{"prompt": "How do I rotate a Kubernetes secret?"}'
```

---

## Step 5: Delegate to Another Agent via A2A

KubeSynth supports native A2A (Agent-to-Agent) delegation. Create a second agent that the first can call.

### 1. Create a specialist agent

```yaml
apiVersion: kubesynth.ai/v1alpha1
kind: AIAgent
metadata:
  name: security-specialist
  namespace: default
spec:
  runtimeKind: opencode
  systemPrompt: "You are a security expert focused on secret rotation and PKI."
  model: gpt-4o
  storageSize: 1Gi
```

```bash
kubectl apply -f security-specialist.yaml
```

### 2. Allow delegation between agents

Create an `AgentPolicy` that allows A2A targeting:

```yaml
apiVersion: kubesynth.ai/v1alpha1
kind: AgentPolicy
metadata:
  name: a2a-delegation-policy
  namespace: default
spec:
  allowedModels:
    - gpt-4o
  a2a:
    allowedTargets:
      - name: security-specialist
        namespace: default
```

```bash
kubectl apply -f a2a-policy.yaml
```

### 3. Delegate via chat

In the Web UI or CLI, mention the specialist with `@`:

```text
@security-specialist How do I rotate a TLS certificate in cert-manager?
```

The gateway routes the request to `security-specialist`, which processes it and returns the answer to the original thread.

**What happens under the hood:**
- Gateway validates the caller against `allowedTargets`
- Creates an A2A JSON-RPC task record
- Forwards the prompt to the target agent's runtime
- Streams or returns the response to the caller

---

## Next Steps

| Goal | Resource |
|------|----------|
| Deploy to production | [Production Deployment Guide](production-deployment-guide.md) |
| Understand architecture | [Architecture Overview](architecture.md) |
| Configure auth, secrets, policies | [Configuration Reference](configuration-reference.md) |
| Monitor and alert | [Operator Guide](operator-guide.md) |
| Troubleshoot issues | [Troubleshooting](troubleshooting.md) |
| Join the community | [Community](community.md) |

---

**Last Updated:** April 27, 2026  
**Platform Version:** 1.0.0
