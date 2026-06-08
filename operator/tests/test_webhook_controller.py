"""Tests for the webhook controller — validation, dispatch, NATS, timer fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# Must import after conftest mocks are active
from controllers.webhook_controller import (
    _build_trigger_status,
    _build_webhook_status,
    _dispatch_to_agent,
    _dispatch_to_workflow,
    _gateway_fetch_pending_dispatches,
    _gateway_patch_execution_status,
    _process_nats_message,
    _validate_cidr,
    _validate_secret_ref,
    _validate_webhook_receiver_spec,
    _validate_workflow_trigger_spec,
)
from kubernetes.client.rest import ApiException as K8sApiException


def _make_k8s_exc(status: int = 404) -> K8sApiException:
    exc = K8sApiException(f"status={status}")
    exc.status = status
    return exc

# ============================================================================
# Validation helpers
# ============================================================================


class TestValidateSecretRef:
    def test_valid_secret_ref(self) -> None:
        _validate_secret_ref("namespace/name#key")

    def test_valid_secret_short(self) -> None:
        _validate_secret_ref("name#key")

    def test_empty_raises(self) -> None:
        with pytest.raises(Exception, match="required"):
            _validate_secret_ref("")

    def test_no_key_suffix_raises(self) -> None:
        with pytest.raises(Exception, match="#key"):
            _validate_secret_ref("namespace/name")


class TestValidateCIDR:
    def test_valid_cidr_v4(self) -> None:
        _validate_cidr("10.0.0.0/8")

    def test_valid_cidr_v6(self) -> None:
        _validate_cidr("::1/128")

    def test_single_ip(self) -> None:
        _validate_cidr("192.168.1.1/32")

    def test_invalid_cidr_raises(self) -> None:
        with pytest.raises(Exception, match="Invalid CIDR"):
            _validate_cidr("not-a-cidr")


class TestValidateWebhookReceiverSpec:
    def test_valid_spec(self) -> None:
        spec = {
            "secretRef": "ns/secret#key",
            "ipAllowlist": ["10.0.0.0/8"],
            "rateLimit": 100,
            "maxPayloadBytes": 1048576,
        }
        _validate_webhook_receiver_spec(spec)

    def test_empty_ip_allowlist(self) -> None:
        spec = {"secretRef": "ns/secret#key", "ipAllowlist": []}
        _validate_webhook_receiver_spec(spec)

    def test_invalid_cidr_in_allowlist(self) -> None:
        spec = {"secretRef": "ns/secret#key", "ipAllowlist": ["bad-cidr"]}
        with pytest.raises(Exception, match="Invalid CIDR"):
            _validate_webhook_receiver_spec(spec)

    def test_rate_limit_too_low(self) -> None:
        spec = {"secretRef": "ns/secret#key", "rateLimit": 0}
        with pytest.raises(Exception, match="rateLimit"):
            _validate_webhook_receiver_spec(spec)

    def test_max_payload_too_low(self) -> None:
        spec = {"secretRef": "ns/secret#key", "maxPayloadBytes": 0}
        with pytest.raises(Exception, match="maxPayloadBytes"):
            _validate_webhook_receiver_spec(spec)

    def test_missing_secret_ref(self) -> None:
        with pytest.raises(Exception, match="secretRef"):
            _validate_webhook_receiver_spec({})


class TestValidateWorkflowTriggerSpec:
    def test_valid_workflow_target(self) -> None:
        spec = {
            "sourceRef": "my-webhook",
            "sourceKind": "WebhookReceiver",
            "workflowRef": {"name": "my-workflow", "namespace": "default"},
        }
        with patch("kubernetes.client.CustomObjectsApi", create=True) as mock_api:
            mock_api.return_value.get_namespaced_custom_object.return_value = {"metadata": {}, "spec": {}}
            _validate_workflow_trigger_spec(spec, "default")

    def test_valid_agent_target(self) -> None:
        spec = {
            "sourceRef": "my-webhook",
            "sourceKind": "WebhookReceiver",
            "agentRef": {"name": "my-agent", "namespace": "default"},
        }
        with patch("kubernetes.client.CustomObjectsApi", create=True) as mock_api:
            mock_api.return_value.get_namespaced_custom_object.return_value = {"metadata": {}, "spec": {}}
            _validate_workflow_trigger_spec(spec, "default")

    def test_missing_source_ref(self) -> None:
        spec = {"sourceKind": "WebhookReceiver", "workflowRef": {"name": "w"}}
        with pytest.raises(Exception, match="sourceRef"):
            _validate_workflow_trigger_spec(spec, "default")

    def test_invalid_source_kind(self) -> None:
        spec = {"sourceRef": "r", "sourceKind": "InvalidKind", "workflowRef": {"name": "w"}}
        with pytest.raises(Exception, match="sourceKind"):
            _validate_workflow_trigger_spec(spec, "default")

    def test_missing_both_refs(self) -> None:
        spec = {"sourceRef": "r", "sourceKind": "WebhookReceiver"}
        with pytest.raises(Exception, match="Either"):
            _validate_workflow_trigger_spec(spec, "default")

    def test_workflow_not_found(self) -> None:
        spec = {
            "sourceRef": "r", "sourceKind": "WebhookReceiver",
            "workflowRef": {"name": "missing", "namespace": "default"},
        }
        with patch("kubernetes.client.CustomObjectsApi", create=True) as mock_api:
            mock_api.return_value.get_namespaced_custom_object.side_effect = _make_k8s_exc(404)
            with pytest.raises(Exception, match="not found"):
                _validate_workflow_trigger_spec(spec, "default")

    def test_agent_not_found(self) -> None:
        spec = {
            "sourceRef": "r", "sourceKind": "WebhookReceiver",
            "agentRef": {"name": "missing", "namespace": "default"},
        }
        with patch("kubernetes.client.CustomObjectsApi", create=True) as mock_api:
            mock_api.return_value.get_namespaced_custom_object.side_effect = _make_k8s_exc(404)
            with pytest.raises(Exception, match="not found"):
                _validate_workflow_trigger_spec(spec, "default")

    def test_negative_retry(self) -> None:
        spec = {
            "sourceRef": "r", "sourceKind": "WebhookReceiver",
            "workflowRef": {"name": "w"},
            "maxRetries": -1,
        }
        with pytest.raises(Exception, match="maxRetries"):
            _validate_workflow_trigger_spec(spec, "default")

    def test_negative_backoff(self) -> None:
        spec = {
            "sourceRef": "r", "sourceKind": "WebhookReceiver",
            "workflowRef": {"name": "w"},
            "backoffSeconds": -1,
        }
        with pytest.raises(Exception, match="backoffSeconds"):
            _validate_workflow_trigger_spec(spec, "default")


# ============================================================================
# Status builders
# ============================================================================


class TestStatusBuilders:
    def test_webhook_status_active(self) -> None:
        status = _build_webhook_status("Active", invocation_count=5)
        assert status["phase"] == "Active"
        assert status["invocationCount"] == 5
        assert "lastEvaluated" in status

    def test_webhook_status_no_count(self) -> None:
        status = _build_webhook_status("Active")
        assert "invocationCount" not in status

    def test_trigger_status_active(self) -> None:
        status = _build_trigger_status("Active", execution_count=10, failure_count=2)
        assert status["phase"] == "Active"
        assert status["executionCount"] == 10
        assert status["failureCount"] == 2

    def test_trigger_status_no_counts(self) -> None:
        status = _build_trigger_status("Active")
        assert "executionCount" not in status
        assert "failureCount" not in status


# ============================================================================
# Gateway HTTP helpers
# ============================================================================


class TestGatewayHttpHelpers:
    @patch("controllers.webhook_controller.urllib.request.urlopen")
    def test_patch_execution_success(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        assert _gateway_patch_execution_status(1, "processing") is True

    @patch("controllers.webhook_controller.urllib.request.urlopen")
    def test_patch_execution_failure(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = OSError("connection error")
        assert _gateway_patch_execution_status(1, "failed") is False

    @patch("controllers.webhook_controller.urllib.request.urlopen")
    def test_patch_with_error_message(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        _gateway_patch_execution_status(1, "failed", error_message="Something broke")
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data)
        assert body["status"] == "failed"
        assert body["error_message"] == "Something broke"

    @patch("controllers.webhook_controller.urllib.request.urlopen")
    def test_fetch_pending_success(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([{"id": 1, "status": "pending"}]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = _gateway_fetch_pending_dispatches(limit=10)
        assert len(result) == 1
        assert result[0]["id"] == 1

    @patch("controllers.webhook_controller.urllib.request.urlopen")
    def test_fetch_pending_empty(self, mock_urlopen) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        result = _gateway_fetch_pending_dispatches()
        assert result == []

    @patch("controllers.webhook_controller.urllib.request.urlopen")
    def test_fetch_pending_failure(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = OSError("timeout")
        result = _gateway_fetch_pending_dispatches()
        assert result == []


# ============================================================================
# Dispatch to workflow
# ============================================================================


class TestDispatchToWorkflow:
    @patch("controllers.workflow_controller.enqueue_workflow_job")
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    @patch("controllers.webhook_controller.kubernetes.client.CustomObjectsApi")
    def test_dispatches_job(self, mock_api_cls, mock_patch, mock_enqueue) -> None:
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {"metadata": {"generation": 3}, "spec": {"steps": []}}
        mock_api_cls.return_value = mock_api
        mock_enqueue.return_value = "job-abc"
        result, lineage = _dispatch_to_workflow(
            execution_id=1, workflow_name="wf1", workflow_namespace="ns1",
            trigger_namespace="ns1", trigger_name="tr1",
            logger=MagicMock(),
        )
        assert result == "job-abc"
        assert lineage["workflow_generation"] == 3
        assert lineage["job_name"] == "job-abc"
        mock_patch.assert_called_once()

    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    @patch("controllers.webhook_controller.kubernetes.client.CustomObjectsApi")
    def test_workflow_not_found(self, mock_api_cls, mock_patch) -> None:
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.side_effect = _make_k8s_exc(404)
        mock_api_cls.return_value = mock_api
        result, _lineage = _dispatch_to_workflow(
            execution_id=1, workflow_name="missing", workflow_namespace="ns1",
            trigger_namespace="ns1", trigger_name="tr1",
            logger=MagicMock(),
        )
        assert result is None
        mock_patch.assert_called_once()


# ============================================================================
# Dispatch to agent
# ============================================================================


class TestDispatchToAgent:
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    @patch("controllers.webhook_controller.kubernetes.client.CustomObjectsApi")
    def test_dispatches_agent(self, mock_api_cls, mock_patch) -> None:
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.return_value = {"metadata": {}, "spec": {}}
        mock_api_cls.return_value = mock_api
        result, lineage = _dispatch_to_agent(
            execution_id=1, agent_name="agent1", agent_namespace="ns1",
            trigger_namespace="ns1", trigger_name="tr1",
            payload={"event": "push"}, event_id="evt-1",
            logger=MagicMock(),
        )
        assert result == "webhook-evt-1"
        assert lineage["session_id"] == "webhook-evt-1"
        mock_patch.assert_called_once()

    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    @patch("controllers.webhook_controller.kubernetes.client.CustomObjectsApi")
    def test_agent_not_found(self, mock_api_cls, mock_patch) -> None:
        mock_api = MagicMock()
        mock_api.get_namespaced_custom_object.side_effect = _make_k8s_exc(404)
        mock_api_cls.return_value = mock_api
        result, _lineage = _dispatch_to_agent(
            execution_id=1, agent_name="missing", agent_namespace="ns1",
            trigger_namespace="ns1", trigger_name="tr1",
            payload={}, event_id="evt-1",
            logger=MagicMock(),
        )
        assert result is None
        mock_patch.assert_called_once()


# ============================================================================
# NATS message processing
# ============================================================================


class TestProcessNatsMessage:
    @patch("controllers.webhook_controller._gateway_claim_execution")
    @patch("controllers.webhook_controller._dispatch_to_workflow")
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    def test_process_workflow_message(self, mock_patch, mock_dispatch, mock_claim) -> None:
        mock_claim.return_value = True
        mock_dispatch.return_value = ("job-1", {"workflow_run_id": "run-1", "job_name": "job-1"})
        data = {
            "execution_id": 1, "namespace": "default", "trigger_name": "tr1",
            "target_kind": "workflow", "workflow_name": "wf1",
            "workflow_namespace": "default", "invocation_id": "inv-1",
        }
        _process_nats_message(data)
        mock_claim.assert_called_once_with(1, claim_source="nats")
        mock_dispatch.assert_called_once()

    @patch("controllers.webhook_controller._gateway_claim_execution")
    @patch("controllers.webhook_controller._dispatch_to_agent")
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    def test_process_agent_message(self, mock_patch, mock_dispatch, mock_claim) -> None:
        mock_claim.return_value = True
        mock_dispatch.return_value = ("webhook-evt-1", {"session_id": "webhook-evt-1"})
        data = {
            "execution_id": 2, "namespace": "default", "trigger_name": "tr2",
            "target_kind": "agent", "agent_name": "agent1",
            "agent_namespace": "default", "invocation_id": "inv-2",
            "payload": {"event": "push"},
        }
        _process_nats_message(data)
        mock_claim.assert_called_once_with(2, claim_source="nats")
        mock_dispatch.assert_called_once()

    @patch("controllers.webhook_controller._gateway_claim_execution")
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    def test_skip_missing_fields(self, mock_patch, mock_claim) -> None:
        _process_nats_message({})
        mock_claim.assert_not_called()
        mock_patch.assert_not_called()

        _process_nats_message({"execution_id": 1})
        mock_claim.assert_not_called()
        mock_patch.assert_not_called()

    @patch("controllers.webhook_controller._gateway_claim_execution")
    @patch("controllers.webhook_controller._dispatch_to_workflow")
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    def test_skip_if_claim_fails(self, mock_patch, mock_dispatch, mock_claim) -> None:
        """Claim returns False if already claimed by another consumer."""
        mock_claim.return_value = False
        data = {
            "execution_id": 3, "namespace": "default", "trigger_name": "tr3",
            "target_kind": "workflow", "workflow_name": "wf1",
            "workflow_namespace": "default", "invocation_id": "inv-3",
        }
        _process_nats_message(data)
        mock_claim.assert_called_once_with(3, claim_source="nats")
        mock_dispatch.assert_not_called()
        mock_patch.assert_not_called()

    @patch("controllers.webhook_controller._gateway_claim_execution")
    @patch("controllers.webhook_controller._dispatch_to_workflow")
    @patch("controllers.webhook_controller._gateway_patch_execution_status")
    def test_dispatch_exception_reported(self, mock_patch, mock_dispatch, mock_claim) -> None:
        mock_claim.return_value = True
        mock_dispatch.side_effect = RuntimeError("K8s API timeout")
        data = {
            "execution_id": 4, "namespace": "default", "trigger_name": "tr4",
            "target_kind": "workflow", "workflow_name": "wf1",
            "workflow_namespace": "default", "invocation_id": "inv-4",
            "payload": {},
        }
        _process_nats_message(data)
        mock_claim.assert_called_once_with(4, claim_source="nats")
        mock_dispatch.assert_called_once()
