"""Shared utility functions used by the operator controller and worker."""

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import PurePosixPath
import re
import time
from typing import Any, Sequence

import httpx


logger = logging.getLogger("operator-utils")

PLACEHOLDER_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")
K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def get_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(float(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid float value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_int_env(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(int(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid integer value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


AGENT_RUNTIME_TIMEOUT_SECONDS = get_float_env("AGENT_RUNTIME_TIMEOUT_SECONDS", 360.0, minimum=1.0)
MAX_THREAD_ID_CHARS = get_int_env("AGENT_MAX_THREAD_ID_CHARS", 128, minimum=16)
DEFAULT_WORKFLOW_STEP_MAX_ATTEMPTS = get_int_env("WORKFLOW_DEFAULT_MAX_ATTEMPTS", 1, minimum=1)
DEFAULT_WORKFLOW_STEP_BACKOFF_SECONDS = get_float_env("WORKFLOW_DEFAULT_BACKOFF_SECONDS", 2.0, minimum=0.0)
UNSUPPORTED_POLICY_BUDGET_FIELDS = (
    "maxTokensPerHour",
    "maxRequestsPerMinute",
    "maxCostPerDayUSD",
)
GOOSE_CONFIG_FORBIDDEN_FILES = {"secrets.yaml"}
MAX_AGENT_SKILL_FILES = get_int_env("AGENT_MAX_SKILL_FILES", 24, minimum=1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_PATH_CHARS", 256, minimum=32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", 16000, minimum=512)
MAX_AGENT_SKILL_TOTAL_CHARS = get_int_env("AGENT_MAX_SKILL_TOTAL_CHARS", 64000, minimum=4096)
MAX_RUNTIME_CONFIG_FILES = get_int_env("RUNTIME_MAX_CONFIG_FILES", 64, minimum=1)
MAX_RUNTIME_CONFIG_PATH_CHARS = get_int_env("RUNTIME_MAX_CONFIG_PATH_CHARS", 256, minimum=32)
MAX_RUNTIME_CONFIG_CONTENT_CHARS = get_int_env("RUNTIME_MAX_CONFIG_CONTENT_CHARS", 64000, minimum=512)
MAX_RUNTIME_CONFIG_TOTAL_CHARS = get_int_env("RUNTIME_MAX_CONFIG_TOTAL_CHARS", 256000, minimum=4096)


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


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

    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    keep_length = max(max_length - len(digest) - 1, 1)
    truncated = base[:keep_length].rstrip("-_") or prefix
    return f"{truncated}-{digest}"


def build_workflow_run_id(namespace: str, workflow_name: str, generation: int) -> str:
    epoch_ms = int(time.time() * 1000)
    digest = hashlib.sha1(
        f"workflow:{namespace}:{workflow_name}:{generation}:{epoch_ms}".encode("utf-8")
    ).hexdigest()[:8]
    return build_thread_id("wf-run", namespace, workflow_name, generation, epoch_ms, digest, max_length=96)


def build_eval_run_id(namespace: str, eval_name: str, generation: int) -> str:
    epoch_ms = int(time.time() * 1000)
    digest = hashlib.sha1(
        f"eval:{namespace}:{eval_name}:{generation}:{epoch_ms}".encode("utf-8")
    ).hexdigest()[:8]
    return build_thread_id("eval-run", namespace, eval_name, generation, epoch_ms, digest, max_length=96)


def workflow_journal_path(artifact_path: str) -> str:
    if artifact_path.endswith(".json"):
        return f"{artifact_path[:-5]}.journal.ndjson"
    return f"{artifact_path}.journal.ndjson"


def _normalize_runtime_config_path(raw_path: Any, *, source: str) -> str:
    candidate = str(raw_path or "").strip().replace("\\", "/")
    if not candidate:
        raise ValueError(f"{source} path must not be blank")
    if len(candidate) > MAX_RUNTIME_CONFIG_PATH_CHARS:
        raise ValueError(
            f"{source} path '{candidate}' exceeds {MAX_RUNTIME_CONFIG_PATH_CHARS} characters"
        )
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
        if isinstance(raw_content, str):
            serialized = raw_content
            value: Any = raw_content
        elif isinstance(raw_content, (dict, list)):
            serialized = json.dumps(raw_content, ensure_ascii=False, sort_keys=True)
            value = raw_content
        else:
            raise ValueError(
                f"{source} path '{path}' must map to a string, object, or array"
            )
        if len(serialized) > MAX_RUNTIME_CONFIG_CONTENT_CHARS:
            raise ValueError(
                f"{source} path '{path}' exceeds {MAX_RUNTIME_CONFIG_CONTENT_CHARS} characters"
            )
        total_chars += len(serialized)
        normalized[path] = value

    if total_chars > MAX_RUNTIME_CONFIG_TOTAL_CHARS:
        raise ValueError(
            f"{source} exceeds the total content limit of {MAX_RUNTIME_CONFIG_TOTAL_CHARS} characters"
        )
    return normalized


def parse_json_output(text: str) -> Any | None:
    candidate = text.strip()
    if not candidate:
        return None
    if not ((candidate.startswith("{") and candidate.endswith("}")) or (candidate.startswith("[") and candidate.endswith("]"))):
        return None
    try:
        return json.loads(candidate)
    except ValueError:
        return None


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
) -> str:
    """Render a workflow prompt template, substituting structured placeholders."""

    def replacer(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression == "input":
            return workflow_input
        if expression == "previous_output":
            return previous_output

        root, _, remainder = expression.partition(".")
        if root not in step_results:
            return match.group(0)

        if not remainder:
            return _resolve_template_value(step_results[root])

        value = _lookup_path(step_results[root], remainder.split("."))
        if value is None:
            return match.group(0)
        return _resolve_template_value(value)

    return PLACEHOLDER_RE.sub(replacer, template)


def validate_workflow_graph(steps: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not steps:
        raise ValueError("AgentWorkflow must contain at least one step")

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
    indegree: dict[str, int] = {name: 0 for name in ordered_names}

    for step_name, step in step_map.items():
        dependencies = [str(dep).strip() for dep in step.get("dependsOn") or [] if str(dep).strip()]
        missing_dependencies = [dependency for dependency in dependencies if dependency not in step_map]
        if missing_dependencies:
            raise ValueError(
                f"Workflow step '{step_name}' depends on unknown steps: {missing_dependencies}"
            )
        for dependency in dependencies:
            adjacency[dependency].add(step_name)
            undirected[dependency].add(step_name)
            undirected[step_name].add(dependency)
            indegree[step_name] += 1

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
        raise ValueError(
            f"Workflow must form a single connected DAG. Disconnected steps: {disconnected}"
        )

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
        if dependencies.issubset(completed_steps):
            ready.append(step)
    return ready


def normalize_step_execution(step: dict[str, Any]) -> dict[str, Any]:
    execution = step.get("execution") or {}
    if not isinstance(execution, dict):
        execution = {}
    return {
        "timeoutSeconds": max(float(execution.get("timeoutSeconds", AGENT_RUNTIME_TIMEOUT_SECONDS) or AGENT_RUNTIME_TIMEOUT_SECONDS), 1.0),
        "maxAttempts": max(int(execution.get("maxAttempts", DEFAULT_WORKFLOW_STEP_MAX_ATTEMPTS) or DEFAULT_WORKFLOW_STEP_MAX_ATTEMPTS), 1),
        "backoffSeconds": max(float(execution.get("backoffSeconds", DEFAULT_WORKFLOW_STEP_BACKOFF_SECONDS) or DEFAULT_WORKFLOW_STEP_BACKOFF_SECONDS), 0.0),
        "retryable": bool(execution.get("retryable", True)),
        "continueOnError": bool(execution.get("continueOnError", False)),
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
        raise ValueError(
            f"{source} namespace '{namespace}' must be a valid lowercase Kubernetes namespace name."
        )

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


def validate_supported_policy_spec(policy_spec: dict[str, Any]) -> None:
    unsupported_fields = unsupported_policy_budget_fields(policy_spec)
    if unsupported_fields:
        joined_fields = ", ".join(sorted(unsupported_fields))
        raise ValueError(
            "AgentPolicy.spec.budget is reserved for future distributed enforcement and is not supported today. "
            f"Remove these fields to use this policy: {joined_fields}."
        )
    parse_policy_a2a_config(policy_spec)


def normalize_goose_config_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise ValueError("Goose config file paths must not be blank.")
    if normalized_path.startswith("/"):
        raise ValueError("Goose config file paths must be relative to the Goose config root.")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Goose config file path '{raw_path}' is invalid.")

    candidate = "/".join(parts)
    if candidate in GOOSE_CONFIG_FORBIDDEN_FILES:
        raise ValueError(
            "Goose secrets.yaml is not supported here. Inject provider secrets through environment variables instead."
        )
    if parts[0] == "permissions":
        raise ValueError(
            "Goose config files under permissions/ are runtime-managed and cannot be preseeded."
        )
    return candidate


def parse_goose_config_files(config_files: Any, *, source: str) -> dict[str, Any]:
    if config_files is None:
        return {}

    if isinstance(config_files, str):
        trimmed = config_files.strip()
        if not trimmed:
            return {}
        try:
            config_files = json.loads(trimmed)
        except ValueError as exc:
            raise ValueError(
                f"{source} must be a JSON object or mapping of relative Goose config file paths to contents."
            ) from exc

    if not isinstance(config_files, dict):
        raise ValueError(
            f"{source} must be a mapping of relative Goose config file paths to contents."
        )

    normalized_files: dict[str, Any] = {}
    for raw_path, raw_content in sorted(config_files.items(), key=lambda item: str(item[0])):
        normalized_path = normalize_goose_config_file_path(raw_path)
        if raw_content is None:
            raise ValueError(f"{source}.{normalized_path} must not be null.")
        normalized_files[normalized_path] = raw_content
    return normalized_files


def normalize_skill_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise ValueError("Skill file paths must not be blank.")
    if len(normalized_path) > MAX_AGENT_SKILL_FILE_PATH_CHARS:
        raise ValueError(
            f"Skill file paths must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer."
        )
    if normalized_path.startswith("/"):
        raise ValueError("Skill file paths must be relative to the agent skill root.")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"Skill file path '{raw_path}' is invalid.")

    candidate = "/".join(parts)
    if not candidate.lower().endswith(".md"):
        raise ValueError(f"Skill file path '{candidate}' must point to a Markdown file ending in .md.")
    return candidate


def parse_agent_skills_config(skills_config: Any, *, source: str = "AIAgent.spec.skills") -> dict[str, Any]:
    if skills_config is None:
        return {}
    if not isinstance(skills_config, dict):
        raise ValueError(f"{source} must be an object when provided.")

    raw_files = skills_config.get("files")
    if raw_files is None:
        if skills_config:
            raise ValueError(f"{source}.files is required when skills are configured.")
        return {}
    if not isinstance(raw_files, dict):
        raise ValueError(f"{source}.files must be a mapping of relative Markdown paths to file contents.")
    if len(raw_files) > MAX_AGENT_SKILL_FILES:
        raise ValueError(f"{source}.files cannot contain more than {MAX_AGENT_SKILL_FILES} entries.")

    normalized_files: dict[str, str] = {}
    total_chars = 0
    for raw_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
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

    return {"files": normalized_files} if normalized_files else {}


def merge_goose_config_files(*config_sets: tuple[Any, str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value, source in config_sets:
        merged.update(parse_goose_config_files(value, source=source))
    return merged


def invoke_agent_runtime(
    agent_name: str,
    namespace: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """POST an invoke request to the agent runtime and return the response body."""
    effective_timeout = timeout_seconds or AGENT_RUNTIME_TIMEOUT_SECONDS
    url = f"{runtime_url(agent_name, namespace)}/invoke"
    last_exc: Exception | None = None
    for attempt in range(3):
        # Create a fresh client per attempt so each gets the full timeout
        # budget instead of sharing a single countdown across retries.
        with httpx.Client(timeout=effective_timeout) as client:
            response = client.post(url, json=payload)
        if response.status_code < 500:
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        last_exc = httpx.HTTPStatusError(
            f"Server error {response.status_code}",
            request=response.request,
            response=response,
        )
        if attempt < 2:
            import time
            time.sleep(min(2 ** attempt, 4))
    raise last_exc  # type: ignore[misc]


def normalize_text(text: str) -> str:
    """Collapse whitespace and lowercase text for fuzzy comparison."""
    return " ".join(text.lower().split())


def exact_match_score(response: str, expected: str) -> float:
    """Return 1.0 if *expected* appears (normalised) inside *response*, else 0.0."""
    if not expected.strip():
        return 1.0
    return 1.0 if normalize_text(expected) in normalize_text(response) else 0.0


def estimate_toxicity(response: str) -> float:
    """Heuristic toxicity score: 1.0 if a toxic marker is present, 0.0 otherwise."""
    if response.startswith("Request blocked"):
        return 0.0
    markers = (" hate ", " kill ", " stupid ", " idiot ", " racist ")
    lowered = f" {response.lower()} "
    return 1.0 if any(marker in lowered for marker in markers) else 0.0
