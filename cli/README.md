# agentctl

Python CLI for the AI Agent Sandbox.

Install locally:

```bash
python -m pip install -e ./cli
```

If you are using the repository virtual environment on Windows, run `.venv/Scripts/agentctl.exe` or activate `.venv` first so `agentctl` is on `PATH`.

Examples:

```bash
agentctl health
agentctl agents list
agentctl agents create -f examples/sample-agent.yaml
agentctl workflows update research-report-pipeline -f examples/sample-workflow.yaml
agentctl evals delete --file examples/sample-eval.yaml --yes
agentctl invoke research-assistant "Explain Kubernetes namespaces"
agentctl approvals approve approval-name --reason "Reviewed by ops"
```

Accepted file formats:

- Kubernetes custom resource manifests such as `AIAgent`, `AgentWorkflow`, and `AgentEval`
- Direct API payload documents in JSON or YAML using snake_case fields

Resource management commands:

- `agentctl agents create|update|delete --file ...`
- `agentctl workflows create|update|delete --file ...`
- `agentctl evals create|update|delete --file ...`

Environment variables:

- `AGENT_GATEWAY_URL` - API gateway base URL. Default: `http://localhost:8080`
- `AGENT_GATEWAY_TOKEN` - Bearer token used by the API gateway
- `AGENT_NAMESPACE` - Default Kubernetes namespace. Default: `default`
