# agentctl

**Modern CLI for KubeSynapse** — a Kubernetes-native multi-runtime AI agent orchestration platform.

`agentctl` provides full control over agents, workflows, policies, approvals, credentials, authentication, and the skills catalog from the terminal.

---

## Installation

```bash
# Install from the repository
python -m pip install -e ./cli

# Or run directly
python cli/agentctl.py --help
```

On Windows with the repository virtual environment, run `.venv\Scripts\agentctl.exe` or activate the venv first:

```powershell
.venv\Scripts\Activate.ps1
agentctl --help
```

**Requirements:** Python 3.11+, httpx, PyYAML, rich, typer.

---

## Quick Start

```bash
# Check gateway health
agentctl health

# Login (for enterprise auth setups)
agentctl auth login -u admin -p secret

# Create an agent from YAML
agentctl agents create -f examples/sample-agent.yaml

# Invoke the agent
agentctl invoke my-agent "Explain Kubernetes namespaces"

# Stream the response in real-time
agentctl invoke my-agent "Build a REST API" --stream

# Create and trigger a workflow
agentctl workflows create -f examples/sample-workflow.yaml
agentctl workflows trigger my-workflow "New input for the pipeline"

# Apply any resource (auto-detects kind)
agentctl apply examples/sample-agent.yaml
```

---

## Global Options

Every command inherits these global options:

| Option | Env Variable | Default | Description |
|--------|-------------|---------|-------------|
| `--gateway-url` | `AGENT_GATEWAY_URL` | `http://localhost:8080` | API gateway base URL |
| `--token` | `AGENT_GATEWAY_TOKEN` | (empty) | Bearer token for authenticated requests |
| `--namespace`, `-n` | `AGENT_NAMESPACE` | `default` | Default Kubernetes namespace |
| `--timeout` | — | `60.0` | HTTP timeout in seconds (minimum 1.0) |
| `--json` | — | `false` | Emit raw JSON instead of rich formatted output |

---

## Command Reference

### Root Commands

| Command | Description |
|---------|-------------|
| `agentctl health` | Check API gateway health status |
| `agentctl config` | Show the effective CLI configuration |
| `agentctl version` | Show the CLI version |
| `agentctl invoke` | Invoke an agent with a prompt |
| `agentctl logs` | Fetch or stream agent runtime logs |
| `agentctl apply` | Create or update a resource from a file (auto-detects kind) |

### Command Groups

| Group | Description |
|-------|-------------|
| `agentctl agents` | Manage and inspect agents |
| `agentctl workflows` | Manage, trigger, and cancel workflows |
| `agentctl approvals` | List, review, and decide on approvals |
| `agentctl policies` | List policies |
| `agentctl auth` | Authentication and user session management |
| `agentctl admin` | Admin operations (requires admin role) |
| `agentctl credentials` | Manage agent git and GitHub credentials |
| `agentctl skills` | Browse the skills catalog |
| `agentctl tools` | Browse MCP tool sidecars and hub servers |

---

## Agents

### List Agents

```bash
agentctl agents list
agentctl agents list -n production
```

### Create an Agent

```bash
agentctl agents create -f examples/sample-agent.yaml
agentctl agents create -f agent.json
```

Accepts Kubernetes custom resource manifests (`kind: AIAgent`) or direct API payload documents in JSON/YAML.

### Show Agent Details

```bash
agentctl agents show my-agent
agentctl agents show my-agent --json
```

### Update an Agent

```bash
# Update from a file
agentctl agents update my-agent -f updated-agent.yaml

# Update OpenCode runtime config files
agentctl agents update opencode-assistant --opencode-config-file opencode.json=.opencode/opencode.json
agentctl agents update opencode-assistant --opencode-config-text prompts/review.md="Review changes conservatively and return only the defects."
agentctl agents update opencode-assistant --clear-opencode-config-files
```

**OpenCode config flags:**
- `--opencode-config-file RELATIVE_PATH=FILE` — Map an OpenCode config-root path to a local file
- `--opencode-config-text RELATIVE_PATH=TEXT` — Set a config file from inline text
- `--clear-opencode-config-files` — Remove all existing config files before applying overrides

Paths must be relative to the runtime config root (e.g., `config.yaml`, `agents/reviewer.md`, `plugins/custom.ts`).

### Delete an Agent

```bash
agentctl agents delete my-agent
agentctl agents delete --file examples/sample-agent.yaml --yes
```

### Discover A2A Peers

```bash
agentctl agents discover workspace-assistant
agentctl agents discover workspace-assistant --include-unreachable
```

Shows the agent's configured Agent-to-Agent (A2A) communication targets and their reachability status.

### Stream Live Agent Events

```bash
agentctl agents live-events my-agent
```

Opens an SSE stream of real-time agent reasoning events (Pi runtime only).

---

## Invoking Agents

### Basic Invocation

```bash
agentctl invoke my-agent "Explain Kubernetes namespaces"
agentctl invoke my-agent --file prompt.txt
echo "Summarize this" | agentctl invoke my-agent
```

### Streaming

```bash
agentctl invoke my-agent "Build a REST API" --stream
```

SSE streaming shows real-time deltas as the agent generates its response.

### Thread Continuations

```bash
agentctl invoke my-agent "What about scaling?" --thread-id abc123
```

### Agent-to-Agent (A2A) Routing

```bash
agentctl invoke my-agent "Ask the reviewer for feedback" \
  --a2a-target-agent reviewer \
  --a2a-target-namespace team-b \
  --a2a-timeout-seconds 30
```

### Runtime-Specific Options

| Option | Runtime | Description |
|--------|---------|-------------|
| `--system TEXT` | OpenCode | Additional system instructions |
| `--max-turns N` | OpenCode | Limit autonomous turns |
| `--no-session` | OpenCode | Disable session persistence |
| `--debug` | OpenCode | Enable debug output |
| `--working-directory DIR` | OpenCode | Run from a subdirectory in workspace |
| `--max-retries N` | OpenCode | Limit autonomous retries |
| `--no-autonomous` | OpenCode | Disable autonomous completion prompt |
| `--output-format FMT` | OpenCode | Preferred output: json, code, markdown, text |
| `--output-schema-file FILE` | OpenCode | JSON/YAML schema for structured output |
| `--a2a-target-agent NAME` | A2A | Route the request to another agent explicitly |
| `--a2a-target-namespace NS` | A2A | Namespace of the explicit A2A target |
| `--a2a-timeout-seconds N` | A2A | Caller-side timeout for the outbound A2A request |

### Approval Workflow

```bash
agentctl invoke my-agent "Deploy to production" --require-approval --approval-action "deploy"
```

---

## Logs

```bash
# Fetch the last 200 lines (default)
agentctl logs my-agent

# Fetch the last 500 lines
agentctl logs my-agent --tail 500

# Stream logs in real-time
agentctl logs my-agent --follow

# Combine tail and follow
agentctl logs my-agent --follow --tail 50
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--tail N` | `-t` | `200` | Number of log lines to retrieve (1-5000) |
| `--follow` | `-f` | `false` | Stream logs in real-time via SSE |

Press `Ctrl+C` to stop following logs.

---

## Workflows

### CRUD Operations

```bash
agentctl workflows list
agentctl workflows create -f examples/sample-workflow.yaml
agentctl workflows show my-workflow
agentctl workflows update my-workflow -f updated-workflow.yaml
agentctl workflows delete my-workflow --yes
```

### Trigger Execution

```bash
# Trigger with existing input
agentctl workflows trigger my-workflow

# Trigger with new input
agentctl workflows trigger my-workflow "Analyze the Q4 financial data"

# Trigger with input from a file
agentctl workflows trigger my-workflow --file input.txt
```

Triggering re-reconciles the workflow even if the spec hasn't changed by resetting the status phase.

### Cancel a Workflow

```bash
agentctl workflows cancel my-workflow
agentctl workflows cancel my-workflow --yes  # skip confirmation
```

Cancels workflows in `running`, `queued`, or `waiting-approval` phase.

### Check Workflow Status

```bash
agentctl workflows status my-workflow
```

Shows a focused view of the current execution state including phase, current step, run ID, pending approvals, and per-step status.

### Fetch Workflow Logs

```bash
agentctl workflows logs my-workflow
```

Streams the runtime logs for the most recent workflow execution.

---

## Approvals

### List Pending Approvals

```bash
agentctl approvals list
```

Scans all workflows in the namespace and shows any pending approval gates.

### Show Approval Details

```bash
agentctl approvals show approval-name
```

### Approve or Deny

```bash
agentctl approvals approve approval-name --reason "Reviewed by ops"
agentctl approvals deny approval-name --reason "Not ready for production"
```

---

## Policies

```bash
agentctl policies list
agentctl policies list -n production
```

---

## Authentication

### Login

```bash
# Interactive (prompts for credentials)
agentctl auth login

# Non-interactive
agentctl auth login -u admin -p mypassword

# LDAP provider
agentctl auth login -u admin -p mypassword --provider ldap
```

On success, prints the access token. Export it to use authenticated commands:

```bash
export AGENT_GATEWAY_TOKEN=<token>
```

### Register

```bash
agentctl auth register -u newuser -p mypassword --email user@example.com --display-name "New User"
```

The first user registered is automatically assigned the `admin` role.

### Current User

```bash
agentctl auth me
```

Shows username, role, auth provider, and allowed namespaces.

### Change Password

```bash
agentctl auth change-password --current oldpass --new newpass
```

Available only for local authentication users.

### Logout

```bash
agentctl auth logout
```

Revokes the current session and refresh token.

### Auth Configuration

```bash
agentctl auth config
```

Shows the gateway's authentication configuration (enabled providers, OIDC/SAML settings, etc.).

---

## Admin User Management

All admin commands require the `admin` role.

### List Users

```bash
agentctl admin users-list
```

### Create a User

```bash
agentctl admin users-create -u newoperator -p securepass --role operator --namespace default --namespace staging
```

| Option | Description |
|--------|-------------|
| `--username`, `-u` | Username (3-128 chars, required) |
| `--password`, `-p` | Password (8+ chars, required) |
| `--role` | Role: `viewer`, `operator`, or `admin` (default: `viewer`) |
| `--email` | Email address |
| `--display-name` | Display name |
| `--namespace` | Allowed namespaces (repeatable) |

### Update a User

```bash
agentctl admin users-update 42 --role admin --active
agentctl admin users-update 42 --inactive  # disable account
agentctl admin users-update 42 --namespace production --namespace staging
```

| Option | Description |
|--------|-------------|
| `--role` | New role: `viewer`, `operator`, or `admin` |
| `--display-name` | New display name |
| `--active/--inactive` | Enable or disable the user account |
| `--namespace` | Replace allowed namespaces (repeatable) |

---

## Credentials

Manage git and GitHub credentials attached to agents. Credentials are stored as Kubernetes Secrets and mounted into agent pods.

### Git Credentials

```bash
# Token-based authentication
agentctl credentials git-set my-agent --method token --token ghp_xxxx

# Basic auth (username + password)
agentctl credentials git-set my-agent --method basic --username user --password pass

# SSH key authentication
agentctl credentials git-set my-agent --method ssh --ssh-key-file ~/.ssh/id_ed25519

# Show credential metadata (does not reveal secrets)
agentctl credentials git-show my-agent

# Delete credentials
agentctl credentials git-delete my-agent --yes
```

| Option | Description |
|--------|-------------|
| `--method` | Auth method: `token`, `basic`, or `ssh` (required) |
| `--token` | PAT token (for `token` method) |
| `--username` | Username (for `basic` method) |
| `--password` | Password (for `basic` method) |
| `--ssh-key-file` | Path to SSH private key file (for `ssh` method) |

If credentials are not provided via options, interactive prompts will appear.

### GitHub MCP Credentials

```bash
# Set GitHub token for the GitHub MCP sidecar
agentctl credentials github-set my-agent --token ghp_xxxx

# Show metadata
agentctl credentials github-show my-agent

# Delete
agentctl credentials github-delete my-agent --yes
```

---

## Skills Catalog

### List Skills

```bash
agentctl skills list
agentctl skills list --category "development"
agentctl skills list --search "kubernetes"
```

| Option | Short | Description |
|--------|-------|-------------|
| `--category` | `-c` | Filter by skill category |
| `--search` | `-s` | Search by name or description |

### Get Skill Details

```bash
agentctl skills get kubernetes-admin
```

Shows skill metadata, tags, file list, and previews Markdown/text content.

---

## MCP Tools

### List Tool Sidecar Categories

```bash
agentctl tools list
```

Shows available MCP tool sidecar types (code-exec, web-search, database, browser, documents, git, github, kubernetes, messaging, rag).

### List MCP Hub Servers

```bash
agentctl tools hub
```

Shows shared MCP hub servers configured in the gateway, including transport type and connection details.

---

## Artifacts

Download files produced by agent runs.

### List Artifacts

```bash
agentctl artifacts list my-agent
```

### Download a File

```bash
agentctl artifacts download my-agent output/results.json
```

### Download Workspace ZIP

```bash
agentctl artifacts zip my-agent
```

---

## Apply (Generic Resource Management)

```bash
agentctl apply examples/sample-agent.yaml
agentctl apply examples/sample-workflow.yaml
```

`apply` auto-detects the resource kind from the `kind` field or document structure:
- `AIAgent` or documents with a `model` field → Agent
- `AgentWorkflow` or documents with a `steps` field → Workflow

If the resource already exists (HTTP 409), it falls back to an update (PATCH).

---

## File Formats

`agentctl` accepts two file formats for resource creation and updates:

### 1. Kubernetes Custom Resource Manifests

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: research-assistant
  namespace: default
        - name: API_KEY
          value: secret
  a2a:
    allowedCallers:
      - name: coordinator
        namespace: default
  skills:
    files:
      analysis/guidelines.md: |
        # Analysis Guidelines
        Follow these steps when analyzing data...
```

### 2. Direct API Payload (snake_case or camelCase)

```yaml
name: research-assistant
model: gpt-4
system_prompt: "You are a research assistant."
runtime_kind: opencode
storage_size: 2Gi
enable_gvisor: false
mcp_servers:
  - web-search
  - documents
```

Both JSON and YAML are supported.

---

## JSON Output

Every command supports `--json` for machine-readable output:

```bash
agentctl agents list --json | jq '.[].name'
agentctl workflows status my-workflow --json | jq '.phase'
agentctl approvals list --json | jq '.[].approval_name'
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_GATEWAY_URL` | API gateway base URL | `http://localhost:8080` |
| `AGENT_GATEWAY_TOKEN` | Bearer token for authentication | (empty) |
| `AGENT_NAMESPACE` | Default Kubernetes namespace | `default` |

---

## Complete Command List

```
agentctl health                         # Gateway health check
agentctl config                         # Show CLI configuration
agentctl version                        # Show CLI version
agentctl apply FILE                     # Create or update resource from file

agentctl invoke AGENT PROMPT            # Invoke agent
agentctl logs AGENT                     # Fetch/stream agent logs

agentctl agents list                    # List agents
agentctl agents create -f FILE          # Create agent
agentctl agents show NAME               # Show agent details
agentctl agents update NAME [-f FILE]   # Update agent
agentctl agents delete NAME             # Delete agent
agentctl agents discover NAME           # Show A2A peer discovery
agentctl agents live-events NAME        # Stream live agent events

agentctl workflows list                 # List workflows
agentctl workflows create -f FILE       # Create workflow
agentctl workflows show NAME            # Show workflow details
agentctl workflows update NAME -f FILE  # Update workflow
agentctl workflows delete NAME          # Delete workflow
agentctl workflows trigger NAME [INPUT] # Trigger workflow execution
agentctl workflows cancel NAME          # Cancel running workflow
agentctl workflows status NAME          # Show focused run status
agentctl workflows logs NAME            # Fetch workflow logs

agentctl approvals list                 # List pending approvals
agentctl approvals show NAME            # Show approval details
agentctl approvals approve NAME         # Approve request
agentctl approvals deny NAME            # Deny request

agentctl policies list                  # List policies

agentctl auth login                     # Login (local/LDAP)
agentctl auth logout                    # Logout and revoke session
agentctl auth register                  # Register new user
agentctl auth me                        # Show current user
agentctl auth change-password           # Change password
agentctl auth config                    # Show auth configuration

agentctl admin users-list               # List all users (admin)
agentctl admin users-create             # Create user (admin)
agentctl admin users-update ID          # Update user (admin)

agentctl credentials git-set AGENT      # Set git credentials
agentctl credentials git-show AGENT     # Show git credential metadata
agentctl credentials git-delete AGENT   # Delete git credentials
agentctl credentials github-set AGENT   # Set GitHub credentials
agentctl credentials github-show AGENT  # Show GitHub credential metadata
agentctl credentials github-delete AGENT # Delete GitHub credentials

agentctl skills list                    # List skills catalog
agentctl skills get ID                  # Show skill details

agentctl tools list                     # List MCP tool sidecars
agentctl tools hub                      # List shared MCP hub servers

agentctl artifacts list AGENT           # List agent artifacts
agentctl artifacts download AGENT FILE  # Download a single artifact
agentctl artifacts zip AGENT            # Download workspace ZIP
```

---

## Examples

```bash
# Full agent lifecycle
agentctl agents create -f examples/sample-agent.yaml
agentctl invoke research-assistant "What is Kubernetes?"
agentctl invoke research-assistant "Tell me more" --thread-id <thread-id> --stream
agentctl logs research-assistant --follow
agentctl agents delete research-assistant --yes

# Workflow execution
agentctl workflows create -f examples/sample-workflow.yaml
agentctl workflows trigger research-report-pipeline "Analyze Q4 data"
agentctl workflows status research-report-pipeline
agentctl approvals list
agentctl approvals approve approval-xyz --reason "Looks good"
agentctl workflows cancel research-report-pipeline --yes

# Explicit A2A invocation
agentctl invoke coordinator "Ask the reviewer for feedback" \
  --a2a-target-agent reviewer \
  --a2a-target-namespace dev \
  --a2a-timeout-seconds 30

# OpenCode runtime controls
agentctl invoke opencode-assistant "Summarize /workspace notes" \
  --max-turns 20 \
  --system "Stay read-only" \
  --working-directory "/workspace/project"

# OpenCode with structured output
agentctl invoke opencode-assistant "Extract API endpoints" \
  --output-format json \
  --output-schema-file schema.json \
  --max-retries 3

# A2A cross-namespace routing
agentctl invoke my-agent "Get review from team-b" \
  --a2a-target-agent reviewer \
  --a2a-target-namespace team-b \
  --a2a-timeout-seconds 30

# Credential management
agentctl credentials git-set my-agent --method token --token ghp_xxxx
agentctl credentials github-set my-agent --token ghp_xxxx

# Admin user management
agentctl admin users-create -u operator1 -p securepass --role operator --namespace default
agentctl admin users-update 42 --role admin --namespace production --namespace staging
agentctl admin users-list
```
