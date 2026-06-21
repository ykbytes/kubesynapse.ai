"""Shared utility functions used by the operator controller and worker."""

import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import httpx
from config import get_float_env, get_int_env

logger = logging.getLogger("operator-utils")

PLACEHOLDER_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")
K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


AGENT_RUNTIME_TIMEOUT_SECONDS = get_float_env("AGENT_RUNTIME_TIMEOUT_SECONDS", 360.0, minimum=1.0)
MAX_THREAD_ID_CHARS = get_int_env("AGENT_MAX_THREAD_ID_CHARS", 128, minimum=16)
DEFAULT_WORKFLOW_STEP_MAX_ATTEMPTS = get_int_env("WORKFLOW_DEFAULT_MAX_ATTEMPTS", 1, minimum=1)
DEFAULT_WORKFLOW_STEP_BACKOFF_SECONDS = get_float_env("WORKFLOW_DEFAULT_BACKOFF_SECONDS", 2.0, minimum=0.0)
UNSUPPORTED_POLICY_BUDGET_FIELDS = (
    "maxTokensPerHour",
    "maxRequestsPerMinute",
    "maxCostPerDayUSD",
)
RUNTIME_CONFIG_FORBIDDEN_FILES = {"secrets.yaml"}
MAX_AGENT_SKILL_FILES = get_int_env("AGENT_MAX_SKILL_FILES", 24, minimum=1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_PATH_CHARS", 256, minimum=32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", 16000, minimum=512)
MAX_AGENT_SKILL_TOTAL_CHARS = get_int_env("AGENT_MAX_SKILL_TOTAL_CHARS", 64000, minimum=4096)
MAX_RUNTIME_CONFIG_FILES = get_int_env("RUNTIME_MAX_CONFIG_FILES", 64, minimum=1)
MAX_RUNTIME_CONFIG_PATH_CHARS = get_int_env("RUNTIME_MAX_CONFIG_PATH_CHARS", 256, minimum=32)
MAX_RUNTIME_CONFIG_CONTENT_CHARS = get_int_env("RUNTIME_MAX_CONFIG_CONTENT_CHARS", 64000, minimum=512)
MAX_RUNTIME_CONFIG_TOTAL_CHARS = get_int_env("RUNTIME_MAX_CONFIG_TOTAL_CHARS", 256000, minimum=4096)
MAX_WORKFLOW_STEPS = get_int_env("MAX_WORKFLOW_STEPS", 100, minimum=1)


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def runtime_url(agent_name: str, namespace: str, port: int = 8080) -> str:
    """Build the in-cluster HTTP URL for an agent runtime StatefulSet Service."""
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:{port}"


def slugify_identifier(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip()).strip("-_") or "item"


def build_thread_id(prefix: str, *parts: object, max_length: int = MAX_THREAD_ID_CHARS) -> str:
    """Build a runtime-safe thread id that stays within the configured limit."""
    normalized_parts = [slugify_identifier(part) for part in parts if str(part).strip()]
    base = "-".join([prefix, *normalized_parts])
    if len(base) <= max_length:
        return base

    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]
    keep_length = max(max_length - len(digest) - 1, 1)
    truncated = base[:keep_length].rstrip("-_") or "item"
    result = f"{truncated}-{digest}"
    return result[:max_length] if len(result) > max_length else result


def build_workflow_run_id(namespace: str, workflow_name: str, generation: int) -> str:
    epoch_ms = int(time.time() * 1000)
    digest = hashlib.sha256(
        f"workflow:{namespace}:{workflow_name}:{generation}:{epoch_ms}".encode()
    ).hexdigest()[:8]
    return build_thread_id("wf-run", namespace, workflow_name, generation, epoch_ms, digest, max_length=96)


def workflow_journal_path(artifact_path: str) -> str:
    if artifact_path.endswith(".json"):
        return f"{artifact_path[:-5]}.journal.ndjson"
    return f"{artifact_path}.journal.ndjson"


def _normalize_runtime_config_path(raw_path: Any, *, source: str) -> str:
    candidate = str(raw_path or "").strip().replace("\\", "/")
    if not candidate:
        raise ValueError(f"{source} path must not be blank")
    if len(candidate) > MAX_RUNTIME_CONFIG_PATH_CHARS:
        raise ValueError(f"{source} path '{candidate}' exceeds {MAX_RUNTIME_CONFIG_PATH_CHARS} characters")
    if candidate.startswith("/") or re.match(r"^[a-zA-Z]:[/\\]", candidate):
        raise ValueError(f"{source} path '{candidate}' must be relative")

    normalized = PurePosixPath(candidate)
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        raise ValueError(f"{source} path '{candidate}' must stay within the runtime config root")
    return normalized.as_posix()


def parse_runtime_config_files(raw_value: Any, *, source: str) -> dict[str, Any]:
    if raw_value in (None, ""):
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"{source} must be an object mapping relative file paths to content")
    if len(raw_value) > MAX_RUNTIME_CONFIG_FILES:
        raise ValueError(f"{source} cannot contain more than {MAX_RUNTIME_CONFIG_FILES} files")

    normalized: dict[str, Any] = {}
    total_chars = 0
    for raw_path, raw_content in raw_value.items():
        path = _normalize_runtime_config_path(raw_path, source=source)
        if path.lower() in RUNTIME_CONFIG_FORBIDDEN_FILES:
            raise ValueError(
                f"{source} path '{path}' is not allowed. "
                "Use environment variables or a secret store for sensitive values."
            )
        if isinstance(raw_content, str):
            serialized = raw_content
            value: Any = raw_content
        elif isinstance(raw_content, (dict, list)):
            serialized = json.dumps(raw_content, ensure_ascii=False, sort_keys=True)
            value = raw_content
        else:
            raise ValueError(f"{source} path '{path}' must map to a string, object, or array")
        if len(serialized) > MAX_RUNTIME_CONFIG_CONTENT_CHARS:
            raise ValueError(f"{source} path '{path}' exceeds {MAX_RUNTIME_CONFIG_CONTENT_CHARS} characters")
        total_chars += len(serialized)
        normalized[path] = value

    if total_chars > MAX_RUNTIME_CONFIG_TOTAL_CHARS:
        raise ValueError(f"{source} exceeds the total content limit of {MAX_RUNTIME_CONFIG_TOTAL_CHARS} characters")
    return normalized


def merge_runtime_config_files(*config_sets: tuple[Any, str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value, source in config_sets:
        merged.update(parse_runtime_config_files(value, source=source))
    return merged


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n([\s\S]*?)\n```")


def parse_json_output(text: str) -> Any | None:
    """Extract a JSON object or array from agent response text.

    Tries two strategies:
    1. The entire stripped text is a valid JSON object/array.
    2. A markdown code-fenced block (````` ```json ... ``` `````) contains
       valid JSON.  When multiple fenced blocks exist, the *last* one wins
       (agents typically place their final answer at the end).
    """
    candidate = text.strip()
    if not candidate:
        return None
    # Strategy 1: entire text is JSON
    if (candidate.startswith("{") and candidate.endswith("}")) or (
        candidate.startswith("[") and candidate.endswith("]")
    ):
        try:
            return json.loads(candidate)
        except ValueError:
            logger.debug("JSON parse failed for candidate: %s", candidate[:200], exc_info=True)
    # Strategy 2: extract from markdown code fences
    fences = _FENCED_JSON_RE.findall(candidate)
    for fenced_content in reversed(fences):
        fenced = fenced_content.strip()
        if not fenced:
            continue
        if (fenced.startswith("{") and fenced.endswith("}")) or (fenced.startswith("[") and fenced.endswith("]")):
            try:
                return json.loads(fenced)
            except ValueError:
                continue
    return None


def missing_json_paths(payload: Any, required_paths: Sequence[str]) -> list[str]:
    """Return required dotted JSON paths that are missing or blank."""
    missing: list[str] = []
    for raw_path in required_paths:
        path = str(raw_path).strip()
        if not path:
            continue
        value = _lookup_path(payload, path.split("."))
        if value in (None, "", [], {}):
            missing.append(path)
    return missing


def _resolve_template_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _lookup_path(payload: Any, path_parts: list[str]) -> Any | None:
    current = payload
    for part in path_parts:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return None
            index = int(part)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def render_prompt(
    template: str,
    workflow_input: str,
    previous_output: str,
    step_results: dict[str, dict[str, Any]],
    project_context: str = "",
) -> str:
    """Render a workflow prompt template, substituting structured placeholders.

    If *project_context* is provided it is prepended as a ``[Project Context]``
    block so every step benefits from shared project knowledge.
    """

    def replacer(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression == "input":
            return workflow_input
        if expression == "previous_output":
            return previous_output

        root, _, remainder = expression.partition(".")
        if root not in step_results:
            logger.warning(
                "render_prompt: unresolvable placeholder '{{%s}}' — step '%s' has no result", expression, root
            )
            return ""

        if not remainder:
            return _resolve_template_value(step_results[root])

        value = _lookup_path(step_results[root], remainder.split("."))
        if value is None:
            logger.warning("render_prompt: unresolvable placeholder '{{%s}}' — path not found", expression)
            return ""
        return _resolve_template_value(value)

    rendered = PLACEHOLDER_RE.sub(replacer, template)
    if project_context:
        rendered = f"[Project Context]\n{project_context}\n\n{rendered}"
    return rendered


def validate_workflow_graph(steps: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not steps:
        raise ValueError("AgentWorkflow must contain at least one step")
    if len(steps) > MAX_WORKFLOW_STEPS:
        raise ValueError(f"AgentWorkflow contains {len(steps)} steps, exceeding the limit of {MAX_WORKFLOW_STEPS}")

    ordered_names: list[str] = []
    step_map: dict[str, dict[str, Any]] = {}
    for step in steps:
        step_name = str(step.get("name", "")).strip()
        if not step_name:
            raise ValueError("Workflow step names must not be empty")
        if step_name in step_map:
            raise ValueError("AgentWorkflow step names must be unique")
        ordered_names.append(step_name)
        step_map[step_name] = step

    adjacency: dict[str, set[str]] = {name: set() for name in ordered_names}
    undirected: dict[str, set[str]] = {name: set() for name in ordered_names}
    indegree: dict[str, int] = dict.fromkeys(ordered_names, 0)

    for step_name, step in step_map.items():
        dependencies = [str(dep).strip() for dep in step.get("dependsOn") or [] if str(dep).strip()]
        missing_dependencies = [dependency for dependency in dependencies if dependency not in step_map]
        if missing_dependencies:
            raise ValueError(f"Workflow step '{step_name}' depends on unknown steps: {missing_dependencies}")
        for dependency in dependencies:
            adjacency[dependency].add(step_name)
            undirected[dependency].add(step_name)
            undirected[step_name].add(dependency)
            indegree[step_name] += 1

        # Validate conditional step branch references
        step_type = str(step.get("type", "agent")).strip()
        if step_type == "conditional":
            for branch_field in ("thenSteps", "elseSteps"):
                branch_refs = [str(s).strip() for s in (step.get(branch_field) or []) if str(s).strip()]
                missing_refs = [ref for ref in branch_refs if ref not in step_map]
                if missing_refs:
                    raise ValueError(
                        f"Conditional step '{step_name}' references unknown steps in {branch_field}: {missing_refs}"
                    )
                # Add implicit connectivity edges so branch targets remain in the connected graph
                for ref in branch_refs:
                    undirected[step_name].add(ref)
                    undirected[ref].add(step_name)

    roots = [name for name, degree in indegree.items() if degree == 0]
    if not roots:
        raise ValueError("Workflow must contain at least one root step")

    indegree_copy = dict(indegree)
    queue = deque(roots)
    topological_order: list[str] = []
    while queue:
        current = queue.popleft()
        topological_order.append(current)
        for child in sorted(adjacency[current]):
            indegree_copy[child] -= 1
            if indegree_copy[child] == 0:
                queue.append(child)

    if len(topological_order) != len(step_map):
        raise ValueError("Workflow contains a dependency cycle")

    visited: set[str] = set()
    connectivity_queue = deque([ordered_names[0]])
    while connectivity_queue:
        current = connectivity_queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for neighbor in sorted(undirected[current]):
            if neighbor not in visited:
                connectivity_queue.append(neighbor)

    if visited != set(ordered_names):
        disconnected = sorted(set(ordered_names) - visited)
        raise ValueError(f"Workflow must form a single connected DAG. Disconnected steps: {disconnected}")

    return {
        "stepMap": step_map,
        "topologicalOrder": topological_order,
        "roots": roots,
        "edges": {name: sorted(children) for name, children in adjacency.items()},
    }


def ready_workflow_steps(
    steps: Sequence[dict[str, Any]],
    completed_steps: set[str],
    skipped_steps: set[str] | None = None,
) -> list[dict[str, Any]]:
    ignored = skipped_steps or set()
    ready: list[dict[str, Any]] = []
    for step in steps:
        step_name = str(step.get("name", "")).strip()
        if not step_name or step_name in completed_steps or step_name in ignored:
            continue
        dependencies = {str(dep).strip() for dep in step.get("dependsOn") or [] if str(dep).strip()}
        if dependencies.issubset(completed_steps | ignored):
            ready.append(step)
    return ready


def compute_execution_waves(
    steps: Sequence[dict[str, Any]],
    completed_steps: set[str] | None = None,
    skipped_steps: set[str] | None = None,
) -> list[list[dict[str, Any]]]:
    """Group remaining workflow steps into execution waves.

    Wave N contains all steps whose dependencies are fully satisfied by the
    union of *completed_steps* and all steps in waves 0..N-1.  This is a
    topological-level grouping that maximises parallelism within each wave.
    """
    done = set(completed_steps or set())
    ignored = set(skipped_steps or set())
    remaining = [
        s
        for s in steps
        if str(s.get("name", "")).strip()
        and str(s.get("name", "")).strip() not in done
        and str(s.get("name", "")).strip() not in ignored
    ]
    waves: list[list[dict[str, Any]]] = []
    while remaining:
        wave = [
            s
            for s in remaining
            if {str(d).strip() for d in s.get("dependsOn") or [] if str(d).strip()}.issubset(done | ignored)
        ]
        if not wave:
            break  # remaining steps have unresolvable deps; caller handles
        waves.append(wave)
        done |= {str(s.get("name", "")).strip() for s in wave}
        remaining = [s for s in remaining if str(s.get("name", "")).strip() not in done]
    return waves


def normalize_step_execution(step: dict[str, Any]) -> dict[str, Any]:
    execution = step.get("execution") or {}
    if not isinstance(execution, dict):
        execution = {}
    pre_auth = execution.get("preAuthorizedActions") or []
    if not isinstance(pre_auth, list):
        pre_auth = []
    required_json_paths = execution.get("requiredJsonPaths") or []
    if not isinstance(required_json_paths, list):
        required_json_paths = []
    return {
        "timeoutSeconds": max(
            float(execution.get("timeoutSeconds", AGENT_RUNTIME_TIMEOUT_SECONDS) or AGENT_RUNTIME_TIMEOUT_SECONDS), 1.0
        ),
        "maxAttempts": max(
            int(execution.get("maxAttempts", DEFAULT_WORKFLOW_STEP_MAX_ATTEMPTS) or DEFAULT_WORKFLOW_STEP_MAX_ATTEMPTS),
            1,
        ),
        "backoffSeconds": max(
            float(
                execution.get("backoffSeconds", DEFAULT_WORKFLOW_STEP_BACKOFF_SECONDS)
                or DEFAULT_WORKFLOW_STEP_BACKOFF_SECONDS
            ),
            0.0,
        ),
        "retryable": bool(execution.get("retryable", True)),
        "continueOnError": bool(execution.get("continueOnError", False)),
        "preAuthorizedActions": [str(a).strip() for a in pre_auth if str(a).strip()],
        "requiredJsonPaths": [str(path).strip() for path in required_json_paths if str(path).strip()],
        "sessionGroup": str(execution.get("sessionGroup") or "").strip(),
        "verifyRetries": max(int(execution.get("verifyRetries", 0) or 0), 0),
        "maxTurns": max(int(execution.get("maxTurns", 0) or 0), 0),
    }


def unsupported_policy_budget_fields(policy_spec: dict[str, Any]) -> list[str]:
    budget = policy_spec.get("budget") or {}
    if not isinstance(budget, dict):
        return []

    unsupported_fields: list[str] = []
    for field_name in UNSUPPORTED_POLICY_BUDGET_FIELDS:
        value = budget.get(field_name)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        unsupported_fields.append(field_name)
    return unsupported_fields


def normalize_a2a_peer_ref(raw_value: Any, *, source: str) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{source} entries must be objects with 'name' and 'namespace' fields.")

    name = str(raw_value.get("name", "")).strip()
    namespace = str(raw_value.get("namespace", "")).strip()
    if not name or not namespace:
        raise ValueError(f"{source} entries must include non-empty 'name' and 'namespace' values.")
    if not K8S_NAME_RE.fullmatch(name):
        raise ValueError(f"{source} name '{name}' must be a valid lowercase Kubernetes resource name.")
    if not K8S_NAME_RE.fullmatch(namespace):
        raise ValueError(f"{source} namespace '{namespace}' must be a valid lowercase Kubernetes namespace name.")

    return {"name": name, "namespace": namespace}


def parse_a2a_peer_refs(peer_refs: Any, *, source: str) -> list[dict[str, str]]:
    if peer_refs is None:
        return []
    if not isinstance(peer_refs, list):
        raise ValueError(f"{source} must be a list of objects with 'name' and 'namespace' fields.")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_value in enumerate(peer_refs):
        peer_ref = normalize_a2a_peer_ref(raw_value, source=f"{source}[{index}]")
        identity = (peer_ref["namespace"], peer_ref["name"])
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(peer_ref)
    return normalized


def parse_agent_a2a_config(a2a_config: Any, *, source: str = "AIAgent.spec.a2a") -> dict[str, Any]:
    if a2a_config is None:
        return {}
    if not isinstance(a2a_config, dict):
        raise ValueError(f"{source} must be an object when provided.")

    allowed_callers = parse_a2a_peer_refs(
        a2a_config.get("allowedCallers"),
        source=f"{source}.allowedCallers",
    )
    return {"allowedCallers": allowed_callers} if allowed_callers else {}


def parse_policy_a2a_config(policy_spec: dict[str, Any]) -> dict[str, Any]:
    a2a_config = policy_spec.get("a2a")
    if a2a_config is None:
        return {}
    if not isinstance(a2a_config, dict):
        raise ValueError("AgentPolicy.spec.a2a must be an object when provided.")

    allowed_targets = parse_a2a_peer_refs(
        a2a_config.get("allowedTargets"),
        source="AgentPolicy.spec.a2a.allowedTargets",
    )
    require_hitl = bool(a2a_config.get("requireHitl", False))
    max_timeout_seconds = a2a_config.get("maxTimeoutSeconds")
    if max_timeout_seconds is not None:
        try:
            max_timeout_seconds = float(max_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("AgentPolicy.spec.a2a.maxTimeoutSeconds must be a number.") from exc
        if max_timeout_seconds < 1:
            raise ValueError("AgentPolicy.spec.a2a.maxTimeoutSeconds must be at least 1 second.")

    parsed: dict[str, Any] = {}
    if allowed_targets:
        parsed["allowedTargets"] = allowed_targets
    if max_timeout_seconds is not None:
        parsed["maxTimeoutSeconds"] = max_timeout_seconds
    if require_hitl:
        parsed["requireHitl"] = True
    return parsed


def parse_tool_policy_config(policy_spec: dict[str, Any]) -> dict[str, Any]:
    tool_policy = policy_spec.get("toolPolicy")
    if tool_policy is None:
        return {}
    if not isinstance(tool_policy, dict):
        raise ValueError("AgentPolicy.spec.toolPolicy must be an object when provided.")

    parsed: dict[str, Any] = {}

    max_delegation_depth = tool_policy.get("maxDelegationDepth")
    if max_delegation_depth is not None:
        try:
            max_delegation_depth = int(max_delegation_depth)
        except (TypeError, ValueError) as exc:
            raise ValueError("AgentPolicy.spec.toolPolicy.maxDelegationDepth must be an integer.") from exc
        if max_delegation_depth < 0:
            raise ValueError("AgentPolicy.spec.toolPolicy.maxDelegationDepth must be >= 0.")
        parsed["maxDelegationDepth"] = max_delegation_depth

    allowed_tool_prefixes = tool_policy.get("allowedToolPrefixes")
    if allowed_tool_prefixes is not None:
        if not isinstance(allowed_tool_prefixes, list):
            raise ValueError("AgentPolicy.spec.toolPolicy.allowedToolPrefixes must be a list of strings.")
        normalized_prefixes = [str(item).strip() for item in allowed_tool_prefixes if str(item).strip()]
        parsed["allowedToolPrefixes"] = sorted(dict.fromkeys(normalized_prefixes))

    blocked_tool_names = tool_policy.get("blockedToolNames")
    if blocked_tool_names is not None:
        if not isinstance(blocked_tool_names, list):
            raise ValueError("AgentPolicy.spec.toolPolicy.blockedToolNames must be a list of strings.")
        normalized_blocked = [str(item).strip() for item in blocked_tool_names if str(item).strip()]
        parsed["blockedToolNames"] = sorted(dict.fromkeys(normalized_blocked))

    require_approval_for = tool_policy.get("requireApprovalFor")
    if require_approval_for is not None:
        if not isinstance(require_approval_for, list):
            raise ValueError("AgentPolicy.spec.toolPolicy.requireApprovalFor must be a list of strings.")
        normalized_approval = [str(item).strip() for item in require_approval_for if str(item).strip()]
        parsed["requireApprovalFor"] = sorted(dict.fromkeys(normalized_approval))

    return parsed


def parse_memory_policy_config(policy_spec: dict[str, Any]) -> dict[str, Any]:
    memory_policy = policy_spec.get("memoryPolicy")
    if memory_policy is None:
        return {}
    if not isinstance(memory_policy, dict):
        raise ValueError("AgentPolicy.spec.memoryPolicy must be an object when provided.")

    parsed: dict[str, Any] = {}

    max_injected_memories = memory_policy.get("maxInjectedMemories")
    if max_injected_memories is not None:
        try:
            max_injected_memories = int(max_injected_memories)
        except (TypeError, ValueError) as exc:
            raise ValueError("AgentPolicy.spec.memoryPolicy.maxInjectedMemories must be an integer.") from exc
        if max_injected_memories < 0:
            raise ValueError("AgentPolicy.spec.memoryPolicy.maxInjectedMemories must be >= 0.")
        parsed["maxInjectedMemories"] = max_injected_memories

    max_injected_chars = memory_policy.get("maxInjectedChars")
    if max_injected_chars is not None:
        try:
            max_injected_chars = int(max_injected_chars)
        except (TypeError, ValueError) as exc:
            raise ValueError("AgentPolicy.spec.memoryPolicy.maxInjectedChars must be an integer.") from exc
        if max_injected_chars < 0:
            raise ValueError("AgentPolicy.spec.memoryPolicy.maxInjectedChars must be >= 0.")
        parsed["maxInjectedChars"] = max_injected_chars

    allowed_memory_types = memory_policy.get("allowedMemoryTypes")
    if allowed_memory_types is not None:
        if not isinstance(allowed_memory_types, list):
            raise ValueError("AgentPolicy.spec.memoryPolicy.allowedMemoryTypes must be a list of strings.")
        normalized_types = [str(item).strip() for item in allowed_memory_types if str(item).strip()]
        parsed["allowedMemoryTypes"] = sorted(dict.fromkeys(normalized_types))

    auto_promote = memory_policy.get("autoPromote")
    if auto_promote is not None:
        if not isinstance(auto_promote, bool):
            raise ValueError("AgentPolicy.spec.memoryPolicy.autoPromote must be a boolean.")
        parsed["autoPromote"] = auto_promote

    return parsed


def validate_supported_policy_spec(policy_spec: dict[str, Any]) -> None:
    unsupported_fields = unsupported_policy_budget_fields(policy_spec)
    if unsupported_fields:
        joined_fields = ", ".join(sorted(unsupported_fields))
        raise ValueError(
            "AgentPolicy.spec.budget is reserved for future distributed enforcement and is not supported today. "
            f"Remove these fields to use this policy: {joined_fields}."
        )
    parse_policy_a2a_config(policy_spec)
    parse_tool_policy_config(policy_spec)
    parse_memory_policy_config(policy_spec)


def normalize_skill_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise ValueError("Skill file paths must not be blank.")
    if len(normalized_path) > MAX_AGENT_SKILL_FILE_PATH_CHARS:
        raise ValueError(f"Skill file paths must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer.")
    if normalized_path.startswith("/"):
        raise ValueError("Skill file paths must be relative to the agent skill root.")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Skill file path '{raw_path}' is invalid.")

    candidate = "/".join(parts)
    if not candidate.lower().endswith(".md"):
        raise ValueError(f"Skill file path '{candidate}' must point to a Markdown file ending in .md.")
    return candidate


def parse_agent_skills_config(skills_config: Any, *, source: str = "AIAgent.spec.skills", namespace: str | None = None) -> dict[str, Any]:
    if skills_config is None:
        return {}
    if not isinstance(skills_config, dict):
        raise ValueError(f"{source} must be an object when provided.")

    raw_files = skills_config.get("files")
    config_map_ref = skills_config.get("configMapRef")
    merged_files: dict[str, str] = {}

    if isinstance(raw_files, dict):
        merged_files = dict(raw_files)
    elif raw_files is not None:
        raise ValueError(f"{source}.files must be a mapping of relative Markdown paths to file contents.")

    if config_map_ref is not None:
        if not isinstance(config_map_ref, str) or not config_map_ref.strip():
            raise ValueError(f"{source}.configMapRef must be a non-empty string.")
        config_map_ref = config_map_ref.strip()
        if namespace:
            try:
                import kubernetes.client
                from kubernetes.client.rest import ApiException
                core_api = kubernetes.client.CoreV1Api()
                cm = core_api.read_namespaced_config_map(name=config_map_ref, namespace=namespace)
            except ApiException as exc:
                if exc.status == 404:
                    raise ValueError(
                        f"{source}.configMapRef '{config_map_ref}' not found in namespace '{namespace}'."
                    ) from exc
                raise ValueError(
                    f"{source}.configMapRef '{config_map_ref}' could not be read: {exc}"
                ) from exc
            cm_data = cm.data or {}
            if not isinstance(cm_data, dict):
                raise ValueError(f"{source}.configMapRef '{config_map_ref}' data is not a valid mapping.")
            for key, value in cm_data.items():
                if key not in merged_files:
                    merged_files[key] = str(value)

    if not merged_files and not config_map_ref:
        return {}

    if len(merged_files) > MAX_AGENT_SKILL_FILES:
        raise ValueError(f"{source}.files cannot contain more than {MAX_AGENT_SKILL_FILES} entries.")

    normalized_files: dict[str, str] = {}
    total_chars = 0
    for raw_path, raw_content in sorted(merged_files.items(), key=lambda item: str(item[0])):
        normalized_path = normalize_skill_file_path(raw_path)
        if not isinstance(raw_content, str):
            raise ValueError(f"{source}.files.{normalized_path} must be a Markdown string.")
        if not raw_content.strip():
            raise ValueError(f"{source}.files.{normalized_path} must not be blank.")
        if len(raw_content) > MAX_AGENT_SKILL_FILE_CONTENT_CHARS:
            raise ValueError(
                f"{source}.files.{normalized_path} exceeds {MAX_AGENT_SKILL_FILE_CONTENT_CHARS} characters."
            )
        total_chars += len(raw_content)
        if total_chars > MAX_AGENT_SKILL_TOTAL_CHARS:
            raise ValueError(f"{source}.files exceeds the total limit of {MAX_AGENT_SKILL_TOTAL_CHARS} characters.")
        normalized_files[normalized_path] = raw_content.replace("\r\n", "\n")

    result: dict[str, Any] = {}
    if normalized_files:
        result["files"] = normalized_files
    if config_map_ref:
        result["configMapRef"] = config_map_ref
    return result


def runtime_error_message(response: httpx.Response, *, max_body_chars: int = 400) -> str:
    """Build a compact HTTP error message that includes a trimmed response body."""
    try:
        response.read()
    except Exception as exc:
        logger.debug("Could not read response body: %s", exc, exc_info=True)

    body = ""
    try:
        body = " ".join(response.text.strip().split())
    except Exception as exc:
        logger.debug("Could not decode response text: %s", exc, exc_info=True)

    if body and len(body) > max_body_chars:
        body = f"{body[:max_body_chars].rstrip()}..."

    base = f"Runtime request failed with HTTP {response.status_code} for url '{response.request.url}'"
    return f"{base}: {body}" if body else base


def summarize_preview_text(value: Any, *, limit: int = 280) -> str | None:
    """Render a short, whitespace-collapsed preview of a value for log output."""
    text = str(value or "").strip()
    if not text:
        return None
    collapsed = re.sub(r"\s+", " ", text)
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: max(limit - 3, 1)].rstrip()}..."


def summarize_tool_input(tool_input: Any) -> str | None:
    """Pick a meaningful preview from a tool input dict, list, or scalar."""
    if isinstance(tool_input, dict):
        for key in (
            "command",
            "path",
            "filePath",
            "file_path",
            "target_dir",
            "workingDirectory",
            "working_directory",
            "query",
            "url",
            "repo",
            "name",
        ):
            preview = summarize_preview_text(tool_input.get(key), limit=160)
            if preview:
                return preview
        return summarize_preview_text(json.dumps(tool_input, sort_keys=True, default=str), limit=160)
    if isinstance(tool_input, list):
        return summarize_preview_text(json.dumps(tool_input, sort_keys=True, default=str), limit=160)
    return summarize_preview_text(tool_input, limit=160)


def _preview_stream_value(value: Any, *, limit: int = 160) -> str:
    preview = summarize_preview_text(value, limit=limit)
    return preview or ""


def _tool_call_input_preview(tool_input: Any) -> str:
    return summarize_tool_input(tool_input) or ""


def runtime_auth_headers() -> dict[str, str]:
    token = os.getenv("RUNTIME_BEARER_TOKEN", "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def invoke_agent_runtime(
    agent_name: str,
    namespace: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """POST an invoke request to the agent runtime and return the response body."""
    if not agent_name or not K8S_NAME_RE.fullmatch(agent_name):
        raise ValueError(f"Invalid agent name for runtime invocation: {agent_name!r}")
    if not namespace or not K8S_NAME_RE.fullmatch(namespace):
        raise ValueError(f"Invalid namespace for runtime invocation: {namespace!r}")
    effective_timeout = timeout_seconds or AGENT_RUNTIME_TIMEOUT_SECONDS
    url = f"{runtime_url(agent_name, namespace)}/invoke"
    last_exc: Exception | None = None
    for attempt in range(3):
        # Create a fresh client per attempt so each gets the full timeout
        # budget instead of sharing a single countdown across retries.
        with httpx.Client(timeout=effective_timeout) as client:
            response = client.post(url, json=payload, headers=runtime_auth_headers())
        if response.status_code < 500:
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    runtime_error_message(response),
                    request=response.request,
                    response=response,
                )
            return response.json()  # type: ignore[no-any-return]
        last_exc = httpx.HTTPStatusError(
            runtime_error_message(response),
            request=response.request,
            response=response,
        )
        if attempt < 2:
            time.sleep(min(2**attempt, 4))
    raise last_exc  # type: ignore[misc]


def invoke_agent_runtime_stream(
    agent_name: str,
    namespace: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float | None = None,
    step_name: str = "",
    iteration: int = 0,
    on_todo_update: Callable[[list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    """POST to /invoke/stream SSE endpoint, log events in real-time, return final result.

    Falls back to the synchronous /invoke endpoint if streaming fails.
    """
    if not agent_name or not K8S_NAME_RE.fullmatch(agent_name):
        raise ValueError(f"Invalid agent name for runtime invocation: {agent_name!r}")
    if not namespace or not K8S_NAME_RE.fullmatch(namespace):
        raise ValueError(f"Invalid namespace for runtime invocation: {namespace!r}")
    effective_timeout = timeout_seconds or AGENT_RUNTIME_TIMEOUT_SECONDS
    stream_url = f"{runtime_url(agent_name, namespace)}/invoke/stream"
    prefix = f"[opencode {step_name} iter={iteration}]" if step_name else f"[opencode {agent_name}]"

    try:
        with httpx.Client(timeout=effective_timeout) as client:  # noqa: SIM117 — nested with for clarity
            with client.stream("POST", stream_url, json=payload, headers=runtime_auth_headers()) as resp:
                if resp.status_code >= 400:
                    logger.warning(
                        "%s stream returned %d, falling back to /invoke: %s",
                        prefix,
                        resp.status_code,
                        runtime_error_message(resp),
                    )
                    return invoke_agent_runtime(agent_name, namespace, payload, timeout_seconds=timeout_seconds)
                final_result: dict[str, Any] = {}
                response_chunks: list[str] = []
                reasoning_chunks: list[str] = []
                streamed_tool_calls: list[dict[str, Any]] = []
                turn_count = 0
                current_event_type = ""
                for line in resp.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event: "):
                        current_event_type = line[7:].strip()
                        continue
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except (json.JSONDecodeError, ValueError):
                        current_event_type = ""
                        continue
                    etype = current_event_type
                    current_event_type = ""  # reset for next event
                    if not etype:
                        continue
                    if etype == "response.turn_started":
                        turn_count += 1
                        agent_name_hint = data.get("agent", "")
                        logger.info("%s turn %d started (agent=%s)", prefix, turn_count, agent_name_hint or "default")
                    elif etype == "response.turn_completed":
                        status = data.get("status", "")
                        resp_len = data.get("response_length", 0)
                        logger.info(
                            "%s turn %d completed — status=%s, response=%d chars", prefix, turn_count, status, resp_len
                        )
                    elif etype == "response.reasoning":
                        reasoning_text = str(data.get("reasoning") or "")
                        if reasoning_text:
                            reasoning_chunks.append(reasoning_text)
                            preview = reasoning_text[:200].replace("\n", " ")
                            logger.info(
                                "%s turn %d reasoning: %s%s",
                                prefix,
                                turn_count,
                                preview,
                                "..." if len(reasoning_text) > 200 else "",
                            )
                    elif etype == "response.delta":
                        delta_text = data.get("delta", "")
                        # Log first 200 chars of delta to show what opencode is doing
                        if delta_text:
                            response_chunks.append(str(delta_text))
                            preview = delta_text[:200].replace("\n", " ")
                            logger.info(
                                "%s turn %d delta: %s%s",
                                prefix,
                                turn_count,
                                preview,
                                "..." if len(delta_text) > 200 else "",
                            )
                    elif etype == "response.tool_call":
                        tool_name = str(data.get("tool", "") or "tool")
                        tool_status = str(data.get("status", "unknown") or "unknown")
                        streamed_tool_calls.append(dict(data))
                        input_preview = _tool_call_input_preview(data.get("input"))
                        suffix = f": {input_preview}" if input_preview else ""
                        logger.info(
                            "%s tool_call: %s [%s]%s",
                            prefix,
                            tool_name,
                            tool_status,
                            suffix,
                        )
                    elif etype == "response.patch":
                        raw_files = data.get("files")
                        patch_files: list[str] = []
                        if isinstance(raw_files, list):
                            for item in raw_files[:5]:
                                if isinstance(item, dict):
                                    file_name = str(item.get("path") or item.get("file") or item.get("name") or "").strip()
                                else:
                                    file_name = str(item or "").strip()
                                if file_name:
                                    patch_files.append(file_name)
                        logger.info(
                            "%s patch: %d file(s)%s",
                            prefix,
                            len(raw_files) if isinstance(raw_files, list) else 0,
                            f" — {', '.join(patch_files)}" if patch_files else "",
                        )
                    elif etype == "response.completed":
                        final_result = data
                        streamed_response = "".join(response_chunks)
                        completed_response = str(final_result.get("response", "") or "").strip()
                        # Prefer the accumulated streamed response when it is materially
                        # longer than the payload in the completed event.  Some runtimes
                        # truncate the final response field while the delta stream is
                        # complete.
                        if not completed_response or (
                            streamed_response and len(streamed_response) > len(completed_response) + 100
                        ):
                            final_result["response"] = streamed_response
                        if not final_result.get("tool_calls") and streamed_tool_calls:
                            final_result["tool_calls"] = streamed_tool_calls
                        if final_result.get("metadata") is None:
                            final_result["metadata"] = {}
                        reasoning_text = "".join(reasoning_chunks)
                        if reasoning_text and not final_result.get("metadata", {}).get("reasoning_text"):
                            final_result["metadata"]["reasoning_text"] = reasoning_text
                        last_response = str(final_result.get("response", ""))
                        logger.info(
                            "%s completed — turns: %d, response: %d chars", prefix, turn_count, len(last_response)
                        )
                    elif etype == "response.error":
                        err_msg = data.get("error", "unknown")
                        logger.warning("%s error event: %s", prefix, err_msg)
                    elif etype == "response.compaction":
                        reason = data.get("reason", "?")
                        logger.info("%s context compaction triggered (reason=%s)", prefix, reason)
                    elif etype == "response.error_recovery":
                        retry = data.get("retry", "?")
                        logger.info("%s error recovery, retry=%s", prefix, retry)
                    elif etype in ("todo.updated", "todo.cleared") and on_todo_update is not None:
                        todos = data.get("todos")
                        if isinstance(todos, list):
                            on_todo_update(todos)
                if final_result:
                    return final_result
                # Stream ended without completed event — fall back
                logger.warning("%s stream ended without completed event, falling back", prefix)
                return invoke_agent_runtime(agent_name, namespace, payload, timeout_seconds=timeout_seconds)
    except Exception as exc:
        logger.warning("%s stream failed (%s), falling back to /invoke", prefix, exc)
        return invoke_agent_runtime(agent_name, namespace, payload, timeout_seconds=timeout_seconds)


def cancel_agent_session(
    agent_name: str,
    namespace: str,
    thread_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> bool:
    """Send a cancel request to the agent runtime to abort a running session.

    Returns True if the cancel was acknowledged, False on any error.
    """
    try:
        url = f"{runtime_url(agent_name, namespace)}/cancel"
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(url, params={"thread_id": thread_id}, headers=runtime_auth_headers())
        return response.status_code == 200
    except Exception as exc:
        logger.debug("Agent session cancel failed for %s/%s: %s", agent_name, namespace, exc, exc_info=True)
        return False
