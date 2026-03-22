"""Controller package — one module per CRD kind.

§2.1d of the road-to-prod plan: controller-per-CRD architecture.

Importing this package registers all Kopf handlers.
"""

from controllers import (  # noqa: F401
    agent_controller,
    approval_controller,
    eval_controller,
    policy_controller,
    status_projection,
    tenant_controller,
    workflow_controller,
)
