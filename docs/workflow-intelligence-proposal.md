# KubeSynapse Overhaul: Self-Verifying, Context-Aware Workflow Platform

## Executive Summary

Five targeted changes transform KubeSynapse from a capable execution substrate into a smarter, self-verifying, context-aware workflow platform. No new services. No rewrites. All changes fit into existing subsystems.

**Core insight:** Agent output quality is determined *before* and *after* execution, not during it. KubeSynapse already runs agents well. What it lacks is:
1. **Proving results** — verification gates after each step
2. **Catching mistakes** — peer-review as a native step type
3. **Front-loading clarity** — project context injection via ConfigMap
4. **Running faster** — formalized wave-based parallel execution
5. **Guiding users** — next-action suggestions + verification/review visibility in the UI

Ideas are drawn from three reference tools (Superpowers two-stage review, BMAD project-context-first design, get-shit-done spec-driven verification) and adapted to fit KubeSynapse' Kubernetes-native CRD + operator + worker architecture.

---

## Phase 1: Workflow Intelligence

### Change 1: `verify` field on workflow steps

**Files:** `charts/kubesynapse/templates/agentworkflow-crd.yaml`, `operator/worker.py`, `operator/utils.py`

**CRD:** Add `verify` (type: string) to the step schema. Optional. When present, after a step completes successfully, the worker sends a second invocation to the same agentRef with a structured verification prompt:

```
Verify the following output against this criterion:
{verify}

Output to verify:
{step_output}

Respond with exactly PASS or FAIL on the first line, followed by your reasoning.
```

**Worker (`execute_workflow_step`):** After the success path (where `step_result` is built), if `step.get("verify")` is truthy, invoke the agent again with the verify prompt. Parse the first line for PASS/FAIL. On FAIL, raise RuntimeError so retry policy applies. On PASS, attach `verificationResult` to the step result and step state.

**Journal:** Record `workflow.step.verified` event with pass/fail status and the verifier's reasoning.

### Change 2: `type: review` workflow step

**Files:** `charts/kubesynapse/templates/agentworkflow-crd.yaml`, `operator/worker.py`

**CRD:** Extend `type` enum from `[agent, loop]` to `[agent, loop, review]`. Add `reviewCriteria` (type: string) to step properties.

**Worker:** Add `execute_review_step()` following the pattern of `execute_loop_step()`. When the worker encounters `type: review`:
1. Gather `previous_output` from dependencies
2. Build a review prompt: "Review the following output against these criteria: {reviewCriteria}\n\nOutput:\n{previous_output}\n\nRespond with APPROVED or REJECTED on the first line, followed by specific findings."
3. Invoke the agentRef with this prompt
4. Parse APPROVED/REJECTED + findings from the response
5. On REJECTED, the step fails (retry policy applies); on APPROVED, it completes
6. Record `reviewResult` in step state with verdict + findings text

**Workflow routing:** The main loop in `run_workflow_worker()` already dispatches by step type (agent, loop, conditional). Add `review` to the dispatch.

### Change 3: `contextRef` for project context injection

**Files:** `charts/kubesynapse/templates/agentworkflow-crd.yaml`, `operator/worker.py`, `operator/utils.py`

**CRD:** Add `contextRef` (type: string) to `spec.properties` (workflow-level, not step-level). Points to a ConfigMap name in the same namespace.

**Worker (`run_workflow_worker`):** After loading the resource, if `spec.get("contextRef")`, read the ConfigMap via K8s CoreV1Api. Concatenate all data values into a project context string. Store it for the duration of the workflow run.

**Utils (`render_prompt`):** Add an optional `project_context` parameter. When provided, prepend it to the rendered prompt as:
```
[Project Context]
{context}
[End Project Context]

{rendered_prompt}
```

This is the BMAD "project-context.md" idea made Kubernetes-native. Teams create a ConfigMap with their tech stack, conventions, constraints, etc. and every workflow step automatically receives it.

---

## Phase 2: Execution Power

### Change 4: Formalized wave-based parallel execution

**Files:** `operator/utils.py`, `operator/worker.py`

The worker already runs frontier steps in parallel with ThreadPoolExecutor. This change formalizes it:

**Utils:** Add `compute_execution_waves()` that takes the step list + dependency graph and groups steps into numbered waves. Wave 0 = roots (no dependencies). Wave N = steps whose dependencies are all in waves 0..N-1.

**Worker:** Replace the main `while` loop's `ready_workflow_steps()` call with pre-computed waves. Execute each wave with ThreadPoolExecutor, collect all results, then advance. Log wave boundaries in the journal (`workflow.wave.started`, `workflow.wave.completed`). This is functionally similar to existing behavior but formalized and observable.

---

## Phase 3: User Experience

### Change 5: Next-action suggestion endpoint + UI verification badges

**API Gateway (`main.py`):** Add `GET /api/workflows/{workflow_name}/next-action` that examines the workflow's current state and returns:
```json
{
  "action": "string",
  "reason": "string",
  "priority": "info|warning|action"
}
```

Logic:
- Workflow completed, no eval exists → "Run an evaluation to validate results"
- Workflow failed at step X → "Review step X failure and retry the workflow"
- Eval failed → "Check failing test cases and fix the agent"
- Agent has no workflow → "Create a workflow to use this agent"
- All passing → "Results look good — deploy or promote"
- Step verification failed → "Step X verification failed — review the output"
- Review step rejected → "Review step X rejected the output — address findings"

**Web UI (`WorkflowManager.tsx`):** 
- Show verification result badges on step cards (✓ Verified / ✗ Verification Failed)
- Show review verdict + findings inline when a review step completes
- Show next-action suggestion card at the top of the workflow detail view

---

## Enhanced Workflow Example

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: feature-pipeline
spec:
  description: "Research → Implement → Review → Verify"
  input: "Add rate limiting to the API gateway"
  contextRef: project-rules  # ConfigMap with tech stack, conventions
  steps:
    - name: research
      agentRef: research-assistant
      prompt: "Research approaches for: {{input}}"
    - name: implement
      agentRef: developer-agent
      prompt: "Implement based on research: {{previous_output}}"
      dependsOn: [research]
      verify: "Run the test suite and confirm all tests pass"
    - name: code-review
      type: review
      agentRef: reviewer-agent
      reviewCriteria: "Code quality, test coverage, adherence to project conventions"
      dependsOn: [implement]
    - name: spec-review
      type: review
      agentRef: reviewer-agent
      reviewCriteria: "Does the implementation satisfy the original request? Edge cases?"
      dependsOn: [implement]
    - name: report
      agentRef: report-writer
      prompt: "Write summary of implementation and review findings: {{previous_output}}"
      dependsOn: [code-review, spec-review]
      requireApproval: true
```

Note: `code-review` and `spec-review` are independent (both depend only on `implement`) so they run in parallel in the same wave. `report` depends on both and runs in the next wave.

---

## File Change Map

| File | Changes |
|------|---------|
| `charts/kubesynapse/templates/agentworkflow-crd.yaml` | Add `verify`, `reviewCriteria` to step properties; add `review` to type enum; add `contextRef` to spec |
| `operator/utils.py` | Add `project_context` param to `render_prompt()`; add `compute_execution_waves()` |
| `operator/worker.py` | Verification logic in `execute_workflow_step()`; new `execute_review_step()`; context loading in `run_workflow_worker()`; wave-based execution loop |
| `api-gateway/main.py` | `GET /api/workflows/{name}/next-action` endpoint |
| `web-ui/src/components/WorkflowManager.tsx` | Verification badges, review findings, next-action card |
| `examples/sample-workflow.yaml` | Enhanced example with verify + review steps |

---

## Decisions

- Verification uses the SAME agentRef as the step (simplest). Future: allow `verifyAgentRef` override
- Review steps reuse the existing `agentRef` field to specify which agent does the review
- Context injection is additive (prepended), not replacing the prompt
- Wave execution is backward-compatible: workflows without explicit parallelism behave identically
- Next-action is advisory only, never auto-executing
- PASS/FAIL and APPROVED/REJECTED parsing is case-insensitive with fallback to "FAIL"/"REJECTED" on ambiguous responses

## Scope Boundaries

**Included:** CRD schema changes, worker execution logic, utils, API endpoint, UI rendering, example workflows
**Excluded:** New CRD types, CLI changes, catalog schema changes, role packs, context-budget monitoring, file-conflict detection in waves
