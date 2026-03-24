# Context Architect — Implementation Plan

> This file is the single source of truth for the memory/context architecture.
> The **Context Architect** agent reads this file before every implementation task.

---

## Status Legend

- [ ] Not started
- [~] In progress
- [x] Done

---

## Phase 1 — Session/State Layer (ADK Short-Term)

**Goal:** Give every agent a clean short-term working context per conversation/task.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 1.1 | Define `SessionState` schema (current messages, tool results, scratchpad, token count) | `agent-runtime/memory/session_state.py` (new) | [x] |
| 1.2 | Integrate ADK `Session` / `State` or equivalent wrapper into agent runtime | `agent-runtime/agent_logic.py` | [x] |
| 1.3 | Add session persistence (SQLite for dev, Redis/Postgres for prod) | `agent-runtime/memory/session_store.py` (new), `operator/state_store.py` | [x] |
| 1.4 | Add token-budget tracking per session so downstream layers know remaining capacity | `agent-runtime/memory/session_state.py` | [x] |
| 1.5 | Write tests for session lifecycle (create, update, expire, resume) | `agent-runtime/tests/test_session_state.py` (new) | [x] |

---

## Phase 2 — Working Memory & Compaction

**Goal:** Prevent long sessions from polluting the prompt. Summarize and compact.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 2.1 | Implement rolling-summary compaction (recursive summarization when token count exceeds threshold) | `agent-runtime/memory/compaction.py` (new) | [ ] |
| 2.2 | Add a `WorkingMemory` buffer that sits between session state and the prompt | `agent-runtime/memory/working_memory.py` (new) | [ ] |
| 2.3 | Wire compaction into the agent loop — trigger after every N turns or when tokens > budget | `agent-runtime/agent_logic.py` | [ ] |
| 2.4 | Add configurable token-budget reservation for memory retrieval results | `agent-runtime/memory/working_memory.py` | [ ] |
| 2.5 | Write tests for compaction (verify summary quality, token reduction, no data loss) | `agent-runtime/tests/test_compaction.py` (new) | [ ] |

---

## Phase 3 — Long-Term Memory API & Backends

**Goal:** Persistent memory that survives across sessions: semantic, episodic, procedural.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 3.1 | Define `MemoryService` interface (add, search, delete, update) compatible with ADK contract | `agent-runtime/memory/memory_service.py` (new) | [ ] |
| 3.2 | Implement `InMemoryBackend` for dev/test | `agent-runtime/memory/backends/in_memory.py` (new) | [ ] |
| 3.3 | Implement `SemanticStore` backend (vector DB — ChromaDB/pgvector) for fact storage | `agent-runtime/memory/backends/semantic_store.py` (new) | [ ] |
| 3.4 | Implement `EpisodicStore` backend for task trajectories and outcomes | `agent-runtime/memory/backends/episodic_store.py` (new) | [ ] |
| 3.5 | Implement `ProceduralStore` backend for learned rules, preferences, corrections | `agent-runtime/memory/backends/procedural_store.py` (new) | [ ] |
| 3.6 | Implement `EntityGraph` backend for entity relationships and temporal indexing | `agent-runtime/memory/backends/entity_graph.py` (new) | [ ] |
| 3.7 | Add `MultiMemoryService` that composes all backends behind the single interface | `agent-runtime/memory/multi_memory.py` (new) | [ ] |
| 3.8 | Add memory config (which backends enabled, connection strings, embedding model) | `agent-runtime/memory/config.py` (new), `agent-runtime/env_utils.py` | [ ] |
| 3.9 | Write tests for each backend and the composed service | `agent-runtime/tests/test_memory_backends.py` (new) | [ ] |

---

## Phase 4 — Memory Ingestion & Consolidation

**Goal:** After each session/task, extract durable memories and resolve conflicts.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 4.1 | Implement `after_session` callback that triggers memory ingestion | `agent-runtime/memory/ingestion.py` (new), `agent-runtime/agent_logic.py` | [ ] |
| 4.2 | Fact extractor — pull stable facts from conversation, deduplicate, tag with provenance | `agent-runtime/memory/extractors/fact_extractor.py` (new) | [ ] |
| 4.3 | Episode extractor — capture task trajectory (goal, steps, outcome, lessons) | `agent-runtime/memory/extractors/episode_extractor.py` (new) | [ ] |
| 4.4 | Conflict detector — find contradictions between new and existing facts | `agent-runtime/memory/extractors/conflict_detector.py` (new) | [ ] |
| 4.5 | Entity resolver — merge co-referent entities, update graph | `agent-runtime/memory/extractors/entity_resolver.py` (new) | [ ] |
| 4.6 | Profile upserter — update user/agent profile from corrections and preferences | `agent-runtime/memory/extractors/profile_upserter.py` (new) | [ ] |
| 4.7 | Add fact versioning (valid_from, valid_to, confidence, source) to semantic store | `agent-runtime/memory/backends/semantic_store.py` | [ ] |
| 4.8 | Run consolidation as a background task (not in hot path) | `agent-runtime/memory/ingestion.py` | [ ] |
| 4.9 | Write tests for extraction, conflict detection, and entity resolution | `agent-runtime/tests/test_ingestion.py` (new) | [ ] |

---

## Phase 5 — Retrieval Orchestrator & Fusion

**Goal:** Multi-strategy retrieval so agents find the right memories efficiently.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 5.1 | Implement retrieval orchestrator with pluggable strategies | `agent-runtime/memory/retrieval/orchestrator.py` (new) | [ ] |
| 5.2 | Semantic search strategy (vector similarity) | `agent-runtime/memory/retrieval/strategies/semantic.py` (new) | [ ] |
| 5.3 | Keyword search strategy (BM25) | `agent-runtime/memory/retrieval/strategies/keyword.py` (new) | [ ] |
| 5.4 | Temporal search strategy (recent-first, time-windowed) | `agent-runtime/memory/retrieval/strategies/temporal.py` (new) | [ ] |
| 5.5 | Graph/entity search strategy (traverse relationships) | `agent-runtime/memory/retrieval/strategies/graph.py` (new) | [ ] |
| 5.6 | Implement Reciprocal Rank Fusion (RRF) to merge results from all strategies | `agent-runtime/memory/retrieval/fusion.py` (new) | [ ] |
| 5.7 | Add cross-encoder reranker for final result ordering | `agent-runtime/memory/retrieval/reranker.py` (new) | [ ] |
| 5.8 | Wire retrieval into agent loop — query memory before generating response | `agent-runtime/agent_logic.py` | [ ] |
| 5.9 | Add `PreloadMemory` / `LoadMemory` tool equivalents for agent self-service retrieval | `agent-runtime/memory/retrieval/tools.py` (new) | [ ] |
| 5.10 | Write tests for retrieval fusion and reranking | `agent-runtime/tests/test_retrieval.py` (new) | [ ] |

---

## Phase 6 — Consistency Controls

**Goal:** Prevent contradictions, stale facts, and hallucinated memories.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 6.1 | Canonical entity registry — single source of truth per entity | `agent-runtime/memory/consistency/entity_registry.py` (new) | [ ] |
| 6.2 | Fact versioning enforcement — always attach valid_from, valid_to, confidence, provenance | `agent-runtime/memory/consistency/versioning.py` (new) | [ ] |
| 6.3 | Conflict resolution rules (most-recent-wins, highest-confidence-wins, user-correction-wins) | `agent-runtime/memory/consistency/conflict_rules.py` (new) | [ ] |
| 6.4 | Contradiction detection at retrieval time — flag and resolve before sending to prompt | `agent-runtime/memory/consistency/contradiction_check.py` (new) | [ ] |
| 6.5 | Write tests for consistency controls | `agent-runtime/tests/test_consistency.py` (new) | [ ] |

---

## Phase 7 — Reflection & Policy Memory

**Goal:** Store and use learned rules, preferences, and corrections.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 7.1 | Implement procedural memory read/write — store rules learned from user corrections | `agent-runtime/memory/reflection/procedural.py` (new) | [ ] |
| 7.2 | Auto-detect repeated corrections and promote to policy rules | `agent-runtime/memory/reflection/rule_learner.py` (new) | [ ] |
| 7.3 | Inject relevant policy/procedural memories into system prompt before each turn | `agent-runtime/agent_logic.py` | [ ] |
| 7.4 | Add observation consolidation — merge similar observations into higher-level insights | `agent-runtime/memory/reflection/observation_consolidator.py` (new) | [ ] |
| 7.5 | Write tests for reflection and rule learning | `agent-runtime/tests/test_reflection.py` (new) | [ ] |

---

## Phase 8 — Evaluation & Metrics

**Goal:** Prove the memory system works and catch regressions.

| # | Task | Files to Edit/Create | Status |
|---|------|----------------------|--------|
| 8.1 | Define evaluation metrics: recall@k, consistency rate, contradiction rate, latency p50/p95, token savings | `agent-runtime/memory/eval/metrics.py` (new) | [ ] |
| 8.2 | Build eval harness — replay recorded sessions and score memory quality | `agent-runtime/memory/eval/harness.py` (new) | [ ] |
| 8.3 | Add Prometheus metrics for memory retrieval latency and cache hits | `agent-runtime/memory/eval/prometheus_metrics.py` (new) | [ ] |
| 8.4 | Add inconsistency regression test suite | `agent-runtime/tests/test_memory_eval.py` (new) | [ ] |

---

## Revised Architecture (Reference)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Runtime                            │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ Session/State│───▶│   Working    │───▶│  Prompt Builder  │  │
│  │   (ADK)      │    │   Memory     │    │  (token-budget)  │  │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘  │
│         │                   │                     │             │
│         │ compaction        │ retrieval            │ inject      │
│         ▼                   ▼                     ▼             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  Compaction   │    │  Retrieval   │    │   LLM Call       │  │
│  │  (summarize)  │    │  Orchestrator│    │                  │  │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘  │
│         │                   │                     │             │
│         ▼                   ▼                     ▼             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Memory Service Interface (ADK)              │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│  ┌──────────┬───────────┬───┴──────┬──────────────┐            │
│  │ Semantic  │ Episodic  │ Entity   │ Procedural   │            │
│  │ Store     │ Store     │ Graph    │ Store        │            │
│  │ (vectors) │ (traject.)│ (nodes)  │ (rules)      │            │
│  └──────────┴───────────┴──────────┴──────────────┘            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Consolidation (background)                     │  │
│  │  fact-extract │ episode-extract │ conflict-detect │ merge │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Consistency Controls                           │  │
│  │  entity-registry │ versioning │ provenance │ resolution  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Reflection / Policy                            │  │
│  │  procedural-mem │ rule-learner │ observation-consolidate  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │           Evaluation                                     │  │
│  │  recall@k │ consistency │ contradiction │ latency │ cost  │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow — Write Path

```
Agent turn completes
  → after_session callback
    → Compaction (summarize if over token budget)
    → Fact Extractor → Semantic Store (upsert with versioning)
    → Episode Extractor → Episodic Store
    → Entity Resolver → Entity Graph
    → Conflict Detector → flag / auto-resolve
    → Profile Upserter → Procedural Store
```

### Data Flow — Read Path

```
New user query arrives
  → Retrieval Orchestrator
    → Semantic search (vector similarity)
    → Keyword search (BM25)
    → Temporal search (recency-weighted)
    → Graph search (entity traversal)
    → RRF Fusion
    → Cross-encoder Rerank
    → Token-budget trim
  → Inject into Working Memory
  → Build prompt (system + policy + memories + session + user query)
  → LLM call
```

### ADK Integration Points

| ADK Concept | Our Layer | Integration |
|---|---|---|
| `Session` / `State` | Session/State layer | Direct use for short-term context |
| `after_agent_callback` | Ingestion | Trigger consolidation pipeline |
| `MemoryService` interface | Memory Service layer | Implement as `MultiMemoryService` |
| `PreloadMemory` / `LoadMemory` | Retrieval tools | Wrap our retrieval orchestrator |
| `VertexAiMemoryBankService` | Semantic Store option | Plug in as one backend |
| `InMemoryMemoryService` | Dev/test backend | Use only for local testing |

---

## Key Design Decisions

1. **Consolidation is background-only** — never block the hot path on memory writes.
2. **Retrieval is always fused** — no single-strategy retrieval for important tasks.
3. **Facts are versioned** — every fact has valid_from, valid_to, confidence, provenance.
4. **User corrections always win** — conflict resolution favors explicit user input.
5. **Token budget is sacred** — memory retrieval results are trimmed to fit the budget.
6. **Each store is independent** — can swap backends without touching other layers.

## Local-Only Constraint

- Current implementation work must default to local or self-hosted components only.
- Do not introduce paid managed services as a requirement for development or baseline production readiness.
- Prefer SQLite, local files, in-process stores, and optional self-hosted backends unless the user explicitly changes this constraint.
