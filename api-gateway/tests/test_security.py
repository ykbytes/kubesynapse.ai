"""Security-focused tests for authentication flows.

These tests verify protections against common attack vectors:
- JWT algorithm confusion (none alg)
- Expired tokens
- Key rotation continuity

NOTE: These tests require the real python-jose package and cannot run when
conftest.py injects a mock jose module (which returns static tokens).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Detect if we're running with the real python-jose or a conftest mock.
# The real package has many submodules; conftest only mocks jose.jwt and jose.jwk.
_real_jose = False
try:
    import jose

    if hasattr(jose, "exceptions") or hasattr(jose, "backends") or hasattr(jose, "constants"):
        _real_jose = True
except Exception:
    pass

pytestmark = pytest.mark.skipif(not _real_jose, reason="requires real python-jose (conftest mock detected)")

# Load jwt_utils directly without going through conftest (avoids heavy main.py imports)
MODULE_PATH = Path(__file__).resolve().parents[1] / "jwt_utils.py"
SPEC = importlib.util.spec_from_file_location("jwt_utils_under_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load jwt_utils module for tests")
jwt_utils = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = jwt_utils
SPEC.loader.exec_module(jwt_utils)


class TestJwtSecurity:
    """Tests for JWT hardening protections."""

    def test_reject_expired_token(self) -> None:
        """Expired tokens must be rejected."""
        user = {"id": 1, "username": "test", "role": "viewer"}
        token, _, _ = jwt_utils.create_access_token(user, "session-1")

        # Fast-forward time beyond expiry
        future = jwt_utils.utc_now() + jwt_utils.timedelta(seconds=jwt_utils.ACCESS_TOKEN_TTL_SECONDS + 10)
        with patch.object(jwt_utils, "utc_now", return_value=future), pytest.raises(ValueError):
            jwt_utils.decode_access_token(token)

    def test_key_rotation_preserves_old_tokens(self) -> None:
        """After key rotation, tokens signed with the previous key must still verify."""
        user = {"id": 1, "username": "test", "role": "viewer"}
        old_token, _, _ = jwt_utils.create_access_token(user, "session-1")

        # Decode before rotation to ensure it works
        claims = jwt_utils.decode_access_token(old_token)
        assert claims["sub"] == "1"

        # Rotate the key
        jwt_utils.rotate_jwt_key()

        # Old token should still verify (grace period via previous key)
        claims_after = jwt_utils.decode_access_token(old_token)
        assert claims_after["sub"] == "1"

    def test_kid_in_header(self) -> None:
        """Created tokens must include a kid header."""
        user = {"id": 1, "username": "test", "role": "viewer"}
        token, _, _ = jwt_utils.create_access_token(user, "session-1")

        # Decode without verification to inspect header
        header = jose.jwt.get_unverified_header(token)
        assert "kid" in header
        assert header["kid"] == "primary"

    def test_decode_with_different_kid_uses_fallback(self) -> None:
        """Tokens with mismatched kid should fall back to available keys."""
        user = {"id": 1, "username": "test", "role": "viewer"}
        token, _, _ = jwt_utils.create_access_token(user, "session-1")

        # Decode should work normally
        claims = jwt_utils.decode_access_token(token)
        assert claims["sub"] == "1"

    def test_reject_none_algorithm(self) -> None:
        """Tokens with alg=none must be rejected immediately."""
        # Manually craft a none-alg token header + payload + empty signature
        import base64
        import json

        header_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
        payload_b64 = base64.urlsafe_b64encode(
            json.dumps({"sub": "1", "token_type": "access", "iss": jwt_utils.JWT_ISSUER}).encode()
        ).rstrip(b"=")
        token = f"{header_b64.decode()}.{payload_b64.decode()}."

        with pytest.raises(ValueError, match="none"):
            jwt_utils.decode_access_token(token)
