"""Tests for the HTTP trace client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from trace_client import TraceClient


class TestTraceClient:
    """Unit tests for TraceClient batching and flush behavior."""

    def test_start_execution_queues_event(self) -> None:
        """start_execution should queue an event without flushing immediately."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        with patch.object(client, "flush") as mock_flush:
            exec_id = client.start_execution(
                namespace="default",
                workflow_name="test-wf",
                agent_name="test-agent",
                run_id="run-1",
            )
            assert exec_id.startswith("exec-")
            assert len(client._buffer) == 1
            assert client._buffer[0]["event_type"] == "execution_started"
            mock_flush.assert_not_called()

    def test_end_execution_queues_event_and_flushes(self) -> None:
        """end_execution should queue an event and trigger flush."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        with patch.object(client, "flush") as mock_flush:
            client.end_execution("exec-123", status="completed", outputs={"result": "ok"})
            assert len(client._buffer) == 1
            assert client._buffer[0]["event_type"] == "execution_completed"
            mock_flush.assert_called_once()

    def test_end_execution_includes_full_metrics_payload(self) -> None:
        """end_execution should forward aggregate execution metrics unchanged."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        with patch.object(client, "flush") as mock_flush:
            client.end_execution(
                "exec-123",
                status="completed",
                outputs={"result": "ok"},
                metrics={
                    "total_steps": 3,
                    "completed_steps": 3,
                    "failed_steps": 0,
                    "total_llm_calls": 3,
                    "total_tool_calls": 7,
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "cost_usd": 0.0123,
                },
            )
            event = client._buffer[0]
            assert event["payload"]["metrics"]["total_tool_calls"] == 7
            assert event["payload"]["metrics"]["total_llm_calls"] == 3
            assert event["payload"]["metrics"]["total_tokens"] == 150
            assert event["payload"]["metrics"]["cost_usd"] == 0.0123
            mock_flush.assert_called_once()

    def test_record_tool_call_queues_event(self) -> None:
        """record_tool_call should queue an event."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        client.record_tool_call(
            execution_id="exec-123",
            step_id="step-1",
            tool_name="bash",
            tool_args={"cmd": "echo hi"},
            tool_result={"stdout": "hi"},
        )
        assert len(client._buffer) == 1
        assert client._buffer[0]["event_type"] == "tool_call_completed"

    def test_auto_flush_on_batch_size(self) -> None:
        """Flush should be triggered when buffer reaches batch_size."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=3, flush_interval_sec=60)
        with patch.object(client, "flush") as mock_flush:
            client.record_event("exec-1", "custom")
            client.record_event("exec-1", "custom")
            mock_flush.assert_not_called()
            client.record_event("exec-1", "custom")
            mock_flush.assert_called_once()

    def test_disabled_client_drops_events(self) -> None:
        """When disabled, no events should be queued."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=False)
        client.start_execution("default", "wf", "agent", "run-1")
        assert len(client._buffer) == 0

    def test_flush_posts_batch_via_httpx(self) -> None:
        """flush should POST buffered events to the gateway via _post_batch."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        client.record_event("exec-1", "custom", payload={"key": "value"})
        captured = client._buffer[:]

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.Client") as mock_client_cls:
            mock_http_client = MagicMock()
            mock_http_client.post.return_value = mock_response
            mock_client_cls.return_value.__enter__.return_value = mock_http_client
            client.flush()
            mock_http_client.post.assert_called_once()
            args, kwargs = mock_http_client.post.call_args
            assert args[0] == "http://gateway:8080/api/v1/traces/batch"
            sent = kwargs["json"]["events"]
            assert len(sent) == 1
            assert sent[0]["event_type"] == "custom"
            assert sent[0]["execution_id"] == "exec-1"
            assert sent[0]["payload"] == {"key": "value"}
            assert sent[0]["timestamp"] == pytest.approx(captured[0]["timestamp"], abs=1)

    def test_flush_clears_buffer(self) -> None:
        """After a successful flush, the buffer should be empty."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        client.record_event("exec-1", "custom")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.Client") as mock_client_cls:
            mock_http_client = MagicMock()
            mock_http_client.post.return_value = mock_response
            mock_client_cls.return_value.__enter__.return_value = mock_http_client
            client.flush()
            assert len(client._buffer) == 0

    def test_flush_failure_does_not_raise(self) -> None:
        """If the HTTP request fails, flush should log a warning and not raise."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        client.record_event("exec-1", "custom")

        with patch("httpx.Client") as mock_client_cls:
            mock_http_client = MagicMock()
            mock_http_client.post.side_effect = Exception("connection refused")
            mock_client_cls.return_value.__enter__.return_value = mock_http_client
            # Should not raise
            client.flush()
            # Buffer is cleared even on failure to avoid unbounded growth
            assert len(client._buffer) == 0

    def test_start_step_returns_step_id(self) -> None:
        """start_step should return a step ID and queue an event."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        step_id = client.start_step("exec-1", "step-name", step_type="agent", step_index=1)
        assert step_id.startswith("step-")
        assert any(e["event_type"] == "step_started" for e in client._buffer)

    def test_end_step_queues_event(self) -> None:
        """end_step should queue a step_completed event."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        client.end_step("exec-1", "step-123", status="completed")
        assert any(e["event_type"] == "step_completed" for e in client._buffer)

    def test_record_llm_call_queues_event(self) -> None:
        """record_llm_call should queue an LLM event with token metadata."""
        client = TraceClient(gateway_url="http://gateway:8080", enabled=True, batch_size=10, flush_interval_sec=60)
        client.record_llm_call(
            execution_id="exec-1",
            step_id="step-1",
            model="gpt-4",
            prompt="hello",
            response="world",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=0.0001,
            latency_ms=150.0,
            provider="openai",
        )
        event = client._buffer[0]
        assert event["event_type"] == "llm_call_completed"
        assert event["payload"]["model"] == "gpt-4"
        assert event["payload"]["prompt_tokens"] == 1
        assert event["payload"]["cost_usd"] == 0.0001
