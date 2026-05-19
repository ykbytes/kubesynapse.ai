"""AgentTenant reconciler — create, update, resume, delete handlers.

§2.1d of the road-to-prod plan: tenant controller extracted from main.py.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from config import OPERATOR_NAMESPACE, PROTECTED_NAMESPACES, TENANT_EXEC_ACCESS
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from reconcile import execute_reconcile, log_operator_event, raise_reconcile_error
from services import (
    describe_api_exception,
    ensure_runtime_access,
    ensure_runtime_namespace_secret,
)

logger = logging.getLogger("operator.controllers.tenant")


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------

@kopf.on.create("kubesynapse.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def create_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    _reconcile_tenant(spec, name, logger)


def _reconcile_tenant(spec: dict[str, Any], name: str, logger: logging.Logger) -> None:
    """Core tenant reconciliation logic shared by create/update/resume handlers."""
    tenant_name = spec.get("tenantName", name)
    target_ns = spec.get("namespace", f"agent-tenant-{tenant_name}")
    quota_spec = spec.get("resourceQuota", {})
    admin_users = spec.get("adminUsers", [])

    if target_ns in PROTECTED_NAMESPACES or target_ns == OPERATOR_NAMESPACE:
        log_operator_event(
            logger,
            logging.ERROR,
            "Refusing to provision AgentTenant into a protected namespace.",
            resource_kind="AgentTenant",
            name=name,
            action="create-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        raise kopf.PermanentError(
            f"Refusing to provision tenant '{tenant_name}' into protected namespace '{target_ns}'."
        )

    log_operator_event(
        logger,
        logging.INFO,
        "Reconciling AgentTenant create event.",
        resource_kind="AgentTenant",
        name=name,
        action="create-tenant",
        tenantName=tenant_name,
        targetNamespace=target_ns,
        adminUserCount=len(admin_users),
    )

    try:
        core_api = kubernetes.client.CoreV1Api()
        rbac_api = kubernetes.client.RbacAuthorizationV1Api()

        namespace_body = kubernetes.client.V1Namespace(
            metadata=kubernetes.client.V1ObjectMeta(
                name=target_ns,
                labels={
                    "managed-by": "kubesynapse",
                    "tenant": tenant_name,
                    "kubesynapse.ai/tenant": "true",
                },
            )
        )
        try:
            core_api.create_namespace(body=namespace_body)
            logger.info("Namespace '%s' created", target_ns)
        except ApiException as exc:
            if exc.status == 409:
                ns_labels = namespace_body.metadata.labels if namespace_body.metadata else {}
                core_api.patch_namespace(
                    name=target_ns,
                    body={"metadata": {"labels": ns_labels}},
                )
                logger.info("Namespace '%s' already exists", target_ns)
            elif exc.status in (400, 422):
                raise kopf.PermanentError(f"Invalid namespace spec: {describe_api_exception(exc)}") from exc
            else:
                raise

        ensure_runtime_access(target_ns)

        hard_limits: dict[str, str] = {}
        if quota_spec.get("maxCPU"):
            hard_limits["limits.cpu"] = quota_spec["maxCPU"]
        if quota_spec.get("maxMemory"):
            hard_limits["limits.memory"] = quota_spec["maxMemory"]
        if quota_spec.get("maxPods"):
            hard_limits["pods"] = str(quota_spec["maxPods"])
        if quota_spec.get("maxGPU"):
            hard_limits["requests.nvidia.com/gpu"] = quota_spec["maxGPU"]

        if hard_limits:
            quota_body = kubernetes.client.V1ResourceQuota(
                metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-quota"),
                spec=kubernetes.client.V1ResourceQuotaSpec(hard=hard_limits),
            )
            try:
                core_api.create_namespaced_resource_quota(namespace=target_ns, body=quota_body)
                logger.info("ResourceQuota created for tenant '%s': %s", tenant_name, hard_limits)
            except ApiException as exc:
                if exc.status == 409:
                    core_api.patch_namespaced_resource_quota(
                        name=f"{tenant_name}-quota",
                        namespace=target_ns,
                        body=quota_body,
                    )
                else:
                    raise

        limit_range = kubernetes.client.V1LimitRange(
            metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-limits"),
            spec=kubernetes.client.V1LimitRangeSpec(
                limits=[
                    kubernetes.client.V1LimitRangeItem(
                        type="Container",
                        default={"cpu": "500m", "memory": "512Mi"},
                        default_request={"cpu": "100m", "memory": "128Mi"},
                    )
                ]
            ),
        )
        try:
            core_api.create_namespaced_limit_range(namespace=target_ns, body=limit_range)
            logger.info("LimitRange created for tenant '%s'", tenant_name)
        except ApiException as exc:
            if exc.status == 409:
                core_api.patch_namespaced_limit_range(
                    name=f"{tenant_name}-limits",
                    namespace=target_ns,
                    body=limit_range,
                )
            else:
                raise

        role = kubernetes.client.V1Role(
            metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-agent-admin", namespace=target_ns),
            rules=[
                kubernetes.client.V1PolicyRule(
                    api_groups=["kubesynapse.ai"],
                    resources=["aiagents", "agentpolicies", "agentapprovals", "agentworkflows"],
                    verbs=["*"],
                ),
                kubernetes.client.V1PolicyRule(
                    api_groups=[""],
                    resources=(
                        ["pods", "pods/exec", "pods/portforward", "pods/log", "services"]
                        if TENANT_EXEC_ACCESS
                        else ["pods", "pods/log", "services"]
                    ),
                    verbs=["get", "list", "watch", "create"],
                ),
            ],
        )
        try:
            rbac_api.create_namespaced_role(namespace=target_ns, body=role)
        except ApiException as exc:
            if exc.status == 409:
                rbac_api.patch_namespaced_role(
                    name=f"{tenant_name}-agent-admin",
                    namespace=target_ns,
                    body=role,
                )
            else:
                raise

        desired_binding_names: set[str] = set()
        for user in admin_users:
            safe_user = re.sub(r"[^a-z0-9-]", "-", user.lower().strip()).strip("-")
            if not safe_user:
                logger.warning("Skipping empty or invalid user string: %s", user)
                continue

            binding_name = f"{tenant_name}-{safe_user}-binding"
            desired_binding_names.add(binding_name)

            binding = kubernetes.client.V1RoleBinding(
                metadata=kubernetes.client.V1ObjectMeta(
                    name=binding_name,
                    namespace=target_ns,
                ),
                role_ref=kubernetes.client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io",
                    kind="Role",
                    name=f"{tenant_name}-agent-admin",
                ),
                subjects=[
                    kubernetes.client.V1Subject(
                        kind="User",
                        name=user,
                        api_group="rbac.authorization.k8s.io",
                    )
                ],
            )
            try:
                rbac_api.create_namespaced_role_binding(namespace=target_ns, body=binding)
                logger.info("RoleBinding created for user '%s' in tenant '%s'", user, tenant_name)
            except ApiException as exc:
                if exc.status == 409:
                    rbac_api.patch_namespaced_role_binding(
                        name=binding_name,
                        namespace=target_ns,
                        body=binding,
                    )
                else:
                    raise

        existing_bindings = rbac_api.list_namespaced_role_binding(namespace=target_ns)
        binding_items = getattr(existing_bindings, "items", None)
        if not isinstance(binding_items, list):
            binding_items = []

        tenant_role_name = f"{tenant_name}-agent-admin"
        binding_prefix = f"{tenant_name}-"
        for existing_binding in binding_items:
            metadata = getattr(existing_binding, "metadata", None)
            binding_name = str(getattr(metadata, "name", "") or "")
            if not binding_name or binding_name in desired_binding_names:
                continue
            if not binding_name.startswith(binding_prefix) or not binding_name.endswith("-binding"):
                continue

            role_ref = getattr(existing_binding, "role_ref", None)
            if str(getattr(role_ref, "name", "") or "") != tenant_role_name:
                continue

            try:
                rbac_api.delete_namespaced_role_binding(name=binding_name, namespace=target_ns)
                logger.info("RoleBinding '%s' removed from tenant '%s'", binding_name, tenant_name)
            except ApiException as exc:
                if exc.status != 404:
                    raise

        ensure_runtime_namespace_secret(target_ns, tenant_name, logger)

        log_operator_event(
            logger,
            logging.INFO,
            "AgentTenant resources reconciled.",
            resource_kind="AgentTenant",
            name=name,
            action="create-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
            adminUserCount=len(admin_users),
            quotaConfigured=bool(hard_limits),
        )
    except Exception as exc:
        raise_reconcile_error(
            logger,
            "create-tenant",
            exc,
            resource_kind="AgentTenant",
            name=name,
            default_delay=15,
            tenantName=tenant_name,
            targetNamespace=target_ns,
            adminUserCount=len(admin_users),
        )


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def delete_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    tenant_name = spec.get("tenantName", name)
    target_ns = spec.get("namespace", f"agent-tenant-{tenant_name}")
    if target_ns in PROTECTED_NAMESPACES or target_ns == OPERATOR_NAMESPACE:
        log_operator_event(
            logger,
            logging.ERROR,
            "Refusing to delete protected namespace via AgentTenant deletion.",
            resource_kind="AgentTenant",
            name=name,
            action="delete-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        return

    try:
        log_operator_event(
            logger,
            logging.INFO,
            "Deleting tenant namespace.",
            resource_kind="AgentTenant",
            name=name,
            action="delete-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        kubernetes.client.CoreV1Api().delete_namespace(name=target_ns)
    except ApiException as exc:
        if exc.status != 404:
            raise_reconcile_error(
                logger,
                "delete-tenant",
                exc,
                resource_kind="AgentTenant",
                name=name,
                default_delay=15,
                tenantName=tenant_name,
                targetNamespace=target_ns,
            )
        log_operator_event(
            logger,
            logging.INFO,
            "Tenant namespace already absent during delete.",
            resource_kind="AgentTenant",
            name=name,
            action="delete-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        return
    log_operator_event(
        logger,
        logging.INFO,
        "Tenant namespace deletion requested.",
        resource_kind="AgentTenant",
        name=name,
        action="delete-tenant",
        tenantName=tenant_name,
        targetNamespace=target_ns,
    )


@kopf.on.update("kubesynapse.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def update_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: _reconcile_tenant(spec, name, logger),
        logger=logger,
        action="update-tenant",
        resource_kind="AgentTenant",
        name=name,
        namespace=spec.get("namespace", f"agent-tenant-{spec.get('tenantName', name)}"),
        default_delay=10,
        start_message="Reconciling AgentTenant update event.",
        success_message="AgentTenant update reconciled.",
    )


@kopf.on.resume("kubesynapse.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def resume_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: _reconcile_tenant(spec, name, logger),
        logger=logger,
        action="resume-tenant",
        resource_kind="AgentTenant",
        name=name,
        namespace=spec.get("namespace", f"agent-tenant-{spec.get('tenantName', name)}"),
        default_delay=10,
        start_message="Reconciling existing AgentTenant on operator startup.",
        success_message="AgentTenant resume reconcile completed.",
    )
