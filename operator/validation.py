"""§9 — Input validation and sanitization helpers for Operator security.

Provides centralized validation for CRD specs, API inputs, and configuration
with clear error messages and security constraints.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("operator.validation")

# Resource name validation (RFC 1123)
RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
RESOURCE_NAME_MAX_LENGTH = 253
NAMESPACE_NAME_MAX_LENGTH = 63


def validate_resource_name(name: str | None, field: str, max_length: int = RESOURCE_NAME_MAX_LENGTH) -> str:
    """Validate a Kubernetes resource name.
    
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


def validate_json_size(data: Any, max_bytes: int = 1048576, field: str = "JSON data") -> None:
    """Reject JSON larger than max_bytes to prevent DoS.
    
    Raises ValueError if too large.
    """
    json_str = json.dumps(data, default=str)
    size = len(json_str.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"{field} exceeds maximum size {max_bytes} bytes: {size}")


def validate_json_depth(data: Any, max_depth: int = 50, current_depth: int = 0, field: str = "JSON data") -> None:
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


def validate_cross_namespace_reference(
    source_ns: str | None,
    target_ns: str | None,
    config: dict[str, Any] | None,
    field: str = "Field reference",
) -> None:
    """§5.3 — Validate cross-namespace reference against policy rules.
    
    Raises ValueError or kopf.PermanentError if not allowed.
    """
    if not source_ns or not target_ns:
        raise ValueError(f"{field}: source and target namespaces must be specified")
    
    if source_ns == target_ns:
        # Same namespace is always allowed
        return
    
    config = config or {}
    mode = str(config.get("from", "Same")).strip() or "Same"
    
    if mode == "All":
        # All namespaces allowed
        return
    
    if mode == "Same":
        raise ValueError(
            f"{field}: cross-namespace references are restricted to the same namespace. "
            f"Cannot reference resource in '{target_ns}' from '{source_ns}'."
        )
    
    if mode == "Selector":
        selector = config.get("selector", {})
        if _match_namespace_selector(target_ns, selector):
            return
        
        raise ValueError(
            f"{field}: target namespace '{target_ns}' does not match selector in policy. "
            f"Reference from '{source_ns}' is not allowed."
        )
    
    raise ValueError(f"{field}: unknown namespace reference policy mode '{mode}'")


def _match_namespace_selector(namespace: str, selector: dict[str, Any]) -> bool:
    """Evaluate a minimal namespace selector against a namespace name."""
    match_names = selector.get("matchNames")
    if isinstance(match_names, list):
        return namespace in {str(item).strip() for item in match_names if str(item).strip()}
    
    match_labels = selector.get("matchLabels") or {}
    label_namespace = str(match_labels.get("kubernetes.io/metadata.name") or "").strip()
    if label_namespace:
        return namespace == label_namespace
    
    return False


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


def validate_spec_constraints(spec: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    """Validate a CRD spec against constraint rules.
    
    Returns sanitized spec or raises ValueError.
    Constraints format:
    {
        "field_name": {
            "type": "string" | "int" | "list" | "dict",
            "required": True | False,
            "max_length": 128,
            "pattern": r"^[a-z]+$",
            "allowed_values": ["value1", "value2"],
        }
    }
    """
    validated = {}
    
    for field_name, field_constraints in constraints.items():
        value = spec.get(field_name)
        field_type = field_constraints.get("type", "string")
        is_required = field_constraints.get("required", False)
        
        # Check required
        if is_required and value is None:
            raise ValueError(f"Required field '{field_name}' is missing")
        
        if value is None:
            continue
        
        # Type check
        type_map = {
            "string": str,
            "int": int,
            "bool": bool,
            "list": list,
            "dict": dict,
        }
        expected_type = type_map.get(field_type)
        if expected_type and not isinstance(value, expected_type):
            raise ValueError(f"Field '{field_name}' must be {field_type}, got {type(value).__name__}")
        
        # Max length check
        if field_type == "string" and "max_length" in field_constraints:
            max_len = field_constraints["max_length"]
            if len(value) > max_len:
                raise ValueError(f"Field '{field_name}' exceeds max length {max_len}")
        
        # Pattern check
        if field_type == "string" and "pattern" in field_constraints:
            pattern = field_constraints["pattern"]
            if not re.match(pattern, value):
                raise ValueError(f"Field '{field_name}' does not match pattern {pattern}")
        
        # Allowed values check
        if "allowed_values" in field_constraints:
            allowed = field_constraints["allowed_values"]
            if value not in allowed:
                raise ValueError(f"Field '{field_name}' must be one of {allowed}, got {value}")
        
        validated[field_name] = value
    
    return validated
