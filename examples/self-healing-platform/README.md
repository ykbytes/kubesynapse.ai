# Self-Healing Platform

**Five AI agents** collaborate to detect, triage, investigate, remediate,
and postmortem a production incident — with a human approval gate before
any fix is applied.

This is KubeSynapse at its most powerful: multi-agent, multi-step, HITL,
and fully observable.

## Architecture

```
platform-monitor ──► incident-triage ──► forensics-collector
                                              │
                    ┌─────────────────────────┘
                    ▼
            remediation-planner
                    │
              ╔═════╧═════╗
              ║ HITL GATE ║  ← Human must approve before execution
              ╚═════╤═════╝
                    ▼
          remediation-executor
                    │
                    ▼
           postmortem-writer
```

| Agent | Role | MCP |
|-------|------|-----|
| `platform-monitor` | Detects anomalies from mock metrics | code-exec |
| `incident-triage` | Classifies severity, opens incident | code-exec |
| `forensics-collector` | Gathers logs, metrics, pod events | code-exec |
| `remediation-planner` | Designs fix, estimates impact | code-exec |
| `remediation-executor` | Applies approved fix | code-exec |
| `postmortem-writer` | Full timeline + RCA + action items | code-exec |

## Workflow

```
1. detect-anomaly     →  alert.json
2. triage-incident    →  incident.json
3. collect-forensics  →  forensics-report.json
4. plan-remediation   →  remediation-plan.yaml
5. ⏸️ approval-gate    →  AgentApproval CR (HUMAN REQUIRED)
6. execute-remediation →  execution-result.json
7. write-postmortem   →  postmortem-INC-2026-001.md
```

## Sample Data (Built-In)

Fake production data simulating a real incident:
- Prometheus metrics showing error rate spike on `payment-api`
- Pod events showing OOMKill on `payment-worker-3`
- Mock application logs showing cascading timeouts
- Infrastructure context (services, namespaces, owners)

## Quick Deploy

```powershell
Set-Location ./examples/self-healing-platform
pwsh ./deploy.ps1
```

## Trigger

```bash
agentctl workflows trigger self-healing-incident
```

## The Approval Gate

After `plan-remediation` completes, the workflow pauses and creates an
`AgentApproval` CR. A human must review the proposed remediation plan
and approve it before execution proceeds.

```bash
# List pending approvals
agentctl runs approvals

# Approve
agentctl runs approve <approval-name> --reason "Plan looks good, proceed"
```

From the Web UI: **Intelligence → Observatory** shows the full execution
timeline with per-step LLM calls and tool invocations.
