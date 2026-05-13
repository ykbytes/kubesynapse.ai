# Deployment README

This directory contains the public deployment-facing documentation that remains after pruning local-only helpers and scratch files.

## What is here

### `tests/test_production_readiness.py`

Use this for automated production-readiness validation from the repository root.

### `deploy/values.*.yaml`

Use these to choose the deployment mode you actually want:

- `deploy/values.cluster.example.yaml` for published-image installs
- `deploy/values.local-images.example.yaml` for local image development
- `deploy/values.google-oidc.example.yaml` as a safe managed sign-in overlay template

## Current deployment paths

## 1. Deploy published images

From the repository root:

```bash
cp ./deploy/values.cluster.example.yaml ./deploy/values.cluster.yaml
# Edit deploy/values.cluster.yaml before installing.

helm upgrade --install kubesynapse ./charts/kubesynapse \
  --namespace kubesynapse \
  --create-namespace \
  -f ./deploy/values.cluster.yaml
```

This is the supported public install path when you want to use the checked-in published image references.

## 2. Build locally, then deploy

Build the core platform images and bundled MCP sidecars:

```bash
make docker-build REGISTRY=localhost/kubesynapse VERSION=dev CONTAINER_CLI=docker
```

Then deploy with a values file that points at your registry.

For the current repeatable Kind path on Windows, prefer:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File ./scripts/deploy-kind.ps1 `
  -ClusterName kubesynapse-dev `
  -Namespace kubesynapse `
  -ReleaseName kubesynapse `
  -AdminPassword "KubesynapseAdmin9!"
```

That helper builds and loads the local images, applies
`deploy/values.local-images.example.yaml` plus `deploy/values.kind.quickstart.yaml`,
injects `catalog/skills-catalog.json`, reconciles the persisted PostgreSQL password on
repeat upgrades, and restarts the core deployments so unchanged `:dev` image tags are
actually picked up.

## 3. Configure the environment-specific overlay

For local image builds, start from `deploy/values.local-images.example.yaml` and adjust the registry coordinates if your cluster does not reach `localhost/kubesynapse/*:dev` directly.

For single-node Kind clusters, also layer in `deploy/values.kind.quickstart.yaml`.
It disables optional friction points such as the shared MCP hub, PodDisruptionBudgets,
and NetworkPolicies so the local cluster converges more reliably.

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

If you are exercising the observability stack, apply `examples/observability-demo-fire.yaml`, verify the created resources reconcile, and inspect the UI and gateway responses described in `docs/observability-explained.md`.

## Current operational assumptions

These are the assumptions that match the codebase now:

- the supported in-tree runtimes are OpenCode, Pi, and Mistral Vibe
- PostgreSQL backs gateway auth and session state
- workflows and evals use worker Jobs plus artifact PVC references
- observability CRDs are part of the chart
- a collector DaemonSet path exists in the platform chart
- the MCP model includes both per-agent sidecars and shared MCP hub connections

## Recommended operator sequence

1. Run the automated readiness checks.
2. Choose the correct values file for your environment.
3. Use `helm upgrade --install` with the values file that matches your environment.
4. Verify pods, gateway health, and UI availability.
5. If relevant, apply the observability example resources and inspect the UI.

## Related docs

- `INSTALL.md`
- `docs/architecture-overview.md`
- `docs/walkthrough.md`
- `docs/observability-explained.md`
- `web-ui/README.md`
- `cli/README.md`
