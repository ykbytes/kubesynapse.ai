# Daily Standup Bot

Three AI agents that generate a structured daily standup report from git
history and Jira sprint data. No API keys needed beyond your LLM provider.

## Architecture

```
git-summarizer ──► jira-tracker ──► standup-scribe
   (Step 1)         (Step 2)         (Step 3)
```

| Agent | Role | MCP |
|-------|------|-----|
| `standup-git` | Reads git log, groups commits by author | git |
| `standup-jira` | Parses Jira JSON, summarizes sprint status | code-exec |
| `standup-scribe` | Merges both into formatted standup report | code-exec |

## Workflow

```
1. summarize-git   →  commits-summary.md
2. track-jira      →  sprint-status.json
3. compose-standup →  standup-YYYY-MM-DD.md
```

## Sample Data (Built-In)

The `project-context.yaml` includes a fake git log (10 commits across 3 devs)
and a fake Jira sprint export (8 issues in various states). No external
services are called — the agents work entirely from this workspace data.

## Quick Deploy

```powershell
Set-Location ./examples/daily-standup-bot
pwsh ./deploy.ps1
```

Manual:

```bash
kubectl apply -f examples/daily-standup-bot/project-context.yaml
kubectl apply -f examples/daily-standup-bot/agents.yaml
kubectl apply -f examples/daily-standup-bot/policy.yaml
kubectl apply -f examples/daily-standup-bot/workflow.yaml
```

## Trigger

```bash
# Via API
curl -X POST http://localhost:8080/api/v1/workflows/daily-standup/trigger?namespace=default \
  -H "Authorization: Bearer $TOKEN"

# Via CLI
agentctl workflows trigger daily-standup
```

## Output

Find `standup-YYYY-MM-DD.md` in the `standup-scribe` agent workspace
(Web UI → Agents → standup-scribe → Workspace Files).
