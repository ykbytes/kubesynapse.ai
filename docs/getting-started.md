# Getting Started with KubeSynapse

**Time to complete:** 10-15 minutes  
**Who is this for:** Platform engineers, DevOps teams, and AI developers who want to run the current KubeSynapse stack and deploy a real agent.

---

## What This Guide Covers

1. Install a local KubeSynapse cluster with the repo-supported Kind helper.
2. Open the web console and verify the gateway.
3. Deploy a real sample `AIAgent` and `AgentPolicy` from `examples/`.
4. Invoke the agent from the UI or `agentctl`.
5. Optionally run the stronger multi-agent Context7 workflow demo.

---

## Prerequisites

| Tool | Minimum Version | Verify Command |
|------|-----------------|----------------|
| Docker | Recent | `docker version` |
| Kind | Recent | `kind version` |
| Helm | 3.12+ | `helm version` |
| kubectl | 1.25+ | `kubectl version --client` |
| PowerShell | 7+ | `pwsh --version` |

You also need credentials for at least one supported model provider before you can successfully invoke agents.

---

## Step 1: Install KubeSynapse On Kind

The most repeatable local install path in this repository is the checked-in PowerShell helper:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"
```

What it does:

- creates or reuses the `kind-kubesynapse-dev` cluster context
- builds local `:dev` images for the operator, API gateway, web UI, and OpenCode runtime
- loads the pinned LiteLLM image required by the chart
- applies `deploy/values.local-images.example.yaml` and `deploy/values.kind.quickstart.yaml`
- injects `catalog/skills-catalog.json` so the `Catalog > Skills` tab is populated
- prints the bootstrap admin credentials and useful port-forward commands

The main chart installs 12 CRDs, including agents, workflows, policies, approvals, tenants, MCP connections, webhook receivers, workflow triggers, and observability resources.

If you prefer a manual path, see:

- [`deploy/README.md`](../deploy/README.md)
- [`charts/kubesynapse/README.md`](../charts/kubesynapse/README.md)
- [`INSTALL.md`](../INSTALL.md)

---

## Step 2: Verify The Gateway And UI

Port-forward the gateway and console:

```bash
kubectl port-forward -n kubesynapse svc/kubesynapse-api-gateway 8080:8080
kubectl port-forward -n kubesynapse svc/kubesynapse-web-ui 3000:80
```

Verify the gateway health endpoint:

```bash
curl http://localhost:8080/api/v1/health
```

Then open the console:

- Web UI: `http://localhost:3000`
- API docs: `http://localhost:8080/api/v1/docs`

Sign in with the admin username and password printed by `scripts/deploy-kind.ps1`.

Before invoking agents, configure at least one provider credential in the Settings workspace or via chart-managed secrets.

---

## Step 3: Deploy Your First Agent

Use the checked-in sample resources:

```bash
kubectl apply -f examples/sample-policy.yaml
kubectl apply -f examples/sample-agent.yaml
```

Verify reconciliation:

```bash
kubectl get aiagents -n default
kubectl get pods -n default
```

These examples show the current shipped object model:

- `examples/sample-policy.yaml` configures guardrails and MCP policy on an `AgentPolicy`.
- `examples/sample-agent.yaml` creates an `AIAgent` with:
  - `spec.runtime.kind: opencode`
  - file-backed skills under `spec.skills.files`
  - a `policyRef`
  - PVC-backed workspace storage

---

## Step 4: Invoke The Agent

### Option A: Web UI

1. Open `http://localhost:3000`.
2. Go to **Chat Workbench**.
3. Select `research-assistant`.
4. Send a prompt.

### Option B: `agentctl`

Install the CLI from this repository:

```bash
python -m pip install -e ./cli
```

Log in and export the returned token:

```bash
agentctl --gateway http://localhost:8080 auth login -u admin -p "<your-password>"
export AGENT_GATEWAY_TOKEN="<token-from-login-output>"
```

On PowerShell:

```powershell
$env:AGENT_GATEWAY_TOKEN="<token-from-login-output>"
```

Invoke the sample agent:

```bash
agentctl --gateway http://localhost:8080 invoke research-assistant "Summarize what KubeSynapse does and why it is Kubernetes-native."
```

### Option C: Raw API

```bash
curl -X POST "http://localhost:8080/api/v1/agents/research-assistant/invoke?namespace=default" \
  -H "Authorization: Bearer <shared-token-or-access-token>" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize what KubeSynapse does and why it is Kubernetes-native."}'
```

---

## Step 5: Run The Best Multi-Agent Demos

Three showcase demos demonstrate KubeSynapse at increasing levels of complexity:

### Quick: Daily Standup Bot
3 agents produce a structured standup report from git history and Jira data.

```bash
kubectl apply -f examples/daily-standup-bot/project-context.yaml
kubectl apply -f examples/daily-standup-bot/agents.yaml
kubectl apply -f examples/daily-standup-bot/policy.yaml
kubectl apply -f examples/daily-standup-bot/workflow.yaml
agentctl workflows trigger daily-standup
```

### Intermediate: GDPR Compliance Auditor
3 agents scan code, classify PII risks, and generate a boardroom-ready compliance report.

```bash
kubectl apply -f examples/gdpr-compliance-auditor/project-context.yaml
kubectl apply -f examples/gdpr-compliance-auditor/agents.yaml
kubectl apply -f examples/gdpr-compliance-auditor/policy.yaml
kubectl apply -f examples/gdpr-compliance-auditor/workflow.yaml
agentctl workflows trigger gdpr-compliance-audit
```

### Advanced: Self-Healing Platform
5 agents run a full incident response pipeline — detect → triage → forensics → remediate (with human approval gate) → postmortem.

```bash
kubectl apply -f examples/self-healing-platform/project-context.yaml
kubectl apply -f examples/self-healing-platform/agents.yaml
kubectl apply -f examples/self-healing-platform/policy.yaml
kubectl apply -f examples/self-healing-platform/workflow.yaml
agentctl workflows trigger self-healing-incident
# The workflow pauses at the approval gate — a human must approve before execution continues
agentctl runs approve <approval-name> --reason "Plan looks correct — proceed"
```

What these demos show:
- Multi-agent collaboration with structured handoffs
- workspace file I/O across steps
- Human-in-the-loop approval gates
- Full Execution Observatory timeline inspection
- Each demo is self-contained — all sample data is embedded in the manifests

To inspect runs in the UI, open **Intelligence > Observatory**.

---

## Runtime Notes

KubeSynapse uses OpenCode as its production runtime:

- `opencode` — production runtime (recommended)
- `pi` — alpha, not recommended for production
- `mistral-vibe` — alpha, not recommended for production

`opencode` is the default runtime path used by the checked-in examples and local dev flows.

---

## Next Steps

| Goal | Resource |
|------|----------|
| Understand the current architecture | [`architecture-overview.md`](architecture-overview.md) |
| See the implementation walkthrough | [`walkthrough.md`](walkthrough.md) |
| Deploy with different overlays | [`../deploy/README.md`](../deploy/README.md) |
| Learn the runtime contract | [`runtime-api-spec.md`](runtime-api-spec.md) |
| Explore observability and traces | [`observability-explained.md`](observability-explained.md) |
| Troubleshoot install or runtime issues | [`troubleshooting.md`](troubleshooting.md) |
| Use the CLI effectively | [`../cli/README.md`](../cli/README.md) |

---

## Notes

- Workflow details primarily live in worker artifacts and logs; CRD status is summary-oriented.
- The API gateway is both the invoke edge and the backend for auth, memory, traces, webhooks, and UI metadata.
- For local Kind installs, `deploy/values.kind.quickstart.yaml` intentionally disables some optional components to keep the cluster lightweight.
