"""Kubernetes service interaction layer.

§2.1c of the road-to-prod plan: K8s API functions extracted from the
operator monolith.
"""

from services.k8s import (
    _patch_statefulset_with_merge_patch,
    _preserve_statefulset_immutable_fields,
    _resize_statefulset_persistent_volume_claims,
    _sanitize_kube_resource,
    cancel_worker_job,
    crd_exists,
    describe_api_exception,
    enqueue_worker_job,
    ensure_network_policy,
    ensure_persistent_storage,
    ensure_runtime_access,
    ensure_runtime_namespace_secret,
    ensure_secret,
    ensure_service,
    ensure_statefulset,
    ensure_worker_artifact_storage,
    patch_custom_status,
    prune_orphaned_resources,
    read_job_state,
)

__all__ = [
    "_patch_statefulset_with_merge_patch",
    "_preserve_statefulset_immutable_fields",
    "_resize_statefulset_persistent_volume_claims",
    "_sanitize_kube_resource",
    "cancel_worker_job",
    "crd_exists",
    "describe_api_exception",
    "enqueue_worker_job",
    "ensure_network_policy",
    "ensure_persistent_storage",
    "ensure_runtime_access",
    "ensure_runtime_namespace_secret",
    "ensure_secret",
    "ensure_service",
    "ensure_statefulset",
    "ensure_worker_artifact_storage",
    "patch_custom_status",
    "prune_orphaned_resources",
    "read_job_state",
]
