"""Shared reconciliation helpers — logging, error classification, and execution.

§2.1d of the road-to-prod plan: extract shared helpers from main.py so that
controller modules can import them without circular dependencies.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import kopf
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from services import describe_api_exception
from tracing import trace_reconcile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERMANENT_API_ERROR_STATUSES: frozenset[int] = frozenset({400, 401, 403, 404, 405, 422})
HIGH_BACKOFF_API_ERROR_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
MAX_LOG_FIELD_LENGTH: int = 400


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _match_namespace_selector(namespace: str, selector: dict[str, Any]) -> bool:
    """Evaluate a minimal namespace selector against a namespace name.

    Current support is intentionally small and backward-compatible:
    - ``matchNames``: explicit namespace allow-list
    - ``matchLabels.kubernetes.io/metadata.name``: exact namespace match
    """
    match_names = selector.get("matchNames")
    if isinstance(match_names, list):
        return namespace in {str(item).strip() for item in match_names if str(item).strip()}

    match_labels = selector.get("matchLabels") or {}
    label_namespace = str(match_labels.get("kubernetes.io/metadata.name") or "").strip()
    if label_namespace:
        return namespace == label_namespace
    return False


def validate_cross_namespace_ref(
    *,
    source_namespace: str,
    target_namespace: str,
    allowed_namespaces: dict[str, Any] | None,
    field_path: str,
    target_kind: str,
) -> None:
    """Validate a cross-namespace reference using Gateway-style rules.

    Supported schema:
    - ``{"from": "Same"}`` (default)
    - ``{"from": "All"}``
    - ``{"from": "Selector", "selector": {...}}``
    """
    if source_namespace == target_namespace:
        return

    config = allowed_namespaces or {}
    mode = str(config.get("from") or "Same").strip() or "Same"

    if mode == "All":
        return
    if mode == "Same":
        raise kopf.PermanentError(
            f"{field_path} may not reference {target_kind} in namespace '{target_namespace}'. "
            "Cross-namespace references are restricted to the same namespace by default."
        )
    if mode == "Selector":
        selector = config.get("selector")
        if isinstance(selector, dict) and _match_namespace_selector(source_namespace, selector):
            return
        raise kopf.PermanentError(
            f"{field_path} may not reference {target_kind} in namespace '{target_namespace}' because "
            f"namespace '{source_namespace}' is not allowed by allowedNamespaces.selector."
        )

    raise kopf.PermanentError(
        f"{field_path}.allowedNamespaces.from has unsupported value '{mode}'. Use Same, All, or Selector."
    )


def _serialize_log_field(value: Any) -> str:
    """Serialize a log field value to a bounded JSON string."""
    try:
        serialized = json.dumps(value) if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        serialized = json.dumps(str(value))
    if len(serialized) > MAX_LOG_FIELD_LENGTH:
        return f"{serialized[: MAX_LOG_FIELD_LENGTH - 3]}..."
    return serialized


def format_log_fields(fields: dict[str, Any]) -> str:
    """Format a dict of log fields into a key=value string."""
    parts: list[str] = []
    for key in sorted(fields):
        value = fields[key]
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}={_serialize_log_field(value)}")
    return " ".join(parts)


def resource_log_fields(
    resource_kind: str | None = None,
    name: str | None = None,
    namespace: str | None = None,
    *,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build structured log fields for a Kubernetes resource."""
    fields: dict[str, Any] = {}
    if resource_kind:
        fields["resourceKind"] = resource_kind
    if name:
        fields["name"] = name
    if namespace:
        fields["namespace"] = namespace
    resolved_generation = generation
    if resolved_generation is None and meta is not None:
        resolved_generation = int((meta or {}).get("generation", 0) or 0)
    if resolved_generation:
        fields["generation"] = resolved_generation
    for key, value in extra.items():
        if value in (None, "", [], {}):
            continue
        fields[key] = value
    return fields


def log_operator_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    resource_kind: str | None = None,
    name: str | None = None,
    namespace: str | None = None,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    **extra: Any,
) -> None:
    """Log a structured operator event."""
    formatted_fields = format_log_fields(
        resource_log_fields(
            resource_kind,
            name,
            namespace,
            meta=meta,
            generation=generation,
            **extra,
        )
    )
    if formatted_fields:
        logger.log(level, "%s %s", message, formatted_fields)
        return
    logger.log(level, message)


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def classify_reconcile_error(action: str, exc: Exception, *, default_delay: int = 10) -> Exception:
    """Classify an exception into PermanentError or TemporaryError."""
    if isinstance(exc, (kopf.PermanentError, kopf.TemporaryError)):
        return exc
    if isinstance(exc, ValueError):
        return kopf.PermanentError(str(exc))
    if isinstance(exc, ApiException):
        status = int(getattr(exc, "status", 0) or 0)
        details = describe_api_exception(exc)
        message = f"{action} failed: {details}"
        if status in PERMANENT_API_ERROR_STATUSES:
            return kopf.PermanentError(message)
        delay = max(default_delay, 30) if status in HIGH_BACKOFF_API_ERROR_STATUSES else default_delay
        return kopf.TemporaryError(message, delay=delay)
    return kopf.TemporaryError(f"{action} failed: {exc}", delay=default_delay)


def raise_reconcile_error(
    logger: logging.Logger,
    action: str,
    exc: Exception,
    *,
    resource_kind: str,
    name: str,
    namespace: str | None = None,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    default_delay: int = 10,
    **extra: Any,
) -> None:
    """Log and raise a classified reconcile error."""
    resolved_error = classify_reconcile_error(action, exc, default_delay=default_delay)
    message = (
        "Reconcile operation failed permanently."
        if isinstance(resolved_error, kopf.PermanentError)
        else "Reconcile operation failed and will be retried."
    )
    log_details = resource_log_fields(
        resource_kind,
        name,
        namespace,
        meta=meta,
        generation=generation,
        action=action,
        error=str(resolved_error),
        sourceErrorType=type(exc).__name__,
        **extra,
    )
    if isinstance(exc, (kopf.PermanentError, kopf.TemporaryError)):
        logger.log(
            logging.ERROR if isinstance(resolved_error, kopf.PermanentError) else logging.WARNING,
            "%s %s",
            message,
            format_log_fields(log_details),
        )
    else:
        logger.exception("%s %s", message, format_log_fields(log_details))
    raise resolved_error from exc


# ---------------------------------------------------------------------------
# Reconcile execution wrapper
# ---------------------------------------------------------------------------


MAX_HANDLER_RETRIES: int = 50
"""Maximum number of retries before escalating TemporaryError to PermanentError."""


def execute_reconcile(
    operation: Callable[[], Any],
    *,
    logger: logging.Logger,
    action: str,
    resource_kind: str,
    name: str,
    namespace: str | None = None,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    default_delay: int = 10,
    retry: int | None = None,
    max_retries: int = MAX_HANDLER_RETRIES,
    start_message: str | None = None,
    success_message: str | None = None,
    **extra: Any,
) -> Any:
    """Execute a reconcile operation with structured logging, tracing, and error handling."""
    if start_message:
        log_operator_event(
            logger,
            logging.INFO,
            start_message,
            resource_kind=resource_kind,
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action=action,
            **extra,
        )
    with trace_reconcile(
        action,
        resource_kind=resource_kind,
        name=name,
        namespace=namespace or "",
        generation=generation or 0,
        **extra,
    ):
        try:
            result = operation()
        except Exception as exc:
            # Escalate TemporaryError to PermanentError after too many retries
            if retry is not None and retry >= max_retries:
                resolved = classify_reconcile_error(action, exc, default_delay=default_delay)
                if isinstance(resolved, kopf.TemporaryError):
                    logger.error(
                        "Max retries (%d) exceeded for %s %s/%s — escalating to permanent failure.",
                        max_retries,
                        resource_kind,
                        namespace or "",
                        name,
                    )
                    raise kopf.PermanentError(
                        f"{action} failed after {retry} retries: {resolved}"
                    ) from exc
            raise_reconcile_error(
                logger,
                action,
                exc,
                resource_kind=resource_kind,
                name=name,
                namespace=namespace,
                meta=meta,
                generation=generation,
                default_delay=default_delay,
                **extra,
            )
        if success_message:
            log_operator_event(
                logger,
                logging.INFO,
                success_message,
                resource_kind=resource_kind,
                name=name,
                namespace=namespace,
                meta=meta,
                generation=generation,
                action=action,
                **extra,
            )
        return result  # type: ignore[possibly-undefined]  # raise_reconcile_error always raises


# ---------------------------------------------------------------------------
# §2.10 — Standard Kubernetes status conditions
# ---------------------------------------------------------------------------

_CONDITION_TRUE = "True"
_CONDITION_FALSE = "False"


def build_condition(
    condition_type: str,
    status: str,
    reason: str,
    message: str,
    *,
    last_transition_time: str | None = None,
) -> dict[str, str]:
    """Build a Kubernetes-style status condition dict."""
    return {
        "type": condition_type,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": last_transition_time or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def set_condition(conditions: list[dict[str, str]], condition: dict[str, str]) -> list[dict[str, str]]:
    """Upsert a condition into a conditions list by type."""
    result = [c for c in conditions if c.get("type") != condition["type"]]
    result.append(condition)
    return sorted(result, key=lambda c: c.get("type", ""))


def conditions_for_phase(phase: str) -> list[dict[str, str]]:
    """Derive standard conditions from a resource phase string."""
    phase_lower = phase.lower() if phase else ""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    if phase_lower in {"completed", "succeeded"}:
        return [
            build_condition(
                "Degraded", _CONDITION_FALSE, "Completed", "Resource completed successfully", last_transition_time=now
            ),
            build_condition(
                "Progressing", _CONDITION_FALSE, "Completed", "Execution finished", last_transition_time=now
            ),
            build_condition(
                "Ready", _CONDITION_TRUE, "Completed", "Resource is fully reconciled", last_transition_time=now
            ),
        ]
    if phase_lower == "failed":
        return [
            build_condition("Degraded", _CONDITION_TRUE, "Failed", "Execution failed", last_transition_time=now),
            build_condition("Progressing", _CONDITION_FALSE, "Failed", "Execution stopped", last_transition_time=now),
            build_condition(
                "Ready", _CONDITION_FALSE, "Failed", "Resource is in a failed state", last_transition_time=now
            ),
        ]
    if phase_lower in {"running", "provisioning", "executing"}:
        return [
            build_condition(
                "Degraded", _CONDITION_FALSE, "InProgress", "No degradation detected", last_transition_time=now
            ),
            build_condition(
                "Progressing", _CONDITION_TRUE, "InProgress", f"Resource is {phase_lower}", last_transition_time=now
            ),
            build_condition(
                "Ready", _CONDITION_FALSE, "InProgress", "Resource is not yet ready", last_transition_time=now
            ),
        ]
    if phase_lower in {"queued", "pending", "scheduling"}:
        return [
            build_condition(
                "Degraded", _CONDITION_FALSE, "Pending", "No degradation detected", last_transition_time=now
            ),
            build_condition(
                "Progressing", _CONDITION_TRUE, "Pending", f"Resource is {phase_lower}", last_transition_time=now
            ),
            build_condition(
                "Ready", _CONDITION_FALSE, "Pending", "Resource is waiting to start", last_transition_time=now
            ),
        ]
    if phase_lower == "cancelled":
        return [
            build_condition(
                "Degraded", _CONDITION_FALSE, "Cancelled", "Resource was cancelled", last_transition_time=now
            ),
            build_condition(
                "Progressing", _CONDITION_FALSE, "Cancelled", "Execution cancelled", last_transition_time=now
            ),
            build_condition("Ready", _CONDITION_FALSE, "Cancelled", "Resource was cancelled", last_transition_time=now),
        ]
    # Default/unknown phase — treat as progressing
    return [
        build_condition("Degraded", _CONDITION_FALSE, "Unknown", "Phase not recognized", last_transition_time=now),
        build_condition(
            "Progressing", _CONDITION_TRUE, "Unknown", f"Resource phase: {phase}", last_transition_time=now
        ),
        build_condition("Ready", _CONDITION_FALSE, "Unknown", "Resource state is unknown", last_transition_time=now),
    ]


def inject_conditions(status: dict[str, Any], phase: str | None = None) -> dict[str, Any]:
    """Add .conditions[] to a status dict based on phase."""
    resolved_phase = phase or status.get("phase", "")
    if resolved_phase:
        status["conditions"] = conditions_for_phase(resolved_phase)
    return status
