# Build a DevOps Agent in 5 Minutes with KubeSynth

**Published:** April 2026 | **Author:** KubeSynth Team

---

In this tutorial, you'll deploy a fully autonomous DevOps agent on your Kubernetes cluster that can diagnose failed pods, read logs, and propose fixes — all governed by policy and with human-in-the-loop approval for destructive actions.

## Prerequisites

- A Kubernetes cluster (Kind, Minikube, or any managed K8s)
- Helm 3.12+
- `kubectl` configured for your cluster
- 5 minutes

## Step 1: Install KubeSynth (60 seconds)

```bash
helm repo add kubesynth https://ykbytes.github.io/kubemininions/charts
helm repo update

helm install kubesynth kubesynth/kubesynth \
  --namespace kubesynth \
  --create-namespace \
  --set operator.image.repository=ghcr.io/ykbytes/kubesynth-operator \
  --set apiGateway.image.repository=ghcr.io/ykbytes/kubesynth-api-gateway \
  --set litellm.enabled=true \
  --set litellm.apiKey.openai=$OPENAI_API_KEY

# Wait for all pods
kubectl wait --for=condition=Ready pods --all -n kubesynth --timeout=120s
```

Verify the installation:

```bash
kubectl get pods -n kubesynth
# NAME                              READY   STATUS    RESTARTS   AGE
# kubesynth-api-gateway-xxx         1/1     Running   0          30s
# kubesynth-operator-xxx            1/1     Running   0          30s
# kubesynth-postgresql-0            1/1     Running   0          30s
# kubesynth-litellm-xxx             1/1     Running   0          30s
```

## Step 2: Define the Agent Policy (30 seconds)

Create a policy that allows kubectl operations but requires approval for deletes:

```yaml
# deploy/devops-agent-policy.yaml
apiVersion: agents.kubesynth.ai/v1
kind: AgentPolicy
metadata:
  name: devops-agent-policy
  namespace: kubesynth
spec:
  maxTokensPerRequest: 4096
  maxDailyCost: 2.00
  allowedTools:
    - kubectl-get
    - kubectl-describe
    - kubectl-logs
    - kubectl-delete
    - helm-list
  requireApproval:
    - kubectl-delete
  llmModel: gpt-4o-mini
  systemPrompt: |
    You are a DevOps agent running on Kubernetes. You can diagnose pod issues,
    read logs, and propose fixes. Always explain your reasoning before taking action.
    Destructive actions (like deleting pods) require explicit approval.
```

Apply it:

```bash
kubectl apply -f deploy/devops-agent-policy.yaml
```

## Step 3: Deploy the Agent (30 seconds)

```yaml
# deploy/devops-agent.yaml
apiVersion: agents.kubesynth.ai/v1
kind: AIAgent
metadata:
  name: devops-bot
  namespace: kubesynth
spec:
  policyRef: devops-agent-policy
  replicas: 1
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
  storage:
    size: 1Gi
  config:
    contextWindow: 8192
    sessionTimeout: 3600
```

Apply it:

```bash
kubectl apply -f deploy/devops-agent.yaml

# Watch the agent come alive
kubectl get statefulset -n kubesynth
# NAME          READY   AGE
# devops-bot    1/1     10s

kubectl get pods -n kubesynth -l app=kubesynth-agent,agent=devops-bot
# NAME            READY   STATUS    RESTARTS   AGE
# devops-bot-0    1/1     Running   0          12s
```

## Step 4: Run Your First Workflow (2 minutes)

Define a workflow that asks the agent to investigate a namespace:

```yaml
# deploy/diagnose-workflow.yaml
apiVersion: agents.kubesynth.ai/v1
kind: AgentWorkflow
metadata:
  name: diagnose-default-ns
  namespace: kubesynth
spec:
  agent: devops-bot
  steps:
    - name: check-pods
      action: kubectl-get
      params:
        command: "get pods -n default -o wide"
    - name: check-events
      action: kubectl-get
      params:
        command: "get events -n default --sort-by='.lastTimestamp' | tail -20"
    - name: diagnose
      action: llm-analyze
      dependsOn: [check-pods, check-events]
      params:
        prompt: |
          Given the pod list and recent events above, identify any issues.
          For each issue found, explain:
          1. What is wrong
          2. Root cause
          3. Recommended fix
          4. Whether the fix requires approval
  retryPolicy:
    maxRetries: 2
    backoff: exponential
```

Apply and watch:

```bash
kubectl apply -f deploy/diagnose-workflow.yaml

# Watch the workflow execute
kubectl get agentworkflow -n kubesynth diagnose-default-ns -w
# NAME                   STATUS     STEPS   AGE
# diagnose-default-ns    Running    1/3     5s
# diagnose-default-ns    Running    2/3     15s
# diagnose-default-ns    Running    3/3     25s
# diagnose-default-ns    Completed  3/3     35s
```

Get the results:

```bash
kubectl describe agentworkflow -n kubesynth diagnose-default-ns
# ...
# Status:
#   Steps:
#     diagnose:
#       Output: |
#         No issues found in default namespace.
#         All pods are running and healthy.
#         No recent error events detected.
```

## Step 5: Approve a Destructive Action

If the agent identifies an issue that requires `kubectl-delete`, it will create an `AgentApproval` CRD:

```bash
kubectl get agentapprovals -n kubesynth
# NAME                       STATUS    AGE
# delete-stuck-pod-abc123    Pending   10s

# Review and approve
kubectl describe agentapproval -n kubesynth delete-stuck-pod-abc123
# ...
# Spec:
#   Reason: "Pod stuck in CrashLoopBackOff for 30+ minutes. Restarting may resolve."
#   Action: kubectl-delete pod stuck-pod -n default

# Approve it
kubectl patch agentapproval -n kubesynth delete-stuck-pod-abc123 \
  --type merge \
  -p '{"spec":{"decision":"approved","comment":"Approved. Deleting stuck pod."}}'

# The agent receives the approval and proceeds
```

## What Just Happened

In 5 minutes, you:

1. **Deployed the full KubeSynth stack** — API gateway, operator, LiteLLM, PostgreSQL, Redis, NATS, Qdrant
2. **Defined governance policy** — token limits, cost limits, tool whitelist, approval gates
3. **Provisioned a stateful agent** — StatefulSet with PVC, stable DNS, graceful lifecycle
4. **Ran a multi-step workflow** — DAG execution with dependencies, retries, and exponential backoff
5. **Exercised the approval system** — human-in-the-loop gate for destructive actions

All without writing a single line of agent code. Just Kubernetes manifests.

## Next Steps

- [Deploy a multi-agent workflow](../walkthrough.md) with two agents collaborating
- [Set up Grafana dashboards](../architecture-overview.md#observability) to monitor agent health
- [Add custom tools](../operator-guide.md#custom-tools) to your agent policy
- [Explore the API reference](../api-reference.md) for programmatic access

## Bonus: One-Liner via CLI

```bash
kubesynth agent create devops-bot \
  --policy devops-agent-policy \
  --model gpt-4o-mini \
  --tools kubectl-get,kubectl-describe,kubectl-logs \
  --storage 1Gi

kubesynth workflow run diagnose-default-ns \
  --agent devops-bot \
  --steps check-pods,check-events,diagnose
```

---

**KubeSynth** — Because your agents deserve Kubernetes.
