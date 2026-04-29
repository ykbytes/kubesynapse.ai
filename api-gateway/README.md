# KubeSynapse API Gateway

FastAPI monolith (~13 k lines) that exposes the public surface of KubeSynapse:
REST APIs, A2A JSON-RPC, SSE streaming, hybrid authentication, and trace storage.

## Purpose

The gateway is the single entry point for the UI, CLI, SDKs, and external
integrations. It handles CRUD for agents, workflows, and evaluations; invokes
agents synchronously or via SSE; routes A2A requests; and stores execution traces.

## Architecture

| Module | Responsibility |
|--------|--------------|
| `main_old.py` | Deployed app entry point — routers, lifespan, and middleware wiring |
| `constants.py` | Centralized defaults, feature flags, and path constants |
| `utils.py` | Shared helpers for serialization, pagination, and request context |
| `auth_middleware.py` | Hybrid auth: shared token, OIDC PKCE, JWT rotation, brute-force protection |
| `trace_store.py` | Trace persistence layer with batching and retention policies |
| `traces_router.py` | REST endpoints for trace querying, export, and live activity streams |

## Endpoints

| Category | Endpoints |
|----------|-----------|
| Health | `GET /api/health`, `GET /api/ready` |
| Agents | `GET /api/agents`, `POST /api/agents`, `GET /api/agents/{name}`, `PATCH /api/agents/{name}`, `DELETE /api/agents/{name}` |
| Workflows | `GET /api/workflows`, `POST /api/workflows`, `GET /api/workflows/{name}`, `PATCH /api/workflows/{name}`, `DELETE /api/workflows/{name}` |
| Evaluations | `GET /api/evals`, `POST /api/evals`, `GET /api/evals/{name}`, `PATCH /api/evals/{name}`, `DELETE /api/evals/{name}` |
| Invoke | `POST /api/agents/{name}/invoke`, `POST /api/agents/{name}/invoke/stream` |
| A2A | `POST /api/a2a` — JSON-RPC routing between agents |
| Artifacts | `GET /api/artifacts/{agent}/list`, `GET /api/artifacts/{agent}/download`, `GET /api/artifacts/{agent}/zip` |
| Traces | `GET /api/traces`, `GET /api/traces/{run_id}`, `GET /api/traces/live` |
| Activity | `GET /api/activity/stream` — Live SSE feed of step-level status transitions |

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
uvicorn main_old:app --host 0.0.0.0 --port 8080
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
