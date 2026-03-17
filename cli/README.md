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
agentctl agents discover workspace-assistant
agentctl agents update goose-assistant --goose-config-file config.yaml=.goose/config.yaml
agentctl agents update goose-assistant --goose-config-text prompts/review.md="Review changes conservatively."
agentctl agents update goose-assistant --clear-goose-config-files
agentctl agents update opencode-assistant --opencode-config-file opencode.json=.opencode/opencode.json
agentctl agents update opencode-assistant --opencode-config-text agents/reviewer.md="---\ndescription: Review only\nmode: subagent\n---\nReview conservatively."
agentctl agents update opencode-assistant --clear-opencode-config-files
agentctl workflows update research-report-pipeline -f examples/sample-workflow.yaml
agentctl evals delete --file examples/sample-eval.yaml --yes
agentctl invoke research-assistant "Explain Kubernetes namespaces"
agentctl invoke research-assistant "Ask the reviewer for a second opinion" --a2a-target-agent reviewer --a2a-target-namespace team-b --a2a-timeout-seconds 20
agentctl invoke research-assistant --subagent "team-a/reviewer|Code Review|Review the latest patch" --subagent "team-a/docs|Docs|Summarize API changes" --subagent-strategy parallel
agentctl invoke research-assistant --subagents-file examples/sample-subagents.yaml
agentctl invoke goose-assistant "Summarize /workspace notes" --max-turns 20 --system "Stay read-only" --builtin developer
agentctl approvals approve approval-name --reason "Reviewed by ops"
```

Accepted file formats:

- Kubernetes custom resource manifests such as `AIAgent`, `AgentWorkflow`, and `AgentEval`
- Direct API payload documents in JSON or YAML using snake_case fields

Resource management commands:

- `agentctl agents create|update|delete --file ...`
- `agentctl workflows create|update|delete --file ...`
- `agentctl evals create|update|delete --file ...`

Specialist team invoke inputs:

- `--subagent namespace/name|role|task` can be repeated to assemble a team inline.
- `--subagents-file FILE` accepts JSON or YAML containing either a top-level `subagents` array or a single subagent object.
- `--subagent-strategy sequential|parallel` controls whether specialists run one at a time or concurrently.
- Shared file entries in `input_files` also support `include_content` and `max_chars` so large files can be referenced without always embedding full contents.

Example `subagents` file:

```yaml
subagent_strategy: parallel
subagents:
	- namespace: team-a
		name: reviewer
		role: Code Review
		task: Review the implementation and list defects.
		input_files:
			- path: /workspace/README.md
				purpose: Current public documentation
	- ref: team-a/docs
		role: Docs
		task: Draft release notes for the same change.
		result_file_path: /workspace/artifacts/docs-summary.md
```

Goose-specific agent update flags:

- `agentctl agents update NAME --goose-config-file RELATIVE_PATH=FILE`
- `agentctl agents update NAME --goose-config-text RELATIVE_PATH=TEXT`
- `agentctl agents update NAME --clear-goose-config-files`

The Goose config paths must stay relative to Goose's config root, for example `config.yaml` or `prompts/review.md`.

OpenCode-specific agent update flags:

- `agentctl agents update NAME --opencode-config-file RELATIVE_PATH=FILE`
- `agentctl agents update NAME --opencode-config-text RELATIVE_PATH=TEXT`
- `agentctl agents update NAME --clear-opencode-config-files`

The OpenCode config paths must stay relative to the OpenCode config root, for example `opencode.json`, `agents/reviewer.md`, or `plugins/custom.ts`.

Environment variables:

- `AGENT_GATEWAY_URL` - API gateway base URL. Default: `http://localhost:8080`
- `AGENT_GATEWAY_TOKEN` - Bearer token used by the API gateway
- `AGENT_NAMESPACE` - Default Kubernetes namespace. Default: `default`
