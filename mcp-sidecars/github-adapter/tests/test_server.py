import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        del args, kwargs

    def get(self, *args, **kwargs):
        del args, kwargs

        def decorator(func):
            return func

        return decorator

    def post(self, *args, **kwargs):
        del args, kwargs

        def decorator(func):
            return func

        return decorator


def _load_module():
    fastapi_module = types.ModuleType("fastapi")
    fastapi_module.FastAPI = _FakeFastAPI
    fastapi_module.HTTPException = _HTTPException
    fastapi_module.Header = lambda *args, **kwargs: None
    fastapi_module.status = types.SimpleNamespace(
        HTTP_400_BAD_REQUEST=400,
        HTTP_401_UNAUTHORIZED=401,
        HTTP_403_FORBIDDEN=403,
        HTTP_502_BAD_GATEWAY=502,
    )
    sys.modules["fastapi"] = fastapi_module

    mcp_module = types.ModuleType("mcp")
    mcp_module.ClientSession = object
    sys.modules["mcp"] = mcp_module

    mcp_client_http_module = types.ModuleType("mcp.client.streamable_http")
    mcp_client_http_module.streamablehttp_client = object
    sys.modules["mcp.client.streamable_http"] = mcp_client_http_module

    uvicorn_module = types.ModuleType("uvicorn")
    uvicorn_module.run = lambda *args, **kwargs: None
    sys.modules["uvicorn"] = uvicorn_module

    module_path = Path(__file__).resolve().parents[1] / "server.py"
    spec = importlib.util.spec_from_file_location("github_adapter_server", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load github adapter module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GitHubAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._original_env = dict(os.environ)
        os.environ["MCP_BEARER_TOKEN"] = "platform-token"
        self.module = _load_module()
        self.module.MCP_BEARER_TOKEN = "platform-token"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)

    async def test_call_tool_requires_forwarded_github_token(self) -> None:
        with self.assertRaises(self.module.HTTPException) as context:
            await self.module.call_tool(
                "search_repositories",
                {},
                authorization="Bearer platform-token",
                github_token=None,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("GitHub token", context.exception.detail)

    async def test_call_tool_forwards_result(self) -> None:
        with patch.object(self.module, "call_upstream_tool", AsyncMock(return_value={"items": ["repo-a"]})) as call_mock:
            result = await self.module.call_tool(
                "search_repositories",
                {"query": "kubemininions"},
                authorization="Bearer platform-token",
                github_token="ghp_test",
            )

        self.assertEqual(result, {"items": ["repo-a"]})
        call_mock.assert_awaited_once_with("search_repositories", {"query": "kubemininions"}, "ghp_test")

    def test_coerce_tool_result_prefers_structured_content(self) -> None:
        class _Result:
            structuredContent = {"ok": True}
            content = []
            isError = False

        self.assertEqual(self.module._coerce_tool_result(_Result()), {"ok": True})

    def test_coerce_tool_result_parses_single_text_json_payload(self) -> None:
        class _TextItem:
            type = "text"
            text = '{"repos": ["kubemininions"]}'

            def model_dump(self, exclude_none=True):
                del exclude_none
                return {"type": self.type, "text": self.text}

        class _Result:
            content = [_TextItem()]
            isError = False

        self.assertEqual(self.module._coerce_tool_result(_Result()), {"repos": ["kubemininions"]})