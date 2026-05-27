# Credential Proxy

A minimal, zero-dependency reverse proxy sidecar for KubeSynapse agent pods.

## Purpose

The credential-proxy runs as a **separate container** alongside the agent runtime. It holds all secrets (API keys, bearer tokens, passwords) and injects them into outbound requests. The agent runtime container never sees these secrets.

## Architecture

```
┌─── Agent Pod ──────────────────────────────────────────────┐
│                                                             │
│  credential-proxy (this container)                          │
│    - Holds LITELLM_MASTER_KEY, MCP_BEARER_TOKEN, etc.       │
│    - Proxies requests, injects auth headers                 │
│    - Validates inbound gateway requests                     │
│                                                             │
│  agent-runtime (separate container)                         │
│    - Zero secrets in env/files/proc                         │
│    - Connects to localhost:4001 (LiteLLM via proxy)         │
│    - Connects to localhost:4010 (MCP Hub via proxy)         │
│    - Listens on localhost:8081 (proxy validates auth)       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

Routes are configured via the `PROXY_ROUTES` environment variable (JSON array):

```json
[
  {
    "listen": ":4001",
    "target": "http://litellm-svc:4000",
    "auth": "bearer",
    "secret_env": "LITELLM_MASTER_KEY"
  },
  {
    "listen": ":4010",
    "target": "http://mcp-hub-svc:8000",
    "auth": "bearer",
    "secret_env": "MCP_BEARER_TOKEN"
  },
  {
    "listen": ":8080",
    "target": "http://localhost:8081",
    "auth": "validate",
    "secret_env": "OPENCODE_SERVER_PASSWORD"
  }
]
```

## Port Mapping

| Port | Purpose | Auth Mode |
|------|---------|-----------|
| `:4001` | LiteLLM proxy (outbound to `litellm-svc:4000`) | `bearer` |
| `:4010` | MCP Hub proxy (outbound to `mcp-hub-svc:8000`) | `bearer` |
| `:4003` | Provider API proxy (outbound to provider endpoint) | `header` |
| `:8080` | Inbound gateway requests (to agent runtime `:8081`) | `validate` |
| `:9090` | Health check endpoint | `none` |

### Host Header Handling

The proxy sets `req.Host = target.Host` on all outbound requests. This is required by APIs like GitHub Copilot that validate the Host header. Without this fix, these APIs return `200 OK` with plain text instead of valid JSON.

### Auth Modes

| Mode | Direction | Behavior |
|------|-----------|----------|
| `bearer` | Outbound | Adds `Authorization: Bearer <secret>` to requests |
| `header` | Outbound | Adds `<header_name>: <secret>` to requests |
| `validate` | Inbound | Validates `Authorization: Bearer <secret>`, strips it, forwards |
| `none` | Both | No auth injection/validation |

## Building

```bash
# Build binary
CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o credential-proxy .

# Build Docker image
docker build -t kubesynapse/credential-proxy:latest .
```

## Testing

```bash
go test -v ./...
```

## Security Properties

- **FROM scratch** — no shell, no package manager, no OS utilities
- **Non-root** — runs as UID 1000
- **Zero dependencies** — Go stdlib only (`net/http`, `httputil`)
- **Minimal attack surface** — ~3MB binary, single static executable
- **Container isolation** — secrets in this container cannot be read by sibling containers
