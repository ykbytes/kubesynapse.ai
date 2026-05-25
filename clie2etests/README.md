# CLI E2E Tests

This folder contains a practical end-to-end test suite for `agentctl` against a local KubeSynapse deployment.

It covers:
- auth and profile setup
- policy apply/list/show/delete
- agent apply/list/show/invoke/logs
- workflow apply/list/show/trigger/status/logs
- approvals list/approve
- webhook create/show/list/dispatch/trigger-show/delete
- admin user create/update/delete
- agent credentials git/github set/show/delete
- observatory health/metrics/traces/export
- providers list/show/models/health

## Assumptions

- Your cluster context is `kind-kubesynapse-dev`
- The KubeSynapse namespace is `kubesynapse`
- The CLI namespace is `default`
- Local admin login is:
  - username: `admin`
  - password: `YourAdminPasswordHere`

## Quick Start

Run from the repo root:

```powershell
.\clie2etests\run-all.ps1
```

Or run step by step:

```powershell
.\clie2etests\01-setup.ps1 -StartPortForward
.\clie2etests\02-deploy.ps1
.\clie2etests\03-exercise.ps1
.\clie2etests\04-cleanup.ps1
```

## Files

- `common.ps1`: shared helper functions
- `01-setup.ps1`: port-forward, profile config, login, health checks
- `02-deploy.ps1`: apply policy, agents, workflow, webhook
- `03-exercise.ps1`: run the CLI coverage suite
- `04-cleanup.ps1`: remove the created resources
- `run-all.ps1`: orchestrator
- `resources/`: manifests and sample payloads

## Notes

- `AgentPolicy` apply/delete is covered via CLI support added in this branch.
- Provider discovery depends on cluster secret wiring. The CLI paths are fixed, but the cluster may still report providers as disconnected if provider auth is stored only in the legacy shared secret.
