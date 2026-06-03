"""Tests for webhook_security module — provider adapters, rate limit, auth, schema."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi import Request as FastAPIRequest

from webhook_security import (
    PROVIDER_VERIFIERS,
    check_webhook_concurrency,
    check_webhook_rate_limit,
    read_limited_body,
    release_webhook_concurrency,
    resolve_webhook_secret_with_key_id,
    sanitize_webhook_payload,
    validate_payload_against_schema,
    verify_provider_signature,
    verify_webhook_api_key,
    verify_webhook_timestamp,
)

# ============================================================================
# Provider signature verification
# ============================================================================


def _hmac_sig(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


class TestProviderVerifiers:
    SECRET = "whsec_test"

    def test_generic_hmac_valid(self) -> None:
        payload = b'{"event":"push"}'
        sig = _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("generic", payload, sig, self.SECRET) is True

    def test_generic_hmac_invalid(self) -> None:
        payload = b'{"event":"push"}'
        assert verify_provider_signature("generic", payload, "bad", self.SECRET) is False

    def test_generic_hmac_empty_secret(self) -> None:
        payload = b'{"event":"push"}'
        sig = _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("generic", payload, sig, "") is False

    def test_github_valid(self) -> None:
        payload = b'{"action":"opened"}'
        sig = "sha256=" + _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("github", payload, sig, self.SECRET) is True

    def test_github_wrong_prefix(self) -> None:
        payload = b'{"action":"opened"}'
        sig = _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("github", payload, sig, self.SECRET) is False

    def test_github_invalid(self) -> None:
        payload = b'{"action":"opened"}'
        assert verify_provider_signature("github", payload, "sha256=bad", self.SECRET) is False

    def test_slack_valid(self) -> None:
        timestamp = str(int(time.time()))
        payload = b'{"event":"message"}'
        basestring = f"v0:{timestamp}:{payload.decode()}"
        sig = "v0=" + _hmac_sig(basestring.encode(), self.SECRET)
        assert verify_provider_signature("slack", payload, sig, self.SECRET, timestamp=timestamp) is True

    def test_slack_missing_timestamp(self) -> None:
        payload = b'{"event":"message"}'
        sig = "v0=somevalue"
        assert verify_provider_signature("slack", payload, sig, self.SECRET) is False

    def test_slack_invalid(self) -> None:
        timestamp = str(int(time.time()))
        payload = b'{"event":"message"}'
        assert verify_provider_signature("slack", payload, "v0=bad", self.SECRET, timestamp=timestamp) is False

    def test_stripe_valid(self) -> None:
        payload = b'{"event":"charge.completed"}'
        sig = "v1=" + _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("stripe", payload, sig, self.SECRET) is True

    def test_stripe_multi_sig_valid(self) -> None:
        payload = b'{"event":"charge.completed"}'
        v1 = "v1=" + _hmac_sig(payload, self.SECRET)
        sig = f"t=1234567890,v0=old,{v1}"
        assert verify_provider_signature("stripe", payload, sig, self.SECRET) is True

    def test_stripe_invalid(self) -> None:
        payload = b'{"event":"charge.completed"}'
        assert verify_provider_signature("stripe", payload, "v1=bad", self.SECRET) is False

    def test_stripe_no_v1(self) -> None:
        payload = b'{"event":"charge.completed"}'
        assert verify_provider_signature("stripe", payload, "v0=old", self.SECRET) is False

    def test_pagerduty_valid(self) -> None:
        payload = b'{"event":"incident.triggered"}'
        sig = _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("pagerduty", payload, sig, self.SECRET) is True

    def test_pagerduty_invalid(self) -> None:
        payload = b'{"event":"incident.triggered"}'
        assert verify_provider_signature("pagerduty", payload, "bad", self.SECRET) is False

    def test_grafana_valid(self) -> None:
        payload = b'{"event":"alert.firing"}'
        sig = _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("grafana", payload, sig, self.SECRET) is True

    def test_unknown_provider_falls_back(self) -> None:
        payload = b'{"event":"unknown"}'
        sig = _hmac_sig(payload, self.SECRET)
        assert verify_provider_signature("nonexistent", payload, sig, self.SECRET) is True

    def test_unknown_provider_bad_sig(self) -> None:
        payload = b'{"event":"unknown"}'
        assert verify_provider_signature("nonexistent", payload, "bad", self.SECRET) is False

    def test_all_provider_verifiers_are_callable(self) -> None:
        for provider, verifier in PROVIDER_VERIFIERS.items():
            assert callable(verifier), f"{provider} verifier is not callable"


# ============================================================================
# Rate limiting
# ============================================================================


class TestRateLimiting:
    def test_allowed_within_limit(self) -> None:
        check_webhook_rate_limit("test-wh", limit=10, window_seconds=60)

    def test_blocked_exceeds_limit(self) -> None:
        webhook_key = "limit-test"
        limit = 3
        for _ in range(limit):
            check_webhook_rate_limit(webhook_key, limit=limit)
        with pytest.raises(HTTPException) as exc:
            check_webhook_rate_limit(webhook_key, limit=limit)
        assert exc.value.status_code == 429

    def test_different_keys_separate(self) -> None:
        limit = 2
        check_webhook_rate_limit("key-a", limit=limit)
        check_webhook_rate_limit("key-a", limit=limit)
        with pytest.raises(HTTPException):
            check_webhook_rate_limit("key-a", limit=limit)
        check_webhook_rate_limit("key-b", limit=limit)

    def test_zero_limit_blocks(self) -> None:
        with pytest.raises(HTTPException, match="Rate limit exceeded"):
            check_webhook_rate_limit("zero-limit", limit=0, window_seconds=60)

    @patch("webhook_security._get_redis_client")
    def test_redis_path_allowed(self, mock_get_redis) -> None:
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        check_webhook_rate_limit("redis-wh", limit=10)
        pipeline = mock_redis.pipeline.return_value
        pipeline.incr.assert_called_once()
        pipeline.expire.assert_called_once()
        pipeline.execute.assert_called_once()

    @patch("webhook_security._get_redis_client")
    def test_redis_path_blocked(self, mock_get_redis) -> None:
        mock_redis = MagicMock()
        mock_redis.get.return_value = "10"
        mock_get_redis.return_value = mock_redis
        with pytest.raises(HTTPException, match="Rate limit exceeded"):
            check_webhook_rate_limit("redis-wh", limit=10)

    @patch("webhook_security._get_redis_client")
    def test_redis_fallback_to_memory(self, mock_get_redis) -> None:
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("Redis down")
        mock_get_redis.return_value = mock_redis
        check_webhook_rate_limit("fallback-wh", limit=10)


# ============================================================================
# Concurrent invocation tracking
# ============================================================================


class TestConcurrency:
    def test_allow_within_limit(self) -> None:
        release_webhook_concurrency("conc-test")
        check_webhook_concurrency("conc-test", max_concurrent=5)
        release_webhook_concurrency("conc-test")

    def test_block_exceeds_limit(self) -> None:
        key = "conc-limit"
        max_c = 2
        check_webhook_concurrency(key, max_c)
        check_webhook_concurrency(key, max_c)
        with pytest.raises(HTTPException) as exc:
            check_webhook_concurrency(key, max_c)
        assert exc.value.status_code == 429
        release_webhook_concurrency(key)
        release_webhook_concurrency(key)
        check_webhook_concurrency(key, max_c)
        release_webhook_concurrency(key)

    def test_release_decrements(self) -> None:
        key = "conc-release"
        check_webhook_concurrency(key, max_concurrent=2)
        check_webhook_concurrency(key, max_concurrent=2)
        release_webhook_concurrency(key)
        check_webhook_concurrency(key, max_concurrent=2)
        release_webhook_concurrency(key)
        release_webhook_concurrency(key)

    def test_zero_max_disabled(self) -> None:
        check_webhook_concurrency("disabled", max_concurrent=0)

    def test_release_noop_on_empty(self) -> None:
        release_webhook_concurrency("nonexistent")


# ============================================================================
# Timestamp / replay protection
# ============================================================================


class TestTimestamp:
    def test_valid_timestamp(self) -> None:
        verify_webhook_timestamp(str(int(time.time())))

    def test_missing_header(self) -> None:
        with pytest.raises(HTTPException, match="Missing"):
            verify_webhook_timestamp(None)

    def test_invalid_format(self) -> None:
        with pytest.raises(HTTPException, match="Invalid"):
            verify_webhook_timestamp("not-a-number")

    def test_stale_timestamp(self) -> None:
        past = str(int(time.time()) - 1000)
        with pytest.raises(HTTPException, match="too old"):
            verify_webhook_timestamp(past, max_age_seconds=300)


# ============================================================================
# API key authentication
# ============================================================================


class TestApiKey:
    def test_valid_key(self) -> None:
        assert verify_webhook_api_key("my-secret-key", "my-secret-key") is True

    def test_invalid_key(self) -> None:
        assert verify_webhook_api_key("wrong-key", "my-secret-key") is False

    def test_missing_header(self) -> None:
        assert verify_webhook_api_key(None, "my-secret-key") is False

    def test_missing_stored(self) -> None:
        assert verify_webhook_api_key("some-key", None) is False

    def test_empty_key(self) -> None:
        assert verify_webhook_api_key("", "secret") is False


# ============================================================================
# Key rotation
# ============================================================================


class TestKeyRotation:
    @patch("webhook_security._resolve_k8s_secret")
    def test_primary_secret_used_when_no_key_id(self, mock_resolve) -> None:
        mock_resolve.return_value = "primary-secret"
        secret, kid = resolve_webhook_secret_with_key_id("ns/secret#key", None, None)
        assert secret == "primary-secret"
        assert kid is None

    @patch("webhook_security._resolve_k8s_secret")
    def test_additional_secret_by_key_id(self, mock_resolve) -> None:
        mock_resolve.return_value = "rotated-secret"
        additional = {"v2": "ns/rotated#key"}
        secret, kid = resolve_webhook_secret_with_key_id("ns/secret#key", additional, "v2")
        assert secret == "rotated-secret"
        assert kid == "v2"

    @patch("webhook_security._resolve_k8s_secret")
    def test_fallback_to_primary_when_key_id_missing(self, mock_resolve) -> None:
        mock_resolve.return_value = "primary-secret"
        additional = {"v1": "ns/old#key"}
        secret, kid = resolve_webhook_secret_with_key_id("ns/secret#key", additional, "nonexistent")
        assert secret == "primary-secret"
        assert kid is None

    @patch("webhook_security._resolve_k8s_secret")
    def test_fallback_to_primary_when_additional_empty(self, mock_resolve) -> None:
        mock_resolve.return_value = "primary-secret"
        secret, kid = resolve_webhook_secret_with_key_id("ns/secret#key", {}, "v2")
        assert secret == "primary-secret"
        assert kid is None


# ============================================================================
# Payload sanitization
# ============================================================================


class TestPayloadSanitization:
    def test_removes_dunder_keys(self) -> None:
        payload = {"__proto__": "polluted", "name": "safe"}
        result = sanitize_webhook_payload(payload)
        assert "__proto__" not in result
        assert result["name"] == "safe"

    def test_removes_nosql_keys(self) -> None:
        payload = {"$where": "danger", "$regex": ".*", "name": "safe"}
        result = sanitize_webhook_payload(payload)
        assert "$where" not in result
        assert "$regex" not in result
        assert result["name"] == "safe"

    def test_recursive_sanitization(self) -> None:
        payload = {"nested": {"__proto__": "polluted", "value": 1}}
        result = sanitize_webhook_payload(payload)
        assert "__proto__" not in result["nested"]
        assert result["nested"]["value"] == 1

    def test_depth_limit(self) -> None:
        deep = {}
        current = deep
        for _ in range(15):
            current["__proto__"] = {}
            current = current["__proto__"]
        result = sanitize_webhook_payload(deep)
        assert result == {}

    def test_non_dict_passthrough(self) -> None:
        assert sanitize_webhook_payload("string") == "string"
        assert sanitize_webhook_payload(123) == 123
        assert sanitize_webhook_payload(None) is None


# ============================================================================
# Payload schema validation
# ============================================================================


class TestSchemaValidation:
    def test_no_schema_returns_no_errors(self) -> None:
        assert validate_payload_against_schema({"a": 1}, None) == []

    def test_required_fields_present(self) -> None:
        schema = {"type": "object", "required": ["name", "event"]}
        payload = {"name": "test", "event": "push"}
        assert validate_payload_against_schema(payload, schema) == []

    def test_missing_required_field(self) -> None:
        schema = {"type": "object", "required": ["name", "event"]}
        payload = {"name": "test"}
        errors = validate_payload_against_schema(payload, schema)
        assert len(errors) == 1
        assert "Missing required field: 'event'" in errors[0]

    def test_type_string_valid(self) -> None:
        schema = {"properties": {"name": {"type": "string"}}}
        assert validate_payload_against_schema({"name": "hello"}, schema) == []

    def test_type_string_invalid(self) -> None:
        schema = {"properties": {"name": {"type": "string"}}}
        errors = validate_payload_against_schema({"name": 42}, schema)
        assert len(errors) == 1
        assert "must be a string" in errors[0]

    def test_type_integer_valid(self) -> None:
        schema = {"properties": {"count": {"type": "integer"}}}
        assert validate_payload_against_schema({"count": 5}, schema) == []

    def test_type_integer_invalid(self) -> None:
        schema = {"properties": {"count": {"type": "integer"}}}
        errors = validate_payload_against_schema({"count": "five"}, schema)
        assert len(errors) == 1
        assert "must be an integer" in errors[0]

    def test_type_boolean(self) -> None:
        schema = {"properties": {"active": {"type": "boolean"}}}
        assert validate_payload_against_schema({"active": True}, schema) == []
        errors = validate_payload_against_schema({"active": "yes"}, schema)
        assert len(errors) == 1
        assert "must be a boolean" in errors[0]

    def test_type_array(self) -> None:
        schema = {"properties": {"items": {"type": "array"}}}
        assert validate_payload_against_schema({"items": [1, 2]}, schema) == []
        errors = validate_payload_against_schema({"items": "not-array"}, schema)
        assert len(errors) == 1
        assert "must be an array" in errors[0]

    def test_type_object(self) -> None:
        schema = {"properties": {"meta": {"type": "object"}}}
        assert validate_payload_against_schema({"meta": {"k": "v"}}, schema) == []
        errors = validate_payload_against_schema({"meta": "string"}, schema)
        assert len(errors) == 1
        assert "must be an object" in errors[0]

    def test_pattern_match(self) -> None:
        schema = {"properties": {"email": {"type": "string", "pattern": r"^[a-z]+@example\.com$"}}}
        assert validate_payload_against_schema({"email": "user@example.com"}, schema) == []
        errors = validate_payload_against_schema({"email": "bad"}, schema)
        assert len(errors) == 1
        assert "pattern" in errors[0]

    def test_minimum_maximum(self) -> None:
        schema = {"properties": {"age": {"type": "integer", "minimum": 0, "maximum": 150}}}
        assert validate_payload_against_schema({"age": 30}, schema) == []
        errors_low = validate_payload_against_schema({"age": -1}, schema)
        assert len(errors_low) == 1
        errors_high = validate_payload_against_schema({"age": 200}, schema)
        assert len(errors_high) == 1
        assert "<= 150" in errors_high[0]

    def test_multiple_errors(self) -> None:
        schema = {"required": ["name", "age"], "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}}
        errors = validate_payload_against_schema({"name": 123}, schema)
        assert len(errors) == 2  # missing age + wrong name type

    def test_field_not_in_properties_still_validated_for_required(self) -> None:
        schema = {"required": ["status"]}
        errors = validate_payload_against_schema({}, schema)
        assert len(errors) == 1


# ============================================================================
# Body reading
# ============================================================================


@pytest.mark.asyncio
async def test_read_limited_body_within_limit() -> None:
    scope = {"type": "http", "method": "POST"}
    body = b"small payload"

    async def _receive():
        return {"type": "http.request", "body": body, "more_body": False}

    req = FastAPIRequest(scope, _receive)
    result = await read_limited_body(req, max_bytes=1024)
    assert result == body


@pytest.mark.asyncio
async def test_read_limited_body_exceeds_limit() -> None:
    scope = {"type": "http", "method": "POST"}
    body = b"x" * 5000

    async def _receive():
        return {"type": "http.request", "body": body, "more_body": False}

    req = FastAPIRequest(scope, _receive)
    with pytest.raises(HTTPException) as exc:
        await read_limited_body(req, max_bytes=100)
    assert exc.value.status_code == 413


# ============================================================================
# Client IP resolution
# ============================================================================


class TestClientIP:
    def test_resolve_direct_ip(self) -> None:
        scope = {"type": "http", "client": ("10.0.0.1", 54321), "headers": []}
        req = FastAPIRequest(scope, lambda: {})
        from webhook_security import resolve_trusted_client_ip
        assert resolve_trusted_client_ip(req) == "10.0.0.1"

    def test_resolve_forwarded_when_trusted(self) -> None:
        with patch.dict("os.environ", {"WEBHOOK_TRUST_PROXY": "true"}):
            scope = {"type": "http", "client": ("10.0.0.1", 54321), "headers": [
                (b"x-forwarded-for", b"203.0.113.5, 10.0.0.1"),
            ]}
            req = FastAPIRequest(scope, lambda: {})
            from webhook_security import resolve_trusted_client_ip
            assert resolve_trusted_client_ip(req) == "10.0.0.1"

    def test_resolve_forwarded_when_not_trusted(self) -> None:
        with patch.dict("os.environ", {"WEBHOOK_TRUST_PROXY": "false"}):
            scope = {"type": "http", "client": ("10.0.0.1", 54321), "headers": [
                (b"x-forwarded-for", b"203.0.113.5"),
            ]}
            req = FastAPIRequest(scope, lambda: {})
            from webhook_security import resolve_trusted_client_ip
            assert resolve_trusted_client_ip(req) == "10.0.0.1"

    def test_no_client_fallback(self) -> None:
        scope = {"type": "http", "headers": []}
        req = FastAPIRequest(scope, lambda: {})
        from webhook_security import resolve_trusted_client_ip
        assert resolve_trusted_client_ip(req) == "unknown"
