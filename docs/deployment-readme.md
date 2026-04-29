# Deployment README

This directory contains the current deployment-facing documents and helper assets for KubeSynapse. The goal of this file is to point at the real entry points that exist in the repository today rather than older generic production prose.

## What is here

### `production-deployment-guide.md`

Use this for broader production planning, hardening, and rollout guidance.

### `deployment-checklist.yaml`

Use this as a deployment checklist during an actual install, upgrade, or validation pass.

### `tests/test_production_readiness.py`

Use this for automated production-readiness validation from the repository root.

### `deploy/values.*.yaml`

Use these to choose the deployment mode you actually want:

- `deploy/values.dockerhub.local.yaml` for published image deployment
- `deploy/values.cluster.example.yaml` for a more general cluster example
- `deploy/values.ai-sandbox.kind-local.yaml` for refreshing the live local Kind release
- `deploy/values.google-oidc.example.yaml` as a safe managed sign-in overlay template

### `scripts/deploy-ai-sandbox-kind.ps1`

Use this when you already have the `ai-sandbox` release in `ai-agent-sandbox` and only want to refresh images and chart-managed values without replaying a stale broad values file.

### `scripts/observability-smoke-test.ps1`

Use this to validate the observability path after deploying the new connector, target, policy, and report CRDs.

## Current deployment paths

## 1. Deploy published images

From the repository root:

```bash
helm upgrade --install KubeSynapse ./charts/kubesynapse \
  -f ./deploy/values.dockerhub.local.yaml
```

This is the fastest path when you want to use the checked-in published image references.

## 2. Build locally, then deploy

Build the core platform images and bundled MCP sidecars:

```bash
make docker-build REGISTRY=ghcr.io/your-org VERSION=latest CONTAINER_CLI=docker
```

Then deploy with a values file that points at your registry.

## 3. Refresh the live Kind sandbox release

Dry run first:

```powershell
pwsh -File ./scripts/deploy-ai-sandbox-kind.ps1 -DryRun
```

Apply the refresh:

```powershell
pwsh -File ./scripts/deploy-ai-sandbox-kind.ps1
```

This script wraps:

- `helm upgrade`
- `--reuse-values`
- `--server-side=true`
- `--force-conflicts`
- `-f deploy/values.ai-sandbox.kind-local.yaml`

That matters because it updates the existing local release with the current image references while avoiding a full reapplication of older environment-wide settings.

## Validation flow

## 1. Automated readiness checks

Run from the repository root:

```bash
python tests/test_production_readiness.py --verbose
```

Optional report output:

```bash
python tests/test_production_readiness.py --report deployment_report.json
```

## 2. Helm and code validation

Useful commands:

```bash
make helm-lint
make test
make lint
```

## 3. Local UI validation

For the web console:

```bash
cd web-ui
npm run build
```

## 4. Observability validation

If you are exercising the observability stack, apply the example resources and run the smoke path:

```powershell
kubectl apply -f .\examples\observability-demo-fire.yaml
pwsh -File .\scripts\observability-smoke-test.ps1
```

Also read `docs/observability-explained.md` for the intended resource flow.

## Current operational assumptions

These are the assumptions that match the codebase now:

- the supported runtime is OpenCode only
- PostgreSQL backs gateway auth and session state
- workflows and evals use worker Jobs plus artifact PVC references
- observability CRDs are part of the chart
- a collector DaemonSet path exists in the platform chart
- the MCP model includes both per-agent sidecars and shared MCP hub connections

## Recommended operator sequence

1. Run the automated readiness checks.
2. Choose the correct values file for your environment.
3. Use `helm upgrade --install` or the Kind refresh script.
4. Verify pods, gateway health, and UI availability.
5. If relevant, run the observability smoke test and inspect the UI.

## Related docs

- `INSTALL.md`
- `docs/architecture-overview.md`
- `docs/walkthrough.md`
- `docs/observability-explained.md`
- `web-ui/README.md`
- `cli/README.md`