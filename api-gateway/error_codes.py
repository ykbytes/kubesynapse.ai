"""Standardised error response model and error codes for KubeSynapse API gateway.

Every error returned by the gateway uses this model so clients (UI, CLI,
external integrations) can programmatically determine what went wrong and
what action to take next.

Usage:
    from error_codes import ErrorResponse, ErrorCode
    raise HTTPException(
        status_code=403,
        detail=ErrorResponse(
            code=ErrorCode.NAMESPACE_DENIED,
            message="Access denied",
            suggestion="Ask your admin to add namespace 'prod' to your account.",
        ).model_dump(),
    )
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Error codes — machine-readable identifiers for every failure mode
# ---------------------------------------------------------------------------


class ErrorCode:
    """Machine-readable error codes returned in every ErrorResponse."""

    # Auth (401)
    AUTH_EXPIRED = "AUTH_EXPIRED"
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_MISSING = "AUTH_MISSING"
    TOKEN_INVALID = "TOKEN_INVALID"
    SELF_REGISTRATION_DISABLED = "SELF_REGISTRATION_DISABLED"

    # Permission (403)
    NAMESPACE_DENIED = "NAMESPACE_DENIED"
    ROLE_TOO_LOW = "ROLE_TOO_LOW"
    SESSION_NOT_OWNED = "SESSION_NOT_OWNED"
    MEMORY_NOT_OWNED = "MEMORY_NOT_OWNED"
    USER_INACTIVE = "USER_INACTIVE"
    WEBHOOK_DISABLED = "WEBHOOK_DISABLED"
    WEBHOOK_IP_DENIED = "WEBHOOK_IP_DENIED"
    WEBHOOK_SIGNATURE_INVALID = "WEBHOOK_SIGNATURE_INVALID"

    # Not Found (404)
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
    ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"
    TENANT_NOT_FOUND = "TENANT_NOT_FOUND"

    # Validation (422)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"
    RESOURCE_NAME_INVALID = "RESOURCE_NAME_INVALID"

    # Conflict (409)
    RESOURCE_EXISTS = "RESOURCE_EXISTS"

    # Rate Limit (429)
    RATE_LIMITED = "RATE_LIMITED"

    # Server errors (500/502/503)
    INVOKE_FAILED = "INVOKE_FAILED"
    STREAM_FAILED = "STREAM_FAILED"
    AGENT_CREATE_FAILED = "AGENT_CREATE_FAILED"
    OPERATOR_ERROR = "OPERATOR_ERROR"
    RUNTIME_UNREACHABLE = "RUNTIME_UNREACHABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Suggestions — user-friendly next-step guidance for common errors
# ---------------------------------------------------------------------------


_SUGGESTIONS: dict[str, str] = {
    ErrorCode.NAMESPACE_DENIED: (
        "Contact your platform admin to add this namespace to your account's allowed namespaces."
    ),
    ErrorCode.ROLE_TOO_LOW: (
        "This operation requires operator or admin privileges. Contact your platform admin to upgrade your role."
    ),
    ErrorCode.AUTH_EXPIRED: (
        "Your session has expired. Please sign in again."
    ),
    ErrorCode.AGENT_NOT_FOUND: (
        "Check the agent name and namespace. If the agent was recently deleted, it may take a moment to reconcile."
    ),
    ErrorCode.POLICY_NOT_FOUND: (
        "The referenced policy does not exist. Create it first or check the policy name."
    ),
    ErrorCode.INVOKE_FAILED: (
        "The agent runtime encountered an error. Check the agent logs in the Execution Observatory for details."
    ),
    ErrorCode.RUNTIME_UNREACHABLE: (
        "The agent runtime is not responding. The operator may be provisioning it — wait a moment and retry."
    ),
    ErrorCode.INTERNAL_ERROR: (
        "An unexpected error occurred. Check the gateway logs for details using the request_id below."
    ),
    ErrorCode.VALIDATION_ERROR: (
        "Check the request body against the API schema. Required fields may be missing or have invalid values."
    ),
    ErrorCode.RATE_LIMITED: (
        "You have exceeded the rate limit. Wait before retrying."
    ),
}


def get_suggestion(error_code: str) -> str | None:
    """Return a user-friendly suggestion for a given error code, if available."""
    return _SUGGESTIONS.get(error_code)


# ---------------------------------------------------------------------------
# ErrorResponse — the standard error envelope
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standard error response returned by every KubeSynapse API endpoint.

    Fields:
        code:        Machine-readable error code (e.g. "NAMESPACE_DENIED").
        message:     Short human-readable summary.
        detail:      Optional longer explanation or context.
        suggestion:  Optional next-step guidance for the user.
        request_id:  Correlation ID for log tracing (from x-request-id header).
    """

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error summary")
    detail: str | None = Field(default=None, description="Additional context")
    suggestion: str | None = Field(default=None, description="Next-step guidance")
    request_id: str | None = Field(default=None, description="Correlation ID for logs")

    model_config = {"extra": "forbid"}


def build_error_response(
    *,
    code: str,
    message: str,
    detail: str | None = None,
    suggestion: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a dict suitable for use as HTTPException detail.

    Automatically fills in suggestion from the suggestion map when not
    explicitly provided.
    """
    if suggestion is None:
        suggestion = get_suggestion(code)
    return ErrorResponse(
        code=code,
        message=message,
        detail=detail,
        suggestion=suggestion,
        request_id=request_id,
    ).model_dump(exclude_none=True)
