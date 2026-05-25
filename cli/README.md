# agentctl

**KubeSynapse CLI** — Kubernetes-native AI agent operations.

`agentctl` provides full control over AI agents, workflows, observability, chat, webhooks, authentication, credentials, and the skills catalog.

---

## Installation

```bash
# From the repository root (editable, recommended for development)
pip install -e ./cli

# Or with dev dependencies (pytest, ruff)
pip install -e "./cli[dev]"

# Build a wheel for regular install / distribution
pip install build
python -m build ./cli
pip install ./cli/dist/kubesynapse_cli-*.whl

# Verify
agentctl --version
```

**Requirements:** Python 3.11+ (deps: httpx, PyYAML, rich, typer, platformdirs, tenacity)
**Package name:** [`kubesynapse-cli`](https://pypi.org/project/kubesynapse-cli/) (build and publish with `python -m build` + `twine upload`)

---

## Quick Start

```bash
# Set up a profile
agentctl profile create demo --gateway http://localhost:8080 --namespace ai-agents
agentctl profile use demo

# Login
agentctl auth login -u admin -p secret

# List agents
agentctl agents list

# Invoke an agent
agentctl invoke my-agent "Explain Kubernetes namespaces"

# Stream response
agentctl invoke my-agent "Build a REST API" --stream
```

### Shell Completion

```bash
# Install (interactive — detects your shell)
agentctl --install-completion

# Or manually for your shell
agentctl --show-completion bash        # >> ~/.bashrc
agentctl --show-completion zsh         # >> ~/.zshrc
agentctl --show-completion powershell  # >> $PROFILE
agentctl --show-completion fish        # >> ~/.config/fish/completions
```

Press **Tab** to complete commands, subcommands, options, and flags.

---

## Configuration

`agentctl` uses **profiles** stored at `~/.config/agentctl/config.yaml`. Tokens are persisted per-profile at `~/.local/share/agentctl/credentials.yaml`.

### Priority (highest to lowest)

1. CLI flag (`--gateway`, `--token`, `--namespace`)
2. Environment variable (`AGENT_GATEWAY_URL`, `AGENT_GATEWAY_TOKEN`, `AGENT_NAMESPACE`, `AGENTCTL_PROFILE`)
3. Active profile from config file

### Profile Management

```bash
agentctl profile list                       # Show all profiles
agentctl profile create prod --gateway https://gateway.prod.io -n production
agentctl profile use prod                   # Switch active profile
agentctl profile login --token <token>      # Save token to current profile
agentctl profile logout                     # Clear saved token
```

---

## Global Options

| Option | Env Var | Default | Description |
|--------|---------|---------|-------------|
| `--gateway`, `-g` | `AGENT_GATEWAY_URL` | `http://localhost:8080` | Gateway base URL |
| `--token`, `-t` | `AGENT_GATEWAY_TOKEN` | — | Bearer token |
| `--namespace`, `-n` | `AGENT_NAMESPACE` | `default` | Target namespace |
| `--profile`, `-p` | `AGENTCTL_PROFILE` | `default` | Config profile |
| `--output`, `-o` | — | `table` | Output: `table`, `json`, `yaml`, `wide`, `name` |
| `--timeout` | — | `60` | Request timeout (seconds) |
| `--version`, `-V` | — | — | Show version |

### Output Formats

```bash
agentctl agents list -o json        # Machine-readable JSON
agentctl agents list -o yaml        # YAML output
agentctl agents list -o wide        # Table with extra columns
agentctl agents list -o name        # Just resource names
```

---

## Command Reference

### Top-Level

| Command | Description |
|---------|-------------|
| `health` | Check API gateway health |
| `apply` | Create or update a resource from a file (auto-detects kind) |
| `invoke` | Invoke an agent with a prompt (shortcut for `agents invoke`) |
| `logs` | Fetch agent logs (shortcut for `agents logs`) |

### Command Groups

| Group | Description |
|-------|-------------|
| [`agents`](#agents) | Manage and inspect AI agents |
| [`workflows`](#workflows) | Manage workflows, trigger executions, check status |
| [`runs`](#runs) | Approvals, policies, and `apply` |
| [`observatory`](#observatory) | Metrics, traces, alerts, and platform health |
| [`chat`](#chat) | Interactive agent chat sessions (including REPL) |
| [`webhooks`](#webhooks) | Manage webhooks, triggers, and dispatch |
| [`auth`](#authentication) | Login, register, sessions, and password management |
| [`admin`](#admin-user-management) | Administrative user management |
| [`credentials`](#credentials) | Git and GitHub credential management for agents |
| [`skills`](#skills) | Skills catalog, MCP tools, and MCP hub |
| [`profile`](#configuration) | CLI configuration profiles and token persistence |

---

## Agents

```bash
agentctl agents list                        # List agents
agentctl agents show my-agent               # Agent details
agentctl agents create -f agent.yaml        # Create from file
agentctl agents update my-agent -f new.yaml # Update from file
agentctl agents delete my-agent             # Delete (with confirmation)
agentctl agents delete my-agent --yes       # Skip confirmation
agentctl agents discover my-agent           # Show A2A peers
agentctl agents live-events my-agent        # Stream real-time events
```

### Invoke

```bash
agentctl invoke my-agent "Prompt here"
agentctl invoke my-agent --file prompt.txt
agentctl invoke my-agent "Stream this" --stream
agentctl invoke my-agent --thread-id abc123 "Continue conversation"
```

### Logs

```bash
agentctl logs my-agent                     # Last 200 lines
agentctl logs my-agent --tail 500          # Last 500 lines
agentctl logs my-agent --follow            # Stream in real-time
```

---

## Workflows

```bash
agentctl workflows list                    # List workflows
agentctl workflows show my-wf              # Workflow details
agentctl workflows create -f wf.yaml       # Create from file
agentctl workflows update my-wf -f new.yaml
agentctl workflows delete my-wf            # Delete with confirmation
agentctl workflows trigger my-wf "input"   # Trigger execution
agentctl workflows cancel my-wf            # Cancel running
agentctl workflows status my-wf            # Step states + status
agentctl workflows logs my-wf              # Workflow runtime logs
agentctl workflows logs my-wf --run-id abc # Specific run logs
```

---

## Runs

```bash
agentctl runs approvals                    # List pending approvals
agentctl runs approve approval-name --reason "OK"
agentctl runs deny approval-name --reason "Blocked"
agentctl runs policies                     # List policies
agentctl runs apply -f resource.yaml       # Create/update resource
```

---

## Observatory

```bash
agentctl observatory health                # Platform health status
agentctl observatory metrics               # Agent and system metrics
agentctl observatory metrics --agent my-agent -w 24h
agentctl observatory traces                # Recent execution traces
agentctl observatory traces --agent my-agent --status failed
agentctl observatory trace <trace-id>      # Detailed trace info
agentctl observatory alerts                # Active alerts
agentctl observatory signals               # Signal watch events
agentctl observatory export --format json --since 24h  # Export traces
```

---

## Chat

```bash
agentctl chat send my-agent "Hello"        # Send a message
agentctl chat send my-agent --thread abc   # Continue thread
agentctl chat threads                      # List chat threads
agentctl chat history <thread-id>          # Message history
agentctl chat interactive my-agent         # REPL-style session
```

---

## Webhooks & Triggers

```bash
agentctl webhooks list                     # List webhooks
agentctl webhooks show my-webhook          # Webhook details
agentctl webhooks create my-webhook --workflow my-wf --event push
agentctl webhooks delete my-webhook
agentctl webhooks triggers                 # List trigger executions
agentctl webhooks trigger-show <id>        # Trigger details
agentctl webhooks dispatch my-webhook --payload '{"ref":"main"}'
```

---

## Authentication

```bash
agentctl auth login -u admin -p secret     # Login (local)
agentctl auth login -u admin -p pass --provider ldap
agentctl auth register -u user -p pass --email user@x.com
agentctl auth me                           # Current user
agentctl auth change-password --current old --new new
agentctl auth config                       # Gateway auth config
agentctl auth logout                       # Revoke session
```

---

## Admin User Management

```bash
agentctl admin users                       # List all users
agentctl admin user-create -u bob -p pass --role operator
agentctl admin user-update 42 --role admin --active
agentctl admin user-delete 42              # Delete user
```

Roles: `viewer`, `operator`, `admin`.

---

## Credentials

```bash
# Git credentials
agentctl credentials git-set my-agent --method token --token ghp_xxx
agentctl credentials git-set my-agent --method basic --username u --password p
agentctl credentials git-set my-agent --method ssh --ssh-key-file ~/.ssh/id_ed25519
agentctl credentials git-show my-agent
agentctl credentials git-delete my-agent

# GitHub MCP credentials
agentctl credentials github-set my-agent --token ghp_xxx
agentctl credentials github-show my-agent
agentctl credentials github-delete my-agent
```

---

## Skills

```bash
agentctl skills list                       # Skills catalog
agentctl skills list --category development
agentctl skills show <skill-id>            # Skill details + file previews
agentctl skills tools                      # MCP tool sidecar categories
agentctl skills hub                        # Shared MCP hub servers
```

---

## Artifacts

```bash
agentctl artifacts list                    # List artifacts
agentctl artifacts list --agent my-agent   # Filter by agent
agentctl artifacts list --workflow my-wf --run-id abc
agentctl artifacts show <artifact-id>      # Artifact metadata
agentctl artifacts download <artifact-id>  # Download to file
agentctl artifacts download <id> --output results.json
```

---

## Providers

```bash
agentctl providers list                    # List LLM providers
agentctl providers show openai             # Provider details
agentctl providers models openai           # Available models
agentctl providers health openai           # Connectivity check
```

---

## Complete Command List

```
Top-level:
  health                                   Gateway health check
  apply FILE                               Create or update resource
  invoke AGENT PROMPT                      Invoke agent (shortcut)
  logs AGENT                               Agent logs (shortcut)

agents:
  agents list                              List agents
  agents show NAME                         Agent details
  agents create -f FILE                    Create agent
  agents update NAME [-f FILE]             Update agent
  agents delete NAME                       Delete agent
  agents discover NAME                     A2A peer discovery
  agents invoke AGENT PROMPT               Invoke agent
  agents logs AGENT                        Fetch agent logs
  agents live-events AGENT                 Stream live events

workflows:
  workflows list                           List workflows
  workflows show NAME                      Workflow details
  workflows create -f FILE                 Create workflow
  workflows update NAME -f FILE            Update workflow
  workflows delete NAME                    Delete workflow
  workflows trigger NAME [INPUT]           Trigger execution
  workflows cancel NAME                    Cancel workflow
  workflows status NAME                    Run status
  workflows logs NAME                      Workflow logs

runs:
  runs approvals                           List pending approvals
  runs approve NAME                        Approve request
  runs deny NAME                           Deny request
  runs policies                            List policies
  runs apply FILE                          Create/update resource

observatory:
  observatory health                       Platform health
  observatory metrics                      Agent/system metrics
  observatory traces                       Execution traces
  observatory trace ID                     Trace detail
  observatory alerts                       Active alerts
  observatory signals                      Signal watch events
  observatory export                       Export traces

chat:
  chat send AGENT MESSAGE                  Send message
  chat threads                             List threads
  chat history ID                          Message history
  chat interactive AGENT                   REPL session

webhooks:
  webhooks list                            List webhooks
  webhooks show NAME                       Webhook details
  webhooks create NAME                     Create webhook
  webhooks delete NAME                     Delete webhook
  webhooks triggers                        List triggers
  webhooks trigger-show ID                 Trigger detail
  webhooks dispatch NAME                   Dispatch webhook

auth:
  auth login                               Login
  auth logout                              Logout
  auth register                            Register user
  auth me                                  Current user
  auth change-password                     Change password
  auth config                              Auth configuration

admin:
  admin users                              List users
  admin user-create                        Create user
  admin user-update ID                     Update user
  admin user-delete ID                     Delete user

credentials:
  credentials git-set AGENT                Set git credentials
  credentials git-show AGENT               Show git metadata
  credentials git-delete AGENT             Delete git creds
  credentials github-set AGENT             Set GitHub creds
  credentials github-show AGENT            Show GitHub metadata
  credentials github-delete AGENT          Delete GitHub creds

skills:
  skills list                              Skills catalog
  skills show ID                           Skill detail
  skills tools                             MCP tool categories
  skills hub                               MCP hub servers

artifacts:
  artifacts list                           List artifacts
  artifacts show ID                        Artifact detail
  artifacts download ID                    Download artifact

providers:
  providers list                           List providers
  providers show NAME                      Provider detail
  providers models NAME                    Provider models
  providers health NAME                    Provider health

profile:
  profile list                             List profiles
  profile use NAME                         Switch profile
  profile create NAME                      Create profile
  profile update NAME                      Update profile
  profile delete NAME                      Delete profile
  profile login                            Save token
  profile logout                           Clear token
```

---

## Development

```bash
cd cli
pip install -e ".[dev]"
pytest tests/ -v              # 78+ tests
ruff check src/agentctl/      # Lint
```

### Package Structure

```
cli/src/agentctl/
  __init__.py         Version
  __main__.py         Entry point
  app.py              Typer app + global options
  config.py           Profile persistence, token store, settings resolution
  client.py           HTTP client with retry, pagination, SSE
  output.py           Rich formatters (table/json/yaml/wide/name)
  commands/
    __init__.py       Registration + top-level commands
    _parsers.py       CRD/flat payload normalization
    agents.py         Agent CRUD, invoke, logs, live-events
    workflows.py      Workflow CRUD, trigger, cancel, status, logs
    runs.py           Approvals, policies, apply
    auth.py           Login, register, sessions
    admin.py          User management
    credentials.py    Git/GitHub credentials
    skills.py         Skills catalog, MCP tools, hub
    profile.py        Profile management
    observatory.py    Metrics, traces, alerts, signals, health
    webhooks.py       Webhooks, triggers, dispatch
    chat.py           Send, threads, history, interactive
    artifacts.py      Artifact list, show, download
    providers.py      Provider list, show, models, health
```
