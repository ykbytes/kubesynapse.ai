"""Kubernetes API interaction layer — ensure, enqueue, and utility functions.

§2.1c of the road-to-prod plan: extract all K8s API calls
(ensure_*, enqueue_*, read_job_state, cancel_worker_job, patch_custom_status)
and their private helpers from operator/main.py into operator/services/.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import random
import time
from collections.abc import Callable
from datetime import UTC as _UTC
from datetime import datetime as _datetime
from functools import wraps
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from builders import (
    OWNER_LABEL_AGENT_NAME,
    OWNER_LABEL_MANAGED_BY,
    OWNER_LABEL_MANAGED_BY_VALUE,
    _extract_statefulset_storage_request,
    _parse_storage_quantity,
    create_worker_artifact_pvc_manifest,
    create_worker_job_manifest,
)
from circuit_breaker import CircuitBreakerOpen, get_k8s_circuit_breaker
from config import (
    CLUSTER_SECRET_STORE,
    DEFAULT_API_GATEWAY_SHARED_TOKEN,
    DEFAULT_LITELLM_MASTER_KEY,
    HELM_RELEASE_NAME,
    IMAGE_PULL_SECRETS,
    OPENCODE_IMMUTABLE_CONFIG,
    OPERATOR_NAMESPACE,
    ORPHAN_PRUNING_ENABLED,
    PI_IMMUTABLE_CONFIG,
    RUNTIME_CLUSTER_ROLE,
    RUNTIME_SERVICE_ACCOUNT,
    SECRET_NAME,
    SECRET_PROVISIONING_MODE,
)
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

ApiTypeError = getattr(kubernetes.client, "ApiTypeError", TypeError)

logger = logging.getLogger("operator.services")


# ---------------------------------------------------------------------------
# §7.2 — Exponential backoff with circuit breaker for K8s API calls
# ---------------------------------------------------------------------------


def _exponential_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_statuses: frozenset[int] = frozenset({409, 429, 500, 502, 503, 504}),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that retries K8s API calls with exponential backoff + jitter."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cb = get_k8s_circuit_breaker()
            for attempt in range(max_retries):
                try:
                    cb.call()
                    result = func(*args, **kwargs)
                    cb.record_success()
                    return result
                except ApiException as exc:
                    cb.record_failure()
                    status = int(getattr(exc, "status", 0) or 0)
                    if attempt < max_retries - 1 and status in retryable_statuses:
                        backoff = min(base_delay * (2**attempt) + random.uniform(0, 1), max_delay)  # noqa: S311
                        logger.warning(
                            "Retryable K8s API error in %s (attempt %d/%d, status=%d), "
                            "retrying in %.1fs: %s",
                            func.__name__,
                            attempt + 1,
                            max_retries,
                            status,
                            backoff,
                            describe_api_exception(exc),
                        )
                        time.sleep(backoff)
                        continue
                    raise
                except CircuitBreakerOpen:
                    raise
                except Exception:
                    cb.record_failure()
                    raise
            return None  # pragma: no cover

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Shared helpers (used internally by ensure_* and other service functions)
# ---------------------------------------------------------------------------


def crd_exists(group: str, version: str, plural: str) -> bool:
    """Return True if the CRD exists in the cluster.

    Uses the CRD name format ``<plural>.<group>``. Missing CRDs return False;
    other API failures are logged and also treated as False so optional
    controllers can be skipped safely at startup.
    """
    crd_name = f"{plural}.{group}"
    api_cls = getattr(kubernetes.client, "ApiextensionsV1Api", None)
    if api_cls is None:
        logger.warning(
            "Skipping CRD existence check for '%s' because ApiextensionsV1Api is unavailable.",
            crd_name,
        )
        return False

    api = api_cls()
    try:
        crd = _sanitize_kube_resource(api.read_custom_resource_definition(name=crd_name))
    except ApiException as exc:
        if exc.status == 404:
            return False
        logger.warning(
            "Failed checking CRD '%s' (%s/%s): %s",
            crd_name,
            group,
            version,
            describe_api_exception(exc),
        )
        return False

    versions = ((crd.get("spec") or {}).get("versions") or []) if isinstance(crd, dict) else []
    if not versions:
        return True
    return any(str(item.get("name") or "") == version for item in versions if isinstance(item, dict))


def describe_api_exception(exc: ApiException) -> str:
    """Format an ApiException for human-readable logging."""
    MAX_LOG_FIELD_LENGTH = 400
    details: list[str] = []
    status = getattr(exc, "status", None)
    if status is not None:
        details.append(f"status={status}")
    reason = str(getattr(exc, "reason", "") or "").strip()
    if reason:
        details.append(f"reason={reason}")
    body = str(getattr(exc, "body", "") or "").strip()
    if body:
        if len(body) > MAX_LOG_FIELD_LENGTH:
            body = f"{body[: MAX_LOG_FIELD_LENGTH - 3]}..."
        details.append(f"body={body}")
    message = str(exc).strip()
    if message and message not in {reason, body}:
        details.append(f"message={message}")
    return ", ".join(details) or exc.__class__.__name__


def _sanitize_kube_resource(resource: Any) -> Any:
    """Normalize a K8s SDK object to a plain dict."""
    if isinstance(resource, (dict, list, str, int, float, bool)) or resource is None:
        return copy.deepcopy(resource)

    api_client_cls = getattr(kubernetes.client, "ApiClient", None)
    if api_client_cls is not None:
        try:
            return api_client_cls().sanitize_for_serialization(resource)
        except Exception as exc:
            logger.debug("sanitize_for_serialization failed: %s", exc, exc_info=True)

    if hasattr(resource, "to_dict"):
        return resource.to_dict()
    return resource


# ---------------------------------------------------------------------------
# StatefulSet reconciliation helpers
# ---------------------------------------------------------------------------


def _preserve_statefulset_immutable_fields(
    manifest: dict[str, Any],
    current_statefulset: dict[str, Any],
) -> dict[str, Any]:
    """Copy immutable fields from current StatefulSet into the desired manifest."""
    patched_manifest = copy.deepcopy(manifest)
    patched_spec = patched_manifest.setdefault("spec", {})
    current_spec = current_statefulset.get("spec") or {}

    for field_name in ("volumeClaimTemplates", "selector", "serviceName"):
        current_value = current_spec.get(field_name)
        if current_value is not None:
            patched_spec[field_name] = current_value

    return patched_manifest


def _patch_statefulset_with_merge_patch(
    apps_api: Any,
    namespace: str,
    statefulset_name: str,
    manifest: dict[str, Any],
) -> Any:
    """Apply a merge-patch to a StatefulSet, falling back to raw API call."""
    try:
        return apps_api.patch_namespaced_stateful_set(
            name=statefulset_name,
            namespace=namespace,
            body=manifest,
            _content_type="application/merge-patch+json",
        )
    except ApiTypeError:
        api_client = apps_api.api_client
        return api_client.call_api(
            "/apis/apps/v1/namespaces/{namespace}/statefulsets/{name}",
            "PATCH",
            {"name": statefulset_name, "namespace": namespace},
            [],
            {
                "Accept": api_client.select_header_accept(
                    [
                        "application/json",
                        "application/yaml",
                        "application/vnd.kubernetes.protobuf",
                    ]
                ),
                "Content-Type": "application/merge-patch+json",
            },
            body=manifest,
            post_params=[],
            files={},
            response_type="V1StatefulSet",
            auth_settings=["BearerToken"],
            _return_http_data_only=True,
            collection_formats={},
        )


def _resize_statefulset_persistent_volume_claims(
    core_api: Any,
    namespace: str,
    statefulset_name: str,
    current_statefulset: dict[str, Any],
    desired_storage: str | None,
) -> None:
    """Expand PVCs attached to a StatefulSet if the desired size is larger."""
    if not desired_storage:
        return

    desired_quantity = _parse_storage_quantity(desired_storage)
    current_spec = current_statefulset.get("spec") or {}
    replicas = max(int(current_spec.get("replicas") or 1), 1)
    claim_templates = current_spec.get("volumeClaimTemplates") or []

    for template in claim_templates:
        claim_name = str((template.get("metadata") or {}).get("name") or "").strip()
        if claim_name != "state-volume":
            continue

        for ordinal in range(replicas):
            pvc_name = f"{claim_name}-{statefulset_name}-{ordinal}"
            try:
                current_pvc = _sanitize_kube_resource(
                    core_api.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
                )
            except ApiException as exc:
                if exc.status == 404:
                    continue
                raise

            current_requests = ((current_pvc.get("spec") or {}).get("resources") or {}).get("requests") or {}
            current_storage = current_requests.get("storage")
            if not current_storage:
                logger.warning(
                    "Skipping PVC resize because '%s' in namespace '%s' has no storage request.",
                    pvc_name,
                    namespace,
                )
                continue

            try:
                current_quantity = _parse_storage_quantity(str(current_storage))
            except ValueError:
                logger.warning(
                    "Skipping PVC resize because '%s' in namespace '%s' has an unsupported storage request %r.",
                    pvc_name,
                    namespace,
                    current_storage,
                )
                continue

            if desired_quantity < current_quantity:
                logger.warning(
                    "Skipping PVC shrink request for '%s' in namespace '%s': current=%s desired=%s.",
                    pvc_name,
                    namespace,
                    current_storage,
                    desired_storage,
                )
                continue
            if desired_quantity == current_quantity:
                continue

            try:
                core_api.patch_namespaced_persistent_volume_claim(
                    name=pvc_name,
                    namespace=namespace,
                    body={"spec": {"resources": {"requests": {"storage": desired_storage}}}},
                )
            except ApiException as exc:
                if exc.status in (403, 422):
                    raise kopf.PermanentError(

                            f"PVC resize request for '{pvc_name}' in namespace '{namespace}' could not be applied: "
                            f"{describe_api_exception(exc)}"

                    ) from exc
                raise


# ---------------------------------------------------------------------------
# ensure_* — idempotent K8s resource creation / update
# ---------------------------------------------------------------------------


@_exponential_backoff()
def ensure_persistent_storage(namespace: str, manifest: dict[str, Any]) -> None:
    """Create a PVC, silently ignoring AlreadyExists."""
    core_api = kubernetes.client.CoreV1Api()
    try:
        core_api.create_namespaced_persistent_volume_claim(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status != 409:
            raise


@_exponential_backoff()
def ensure_service(namespace: str, manifest: dict[str, Any]) -> None:
    """Create or patch a Service."""
    core_api = kubernetes.client.CoreV1Api()
    service_name = manifest["metadata"]["name"]
    try:
        core_api.create_namespaced_service(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_service(name=service_name, namespace=namespace, body=manifest)
            return
        raise


@_exponential_backoff()
def ensure_statefulset(namespace: str, manifest: dict[str, Any]) -> None:
    """Create or reconcile a StatefulSet with immutable-field preservation."""
    apps_api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()
    statefulset_name = manifest["metadata"]["name"]
    try:
        apps_api.create_namespaced_stateful_set(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            current_statefulset = _sanitize_kube_resource(
                apps_api.read_namespaced_stateful_set(name=statefulset_name, namespace=namespace)
            )
            desired_storage = _extract_statefulset_storage_request(manifest)
            patched_manifest = _preserve_statefulset_immutable_fields(manifest, current_statefulset)
            _patch_statefulset_with_merge_patch(apps_api, namespace, statefulset_name, patched_manifest)
            reconciled_statefulset = _sanitize_kube_resource(
                apps_api.read_namespaced_stateful_set(name=statefulset_name, namespace=namespace)
            )
            # Compare only the pod-template-revision annotation which the
            # operator controls.  K8s may mutate other template fields (env
            # ordering, defaulted values, injected sidecars) making a full
            # deep comparison unreliable.
            from builders.helpers import POD_TEMPLATE_REVISION_ANNOTATION as _REV_ANN

            desired_rev = (
                ((patched_manifest.get("spec") or {}).get("template") or {})
                .get("metadata", {})
                .get("annotations", {})
                .get(_REV_ANN)
            )
            actual_rev = (
                ((reconciled_statefulset.get("spec") or {}).get("template") or {})
                .get("metadata", {})
                .get("annotations", {})
                .get(_REV_ANN)
            )
            if desired_rev and actual_rev != desired_rev:
                logging.getLogger("operator.services.k8s").warning(
                    "StatefulSet '%s/%s' pod-template-revision mismatch after patching: "
                    "desired=%s actual=%s",
                    namespace,
                    statefulset_name,
                    desired_rev,
                    actual_rev,
                )
                raise kopf.TemporaryError(
                    (
                        f"StatefulSet '{statefulset_name}' in namespace '{namespace}' did not converge to the "
                        "desired pod template after patching."
                    ),
                    delay=10,
                ) from exc
            _resize_statefulset_persistent_volume_claims(
                core_api,
                namespace,
                statefulset_name,
                reconciled_statefulset,
                desired_storage,
            )
            return
        raise


@_exponential_backoff()
def ensure_secret(namespace: str, manifest: dict[str, Any]) -> None:
    """Create or patch a Secret."""
    core_api = kubernetes.client.CoreV1Api()
    secret_name = str(manifest["metadata"]["name"])
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_secret(name=secret_name, namespace=namespace, body=manifest)
            return
        raise


@_exponential_backoff()
def ensure_config_map(namespace: str, manifest: dict[str, Any]) -> None:
    """Create or reconcile a ConfigMap, recreating immutable entries when data changes."""
    core_api = kubernetes.client.CoreV1Api()
    config_map_name = str(manifest["metadata"]["name"])
    try:
        core_api.create_namespaced_config_map(namespace=namespace, body=manifest)
        return
    except ApiException as exc:
        if exc.status != 409:
            raise

    try:
        existing = _sanitize_kube_resource(core_api.read_namespaced_config_map(name=config_map_name, namespace=namespace))
    except ApiException as exc:
        if exc.status == 404:
            core_api.create_namespaced_config_map(namespace=namespace, body=manifest)
            return
        raise

    desired_data = copy.deepcopy(manifest.get("data") or {})
    desired_binary_data = copy.deepcopy(manifest.get("binaryData") or {})
    desired_immutable = bool(manifest.get("immutable", False))

    existing_data = copy.deepcopy(existing.get("data") or {}) if isinstance(existing, dict) else {}
    existing_binary_data = copy.deepcopy(existing.get("binaryData") or {}) if isinstance(existing, dict) else {}
    existing_immutable = bool((existing or {}).get("immutable", False)) if isinstance(existing, dict) else False

    if (
        existing_data != desired_data
        or existing_binary_data != desired_binary_data
        or existing_immutable != desired_immutable
    ):
        core_api.delete_namespaced_config_map(name=config_map_name, namespace=namespace)
        core_api.create_namespaced_config_map(namespace=namespace, body=manifest)
        return

    metadata = copy.deepcopy(manifest.get("metadata") or {})
    metadata.pop("namespace", None)
    if metadata:
        core_api.patch_namespaced_config_map(
            name=config_map_name,
            namespace=namespace,
            body={"metadata": metadata},
        )


def _runtime_immutable_config_map_names() -> list[str]:
    release_prefix = HELM_RELEASE_NAME or "kubesynapse"
    names: list[str] = []
    if OPENCODE_IMMUTABLE_CONFIG:
        names.append(f"{release_prefix}-opencode-safe-config")
    if PI_IMMUTABLE_CONFIG:
        names.append(f"{release_prefix}-pi-safe-config")
    return names


def _compute_config_map_hash(data: dict[str, str] | None, binary_data: dict[str, str] | None) -> str:
    """Compute a SHA-256 hash of ConfigMap data for drift detection."""
    content = json.dumps({"data": data or {}, "binaryData": binary_data or {}}, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _ensure_runtime_namespace_immutable_config_maps(namespace: str, logger: logging.Logger) -> None:
    """Mirror immutable runtime ConfigMaps into agent namespaces with drift detection."""
    if namespace == OPERATOR_NAMESPACE:
        return

    config_map_names = _runtime_immutable_config_map_names()
    if not config_map_names:
        return

    core_api = kubernetes.client.CoreV1Api()
    for config_map_name in config_map_names:
        try:
            source_config_map = _sanitize_kube_resource(
                core_api.read_namespaced_config_map(name=config_map_name, namespace=OPERATOR_NAMESPACE)
            )
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.TemporaryError(
                    (
                        f"Immutable runtime ConfigMap '{config_map_name}' is missing from operator namespace "
                        f"'{OPERATOR_NAMESPACE}'."
                    ),
                    delay=30,
                ) from exc
            raise kopf.TemporaryError(
                (
                    f"Failed to read immutable runtime ConfigMap '{config_map_name}' from namespace "
                    f"'{OPERATOR_NAMESPACE}': {describe_api_exception(exc)}"
                ),
                delay=30,
            ) from exc

        if not isinstance(source_config_map, dict):
            raise kopf.TemporaryError(
                (
                    f"Immutable runtime ConfigMap '{config_map_name}' in namespace '{OPERATOR_NAMESPACE}' "
                    "did not serialize to a dictionary."
                ),
                delay=30,
            )

        source_data = source_config_map.get("data") or {}
        source_binary_data = source_config_map.get("binaryData") or {}
        source_hash = _compute_config_map_hash(source_data, source_binary_data)

        # Check if target ConfigMap exists and compare hashes
        target_hash = None
        try:
            target_config_map = _sanitize_kube_resource(
                core_api.read_namespaced_config_map(name=config_map_name, namespace=namespace)
            )
            if isinstance(target_config_map, dict):
                target_annotations = (target_config_map.get("metadata") or {}).get("annotations") or {}
                target_hash = target_annotations.get("kubesynapse.ai/config-hash")
                target_data = target_config_map.get("data") or {}
                target_binary_data = target_config_map.get("binaryData") or {}
                computed_target_hash = _compute_config_map_hash(target_data, target_binary_data)
                if target_hash == computed_target_hash and target_hash == source_hash:
                    logger.debug("ConfigMap '%s' in namespace '%s' is in sync (hash=%s)", config_map_name, namespace, source_hash)
                    continue
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("Failed to read target ConfigMap '%s/%s': %s", namespace, config_map_name, exc)

        source_metadata = source_config_map.get("metadata") or {}
        source_labels = source_metadata.get("labels") or {}
        labels = {
            "managed-by": "kubesynapse",
            "kubesynapse.ai/runtime-config": "true",
        }
        component_label = str(source_labels.get("app.kubernetes.io/component") or "").strip()
        if component_label:
            labels["app.kubernetes.io/component"] = component_label

        annotations = {
            "kubesynapse.ai/config-hash": source_hash,
            "kubesynapse.ai/synced-at": _datetime.now(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if target_hash:
            annotations["kubesynapse.ai/previous-hash"] = target_hash

        config_map_manifest: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": config_map_name,
                "namespace": namespace,
                "labels": labels,
                "annotations": annotations,
            },
            "data": copy.deepcopy(source_data),
        }
        if source_binary_data:
            config_map_manifest["binaryData"] = copy.deepcopy(source_binary_data)
        if "immutable" in source_config_map:
            config_map_manifest["immutable"] = bool(source_config_map.get("immutable"))

        ensure_config_map(namespace, config_map_manifest)
        drift_msg = "updated" if target_hash else "provisioned"
        logger.info("ConfigMap '%s' %s for namespace '%s' (hash=%s)", config_map_name, drift_msg, namespace, source_hash)


def ensure_runtime_namespace_secret(namespace: str, owner_name: str, logger: logging.Logger) -> None:
    """Provision namespace-scoped runtime prerequisites for an agent namespace."""
    if SECRET_PROVISIONING_MODE == "external-secrets":  # noqa: S105 — provisioning mode, not a password
        external_secret = {
            "apiVersion": "external-secrets.io/v1beta1",
            "kind": "ExternalSecret",
            "metadata": {
                "name": SECRET_NAME,
                "namespace": namespace,
                "labels": {
                    "managed-by": "kubesynapse",
                    "kubesynapse.ai/runtime-secret": "true",
                    "kubesynapse.ai/owner": owner_name,
                },
            },
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": CLUSTER_SECRET_STORE, "kind": "ClusterSecretStore"},
                "target": {"name": SECRET_NAME},
                "data": [
                    {
                        "secretKey": "LITELLM_MASTER_KEY",
                        "remoteRef": {"key": "kubesynapse/litellm-master-key"},
                    },
                    {
                        "secretKey": "API_GATEWAY_SHARED_TOKEN",
                        "remoteRef": {"key": "kubesynapse/api-gateway-shared-token"},
                    },
                ],
            },
        }
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            custom_api.create_namespaced_custom_object(
                group="external-secrets.io",
                version="v1beta1",
                namespace=namespace,
                plural="externalsecrets",
                body=external_secret,
            )
            logger.info("ExternalSecret '%s' provisioned for namespace '%s'", SECRET_NAME, namespace)
        except ApiException as exc:
            if exc.status == 409:
                try:
                    custom_api.patch_namespaced_custom_object(
                        group="external-secrets.io",
                        version="v1beta1",
                        namespace=namespace,
                        plural="externalsecrets",
                        name=SECRET_NAME,
                        body=external_secret,
                    )
                except ApiException as patch_exc:
                    raise kopf.TemporaryError(
                        f"Failed to update ExternalSecret '{SECRET_NAME}' for namespace '{namespace}': {patch_exc}",
                        delay=30,
                    ) from patch_exc
            else:
                raise kopf.TemporaryError(
                    f"Failed to reconcile ExternalSecret '{SECRET_NAME}' for namespace '{namespace}': {exc}",
                    delay=30,
                ) from exc
        _ensure_runtime_namespace_immutable_config_maps(namespace, logger)
        return

    string_data: dict[str, str] = {}
    if DEFAULT_LITELLM_MASTER_KEY:
        string_data["LITELLM_MASTER_KEY"] = DEFAULT_LITELLM_MASTER_KEY
    if DEFAULT_API_GATEWAY_SHARED_TOKEN:
        string_data["API_GATEWAY_SHARED_TOKEN"] = DEFAULT_API_GATEWAY_SHARED_TOKEN

    if not string_data:
        logger.warning(
            (
                "Skipping runtime secret provisioning for namespace '%s' because "
                "DEFAULT_LITELLM_MASTER_KEY and DEFAULT_API_GATEWAY_SHARED_TOKEN are empty."
            ),
            namespace,
        )
        _ensure_runtime_namespace_immutable_config_maps(namespace, logger)
        return

    secret_manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "managed-by": "kubesynapse",
                "kubesynapse.ai/runtime-secret": "true",
                "kubesynapse.ai/owner": owner_name,
            },
        },
        "type": "Opaque",
        "stringData": string_data,
    }
    ensure_secret(namespace, secret_manifest)
    logger.info("Secret '%s' provisioned for namespace '%s'", SECRET_NAME, namespace)
    _ensure_runtime_namespace_immutable_config_maps(namespace, logger)


@_exponential_backoff()
def ensure_network_policy(namespace: str, manifest: dict[str, Any]) -> None:
    """Create or replace a NetworkPolicy."""
    networking_api = kubernetes.client.NetworkingV1Api()
    policy_name = str(manifest["metadata"]["name"])
    try:
        networking_api.create_namespaced_network_policy(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            networking_api.replace_namespaced_network_policy(name=policy_name, namespace=namespace, body=manifest)
        else:
            raise


@_exponential_backoff()
def ensure_runtime_access(namespace: str) -> None:
    """Create or patch a ServiceAccount, RoleBinding, and ClusterRoleBinding for agent runtimes."""
    core_api = kubernetes.client.CoreV1Api()
    rbac_api = kubernetes.client.RbacAuthorizationV1Api()
    binding_name = f"{RUNTIME_SERVICE_ACCOUNT}-binding"

    service_account = kubernetes.client.V1ServiceAccount(
        metadata=kubernetes.client.V1ObjectMeta(name=RUNTIME_SERVICE_ACCOUNT, namespace=namespace),
        image_pull_secrets=[
            kubernetes.client.V1LocalObjectReference(name=secret_name) for secret_name in IMAGE_PULL_SECRETS
        ]
        or None,
    )
    try:
        core_api.create_namespaced_service_account(namespace=namespace, body=service_account)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_service_account(
                name=RUNTIME_SERVICE_ACCOUNT,
                namespace=namespace,
                body=service_account,
            )
        else:
            raise

    binding = kubernetes.client.V1RoleBinding(
        metadata=kubernetes.client.V1ObjectMeta(
            name=binding_name,
            namespace=namespace,
        ),
        role_ref=kubernetes.client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="ClusterRole",
            name=RUNTIME_CLUSTER_ROLE,
        ),
        subjects=[
            kubernetes.client.V1Subject(
                kind="ServiceAccount",
                name=RUNTIME_SERVICE_ACCOUNT,
                namespace=namespace,
            )
        ],
    )
    try:
        rbac_api.create_namespaced_role_binding(namespace=namespace, body=binding)
    except ApiException as exc:
        if exc.status == 409:
            try:
                rbac_api.patch_namespaced_role_binding(
                    name=binding_name,
                    namespace=namespace,
                    body=binding,
                )
            except ApiException as patch_exc:
                patch_body = str(getattr(patch_exc, "body", "") or "")
                if patch_exc.status == 422 and "cannot change roleRef" in patch_body:
                    logger.warning(
                        "RoleBinding '%s/%s' has an immutable roleRef mismatch; recreating it.",
                        namespace,
                        binding_name,
                    )
                    rbac_api.delete_namespaced_role_binding(name=binding_name, namespace=namespace)
                    rbac_api.create_namespaced_role_binding(namespace=namespace, body=binding)
                else:
                    raise
        else:
            raise

    # P1-5: ClusterRoleBinding removed — agents receive namespace-scoped
    # RoleBindings only by default.  Cluster-wide read access (e.g. for
    # the Kubernetes MCP sidecar to read nodes) is opt-in via the Helm
    # value agentRuntime.clusterReadAccess.


# ---------------------------------------------------------------------------
# CRD status patching
# ---------------------------------------------------------------------------

_STATUS_PATCH_MAX_RETRIES: int = 3


def patch_custom_status(plural: str, namespace: str, name: str, status: dict[str, Any]) -> None:
    """Patch the .status subresource with optimistic concurrency retry on 409.

    On conflict, the current resource is re-fetched to obtain the latest
    ``resourceVersion`` so the retry body participates in proper optimistic
    locking instead of blindly sending the same stale body.
    """
    import random as _random
    import time as _time

    cb = get_k8s_circuit_breaker()
    api = kubernetes.client.CustomObjectsApi()
    for attempt in range(_STATUS_PATCH_MAX_RETRIES):
        try:
            cb.call()
            body: dict[str, Any] = {"status": status}
            if attempt > 0:
                body["metadata"] = {"resourceVersion": _latest_resource_version}
            api.patch_namespaced_custom_object_status(
                group="kubesynapse.ai",
                version="v1alpha1",
                namespace=namespace,
                plural=plural,
                name=name,
                body=body,
            )
            cb.record_success()
            return
        except ApiException as exc:
            cb.record_failure()
            if exc.status == 409 and attempt < _STATUS_PATCH_MAX_RETRIES - 1:
                try:
                    current = api.get_namespaced_custom_object(
                        group="kubesynapse.ai",
                        version="v1alpha1",
                        namespace=namespace,
                        plural=plural,
                        name=name,
                    )
                    _latest_resource_version = str(
                        (current.get("metadata") or {}).get("resourceVersion") or ""
                    )
                except ApiException:
                    _latest_resource_version = ""
                backoff = (2**attempt) + _random.uniform(0, 0.5)
                logging.getLogger("operator.services.k8s").warning(
                    "Conflict patching %s/%s/%s status (409), retry %d/%d in %.1fs "
                    "(refreshed resourceVersion=%s).",
                    plural,
                    namespace,
                    name,
                    attempt + 1,
                    _STATUS_PATCH_MAX_RETRIES,
                    backoff,
                    _latest_resource_version or "<unset>",
                )
                _time.sleep(backoff)
                continue
            raise


# ---------------------------------------------------------------------------
# Worker job management
# ---------------------------------------------------------------------------


def ensure_worker_artifact_storage(
    kind: str, resource_namespace: str, resource_name: str,
    owner_references: list[dict[str, Any]] | None = None,
) -> str:
    """Create the artifact PVC for a worker job and return its name."""
    manifest = create_worker_artifact_pvc_manifest(kind, resource_namespace, resource_name, owner_references)
    ensure_persistent_storage(OPERATOR_NAMESPACE, manifest)
    return str(manifest["metadata"]["name"])


@_exponential_backoff()
def enqueue_worker_job(
    kind: str,
    resource_namespace: str,
    resource_name: str,
    generation: int,
    artifact_pvc_name: str,
    artifact_path: str,
    *,
    run_id: str | None = None,
    git_config: dict[str, Any] | None = None,
    max_parallel_steps: int | None = None,
    resource_uid: str | None = None,
) -> str:
    """Create a worker Job and return its name."""
    manifest = create_worker_job_manifest(
        kind,
        resource_namespace,
        resource_name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=run_id,
        git_config=git_config,
        max_parallel_steps=max_parallel_steps,
        resource_uid=resource_uid,
    )
    job_name = str(manifest["metadata"]["name"])
    batch_api = kubernetes.client.BatchV1Api()
    try:
        existing = batch_api.read_namespaced_job(name=job_name, namespace=OPERATOR_NAMESPACE)
        if existing:
            # Job already exists — idempotent return
            return job_name
    except kubernetes.client.ApiException as exc:
        if exc.status != 404:
            raise
    batch_api.create_namespaced_job(namespace=OPERATOR_NAMESPACE, body=manifest)
    return job_name


@_exponential_backoff()
def read_job_state(name: str, namespace: str) -> str:
    """Read the current state of a Job: missing, pending, active, succeeded, failed, none.

    Returns:
        "none" — no worker job name has been assigned yet.
        "missing" — a job name was assigned but the Job resource does not exist.
        "pending" / "active" / "succeeded" / "failed" — Job lifecycle states.
    """
    if not name:
        return "none"

    batch_api = kubernetes.client.BatchV1Api()
    try:
        job = batch_api.read_namespaced_job(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            return "missing"
        raise

    status: Any = getattr(job, "status", None)
    if status is None:
        return "pending"
    if (status.active or 0) > 0:
        return "active"
    if (status.succeeded or 0) > 0:
        return "succeeded"
    if (status.failed or 0) > 0:
        return "failed"
    return "pending"


@_exponential_backoff()
def cancel_worker_job(name: str, namespace: str) -> bool:
    """Delete a worker Job and its pods. Returns True if a Job was deleted."""
    if not name:
        return False
    batch_api = kubernetes.client.BatchV1Api()
    try:
        batch_api.delete_namespaced_job(
            name=name,
            namespace=namespace,
            body=kubernetes.client.V1DeleteOptions(propagation_policy="Background"),
        )
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise


def read_worker_lease_freshness(kind: str, name: str, generation: int) -> tuple[bool, str]:
    """Check if a worker lease is currently held and fresh.

    §reliability-P2: Returns (is_fresh, holder_identity). A lease is considered
    fresh if its renew_time is within lease_duration_seconds of now.
    Used by the watchdog to avoid re-enqueueing workflows with active workers.
    """
    lease_name = f"{name}-gen-{generation}-{kind}"[:253]
    try:
        lease = kubernetes.client.CoordinationV1Api().read_namespaced_lease(
            name=lease_name, namespace=OPERATOR_NAMESPACE,
        )
    except ApiException as exc:
        if exc.status == 404:
            return False, ""
        raise

    spec = lease.spec
    if spec is None:
        return False, ""

    holder = str(spec.holder_identity or "")
    renew_time = spec.renew_time or spec.acquire_time
    duration = spec.lease_duration_seconds or 120

    if renew_time is None:
        return False, holder

    now = _datetime.now(_UTC)
    age_seconds = (now - renew_time).total_seconds()
    return age_seconds <= duration, holder


# ---------------------------------------------------------------------------
# Orphan pruning (§kagent-pattern-6)
# ---------------------------------------------------------------------------

# Resource types to prune — NetworkPolicies, Services, and Secrets (MCP auth).
# StatefulSets and PVCs are intentionally excluded: StatefulSets are owned via
# ownerReferences (K8s GC handles them), and PVCs use Retain policy.
_PRUNABLE_RESOURCE_TYPES: list[dict[str, str]] = [
    {
        "api": "NetworkingV1Api",
        "list": "list_namespaced_network_policy",
        "delete": "delete_namespaced_network_policy",
        "kind": "NetworkPolicy",
    },
    {"api": "CoreV1Api", "list": "list_namespaced_service", "delete": "delete_namespaced_service", "kind": "Service"},
    {"api": "CoreV1Api", "list": "list_namespaced_secret", "delete": "delete_namespaced_secret", "kind": "Secret"},
]


@_exponential_backoff()
def prune_orphaned_resources(
    namespace: str,
    agent_name: str,
    desired_names: set[str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Delete agent-scoped resources that are no longer in the desired set.

    Lists resources matching the owner labels
    (``kubesynapse.ai/managed-by=operator``,
    ``kubesynapse.ai/agent-name=<agent_name>``), then deletes any
    whose ``metadata.name`` is NOT in *desired_names*.

    Parameters
    ----------
    namespace : str
        The namespace to scan.
    agent_name : str
        The agent name to scope the label selector.
    desired_names : set[str]
        Resource names that should be kept (from ``AgentOutputs.desired_resource_names()``).
    dry_run : bool
        If True, log what would be deleted but don't actually delete.

    Returns
    -------
    list[str]
        Names of resources that were (or would be) deleted.
    """
    if not ORPHAN_PRUNING_ENABLED:
        return []

    label_selector = f"{OWNER_LABEL_MANAGED_BY}={OWNER_LABEL_MANAGED_BY_VALUE},{OWNER_LABEL_AGENT_NAME}={agent_name}"
    pruned: list[str] = []

    for resource_type in _PRUNABLE_RESOURCE_TYPES:
        api_cls = getattr(kubernetes.client, resource_type["api"])
        api_instance = api_cls()
        list_method = getattr(api_instance, resource_type["list"])
        delete_method = getattr(api_instance, resource_type["delete"])
        kind = resource_type["kind"]

        try:
            result = list_method(namespace=namespace, label_selector=label_selector)
        except ApiException as exc:
            logger.warning(
                "Orphan pruning: failed to list %s in namespace '%s': %s",
                kind,
                namespace,
                describe_api_exception(exc),
            )
            continue

        items = _sanitize_kube_resource(result)
        if isinstance(items, dict):
            items = items.get("items") or []
        elif hasattr(result, "items"):
            items = [_sanitize_kube_resource(item) for item in (result.items or [])]
        else:
            items = []

        for item in items:
            item_name = str((item.get("metadata") or {}).get("name") or "")
            if not item_name:
                continue
            if item_name in desired_names:
                continue

            if dry_run:
                logger.info(
                    "Orphan pruning (dry-run): would delete %s '%s' in namespace '%s' for agent '%s'.",
                    kind,
                    item_name,
                    namespace,
                    agent_name,
                )
                pruned.append(item_name)
                continue

            try:
                delete_method(name=item_name, namespace=namespace)
                logger.info(
                    "Orphan pruning: deleted %s '%s' in namespace '%s' for agent '%s'.",
                    kind,
                    item_name,
                    namespace,
                    agent_name,
                )
                pruned.append(item_name)
            except ApiException as exc:
                if exc.status == 404:
                    # Already gone — not an error
                    continue
                logger.warning(
                    "Orphan pruning: failed to delete %s '%s' in namespace '%s': %s",
                    kind,
                    item_name,
                    namespace,
                    describe_api_exception(exc),
                )

    return pruned
