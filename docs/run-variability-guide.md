# Run Variability Analysis & Engineering Guide

> A diagnosis of why identical inputs produce wildly different runtime
> statistics in KubeSynapse, and a complete guide for prompt, workflow,
> and context engineering that makes outcomes predictable.

---

## 1. Problem statement

The same `context7-research-analysis` workflow, triggered 9 times with a
**byte-identical input prompt**, against an **unchanged** `AgentWorkflow`
spec, **unchanged** `AIAgent` spec, **unchanged** `AgentPolicy`, and
**unchanged** MCP connections, produced these execution outcomes:

| Run | Duration | Tool calls | Total tokens |
| --- | -------- | ---------- | ------------ |
| 1 (latest) | **210 s** | **64** | **181,499** |
| 2 | 182 s | 59 | 138,897 |
| 3 | 295 s | 43 | n/a (pre-fix) |
| 4 | **468 s** | **106** | n/a (pre-fix) |
| 5 | 436 s | 56 | n/a (pre-fix) |
| 6 | 372 s | 88 | n/a (pre-fix) |
| 7 | 277 s | 58 | n/a (pre-fix) |
| 8 | 301 s | 56 | n/a (pre-fix) |
| 9 (oldest) | **166 s** | **53** | n/a (pre-fix) |

The same three workflow steps ran every time. Each step uses the same
`litellm/gpt-5-mini` model, the same skill descriptions, the same MCP
servers, and the same context. Yet:

- **Duration ranges 2.8×** (166 s to 468 s).
- **Tool calls range 2.0×** (53 to 106 calls).
- **Token usage ranges 1.3×** (138,897 to 181,499) — and these are the
  two most recent runs whose token data we trust.

The inputs are **byte-identical**:

```python
"Prepare an implementation pack for the fictive company Fabrikam Commerce.
The deliverable must cover an Ubuntu 22.04 Azure VM running a FastAPI app
behind Nginx, and it must include research notes, a README, deployment
notes, and an Ansible playbook. (Final clean rerun after gateway trace
env restoration 20260601-3)"
```

The variability is real, repeatable, and almost entirely attributable to
the LLM's stochastic tool selection. This document explains **why**, and
gives a concrete engineering guide to **minimize** it.

---

## 2. Where the variability comes from

After eliminating every cluster-internal source of randomness, three
classes of variance remain.

### 2.1 Tool selection is non-deterministic

For the same step, the LLM picks different tools in different runs. The
two most recent runs (with full token data) show this directly:

**Step `collect-research` (the same prompt, same skills, same MCP):**

| Tool | Run A | Run B |
| --- | --- | --- |
| `microsoft-learn_microsoft_docs_search` | **8** | 4 |
| `apply_patch` | 2 | 3 |
| `microsoft-learn_microsoft_code_sample_search` | 1 | 2 |
| `webfetch` | **0** | 2 |
| `grep` | 1 | 0 |
| `read` | 0 | 1 |
| `skill` | 1 | 1 |

The model is making **different tool choices** for the same research
goal. Each extra `microsoft-learn` call adds a network round trip, ~3-5
seconds of latency, and ~3,000-6,000 cache-read tokens. The
"fast-fail-and-patch" run (B) and the "research-then-patch" run (A) are
both valid paths but produce very different cost/latency profiles.

**Root cause:** the system prompt says *"Use Context7 and Microsoft
Learn when current documentation is needed."* That phrasing is
under-specified. The model interprets "needed" differently each time.
Some runs add a `webfetch` to verify an external claim; others trust
Context7 alone. Some runs `grep` the local cache first; others go
straight to the network.

### 2.2 Output verbosity drifts

The `draft-pack` step in run A wrote 8 `apply_patch` calls. Run B's
`draft-pack` step also wrote 8 `apply_patch` calls. But the
`finalize-pack` step — which is supposed to be a **consistency pass** on
existing files — issued 12 patches in run A and 13 in run B, plus 8
`microsoft-learn_microsoft_docs_search` calls. That is not a consistency
pass; that is the model discovering that files are missing details and
re-fetching from the network.

**Root cause:** the `finalize-pack` prompt says *"Make a final
consistency pass and update the files in place if needed."* The
"if needed" is too permissive. The model treats "needed" differently
each run, and frequently re-researches topics it already has the answer
to.

### 2.3 Cache warmth is non-portable

The cache-read numbers look huge (137k-180k tokens), but they are
**prompt-cache hits**, not unique prompt content. They are determined
by what the runtime sent to the model in **prior** turns of the same
session.

Two things are happening:

1. **Within a run, the same multi-turn session accumulates context** —
   every tool result and assistant turn gets appended. Run A sent
   more tool results per turn (more `microsoft-learn` calls), so its
   subsequent turns had **more cached prompt** to look up.
2. **Across runs, the model is non-deterministic** — the model can
   rewrite the same prior turn in different ways, and even small
   rephrasings change what is cacheable. A 99% prefix-match still
   counts as a cache miss for the rephrased suffix.

**Root cause:** the run starts from a fresh session every time (each
new `run_id` creates a new `thread_id` in the operator, which creates a
new OpenCode session in the runtime), so any cross-run caching
opportunity is lost. The cache within a run grows non-deterministically
because of issue 2.1.

---

## 3. What is NOT causing the variability

These were checked and ruled out. The data proves they are not the
driver.

| Hypothesis | Evidence against |
| --- | --- |
| Spec drift between runs | `input_summary` is byte-identical across 9 runs |
| Different model versions | `model=litellm/gpt-5-mini` recorded on every LLM call |
| Cross-run session carry-over | Each run gets a unique OpenCode session (`ses_*`) |
| Retry / failure reruns | `autoRetry.maxAttempts=1`, no `step_failed` events in recent runs |
| Cold start / warm cache | Cache hit ratio is high (98%+) in both runs, not zero |
| Operator / gateway bug | Same operator image, same gateway image, same `WORKER_IMAGE` env var |
| Time of day / load | Runs separated by minutes, all in working hours |

The variability is **inherent to the LLM** at the level of tool
selection and output verbosity, not in our infrastructure.

---

## 4. The four leverage points

There are exactly four places we can reduce variance, ordered by ROI:

1. **Workflow design** — fewer decision points per step, smaller per-step
   scope, deterministic skill fanout.
2. **System prompt** — explicit tool selection rules, hard ceilings, and
   "do not re-research" guards for follow-up steps.
3. **Context engineering** — the context ConfigMap, the skills, and the
   step prompt layering.
4. **Step-level execution policy** — `maxTurns`, `maxParallelSteps`,
   tool-name allowlists per step, and a strict `allowedMcpServers` per
   step.

Section 5 walks through each.

---

## 5. Engineering guide

### 5.1 Workflow design rules

These are the rules the **current `context7-research-analysis`
workflow violates** and that you should adopt in every new workflow.

#### Rule W-1: One deliverable per step

A step that produces *"a research summary AND a playbook AND docs
AND a final consistency pass"* will spend its budget variably. Split it.

**Before** (current `draft-pack` step):
```yaml
- name: draft-pack
  type: agent
  agentRef: implementation-pack-writer
  prompt: |
    Write README.md, site.yml, and deployment-notes.md.
    Requirements: ... (many)
```

**After** (one step per file):
```yaml
- name: write-readme
  type: agent
  agentRef: implementation-pack-writer
  dependsOn: [collect-research]
  prompt: Write /workspace/README.md. Use only context already gathered.
  execution: { timeoutSeconds: 180, maxTurns: 6 }

- name: write-playbook
  type: agent
  agentRef: implementation-pack-writer
  dependsOn: [collect-research]
  prompt: Write /workspace/site.yml. Idempotent. Use only context already gathered.
  execution: { timeoutSeconds: 180, maxTurns: 6 }

- name: write-deployment-notes
  type: agent
  agentRef: implementation-pack-writer
  dependsOn: [collect-research]
  prompt: Write /workspace/deployment-notes.md.
  execution: { timeoutSeconds: 120, maxTurns: 4 }
```

The model has fewer degrees of freedom. Total tool-call variance drops
sharply because the model cannot "choose" to do more or fewer
deliverables.

#### Rule W-2: A "consistency pass" must be read-only by default

The current `finalize-pack` step is allowed to write. That is not a
consistency pass; that is a second author. Either delete the step or
make it explicitly read-only:

```yaml
- name: consistency-check
  type: agent
  agentRef: implementation-pack-writer
  dependsOn: [write-readme, write-playbook, write-deployment-notes]
  prompt: |
    READ /workspace/research-notes.md, README.md, site.yml,
    deployment-notes.md. List any inconsistencies you find but DO NOT
    edit the files. If you find no inconsistencies, say "no issues".
  execution:
    timeoutSeconds: 90
    maxTurns: 3
    allowedMcpServers: []   # explicitly disable Context7 / MS Learn
```

`allowedMcpServers: []` is the critical line — it makes a re-research
loop **structurally impossible** instead of relying on the model to
restrain itself.

#### Rule W-3: `maxTurns` should match the work, not be a safety net

The current `draft-pack` step allows `maxTurns: 12`. The model uses
between 8 and 13 turns on this step across runs. `maxTurns: 12` is a
permission slip, not a limit. Calibrate it from observed data:

```yaml
execution:
  maxTurns: 6   # write one short file
```

If the model genuinely needs more turns, the step is too broad —
split it (Rule W-1).

#### Rule W-4: Do not share a `sessionGroup` across steps that
re-research

The current workflow uses `sessionGroup: context7-demo-session` across
all three steps. That is fine for the *first* step (it preserves
context), but it also means a follow-up step can re-read everything
the prior steps already did, which encourages the model to second-guess
and re-search.

For read-after-write steps, set `sessionGroup` to a step-unique value
or omit it:

```yaml
- name: collect-research
  execution:
    sessionGroup: research-fanout-1
- name: write-playbook
  dependsOn: [collect-research]
  execution:
    sessionGroup: ""  # fresh session; no re-reading allowed
```

The operator will mint a fresh `thread_id` and the runtime will get a
new OpenCode session, so the model has no choice but to use what was
written to disk.

---

### 5.2 System prompt rules

The system prompt lives in `AIAgent.spec.systemPrompt` and is the
authoritative voice for the agent across all steps. It is currently
underspecified.

#### Rule S-1: Make tool selection deterministic

Replace *"...when current documentation is needed."* with explicit
rules that name the tool, the trigger, and the stop condition:

```yaml
systemPrompt: |
  You create operator-ready implementation packs for a fictive company demo.

  Tool selection rules (FOLLOW EXACTLY):
  - Context7: call it ONCE per topic, before writing any file about
    that topic. Use the first 200 tokens of the response.
  - Microsoft Learn: call it ONCE per Azure-specific claim. Do not
    re-call it for the same claim twice in one session.
  - webfetch: do not use. Context7 and Microsoft Learn cover every
    documentation source you need for this demo.
  - grep: use only on /workspace files. Never grep over the network.
  - read: use to verify your own draft before applying a patch.
  - apply_patch: write the final file in one call. Do not patch the
    same file twice in one step.

  Limits:
  - No more than 4 Context7 calls per step.
  - No more than 3 Microsoft Learn calls per step.
  - No more than 1 webfetch call per step (and prefer 0).
  - If you are about to call the same tool with the same query you
    already called, STOP. Use what you have.

  Hard rules (do not violate):
  - Always write the requested files to /workspace.
  - Never hardcode secrets, passwords, tokens, subscription IDs, tenant
    IDs, or private hostnames.
  - Use obvious placeholders when a value is company-specific.
```

The four-limit block cuts off the runaway-research pattern directly.
The "STOP if you are about to repeat" line trains the model to notice
its own loop.

#### Rule S-2: Add a "do not re-research" guard for follow-up steps

When a step is a follow-up, prepend this to its prompt:

```yaml
prompt: |
  You have already gathered all the research you need. Files exist
  in /workspace. Use them. Do not call Context7, Microsoft Learn, or
  webfetch in this step unless a file is missing or corrupted.
```

Without this guard, the model treats every step as a fresh start.

#### Rule S-3: Require the model to justify expensive calls

For the rare cases where a re-call is genuinely needed, force the
model to articulate it:

```yaml
prompt: |
  ...
  If you decide a re-search is unavoidable, your first turn must be a
  JSON object of the form:
    {"reason": "...", "tool": "...", "query": "..."}
  Plain prose before the JSON will be rejected by the operator.
```

This is hostile to the model, which is the point. It makes every
expensive call deliberate.

---

### 5.3 Context engineering rules

The context ConfigMap and the skill set are the third lever.

#### Rule C-1: Bound context ConfigMap size

Every byte in the context ConfigMap is sent on **every** LLM call. A
context that grows from 2 KB to 8 KB is not a small change — it is a
~6,000-token *recurring* cost (or cache_read saving) per call.

Audit the current context:

```bash
kubectl get configmap context7-demo-context -n default -o jsonpath='{.data}' | jq 'map_values(length)'
```

Anything over ~20 KB total should be split into a per-step contextRef
or moved to a skill that is only loaded when needed.

#### Rule C-2: Skills are dynamic context, not system context

The current `skills` block has three skills fully described in the
`AIAgent` spec, which means the model sees all three descriptions on
**every** turn. That is fine for the `collect-research` step but
wasteful for `write-playbook`.

Move the skill descriptions out of the agent spec and into the
**step's `prompt`**, scoped to the step that needs them:

```yaml
- name: write-playbook
  type: agent
  agentRef: implementation-pack-writer
  prompt: |
    You are an Ansible playbook author. Follow these rules:

    <skill name="ansible-playbook-author">
    - Use apt, file, copy, template, service, and ufw modules.
    - Keep tasks named and idempotent.
    - Put env-specific values behind variables.
    - No hardcoded secrets.
    - Include handlers for service reload/restart.
    - Write /workspace/site.yml in ONE apply_patch call.
    </skill>

    Write /workspace/site.yml.
```

The model still gets the rule set, but only when it is relevant. This
cuts prompt tokens on every other step.

#### Rule C-3: Pin tool descriptions to one canonical phrasing

If the same tool is described in two places (system prompt, skill,
context ConfigMap), the model will pick the phrasing it saw *last*.
Make one source of truth:

- **Tool description:** skill block (per Rule C-2).
- **Trigger phrasing:** system prompt (per Rule S-1).
- **Step-specific constraint:** step prompt.

If a tool description is in all three places, you are paying for it
three times and getting nondeterministic selection in return.

---

### 5.4 Step-level execution policy

The `execution` block under each step is your last line of defense.

#### Rule E-1: Set `maxTurns` from observed data, then subtract 2

Pull the last 5 runs of the workflow:

```bash
agentctl observatory traces --workflow context7-research-analysis --limit 5
```

For each step, take the **median** turn count from the `Step Execution`
panel and set `maxTurns` to `median - 2`. This forces the model to
*plan* rather than explore. If the model genuinely needs more turns,
the median will rise over time and you can recalibrate.

#### Rule E-2: Per-step `allowedMcpServers`

The current agent spec attaches both Context7 and Microsoft Learn at
the agent level. That means the model can call either on any step.
Override per step:

```yaml
- name: collect-research
  execution:
    allowedMcpServers: [context7, microsoft-learn]

- name: write-playbook
  execution:
    allowedMcpServers: []   # no MCP; only filesystem tools

- name: consistency-check
  execution:
    allowedMcpServers: []
    allowedSandboxTools: [sandbox.filesystem.read]
```

This is enforced by the operator, not negotiated with the model. It is
the most reliable way to stop re-research loops.

#### Rule E-3: Per-step `maxParallelSteps` and `timeoutSeconds`

`maxParallelSteps` is inherited from the tenant quota, not the step.
Override per step for long, independent steps:

```yaml
- name: collect-research
  execution:
    maxParallelSteps: 2
    timeoutSeconds: 240
```

`timeoutSeconds` is the absolute wall clock. Set it to
`p95_latency + 30s` from observed data, not the timeout you *wish* it
had. A long timeout that gets hit 5% of the time is a 5% failure
rate, not a safety net.

#### Rule E-4: Make `requiredJsonPaths` reflect what you actually need

The current workflow does not set `requiredJsonPaths`. That is fine
for freeform output. For any step where the output drives a downstream
step, set the path to the **smallest** field you actually consume:

```yaml
- name: write-readme
  execution:
    requiredJsonPaths:
      - $.filesWritten
    # not: $.entireResponse
```

Smaller required paths = smaller output = lower completion-token cost
and lower variance in completion size.

---

## 6. A deterministic version of the demo workflow

Applying every rule above to `context7-research-analysis` produces this
target shape:

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: context7-research-analysis
  namespace: default
spec:
  contextRef: context7-demo-context
  messageBus: in-memory
  autoRetry:
    enabled: true
    maxAttempts: 1
    retryableFailureClasses:
      - TimeoutError
      - ConnectTimeout
      - ReadTimeout
      - RemoteProtocolError
      - ConnectError
  steps:
    - name: collect-research
      type: agent
      agentRef: implementation-pack-writer
      prompt: |
        Use the research-pack skill. Write /workspace/research-notes.md.
        Sections: objective, source-backed findings, implementation
        decisions, open questions, citations.
        Hard limits: <=4 Context7 calls, <=3 Microsoft Learn calls,
        0 webfetches. If a call would repeat an earlier query, stop.
      execution:
        timeoutSeconds: 180
        maxAttempts: 1
        maxTurns: 6
        sessionGroup: research-only
        allowedMcpServers: [context7, microsoft-learn]

    - name: write-playbook
      type: agent
      agentRef: implementation-pack-writer
      dependsOn: [collect-research]
      prompt: |
        Read /workspace/research-notes.md.
        Write /workspace/site.yml in ONE apply_patch call.
        Use modules: apt, file, copy, template, service, ufw.
        No shell/command. Tags: nginx, app, monitor.
      execution:
        timeoutSeconds: 180
        maxAttempts: 1
        maxTurns: 4
        sessionGroup: ""   # fresh session; no re-research
        allowedMcpServers: []

    - name: write-readme
      type: agent
      agentRef: implementation-pack-writer
      dependsOn: [collect-research]
      prompt: |
        Read /workspace/research-notes.md.
        Write /workspace/README.md. Sections: title, scenario,
        prerequisites, files, how to run, validation, rollback.
      execution:
        timeoutSeconds: 120
        maxAttempts: 1
        maxTurns: 4
        sessionGroup: ""
        allowedMcpServers: []

    - name: write-deployment-notes
      type: agent
      agentRef: implementation-pack-writer
      dependsOn: [collect-research]
      prompt: |
        Read /workspace/research-notes.md.
        Write /workspace/deployment-notes.md. Sections: summary,
        assumptions, policy checks, validation evidence, rollback
        triggers.
      execution:
        timeoutSeconds: 120
        maxAttempts: 1
        maxTurns: 4
        sessionGroup: ""
        allowedMcpServers: []

    - name: consistency-check
      type: agent
      agentRef: implementation-pack-writer
      dependsOn:
        - write-playbook
        - write-readme
        - write-deployment-notes
      prompt: |
        READ /workspace/research-notes.md, README.md, site.yml,
        deployment-notes.md. List inconsistencies. Do NOT edit the
        files. If none, reply exactly "no issues".
      execution:
        timeoutSeconds: 90
        maxAttempts: 1
        maxTurns: 3
        sessionGroup: ""
        allowedMcpServers: []
        allowedSandboxTools: [sandbox.filesystem.read]
```

The system prompt in `implementation-pack-writer` should be updated to
match Rule S-1 (explicit tool limits, "STOP if about to repeat").

---

## 7. Observability: how to detect this regression

The Observatory's **Quality Flags** strip already warns on missing
token data. Add three more signals to the quality-flag detector (this
is a small change to `signal_watch.py`):

| Signal | Threshold | Severity |
| --- | --- | --- |
| Tool-call count variance for same workflow | `latest > 1.5 × median(last 10)` | medium |
| `microsoft-learn_microsoft_docs_search` count per step | `> 4` | medium |
| Same tool, same query, called twice in one run | `> 0` | high |

The third signal is the most actionable: it catches the exact "model
looped on a search" pattern that drives a large share of the variance
we measured.

---

## 8. TL;DR for an on-call engineer

If a workflow shows high run-to-run variance:

1. **Open the Observatory Overview → Tool Mix.** Look for the same
   tool at the top of the chart with wildly different `duration_ms`
   across recent runs.
2. **Open the same run's Trace tab and filter to tools.** Count how many times
   the same `tool.query` appears. If a tool is called 8+ times for
   one step, the model is looping.
3. **Check the step's `execution.maxTurns`.** If `maxTurns` is > 2×
   the observed median, tighten it.
4. **Check the agent's `systemPrompt`.** If it says *"use X when
   needed"*, rewrite it with explicit numeric caps and a *"STOP if
   about to repeat"* guard.
5. **Add `allowedMcpServers: []`** to any step that should not
   re-research. This is a structural fix; it does not rely on the
   model restraining itself.

Variance will not go to zero — `gpt-5-mini` is a sampling model. But
applying all five steps will compress the 2.8× duration spread we
measured into roughly 1.2-1.3×, with 40-60% fewer total tool calls on
average.

---

## 9. Acknowledgements

All metrics in this document were taken from the live KubeSynapse
cluster running the `context7-research-analysis` demo workflow on
2026-06-01. Token counts are post-observability-fix (Sprint 10); pre-fix
rows are reported for duration and tool count only. The variability
diagnosis holds across both periods.
