# KubeSynapse Incident Scripts

A small, dependency-free set of helpers for end-to-end demoing of the Incidents
flow: firing an Alertmanager-style alert, triggering a workflow that picks up
the incident, and producing a Markdown (or HTML) report for handoff.

All scripts auto-resolve the gateway token from the `kubesynapse-llm-api-keys`
(or `kubesynapse-shared-auth`) secret when `KUBESYNAPSE_API_TOKEN` is not
already in the environment, and they start a `kubectl port-forward` to the
API gateway if no listener is present on `localhost:8080`.

## Scripts

| Script | Purpose |
| --- | --- |
| `fire-alertmanager-alert.{ps1,sh}` | Sends an Alertmanager v4 webhook to `/api/v1/webhooks/alertmanager` to create a firing (or resolved) incident. |
| `trigger-workflow-and-link.{ps1,sh}` | Triggers an `AgentWorkflow` and patches the incident to record the `workflow_run_id` for the Observatory deep link. |
| `generate-incident-report.{ps1,sh}` | Fetches the incident + timeline + linked run trace/logs and writes a Markdown report (`--format html` to also render HTML). |

## Quick Start

```powershell
# 1. Fire an example alert (creates a "DemoHighLatency" warning incident)
.\scripts\incidents\fire-alertmanager-alert.ps1

# 2. Run the default workflow (secure-incident-mesh) and link the run
.\scripts\incidents\trigger-workflow-and-link.ps1

# 3. Generate a Markdown + HTML report
.\scripts\incidents\generate-incident-report.ps1 -Format both
```

The PowerShell and Bash variants share the same names and behavior, so the
same recipe works on both Windows (PowerShell 7+) and Linux/macOS shells.

## Arguments

`fire-alertmanager-alert.{ps1,sh}`

| Flag | Default | Notes |
| --- | --- | --- |
| `--namespace` / `-Namespace` | `default` | K8s namespace to attach the incident to. |
| `--severity` / `-Severity` | `warning` | One of `critical`, `warning`, `info`. |
| `--alertname` / `-Alertname` | `DemoHighLatency` | Alertmanager label. |
| `--service` / `-Service` | `checkout-api` | Free-form service label. |
| `--environment` / `-Environment` | `demo` | Free-form env label. |
| `--summary` / `-Summary` | _(see script)_ | Maps to the Alertmanager `summary` annotation. |
| `--description` / `-Description` | _(see script)_ | Maps to the Alertmanager `description` annotation. |
| `--resolve` / `-Resolve` | _off_ | Sends a `resolved` status instead of `firing`. |

`trigger-workflow-and-link.{ps1,sh}`

| Flag | Default | Notes |
| --- | --- | --- |
| `--namespace` / `-Namespace` | `default` | K8s namespace of both incident and workflow. |
| `--incident-name` / `-IncidentName` | _last-fired_ | Incident to patch. Defaults to the most recent run of `fire-…` via `/tmp/kubesynapse-last-incident.txt` (POSIX) or `%TEMP%\kubesynapse-last-incident.txt` (Windows). |
| `--workflow-name` / `-WorkflowName` | `secure-incident-mesh` | `AgentWorkflow` to trigger. |
| `--input` / `-WorkflowInput` | _(see script)_ | Replaces `spec.input` on the workflow before the operator reconciles. |
| `--wait` / `-WaitSeconds` | `30` | How long to wait for the operator to publish a `runId`. |

`generate-incident-report.{ps1,sh}`

| Flag | Default | Notes |
| --- | --- | --- |
| `--namespace` / `-Namespace` | `default` | K8s namespace. |
| `--incident-name` / `-IncidentName` | _last-fired_ | See above. |
| `--output-dir` / `-OutputDir` | `./reports` | Where to write the report. |
| `--format` / `-Format` | `md` | `md`, `html`, or `both`. |

## Requirements

- `kubectl` and `jq`/PowerShell reachable on `PATH`
- The shared token secret must be installed in the `kubesynapse` namespace
  (default Helm install creates `kubesynapse-llm-api-keys` with
  `API_GATEWAY_SHARED_TOKEN`)
- For HTML output the PowerShell variant requires the optional `System.Web`
  assembly (always available on Windows PowerShell 5+ and PowerShell 7+)
