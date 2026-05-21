"""Controller package — one module per CRD kind.

§2.1d of the road-to-prod plan: controller-per-CRD architecture.

Importing this package registers all Kopf handlers.
"""

from __future__ import annotations

import importlib
import logging

from services import crd_exists

logger = logging.getLogger("operator.controllers")


def _import_controller(module_name: str) -> None:
    """Import a controller module for its side-effect of Kopf registration."""
    importlib.import_module(f"controllers.{module_name}")


# Core CRDs: always loaded.
_import_controller("agent_controller")
_import_controller("workflow_controller")
_import_controller("status_projection")

# Run Intelligence Layer — signal watch (timer-based, no CRD dependency)
_import_controller("signal_watch")


def _optional_controller(module_name: str, plural: str) -> None:
    """Import an optional controller only when its CRD exists."""
    if crd_exists("kubesynapse.ai", "v1alpha1", plural):
        _import_controller(module_name)
        return
    logger.warning(
        "Skipping optional controller '%s' because CRD '%s.kubesynapse.ai' is not installed.",
        module_name,
        plural,
    )


_optional_controller("approval_controller", "agentapprovals")
_optional_controller("tenant_controller", "agenttenants")
_optional_controller("policy_controller", "agentpolicies")
_optional_controller("observation_controller", "observationtargets")
_optional_controller("mcp_connection_controller", "mcpconnections")
_optional_controller("webhook_controller", "webhookreceivers")
