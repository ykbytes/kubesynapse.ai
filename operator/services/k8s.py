"""Kubernetes API interaction layer — ensure, enqueue, and utility functions.

§2.1c of the road-to-prod plan: extract all K8s API calls
(ensure_*, enqueue_*, read_job_state, cancel_worker_job, patch_custom_status)
and their private helpers from operator/main.py into operator/services/.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import kopf

import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from config import (
    CLUSTER_SECRET_STORE,
    DEFAULT_API_GATEWAY_SHARED_TOKEN,
    DEFAULT_LITELLM_MASTER_KEY,
    IMAGE_PULL_SECRETS,
    OPERATOR_NAMESPACE,
    ORPHAN_PRUNING_ENABLED,
    RUNTIME_CLUSTER_ROLE,
    RUNTIME_SERVICE_ACCOUNT,
    SECRET_NAME,
    SECRET_PROVISIONING_MODE,
)
from builders import (
    OWNER_LABEL_AGENT_NAME,
    OWNER_LABEL_MANAGED_BY,
    OWNER_LABEL_MANAGED_BY_VALUE,
    _extract_statefulset_storage_request,
    _parse_storage_quantity,
    _statefulset_template_signature,
    artifact_file_path,
    build_artifact_ref,
    build_journal_ref,
    create_a2a_egress_network_policy_manifest,
    create_a2a_ingress_network_policy_manifest,
    create_agent_service_manifest,
    create_agent_statefulset_manifest,
    create_mcp_auth_secret_manifest,
    create_mcp_network_policy_manifest,
    create_worker_artifact_pvc_manifest,
    create_worker_job_manifest,
)
from utils import (
    build_eval_run_id,
    build_workflow_run_id,
    now_iso,
    parse_a2a_peer_refs,
    parse_agent_a2a_config,
    parse_policy_a2a_config,
    workflow_journal_path,
)

ApiTypeError = getattr(kubernetes.client, "ApiTypeError", TypeError)

logger = logging.getLogger("operator.services")


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
        except Exception:
            pass

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
                        (
                            f"PVC resize request for '{pvc_name}' in namespace '{namespace}' could not be applied: "
                            f"{describe_api_exception(exc)}"
                        )
                    )
                raise


# ---------------------------------------------------------------------------
# ensure_* — idempotent K8s resource creation / update
# ---------------------------------------------------------------------------


def ensure_persistent_storage(namespace: str, manifest: dict[str, Any]) -> None:
    """Create a PVC, silently ignoring AlreadyExists."""
    core_api = kubernetes.client.CoreV1Api()
    try:
        core_api.create_namespaced_persistent_volume_claim(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status != 409:
            raise


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
                )
            _resize_statefulset_persistent_volume_claims(
                core_api,
                namespace,
                statefulset_name,
                reconciled_statefulset,
                desired_storage,
            )
            return
        raise


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


def ensure_runtime_namespace_secret(namespace: str, owner_name: str, logger: logging.Logger) -> None:
    """Provision the runtime secret for a namespace (via ExternalSecret or native Secret)."""
    if SECRET_PROVISIONING_MODE == "external-secrets":
        external_secret = {
            "apiVersion": "external-secrets.io/v1beta1",
            "kind": "ExternalSecret",
            "metadata": {
                "name": SECRET_NAME,
                "namespace": namespace,
                "labels": {
                    "managed-by": "kubesynth",
                    "kubesynth.ai/runtime-secret": "true",
                    "kubesynth.ai/owner": owner_name,
                },
            },
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": CLUSTER_SECRET_STORE, "kind": "ClusterSecretStore"},
                "target": {"name": SECRET_NAME},
                "data": [
                    {
                        "secretKey": "LITELLM_MASTER_KEY",
                        "remoteRef": {"key": "kubesynth/litellm-master-key"},
                    },
                    {
                        "secretKey": "API_GATEWAY_SHARED_TOKEN",
                        "remoteRef": {"key": "kubesynth/api-gateway-shared-token"},
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
        return

    secret_manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "managed-by": "kubesynth",
                "kubesynth.ai/runtime-secret": "true",
                "kubesynth.ai/owner": owner_name,
            },
        },
        "type": "Opaque",
        "stringData": string_data,
    }
    ensure_secret(namespace, secret_manifest)
    logger.info("Secret '%s' provisioned for namespace '%s'", SECRET_NAME, namespace)


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


def ensure_runtime_access(namespace: str) -> None:
    """Create or patch a ServiceAccount and RoleBinding for agent runtimes."""
    core_api = kubernetes.client.CoreV1Api()
    rbac_api = kubernetes.client.RbacAuthorizationV1Api()

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
            name=f"{RUNTIME_SERVICE_ACCOUNT}-binding",
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
            rbac_api.patch_namespaced_role_binding(
                name=f"{RUNTIME_SERVICE_ACCOUNT}-binding",
                namespace=namespace,
                body=binding,
            )
        else:
            raise


# ---------------------------------------------------------------------------
# CRD status patching
# ---------------------------------------------------------------------------

_STATUS_PATCH_MAX_RETRIES: int = 3


def patch_custom_status(plural: str, namespace: str, name: str, status: dict[str, Any]) -> None:
    """Patch the .status subresource with optimistic concurrency retry on 409."""
    import random as _random
    import time as _time

    api = kubernetes.client.CustomObjectsApi()
    for attempt in range(_STATUS_PATCH_MAX_RETRIES):
        try:
            api.patch_namespaced_custom_object_status(
                group="kubesynth.ai",
                version="v1alpha1",
                namespace=namespace,
                plural=plural,
                name=name,
                body={"status": status},
            )
            return
        except ApiException as exc:
            if exc.status == 409 and attempt < _STATUS_PATCH_MAX_RETRIES - 1:
                backoff = (2**attempt) + _random.uniform(0, 0.5)
                logging.getLogger("operator.services.k8s").warning(
                    "Conflict patching %s/%s/%s status (409), retry %d/%d in %.1fs.",
                    plural,
                    namespace,
                    name,
                    attempt + 1,
                    _STATUS_PATCH_MAX_RETRIES,
                    backoff,
                )
                _time.sleep(backoff)
                continue
            raise


# ---------------------------------------------------------------------------
# Worker job management
# ---------------------------------------------------------------------------


def ensure_worker_artifact_storage(kind: str, resource_namespace: str, resource_name: str) -> str:
    """Create the artifact PVC for a worker job and return its name."""
    manifest = create_worker_artifact_pvc_manifest(kind, resource_namespace, resource_name)
    ensure_persistent_storage(OPERATOR_NAMESPACE, manifest)
    return str(manifest["metadata"]["name"])


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
    )
    batch_api = kubernetes.client.BatchV1Api()
    batch_api.create_namespaced_job(namespace=OPERATOR_NAMESPACE, body=manifest)
    return str(manifest["metadata"]["name"])


def read_job_state(name: str, namespace: str) -> str:
    """Read the current state of a Job: missing, pending, active, succeeded, failed."""
    if not name:
        return "missing"

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


def prune_orphaned_resources(
    namespace: str,
    agent_name: str,
    desired_names: set[str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Delete agent-scoped resources that are no longer in the desired set.

    Lists resources matching the owner labels
    (``kubesynth.ai/managed-by=operator``,
    ``kubesynth.ai/agent-name=<agent_name>``), then deletes any
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
