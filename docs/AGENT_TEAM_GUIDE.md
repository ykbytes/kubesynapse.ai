# KubeSynth Multi-Agent Team — Quick Reference

**Version:** 1.0  
**Date:** 2026-04-23  
**Branch:** `preprod`

---

## How to Use

### Switch to the Primary Agent
```
Press Tab in OpenCode until you see: [kubesynth-architect]
```

### Invoke a Subagent Directly
```
@kubesynth-ui-artist improve the chat workbench responsive layout
```

### Let the Architect Delegate
```
kubesynth-architect> The workflow controller has a race condition
```
The architect will analyze and delegate to `@kubesynth-bug-hunter`.

---

## Agent Roster

| Agent | Color | Mode | Best For |
|-------|-------|------|----------|
| **`kubesynth-architect`** | Purple `#7C3AED` | **Primary** | Orchestration, planning, cross-cutting decisions |
| **`kubesynth-ui-artist`** | Pink `#EC4899` | Subagent | React components, Tailwind CSS, accessibility, animations |
| **`kubesynth-landing-magician`** | Cyan `#06B6D4` | Subagent | Landing pages, brand design, marketing site, scroll animations |
| **`kubesynth-security-guardian`** | Red `#EF4444` | Subagent | Security audits, vulnerability scanning, auth review, compliance |
| **`kubesynth-prod-engineer`** | Blue `#3B82F6` | Subagent | Helm hardening, probes, PDBs, logging, tracing, resource tuning |
| **`kubesynth-docs-storyteller`** | Green `#10B981` | Subagent | README, guides, blog posts, demos, GitHub templates, benchmarks |
| **`kubesynth-bug-hunter`** | Orange `#F97316` | Subagent | Bug investigation, regression tests, code quality, coverage |
| **`kubesynth-backend-refactorer`** | Indigo `#6366F1` | Subagent | Operator logic, gateway APIs, runtime pipeline, SQLAlchemy |

---

## Decision Matrix

### "I want to..." → "Use this agent"

| Task | Agent | Example |
|------|-------|---------|
| Fix a UI bug or add a new component | `@kubesynth-ui-artist` | "Add loading skeletons to the agent list" |
| Redesign the landing page | `@kubesynth-landing-magician` | "Create a hero section with terminal animation" |
| Audit auth flow for vulnerabilities | `@kubesynth-security-guardian` | "Review JWT handling in the gateway" |
| Add liveness probes to Helm chart | `@kubesynth-prod-engineer` | "Add probes and PDBs to all services" |
| Rewrite README for OSS launch | `@kubesynth-docs-storyteller` | "Make README scannable with architecture diagram" |
| Fix a race condition in worker | `@kubesynth-bug-hunter` | "Investigate workflow watchdog retry bug" |
| Refactor 13k-line gateway into modules | `@kubesynth-backend-refactorer` | "Split main.py into routers/" |
| Plan a multi-domain feature | `@kubesynth-architect` | "Plan the v0.2 release with UI + backend changes" |

---

## Typical Workflows

### Workflow 1: Landing Page Refresh
```
User: "Our landing page needs a complete redesign"

Architect: "I'll coordinate this. Let me delegate to the specialists."
  → @kubesynth-landing-magician: "Design new landing page sections"
  → @kubesynth-ui-artist: "Build the React components"
  → @kubesynth-docs-storyteller: "Write the copy and CTA messages"
  → @kubesynth-prod-engineer: "Ensure static assets are cached"

Architect: "Review and integrate all outputs. Done."
```

### Workflow 2: Security Audit
```
User: "We're going production next week, need a security review"

Architect: "Critical path. Delegating immediately."
  → @kubesynth-security-guardian: "Full security audit of gateway and operator"
  → @kubesynth-prod-engineer: "Harden Helm chart based on audit findings"
  → @kubesynth-bug-hunter: "Add regression tests for security fixes"

Architect: "Prioritize critical findings, plan remediation."
```

### Workflow 3: Bug Investigation
```
User: "Workflow gets stuck in 'queued' state"

Architect: "Routing to bug hunter."
  → @kubesynth-bug-hunter: "Investigate workflow controller watchdog"
  → @kubesynth-backend-refactorer: "Refactor worker state machine if needed"

Architect: "Review fix and add regression test."
```

### Workflow 4: OSS Growth Sprint
```
User: "We need 1000 GitHub stars in 30 days"

Architect: "Multi-pronged approach."
  → @kubesynth-docs-storyteller: "Rewrite README, create blog posts, benchmarks"
  → @kubesynth-landing-magician: "Build stunning landing page"
  → @kubesynth-prod-engineer: "Add dev container for easy contribution"
  → @kubesynth-ui-artist: "Polish the demo experience in Web UI"

Architect: "Coordinate launch timeline."
```

---

## Agent Permissions Summary

| Agent | Can Edit | Can Bash | Special Permissions |
|-------|----------|----------|---------------------|
| **architect** | Ask | Ask (git/make allow) | Can invoke all subagents via Task |
| **ui-artist** | Ask | npm only | No destructive commands |
| **landing-magician** | Ask | npm only | Web research allowed |
| **security-guardian** | **Deny** | Ask (scanning tools) | Read-only audit, reports only |
| **prod-engineer** | Ask | Allow (helm/make/pytest) | Infrastructure commands |
| **docs-storyteller** | Ask | **Deny** | Pure content creation |
| **bug-hunter** | Ask | Allow (test/lint tools) | Code search and test running |
| **backend-refactorer** | Ask | Allow (test/lint tools) | Code search and refactoring |

> **Security Note:** The security guardian is intentionally read-only. It audits and reports, never auto-fixes.

---

## Installation

### Global (works from any directory)
```bash
# Already installed at:
~/.config/opencode/agents/
```

### Per-Project (version controlled, shared with team)
```bash
# Already installed at:
kubemininions/.opencode/agents/
```

### Restart OpenCode to Pick Up New Agents
```powershell
# Windows
taskkill /F /IM opencode.exe /IM OpenCode.exe
cd C:\Users\ahmed\OneDrive\Desktop\repos\kubesynth\kubemininions
opencode
```

---

## Customization

### Add a New Subagent
1. Create `~/.config/opencode/agents/my-agent.md`
2. Use YAML frontmatter for config
3. Add `mode: subagent`
4. Add to `kubesynth-architect` task permissions

### Change Models per Agent
Edit the `model:` field in any agent's frontmatter:
```yaml
model: openai/gpt-5
```

### Adjust Temperature
- **0.0-0.2**: Security, bugs, backend (deterministic)
- **0.3-0.5**: UI, production (balanced)
- **0.6-0.8**: Landing, docs (creative)

---

## Troubleshooting

### Agent doesn't show in list
1. Check file is in `~/.config/opencode/agents/` or `.opencode/agents/`
2. Ensure YAML frontmatter is valid (use `---` delimiters)
3. Restart OpenCode: kill process and restart

### Task delegation fails
1. Check `kubesynth-architect` has `permission.task` for that subagent
2. Ensure subagent file exists and is readable
3. Check `opencode agent list` shows the subagent

### Agent makes wrong changes
1. Adjust `permission.edit` to `ask` or `deny`
2. Add more specific bash permission rules
3. Refine the system prompt with clearer constraints

---

## Tips for Maximum Effectiveness

1. **Start with the architect** — Let it decide who to call
2. **Be specific** — "Fix the chat scrollbar" is better than "Fix UI"
3. **Provide context** — Link to files, paste error messages
4. **Iterate** — Review subagent output, ask for refinements
5. **Combine agents** — Complex tasks need multiple specialists
6. **Use `@` for quick tasks** — Direct invocation skips planning overhead

---

*Generated by the KubeSynth Architect agent team. For questions or improvements, delegate to `@kubesynth-docs-storyteller`.*
