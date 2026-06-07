# KubeSynapse Agent Guide

This file gives AI coding agents the minimum repo-specific context needed to work safely. Link to the referenced docs for detail instead of duplicating them here.

## Start Here

- Product and current architecture: [README.md](README.md), [docs/architecture-overview.md](docs/architecture-overview.md), [docs/architecture.md](docs/architecture.md)
- Deployment and chart behavior: [charts/kubesynapse/README.md](charts/kubesynapse/README.md), [charts/kubesynapse/values.yaml](charts/kubesynapse/values.yaml), [charts/kubesynapse/values.schema.json](charts/kubesynapse/values.schema.json), [docs/configuration-reference.md](docs/configuration-reference.md), [deploy/README.md](deploy/README.md)
- Component docs: [api-gateway/README.md](api-gateway/README.md), [operator/README.md](operator/README.md), [web-ui/README.md](web-ui/README.md), [opencode-runtime/README.md](opencode-runtime/README.md), [mcp-sidecars/README.md](mcp-sidecars/README.md), [cli/README.md](cli/README.md)
- Smoke test scripts: [scripts/incidents/README.md](scripts/incidents/README.md)

## Architecture Truths

- Kubernetes CRDs are the control-plane source of truth.
- The API gateway is a substantial backend. It owns auth, CRUD, invoke routing, A2A, SSE, traces, incident management, and UI-facing metadata.
- The operator is the active control-plane engine. It reconciles agents into runtime StatefulSets, workflows into Jobs, incidents into lifecycle states.
- OpenCode is the production runtime. Pi and Mistral Vibe are alpha-only.
- Workflow detail lives mainly in worker artifacts and logs; CRD status is summary-level.
- MCP exists in two forms: per-agent sidecars and the shared MCP hub.
- Run intelligence is built into the platform: runtime events flow into the gateway trace store, then into signal watch and system-agent driven analysis.
- The durable Observatory tool payloads come from runtime-extracted final tool_calls, not from transient runtime status events.
- OpenCode caps extracted tool outputs at 40,000 characters before trace pipeline entry.
- Incident management flow: Alertmanager webhook (POST /api/v1/webhooks/alertmanager) → gateway CRUD → operator incident lifecycle controller.
- Workflow runs are safest with a single-agent pattern (same agentRef across steps, sessionGroup, autoRetry). Multi-agent workflows can stall with mismatched runtime configs.
- Scripts for alerting, workflow trigger, and report generation live in scripts/incidents/.

## Critical Operator Fix (June 2026)

`operator/controllers/webhook_controller.py` had a module-level call to `_start_nats_subscriber()` (line 791) that used `loop.run_until_complete(_listen())` when the asyncio loop was not yet running. Since `_listen()` contains `while True: await asyncio.sleep(60)` (infinite loop), `run_until_complete` blocks the import **indefinitely**, preventing Kopf from ever starting its event loop. Fix: changed to `loop.create_task(_listen())` which schedules the coroutine without blocking. If this pattern is used elsewhere, always prefer `create_task` over `run_until_complete` for infinite coroutines at module level.

## Critical Credential-Proxy Fix (June 2026)

`credential-proxy/main.go` reverse proxy used `httputil.NewSingleHostReverseProxy` which appends the incoming path onto the target URL. When a remote MCP target already ended with a concrete path (`/mcp`), a local proxy request to `/mcp` was forwarded as `/mcp/mcp`, returning 404. Fix: the `Director` function was changed to capture the original incoming path (`originalPath`) before the `originalDirector` rewrites it, then conditionally map `/mcp`-prefixed requests to the target's full path using a `joinURLPath` helper that avoids double-slash. If `httputil.ReverseProxy` director logic is used for targets with a concrete path suffix, always save `req.URL.Path` before calling `originalDirector(req)`.

## Repo Map

- [api-gateway/](api-gateway/) FastAPI public surface: auth, CRUD, invoke, A2A, SSE, traces.
- [operator/](operator/) Kopf controllers, manifest builders, and worker orchestration.
- [opencode-runtime/](opencode-runtime/) production agent runtime. [pi-runtime/](pi-runtime/), [vibe-runtime/](vibe-runtime/) are alpha.
- [web-ui/](web-ui/) Vite, React, and TypeScript frontend. Production is served by Nginx and proxies `/api` to the gateway.
- [charts/kubesynapse/](charts/kubesynapse/) main platform chart: CRDs, control plane, shared services, system agents, collector, secret wiring.
- [charts/agents/](charts/agents/) starter charts that install single `AIAgent` resources.
- [deploy/](deploy/) environment overlays and deployment notes.
- [examples/](examples/) sample CRDs and demo resources.

## Build, Test, and Validation

- Root checks: `make test`, `make lint`, `make helm-lint`, `make helm-template`, `make ui-build`
- Image and packaging: `make docker-build`, `make helm-package`
- Targeted checks:
  - `cd api-gateway && python -m pytest tests/ -v`
  - `cd operator && python -m pytest tests/ -v`
  - `cd web-ui && npm run build`

## Working Rules

- Prefer chart templates and values over prose docs if they disagree, then update the stale doc in the same change when appropriate.
- When changing chart values or deployment wiring, keep related docs aligned: [charts/kubesynapse/README.md](charts/kubesynapse/README.md), [docs/configuration-reference.md](docs/configuration-reference.md), and the matching files under [deploy/](deploy/).
- When changing architecture-sensitive behavior, check whether [docs/architecture-overview.md](docs/architecture-overview.md), [docs/architecture.md](docs/architecture.md), [docs/observability-explained.md](docs/observability-explained.md), or [docs/runtime-api-spec.md](docs/runtime-api-spec.md) need updates.
- When changing AgentPolicy enforcement or Gatekeeper templates, also update the in-app docs at [web-ui/src/components/docs/sections.tsx](web-ui/src/components/docs/sections.tsx).
- For web UI work, preserve the same-host `/api` proxy behavior used by both the Vite dev server and the Helm Nginx config.
- For auth or secret work, inspect both application code and chart wiring, especially [charts/kubesynapse/templates/api-gateway.yaml](charts/kubesynapse/templates/api-gateway.yaml) and [charts/kubesynapse/templates/external-secrets.yaml](charts/kubesynapse/templates/external-secrets.yaml).
- System agents are installed as post-install and post-upgrade Helm hooks. Do not rename or remove them casually.
- Local and air-gapped installs must account for the LiteLLM image preload called out in [charts/kubesynapse/README.md](charts/kubesynapse/README.md).
- The gateway container starts ``uvicorn main:app``. The FastAPI application is defined in
  ``api-gateway/_core.py`` (with router modules under ``api-gateway/routers/``) and
  re-exported by ``api-gateway/main.py``.
- The root Makefile uses POSIX shell constructs. On Windows, prefer Git Bash, WSL, or the equivalent direct component commands if `make` is not running under a POSIX shell.

## Conventions

- Python baseline is 3.11+.
- Ruff is the primary lint and format tool, and mypy is configured strictly in [pyproject.toml](pyproject.toml).
- Pytest import mode is configured in both [pytest.ini](pytest.ini) and [pyproject.toml](pyproject.toml).
- Prefer small, component-local changes and start from the owning surface instead of editing across gateway, operator, runtime, UI, and chart layers at once.
- When documenting behavior, link to the canonical doc instead of copying large architecture sections into new files.
