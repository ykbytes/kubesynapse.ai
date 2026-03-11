"""Shared utility functions used by the operator controller and worker."""

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import time
from typing import Any, Sequence

import httpx


logger = logging.getLogger("operator-utils")
PLACEHOLDER_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


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


def workflow_journal_path(artifact_path: str) -> str:
    if artifact_path.endswith(".json"):
        return f"{artifact_path[:-5]}.journal.ndjson"
    return f"{artifact_path}.journal.ndjson"


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


def invoke_agent_runtime(
    agent_name: str,
    namespace: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """POST an invoke request to the agent runtime and return the response body."""
    with httpx.Client(
        timeout=timeout_seconds or AGENT_RUNTIME_TIMEOUT_SECONDS,
        transport=httpx.HTTPTransport(retries=2),
    ) as client:
        response = client.post(f"{runtime_url(agent_name, namespace)}/invoke", json=payload)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


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
