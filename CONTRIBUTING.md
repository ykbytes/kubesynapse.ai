# Contributing to KubeSynapse

Thanks for your interest in contributing! KubeSynapse is an Apache 2.0 open-source project that welcomes contributions of all kinds.

## Ways to contribute

- **Use it.** Run KubeSynapse and tell us what works and what doesn't.
- **Star & share.** Help others discover the project.
- **Report bugs.** Use the [bug report template](https://github.com/ykbytes/kubesynapse.ai/issues/new?template=bug_report.yml).
- **Request features.** Use the [feature request template](https://github.com/ykbytes/kubesynapse.ai/issues/new?template=feature_request.yml).
- **Improve docs.** Fix typos, add examples, write guides.
- **Write code.** Pick up a [`good first issue`](https://github.com/ykbytes/kubesynapse.ai/labels/good%20first%20issue) and submit a PR.

## Development setup

```bash
# Clone the repo
git clone https://github.com/ykbytes/kubesynapse.ai.git
cd kubesynapse.ai

# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -e api-gateway/[dev]
pip install -e operator/[dev]
pip install -e cli/[dev]
cd web-ui && npm install && cd ..
```

## Project structure

| Component | Directory | Language | Test command |
|-----------|-----------|----------|-------------|
| API Gateway | `api-gateway/` | Python (FastAPI) | `pytest tests/ -v` |
| Operator | `operator/` | Python (Kopf) | `pytest tests/ -v` |
| CLI | `cli/` | Python (Typer) | `pytest tests/ -v -q` |
| Web UI | `web-ui/` | TypeScript (React) | `npm run build` |
| Helm Chart | `charts/kubesynapse/` | YAML | `helm lint` |
| Runtimes | `opencode-runtime/` | Python | `pytest tests/ -v` |

## Code conventions

### Python
- **3.11+** minimum
- **Ruff** for linting and formatting (`ruff check . && ruff format .`)
- **mypy** for type checking (strict mode in `pyproject.toml`)
- **Prefer async** patterns in gateway routes (`httpx.AsyncClient`)
- **No unnecessary comments** — code should be self-documenting

### TypeScript / React
- **React 18** with functional components and hooks
- **Tailwind CSS v4** — utility-first, no custom CSS files
- **Radix UI** primitives for accessibility
- **Loading states** for every async operation
- **WAI-ARIA**: keyboard nav, focus management, screen reader labels

### YAML / Helm
- `values.yaml` is the configuration source of truth
- `values.schema.json` validates all values
- Never store secrets in `values.yaml` — use `external-secrets.yaml` or K8s Secrets

## Commit conventions

We use [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
feat(operator): add gVisor runtime class support
fix(gateway): handle streamed error responses safely  
docs(readme): add shell completion instructions
chore(deps): bump httpx to 0.28
```

Sign your commits:
```bash
git commit -s -m "feat: description"
```

## Before submitting a PR

1. **Run tests** for the components you changed
2. **Run linters**: `ruff check . && ruff format .` (Python), `npm run lint` (Web UI), `helm lint charts/kubesynapse/` (Helm)
3. **Update docs** if you changed behavior or APIs
4. **Check the PR template** — fill out all sections
5. **Keep PRs focused** — one concern per PR

## Local testing with Kind

```bash
# Create a Kind cluster
kind create cluster --name kubesynapse-dev

# Deploy the platform
pwsh ./scripts/deploy-kind.ps1 -ClusterName kubesynapse-dev -Namespace kubesynapse -AdminPassword "DevPass9!"

# Port-forward
kubectl port-forward svc/kubesynapse-api-gateway -n kubesynapse 8080:8080
kubectl port-forward svc/kubesynapse-web-ui -n kubesynapse 3000:80

# After code changes, rebuild and reload
docker build -t localhost/kubesynapse/kubesynapse-api-gateway:dev api-gateway/
kind load docker-image localhost/kubesynapse/kubesynapse-api-gateway:dev --name kubesynapse-dev
kubectl rollout restart deployment/kubesynapse-api-gateway -n kubesynapse
```

## Getting help

- [GitHub Discussions](https://github.com/ykbytes/kubesynapse.ai/discussions) — questions and ideas
- [GitHub Issues](https://github.com/ykbytes/kubesynapse.ai/issues) — bugs and features
- [Architecture docs](docs/architecture-overview.md) — how the system works
- [AGENTS.md](AGENTS.md) — repo-specific guidance for AI coding agents

## License

By contributing, you agree that your contributions will be licensed under the [Apache 2.0 License](LICENSE).
