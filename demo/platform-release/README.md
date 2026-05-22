# Platform Release Demo

This is the strongest demo for:

- developers
- platform engineers
- DevOps teams
- release managers
- engineering leaders who want evidence-backed change plans instead of AI theater

## What It Proves

- live documentation research via the existing Context7 MCP path
- CRD-defined agents and workflow
- artifact handoff through the workflow workspace
- structured release-risk analysis
- approval gate before the final operator brief is produced
- a workflow that helps humans decide, not a workflow that blindly changes production

## Apply

```bash
kubectl apply -f demo/platform-release/bundle.yaml
```

## Trigger

```bash
agentctl --gateway-url http://localhost:8080 workflows trigger ingress-upgrade-release-readiness
```

## What To Show On Camera

1. `kubectl get aiagents,agentworkflows -n default`
2. the workflow run appearing in the UI
3. the approval resource appearing before the final publish step
4. the approval being resolved live
5. the final brief landing as a workflow artifact

## Strong Narration Angle

`This is not an autonomous rollout bot. It is a release-readiness workflow that gathers upstream facts, turns them into platform-specific risk analysis, and then pauses for a human approval before emitting the final operator brief.`
