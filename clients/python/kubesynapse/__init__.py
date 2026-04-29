"""kubesynapse Python SDK — programmatic access to the kubesynapse API gateway.

Usage:
    from kubesynapse import KubeSynapseClient

    client = KubeSynapseClient(base_url="http://localhost:8080")
    agents = client.list_agents()
    workflow = client.run_workflow("my-workflow", agent="devops-bot")
"""

from .client import KubeSynapseClient, KubeSynapseError
from .models import (
    Agent,
    AgentCreate,
    AgentList,
    AgentPolicy,
    AgentStatus,
    AgentWorkflow,
    AgentWorkflowCreate,
    AgentWorkflowStatus,
    HealthStatus,
)

__version__ = "0.1.0"
__all__ = [
    "Agent",
    "AgentCreate",
    "AgentList",
    "AgentPolicy",
    "AgentStatus",
    "AgentWorkflow",
    "AgentWorkflowCreate",
    "AgentWorkflowStatus",
    "HealthStatus",
    "KubeSynapseClient",
    "KubeSynapseError",
]
