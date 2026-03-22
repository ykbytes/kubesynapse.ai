"""AIAgent reconciler — create, update, resume, delete handlers.

§2.1d of the road-to-prod plan: agent controller extracted from main.py.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf

import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from builders import (
    create_a2a_egress_network_policy_manifest,
    create_a2a_ingress_network_policy_manifest,
    create_agent_service_manifest,
    create_agent_statefulset_manifest,
    create_mcp_auth_secret_manifest,
    create_mcp_network_policy_manifest,
)
from reconcile import execute_reconcile, log_operator_event
from services import (
    ensure_network_policy,
    ensure_runtime_access,
    ensure_runtime_namespace_secret,
    ensure_secret,
    ensure_service,
    ensure_statefulset,
)
from utils import (
    parse_a2a_peer_refs,
    parse_agent_a2a_config,
    parse_policy_a2a_config,
    validate_supported_policy_spec,
)

logger = logging.getLogger("operator.controllers.agent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_agent_policy(namespace: str, policy_ref: str | None) -> tuple[str | None, dict[str, Any]]:
    """Resolve the AgentPolicy for a namespace, by ref or first-available."""
    custom_api = kubernetes.client.CustomObjectsApi()
    if policy_ref:
        try:
            policy: dict[str, Any] = custom_api.get_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentpolicies",
                name=policy_ref,
            )  # type: ignore[assignment]
            policy_spec = policy.get("spec", {})
            try:
                validate_supported_policy_spec(policy_spec)
            except ValueError as exc:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' is not supported: {exc}") from exc
            return policy_ref, policy_spec
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' was not found") from exc
            raise

    policies = custom_api.list_namespaced_custom_object(
        group="sandbox.enterprise.ai",
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
        group="sandbox.enterprise.ai",
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


def create_agent_resources(spec: dict[str, Any], name: str, namespace: str, handler_logger: logging.Logger) -> None:
    """Provision all Kubernetes resources for an AIAgent."""
    ensure_runtime_access(namespace)
    ensure_runtime_namespace_secret(namespace, name, handler_logger)
    policy_name, policy_spec = resolve_agent_policy(namespace, spec.get("policyRef"))
    tenant_spec = resolve_tenant_for_namespace(namespace)
    validate_agent_model(spec.get("model", "gpt-4"), policy_spec, tenant_spec)
    agent_a2a_config = parse_agent_a2a_config(spec.get("a2a"), source="AIAgent.spec.a2a")
    policy_a2a_config = parse_policy_a2a_config(policy_spec or {})
    allowed_mcp = sorted(
        {
            str(item).strip()
            for item in (policy_spec.get("allowedMcpServers") or [])
            if str(item).strip()
        }
    )

    service_manifest = create_agent_service_manifest(name, namespace)
    statefulset_manifest = create_agent_statefulset_manifest(name, namespace, spec, policy_name, policy_spec)
    network_policy_manifest = create_mcp_network_policy_manifest(name, namespace, allowed_mcp)
    a2a_egress_policy_manifest = create_a2a_egress_network_policy_manifest(
        name,
        namespace,
        parse_a2a_peer_refs(policy_a2a_config.get("allowedTargets"), source="AgentPolicy.spec.a2a.allowedTargets"),
    )
    a2a_ingress_policy_manifest = create_a2a_ingress_network_policy_manifest(
        name,
        namespace,
        parse_a2a_peer_refs(agent_a2a_config.get("allowedCallers"), source="AIAgent.spec.a2a.allowedCallers"),
    )
    mcp_auth_secret_manifest: dict[str, Any] | None = None
    if allowed_mcp:
        mcp_auth_secret_manifest = create_mcp_auth_secret_manifest(namespace)

    log_operator_event(
        handler_logger,
        logging.INFO,
        "Resolved agent resource configuration.",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        policyName=policy_name,
        allowedMcpServers=allowed_mcp,
        hasTenantPolicy=bool(tenant_spec),
        runtimeKind=str((spec.get("runtime") or {}).get("kind") or "langgraph")
        if isinstance(spec.get("runtime") or {}, dict)
        else "langgraph",
    )

    for manifest in (
        service_manifest,
        statefulset_manifest,
        network_policy_manifest,
        a2a_egress_policy_manifest,
        a2a_ingress_policy_manifest,
    ):
        if manifest is None:
            continue
        kopf.adopt(manifest)

    ensure_service(namespace, service_manifest)
    if mcp_auth_secret_manifest is not None:
        ensure_secret(namespace, mcp_auth_secret_manifest)
    ensure_statefulset(namespace, statefulset_manifest)
    ensure_network_policy(namespace, network_policy_manifest)
    ensure_network_policy(namespace, a2a_egress_policy_manifest)
    ensure_network_policy(namespace, a2a_ingress_policy_manifest)


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------

@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def create_agent(spec: dict[str, Any], name: str, namespace: str, logger: Any, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="create-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=10,
        start_message="Reconciling AIAgent create event.",
        success_message="AIAgent resources reconciled.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def update_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="update-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=5,
        start_message="Reconciling AIAgent update event.",
        success_message="AIAgent update reconciled.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.resume("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def resume_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="resume-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=5,
        start_message="Reconciling existing AIAgent on operator startup.",
        success_message="AIAgent resume reconcile completed.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def delete_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del spec, kwargs
    log_operator_event(
        logger,
        logging.INFO,
        "AIAgent deleted; Kubernetes-owned resources will be garbage-collected while PVCs are retained.",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        action="delete-agent",
    )
