"""
Human-in-the-Loop (HITL) module for AI Agent Sandbox.
Provides the ability for agents to pause execution and wait for human approval
via Kubernetes AgentApproval CRD before executing high-risk actions.
"""

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime
from threading import Lock
from typing import Any, TypedDict

import httpx

logger = logging.getLogger("hitl")

client: Any
config: Any
try:
    from kubernetes import client as _k8s_client  # type: ignore[import-untyped]
    from kubernetes import config as _k8s_config

    client = _k8s_client
    config = _k8s_config
except Exception:
    client = None
    config = None


APPROVAL_GROUP = "kubesynth.ai"
APPROVAL_VERSION = "v1alpha1"
APPROVAL_PLURAL = "agentapprovals"
HITL_MODE = os.getenv("HITL_MODE", "enforce").strip().lower()
HITL_NOTIFICATION_WEBHOOK_URL = os.getenv("HITL_NOTIFICATION_WEBHOOK_URL", "").strip()
HITL_NOTIFICATION_TIMEOUT_SECONDS = max(float(os.getenv("HITL_NOTIFICATION_TIMEOUT_SECONDS", "5")), 1.0)
HITL_MAX_TOOL_ARGS_BYTES = max(int(os.getenv("HITL_MAX_TOOL_ARGS_BYTES", "8192")), 512)

_ALLOWED_HITL_MODES = {"enforce", "dry-run", "disabled"}
_APPROVAL_API: Any | None = None
_APPROVAL_API_LOCK = Lock()


class ApprovalResult(TypedDict, total=False):
    approval_name: str
    decision: str
    namespace: str
    reason: str
    request_id: str


def _get_hitl_mode() -> str:
    if HITL_MODE in _ALLOWED_HITL_MODES:
        return HITL_MODE
    logger.warning("Unsupported HITL_MODE '%s'; defaulting to 'enforce'.", HITL_MODE)
    return "enforce"


def _slugify_k8s_name(value: str, max_length: int = 63) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "approval"
    trimmed = slug[:max_length].rstrip("-")
    return trimmed or "approval"


def _build_approval_name(agent_name: str, request_id: str, action: str, tool_name: str) -> str:
    digest = hashlib.sha256(f"{request_id}:{action}:{tool_name}".encode()).hexdigest()[:12]
    base_max_length = max(1, 63 - len(digest) - 1)
    base = _slugify_k8s_name(agent_name, max_length=base_max_length)
    return f"{base}-{digest}"


def _serialize_tool_args(tool_args: dict[str, Any] | None) -> str:
    payload = json.dumps(tool_args or {}, default=str, sort_keys=True)
    if len(payload.encode("utf-8")) <= HITL_MAX_TOOL_ARGS_BYTES:
        return payload

    logger.warning("toolArgs payload exceeded %s bytes; truncating approval payload.", HITL_MAX_TOOL_ARGS_BYTES)
    preview = payload[: max(128, HITL_MAX_TOOL_ARGS_BYTES // 2)]
    return json.dumps({"truncated": True, "preview": preview}, sort_keys=True)


def _send_approval_notification(payload: dict[str, Any]) -> None:
    if not HITL_NOTIFICATION_WEBHOOK_URL:
        return

    try:
        httpx.post(
            HITL_NOTIFICATION_WEBHOOK_URL,
            json=payload,
            timeout=HITL_NOTIFICATION_TIMEOUT_SECONDS,
        ).raise_for_status()
    except Exception as exc:
        logger.warning("Failed to send HITL approval notification: %s", exc)


def _get_custom_objects_api() -> Any | None:
    global _APPROVAL_API

    if _APPROVAL_API is not None:
        return _APPROVAL_API

    if client is None or config is None:
        return None

    with _APPROVAL_API_LOCK:
        if _APPROVAL_API is not None:
            return _APPROVAL_API

        try:
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config for HITL approvals.")
            except Exception:
                config.load_kube_config()
                logger.info("Loaded local kubeconfig for HITL approvals.")
            _APPROVAL_API = client.CustomObjectsApi()
        except Exception as exc:
            logger.warning("Kubernetes package not available or configured for HITL approvals: %s", exc)
            return None

    return _APPROVAL_API


def _read_approval_status(api: Any, approval_name: str, namespace: str) -> dict[str, Any] | None:
    try:
        return api.get_namespaced_custom_object(
            group=APPROVAL_GROUP,
            version=APPROVAL_VERSION,
            namespace=namespace,
            plural=APPROVAL_PLURAL,
            name=approval_name,
        )
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise


def request_approval(
    agent_name: str,
    action: str,
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
    request_id: str = "",
    namespace: str | None = None,
) -> ApprovalResult:
    if not request_id.strip():
        raise ValueError("request_id must not be empty")

    mode = _get_hitl_mode()
    resolved_namespace = namespace if namespace is not None else os.getenv("AGENT_NAMESPACE", "default")
    namespace = resolved_namespace.strip() or "default"
    approval_name = _build_approval_name(agent_name, request_id, action, tool_name)

    if mode == "disabled":
        logger.info("HITL disabled; allowing action '%s' for agent '%s'.", action, agent_name)
        return {
            "approval_name": approval_name,
            "decision": "approved",
            "namespace": namespace,
            "request_id": request_id,
        }

    approval_body = {
        "apiVersion": f"{APPROVAL_GROUP}/{APPROVAL_VERSION}",
        "kind": "AgentApproval",
        "metadata": {
            "name": approval_name,
            "namespace": namespace,
        },
        "spec": {
            "agentName": agent_name,
            "action": action,
            "toolName": tool_name,
            "toolArgs": _serialize_tool_args(tool_args),
            "requestId": request_id,
            "requestedAt": datetime.now(UTC).isoformat(),
        },
        "status": {
            "decision": "pending",
        },
    }

    api = _get_custom_objects_api()
    if api is None:
        if mode == "dry-run":
            logger.warning(
                "Approval requested for '%s' by '%s' with no Kubernetes API; auto-approving because HITL_MODE=dry-run.",
                action,
                agent_name,
            )
            return {
                "approval_name": approval_name,
                "decision": "approved",
                "namespace": namespace,
                "request_id": request_id,
            }

        logger.error(
            "Approval requested for '%s' by '%s' but Kubernetes API is unavailable and HITL_MODE=%s; denying.",
            action,
            agent_name,
            mode,
        )
        return {
            "approval_name": approval_name,
            "decision": "denied",
            "namespace": namespace,
            "request_id": request_id,
            "reason": "Kubernetes API unavailable for approval handling",
        }

    existing = _read_approval_status(api, approval_name, namespace)
    if existing is not None:
        status = existing.get("status", {})
        return {
            "approval_name": approval_name,
            "decision": status.get("decision", "pending"),
            "namespace": namespace,
            "request_id": request_id,
            "reason": str(status.get("reason", "")),
        }

    try:
        api.create_namespaced_custom_object(
            group=APPROVAL_GROUP,
            version=APPROVAL_VERSION,
            namespace=namespace,
            plural=APPROVAL_PLURAL,
            body=approval_body,
        )
        logger.info("Approval request '%s' created asynchronously.", approval_name)
        _send_approval_notification(
            {
                "approval_name": approval_name,
                "namespace": namespace,
                "agent_name": agent_name,
                "action": action,
                "tool_name": tool_name,
                "request_id": request_id,
            }
        )
    except Exception as exc:
        logger.error("Failed to create approval request '%s': %s", approval_name, exc)
        return {
            "approval_name": approval_name,
            "decision": "denied",
            "namespace": namespace,
            "request_id": request_id,
            "reason": str(exc),
        }

    return {
        "approval_name": approval_name,
        "decision": "pending",
        "namespace": namespace,
        "request_id": request_id,
    }


def hitl_gate(
    action_description: str,
    tool_name: str = "",
    tool_args: dict[str, Any] | None = None,
    request_id: str = "",
) -> ApprovalResult:
    agent_name = os.getenv("AGENT_NAME", "unknown-agent")

    result = request_approval(
        agent_name=agent_name,
        action=action_description,
        tool_name=tool_name,
        tool_args=tool_args,
        request_id=request_id,
    )

    if result.get("decision") == "denied":
        reason = result.get("reason") or f"Human approval denied action: {action_description}"
        raise PermissionError(reason)

    return result
