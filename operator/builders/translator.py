"""Translator pattern — bundle all agent manifests into a single AgentOutputs.

Inspired by kagent's translator pattern (adk_api_translator.go): a thin
controller calls translate_agent() once to produce every manifest, then
passes the bundle to ensure_* functions.  Existing create_*_manifest()
functions are reused internally — no breaking changes.

§kagent-pattern-2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from builders.manifests import (
    create_a2a_egress_network_policy_manifest,
    create_a2a_ingress_network_policy_manifest,
    create_agent_service_manifest,
    create_agent_statefulset_manifest,
    create_mcp_auth_secret_manifest,
    create_mcp_network_policy_manifest,
    create_opencode_provider_bootstrap_secret,
    create_pi_provider_bootstrap_secret,
    resolve_runtime_kind,
    mcp_connections_require_shared_bearer_token,
)
from utils import (
    parse_a2a_peer_refs,
    parse_agent_a2a_config,
    parse_policy_a2a_config,
)

logger = logging.getLogger("operator.builders.translator")


# ---------------------------------------------------------------------------
# AgentOutputs — the manifest bundle
# ---------------------------------------------------------------------------


@dataclass
class AgentOutputs:
    """All Kubernetes manifests produced for a single AIAgent reconciliation.

    Fields mirror the resources created in agent_controller.create_agent_resources().
    Each field is a raw dict manifest (or None when the resource is optional).
    """

    service: dict[str, Any]
    statefulset: dict[str, Any]
    mcp_network_policy: dict[str, Any]
    a2a_egress_network_policy: dict[str, Any]
    a2a_ingress_network_policy: dict[str, Any]
    mcp_auth_secret: dict[str, Any] | None = None
    provider_bootstrap_secret: dict[str, Any] | None = None

    # Metadata carried through for logging / pruning
    agent_name: str = ""
    agent_namespace: str = ""
    policy_name: str | None = None
    runtime_kind: str = "opencode"
    allowed_mcp_servers: list[str] = field(default_factory=list)
    has_tenant: bool = False

    # ------------------------------------------------------------------
    # Convenience iterators
    # ------------------------------------------------------------------

    def owned_manifests(self) -> list[dict[str, Any]]:
        """Return all non-None manifests that should be adopted via kopf.adopt()."""
        return [
            m
            for m in (
                self.service,
                self.statefulset,
                self.mcp_network_policy,
                self.a2a_egress_network_policy,
                self.a2a_ingress_network_policy,
            )
            if m is not None
        ]

    def all_manifests(self) -> list[dict[str, Any]]:
        """Return every non-None manifest (including secrets not owned by the CR)."""
        manifests = self.owned_manifests()
        if self.mcp_auth_secret is not None:
            manifests.append(self.mcp_auth_secret)
        if self.provider_bootstrap_secret is not None:
            manifests.append(self.provider_bootstrap_secret)
        return manifests

    def desired_resource_names(self) -> set[str]:
        """Return the set of metadata.name values across all manifests.

        Used by orphan pruning (Pattern 6) to determine which resources
        are *desired* and should be kept.
        """
        names: set[str] = set()
        for manifest in self.all_manifests():
            name = (manifest.get("metadata") or {}).get("name")
            if name:
                names.add(str(name))
        return names


# ---------------------------------------------------------------------------
# translate_agent — the single entry point
# ---------------------------------------------------------------------------


def translate_agent(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    policy_name: str | None,
    policy_spec: dict[str, Any] | None,
    tenant_spec: dict[str, Any] | None = None,
) -> AgentOutputs:
    """Translate an AIAgent spec + resolved policy/tenant into a manifest bundle.

    This is a *pure computation* — it does not call the Kubernetes API.
    All K8s interactions (ensure_*, kopf.adopt) remain in the controller.

    Parameters
    ----------
    spec : dict
        The AIAgent .spec dict.
    name : str
        The AIAgent metadata.name.
    namespace : str
        The AIAgent metadata.namespace.
    policy_name : str | None
        Resolved AgentPolicy name (may be ``None``).
    policy_spec : dict | None
        Resolved AgentPolicy .spec dict (may be ``None`` or ``{}``).
    tenant_spec : dict | None
        Resolved AgentTenant .spec dict (may be ``None``).

    Returns
    -------
    AgentOutputs
        All manifests required for the agent's reconciliation.
    """
    policy_spec = policy_spec or {}

    agent_a2a_config = parse_agent_a2a_config(spec.get("a2a"), source="AIAgent.spec.a2a")
    policy_a2a_config = parse_policy_a2a_config(policy_spec)

    allowed_mcp: list[str] = sorted(
        {str(item).strip() for item in (policy_spec.get("allowedMcpServers") or []) if str(item).strip()}
    )
    requested_mcp_servers: list[str] = sorted(
        {str(item).strip() for item in (spec.get("mcpServers") or []) if str(item).strip()}
    )
    structured_mcp_connections = spec.get("mcpConnections") if isinstance(spec.get("mcpConnections"), list) else []
    needs_shared_mcp_bearer = mcp_connections_require_shared_bearer_token(structured_mcp_connections, requested_mcp_servers)

    # --- Build manifests (reuse existing builder functions) ---
    service_manifest = create_agent_service_manifest(name, namespace)
    statefulset_manifest = create_agent_statefulset_manifest(name, namespace, spec, policy_name, policy_spec)
    mcp_network_policy = create_mcp_network_policy_manifest(name, namespace, allowed_mcp)
    a2a_egress_policy = create_a2a_egress_network_policy_manifest(
        name,
        namespace,
        parse_a2a_peer_refs(policy_a2a_config.get("allowedTargets"), source="AgentPolicy.spec.a2a.allowedTargets"),
    )
    a2a_ingress_policy = create_a2a_ingress_network_policy_manifest(
        name,
        namespace,
        parse_a2a_peer_refs(agent_a2a_config.get("allowedCallers"), source="AIAgent.spec.a2a.allowedCallers"),
    )

    mcp_auth_secret: dict[str, Any] | None = None
    if needs_shared_mcp_bearer:
        mcp_auth_secret = create_mcp_auth_secret_manifest(namespace)

    runtime_kind = resolve_runtime_kind(spec)
    provider_bootstrap_secret = (
        create_pi_provider_bootstrap_secret(name, namespace)
        if runtime_kind == "pi"
        else None if runtime_kind == "mistral-vibe" else create_opencode_provider_bootstrap_secret(name, namespace, spec)
    )

    return AgentOutputs(
        service=service_manifest,
        statefulset=statefulset_manifest,
        mcp_network_policy=mcp_network_policy,
        a2a_egress_network_policy=a2a_egress_policy,
        a2a_ingress_network_policy=a2a_ingress_policy,
        mcp_auth_secret=mcp_auth_secret,
        provider_bootstrap_secret=provider_bootstrap_secret,
        agent_name=name,
        agent_namespace=namespace,
        policy_name=policy_name,
        runtime_kind=runtime_kind,
        allowed_mcp_servers=allowed_mcp,
        has_tenant=bool(tenant_spec),
    )
