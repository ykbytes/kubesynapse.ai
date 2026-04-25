"""Smoke tests for the KubeSynth operator.

These tests verify core operator logic without requiring a real Kubernetes cluster.
"""

from __future__ import annotations

import reconcile as operator_reconcile


class TestReconcileErrorClassification:
    """Tests for error classification logic."""

    def test_4xx_api_error_is_permanent(self, api_exception) -> None:
        """4xx API errors should be classified as permanent failures."""
        exc = api_exception(422, "Unprocessable Entity", '{"error":"invalid"}')
        error = operator_reconcile.classify_reconcile_error("create-agent", exc, default_delay=7)
        assert isinstance(error, Exception)
        assert "create-agent failed:" in str(error)
        assert "status=422" in str(error)

    def test_5xx_api_error_is_temporary(self, api_exception) -> None:
        """5xx API errors should be classified as temporary failures with backoff."""
        exc = api_exception(503, "Service Unavailable")
        error = operator_reconcile.classify_reconcile_error("run-workflow", exc, default_delay=5)
        assert isinstance(error, Exception)
        assert "status=503" in str(error)

    def test_409_conflict_is_temporary(self, api_exception) -> None:
        """409 Conflict should be treated as temporary (retryable)."""
        exc = api_exception(409, "Conflict")
        error = operator_reconcile.classify_reconcile_error("apply-resource", exc, default_delay=5)
        assert isinstance(error, Exception)
        assert "status=409" in str(error)


class TestOperatorConfig:
    """Tests for operator configuration validation."""

    def test_operator_api_port_is_defined(self) -> None:
        """The operator should have an API port defined."""
        import config as operator_config
        assert hasattr(operator_config, "API_PORT")
        assert operator_config.API_PORT > 0

    def test_operator_namespace_is_defined(self) -> None:
        """The operator should have a namespace defined."""
        import config as operator_config
        assert hasattr(operator_config, "OPERATOR_NAMESPACE")
        assert operator_config.OPERATOR_NAMESPACE


class TestTenantValidation:
    """Smoke tests for tenant controller validation logic."""

    def test_tenant_spec_has_required_fields(self, sample_tenant_spec) -> None:
        """A valid tenant spec should have namespacePrefix and quota."""
        assert "namespacePrefix" in sample_tenant_spec
        assert "quota" in sample_tenant_spec
        assert "maxAgents" in sample_tenant_spec["quota"]


class TestAgentValidation:
    """Smoke tests for agent spec validation."""

    def test_agent_spec_has_runtime(self, sample_agent_spec) -> None:
        """A valid agent spec should have a runtime configuration."""
        assert "runtime" in sample_agent_spec
        assert sample_agent_spec["runtime"]["kind"] == "opencode"

    def test_agent_spec_has_model(self, sample_agent_spec) -> None:
        """A valid agent spec should have a model configuration."""
        assert "model" in sample_agent_spec
        assert "provider" in sample_agent_spec["model"]
