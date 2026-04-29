# Contributing to KubeSynapse

Thank you for your interest in contributing to KubeSynapse! This guide covers everything you need to get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Environment](#development-environment)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Issue Tracking](#issue-tracking)
- [Community](#community)

## Code of Conduct

All contributors must follow our [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful, be constructive, and help us build a welcoming community.

## Getting Started

### Prerequisites

- Python 3.11+ with `pip`
- Node.js 20+ with `npm`
- Kubernetes cluster (Kind, Minikube, or Docker Desktop)
- Helm 3.12+
- Docker or Podman

### Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/<your-username>/KubeSynapse.git
cd KubeSynapse
git remote add upstream https://github.com/kubesynapse/kubesynapse.git
```

### Branch Strategy

- `main` — Stable, release-ready code
- `preprod` — Integration branch for upcoming release
- Feature branches: `feat/<description>`, `fix/<description>`, `docs/<description>`

```bash
git checkout -b feat/my-feature preprod
```

## Development Environment

### Python Services

```bash
# Install per-service dependencies
pip install -r operator/requirements.txt
pip install -r api-gateway/requirements.txt
pip install -r opencode-runtime/requirements.txt

# Install dev tooling
pip install ruff mypy pytest pytest-cov pytest-asyncio bandit
```

### Web UI

```bash
cd web-ui
npm install
npm run dev    # Start dev server at http://localhost:5173
```

### Pi Runtime

```bash
cd pi-runtime
npm install    # Install Pi runtime dev dependencies
```

### Local Kind Cluster (for integration testing)

```bash
kind create cluster --config kind-cluster-config.yaml
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
helm install KubeSynapse ./charts/kubesynapse -n kubesynapse --create-namespace
```

## Code Standards

### Python

- **Formatting**: [Ruff](https://docs.astral.sh/ruff/) with project config (`pyproject.toml`)
- **Type checking**: `mypy --strict` (target: zero errors)
- **Line length**: 120 characters
- **Target Python**: 3.11+
- **Docstrings**: Google-style for public APIs
- **Security**: Bandit scan must return zero HIGH/CRITICAL issues

```bash
# Run all checks
ruff check api-gateway/ operator/ opencode-runtime/
ruff format --check api-gateway/ operator/ opencode-runtime/
mypy api-gateway/ operator/ opencode-runtime/
bandit -r api-gateway/ operator/
```

### TypeScript / React

- **Formatting**: ESLint + Prettier (project config)
- **Components**: Functional components with hooks
- **Styling**: Tailwind CSS v4
- **Accessibility**: WCAG 2.1 AA minimum

```bash
cd web-ui
npm run lint
npm run build    # Must pass with zero errors before PR
```

### Helm Charts

```bash
helm lint charts/kubesynapse --strict
helm template KubeSynapse charts/kubesynapse --debug
```

### YAML / CRD Naming Convention

All Kubernetes CRD specifications and example YAML files **must use camelCase** for field names.
This aligns with the Kubernetes API conventions and ensures consistent developer experience
across `kubectl`, CRD schemas, and OpenAPI documentation.

**Correct (camelCase):**
```yaml
spec:
  systemPrompt: "You are an assistant"
  runtimeKind: opencode
  storageSize: 1Gi
  enableGVisor: false
  mcpConnections: []
```

**Incorrect (snake_case):**
```yaml
spec:
  system_prompt: "You are an assistant"    # Wrong
  runtime_kind: opencode                   # Wrong
  storage_size: 1Gi                        # Wrong
  enable_gvisor: false                     # Wrong
  mcp_connections: []                      # Wrong
```

Run the validation script before submitting a PR:
```bash
bash scripts/validate-crd-yaml.sh --strict
```

## Testing

### Running Tests

```bash
# Operator unit tests
cd operator && pytest tests/ -v

# API Gateway tests
cd api-gateway && pytest tests/ -v --cov=. --cov-report=term-missing

# OpenCode Runtime tests
cd opencode-runtime && pytest tests/ -v --cov=. --cov-report=term-missing

# Frontend tests
cd web-ui && npm run test
```

### Test Requirements

- New features must include tests
- Bug fixes should include a regression test
- Smoke tests for all API endpoints
- Test coverage should not decrease

## Pull Request Process

1. **Keep it focused**: One PR = one feature/fix. No mega-PRs.
2. **Write a clear description**: What, why, how tested.
3. **Link issues**: Reference related issues with `Closes #123`.
4. **Check the boxes**: Our PR template has a pre-submit checklist.
5. **Pass CI**: All lint, test, and build checks must pass.
6. **Sign-off**: Use `git commit -s` for DCO compliance.

### PR Review Expectations

- Maintainers review within 5 business days
- Address all review feedback
- Squash commits before merge (maintainer will handle this)
- Once approved, a maintainer will merge

### Commit Style

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(api-gateway): add agent CRUD endpoints
fix(operator): handle namespace deletion gracefully
docs(contributing): add PR process documentation
chore(deps): bump fastapi to 0.110.0
```

## Issue Tracking

- **Bug reports**: Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md)
- **Feature requests**: Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
- **Good First Issues**: See [Good First Issue template](.github/ISSUE_TEMPLATE/good_first_issue.md) — tagged with `good first issue` label
- **Security vulnerabilities**: See [SECURITY.md](SECURITY.md) — do NOT open public issues

### Good First Issue Criteria

Issues tagged `good first issue` meet these criteria:
- Self-contained task (≤ 100 lines of code changed)
- Clear acceptance criteria with a checklist
- Estimated effort: 1-4 hours for a first-time contributor
- Well-defined entry points (specific files, functions)
- Mentoring available from a maintainer
- Not blocking a release or critical path

To claim a Good First Issue, comment `/assign` on the issue. A maintainer will assign it to you within 24 hours.

## Repository Structure

| Area | Description |
|------|-------------|
| `operator/` | Kubernetes operator (Kopf-based) — reconciles CRDs into running pods |
| `api-gateway/` | FastAPI gateway — REST API, A2A endpoints, authentication |
| `opencode-runtime/` | OpenCode runtime — FastAPI wrapper around opencode serve |
| `pi-runtime/` | Pi agent runtime bridge (Node.js HTTP bridge for Pi RPC mode) |
| `web-ui/` | React 18 + Vite + Tailwind CSS v4 console |
| `mcp-sidecars/` | 10 MCP tool sidecar container images |
| `charts/kubesynapse/` | Helm chart for full-stack deployment |
| `docs/` | Architecture, deployment, and operations guides |
| `scripts/` | Automation scripts (demo, release, etc.) |
| `catalog/` | Community agent and workflow catalog |
| `cli/` | `agentctl` CLI tool |

## Community

- **GitHub Discussions**: [github.com/kubesynapse/kubesynapse/discussions](https://github.com/kubesynapse/kubesynapse/discussions)
- **Roadmap**: [ROADMAP.md](ROADMAP.md)
- **Maintainers**: [MAINTAINERS.md](MAINTAINERS.md)

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
