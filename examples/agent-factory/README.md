# KubeSynapse Factory Example

This example packages a lean factory for turning an incoming idea into a reviewed KubeSynapse bundle. The previous six-agent version duplicated materialization and quality review. This version keeps the same core behavior with four agents and a single draft -> review -> finalize path.

## Resources

- `project-context.yaml`: shared platform rules and bundle design constraints.
- `policy.yaml`: guardrails for the factory agents.
- `agents.yaml`: four agents.
- `workflow.yaml`: the factory orchestration pipeline.
- `factory-output-schema.json`: reference schema for the factory blueprint contract.
- `invoke-examples.sh`: example API calls.
- `deploy.ps1`: apply and validate the example in a cluster.

## Agents

1. `KubeSynapse-factory-analyst`
   Expands raw requests into a structured specification with requirements, roles, tasks, acceptance criteria, and verification guidance.
2. `KubeSynapse-factory`
   Drafts the initial bundle, then finalizes it after review. Final materialization now stays with the factory instead of a separate materializer agent.
3. `KubeSynapse-factory-reviewer`
   Performs schema, reference, approval-boundary, and quality review in one pass.
4. `KubeSynapse-factory-deployer`
   Applies approved manifests and, if separately approved, triggers the generated workflow.

## Workflow Shape

The workflow keeps explicit approval control while removing the old duplicated loops:

1. `analyze-request`
2. `generate-blueprint`
3. `review-blueprint`
4. `finalize-bundle`
5. `deploy-approved-bundle` (conditional gate)
6. `deploy-bundle` (approval required)
7. `run-approved-workflow` (conditional gate)
8. `run-generated-workflow` (approval required)

## Modes

- `lightweight-draft`
  The pipeline still analyzes, reviews, and finalizes the design, but the finalization step stays design-only and does not write files or open live-action gates.
- `governed-bundle`
  Produces a review-ready or handoff-ready bundle with supporting deliverables. Deployment and generated-workflow execution remain disabled.
- `fully-autonomous`
  Produces the strongest deployable bundle the factory can justify. Deployment and generated-workflow execution still require explicit approval at runtime.

## Deploy

From the repo root:

```powershell
Set-Location ./examples/agent-factory
pwsh ./deploy.ps1
```

The deploy script:

- removes the obsolete `KubeSynapse-factory-materializer` and `KubeSynapse-factory-quality-reviewer` agents,
- validates the context, policy, agents, and workflow manifests,
- applies the lean four-agent bundle,
- waits for the four active sandboxes to roll out.

## Invoke

Use `invoke-examples.sh` for direct agent invocation and workflow-trigger examples. The workflow name remains `KubeSynapse-factory-pipeline`, so existing trigger examples continue to work.

When `deploy-bundle` or `run-generated-workflow` pauses for approval, approve the generated `AgentApproval` from the web UI or with the API shown in `invoke-examples.sh`.
