"""Shared helper functions and constants for K8s manifest builders.

§2.1b of the road-to-prod plan: extract manifest construction helpers
from operator/main.py into the builders package.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from config import (
    API_GATEWAY_INTERNAL_URL,
    API_PORT,
    ARTIFACT_MOUNT_PATH,
    OTEL_ENDPOINT,
    OPERATOR_NAMESPACE,
    WORKER_ARTIFACT_SIZE,
    WORKER_ARTIFACT_STORAGE_CLASS,
)
from utils import now_iso

logger = logging.getLogger("operator.builders")

# ---------------------------------------------------------------------------
# Constants shared across builders and services
# ---------------------------------------------------------------------------

POD_TEMPLATE_REVISION_ANNOTATION: str = "kubesynth.ai/pod-template-revision"

# Orphan pruning labels (§kagent-pattern-6)
# Added to every agent-scoped manifest so prune_orphaned_resources() can
# list-by-label and compare against the desired resource set.
OWNER_LABEL_MANAGED_BY: str = "kubesynth.ai/managed-by"
OWNER_LABEL_AGENT_NAME: str = "kubesynth.ai/agent-name"
OWNER_LABEL_MANAGED_BY_VALUE: str = "operator"


def agent_owner_labels(agent_name: str) -> dict[str, str]:
    """Return the standard owner labels for orphan pruning."""
    return {
        OWNER_LABEL_MANAGED_BY: OWNER_LABEL_MANAGED_BY_VALUE,
        OWNER_LABEL_AGENT_NAME: agent_name,
    }


KUBERNETES_RESOURCE_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
STORAGE_QUANTITY_MULTIPLIERS: dict[str, Decimal] = {
    "": Decimal(1),
    "n": Decimal("1e-9"),
    "m": Decimal("1e-3"),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(1000**2),
    "G": Decimal(1000**3),
    "T": Decimal(1000**4),
    "P": Decimal(1000**5),
    "E": Decimal(1000**6),
    "Ki": Decimal(1024),
    "Mi": Decimal(1024**2),
    "Gi": Decimal(1024**3),
    "Ti": Decimal(1024**4),
    "Pi": Decimal(1024**5),
    "Ei": Decimal(1024**6),
}

# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


def sandbox_name(agent_name: str) -> str:
    """Derive the StatefulSet/Service name for an agent."""
    return f"{agent_name}-sandbox"


def resolved_api_gateway_internal_url() -> str:
    """Return the API gateway URL, falling back to in-cluster DNS."""
    if API_GATEWAY_INTERNAL_URL:
        return API_GATEWAY_INTERNAL_URL.rstrip("/")
    return f"http://kubesynth-api-gateway.{OPERATOR_NAMESPACE}.svc.cluster.local:8080"


def slugify_name(value: str, max_length: int = 63) -> str:
    """Produce a K8s-safe DNS name from an arbitrary string."""
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "resource"
    trimmed = slug[:max_length].rstrip("-")
    return trimmed or "resource"


def hashed_resource_name(prefix: str, namespace: str, name: str, suffix: str = "") -> str:
    """Build a deterministic K8s name with a truncated SHA-256 hash suffix."""
    digest = hashlib.sha256(f"{prefix}:{namespace}:{name}:{suffix}".encode("utf-8")).hexdigest()[:10]
    base = slugify_name(f"{prefix}-{namespace}-{name}", max_length=max(1, 63 - len(digest) - 1))
    return f"{base}-{digest}"


# ---------------------------------------------------------------------------
# Path & artifact helpers
# ---------------------------------------------------------------------------


def worker_artifact_pvc_name(kind: str, namespace: str, name: str) -> str:
    """Derive the PVC name for worker Job artifacts."""
    return hashed_resource_name(f"{kind}-artifacts", namespace, name)


def artifact_file_path(kind: str, namespace: str, name: str, generation: int) -> str:
    """Derive the artifact JSON file path inside the PVC."""
    safe_namespace = slugify_name(namespace, max_length=40)
    safe_name = slugify_name(name, max_length=40)
    return f"{ARTIFACT_MOUNT_PATH}/{kind}s/{safe_namespace}/{safe_name}/generation-{generation}.json"


def worker_passthrough_env() -> list[dict[str, str]]:
    """Build env vars that are passed through from operator env to worker containers."""
    items: list[dict[str, str]] = []
    for name in (
        "STATE_DB_ENABLED",
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_DRIVER",
        "DATABASE_SQLITE_PATH",
    ):
        value = os.getenv(name, "")
        if value:
            items.append({"name": name, "value": value})
    return items


def build_artifact_ref(
    pvc_name: str,
    path: str,
    generation: int,
    *,
    journal_path: str | None = None,
) -> dict[str, Any]:
    """Build an artifact reference dict for CRD status."""
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        "updatedAt": now_iso(),
        **({"journalPath": journal_path} if journal_path else {}),
    }


def build_journal_ref(pvc_name: str, path: str, generation: int) -> dict[str, Any]:
    """Build a journal reference dict for CRD status."""
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        "updatedAt": now_iso(),
    }


# ---------------------------------------------------------------------------
# PVC helpers
# ---------------------------------------------------------------------------


def build_pvc_spec(storage_size: str, storage_class_name: str | None = None) -> dict[str, Any]:
    """Build a PVC spec dict."""
    pvc_spec: dict[str, Any] = {
        "accessModes": ["ReadWriteOnce"],
        "resources": {"requests": {"storage": storage_size}},
    }
    if storage_class_name:
        pvc_spec["storageClassName"] = storage_class_name
    return pvc_spec


def _parse_storage_quantity(value: str) -> Decimal:
    """Parse a K8s storage quantity string into bytes as a Decimal."""
    normalized = str(value or "").strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTPE]i|[numkKMGTPE])?", normalized)
    if not match:
        raise ValueError(f"Unsupported storage quantity: {value!r}")

    number_text, suffix = match.groups()
    try:
        number = Decimal(number_text)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported storage quantity: {value!r}") from exc
    return number * STORAGE_QUANTITY_MULTIPLIERS[suffix or ""]


# ---------------------------------------------------------------------------
# Network policy helpers
# ---------------------------------------------------------------------------


def platform_namespace_selector() -> dict[str, dict[str, str]]:
    """Return a namespace selector matching the operator namespace."""
    return {"matchLabels": {"kubernetes.io/metadata.name": OPERATOR_NAMESPACE}}


def agent_baseline_ingress_peers() -> list[dict[str, Any]]:
    """Return default ingress peers for agent pods."""
    return [
        {
            "namespaceSelector": platform_namespace_selector(),
            "podSelector": {"matchLabels": {"app": "api-gateway"}},
        },
        {
            "namespaceSelector": platform_namespace_selector(),
            "podSelector": {"matchLabels": {"app": "operator"}},
        },
        {
            "namespaceSelector": platform_namespace_selector(),
            "podSelector": {"matchLabels": {"app": "operator-worker"}},
        },
    ]


def agent_baseline_egress_rules() -> list[dict[str, Any]]:
    """Return default egress rules for agent pods."""
    rules: list[dict[str, Any]] = [
        {
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        },
        {
            "to": [
                {
                    "namespaceSelector": platform_namespace_selector(),
                    "podSelector": {"matchLabels": {"app": "api-gateway"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": API_PORT}],
        },
        {
            "to": [
                {
                    "namespaceSelector": platform_namespace_selector(),
                    "podSelector": {"matchLabels": {"app": "litellm"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": 4000}],
        },
        {
            "to": [
                {
                    "namespaceSelector": platform_namespace_selector(),
                    "podSelector": {"matchLabels": {"app": "qdrant"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": 6333}],
        },
        {
            "ports": [{"protocol": "TCP", "port": 443}],
        },
    ]
    if OTEL_ENDPOINT:
        rules.append(
            {
                "to": [
                    {
                        "namespaceSelector": platform_namespace_selector(),
                        "podSelector": {"matchLabels": {"app": "otel-collector"}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 4317}],
            }
        )
    return rules
