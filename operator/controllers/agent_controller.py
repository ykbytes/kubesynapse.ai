"""AIAgent reconciler — create, update, resume, delete handlers.

§2.1d of the road-to-prod plan: agent controller extracted from main.py.
§kagent-pattern-2: Uses the translator pattern — translate_agent() produces
an AgentOutputs bundle, the controller applies it via ensure_* functions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC as _UTC
from datetime import datetime as _datetime
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from builders.translator import AgentOutputs, translate_agent
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from reconcile import (
    build_condition,
    execute_reconcile,
    inject_conditions,
    log_operator_event,
    set_condition,
    validate_cross_namespace_ref,
)
from services import (
    describe_api_exception,
    ensure_network_policy,
    ensure_runtime_access,
    ensure_runtime_namespace_secret,
    ensure_secret,
    ensure_service,
    ensure_statefulset,
    patch_custom_status,
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
    if not model:
        raise kopf.PermanentError("AIAgent.spec.model must be explicitly set.")

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


def _patch_agent_status(
    plural: str,
    namespace: str,
    name: str,
    phase: str,
    conditions: list[dict[str, str]] | None = None,
    error: str | None = None,
    observed_generation: int | None = None,
) -> None:
    """Patch AIAgent status with phase, conditions, and optional error message."""
    status: dict[str, Any] = {"phase": phase}
    if conditions:
        status["conditions"] = conditions
    else:
        status = inject_conditions(status, phase)
    if error:
        status["error"] = error
    if observed_generation is not None:
        status["observedGeneration"] = observed_generation
    try:
        patch_custom_status(plural, namespace, name, status)
    except Exception as exc:
        logger.warning("Failed to patch AIAgent status for %s/%s: %s", namespace, name, describe_api_exception(exc))


def _record_agent_event(
    namespace: str,
    name: str,
    event_type: str,
    reason: str,
    message: str,
    *,
    action: str | None = None,
) -> None:
    """Record a Kubernetes Event on the AIAgent resource.

    Events appear in `kubectl describe aiagent <name>` and provide
    visibility into reconciliation history without reading operator logs.
    """
    core_api = kubernetes.client.CoreV1Api()
    now = _datetime.now(_UTC)

    event = kubernetes.client.CoreV1Event(
        metadata=kubernetes.client.V1ObjectMeta(
            generate_name=f"{name}-",
            namespace=namespace,
            labels={
                "kubesynapse.ai/owner": name,
                "kubesynapse.ai/event-type": event_type,
            },
        ),
        involved_object=kubernetes.client.V1ObjectReference(
            api_version="kubesynapse.ai/v1alpha1",
            kind="AIAgent",
            name=name,
            namespace=namespace,
        ),
        type=event_type,
        reason=reason,
        message=message,
        first_timestamp=now,
        last_timestamp=now,
        count=1,
        action=action or reason,
        reporting_component="kubesynapse-operator",
        reporting_instance="kubesynapse-operator",
    )

    try:
        core_api.create_namespaced_event(namespace=namespace, body=event)
    except ApiException as exc:
        if exc.status == 403:
            logger.debug("Operator lacks permission to create Events — skipping event recording")
        else:
            logger.warning("Failed to record K8s event for %s/%s: %s", namespace, name, describe_api_exception(exc))


def _validate_agent_dependencies(namespace: str, name: str, spec: dict[str, Any]) -> list[str]:
    """Validate that required dependencies exist before creating agent resources.

    Returns a list of missing dependency descriptions. Empty list means all OK.
    """
    missing: list[str] = []
    core_api = kubernetes.client.CoreV1Api()

    # Check required ConfigMaps exist in OPERATOR_NAMESPACE (source)
    from config import OPERATOR_NAMESPACE as _OP_NS
    from services import _runtime_immutable_config_map_names as _get_runtime_cm_names

    try:
        cm_names = _get_runtime_cm_names()
        for cm_name in cm_names:
            try:
                core_api.read_namespaced_config_map(name=cm_name, namespace=_OP_NS)
            except ApiException as exc:
                if exc.status == 404:
                    missing.append(f"ConfigMap '{cm_name}' not found in operator namespace '{_OP_NS}'")
    except Exception as exc:
        missing.append(f"Failed to check runtime ConfigMaps: {exc}")

    # Check ServiceAccount for runtime
    from config import RUNTIME_SERVICE_ACCOUNT as _SA

    try:
        core_api.read_namespaced_service_account(name=_SA, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            missing.append(f"ServiceAccount '{_SA}' not found in namespace '{namespace}'")

    # Check if secret provisioning is configured
    from config import SECRET_NAME as _SECRET_NAME
    from config import SECRET_PROVISIONING_MODE as _PROV_MODE

    if _PROV_MODE == "external-secrets":
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            custom_api.get_namespaced_custom_object(
                group="external-secrets.io",
                version="v1beta1",
                namespace=namespace,
                plural="externalsecrets",
                name=_SECRET_NAME,
            )
        except ApiException as exc:
            if exc.status == 404:
                missing.append(f"ExternalSecret '{_SECRET_NAME}' not found in namespace '{namespace}'")
    else:
        try:
            core_api.read_namespaced_secret(name=_SECRET_NAME, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                missing.append(f"Secret '{_SECRET_NAME}' not found in namespace '{namespace}'")

    # Check resource quotas — warn if namespace has quotas that may block pod scheduling
    quota_warnings = _check_resource_quotas(namespace, spec)
    missing.extend(quota_warnings)

    return missing


def _check_resource_quotas(namespace: str, spec: dict[str, Any]) -> list[str]:
    """Check if resource quotas may block agent pod scheduling.

    Returns a list of warning messages (not blocking, just warnings).
    """
    warnings: list[str] = []
    core_api = kubernetes.client.CoreV1Api()

    try:
        quotas = core_api.list_namespaced_resource_quota(namespace=namespace)
    except ApiException:
        return warnings

    # Extract resource requests from spec if available
    resources = (spec.get("resources") or {})
    requests = resources.get("requests") or {}

    for rq in quotas.items:
        rq_name = rq.metadata.name
        hard = rq.status.hard or {}
        used = rq.status.used or {}

        cpu_hard = hard.get("requests.cpu")
        cpu_used = used.get("requests.cpu")
        cpu_request = requests.get("cpu")
        if cpu_hard and cpu_used and cpu_request and _parse_quantity(cpu_used) + _parse_quantity(cpu_request) > _parse_quantity(cpu_hard):
            warnings.append(f"ResourceQuota '{rq_name}' CPU requests may be exceeded")

        mem_hard = hard.get("requests.memory")
        mem_used = used.get("requests.memory")
        mem_request = requests.get("memory")
        if mem_hard and mem_used and mem_request and _parse_quantity(mem_used) + _parse_quantity(mem_request) > _parse_quantity(mem_hard):
            warnings.append(f"ResourceQuota '{rq_name}' memory requests may be exceeded")

        pods_hard = hard.get("pods")
        pods_used = used.get("pods")
        if pods_hard and pods_used and _parse_quantity(pods_used) >= _parse_quantity(pods_hard):
            warnings.append(f"ResourceQuota '{rq_name}' pod limit reached")

    return warnings


def _parse_quantity(value: str) -> float:
    """Parse a Kubernetes resource quantity string to a numeric value.

    Supports: '100m', '1', '1.5', '1Gi', '512Mi', '1000', etc.
    """
    if not value:
        return 0.0
    val = str(value).strip()
    if val.endswith("m"):
        return float(val[:-1]) / 1000.0
    if val.endswith("Mi"):
        return float(val[:-2])
    if val.endswith("Gi"):
        return float(val[:-2]) * 1024.0
    if val.endswith("Ki"):
        return float(val[:-2]) / 1024.0
    return float(val)


def _compute_revision_hash(spec: dict[str, Any]) -> str:
    """Compute a deterministic hash from the agent spec for revision tracking.

    This hash changes when model, runtime config, resources, or other
    spec fields that affect the pod template are modified.
    """
    revision_data = {
        "model": spec.get("model"),
        "runtime": spec.get("runtime"),
        "resources": spec.get("resources"),
        "mcpServers": spec.get("mcpServers"),
        "mcpSidecars": spec.get("mcpSidecars"),
        "systemPrompt": spec.get("systemPrompt"),
        "policyRef": spec.get("policyRef"),
    }
    content = json.dumps(revision_data, sort_keys=True, default=str)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _check_revision_change(name: str, namespace: str, expected_hash: str, logger: logging.Logger) -> bool:
    """Check if the StatefulSet's revision hash matches the expected hash.

    Returns True if a revision change is detected (reconcile should trigger restart).
    """
    apps_api = kubernetes.client.AppsV1Api()
    sts_name = f"{name}-sandbox"

    try:
        sts = apps_api.read_namespaced_stateful_set(name=sts_name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            return False
        logger.warning("Failed to read StatefulSet for revision check: %s", describe_api_exception(exc))
        return False

    current_hash = (sts.spec.template.metadata.annotations or {}).get("kubesynapse.ai/revision-hash", "")
    return current_hash != expected_hash and current_hash != ""


def create_agent_resources(spec: dict[str, Any], name: str, namespace: str, handler_logger: logging.Logger, meta: dict[str, Any] | None = None) -> None:
    """Provision all Kubernetes resources for an AIAgent.

    Uses the translator pattern (§kagent-pattern-2): a single
    ``translate_agent()`` call produces an ``AgentOutputs`` bundle,
    then this function applies each manifest via ensure_* functions.
    """
    generation = int((meta or {}).get("generation", 0) or 0)
    plural = "aiagents"
    revision_hash = _compute_revision_hash(spec)

    _patch_agent_status(plural, namespace, name, "Provisioning", observed_generation=generation)
    _record_agent_event(namespace, name, "Normal", "ReconcileStarted", f"Reconciling AIAgent generation {generation} (revision={revision_hash})", action="reconcile")

    # Check for spec revision that may require pod restart
    revision_changed = _check_revision_change(name, namespace, revision_hash, handler_logger)
    if revision_changed:
        _record_agent_event(namespace, name, "Normal", "RevisionChanged", f"Spec revision changed to {revision_hash}, rolling restart will occur", action="revision")

    # Pre-flight dependency validation
    missing_deps = _validate_agent_dependencies(namespace, name, spec)
    if missing_deps:
        error_msg = "Missing dependencies: " + "; ".join(missing_deps)
        failed_condition = build_condition(
            "Ready", "False", "DependenciesMissing", error_msg
        )
        conditions = set_condition([], failed_condition)
        _patch_agent_status(plural, namespace, name, "Failed", conditions=conditions, error=error_msg, observed_generation=generation)
        _record_agent_event(namespace, name, "Warning", "DependenciesMissing", error_msg, action="validate")
        raise kopf.PermanentError(error_msg)

    ensure_runtime_access(namespace)
    ensure_runtime_namespace_secret(namespace, name, handler_logger)
    policy_name, policy_spec = resolve_agent_policy(namespace, spec.get("policyRef"))
    tenant_spec = resolve_tenant_for_namespace(namespace)
    validate_agent_cross_namespace_targets(spec, policy_spec, namespace)
    model = str(spec.get("model") or "").strip()
    validate_agent_model(model, policy_spec, tenant_spec)

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
    _record_agent_event(namespace, name, "Normal", "StatefulSetCreated", f"StatefulSet '{name}-sandbox' created/updated", action="create")
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
        _record_agent_event(
            namespace, name, "Normal", "OrphansPruned",
            f"Pruned {len(pruned_resource_names)} orphaned resources",
            action="prune",
        )

    ready_condition = build_condition(
        "Ready", "True", "ResourcesCreated", "All agent resources created successfully"
    )
    conditions = set_condition([], ready_condition)
    _patch_agent_status(plural, namespace, name, "Running", conditions=conditions, observed_generation=generation)
    _record_agent_event(namespace, name, "Normal", "ReconcileSucceeded", f"Generation {generation} reconciled successfully", action="reconcile")

    # Post-reconcile verification: ensure desired resources exist
    _verify_reconcile_idempotency(name, namespace, outputs.desired_resource_names(), handler_logger)


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


def _reconcile_agent(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    meta: dict[str, Any] | None = None,
    retry: int = 0,
    action: str = "reconcile-agent",
    start_message: str | None = None,
    success_message: str | None = None,
) -> None:
    """Execute agent reconciliation with status updates on success and failure."""
    generation = int((meta or {}).get("generation", 0) or 0)
    plural = "aiagents"
    try:
        execute_reconcile(
            lambda: create_agent_resources(spec, name, namespace, logger, meta),
            logger=logger,
            action=action,
            resource_kind="AIAgent",
            name=name,
            namespace=namespace,
            meta=meta,
            default_delay=5 if action != "create-agent" else 10,
            retry=retry,
            start_message=start_message,
            success_message=success_message,
            policyRef=spec.get("policyRef"),
        )
    except Exception as exc:
        error_msg = str(exc)
        failed_condition = build_condition(
            "Ready", "False", "ReconcileFailed", error_msg[:500]
        )
        conditions = set_condition([], failed_condition)
        _patch_agent_status(plural, namespace, name, "Failed", conditions=conditions, error=error_msg[:1000], observed_generation=generation)
        raise


@kopf.on.create("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def create_agent(spec: dict[str, Any], name: str, namespace: str, logger: Any, meta: dict[str, Any] | None = None, retry: int = 0, **kwargs: Any) -> None:
    del kwargs
    _reconcile_agent(
        spec, name, namespace, logger, meta, retry,
        action="create-agent",
        start_message="Reconciling AIAgent create event.",
        success_message="AIAgent resources reconciled.",
    )


@kopf.on.update("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def update_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, meta: dict[str, Any] | None = None, retry: int = 0, **kwargs: Any) -> None:
    del kwargs
    _reconcile_agent(
        spec, name, namespace, logger, meta, retry,
        action="update-agent",
        start_message="Reconciling AIAgent update event.",
        success_message="AIAgent update reconciled.",
    )


@kopf.on.resume("kubesynapse.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def resume_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, meta: dict[str, Any] | None = None, retry: int = 0, **kwargs: Any) -> None:
    del kwargs
    _reconcile_agent(
        spec, name, namespace, logger, meta, retry,
        action="resume-agent",
        start_message="Reconciling existing AIAgent on operator startup.",
        success_message="AIAgent resume reconcile completed.",
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


# ---------------------------------------------------------------------------
# Runtime health monitoring (§prod-health-1)
# ---------------------------------------------------------------------------


def _check_runtime_health(name: str, namespace: str, logger: logging.Logger) -> tuple[bool, str]:
    """Check if the agent runtime pod is healthy via K8s readiness conditions.

    Uses K8s pod conditions instead of direct HTTP to avoid network policy issues.
    Returns (is_healthy, message) tuple.
    """
    core_api = kubernetes.client.CoreV1Api()
    label_selector = f"agent-name={name},app=ai-agent"

    try:
        pods = core_api.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
    except ApiException as exc:
        return False, f"Failed to list pods: {describe_api_exception(exc)}"

    if not pods.items:
        return False, "No pods found for agent"

    pod = pods.items[0]
    pod_phase = pod.status.phase if pod.status else "Unknown"
    conditions = pod.status.conditions if pod.status else []

    if pod_phase not in ("Running",):
        # Check for common failure reasons in container statuses
        container_issues = _detect_container_issues(pod)
        if container_issues:
            return False, f"Pod phase={pod_phase}: {container_issues}"
        return False, f"Pod is not running (phase={pod_phase})"

    # Check for container issues even if pod is Running (e.g., restarts)
    container_issues = _detect_container_issues(pod)
    if container_issues:
        return False, container_issues

    # Check readiness condition
    ready_condition = None
    for cond in conditions or []:
        if cond.type == "Ready":
            ready_condition = cond
            break

    if ready_condition is None:
        return False, "Pod has no Ready condition yet"

    if ready_condition.status == "True":
        return True, "Pod is ready and running"

    reason = ready_condition.reason or "NotReady"
    message = ready_condition.message or "Pod is not ready"
    return False, f"Pod not ready (reason={reason}, message={message[:200]})"


def _detect_container_issues(pod) -> str:
    """Detect common container issues from pod status.

    Returns issue description or empty string if no issues found.
    """
    if not pod.status:
        return ""

    # Check container statuses for issues
    container_statuses = (
        (pod.status.container_statuses or []) +
        (pod.status.init_container_statuses or [])
    )

    for cs in container_statuses:
        if not cs:
            continue

        # Check waiting state
        if cs.state and cs.state.waiting:
            reason = cs.state.waiting.reason or ""
            message = cs.state.waiting.message or ""
            if reason in ("ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"):
                return f"Container '{cs.name}' {reason}: {message[:200]}"
            if reason == "CrashLoopBackOff":
                restart_count = cs.restart_count or 0
                return f"Container '{cs.name}' CrashLoopBackOff (restarts={restart_count}): {message[:200]}"

        # Check terminated state for errors
        if cs.state and cs.state.terminated:
            reason = cs.state.terminated.reason or ""
            exit_code = cs.state.terminated.exit_code or 0
            if exit_code != 0:
                if reason == "OOMKilled":
                    return f"Container '{cs.name}' OOMKilled (exit_code={exit_code})"
                return f"Container '{cs.name}' terminated (reason={reason}, exit_code={exit_code})"

        # High restart count
        if cs.restart_count and cs.restart_count > 5:
            return f"Container '{cs.name}' has restarted {cs.restart_count} times"

    return ""


def _verify_reconcile_idempotency(
    name: str, namespace: str, desired_names: set[str], logger: logging.Logger
) -> None:
    """Verify that all desired resources exist after reconciliation.

    This is a safety check to detect any resources that should have been
    created but weren't, indicating a potential idempotency issue.
    """
    core_api = kubernetes.client.CoreV1Api()
    apps_api = kubernetes.client.AppsV1Api()
    networking_api = kubernetes.client.NetworkingV1Api()

    missing: list[str] = []

    # Check StatefulSet
    try:
        apps_api.read_namespaced_stateful_set(name=f"{name}-sandbox", namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            missing.append(f"StatefulSet '{name}-sandbox'")

    # Check Service
    try:
        core_api.read_namespaced_service(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404 and f"{name}" in desired_names:
            missing.append(f"Service '{name}'")

    # Check NetworkPolicies
    for netpol_suffix in ("mcp", "a2a-egress", "a2a-ingress"):
        netpol_name = f"{name}-{netpol_suffix}"
        if netpol_name in desired_names:
            try:
                networking_api.read_namespaced_network_policy(name=netpol_name, namespace=namespace)
            except ApiException as exc:
                if exc.status == 404:
                    missing.append(f"NetworkPolicy '{netpol_name}'")

    if missing:
        logger.warning(
            "Post-reconcile verification failed for %s/%s: missing resources: %s",
            namespace, name, missing,
        )
        _record_agent_event(
            namespace, name, "Warning", "ReconcileVerificationFailed",
            f"Missing resources after reconcile: {', '.join(missing)}",
            action="verify",
        )


@kopf.timer("kubesynapse.ai", "v1alpha1", "aiagents", interval=60)  # type: ignore[arg-type]
def monitor_agent_runtime_health(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    """Periodically check agent runtime health and update status conditions."""
    del kwargs
    plural = "aiagents"

    apps_api = kubernetes.client.AppsV1Api()
    try:
        sts = apps_api.read_namespaced_stateful_set(name=f"{name}-sandbox", namespace=namespace)
        if sts.status and sts.status.ready_replicas and sts.status.ready_replicas > 0:
            is_healthy, message = _check_runtime_health(name, namespace, logger)

            # Check credential proxy sidecar health
            proxy_healthy, proxy_message = _check_credential_proxy_health(name, namespace, logger)
            if not proxy_healthy:
                message = f"{message}; proxy: {proxy_message}"

            # Check API gateway connectivity
            gateway_ok, gateway_message = _check_gateway_connectivity(name, namespace, logger)
            if not gateway_ok:
                message = f"{message}; gateway: {gateway_message}"

            all_healthy = is_healthy and proxy_healthy and gateway_ok
            if all_healthy:
                healthy_condition = build_condition(
                    "RuntimeHealthy", "True", "HealthCheckPassed", message
                )
            else:
                healthy_condition = build_condition(
                    "RuntimeHealthy", "False", "HealthCheckFailed", message
                )
                log_operator_event(
                    logger,
                    logging.WARNING,
                    f"Agent runtime health check failed: {message}",
                    resource_kind="AIAgent",
                    name=name,
                    namespace=namespace,
                    action="runtime-health-check",
                    healthMessage=message,
                )

            conditions = set_condition([], healthy_condition)
            _patch_agent_status(plural, namespace, name, "Running", conditions=conditions)
        else:
            waiting_condition = build_condition(
                "RuntimeHealthy", "Unknown", "WaitingForPods", "StatefulSet pods not yet ready"
            )
            conditions = set_condition([], waiting_condition)
            _patch_agent_status(plural, namespace, name, "Running", conditions=conditions)
    except ApiException as exc:
        if exc.status == 404:
            not_found_condition = build_condition(
                "RuntimeHealthy", "False", "StatefulSetMissing", "Agent StatefulSet not found"
            )
            conditions = set_condition([], not_found_condition)
            _patch_agent_status(plural, namespace, name, "Running", conditions=conditions)
        else:
            logger.warning("Error checking StatefulSet for agent '%s/%s': %s", namespace, name, exc)


def _check_credential_proxy_health(name: str, namespace: str, logger: logging.Logger) -> tuple[bool, str]:
    """Check if the credential proxy sidecar is running in the agent pod.

    Returns (is_healthy, message) tuple.
    """
    core_api = kubernetes.client.CoreV1Api()
    label_selector = f"agent-name={name},app=ai-agent"

    try:
        pods = core_api.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
    except ApiException as exc:
        return False, f"Failed to list pods: {describe_api_exception(exc)}"

    if not pods.items:
        return False, "No pods found"

    pod = pods.items[0]
    container_statuses = pod.status.container_statuses or []

    # Look for credential-proxy container
    proxy_status = None
    for cs in container_statuses:
        if cs and "credential-proxy" in (cs.name or "").lower():
            proxy_status = cs
            break

    if proxy_status is None:
        return True, "Credential proxy not configured (sidecar not present)"

    if not proxy_status.ready:
        if proxy_status.state and proxy_status.state.waiting:
            reason = proxy_status.state.waiting.reason or "Waiting"
            message = proxy_status.state.waiting.message or ""
            return False, f"Proxy not ready ({reason}): {message[:200]}"
        return False, "Proxy container not ready"

    if proxy_status.restart_count and proxy_status.restart_count > 3:
        return False, f"Proxy has restarted {proxy_status.restart_count} times"

    return True, "Credential proxy is healthy"


def _check_gateway_connectivity(name: str, namespace: str, logger: logging.Logger) -> tuple[bool, str]:
    """Verify the API gateway is reachable from the operator.

    This checks gateway health from the operator's perspective, not from
    within the agent pod (which would require exec or port-forward).
    Returns (is_healthy, message) tuple.
    """
    from config import GATEWAY_URL as _GW_URL

    if not _GW_URL:
        return True, "Gateway URL not configured (skipping check)"

    try:
        import httpx
        health_url = f"{_GW_URL}/health"
        with httpx.Client(timeout=5) as client:
            response = client.get(health_url)
            if response.status_code == 200:
                return True, "Gateway is reachable"
            return False, f"Gateway returned status {response.status_code}"
    except Exception as exc:
        return False, f"Gateway unreachable: {exc}"
