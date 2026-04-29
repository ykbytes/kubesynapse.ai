"""Pydantic models matching the kubesynapse API v1 schema.

Auto-generated from /api/v1/openapi.json with manual refinements for ergonomic usage.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── Health ─────────────────────────────────────────────────────────

class HealthStatus(BaseModel):
    """Health check response."""
    status: str = Field(description="Overall health status: healthy, degraded, unhealthy")
    version: str = Field(description="API gateway version")
    uptime_seconds: float = Field(description="Gateway uptime in seconds")
    database: str = Field(default="unknown", description="Database connectivity: connected, disconnected")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Agents ─────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    """Agent lifecycle states."""
    PENDING = "pending"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPED = "stopped"
    FAILED = "failed"


class AgentCreate(BaseModel):
    """Request body for creating an AIAgent."""
    name: str = Field(description="Unique agent name")
    namespace: str = Field(default="kubesynapse", description="Kubernetes namespace")
    policy_ref: str = Field(default="default", description="AgentPolicy CRD name")
    replicas: int = Field(default=1, ge=1, le=10, description="Number of agent replicas")
    resources: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "requests": {"cpu": "100m", "memory": "256Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
        description="Pod resource requests and limits"
    )
    config: dict[str, Any] = Field(
        default_factory=lambda: {
            "contextWindow": 8192,
            "sessionTimeout": 3600,
        },
        description="Agent runtime configuration"
    )


class Agent(BaseModel):
    """An AIAgent resource."""
    name: str
    namespace: str
    status: AgentStatus
    policy_ref: str
    replicas: int
    ready_replicas: int = 0
    created_at: datetime
    updated_at: datetime | None = None
    spec: dict[str, Any] = Field(default_factory=dict)


class AgentList(BaseModel):
    """Paginated list of agents."""
    items: list[Agent]
    total: int
    page: int = 1
    page_size: int = 20


# ── Agent Policies ─────────────────────────────────────────────────

class AgentPolicy(BaseModel):
    """Governance policy for an AIAgent."""
    name: str
    max_tokens_per_request: int = 4096
    max_daily_cost: float = 5.0
    allowed_tools: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)
    llm_model: str = "gpt-4o-mini"
    system_prompt: str = ""


# ── Workflows ──────────────────────────────────────────────────────

class AgentWorkflowStatus(str, Enum):
    """Workflow execution states."""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStep(BaseModel):
    """A single step in an AgentWorkflow DAG."""
    name: str
    action: str
    agent: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    timeout: int = 60
    require_approval: bool = False


class AgentWorkflowCreate(BaseModel):
    """Request body for creating an AgentWorkflow."""
    name: str = Field(description="Workflow name")
    namespace: str = Field(default="kubesynapse")
    agent: str = Field(description="Agent to execute the workflow")
    steps: list[WorkflowStep] = Field(description="Ordered workflow steps")
    retry_policy: dict[str, Any] = Field(
        default_factory=lambda: {"max_retries": 3, "backoff": "exponential"},
        description="Retry configuration"
    )


class StepResult(BaseModel):
    """Result of a single workflow step."""
    name: str
    status: str
    output: str | None = None
    error: str | None = None
    duration_ms: float = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AgentWorkflow(BaseModel):
    """An AgentWorkflow resource with execution results."""
    name: str
    namespace: str
    agent: str
    status: AgentWorkflowStatus
    steps: list[StepResult] = Field(default_factory=list)
    total_steps: int = 0
    completed_steps: int = 0
    created_at: datetime
    updated_at: datetime | None = None


# ── Error ──────────────────────────────────────────────────────────

class APIError(BaseModel):
    """Standardized API error response."""
    error: str = Field(description="Error type")
    message: str = Field(description="Human-readable error message")
    status_code: int = Field(description="HTTP status code")
    detail: dict[str, Any] | None = None
