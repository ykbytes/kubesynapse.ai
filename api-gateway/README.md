# KubeSynapse API Gateway

FastAPI gateway surface for KubeSynapse: a thin application factory, modular
routers, shared gateway core logic, hybrid authentication, and trace storage.

## Purpose

The gateway is the single entry point for the UI, CLI, SDKs, and external
integrations. It handles CRUD for agents, workflows, and evaluations; invokes
agents synchronously or via SSE; routes A2A requests; and stores execution traces.

## Supported Runtimes

The gateway validates and serves three runtime kinds:

- `opencode` is the default runtime path used by the checked-in examples and the OpenCode config-file workflow.
- `pi` is the supported alternative runtime and uses the same CRUD, invoke, artifact, and SSE surfaces.
- `mistral-vibe` is the supported Mistral-backed runtime bridge and uses the same CRUD, invoke, artifact, and SSE surfaces.

Only `opencode`, `pi`, and `mistral-vibe` belong to the supported request surface.

## Architecture

| Module | Responsibility |
|--------|--------------|
| `main.py` | Deployed app entry point — app factory, middleware, and router mounting |
| `_core.py` | Shared gateway models, runtime validation, Kubernetes helpers, and response shaping |
| `routers/` | Modular REST route handlers for agents, workflows, evals, auth, chat, webhooks, and observability |
| `constants.py` | Centralized defaults, feature flags, and path constants |
| `utils.py` | Shared helpers for serialization, pagination, and request context |
| `auth_middleware.py` | Hybrid auth: shared token, OIDC PKCE, JWT rotation, brute-force protection |
| `trace_store.py` | Trace persistence layer with batching and retention policies |
| `traces_router.py` | REST endpoints for trace querying, export, and live activity streams |

## Endpoints

| Category | Endpoints |
|----------|-----------|
| Health | `GET /api/v1/health`, `GET /api/v1/ready` |
| Agents | `GET /api/v1/agents`, `POST /api/v1/agents`, `GET /api/v1/agents/{name}`, `PATCH /api/v1/agents/{name}`, `DELETE /api/v1/agents/{name}` |
| Workflows | `GET /api/v1/workflows`, `POST /api/v1/workflows`, `GET /api/v1/workflows/{name}`, `PATCH /api/v1/workflows/{name}`, `DELETE /api/v1/workflows/{name}` |
| Evaluations | `GET /api/v1/evals`, `POST /api/v1/evals`, `GET /api/v1/evals/{name}`, `PATCH /api/v1/evals/{name}`, `DELETE /api/v1/evals/{name}` |
| Invoke | `POST /api/v1/agents/{name}/invoke`, `POST /api/v1/agents/{name}/invoke/stream` |
| A2A | `POST /api/v1/a2a` — JSON-RPC routing between agents |
| Artifacts | `GET /api/v1/artifacts/{agent}/list`, `GET /api/v1/artifacts/{agent}/download`, `GET /api/v1/artifacts/{agent}/zip` |
| Traces | `GET /api/v1/traces`, `GET /api/v1/traces/{run_id}`, `GET /api/v1/traces/live` |
| Activity | `GET /api/v1/activity/stream` — Live SSE feed of step-level status transitions |

## Authentication

The gateway supports three modes, configurable per environment:

1. **Shared Token** — Simple bearer token for dev/test and service-to-service
   calls. Rotate via `API_GATEWAY_SHARED_TOKEN`.
2. **OIDC PKCE** — Browser-first login flow. The gateway initiates PKCE against
   any standard OIDC provider and issues short-lived JWTs.
3. **JWT Rotation** — Access tokens expire quickly; refresh tokens are rotated on
   every use and stored hashed.
4. **Brute-Force Protection** — Failed login attempts are rate-limited per IP
   and per username with exponential backoff.

## Development Setup

```bash
cd api-gateway/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the server locally:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Testing

```bash
pytest tests/test_smoke.py -v
```

Smoke tests cover health, agent CRUD, invoke round-trip, and SSE streaming
negotiation.

## Deployment

Current image:

```bash
docker pull docker.io/kubesynapse/kubesynapse-api-gateway:v1.0.15
```

In production the gateway runs behind the chart's Ingress at `/api` with the
Web UI on `/`.
