"""Tests for §security-R5 runtime identity binding.

These tests cover the new X-Runtime-Identity header validation path
that binds the shared api-gateway token to a specific agent + namespace.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

# Ensure consistent env state before importing auth_middleware
os.environ.setdefault("API_GATEWAY_SHARED_TOKEN", "test-shared-token")
os.environ.setdefault("API_GATEWAY_AUTH_MODE", "shared_token")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-tests")

from auth_middleware import (
    build_runtime_identity_principal,
    build_shared_token_principal,
    verify_shared_token,
    verify_shared_token_with_identity,
)

_SECRET = "test-runtime-identity-secret-32-bytes!"


def _make_identity_header(agent_name: str, namespace: str) -> str:
    digest = hmac.new(
        _SECRET.encode("utf-8"),
        f"{agent_name}:{namespace}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{agent_name}:{namespace}:{digest}"


def test_legacy_shared_token_principal_is_viewer_with_no_namespaces() -> None:
    """§security-R5: a bare shared token no longer escalates to admin.

    The default principal is now viewer/empty-namespaces, so a leaked
    shared token from a compromised runtime cannot reach admin endpoints.
    """
    principal = verify_shared_token("test-shared-token")
    assert principal["role"] == "viewer"
    assert principal["allowed_namespaces"] == []
    assert principal["auth_provider"] == "shared_token"


def test_legacy_build_shared_token_principal_is_viewer() -> None:
    principal = build_shared_token_principal()
    assert principal["role"] == "viewer"
    assert principal["allowed_namespaces"] == []


def test_runtime_identity_principal_scopes_to_single_namespace() -> None:
    principal = build_runtime_identity_principal(
        agent_name="agent-1",
        namespace="tenant-a",
    )
    assert principal["role"] == "operator"
    assert principal["allowed_namespaces"] == ["tenant-a"]
    assert principal["auth_provider"] == "runtime_identity"
    assert "tenant-a" in principal["sub"]
    assert "agent-1" in principal["sub"]


def test_shared_token_with_valid_identity_grants_operator() -> None:
    """When the X-Runtime-Identity header carries a valid HMAC, the
    shared token is bound to the named agent/namespace with operator role.
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        identity = _make_identity_header("agent-1", "tenant-a")
        principal = verify_shared_token_with_identity("test-shared-token", identity)
    assert principal["role"] == "operator"
    assert principal["allowed_namespaces"] == ["tenant-a"]


def test_shared_token_with_invalid_identity_returns_401() -> None:
    """A bad HMAC must NOT escalate. It returns 401 instead."""
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        bad_identity = "agent-1:tenant-a:" + "0" * 64
        with pytest.raises(HTTPException) as exc_info:
            verify_shared_token_with_identity("test-shared-token", bad_identity)
    assert exc_info.value.status_code == 401


def test_shared_token_with_malformed_identity_falls_back_to_viewer() -> None:
    """A malformed identity header (wrong number of colons, bad chars)
    is treated as missing — the legacy viewer principal is returned so
    a misconfigured caller can recover without 401-storming.
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        principal = verify_shared_token_with_identity(
            "test-shared-token",
            "this:is:not:a:valid:header",
        )
    assert principal["role"] == "viewer"
    assert principal["allowed_namespaces"] == []


def test_shared_token_with_missing_identity_when_secret_configured_falls_back() -> None:
    """If the secret is configured but no identity header is provided,
    the legacy viewer principal is returned. The api-gateway cannot
    silently upgrade a caller that doesn't present a valid identity.
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        principal = verify_shared_token_with_identity("test-shared-token", None)
    assert principal["role"] == "viewer"


def test_shared_token_with_identity_but_no_secret_falls_back() -> None:
    """When the api-gateway has no secret configured (first install), the
    legacy principal is returned. This preserves backward compatibility
    for environments that haven't yet rolled out the identity secret.
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": ""}):
        identity = _make_identity_header("agent-1", "tenant-a")
        principal = verify_shared_token_with_identity("test-shared-token", identity)
    assert principal["role"] == "viewer"


def test_shared_token_with_wrong_namespace_in_identity_is_rejected() -> None:
    """An identity claiming a different namespace than the HMAC was
    computed for must be rejected (caller is trying to spoof another
    agent's identity).
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        # HMAC computed for tenant-a, but header claims tenant-b
        digest = hmac.new(
            _SECRET.encode("utf-8"),
            b"agent-1:tenant-a",
            hashlib.sha256,
        ).hexdigest()
        forged = f"agent-1:tenant-b:{digest}"
        with pytest.raises(HTTPException) as exc_info:
            verify_shared_token_with_identity("test-shared-token", forged)
    assert exc_info.value.status_code == 401


def test_identity_header_rejects_invalid_characters() -> None:
    """The parser must reject agent_name/namespace containing colons,
    slashes, or other unsafe characters to prevent header smuggling.
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        # Try to inject extra header fields via the agent name
        bad_values = [
            "agent/1:tenant-a:" + "0" * 64,
            "agent 1:tenant-a:" + "0" * 64,
            "agent:1:tenant-a:" + "0" * 64,
            "agent\n1:tenant-a:" + "0" * 64,
        ]
        for bad in bad_values:
            principal = verify_shared_token_with_identity("test-shared-token", bad)
            assert principal["role"] == "viewer", f"Bad header was not rejected: {bad!r}"


def test_wrong_shared_token_always_rejected() -> None:
    """A wrong shared token must always be rejected, even with a valid
    identity claim. The identity only binds the token; it does not
    substitute for the bearer credential.
    """
    with patch.dict(os.environ, {"RUNTIME_IDENTITY_HMAC_SECRET": _SECRET}):
        identity = _make_identity_header("agent-1", "tenant-a")
        with pytest.raises(HTTPException) as exc_info:
            verify_shared_token_with_identity("wrong-shared-token", identity)
    assert exc_info.value.status_code == 401
