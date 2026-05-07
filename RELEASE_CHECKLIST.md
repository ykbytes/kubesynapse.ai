# KubeSynapse Release Checklist

Use this checklist before tagging a new release.

---

## Build & Lint

- [ ] All component images build successfully (`make docker-build`)
- [ ] `helm lint --strict` passes for `./charts/kubesynapse`
- [ ] `ruff check` reports zero errors across Python services
- [ ] `mypy --strict` target status is documented in the component README
- [ ] `npm run build` produces zero TypeScript errors in `web-ui/`

## Tests

- [ ] Operator unit tests pass (`pytest operator/tests/ -v`)
- [ ] Gateway smoke tests pass (`pytest api-gateway/tests/test_smoke.py -v`)

## Versioning

- [ ] Version bumps applied in:
  - `charts/kubesynapse/Chart.yaml`
  - All `Dockerfile`s
  - `release-please-manifest.json`
  - Root `README.md`
- [ ] `CHANGELOG.md` updated with sprint changes

## Documentation

- [ ] All READMEs verified for accuracy and stale links
- [ ] Documentation cross-links verified (no 404s)

## Kind Smoke Test

- [ ] Create local Kind cluster
- [ ] Load images with `kind load docker-image`
- [ ] Deploy KubeSynapse via Helm
- [ ] Create an agent and invoke it
- [ ] Verify artifact APIs respond correctly

## Security

- [ ] `bandit` scan clean for Python services
- [ ] `pip-audit` clean (or accepted risks documented)
- [ ] `npm audit` clean in `web-ui/` (or accepted risks documented)

## Git & Release

- [ ] Git tag created and pushed
- [ ] Release notes drafted with migration notes

---

## Current Versions

| Component | Current Tag |
|-----------|-------------|
| Operator | `kubesynapse-operator:v2.1.0-run-intelligence` |
| API Gateway | `kubesynapse-api-gateway:v2.1.0-run-intelligence` |
| Web UI | `kubesynapse-web-ui:v2.1.0-run-intelligence` |
| Pi Runtime | `kubesynapse-pi-rt:v2.1.0-run-intelligence` |
| OpenCode Runtime | `kubesynapse-opencode-rt:v2.1.0-run-intelligence` |
| Mistral Vibe Runtime | `kubesynapse-vibe-rt:v2.1.0-run-intelligence` |
| LiteLLM | `litellm/litellm:v1.82.3-stable` |
