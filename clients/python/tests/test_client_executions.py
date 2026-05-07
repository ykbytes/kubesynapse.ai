from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kubesynapse.client import KubeSynapseClient


@pytest.mark.asyncio
async def test_list_executions_uses_live_route_and_envelope(monkeypatch) -> None:
    client = KubeSynapseClient()
    captured = {}

    async def fake_request(method: str, path: str, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {"items": [{"id": "exec-1"}], "limit": 50, "offset": 0}

    monkeypatch.setattr(client, "_request", fake_request)

    response = await client.list_executions(workflow_name="wf-a", limit=50)

    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/traces/executions"
    assert captured["kwargs"]["params"]["workflow_name"] == "wf-a"
    assert response.items == [{"id": "exec-1"}]


@pytest.mark.asyncio
async def test_legacy_trace_wrappers_delegate_to_execution_methods(monkeypatch) -> None:
    client = KubeSynapseClient()
    list_mock = AsyncMock(return_value="list-response")
    get_mock = AsyncMock(return_value="detail-response")
    monkeypatch.setattr(client, "list_executions", list_mock)
    monkeypatch.setattr(client, "get_execution", get_mock)

    listed = await client.list_traces(limit=10)
    detail = await client.get_trace("exec-1")

    list_mock.assert_awaited_once_with(workflow_name=None, limit=10, offset=0)
    get_mock.assert_awaited_once_with("exec-1")
    assert listed == "list-response"
    assert detail == "detail-response"