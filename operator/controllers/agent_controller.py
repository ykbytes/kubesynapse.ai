"""AIAgent reconciler — create, update, resume, delete handlers.

§2.1d of the road-to-prod plan: agent controller extracted from main.py.
§kagent-pattern-2: Uses the translator pattern — translate_agent() produces
an AgentOutputs bundle, the controller applies it via ensure_* functions.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from builders.translator import AgentOutputs, translate_agent
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from reconcile import execute_reconcile, log_operator_event, validate_cross_namespace_ref
from services import (
    ensure_network_policy,
    ensure_runtime_access,
    ensure_runtime_namespace_secret,
    ensure_secret,
    ensure_service,
    ensure_statefulset,
    prune_orphaned_resources,
)

from utils import validate_supported_policy_spec

logger = logging.getLogger("operator.controllers.agent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_namespaced_ref(raw_ref: str | None) -> tuple[str | None, str | None]:
    """Parse a ref that may be either 'name' or 'namespace/name'."""
    value = str(raw_ref or "").strip()
    if not value:
        return None, None
    if "/" not in value:
        return None, value
    ref_namespace, ref_name = value.split("/", 1)
    return ref_namespace.strip() or None, ref_name.strip() or None


def resolve_agent_policy(namespace: str, policy_ref: str | None) -> tuple[str | None, dict[str, Any]]:
    """Resolve the AgentPolicy for a namespace, by ref or first-available."""
    custom_api = kubernetes.client.CustomObjectsApi()
    if policy_ref:
        policy_namespace, policy_name = _parse_namespaced_ref(policy_ref)
        resolved_policy_namespace = policy_namespace or namespace
        try:
            policy: dict[str, Any] = custom_api.get_namespaced_custom_object(
                group="kubesynapse.ai",
                version="v1alpha1",
                namespace=resolved_policy_namespace,
                plural="agentpolicies",
                name=policy_name,
            )  # type: ignore[assignment]
            policy_spec = policy.get("spec", {})
            validate_cross_namespace_ref(
                source_namespace=namespace,
                target_namespace=resolved_policy_namespace,
                allowed_namespaces=policy_spec.get("allowedNamespaces"),
                field_path="AIAgent.spec.policyRef",
                target_kind="AgentPolicy",
            )
            try:
                validate_supported_policy_spec(policy_spec)
            except ValueError as exc:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' is not supported: {exc}") from exc
            return policy_name, policy_spec
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' was not found") from exc
            raise

    policies = custom_api.list_namespaced_custom_object(
        group="kubesynapse.ai",
        version="v1alpha1",
        namespace=namespace,
        plural="agentpolicies",
    ).get("items", [])
    policies.sort(key=lambda item: item.get("metadata", {}).get("name", ""))
    if not policies:
        return None, {}
    policy = policies[0]
    policy_name = policy.get("metadata", {}).get("name")
    policy_spec = policy.get("spec", {})
    try:
        validate_supported_policy_spec(policy_spec)
    except ValueError as exc:
        raise kopf.PermanentError(f"AgentPolicy '{policy_name}' is not supported: {exc}") from exc
    return policy_name, policy_spec


def resolve_tenant_for_namespace(namespace: str) -> dict[str, Any] | None:
    """Find the AgentTenant spec that targets *namespace*."""
    custom_api = kubernetes.client.CustomObjectsApi()
    tenants = custom_api.list_cluster_custom_object(
        group="kubesynapse.ai",
        version="v1alpha1",
        plural="agenttenants",
    ).get("items", [])
    for tenant in tenants:
        tenant_spec = tenant.get("spec", {})
        if tenant_spec.get("namespace") == namespace:
            return tenant_spec
    return None


def validate_agent_model(model: str, policy_spec: dict[str, Any], tenant_spec: dict[str, Any] | None) -> None:
    """Validate the agent model against policy and tenant constraints."""
    policy_models = set(policy_spec.get("allowedModels", []))
    if policy_models and model not in policy_models:
        raise kopf.PermanentError(
            f"Model '{model}' is not allowed by AgentPolicy. Allowed models: {sorted(policy_models)}"
        )

    tenant_models = set((tenant_spec or {}).get("allowedModels", []))
    if tenant_models and model not in tenant_models:
        raise kopf.PermanentError(
            f"Model '{model}' is not allowed for tenant namespace. Allowed models: {sorted(tenant_models)}"
        )


def validate_agent_cross_namespace_targets(
    agent_spec: dict[str, Any],
    policy_spec: dict[str, Any],
    namespace: str,
) -> None:
    """Validate cross-namespace A2A targets using AIAgent.spec.allowedNamespaces."""
    allowed_namespaces = agent_spec.get("allowedNamespaces")
    a2a = (policy_spec or {}).get("a2a") or {}
    for index, target in enumerate(a2a.get("allowedTargets") or []):
        if not isinstance(target, dict):
            continue
        target_namespace = str(target.get("namespace") or "").strip() or namespace
        validate_cross_namespace_ref(
            source_namespace=namespace,
            target_namespace=target_namespace,
            allowed_namespaces=allowed_namespaces,
            field_path=f"AgentPolicy.spec.a2a.allowedTargets[{index}]",
            target_kind="AIAgent",
        )


def create_agent_resources(spec: dict[str, Any], name: str, namespace: str, handler_logger: logging.Logger) -> None:
    """Provision all Kubernetes resources for an AIAgent.

    Uses the translator pattern (§kagent-pattern-2): a single
    ``translate_agent()`` call produces an ``AgentOutputs`` bundle,
    then this function applies each manifest via ensure_* functions.
    """
    ensure_runtime_access(namespace)
    ensure_runtime_namespace_secret(namespace, name, handler_logger)
    policy_name, policy_spec = resolve_agent_policy(namespace, spec.get("policyRef"))
    tenant_spec = resolve_tenant_for_namespace(namespace)
    validate_agent_cross_namespace_targets(spec, policy_spec, namespace)
    validate_agent_model(spec.get("model", "gpt-4"), policy_spec, tenant_spec)

    # --- Translator pattern: produce all manifests in one call ---
    outputs: AgentOutputs = translate_agent(
        spec=spec,
        name=name,
        namespace=namespace,
        policy_name=policy_name,
        policy_spec=policy_spec,
        tenant_spec=tenant_spec,
    )

    log_operator_event(
        handler_logger,
        logging.INFO,
        "Resolved agent resource configuration.",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        policyName=outputs.policy_name,
        allowedMcpServers=outputs.allowed_mcp_servers,
        hasTenantPolicy=outputs.has_tenant,
        runtimeKind=outputs.runtime_kind,
    )

    # Adopt owned manifests (sets ownerReferences so K8s GC cleans up)
    for manifest in outputs.owned_manifests():
        kopf.adopt(manifest)

    # Apply manifests via idempotent ensure_* functions
    ensure_service(namespace, outputs.service)
    if outputs.mcp_auth_secret is not None:
        kopf.adopt(outputs.mcp_auth_secret)
        ensure_secret(namespace, outputs.mcp_auth_secret)
    if outputs.provider_bootstrap_secret is not None:
        kopf.adopt(outputs.provider_bootstrap_secret)
        ensure_secret(namespace, outputs.provider_bootstrap_secret)
    ensure_statefulset(namespace, outputs.statefulset)
    ensure_network_policy(namespace, outputs.mcp_network_policy)
    ensure_network_policy(namespace, outputs.a2a_egress_network_policy)
    ensure_network_policy(namespace, outputs.a2a_ingress_network_policy)
    pruned_resource_names = prune_orphaned_resources(namespace, name, outputs.desired_resource_names())
    if pruned_resource_names:
        log_operator_event(
            handler_logger,
            logging.INFO,
            "Pruned orphaned agent resources.",
            resource_kind="AIAgent",
            name=name,
            namespace=namespace,
            prunedResourceNames=sorted(pruned_resource_names),
        )


# ---------------------------------------------------------------------------
# Agent deletion cleanup (§prod-cleanup-1)
# ---------------------------------------------------------------------------


def _cleanup_agent_resources(name: str, namespace: str, handler_logger: logging.Logger) -> dict[str, list[str]]:
    """Clean up resources that survive AIAgent deletion.

    Kubernetes garbage-collects owner-referenced resources (Service,
    StatefulSet, NetworkPolicy, Secrets) when the AIAgent CR is deleted.
    However, PVCs created by StatefulSet volumeClaimTemplates use the
    ``whenDeleted: Retain`` policy and are intentionally NOT garbage-collected.

    This function:
    1. Deletes orphaned PVCs labeled with the agent name.
    2. Deletes any remaining NetworkPolicies, Services, or Secrets that
       somehow escaped ownerReference GC.

    Returns a summary of what was cleaned up.
    """
    cleaned: dict[str, list[str]] = {"pvcs": [], "network_policies": [], "services": [], "secrets": []}

    # --- Clean up orphaned PVCs ---
    core_api = kubernetes.client.CoreV1Api()
    label_selector = f"agent-name={name},app=ai-agent"
    try:
        pvcs = core_api.list_namespaced_persistent_volume_claim(
            namespace=namespace, label_selector=label_selector
        )
        for pvc in pvcs.items:
            pvc_name = pvc.metadata.name
            try:
                core_api.delete_namespaced_persistent_volume_claim(
                    name=pvc_name,
                    namespace=namespace,
                    propagation_policy="Background",
                )
                cleaned["pvcs"].append(pvc_name)
                handler_logger.info("Deleted orphaned PVC '%s/%s'.", namespace, pvc_name)
            except ApiException as exc:
                if exc.status != 404:
                    handler_logger.warning(
                        "Failed to delete PVC '%s/%s': %s", namespace, pvc_name, exc
                    )
    except ApiException as exc:
        handler_logger.warning("Failed to list PVCs for agent '%s/%s': %s", namespace, name, exc)

    # --- Clean up any surviving NetworkPolicies ---
    networking_api = kubernetes.client.NetworkingV1Api()
    try:
        netpols = networking_api.list_namespaced_network_policy(
            namespace=namespace, label_selector=label_selector
        )
        for netpol in netpols.items:
            netpol_name = netpol.metadata.name
            try:
                networking_api.delete_namespaced_network_policy(name=netpol_name, namespace=namespace)
                cleaned["network_policies"].append(netpol_name)
                handler_logger.info("Deleted orphaned NetworkPolicy '%s/%s'.", namespace, netpol_name)
            except ApiException as exc:
                if exc.status != 404:
                    handler_logger.warning(
                        "Failed to delete NetworkPolicy '%s/%s': %s", namespace, netpol_name, exc
                    )
    except ApiException as exc:
        handler_logger.warning("Failed to list NetworkPolicies for agent '%s/%s': %s", namespace, name, exc)

    # --- Clean up any surviving Services ---
    try:
        services = core_api.list_namespaced_service(namespace=namespace, label_selector=label_selector)
        for svc in services.items:
            svc_name = svc.metadata.name
            try:
                core_api.delete_namespaced_service(name=svc_name, namespace=namespace)
                cleaned["services"].append(svc_name)
                handler_logger.info("Deleted orphaned Service '%s/%s'.", namespace, svc_name)
            except ApiException as exc:
                if exc.status != 404:
                    handler_logger.warning(
                        "Failed to delete Service '%s/%s': %s", namespace, svc_name, exc
                    )
    except ApiException as exc:
        handler_logger.warning("Failed to list Services for agent '%s/%s': %s", namespace, name, exc)

    # --- Clean up any surviving Secrets ---
    try:
        secrets = core_api.list_namespaced_secret(namespace=namespace, label_selector=label_selector)
        for secret in secrets.items:
            secret_name = secret.metadata.name
            try:
                core_api.delete_namespaced_secret(name=secret_name, namespace=namespace)
                cleaned["secrets"].append(secret_name)
                handler_logger.info("Deleted orphaned Secret '%s/%s'.", namespace, secret_name)
            except ApiException as exc:
                if exc.status != 404:
                    handler_logger.warning(
                        "Failed to delete Secret '%s/%s': %s", namespace, secret_name, exc
                    )
    except ApiException as exc:
        handler_logger.warning("Failed to list Secrets for agent '%s/%s': %s", namespace, name, exc)

    return cleaned


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------


@kopf.on.create("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def create_agent(spec: dict[str, Any], name: str, namespace: str, logger: Any, retry: int = 0, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="create-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=10,
        retry=retry,
        start_message="Reconciling AIAgent create event.",
        success_message="AIAgent resources reconciled.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.update("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def update_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, retry: int = 0, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="update-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling AIAgent update event.",
        success_message="AIAgent update reconciled.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.resume("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def resume_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, retry: int = 0, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="resume-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling existing AIAgent on operator startup.",
        success_message="AIAgent resume reconcile completed.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def delete_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    """Clean up all agent-owned resources including PVCs on AIAgent deletion.

    Kubernetes GC handles owner-referenced resources (StatefulSet, Service,
    NetworkPolicy, Secrets). This handler explicitly cleans up:
    - PVCs from StatefulSet volumeClaimTemplates (retained by policy)
    - Any resources that escaped GC due to race conditions
    """
    del spec, kwargs
    log_operator_event(
        logger,
        logging.INFO,
        "AIAgent deleted — cleaning up owned resources including retained PVCs.",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        action="delete-agent",
    )
    try:
        cleaned = _cleanup_agent_resources(name, namespace, logger)
        total_cleaned = sum(len(v) for v in cleaned.values())
        if total_cleaned > 0:
            log_operator_event(
                logger,
                logging.INFO,
                f"Cleaned up {total_cleaned} orphaned resources for deleted AIAgent.",
                resource_kind="AIAgent",
                name=name,
                namespace=namespace,
                action="delete-agent-cleanup",
                cleanedResources=cleaned,
            )
        else:
            log_operator_event(
                logger,
                logging.INFO,
                "No additional cleanup needed for AIAgent (K8s GC handled owner-referenced resources).",
                resource_kind="AIAgent",
                name=name,
                namespace=namespace,
                action="delete-agent-cleanup",
            )
    except Exception as exc:
        log_operator_event(
            logger,
            logging.ERROR,
            f"Error during AIAgent deletion cleanup: {exc}",
            resource_kind="AIAgent",
            name=name,
            namespace=namespace,
            action="delete-agent-cleanup-error",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Orphan PVC cleanup timer (§prod-cleanup-2)
# ---------------------------------------------------------------------------


@kopf.timer("kubesynapse.ai", "v1alpha1", "aiagents", interval=300)  # type: ignore[arg-type]
def cleanup_orphan_pvcs(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    """Periodically check for and clean up PVCs belonging to this agent
    that have no corresponding StatefulSet (orphaned from prior deletions).

    This is a safety net for PVCs that were orphaned before the delete
    handler was enhanced to clean them up.
    """
    del kwargs
    core_api = kubernetes.client.CoreV1Api()
    apps_api = kubernetes.client.AppsV1Api()
    label_selector = f"agent-name={name},app=ai-agent"

    # Check if the StatefulSet still exists
    try:
        apps_api.read_namespaced_stateful_set(name=f"{name}-sandbox", namespace=namespace)
        # StatefulSet exists — no cleanup needed
        return
    except ApiException as exc:
        if exc.status != 404:
            logger.warning("Error checking StatefulSet for agent '%s/%s': %s", namespace, name, exc)
            return
        # StatefulSet not found — check for orphaned PVCs

    try:
        pvcs = core_api.list_namespaced_persistent_volume_claim(
            namespace=namespace, label_selector=label_selector
        )
        for pvc in pvcs.items:
            pvc_name = pvc.metadata.name
            try:
                core_api.delete_namespaced_persistent_volume_claim(
                    name=pvc_name,
                    namespace=namespace,
                    propagation_policy="Background",
                )
                log_operator_event(
                    logger,
                    logging.INFO,
                    f"Cleaned up orphaned PVC '{pvc_name}' with no matching StatefulSet.",
                    resource_kind="AIAgent",
                    name=name,
                    namespace=namespace,
                    action="orphan-pvc-cleanup",
                    pvcName=pvc_name,
                )
            except ApiException as del_exc:
                if del_exc.status != 404:
                    logger.warning(
                        "Failed to delete orphaned PVC '%s/%s': %s", namespace, pvc_name, del_exc
                    )
    except ApiException as exc:
        logger.warning("Failed to list PVCs for orphan cleanup of agent '%s/%s': %s", namespace, name, exc)
