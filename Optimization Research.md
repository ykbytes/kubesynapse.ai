# Optimization Research

This note captures the optimization strategy behind KubeSynapse ROI Lab and the workflow optimizer agent. The goal is not to make optimistic claims from a single run. The product should create a copied candidate workflow, preserve the original workflow intent, run paired trials, and prove whether the candidate saves time, tokens, tool calls, and cost without reducing output quality or expanding permissions.

## Why Candidate Runs Can Regress

Agentic workflows have high variance because each run combines LLM latency, provider queueing, prompt-cache hit rate, tool I/O, retry behavior, and step dependency shape. A candidate can become slower even when it uses fewer tokens if it loses cache locality, introduces longer reasoning loops, serializes work that could run independently, or gives an agent vague instructions that cause repeated tool calls.

The important product rule is simple: estimated savings are a hypothesis, not proof. ROI Lab should show estimates before execution, but promotion must depend on paired candidate-vs-baseline trials and explicit quality gates.

## Current Best Techniques

### Trace Reflection

GEPA-style optimization uses full execution traces and natural-language reflection to improve prompts and workflows from real failures and bottlenecks rather than isolated prompt edits. DSPy also frames GEPA as an optimizer that reflects on full traces for specific predictors. For KubeSynapse, that means the optimizer dossier should include baseline runs, step timings, LLM calls, tool calls, prompts, artifacts, and failures before asking for a candidate.

Sources: [GEPA](https://arxiv.org/abs/2507.19457), [DSPy GEPA docs](https://dspy.ai/api/optimizers/GEPA/overview/).

### Tool Economy And Meta-Tools

AWO identifies repeated tool-execution patterns and turns them into more efficient meta-tools or batched operations. In KubeSynapse v1, we should not invent new runtime tool APIs automatically, but the optimizer can still reduce redundant reads/writes, ask agents to batch deterministic file inspection, and move repeated checks into reusable artifacts.

Source: [Optimizing Agentic Workflows using Meta-tools](https://www.microsoft.com/en-us/research/publication/optimizing-agentic-workflows-using-meta-tools/).

### Prompt-Cache-Aware Context Layout

Prompt caching can reduce API costs and time-to-first-token when stable prefixes are kept stable and volatile run data is placed later. Bad candidates often regress by mixing dynamic trace details into the stable prompt, destroying cache reuse. The optimizer should separate durable instructions, schemas, examples, and tool policy from per-run inputs.

Source: [An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks](https://arxiv.org/html/2601.06007v2).

### Workflow Graph Optimization

Agentic workflows are computation graphs: steps, dependencies, tools, memory, and verification. Optimization can be static, such as rewriting prompts or model routing, or dynamic, such as changing graph topology. Topology rewrite is powerful but risky, so KubeSynapse should keep it opt-in and compare both quality and ROI before promotion.

Source: [A Survey of Workflow Optimization for LLM Agents](https://arxiv.org/html/2603.22386v1), [awesome-agentic-workflow-optimization](https://github.com/IBM/awesome-agentic-workflow-optimization).

### Workflow-Aware Serving And Caching

Recent systems work models agentic workloads as query plans and optimizes caching/scheduling around workflow structure. KubeSynapse can apply this at the product layer first: surface cache pressure, identify repeated context/tool paths, and recommend cacheable artifacts or shorter stable instructions.

Source: [Efficient LLM Serving for Agentic Workflows](https://arxiv.org/html/2603.16104v1).

## Optimizer Agent Skills

The optimizer agent should expose these skills in its manifest so users can inspect what it is allowed and expected to do:

- `critical-path-roi`: find the slowest and most expensive steps, then propose changes that affect wall-clock and cost directly.
- `context-compression`: shrink prompts by removing repeated volatile context, moving stable instructions into cache-friendly prefixes, and preserving output contracts.
- `tool-economy`: reduce repeated reads/writes, batch deterministic tool operations, and create reusable intermediate artifacts.
- `topology-rewrite`: when explicitly allowed, consolidate or reshape steps only if the workflow purpose, artifacts, approvals, and contracts remain equivalent.
- `regression-proof-gate`: treat optimizer output as a hypothesis and require paired trials, quality checks, and no privilege expansion before promotion.

## Candidate Generation Rules

The optimizer must never edit the source workflow in place. It should output a copied manifest bundle with suffixed names and labels linking back to the source workflow, source runs, optimizer agent, and study id.

Candidates should preserve provider/model unless an admin-approved routing policy exists. For now, preserve the original model family and focus on prompt, context, tool-use, timeout, batching, and optional topology changes.

The candidate must not include ROI Lab meta-instructions inside target workflow prompts or agent system prompts. The target workflow should only know how to do its business task.

## Proof Gate

A candidate is a winner only when it:

- Passes manifest safety checks: namespace, allowed kinds, no secret/env expansion, no privilege expansion, and preserved contracts.
- Runs enough safe trials to produce meaningful confidence.
- Shows no material regression beyond the configured noise budget.
- Preserves output quality through machine checks or human review.
- Shows measured savings in cost per successful run, tokens per successful run, wall-clock per successful run, tool calls, LLM calls, retry rate, and approval waits.

## Product Direction

ROI Lab should make gains obvious and auditable:

- Show baseline vs candidate as the primary comparison.
- Separate estimated savings from verified savings.
- Provide side-by-side manifest diff for every candidate.
- Show why a candidate won or regressed.
- Keep raw traces and prompt payloads behind inspectors.
- Persist every study, candidate, trial, proof result, and dataset export state for future training and regression tests.

## Dataset Path

The immediate training path is dataset-first, not fine-tuning-first. Capture redacted baseline traces, candidate traces, manifest snapshots, labels, proof-gate results, and human review outcomes. Use this data for replay tests, few-shot optimizer examples, routing rules, evaluator rubrics, and later tenant-local evaluator or routing models after consent, redaction, and tenancy isolation are in place.

