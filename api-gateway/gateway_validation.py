"""§9 — Input validation and sanitization helpers for API Gateway.

Provides centralized validation for REST API payloads, query parameters,
and configuration with clear error messages and security constraints.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("api-gateway.validation")

# Resource name validation (RFC 1123)
RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
RESOURCE_NAME_MAX_LENGTH = 253
NAMESPACE_NAME_MAX_LENGTH = 63
API_KEY_MIN_LENGTH = 32
API_KEY_MAX_LENGTH = 256


def validate_resource_name(name: str | None, field: str, max_length: int = RESOURCE_NAME_MAX_LENGTH) -> str:
    """Validate a Kubernetes-compatible resource name.
    
    Raises ValueError if invalid.
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"{field} must be a non-empty string")
    
    name = name.strip()
    if not name:
        raise ValueError(f"{field} cannot be empty after whitespace trimming")
    
    if len(name) > max_length:
        raise ValueError(f"{field} exceeds maximum length {max_length}: {len(name)}")
    
    if not RESOURCE_NAME_PATTERN.match(name):
        raise ValueError(
            f"{field} '{name}' does not match RFC 1123 pattern. "
            "Must start/end with alphanumeric, contain only lowercase letters, numbers, and hyphens."
        )
    
    return name


def validate_namespace_name(namespace: str | None) -> str:
    """Validate a Kubernetes namespace name with stricter length limit."""
    if not namespace or not isinstance(namespace, str):
        raise ValueError("Namespace must be a non-empty string")
    
    namespace = namespace.strip()
    if not namespace:
        raise ValueError("Namespace cannot be empty after whitespace trimming")
    
    return validate_resource_name(namespace, "Namespace", max_length=NAMESPACE_NAME_MAX_LENGTH)


def validate_api_key(key: str | None, field: str = "API key") -> str:
    """Validate an API key format for minimum length and character set.
    
    Raises ValueError if invalid.
    """
    if not key or not isinstance(key, str):
        raise ValueError(f"{field} must be a non-empty string")
    
    key = key.strip()
    if not key:
        raise ValueError(f"{field} cannot be empty after whitespace trimming")
    
    if len(key) < API_KEY_MIN_LENGTH:
        raise ValueError(f"{field} is too short (minimum {API_KEY_MIN_LENGTH} characters)")
    
    if len(key) > API_KEY_MAX_LENGTH:
        raise ValueError(f"{field} exceeds maximum length {API_KEY_MAX_LENGTH}")
    
    # Allow alphanumeric, hyphens, underscores, dots (common for API keys)
    if not re.match(r"^[a-zA-Z0-9._-]+$", key):
        raise ValueError(f"{field} contains invalid characters (only alphanumeric, -, _, . allowed)")
    
    return key


def validate_json_size(data: Any, max_bytes: int = 5242880, field: str = "Payload") -> None:
    """Reject JSON larger than max_bytes to prevent DoS.
    
    Default: 5MB (prevents huge request bodies that could starve memory)
    Raises ValueError if too large.
    """
    json_str = json.dumps(data, default=str)
    size = len(json_str.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"{field} exceeds maximum size {max_bytes} bytes: {size}")


def validate_json_depth(
    data: Any,
    max_depth: int = 50,
    current_depth: int = 0,
    field: str = "Payload",
) -> None:
    """Reject deeply nested JSON to prevent DoS.
    
    Raises ValueError if too deep.
    """
    if current_depth > max_depth:
        raise ValueError(f"{field} exceeds maximum nesting depth {max_depth}")
    
    if isinstance(data, dict):
        for value in data.values():
            validate_json_depth(value, max_depth, current_depth + 1, field)
    elif isinstance(data, (list, tuple)):
        for item in data:
            validate_json_depth(item, max_depth, current_depth + 1, field)


def sanitize_log_field(value: Any, max_length: int = 400) -> str:
    """Convert any value to loggable string, truncating if needed.
    
    Prevents log injection and extremely long values that could break tools.
    """
    if value is None:
        return "<nil>"
    
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, default=str)
        except Exception:
            text = repr(value)
    else:
        text = str(value)
    
    if len(text) > max_length:
        return text[:max_length - 3] + "..."
    
    # Remove newlines to avoid log parsing issues
    return text.replace("\n", "\\n").replace("\r", "\\r")


def validate_url_param(param: str | None, field: str = "URL parameter") -> str:
    """Validate URL parameter for length and URL safety.
    
    Raises ValueError if invalid.
    """
    if not param or not isinstance(param, str):
        raise ValueError(f"{field} must be a non-empty string")
    
    param = param.strip()
    if not param:
        raise ValueError(f"{field} cannot be empty after whitespace trimming")
    
    # Limit to prevent URL length issues (most servers limit to 2000-8000 chars)
    if len(param) > 1000:
        raise ValueError(f"{field} exceeds maximum length 1000")
    
    return param


def validate_email(email: str | None) -> str:
    """Validate email address format.
    
    Raises ValueError if invalid.
    """
    if not email or not isinstance(email, str):
        raise ValueError("Email must be a non-empty string")
    
    email = email.strip().lower()
    if not email:
        raise ValueError("Email cannot be empty after whitespace trimming")
    
    # RFC 5322 simplified pattern (not perfect but good enough)
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValueError(f"Invalid email format: {email}")
    
    if len(email) > 320:  # Max length per RFC 5321
        raise ValueError("Email address exceeds maximum length 320")
    
    return email


def validate_enum(value: Any, allowed: set[str] | frozenset[str], field: str) -> str:
    """Validate value is one of allowed enum values.
    
    Raises ValueError if not allowed.
    """
    if value is None:
        raise ValueError(f"{field} is required")
    
    value_str = str(value).strip()
    if value_str not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}, got '{value_str}'")
    
    return value_str


def validate_agent_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate agent creation/update spec.
    
    Returns validated spec or raises ValueError.
    """
    validated = {}
    
    # Agent name (required, must be valid K8s name)
    if "name" in spec:
        validated["name"] = validate_resource_name(spec.get("name"), "Agent name")
    
    # Namespace (optional, defaults to current context)
    if "namespace" in spec:
        validated["namespace"] = validate_namespace_name(spec.get("namespace"))
    
    # Replicas (optional, must be 1+)
    if "replicas" in spec:
        replicas = spec.get("replicas")
        if not isinstance(replicas, int) or replicas < 1 or replicas > 100:
            raise ValueError("Replicas must be an integer between 1 and 100")
        validated["replicas"] = replicas
    
    # Image (optional, basic URL validation)
    if "image" in spec:
        image = spec.get("image")
        if not isinstance(image, str) or len(image) < 3 or len(image) > 256:
            raise ValueError("Image must be a string between 3-256 characters")
        validated["image"] = image.strip()
    
    # Policy (optional, must be known value)
    if "policy" in spec:
        policy = spec.get("policy")
        if isinstance(policy, str):
            validated["policy"] = validate_enum(policy, {"permissive", "strict"}, "Agent policy")
    
    return validated


def validate_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate workflow creation/update spec.
    
    Returns validated spec or raises ValueError.
    """
    validated = {}
    
    # Workflow name (required, must be valid K8s name)
    if "name" in spec:
        validated["name"] = validate_resource_name(spec.get("name"), "Workflow name")
    
    # Namespace (required, must be valid namespace)
    if "namespace" in spec:
        validated["namespace"] = validate_namespace_name(spec.get("namespace"))
    
    # Agent reference (optional)
    if "agent_ref" in spec:
        agent_ref = spec.get("agent_ref")
        if not isinstance(agent_ref, str) or not agent_ref.strip():
            raise ValueError("Agent reference must be a non-empty string")
        validated["agent_ref"] = agent_ref.strip()
    
    return validated
