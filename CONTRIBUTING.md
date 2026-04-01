# Contributing to kubesynthai

Thank you for your interest in contributing to kubesynthai.

## Getting Started

1. Fork the repository
2. Create a feature branch from `main`
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/<your-username>/kubesynth.git
cd kubesynth

# Install Python dependencies (per service)
pip install -r operator/requirements.txt
pip install -r agent-runtime/requirements.txt
pip install -r api-gateway/requirements.txt

# Install web-ui dependencies
cd web-ui && npm install && cd ..

# Run tests
make test

# Run linting
make lint
```

## Code Standards

- Python code follows flake8 conventions (line length 120)
- TypeScript code uses the project ESLint config
- All Python services target Python 3.11+
- Helm charts should pass `helm lint`

## Pull Request Guidelines

- Keep PRs focused on a single concern
- Include tests for new functionality where practical
- Update documentation if your change affects user-facing behavior
- Ensure `make lint` and `make test` pass before submitting

## Repository Structure

See [README.md](README.md) for the full repository layout. Key areas:

| Area | What lives here |
|---|---|
| `operator/` | Kubernetes operator (Kopf-based) |
| `agent-runtime/` | LangGraph-based agent runtime |
| `goose-runtime/`, `codex-runtime/`, `opencode-runtime/` | Alternative runtime adapters |
| `api-gateway/` | FastAPI gateway |
| `web-ui/` | React + TypeScript console |
| `mcp-sidecars/` | 10 MCP tool sidecar images |
| `charts/` | Helm charts |
| `docs/` | Architecture and deployment docs |

## Reporting Issues

Use [GitHub Issues](https://github.com/kubesynthai/kubesynth/issues) to report bugs or request features. Include:

- Steps to reproduce
- Expected vs. actual behavior
- Kubernetes version and environment details (if applicable)

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
