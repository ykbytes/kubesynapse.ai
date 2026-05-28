"""Audit logging middleware for API gateway.

Emits structured audit events for security-sensitive operations
like agent invokes, auth events, and admin actions.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger("api-gateway.audit")


def emit_audit_event(
    action: str,
    *,
    user: str | None = None,
    agent: str | None = None,
    namespace: str | None = None,
    request_id: str | None = None,
    status: str = "success",
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a structured audit event.

    Args:
        action: The action being audited (e.g., "invoke", "login", "create_agent")
        user: The user performing the action
        agent: The target agent (if applicable)
        namespace: The target namespace (if applicable)
        request_id: The request ID for traceability
        status: "success", "failed", "denied", etc.
        detail: Human-readable detail about the event
        metadata: Additional structured metadata
    """
    event = {
        "event": "audit",
        "action": action,
        "timestamp": time.time(),
        "user": user,
        "agent": agent,
        "namespace": namespace,
        "request_id": request_id,
        "status": status,
    }
    if detail:
        event["detail"] = detail
    if metadata:
        event["metadata"] = metadata

    logger.info("audit: %s", json.dumps(event, default=str))


def emit_invoke_audit(
    *,
    user: str | None,
    agent: str,
    namespace: str,
    request_id: str | None,
    status: str,
    latency_ms: float,
    model: str | None = None,
    detail: str | None = None,
) -> None:
    """Emit an audit event specifically for agent invokes."""
    metadata: dict[str, Any] = {"latency_ms": round(latency_ms, 1)}
    if model:
        metadata["model"] = model
    emit_audit_event(
        action="invoke",
        user=user,
        agent=agent,
        namespace=namespace,
        request_id=request_id,
        status=status,
        detail=detail,
        metadata=metadata,
    )


def emit_auth_audit(
    *,
    user: str | None,
    action: str,
    status: str,
    detail: str | None = None,
    request_id: str | None = None,
) -> None:
    """Emit an audit event for authentication operations."""
    emit_audit_event(
        action=f"auth.{action}",
        user=user,
        status=status,
        detail=detail,
        request_id=request_id,
    )


def emit_admin_audit(
    *,
    user: str | None,
    action: str,
    resource: str,
    status: str,
    detail: str | None = None,
    request_id: str | None = None,
) -> None:
    """Emit an audit event for admin operations."""
    emit_audit_event(
        action=f"admin.{action}",
        user=user,
        status=status,
        detail=detail,
        request_id=request_id,
        metadata={"resource": resource},
    )
