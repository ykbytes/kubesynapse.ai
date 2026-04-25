"""AgentPolicy reconciler — create, update handlers.

§2.1d of the road-to-prod plan: policy controller extracted from main.py.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf
from reconcile import execute_reconcile

from utils import validate_supported_policy_spec

logger = logging.getLogger("operator.controllers.policy")


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------

@kopf.on.create("kubesynth.ai", "v1alpha1", "agentpolicies")  # type: ignore[arg-type]
def create_policy(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: validate_supported_policy_spec(spec),
        logger=logger,
        action="validate-policy",
        resource_kind="AgentPolicy",
        name=name,
        namespace=namespace,
        start_message="Validating AgentPolicy create event.",
        success_message="AgentPolicy validated.",
    )


@kopf.on.update("kubesynth.ai", "v1alpha1", "agentpolicies")  # type: ignore[arg-type]
def update_policy(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: validate_supported_policy_spec(spec),
        logger=logger,
        action="update-policy",
        resource_kind="AgentPolicy",
        name=name,
        namespace=namespace,
        start_message="Validating AgentPolicy update event.",
        success_message="AgentPolicy update validated.",
    )
