"""Tests for agentctl.client — ApiClient request, error handling, pagination, SSE."""

from __future__ import annotations

import json

import httpx
import pytest

from agentctl.client import ApiClient, ApiError
from agentctl.config import ResolvedSettings


@pytest.fixture
def settings() -> ResolvedSettings:
    return ResolvedSettings(
        gateway_url="http://gateway:8080",
        token="my-token",
        namespace="test-ns",
        timeout=10.0,
        output_format="table",
    )


class TestApiClientConstruction:
    def test_sets_bearer_token_header(self, settings: ResolvedSettings) -> None:
        client = ApiClient(settings)
        assert client._client.headers["Authorization"] == "Bearer my-token"

    def test_accept_header(self, settings: ResolvedSettings) -> None:
        client = ApiClient(settings)
        assert client._client.headers["Accept"] == "application/json"

    def test_no_token_header_when_empty(self) -> None:
        settings = ResolvedSettings(
            gateway_url="http://gateway:8080",
            token="",
            namespace="test-ns",
            timeout=10.0,
            output_format="table",
        )
        client = ApiClient(settings)
        assert "Authorization" not in client._client.headers

    def test_base_url_strips_trailing_slash(self) -> None:
        settings = ResolvedSettings(
            gateway_url="http://gateway:8080/",
            token="",
            namespace="test-ns",
            timeout=10.0,
            output_format="table",
        )
        client = ApiClient(settings)
        # httpx normalizes base_url, but our code strips it too
        assert str(client._client.base_url).rstrip("/") == "http://gateway:8080"


class TestApiClientRequests:
    def test_get_sends_correct_method_and_path(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(method="GET", url="http://gateway:8080/api/agents", json=[{"name": "test"}])
        client = ApiClient(settings)
        data = client.get("/api/agents")
        assert data == [{"name": "test"}]

    def test_post_sends_json_payload(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(method="POST", url="http://gateway:8080/api/agents", json={"status": "created"})
        client = ApiClient(settings)
        data = client.post("/api/agents", payload={"name": "my-agent", "model": "gpt-4"})
        assert data == {"status": "created"}
        request = httpx_mock.get_request()
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"name": "my-agent", "model": "gpt-4"}

    def test_delete_returns_none_on_empty(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(method="DELETE", url="http://gateway:8080/api/agents/test", status_code=204)
        client = ApiClient(settings)
        data = client.delete("/api/agents/test")
        assert data is None

    def test_request_passes_params(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(method="GET", url="http://gateway:8080/api/agents?namespace=test-ns", json=[])
        client = ApiClient(settings)
        client.get("/api/agents", params={"namespace": "test-ns"})

    def test_put_method(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(method="PUT", url="http://gateway:8080/api/agents/test", json={"status": "updated"})
        client = ApiClient(settings)
        data = client.put("/api/agents/test", payload={"model": "gpt-4"})
        assert data == {"status": "updated"}

    def test_patch_method(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(method="PATCH", url="http://gateway:8080/api/agents/test", json={"status": "patched"})
        client = ApiClient(settings)
        data = client.patch("/api/agents/test", payload={"model": "gpt-4"})
        assert data == {"status": "patched"}

    def test_get_text_preserves_non_json_manifest(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/optimizations/candidates/cand-1/manifest",
            headers={"Content-Type": "application/yaml"},
            text="---\nkind: AgentWorkflow\n",
        )
        client = ApiClient(settings)

        content = client.get_text(
            "/api/optimizations/candidates/cand-1/manifest",
            accept="application/yaml",
        )

        assert content == "---\nkind: AgentWorkflow\n"
        request = httpx_mock.get_request()
        assert request.headers["Accept"] == "application/yaml"


class TestApiErrorHandling:
    def test_400_extracts_detail_string(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents",
            status_code=400,
            json={"detail": "Bad request"},
        )
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.get("/api/agents")
        assert "Bad request" in str(exc.value)
        assert exc.value.status_code == 400

    def test_404_extracts_message(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents/missing",
            status_code=404,
            json={"detail": "Agent not found"},
        )
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.get("/api/agents/missing")
        assert "Agent not found" in str(exc.value)
        assert exc.value.status_code == 404

    def test_validation_error_extracts_fields(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="POST",
            url="http://gateway:8080/api/agents",
            status_code=422,
            json={
                "detail": [
                    {"loc": ["body", "name"], "msg": "field required"},
                    {"loc": ["body", "model"], "msg": "field required"},
                ]
            },
        )
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.post("/api/agents", payload={})
        assert "body -> name" in str(exc.value)
        assert "body -> model" in str(exc.value)
        assert exc.value.status_code == 422

    def test_connection_error(self, settings: ResolvedSettings) -> None:
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.get("/api/agents")
        assert "Connection failed" in str(exc.value)

    def test_500_uses_text_fallback(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents",
            status_code=500,
            text="Internal Server Error",
        )
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.get("/api/agents")
        assert "Internal Server Error" in str(exc.value)

    def test_streamed_error_reads_body_before_decode(self, settings: ResolvedSettings, httpx_mock) -> None:
        """_raise_for_status handles streamed error responses without ResponseNotRead."""
        # Use httpx_mock to simulate a streaming error response
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents/missing",
            status_code=404,
            stream=httpx.ByteStream(b'{"detail":"Not Found"}'),
        )
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.get("/api/agents/missing")
        assert "Not Found" in str(exc.value)
        assert exc.value.status_code == 404

    def test_streamed_error_fallback_to_reason_phrase(self, settings: ResolvedSettings, httpx_mock) -> None:
        """_raise_for_status falls back to reason phrase when body is unreadable."""
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents/gone",
            status_code=410,
        )
        client = ApiClient(settings)
        with pytest.raises(ApiError) as exc:
            client.get("/api/agents/gone")
        assert exc.value.status_code == 410


class TestPagination:
    def test_paginate_single_page(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents?limit=100&offset=0",
            json=[{"name": "a"}, {"name": "b"}],
        )
        client = ApiClient(settings)
        items = client.paginate("/api/agents")
        assert len(items) == 2

    def test_paginate_multiple_pages(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents?limit=2&offset=0",
            json=[{"name": "a"}, {"name": "b"}],
        )
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents?limit=2&offset=2",
            json=[{"name": "c"}],
        )
        client = ApiClient(settings)
        items = client.paginate("/api/agents", page_size=2)
        assert len(items) == 3
        assert items[-1]["name"] == "c"

    def test_paginate_stops_when_results_under_limit(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/agents?limit=5&offset=0",
            json=[{"name": "a"}, {"name": "b"}],  # fewer than page_size
        )
        client = ApiClient(settings)
        items = client.paginate("/api/agents", page_size=5)
        assert len(items) == 2

    def test_paginate_dict_response_with_items_key(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/traces?limit=100&offset=0",
            json={"items": [{"id": "1"}, {"id": "2"}]},
        )
        client = ApiClient(settings)
        items = client.paginate("/api/traces")
        assert len(items) == 2

    def test_paginate_dict_response_with_results_key(self, settings: ResolvedSettings, httpx_mock) -> None:
        httpx_mock.add_response(
            method="GET",
            url="http://gateway:8080/api/search?limit=100&offset=0",
            json={"results": [{"id": "x"}]},
        )
        client = ApiClient(settings)
        items = client.paginate("/api/search")
        assert len(items) == 1


class TestSSEParsing:
    def test_iter_sse_parses_basic_event(self, settings: ResolvedSettings) -> None:
        lines = [
            "event: response.delta",
            "data: {\"delta\":\"Hello\"}",
            "",
        ]
        response = _make_stream_response("\n".join(lines))
        client = ApiClient(settings)
        events = list(client.iter_sse(response))
        assert len(events) == 1
        assert events[0]["event"] == "response.delta"
        assert events[0]["data"] == '{"delta":"Hello"}'

    def test_iter_sse_handles_multiple_events(self, settings: ResolvedSettings) -> None:
        lines = [
            "event: response.delta",
            "data: {\"delta\":\"Hello\"}",
            "",
            "event: response.completed",
            "data: {\"status\":\"done\"}",
            "",
        ]
        response = _make_stream_response("\n".join(lines))
        client = ApiClient(settings)
        events = list(client.iter_sse(response))
        assert len(events) == 2
        assert events[1]["event"] == "response.completed"

    def test_iter_sse_handles_multiline_data(self, settings: ResolvedSettings) -> None:
        lines = [
            "event: log.line",
            "data: line 1",
            "data: line 2",
            "",
        ]
        response = _make_stream_response("\n".join(lines))
        client = ApiClient(settings)
        events = list(client.iter_sse(response))
        assert len(events) == 1
        assert events[0]["data"] == "line 1\nline 2"

    def test_iter_sse_empty_stream(self, settings: ResolvedSettings) -> None:
        response = _make_stream_response("")
        client = ApiClient(settings)
        events = list(client.iter_sse(response))
        assert events == []


def _make_stream_response(text: str) -> httpx.Response:
    """Create a mock httpx.Response suitable for iter_lines()."""
    import io
    from httpx._transports.mock import MockTransport

    content = text.encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    transport = MockTransport(handler)
    client = httpx.Client(transport=transport)
    # We need a real response object that supports iter_lines
    response = httpx.Response(200, content=content)
    # Manually set the underlying transport to keep iter_lines working
    response._elapsed = 0.0
    response._request = httpx.Request("GET", "http://test")
    return response
