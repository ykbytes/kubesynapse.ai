# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.0](https://github.com/ykbytes/kubesynapse.ai/compare/v0.1.0...v0.2.0) (2026-07-02)


### Added

* **backend:** enrich step tool/artifact summaries with duration, output, paths, errors ([1ac33be](https://github.com/ykbytes/kubesynapse.ai/commit/1ac33bee23216788c3adb861bccaaeae32e006d0))
* **gateway:** enrich live SSE activity payloads with structured fields ([37c7f60](https://github.com/ykbytes/kubesynapse.ai/commit/37c7f604ad79b8d40db06b44a98e69b15b68835c))
* incident management CRUD + UI + smoke test scripts ([7f78004](https://github.com/ykbytes/kubesynapse.ai/commit/7f780049782a4b750cff50e6785c28025fdcffbd))
* KubeSynapse — Kubernetes-native AI agent platform ([0c80731](https://github.com/ykbytes/kubesynapse.ai/commit/0c80731aa748e6704761b34fa5cacf3458161019))
* **landing:** optimized public site build + branded logo ([9a221e5](https://github.com/ykbytes/kubesynapse.ai/commit/9a221e514c7d954417256dda304d3e5d49a850a5))
* **mcp:** harden sidecar images, pin deps, enrich capabilities metadata ([98a4aeb](https://github.com/ykbytes/kubesynapse.ai/commit/98a4aeb5fb6ec80cdd8d4c72e1efcf1e41d73759))
* migrate images to quay.io, harden optimizer readiness check, enhance MCP sidecar ([10a9299](https://github.com/ykbytes/kubesynapse.ai/commit/10a929969f4c95a40edffb2244578240fa775e81))
* **optimizations:** add ROI Lab backend, store, tests, and example agent ([dce7881](https://github.com/ykbytes/kubesynapse.ai/commit/dce78811e53a6ba7434df12a75063624d1d79732))
* refine optimize roi candidate workflow ([971fc31](https://github.com/ykbytes/kubesynapse.ai/commit/971fc3138d0c8bbe1253949947abb4ecca609d20))
* runtime hardening and premium UI integration ([9a1d708](https://github.com/ykbytes/kubesynapse.ai/commit/9a1d70854282f76bb2733c76caedc47e91235f47))
* **security:** deeper-scan hardening (Round 4) ([ced3bbd](https://github.com/ykbytes/kubesynapse.ai/commit/ced3bbd769d9fdf6774c4df1c6163102cdd6dda9))
* **security:** multi-tenancy hardening for OpenCode runtime (Round 3) ([c07dd0a](https://github.com/ykbytes/kubesynapse.ai/commit/c07dd0a48c1e976035d66a7708b868824f453660))
* **security:** OPA Gatekeeper integration, admin tool ceiling, and policy seal ([936f997](https://github.com/ykbytes/kubesynapse.ai/commit/936f997bbafa30111f69c474018712a976562c07))
* **security:** rounds 5 & 6 hardening - auth, MCP, SSRF, XSS, audit ([9e72331](https://github.com/ykbytes/kubesynapse.ai/commit/9e7233187094f676d35be8b18d4883cc0d1bd02e))
* **ui+infra:** Observatory redesign, Permission Matrix, and backend fixes ([709678a](https://github.com/ykbytes/kubesynapse.ai/commit/709678a0ecbef08baf7c518b410a48647a47bf88))
* **ui:** AIOps composer redesign — Phase 1 frontend ([d0a7fd8](https://github.com/ykbytes/kubesynapse.ai/commit/d0a7fd8a492990280921bac63949051a8b5fd0a5))
* **ui:** compact agent header, catalog header, and sidebar ([11c822a](https://github.com/ykbytes/kubesynapse.ai/commit/11c822a2ed1c5fbe555705b43ed69a980eef5c23))
* **ui:** Observatory/Incidents/Catalog redesign + MCP scroll fix + AgentManagementPanel cleanup ([68fd06b](https://github.com/ykbytes/kubesynapse.ai/commit/68fd06b99842a5b9fc97c82420ffffa4dbdcbacd))
* **webhooks:** claim-based dispatch with atomic dedup, state machine, and lineage tracking ([8650193](https://github.com/ykbytes/kubesynapse.ai/commit/865019328a1290515e3c707a2d81ed5bcbbdee7f))


### Fixed

* add RUNTIME_AUTH_REQUIRED override to decouple from CREDENTIAL_PROXY_ENABLED ([4f760ae](https://github.com/ykbytes/kubesynapse.ai/commit/4f760ae3ad2cf3355fd4c8bfb2d6bef280b38a4a))
* align CREDENTIAL_PROXY_MCP_HUB_PORT to 4010 across all components ([194366c](https://github.com/ykbytes/kubesynapse.ai/commit/194366ce56581650c55211885669c48d9eff7b44))
* **api-gateway:** resolve CrashLoopBackOff causing login 502 ([8ef4153](https://github.com/ykbytes/kubesynapse.ai/commit/8ef41533b6f92b1ecf2722806ab2317756dff2f6))
* **auth:** add missing cast import from typing ([034c876](https://github.com/ykbytes/kubesynapse.ai/commit/034c876b974cced930fbea4cb531ca899674a876))
* correct secret name in README password retrieval command ([de2efde](https://github.com/ykbytes/kubesynapse.ai/commit/de2efde73f06143a6dcc09712e499cd7e6ff1bd7))
* incident controller reliability + gateway test infrastructure fixes ([de9153c](https://github.com/ykbytes/kubesynapse.ai/commit/de9153cc0a7080ab5a3b766457144470a9bd451e))
* **install:** add helm dependency build before install ([36bf31a](https://github.com/ykbytes/kubesynapse.ai/commit/36bf31a70ccaad47ce325734c5e0fe34a1e3b425))
* **install:** add WSL/Windows PATH bridge for kind.exe, helm.exe ([41f31c9](https://github.com/ykbytes/kubesynapse.ai/commit/41f31c97042979b3b2bfa333e71b2589c1145c91))
* **install:** bridge WSL/Windows kubeconfig mismatch for kind.exe ([449c1ec](https://github.com/ykbytes/kubesynapse.ai/commit/449c1ecf783d196bd4431781e629fd9676e46ca8))
* **install:** convert WSL paths to Windows paths for helm.exe ([bacce36](https://github.com/ykbytes/kubesynapse.ai/commit/bacce365c7eadff6a2d8c50cfd63fd7648df6d76))
* **install:** integrate MCP sidecar builds into install flow ([4fa03be](https://github.com/ykbytes/kubesynapse.ai/commit/4fa03bed360e072cf0cb6a21b527d6ab81a215aa))
* **install:** use forward-slash Windows paths instead of backslash ([fa2e4c1](https://github.com/ykbytes/kubesynapse.ai/commit/fa2e4c1c990deaced24277fb31e152046e244377))
* **opencode-runtime:** remove dead config_generator.py from Dockerfile COPY ([51cdd13](https://github.com/ykbytes/kubesynapse.ai/commit/51cdd13501c25428f1f930f9c96c578da1931aed))
* persist optimization candidate history ([1b9e701](https://github.com/ykbytes/kubesynapse.ai/commit/1b9e7016980853371aa08181d5eeb7ccd5feeee0))
* **platform:** reliability, security and performance hardening [WP-1..WP-10] ([97422c2](https://github.com/ykbytes/kubesynapse.ai/commit/97422c2e0dede622ba5abbf7e62c267e71e5e3a3))
* **README:** replace wordmark SVG with icon-only badge for reliable rendering ([ad3050e](https://github.com/ykbytes/kubesynapse.ai/commit/ad3050edaefde92d890d0d700c133cfb62fb1ee2))
* reduce opencode invoke latency and align api v1 paths ([3e4684a](https://github.com/ykbytes/kubesynapse.ai/commit/3e4684a41836bc33c54c8c86320843f83e3a11a4))
* remove expires 0 from Copilot OAuth auth content ([4ee7744](https://github.com/ykbytes/kubesynapse.ai/commit/4ee7744bb9995b987ee1831efbce5c0e17fe0c5b))
* remove MCP sidecars from all 3 demos — images not available in Kind ([f41bad6](https://github.com/ykbytes/kubesynapse.ai/commit/f41bad6b1fc4786867f3fcd1b167630561db41ab))
* repair optimizer candidate generation and simplify roi lab ([2df2771](https://github.com/ykbytes/kubesynapse.ai/commit/2df277115a4c4cb66acd87846d0b8a2a5e90887a))
* resolve daily-standup-bot end-to-end workflow issues ([8edbc70](https://github.com/ykbytes/kubesynapse.ai/commit/8edbc709dc2a467b65619dda8c8b95c5edc004db))
* restore reasoning and capability contracts after UI merge ([89e1087](https://github.com/ykbytes/kubesynapse.ai/commit/89e10872b007fe372dc0939cfc3d1e8a46a0a4ed))
* security audit fixes + credential-proxy path fix + docs ([1fd62b2](https://github.com/ykbytes/kubesynapse.ai/commit/1fd62b22958631bd0737e4d8f684fc5697f47923))
* switch demos to opencode-go/deepseek-v4-flash — fastest available model ([fbae799](https://github.com/ykbytes/kubesynapse.ai/commit/fbae799619e2358cb9f83cf2e787437ebb1f4ce2))
* switch demos to opencode-go/glm-5 — working free model ([3d81902](https://github.com/ykbytes/kubesynapse.ai/commit/3d819027dee172a83c52a8323c5ae3756aaa6d0f))
* sync bootstrap admin password on env change ([04d44bf](https://github.com/ykbytes/kubesynapse.ai/commit/04d44bf863b95cc1977d6cb8ea85aa0af165873e))
* **traces:** dedup run history + observability docs and faithful architecture diagram ([8062156](https://github.com/ykbytes/kubesynapse.ai/commit/8062156a0d97ea3892211421f06e753f2e90d66e))
* **traces:** token breakdown + per-tool duration end-to-end ([a4e1710](https://github.com/ykbytes/kubesynapse.ai/commit/a4e1710ed12ff635bf7b34b83a27eb60096cfb5d))
* **ui:** replace hard truncate with line-clamp on chats/policies/list sidebars ([ce5a2a9](https://github.com/ykbytes/kubesynapse.ai/commit/ce5a2a958f97146fbf7d19f09e4d9e8ab87db381))
* validate demos against real CRD schema — model, sessionGroup, policies ([b5ca8a9](https://github.com/ykbytes/kubesynapse.ai/commit/b5ca8a92f2c96ca2f4418e0b5391244a3a6a3924))


### Changed

* **operator:** deduplicate preview/summarize helpers ([c3ba31c](https://github.com/ykbytes/kubesynapse.ai/commit/c3ba31c660e1fbfd7a315d45717715b920202c76))


### Documentation

* 3-day work summary (June 10-13, 2026) ([c0290c0](https://github.com/ykbytes/kubesynapse.ai/commit/c0290c0dd1ffc4d5ee73012e7ad570b3799b349b))
* 3-day work summary for hardening-and-ui-cleanup (June 10-13, 2026) ([1351fba](https://github.com/ykbytes/kubesynapse.ai/commit/1351fba77292cdf84ccdcf865ac7199f90526a02))
* add Sprint 11 changelog entry for dead code cleanup ([e0fff22](https://github.com/ykbytes/kubesynapse.ai/commit/e0fff22818e133aa869b0fe6103d5f79d7b0770d))
* comprehensive README overhaul — branded logo, incident management, webhook dispatch, security audit, landing page ([b9b3693](https://github.com/ykbytes/kubesynapse.ai/commit/b9b36935bfd01dc9d76d5d2e7c62a84ee6b0f7ca))
* document LiteLLM runtime secret drift ([609e517](https://github.com/ykbytes/kubesynapse.ai/commit/609e5172b789682c34244dad056be88dfe673062))
* feature only OpenCode as production runtime, mark Pi/Vibe as alpha ([2922019](https://github.com/ykbytes/kubesynapse.ai/commit/2922019b9d72946d183736b62f825fdb2c967669))
* fix 11 CRITICAL + 16 HIGH + 20+ MEDIUM in-app doc issues ([5267d63](https://github.com/ykbytes/kubesynapse.ai/commit/5267d6388f69d2d163115b480857978f97fa5e82))
* fix deployment guides — add MCP sidecars, fix API paths, mark Pi/Vibe alpha ([a8a528b](https://github.com/ykbytes/kubesynapse.ai/commit/a8a528bf83e3c54777bd1e56486bfeffd8c1e6b9))
* fix README quickstart and DX — critical user-facing bugs ([6ee14e5](https://github.com/ykbytes/kubesynapse.ai/commit/6ee14e5fbbc657a2522d5eb2ad910b9f648031ee))
* polish pass — fix remaining factual issues + add cross-reference callouts between sections ([71bb55c](https://github.com/ykbytes/kubesynapse.ai/commit/71bb55cb7dff2fef7fa2e608cb61e0fcf780fe00))
* redesigned architecture diagram — color-coded layers, emojis, cleaner flow ([c5b4715](https://github.com/ykbytes/kubesynapse.ai/commit/c5b4715259004a8df2bf756f461a0f4afe608e24))
* replace README architecture diagram with color-coded layered version ([dbd6039](https://github.com/ykbytes/kubesynapse.ai/commit/dbd6039a30f10bc730f9925041cddbbaf860d3b9))
* run-variability analysis and prompt/workflow/context engineering guide ([bc0e3d9](https://github.com/ykbytes/kubesynapse.ai/commit/bc0e3d9e16d5a83bebb9bf3f31f979f42bac0c67))
* Update AGENTS.md with incident flow, operator fix, smoke test scripts ([7f78004](https://github.com/ykbytes/kubesynapse.ai/commit/7f780049782a4b750cff50e6785c28025fdcffbd))
* validate and correct architecture diagram — add labels, fix edges ([14b5939](https://github.com/ykbytes/kubesynapse.ai/commit/14b593948b4aa5efc777e4d5f8731c5e3ef3bbce))

## [Unreleased] - Sprint 11 (Dead Code Cleanup & Operator Hardening)

### Removed
- **OpenCode Runtime** (Phase 2 + 3, ~2,124 lines net):
  - Deleted unused modules: `opencode-runtime/memory/entity.py` (EntityExtractor, 170 lines), `opencode-runtime/config_generator.py` (183 lines), `opencode-runtime/pi_client.py` (354 lines), `opencode-runtime/pi_types.py` (341 lines), `opencode-runtime/memory.py` (355 lines)
  - Removed dead SSE bridge subsystem from `opencode_client.py` (204 lines, including `_parse_sse_lines`, `_safe_int`, `_safe_float`, `SseEvent`, and threading bridge)
  - Removed 6 unused `MemoryManager` methods: `remove_provider`, `build_context`, `compact`, `get_stats`, `on_turn_start`, `on_session_end`
  - Removed 15 unused config constants (`OPENCODE_API_KEY`, `GITHUB_TOKEN`, `COPILOT_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_MCP_TOKEN`, `COMPACTION_PRESERVE_*`, `MEMORY_*`, etc.)
  - Removed `list_providers()` from `providers.py`
  - Removed `emit_agent_call()` from `runtime_events.py`
  - Removed unused `Callable` import from `runtime_events.py`
  - Removed unused `json` import from `memory/manager.py`
  - Removed `EntityExtractor` / `ENTITY_EXTRACTOR` exports from `memory/__init__.py`
  - Removed dead SSE bridge test classes (`SSEBridgeParserTests`, `SafeIntFloatTestsBridge`)
- **Operator** (Phase 2 + 3 + 4, ~196 lines net):
  - Deleted `operator/errors.py` (entire module unused, 85 lines)
  - Deleted `operator/mock_entrypoint.py` (copied into Docker image but never executed, 62 lines)
  - Removed dead `_start_readiness_server` / `_render_prometheus_metrics` / `_READINESS_PORT` from `operator/main.py` (referenced an undefined `_ReadinessHandler` class — wrapped in try/except so the operator silently lost its readiness server; kopf's `--liveness=http://0.0.0.0:8080/healthz` flag already provides health checks)
  - Removed dead dedup helpers: `is_duplicate_event`, `_event_key`, `_dedup_cache`, `_dedup_lock`, `_DEDUP_TTL_SECONDS`
  - Removed dead metric helpers: `record_reconcile_metric`, `_metrics_lock`, `_reconcile_*_globals`
  - Removed dead in-flight reconciliation: `in_flight_reconciliation`, `wait_for_in_flight`
  - Removed `get_tracer` / `get_trace_id` from `tracing.py`
  - Removed `normalize_text`, `exact_match_score`, `estimate_toxicity` from `utils.py`
  - Removed `_find_mcp_connection_cr` from `controllers/mcp_connection_controller.py`
  - Removed `_reconcile_connector_status` from `controllers/observation_controller.py`
  - Removed `ORPHAN_PVC_CLEANUP_INTERVAL` from `config.py`
  - Consolidated duplicate `summarize_preview_text` / `summarize_tool_input` (worker.py) and `_preview_stream_value` / `_tool_call_input_preview` (utils.py) into single canonical versions in `utils.py` with backward-compat shims
  - Removed unused `threading` / `time` / `http.server` (BaseHTTPRequestHandler, HTTPServer) imports from `main.py`
  - Updated `operator/Dockerfile` to drop deleted `mock_entrypoint.py` and long-deleted `errors.py` from COPY list

### Changed
- **Live Verification**: Dead code cleanup rolled out as `localhost/kubesynapse/kubesynapse-operator:cleanup-20260602`. Workflow generation 12 (`context7-research-analysis`) ran end-to-end in 248.9s with 54 tool calls and full token breakdown (92,847 total: 254 prompt / 1,201 completion / 91,392 cache_read). 100% of tool calls have per-tool `duration_ms` populated (avg 373ms, max 1455ms). One duplicate worker job was correctly rejected by the lease lock during the rollout race, confirming the dedup fix works as designed.
- **Tests**: 393/393 opencode-runtime tests pass, 261/262 operator tests pass (1 pre-existing tenant isolation failure unrelated to cleanup)

## [Unreleased] - Sprint 10 (Observatory Pipeline Hardening & UI Fixes)

### Added
- **Token Breakdown**:
  - Full token breakdown (prompt, completion, cache_read, cache_write, reasoning) propagated end-to-end from OpenCode runtime through operator/gateway into LLMCallRecord and WorkflowExecution
  - `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` columns added to `runtime_run_events` table
  - Observatory UI Token Breakdown panel with stacked bar, cache hit ratio, and quality flags
- **Tool Call Duration**:
  - Per-tool `duration_ms` extracted from OpenCode's native `state.time.start`/`state.time.end` timestamps in `extract_tool_calls_from_messages()`
  - Duration propagated through operator worker and gateway direct-invoke handler into `ToolCallRecord.duration_ms`
  - Observatory Tool Mix chart now shows real per-tool wall-clock time
- **Policy Enforcement**:
  - Added optional OPA Gatekeeper sub-chart integration with admission constraints for required policy references, sealed policy protection, tool-pattern validation, and policy orphan prevention
  - Added `AgentPolicy.spec.sealed` and `AgentPolicy.spec.toolPolicy.adminToolCeiling`
  - Added operator-side policy attestation via `KUBESYNAPSE_POLICY_HASH` and runtime env injection for `OPENCODE_ADMIN_PERMISSION_CEILING_JSON`
- **Observatory UI**:
  - Added Prism-based JSON syntax highlighting for tool arguments and results
  - Added diff-aware rendering for patch-style tool payloads
  - Added expandable tool call rows with icon mapping, ArgsCard field extraction, and ResultBlock auto-detection
  - Added run-level insight charts to the Overview tab: Recent Run Trend (duration sparkline across the workflow's last runs), Step Contribution (share bars), Step Variability (min/median/max range per step with current-run marker), Tool Mix (time-weighted MCP tool usage with failure counts), Model Efficiency (token-vs-latency scatter, bubble by cost), and Quality Flags strip (warning/error events, tool failures, longest quiet gap, missing token data). Pure CSS, no charting library added; derives from payloads already fetched for the Observatory.

### Changed
- **OpenCode Runtime**:
  - Increased extracted tool-result payload limit from `2000` to `40000` characters before forwarding trace data to the operator and gateway
- **Documentation**:
  - Updated repo docs and in-app docs to reflect the current Observatory workspace, trace payload fields, Gatekeeper-backed policy enforcement, and OpenCode runtime behavior

### Fixed
- **Trace Pipeline**:
  - Fixed 0-tokens issue: operator worker and gateway were reading flat `metadata.prompt_tokens` instead of nested `metadata.tokens.input/output/reasoning/cache_read/cache_write`
  - Fixed runtime `_sync_emit` omitting `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens` from event envelopes
  - Fixed gateway `_upsert_from_event` missing handler for `llm.call` event type (LLM calls from runtime events were silently dropped)
  - Fixed direct-invoke gateway handler assigning overall execution latency to every tool call instead of per-tool duration
  - Fixed direct-invoke tool call field name mismatch: gateway now accepts both runtime format (`tool`/`input`/`output`) and legacy format (`name`/`args`/`result`)
  - Fixed `DEFAULT_API_GATEWAY_SHARED_TOKEN` not propagating to worker jobs (workers couldn't auth to `/api/traces/batch`)
  - Changed helm chart from `valueFrom: secretKeyRef` (optional) to direct `value:` for reliable token injection
  - Fixed worker log endpoint looking up pods in workflow namespace instead of operator namespace (`kubesynapse`)
  - Fixed `execution_id` missing from step, LLM call, and tool call records stored in `execution_traces` DB
  - Fixed `latency_ms` not computed for steps — now calculated from `started_at` → `completed_at`
  - Fixed per-step LLM/tool counts showing 0 — `_execution_trace_to_dict` now joins by `step_id`
  - Fixed `step_index` hardcoded to 0 — worker no longer sends explicit index, backend auto-increments from `len(steps)`
  - Fixed LLM calls not recorded for pi-runtime when metadata is not a dict
- **Observatory UI**:
  - Fixed tabs (Steps, Logs, Insights, Compare) not scrollable — added `flex-1 overflow-y-auto`
  - Fixed observatory sidebar list not rendering in AppSidebar
  - Made tool/LLM call parsers defensive against missing `execution_id` (old data compatibility)
  - Fixed malformed or truncated JSON results falling back to plain text when the runtime output was missing closing braces
- **Auth Page**:
  - Tab now shows "Create Account" during bootstrap instead of misleading "Sign In"
  - Hidden broken "Sign in instead" toggle when no users exist (bootstrap mode)
  - Restored "Open Console" button on local LandingPage (showLogin prop)

## [Unreleased] - Sprint 9 (Pi Runtime & Live Observability)

### Added
- **Pi Runtime Integration**:
  - New `runtime.kind: "pi"` support alongside `opencode`
  - Pi bridge (`pi-runtime/pi_bridge.js`) implements HTTP bridge for Pi RPC mode
  - Artifact API endpoints (`/artifacts/list`, `/artifacts/download`, `/artifacts/zip`) added to pi-runtime
  - Model timeout mechanism (`MODEL_TIMEOUT_MS=120s`) with auto-abort and retry
- **Deployment Hardening**:
  - LiteLLM database bootstrap is now automatic via Helm init container running `prisma db push`
  - Operator dependency egress policy added for PostgreSQL, Redis, NATS, LiteLLM, and Qdrant
  - Operator Kubernetes API egress policy fixed to avoid blocking private-cluster API access
  - LiteLLM isolation policy now includes egress to PostgreSQL, Redis, and DNS
- **Workflow Engine Improvements**:
  - Fixed workflow controller enqueue bug (`GROUP`, `VERSION`, `WORKFLOW_PLURAL`)
  - Fixed worker artifact PVC creation (skip cross-namespace `ownerReferences`)
  - Fixed streamed response reconstruction (backfill missing completed.response / tool_calls from stream events)
  - Fixed stream truncation bug (prefer accumulated `response.delta` text)
  - Added autoRetry for recoverable failures
  - Radically slimmed context ConfigMaps to prevent model hangs
- **Live Observability UI**:
  - ExecutionObservatory with trace inspection, StepInspector, LLMCallViewer, TracePlayer, ExecutionTimeline, ExecutionDiffView
  - Live Activity Stream with step-level status transitions
  - Workflow file browser with ZIP download restoration
  - Agent live reasoning log design (terminal-style SSE events, filter chips, copy/download, stall detection)
- **Resource & Reliability**:
  - Boosted agent sandbox resources (builder limits: 4 CPU / 8Gi)
  - Increased step timeouts (`scaffold-project` 3600s, `build-synth-core` 5400s, etc.)
  - Wipe Pi session PVC between restarts to clear stale sessions

### Verification
- `npm run build` — 0 TypeScript errors
- `helm lint --strict` — passes
- `ruff check` — 0 errors
- Operator tests pass

---

## [1.0.0] - 2026-04-27 — Sprint 8 (Final)

### Added
- **Vulnerability Scanning Pipeline** (`.github/workflows/security-scan.yaml`):
  - Trivy container image scanning for all 4 images (api-gateway, operator, opencode-runtime, web-ui) with SARIF upload to GitHub Security
  - Trivy filesystem scanning with SARIF upload
  - kube-linter for Helm/K8s best practices (privileged containers, privilege escalation, read-only root FS, run-as-non-root, capabilities, sensitive host mounts, anti-affinity, RBAC)
  - checkov for IaC security scanning (Helm charts + rendered K8s manifests)
  - npm audit for both web-ui and TypeScript SDK
  - pip-audit extended to cover cli/ dependencies
  - Bandit SAST with SARIF format and GitHub Security integration
  - CRITICAL vulnerabilities block on all scans
  - Secret detection via TruffleHog with verified credential scanning
- **RBAC Audit & Matrix** (`docs/rbac-matrix.md`):
  - Comprehensive documentation of all 5 ServiceAccounts (operator, api-gateway, agent-runtime, collector, litellm)
  - Detailed permission matrix with justification for every API group/resource/verb
  - Least-privilege audit checklist (13 checks, all PASS)
  - Verification commands for cluster operators
  - Identified: no `pods/exec`, no cluster-wide secret list on gateway, agent runtime cannot mutate platform CRDs
- **Secrets Management Guide** (`docs/secrets-management.md`):
  - 3 full integration paths: External Secrets Operator (AWS/GCP/Azure), Vault CSI Provider (HashiCorp Vault), Sealed Secrets (Bitnami)
  - Each path: prerequisites, step-by-step installation, configuration snippets, verification commands
  - Comparison table across all 3 approaches
  - KubeSynapse-specific secret reference (8 secret keys with component mapping)
  - Security best practices section
- **Artifact Distribution**:
  - Docker Hub publishing in release workflow: `KubeSynapse/operator`, `KubeSynapse/api-gateway`, `KubeSynapse/opencode-runtime`, `KubeSynapse/web-ui` (with `:latest` tags)
  - Helm OCI pushed to Quay.io (`oci://quay.io/yakdhane/charts/kubesynapse`)
  - Python SDK renamed to `kubesynapse-sdk` for `pip install kubesynapse-sdk`
  - TypeScript SDK renamed to `@kubesynapse/sdk` for `npm install @kubesynapse/sdk`
  - CLI renamed to `kubesynapse-cli` for `pip install kubesynapse-cli`
  - README updated with install instructions for pip, npm, Homebrew, and Helm OCI
- **Compatibility Matrix** (`COMPATIBILITY.md`):
  - Test matrix covering K8s 1.25–1.34 (Kind), with planned EKS/GKE/AKS columns
  - Component compatibility table (8 core components, 11 MCP sidecars)
  - Kubernetes feature requirements reference
  - Automated compatibility test script (`scripts/test-compatibility.sh`) — creates Kind clusters across versions, deploys KubeSynapse, runs smoke tests, cleans up
  - Known limitations documented (OpenShift, GKE Autopilot, arm64, Fargate, Windows)
- **Accessibility (WCAG 2.1 AA)**:
  - `SkipToContent` component — skip-to-main-content link, first focusable element on every page
  - `AriaLiveRegion` component — dual-region (polite `role="status"` + assertive `role="alert"`) with `announceToScreenReader()` utility
  - `FocusTrap` component — keyboard trap for modals/dialogs/drawers with Escape handling
  - `ConfirmDialog` enhanced: `aria-labelledby`, `aria-describedby`, `aria-label` on buttons, decorative icon `aria-hidden`
  - `<main id="main-content" tabIndex={-1}>` for skip link target
  - Color contrast verified: `text-foreground` on `bg-background` = 12.3:1 (WCAG AA requires 4.5:1)
  - Accessibility audit report (`docs/accessibility-report.md`) — full WCAG 2.1 AA compliance matrix with 50 success criteria
- **Security Documentation** (`SECURITY.md`):
  - Accepted vulnerabilities section: pip-audit accepted risks (2 entries), Trivy container accepted risks (2 entries), kube-linter accepted risks (2 entries), Bandit accepted risks (2 entries)
  - Quarterly review cadence defined
  - Escalation process for new CRITICAL CVEs

### Changed
- `clients/python/setup.py` — package renamed from `kubesynapse-client` to `kubesynapse-sdk`
- `clients/typescript/package.json` — package renamed from `@KubeSynapse/client` to `@kubesynapse/sdk`
- `cli/pyproject.toml` — package renamed from `agentctl` to `kubesynapse-cli`
- `web-ui/src/App.tsx` — integrates SkipToContent and AriaLiveRegion at app root; main element gets `id="main-content"`
- `.github/workflows/release.yaml` — extended for dual-registry (GHCR + Docker Hub) with cosign signing on both, `:latest` tags on Docker Hub, Helm OCI push to both registries
- `README.md` — added pip/npm/Homebrew install instructions, Helm OCI one-liner install

### Verification
- `npm run build` — ✅ 0 TypeScript errors (4608 modules)
- `helm lint --strict` — ✅ passes
- `ruff check` — ✅ 0 errors on all new code
- All 6 a11y components built successfully
- Release workflow validated for dual-registry push

---

## [Unreleased] - Sprint 7

### Added
- **CI/CD Release Automation**: `.github/workflows/release-please.yaml` — Google release-please action with conventional commit detection, auto-versioning, and auto-CHANGELOG generation (`release-please-config.json`, `.release-please-manifest.json`)
- **Supply Chain Integrity**: `.github/workflows/supply-chain.yaml` — per-push SBOM generation (Syft SPDX + CycloneDX), Trivy vulnerability scanning with SARIF upload to GitHub Security, Cosign keyless image signing with OIDC, and build provenance attestation
- **Grafana Dashboards** (3 new):
  - `deploy/grafana/dashboards/agent-overview.json` — Agent health, pod status, memory/CPU, CRD reconciliation rates
  - `deploy/grafana/dashboards/workflow-execution.json` — Workflow runs, step duration P50/P95, worker queue depth, failure rates
  - `deploy/grafana/dashboards/llm-usage.json` — Token rate by model, cost rate ($/hr), latency P50/P95/P99 per model, provider error rates, LiteLLM health
- **Prometheus Alert Rules** (4 new): Agent pod down (critical), workflow failure rate > 5%, API error rate > 1%, LiteLLM unhealthy, step timeout rate > 10%
- **Performance Benchmarks**: `benchmarks/` directory with 3 reproducible benchmark scripts (`bench-reconcile.py`, `bench-api.py`, `bench-concurrency.py`) and comprehensive README with baseline targets, CI integration, and JSON export format
- **Landing Page v2.0**: Animated cluster visualization in hero (floating agent pods + K8s control plane + SVG connection lines), live GitHub stars counter (fetched from GitHub API), 4-column comparison matrix (KubeSynapse vs LangChain vs CrewAI vs Kubiya) with 12 capability rows, system-preference dark mode detection (already existed but enhanced)
- **Blog Posts** (3): `docs/blog/what-is-KubeSynapse.md` — "Why Kubernetes is the Right Platform for AI Agents", `docs/blog/KubeSynapse-vs-alternatives.md` — full comparison with detailed feature matrix, `docs/blog/building-first-agent.md` — "Build a DevOps Agent in 5 Minutes" tutorial with copy-pasteable YAML
- **Video Content Plan**: `docs/videos.md` — 5-video series outline (product overview 3min, governance 8min, workflows 8min, observability 6min, community 4min) with scripts, visual assets, recording tools, and publishing strategy
- **Python SDK**: `clients/python/` — async `KubeSynapseClient` (httpx + Pydantic v2) with 15 API methods covering health, agents, workflows, policies, and traces; `SyncKubeSynapseClient` wrapper; `setup.py` with PyPI-ready config; full type annotations and docstrings
- **TypeScript SDK**: `clients/typescript/` — `KubeSynapseClient` class with full type coverage, 15 API methods, AbortController timeouts, error handling; exports all request/response types; React/Next.js usage example
- **Community Infrastructure**: `docs/community.md` — Community page with Slack/Discord links, meeting schedule, contributor path (4 levels), Good First Issue criteria; `docs/contributor-program.md` — 4 recognition tiers (Bronze/Silver/Gold/Platinum), swag, conference sponsorship, nomination process; Good First Issue template (`.github/ISSUE_TEMPLATE/good_first_issue.md`)
- **Good First Issue** label criteria added to `CONTRIBUTING.md`

### Changed
- `web-ui/src/components/LandingPage.tsx` — Added `AnimatedCluster` component (floating pod visualization), `GitHubStars` component (live star count from GitHub API), replaced generic "Other Platforms" comparison with 4-column matrix (KubeSynapse vs LangChain vs CrewAI vs Kubiya)
- `deploy/prometheus/rules.yaml` — Expanded from 8 to 13 alert rules with Sprint 7 additions
- `CONTRIBUTING.md` — Added Good First Issue criteria section

### Verification
- `npm run build` — ✅ 0 TypeScript errors (4606 modules)
- `helm lint --strict` — ✅ passes (0 failures)
- `ruff check` — ✅ 0 errors on all new code (benchmarks/, clients/)
- `ruff check --fix` — ✅ auto-fixes applied, all clean

### Added
- Production-grade SaaS landing page with animated particle background, typewriter hero, scroll parallax, and tabbed macOS terminal showcasing complete AIAgent/AgentWorkflow YAML examples (`web-ui/src/components/LandingPage.tsx`)
- `api-gateway/constants.py` — extracted 90+ constants (env vars, A2A protocol, runtime limits, factory modes, validation patterns)
- `api-gateway/utils.py` — extracted 10 utility functions with full type annotations (`now_iso`, `normalize_json_object`, `normalize_subagent_strategy`, etc.)
- Helm production hardening toggles (`podDisruptionBudget.enabled`, `networkPolicy.enabled`)
- PodDisruptionBudgets for API Gateway, Operator, LiteLLM, and PostgreSQL with verified selectors
- Startup probes for web-ui, nats, redis, postgresql, qdrant, and collector DaemonSet
- NetworkPolicy templates with default deny ingress/egress, DNS egress, and per-component allow rules (`templates/network-policy-default.yaml`)
- Security contexts for collector DaemonSet (`allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities: drop: [ALL]`)
- `.bandit.yaml` with K8s-appropriate skips (B104/B108 for container networking and /tmp mounts)
- `.github/workflows/security-scan.yaml` for automated bandit + trivy scanning
- `.pre-commit-config.yaml` with ruff, mypy, and helm-lint hooks
- `.devcontainer/devcontainer.json` for VS Code remote containers
- GitHub issue templates (bug report, feature request) and PR template
- `CODE_OF_CONDUCT.md`

### Security
- Fixed 12 vulnerabilities in `api-gateway/auth_middleware.py` (CVSS up to 9.8):
  - OIDC default `audience` changed from empty string to `KubeSynapse-gateway`
  - Enforced HTTPS for OIDC endpoints via URL scheme validation
  - Added `Secure`, `HttpOnly`, `SameSite=Lax` flags to auth cookies
  - Made Bearer token parsing case-insensitive
  - Fixed `X-Forwarded-For` to use last proxy IP instead of first
  - Added `kid` validation before JWK signature verification
  - Replaced global `asyncio.Lock()` with lazy initialization
  - Fixed namespace default from `["*"]` to `[]` (breaking security fix)
  - Added 15s sleep to pod lifecycle preStop hooks
  - Wrapped `verify_refresh_token` in `try/except` with `safe_record_audit`
  - Fixed `verify_password` to return `False` on exception instead of raising
  - Rate-limit auth endpoints (login, register, password reset)

### Added — Sprint 2 (Stories 1-6)
- **Memory System Overhaul** (`opencode-runtime/memory/`):
  - 5-tier retention: EPHEMERAL, SESSION, WORKSPACE, LONG_TERM, PERMANENT
  - Pluggable provider architecture: Builtin (JSONL), Semantic (Qdrant vector DB)
  - Entity extraction for user profiles and project context (inspired by Hermes Agent)
  - Context fencing with `<memory-context>` tags to prevent model hallucination
  - Time-decay relevance scoring and automatic pruning
  - 15 new environment variables for memory configuration
- **Test Infrastructure**:
  - `api-gateway/tests/conftest.py` — FastAPI TestClient fixtures with mocked auth, K8s, DB
  - `api-gateway/tests/test_smoke.py` — 8 smoke tests (health, ready, auth, CRUD, metrics)
  - `operator/tests/conftest.py` — Mock K8s API fixtures, sample specs
  - `operator/tests/test_smoke.py` — 8 smoke tests (error classification, config, validation)
  - `Makefile` targets: `test-gateway`, `test-operator` with `pytest-cov`
  - CI workflow updated to run tests with coverage and upload artifacts
- **Static Analysis Baseline**:
  - `ruff check` passes with **0 errors** across all Python code (was 281)
  - `helm lint --strict` passes with JSON Schema validation
  - Added `per-file-ignores` in `pyproject.toml` for intentional patterns
- **Configuration Hardening**:
  - `charts/kubesynapse/values.schema.json` — comprehensive JSON Schema for Helm values
  - `docs/configuration-reference.md` — documents every env var and Helm value
  - `deploy/values.dev.yaml`, `values.staging.yaml`, `values.production.yaml`
- **Database & Migration Safety**:
  - PostgreSQL connection pool tuning: `pool_size`, `max_overflow`, `pool_recycle`, `pool_timeout`
  - `statement_timeout` configured for PostgreSQL connections
  - `/api/health/db` endpoint returning 200/503 based on DB connectivity
  - `SchemaVersion` model and `_verify_schema_version()` for migration integrity
  - N+1 query eliminated in `record_memory_items()` via batched lookup
- **API Contract Validation**:
  - `RateLimitMiddleware` — token bucket per IP, configurable RPS/burst
  - `RequestSizeLimitMiddleware` — rejects bodies >10MB
  - `ErrorResponse` Pydantic model with standardized error schema
  - Descriptions added to 8 key Pydantic models (InvokeRequest, CreateAgentRequest, etc.)
- **Authentication Hardening**:
  - `jwt_utils.py` rewritten for multiple active keys with `kid` rotation
  - JWT key rotation via `rotate_jwt_key()` with grace period for old tokens
  - Explicit rejection of JWT `none` algorithm
  - `PasswordResetToken` model and password reset flow (`/api/auth/forgot-password`, `/api/auth/reset-password`)
  - Exponential backoff for brute-force protection
  - Structured audit logging: `audit_login_success`, `audit_login_failure`
- **Helm Production Hardening**:
  - PodDisruptionBudgets for 4 components
  - Startup probes for 6 components
  - Security contexts (runAsNonRoot, readOnlyRootFilesystem, drop ALL)
  - 10 NetworkPolicy templates (default deny + per-component allows)

### Changed
- `README.md` completely rewritten with Mermaid architecture diagram, Quick Start, feature comparison table, and real-world use cases
- LandingPage switched from dark theme to light/white theme for better readability
- Makefile lint target migrated from flake8 to ruff + bandit
- `.github/workflows/ci.yaml` now triggers on `preprod` branch in addition to `main`
- `pyproject.toml` updated with `constants` in `known-first-party` isort list
- Resource requests/limits tuned to sensible production defaults across all Helm components
- Collector DaemonSet hardened with container securityContext, startupProbe, and `/tmp` emptyDir mount

### Fixed
- All 36 ruff lint issues in `api-gateway/main.py` reduced to 0 (import sorting, bare except clauses, en-dash characters, nested with statements, false-positive S105 suppressions)
- `api-gateway/main.py` import block reorganized with `constants` and `utils` as first-party modules
- B904 violations fixed by adding `from None` to HTTPException conversions in date parsing
- S110 violations fixed by replacing bare `pass` with `logger.warning(..., exc_info=True)`
- RUF003 en-dash characters replaced with hyphens in comments

### Removed
- 15+ junk/temporary files from repository root
- Fake integration claims from landing page

---

## [Unreleased] - Deployment & Docker

### Added
- **Docker & Deployment Infrastructure**:
  - `docker-compose.yml` — full local stack (Postgres 16, Redis 7, NATS 2, Qdrant 1.7, API Gateway, Operator, Web UI, OpenCode RT, LiteLLM proxy)
  - `deploy/litellm-config.yaml` — model routing config for OpenAI, Anthropic
  - `scripts/deploy-docker.sh` — Docker Compose lifecycle helper (up/down/build/logs/status/health/push)
  - `scripts/deploy-k8s.sh` — Helm-based K8s deployment helper (install/upgrade/uninstall/status/logs/port-forward)
  - `scripts/verify-docker-builds.sh` — validates all Dockerfiles build successfully
  - `deploy/README.md` — comprehensive deployment guide with quick start, troubleshooting, production checklist
  - Makefile targets: `compose-up`, `compose-down`, `compose-build`, `compose-logs`, `compose-status`, `k8s-install`, `k8s-upgrade`, `k8s-uninstall`, `k8s-status`, `k8s-logs`, `k8s-port-forward`
- **Dockerfile updates**:
  - `api-gateway/Dockerfile` — includes `trace_store.py`, `traces_router.py`
  - `operator/Dockerfile` — includes `trace_client.py`, `circuit_breaker.py`
  - `opencode-runtime/Dockerfile` — includes `memory/` package
  - `.dockerignore` files expanded (IDE files, venv, logs, OS files)

## [Unreleased] - Execution Observatory

### Added
- **Execution Observatory** — end-to-end workflow trace inspection and replay:
  - `api-gateway/trace_store.py` — hybrid SQL+JSONL+filesystem trace storage with 4 models (WorkflowExecution, StepExecution, LLMCallRecord, ToolCallRecord) and 20 event types
  - `api-gateway/traces_router.py` — FastAPI router with 8 endpoints: list, detail, summary, step detail, events, delete, JSON export, and self-contained HTML report
  - `operator/trace_client.py` — batched, asynchronous HTTP trace reporter with graceful degradation (fire-and-forget, thread-safe, auto-flush)
  - `operator/worker.py` — wired trace emission for workflow start/end, step start/end, LLM calls, and tool calls via thread-local context
  - `web-ui/src/components/ExecutionObservatory.tsx` — full workspace panel with execution list, filters, and tabbed detail view
  - `web-ui/src/components/observatory/` — 5 sub-components: TracePlayer (play/pause/seek), StepInspector (Sheet drawer), LLMCallViewer (prompt/response dialog), ExecutionTimeline (vertical, color-coded), ExecutionDiffView (side-by-side comparison)
  - Integrated "Observatory" into App.tsx routing, AppSidebar.tsx navigation, and lib/api.ts helpers
  - Added `ExecutionListItem` and `ExecutionListResponse` TypeScript types
  - 11 unit tests for `TraceClient` batching, flush, and failure handling (`operator/tests/test_trace_client.py`)
  - Trace endpoint smoke tests added to `api-gateway/tests/test_smoke.py`

### Fixed
- `web-ui` TypeScript build errors in new Observatory components (import paths, unused variables, type mismatches, `fractionalSecondDigits` compatibility)
- `operator/trace_client.py` removed unused `json` import (ruff F401)
- `operator/worker.py` replaced `try/except/pass` with `hasattr` checks for trace context cleanup (ruff SIM105)

## [0.1.0] - 2026-03-19

### Added
- Initial platform release
- 5 core CRDs: AIAgent, AgentPolicy, AgentApproval, AgentTenant, AgentWorkflow
- Kopf-based Kubernetes operator
- LangGraph agent runtime with guardrails, HITL approval, and RAG
- Goose runtime adapter
- FastAPI API gateway with hybrid auth (shared token + OIDC)
- React + TypeScript web console
- Helm chart (`charts/kubesynapse/`)
- CLI tool (`agentctl`) built on Typer + Rich
- MCP sidecar architecture with 3-tier execution model
- Pre-built images published to `quay.io/yakdhane/kubesynapse`
