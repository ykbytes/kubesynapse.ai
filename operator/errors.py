"""Structured error taxonomy for the kubesynapse operator.

Provides typed error codes for CRD status conditions, audit logging,
and machine-readable failure classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperatorError:
    """Structured operator error with machine-readable code and metadata."""

    code: str
    severity: str  # "fatal" | "transient" | "warning"
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_condition_reason(self) -> str:
        """Return a CamelCase reason string suitable for K8s status conditions."""
        return self.code.replace("_", " ").title().replace(" ", "")


# ---------------------------------------------------------------------------
# Error code constants — grouped by domain
# ---------------------------------------------------------------------------

# Agent provisioning
AGENT_RUNTIME_INVALID = "AGENT_RUNTIME_INVALID"
AGENT_MODEL_FORBIDDEN = "AGENT_MODEL_FORBIDDEN"
AGENT_POLICY_NOT_FOUND = "AGENT_POLICY_NOT_FOUND"
AGENT_POLICY_UNSUPPORTED = "AGENT_POLICY_UNSUPPORTED"
AGENT_MCP_CONFIG_INVALID = "AGENT_MCP_CONFIG_INVALID"
AGENT_GITHUB_CONFIG_INVALID = "AGENT_GITHUB_CONFIG_INVALID"
AGENT_RUNTIME_CONFIG_INVALID = "AGENT_RUNTIME_CONFIG_INVALID"
AGENT_SKILLS_INVALID = "AGENT_SKILLS_INVALID"
AGENT_STATEFULSET_FAILED = "AGENT_STATEFULSET_FAILED"

# Workflow execution
WORKFLOW_CYCLE_DETECTED = "WORKFLOW_CYCLE_DETECTED"
WORKFLOW_STEP_FAILED = "WORKFLOW_STEP_FAILED"
WORKFLOW_STEP_TIMEOUT = "WORKFLOW_STEP_TIMEOUT"
WORKFLOW_DUPLICATE_RUN = "WORKFLOW_DUPLICATE_RUN"
WORKFLOW_SPEC_INVALID = "WORKFLOW_SPEC_INVALID"

# Tenant management
TENANT_NAMESPACE_FAILED = "TENANT_NAMESPACE_FAILED"
TENANT_QUOTA_EXCEEDED = "TENANT_QUOTA_EXCEEDED"

# Runtime invocation
RUNTIME_TIMEOUT = "RUNTIME_TIMEOUT"
RUNTIME_INVOCATION_FAILED = "RUNTIME_INVOCATION_FAILED"
RUNTIME_NOT_READY = "RUNTIME_NOT_READY"

# Infrastructure
K8S_API_ERROR = "K8S_API_ERROR"
K8S_CONFLICT = "K8S_CONFLICT"
STATE_DB_ERROR = "STATE_DB_ERROR"


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------

def agent_provision_error(code: str, message: str, **metadata: Any) -> OperatorError:
    """Create a fatal error for agent provisioning failures."""
    return OperatorError(code=code, severity="fatal", message=message, metadata=metadata)


def workflow_execution_error(code: str, message: str, **metadata: Any) -> OperatorError:
    """Create a fatal error for workflow execution failures."""
    return OperatorError(code=code, severity="fatal", message=message, metadata=metadata)


def transient_error(code: str, message: str, **metadata: Any) -> OperatorError:
    """Create a transient error that may resolve on retry."""
    return OperatorError(code=code, severity="transient", message=message, metadata=metadata)


def warning_error(code: str, message: str, **metadata: Any) -> OperatorError:
    """Create a non-fatal warning."""
    return OperatorError(code=code, severity="warning", message=message, metadata=metadata)
