import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException


try:
    import jose  # noqa: F401
except ModuleNotFoundError:
    jose_module = types.ModuleType("jose")
    jose_module.jwk = types.SimpleNamespace(construct=lambda *_args, **_kwargs: None)
    jose_module.jwt = types.SimpleNamespace(
        get_unverified_header=lambda _token: {},
        get_unverified_claims=lambda _token: {},
    )
    jose_utils_module = types.ModuleType("jose.utils")
    jose_utils_module.base64url_decode = lambda value: value
    sys.modules["jose"] = jose_module
    sys.modules["jose.utils"] = jose_utils_module


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("api_gateway_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load api-gateway main module for tests")
api_gateway_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api_gateway_main
SPEC.loader.exec_module(api_gateway_main)


class GatewayRuntimeValidationTests(unittest.TestCase):
    def test_codex_agent_rejects_mcp_servers(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "codex"},
                    "mcpServers": ["github"],
                    "mcpSidecars": [],
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("mcp_servers", str(context.exception.detail))

    def test_codex_agent_allows_mcp_sidecars(self) -> None:
        api_gateway_main.validate_agent_runtime_compatibility(
            {
                "runtime": {"kind": "codex"},
                "mcpServers": [],
                "mcpSidecars": [{"name": "browser", "port": 8081}],
            }
        )

    def test_goose_agent_rejects_mcp_servers(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "goose"},
                    "mcpServers": ["github"],
                    "mcpSidecars": [],
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("mcp_servers", str(context.exception.detail))

    def test_goose_agent_rejects_mcp_sidecars(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "goose"},
                    "mcpServers": [],
                    "mcpSidecars": [{"name": "tool-bridge", "port": 8081}],
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("mcp_sidecars", str(context.exception.detail))

    def test_goose_invoke_rejects_unsupported_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            require_approval=True,
            tool_name="tool.run",
            mcp_server="github",
            sandbox_session={"id": "session-1"},
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("require_approval", str(context.exception.detail))
        self.assertIn("tool_name", str(context.exception.detail))
        self.assertIn("mcp_server", str(context.exception.detail))
        self.assertIn("sandbox_session", str(context.exception.detail))

    def test_goose_invoke_rejects_subagents(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="Coordinate the investigation",
            subagents=[{"name": "analysis-agent", "namespace": "team-b"}],
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("subagents", str(context.exception.detail))

    def test_goose_invoke_rejects_a2a_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
            a2a_timeout_seconds=15,
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("a2a_target", str(context.exception.detail))
        self.assertIn("a2a_timeout_seconds", str(context.exception.detail))

    def test_langgraph_invoke_keeps_extended_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            require_approval=True,
            tool_name="tool.run",
            mcp_server="github",
            sandbox_session={"id": "session-1"},
        )

        api_gateway_main.validate_invoke_runtime_compatibility("langgraph", request)

    def test_goose_invoke_allows_goose_run_controls(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            system="stay read-only",
            no_session=True,
            max_turns=12,
            debug=True,
            working_directory="nested/project",
            builtin_extensions=["developer"],
            stdio_extensions=["echo custom-tool"],
            streamable_http_extensions=["https://example.com/mcp"],
        )

        api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

    def test_goose_invoke_rejects_opencode_only_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            output_format="json",
            output_schema={"type": "object"},
            max_retries=2,
            autonomous=False,
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

        self.assertIn("output_format", str(context.exception.detail))
        self.assertIn("output_schema", str(context.exception.detail))
        self.assertIn("max_retries", str(context.exception.detail))
        self.assertIn("autonomous", str(context.exception.detail))

    def test_opencode_invoke_allows_opencode_only_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            output_format="json",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_retries=2,
            structured_output_retry_count=3,
            autonomous=False,
        )

        api_gateway_main.validate_invoke_runtime_compatibility("opencode", request)

    def test_goose_invoke_rejects_structured_output_retry_count(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            structured_output_retry_count=3,
        )
        with self.assertRaises(HTTPException) as ctx:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("structured_output_retry_count", ctx.exception.detail)

    def test_delete_is_allowed_for_cors(self) -> None:
        cors_middleware = next(
            middleware
            for middleware in api_gateway_main.app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        )

        self.assertIn("DELETE", cors_middleware.kwargs["allow_methods"])

    def test_invoke_request_normalizes_whitespace(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="  hello  ",
            thread_id="   ",
            model="  ",
            system="   ",
            approval_action="   ",
            tool_name="  ",
            mcp_server="   ",
            a2a_target_agent=" analysis-agent ",
            a2a_target_namespace=" team-b ",
            working_directory="  nested/project  ",
            builtin_extensions=[" developer ", "   "],
            stdio_extensions=[" echo tool ", "   "],
            streamable_http_extensions=[" https://example.com/mcp ", "   "],
            subagent_strategy=" Parallel ",
        )

        self.assertEqual(request.prompt, "hello")
        self.assertIsNone(request.thread_id)
        self.assertIsNone(request.model)
        self.assertIsNone(request.system)
        self.assertIsNone(request.approval_action)
        self.assertEqual(request.tool_name, "")
        self.assertIsNone(request.mcp_server)
        self.assertEqual(request.a2a_target_agent, "analysis-agent")
        self.assertEqual(request.a2a_target_namespace, "team-b")
        self.assertEqual(request.working_directory, "nested/project")
        self.assertEqual(request.builtin_extensions, ["developer"])
        self.assertEqual(request.stdio_extensions, ["echo tool"])
        self.assertEqual(request.streamable_http_extensions, ["https://example.com/mcp"])
        self.assertEqual(request.subagent_strategy, "parallel")

    def test_invoke_request_requires_complete_a2a_target(self) -> None:
        with self.assertRaises(ValueError):
            api_gateway_main.InvokeRequest(prompt="hello", a2a_target_agent="analysis-agent")


class WorkflowSchemaTests(unittest.TestCase):
    def test_build_workflow_spec_preserves_context_and_review_fields(self) -> None:
        body = api_gateway_main.WorkflowRequest(
            name="feature-pipeline",
            description="desc",
            input="input",
            context_ref="project-rules",
            steps=[
                api_gateway_main.WorkflowStepRequest(
                    name="implement",
                    agent_ref="dev-agent",
                    prompt="Implement it",
                    verify="Run tests and report PASS or FAIL",
                ),
                api_gateway_main.WorkflowStepRequest(
                    name="review",
                    agent_ref="reviewer-agent",
                    step_type="review",
                    review_criteria="Code quality",
                    depends_on=["implement"],
                ),
            ],
        )

        spec = api_gateway_main.build_workflow_spec(body)

        self.assertEqual(spec["contextRef"], "project-rules")
        self.assertEqual(spec["steps"][0]["verify"], "Run tests and report PASS or FAIL")
        self.assertEqual(spec["steps"][1]["type"], "review")
        self.assertEqual(spec["steps"][1]["reviewCriteria"], "Code quality")

    def test_workflow_info_from_resource_maps_new_fields(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default", "creationTimestamp": "2026-03-19T00:00:00Z"},
            "spec": {
                "description": "desc",
                "input": "input",
                "contextRef": "project-rules",
                "messageBus": "in-memory",
                "steps": [
                    {
                        "name": "implement",
                        "agentRef": "dev-agent",
                        "prompt": "Implement",
                        "verify": "Run tests",
                    },
                    {
                        "name": "review",
                        "agentRef": "reviewer-agent",
                        "type": "review",
                        "reviewCriteria": "Code quality",
                        "dependsOn": ["implement"],
                    },
                ],
            },
            "status": {"phase": "running", "currentStep": "review"},
        }

        info = api_gateway_main.workflow_info_from_resource(workflow)

        self.assertEqual(info.context_ref, "project-rules")
        self.assertEqual(info.steps[0].verify, "Run tests")
        self.assertEqual(info.steps[1].step_type, "review")
        self.assertEqual(info.steps[1].review_criteria, "Code quality")

    def test_parse_json_object_response_rejects_invalid_json(self) -> None:
        response = httpx.Response(200, text="not-json")

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_json_object_response(response, context="Agent runtime /invoke")

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("invalid JSON", str(context.exception.detail))

    def test_parse_json_object_response_rejects_non_object_payload(self) -> None:
        response = httpx.Response(200, json=["not", "an", "object"])

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_json_object_response(response, context="Agent runtime /invoke")

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("non-object", str(context.exception.detail))

    def test_error_payload_from_body_prefers_detail_field(self) -> None:
        payload = api_gateway_main.error_payload_from_body(
            json.dumps({"detail": "runtime cold start"}).encode("utf-8"),
            "fallback",
        )

        self.assertEqual(payload, {"error": "runtime cold start"})

    def test_parse_goose_config_files_normalizes_relative_paths(self) -> None:
        parsed = api_gateway_main.parse_goose_config_files(
            {
                " config.yaml ": {"GOOSE_MODE": "smart_approve"},
                "prompts\\review.md": "Review conservatively.",
            },
            source="goose_config_files",
        )

        self.assertEqual(
            parsed,
            {
                "config.yaml": {"GOOSE_MODE": "smart_approve"},
                "prompts/review.md": "Review conservatively.",
            },
        )

    def test_parse_goose_config_files_rejects_runtime_managed_paths(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_goose_config_files(
                {"permissions/tool_permissions.json": {}},
                source="goose_config_files",
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("permissions", str(context.exception.detail))

    def test_parse_opencode_config_files_normalizes_relative_paths(self) -> None:
        parsed = api_gateway_main.parse_opencode_config_files(
            {
                " opencode.json ": {"default_agent": "build"},
                "plugins\\notify.ts": "export const NotifyPlugin = async () => ({})",
            },
            source="opencode_config_files",
        )

        self.assertEqual(
            parsed,
            {
                "opencode.json": {"default_agent": "build"},
                "plugins/notify.ts": "export const NotifyPlugin = async () => ({})",
            },
        )

    def test_parse_agent_skills_config_normalizes_markdown_paths(self) -> None:
        parsed = api_gateway_main.parse_agent_skills_config(
            {
                "files": {
                    " .github\\skills\\reviewer\\SKILL.md ": "---\nname: reviewer\n---\nReview carefully.\n",
                }
            },
            source="skills",
            strict=True,
        )

        self.assertEqual(
            parsed,
            {
                "files": {
                    ".github/skills/reviewer/SKILL.md": "---\nname: reviewer\n---\nReview carefully.\n",
                }
            },
        )

    def test_parse_agent_skills_config_rejects_non_markdown_paths(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_agent_skills_config(
                {"files": {".github/skills/reviewer/config.yaml": "name: reviewer"}},
                source="skills",
                strict=True,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn(".md", str(context.exception.detail))

    def test_build_agent_spec_includes_goose_config_files(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="goose-agent",
            model="gpt-4",
            runtime_kind="goose",
            goose_config_files={"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(spec["runtime"]["kind"], "goose")
        self.assertEqual(
            spec["runtime"]["goose"]["configFiles"],
            {"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

    def test_build_agent_spec_includes_opencode_config_files(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            opencode_config_files={"opencode.json": {"default_agent": "build"}},
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(spec["runtime"]["kind"], "opencode")
        self.assertEqual(
            spec["runtime"]["opencode"]["configFiles"],
            {"opencode.json": {"default_agent": "build"}},
        )

    def test_build_agent_spec_includes_a2a_config(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="langgraph-agent",
            model="gpt-4",
            a2a_config={
                "allowed_callers": [
                    {"name": "research-agent", "namespace": "team-a"},
                ]
            },
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(
            spec["a2a"],
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_build_agent_spec_includes_skill_files(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="langgraph-agent",
            model="gpt-4",
            skills={
                "files": {
                    ".github/skills/research/SKILL.md": (
                        "---\n"
                        "name: research\n"
                        "description: Gather evidence carefully.\n"
                        "allowedSandboxTools:\n"
                        "  - sandbox.filesystem.read\n"
                        "---\n"
                        "Read source material before answering.\n"
                    )
                }
            },
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertIn("skills", spec)
        self.assertIn(".github/skills/research/SKILL.md", spec["skills"]["files"])

    def test_build_agent_spec_preserves_existing_a2a_config_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "a2a": {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
                "runtime": {"kind": "langgraph"},
            },
        )

        self.assertEqual(
            spec["a2a"],
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_build_agent_spec_preserves_existing_goose_config_files_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "runtime": {
                    "kind": "goose",
                    "goose": {"configFiles": {"config.yaml": {"GOOSE_MODE": "smart_approve"}}},
                },
            },
        )

        self.assertEqual(spec["runtime"]["kind"], "goose")
        self.assertEqual(
            spec["runtime"]["goose"]["configFiles"],
            {"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

    def test_build_agent_spec_preserves_existing_opencode_config_files_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "runtime": {
                    "kind": "opencode",
                    "opencode": {"configFiles": {"opencode.json": {"default_agent": "build"}}},
                },
            },
        )

        self.assertEqual(spec["runtime"]["kind"], "opencode")
        self.assertEqual(
            spec["runtime"]["opencode"]["configFiles"],
            {"opencode.json": {"default_agent": "build"}},
        )

    def test_build_agent_spec_preserves_existing_skills_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "skills": {
                    "files": {
                        ".github/skills/research/SKILL.md": "---\nname: research\n---\nRead first.\n",
                    }
                },
            },
        )

        self.assertEqual(
            spec["skills"],
            {
                "files": {
                    ".github/skills/research/SKILL.md": "---\nname: research\n---\nRead first.\n",
                }
            },
        )

    def test_build_agent_spec_rejects_goose_config_files_for_langgraph(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="langgraph-agent",
            model="gpt-4",
            runtime_kind="langgraph",
            goose_config_files={"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.build_agent_spec(request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("runtime_kind", str(context.exception.detail))

    def test_build_agent_spec_rejects_opencode_config_files_for_langgraph(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="langgraph-agent",
            model="gpt-4",
            runtime_kind="langgraph",
            opencode_config_files={"opencode.json": {"default_agent": "build"}},
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.build_agent_spec(request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("runtime_kind", str(context.exception.detail))

    def test_agent_detail_from_resource_exposes_goose_config_files(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "goose-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "systemPrompt": "stay read-only",
                    "runtime": {
                        "kind": "goose",
                        "goose": {"configFiles": {"config.yaml": {"GOOSE_MODE": "smart_approve"}}},
                    },
                },
            }
        )

        self.assertEqual(detail.goose_config_files, {"config.yaml": {"GOOSE_MODE": "smart_approve"}})

    def test_agent_detail_from_resource_exposes_opencode_config_files(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "opencode-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "systemPrompt": "stay precise",
                    "runtime": {
                        "kind": "opencode",
                        "opencode": {"configFiles": {"opencode.json": {"default_agent": "build"}}},
                    },
                },
            }
        )

        self.assertEqual(detail.opencode_config_files, {"opencode.json": {"default_agent": "build"}})

    def test_agent_detail_from_resource_exposes_a2a_config(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "langgraph-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "a2a": {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
                    "runtime": {"kind": "langgraph"},
                },
            }
        )

        self.assertEqual(
            detail.a2a_config,
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_agent_detail_from_resource_exposes_skill_summaries(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "langgraph-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "runtime": {"kind": "langgraph"},
                    "skills": {
                        "files": {
                            ".github/skills/research/SKILL.md": (
                                "---\n"
                                "name: research\n"
                                "description: Gather evidence carefully.\n"
                                "allowedSandboxTools:\n"
                                "  - sandbox.filesystem.read\n"
                                "allowedA2ATargets:\n"
                                "  - name: analysis-agent\n"
                                "    namespace: team-b\n"
                                "allowSubagents: true\n"
                                "---\n"
                                "Read source material before answering.\n"
                            )
                        }
                    },
                },
            }
        )

        self.assertEqual(set(detail.skills["files"].keys()), {".github/skills/research/SKILL.md"})
        self.assertEqual(len(detail.skill_summaries), 1)
        self.assertEqual(detail.skill_summaries[0]["name"], "research")
        self.assertEqual(detail.skill_summaries[0]["allowed_sandbox_tools"], ["sandbox.filesystem.read"])
        self.assertEqual(
            detail.skill_summaries[0]["allowed_a2a_targets"],
            [{"name": "analysis-agent", "namespace": "team-b"}],
        )
        self.assertTrue(detail.skill_summaries[0]["allow_subagents"])


class GatewayToolCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_sidecar_catalog_cache = api_gateway_main._MCP_SIDECAR_CATALOG_CACHE
        api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None

    def tearDown(self) -> None:
        api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = self._original_sidecar_catalog_cache

    def test_catalog_image_resolution_uses_fully_qualified_image(self) -> None:
        with patch.dict(
            api_gateway_main.os.environ,
            {
                "MCP_SIDECAR_CATALOG_JSON": json.dumps(
                    {"codeExec": {"image": "docker.io/yakdhane/mcp-code-exec:v2", "port": 8090}}
                )
            },
            clear=False,
        ):
            api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None
            self.assertEqual(
                api_gateway_main._resolve_sidecar_image("code-exec"),
                "docker.io/yakdhane/mcp-code-exec:v2",
            )

    def test_tool_categories_prefer_catalog_port_over_default_port(self) -> None:
        with patch.dict(
            api_gateway_main.os.environ,
            {
                "MCP_SIDECAR_CATALOG_JSON": json.dumps(
                    {"codeExec": {"image": "docker.io/yakdhane/mcp-code-exec:v2", "port": 9012}}
                )
            },
            clear=False,
        ):
            api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None
            categories = api_gateway_main.get_tool_categories(user=None)

        code_exec = next(tool for tool in categories if tool["id"] == "code-exec")
        self.assertEqual(code_exec["default_port"], 9012)
        self.assertEqual(code_exec["sidecar_image"], "docker.io/yakdhane/mcp-code-exec:v2")

    def test_tool_categories_fallback_to_default_port_when_catalog_port_missing_or_invalid(self) -> None:
        test_cases = [
            {"name": "missing", "catalog": {"codeExec": {"image": "docker.io/yakdhane/mcp-code-exec:v2"}}},
            {
                "name": "invalid",
                "catalog": {"codeExec": {"image": "docker.io/yakdhane/mcp-code-exec:v2", "port": "invalid"}},
            },
        ]

        for test_case in test_cases:
            with self.subTest(name=test_case["name"]), patch.dict(
                api_gateway_main.os.environ,
                {"MCP_SIDECAR_CATALOG_JSON": json.dumps(test_case["catalog"])},
                clear=False,
            ):
                api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None
                categories = api_gateway_main.get_tool_categories(user=None)

            code_exec = next(tool for tool in categories if tool["id"] == "code-exec")
            self.assertEqual(code_exec["default_port"], 8090)
            self.assertEqual(code_exec["sidecar_image"], "docker.io/yakdhane/mcp-code-exec:v2")


class GatewayAgentDiscoveryTests(unittest.TestCase):
    def test_discover_agent_peers_reports_reachable_and_blocked_targets(self) -> None:
        caller_agent = {
            "metadata": {"name": "planner", "namespace": "default"},
            "spec": {
                "model": "gpt-4",
                "policyRef": "planner-policy",
                "runtime": {"kind": "langgraph"},
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                        {"name": "reviewer", "namespace": "team-b"},
                        {"name": "missing", "namespace": "team-c"},
                    ]
                }
            }
        }
        researcher_agent = {
            "metadata": {"name": "researcher", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o",
                "runtime": {"kind": "langgraph"},
                "a2a": {"allowedCallers": [{"name": "planner", "namespace": "default"}]},
            },
        }
        reviewer_agent = {
            "metadata": {"name": "reviewer", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o-mini",
                "runtime": {"kind": "goose"},
                "a2a": {"allowedCallers": [{"name": "someone-else", "namespace": "default"}]},
            },
        }

        def fake_read_agent(name: str, namespace: str) -> dict[str, object]:
            if (namespace, name) == ("default", "planner"):
                return caller_agent
            if (namespace, name) == ("team-b", "researcher"):
                return researcher_agent
            if (namespace, name) == ("team-b", "reviewer"):
                return reviewer_agent
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        def fake_get_agent_status(name: str, namespace: str) -> str:
            if (namespace, name) == ("team-b", "researcher"):
                return "running"
            if (namespace, name) == ("team-b", "reviewer"):
                return "running"
            return "unknown"

        with patch.object(api_gateway_main, "read_agent", side_effect=fake_read_agent), patch.object(
            api_gateway_main,
            "read_custom_resource",
            return_value=policy,
        ), patch.object(api_gateway_main, "get_agent_status", side_effect=fake_get_agent_status):
            response = api_gateway_main.discover_agent_peers("planner", "default")

        self.assertEqual(response.agent_name, "planner")
        self.assertEqual(response.policy_ref, "planner-policy")
        self.assertEqual(len(response.peers), 3)
        self.assertTrue(response.peers[0].reachable)
        self.assertEqual(response.peers[0].name, "researcher")
        self.assertEqual(response.peers[0].runtime_kind, "langgraph")
        self.assertFalse(response.peers[1].reachable)
        self.assertFalse(response.peers[1].accepts_caller)
        self.assertIn("allowedCallers", response.peers[1].reason or "")
        self.assertFalse(response.peers[2].exists)
        self.assertEqual(response.peers[2].reason, "Target agent does not exist.")

    def test_discover_agent_peers_marks_non_running_target_unreachable(self) -> None:
        caller_agent = {
            "metadata": {"name": "planner", "namespace": "default"},
            "spec": {
                "model": "gpt-4",
                "policyRef": "planner-policy",
                "runtime": {"kind": "langgraph"},
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                    ]
                }
            }
        }
        researcher_agent = {
            "metadata": {"name": "researcher", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o",
                "runtime": {"kind": "langgraph"},
                "a2a": {"allowedCallers": [{"name": "planner", "namespace": "default"}]},
            },
        }

        def fake_read_agent(name: str, namespace: str) -> dict[str, object]:
            if (namespace, name) == ("default", "planner"):
                return caller_agent
            if (namespace, name) == ("team-b", "researcher"):
                return researcher_agent
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        with patch.object(api_gateway_main, "read_agent", side_effect=fake_read_agent), patch.object(
            api_gateway_main,
            "read_custom_resource",
            return_value=policy,
        ), patch.object(api_gateway_main, "get_agent_status", return_value="pending"):
            response = api_gateway_main.discover_agent_peers("planner", "default")

        self.assertFalse(response.peers[0].reachable)
        self.assertEqual(response.peers[0].status, "pending")
        self.assertIn("status is 'pending'", response.peers[0].reason or "")


class GatewayA2AProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def tearDown(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def test_build_agent_card_exposes_jsonrpc_interface_and_skills(self) -> None:
        agent = {
            "metadata": {
                "name": "planner",
                "namespace": "default",
                "creationTimestamp": "2026-03-11T00:00:00Z",
                "generation": 7,
            },
            "spec": {
                "model": "gpt-4o",
                "systemPrompt": "Plan research tasks and delegate specialized work when needed.",
                "policyRef": "planner-policy",
                "runtime": {"kind": "langgraph"},
                "mcpServers": ["github"],
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                    ]
                }
            }
        }

        with patch.object(api_gateway_main, "read_agent", return_value=agent), patch.object(
            api_gateway_main,
            "get_agent_status",
            return_value="running",
        ), patch.object(api_gateway_main, "read_custom_resource", return_value=policy):
            card = api_gateway_main.build_agent_card(
                "planner",
                "default",
                types.SimpleNamespace(base_url="http://gateway.local/"),
            )

        self.assertEqual(card["name"], "planner")
        self.assertEqual(card["url"], "http://gateway.local/a2a/planner?namespace=default")
        self.assertEqual(card["protocolVersion"], api_gateway_main.A2A_PROTOCOL_VERSION)
        self.assertEqual(card["preferredTransport"], "JSONRPC")
        self.assertEqual(card["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")
        self.assertEqual(card["supportedInterfaces"][0]["tenant"], "default")
        self.assertTrue(card["capabilities"]["streaming"])
        self.assertFalse(card["capabilities"]["pushNotifications"])
        self.assertEqual(card["version"], "1.0.7")
        self.assertTrue(any(skill["id"] == "peer-delegation" for skill in card["skills"]))
        self.assertTrue(any(skill["id"] == "mcp-github" for skill in card["skills"]))


class GatewayA2AProtocolAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def tearDown(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    async def test_handle_a2a_send_message_returns_completed_task_and_supports_get(self) -> None:
        invoke_response = api_gateway_main.InvokeResponse(
            agent_name="planner",
            response="Delegated summary",
            thread_id="ctx-123",
            model="gpt-4o",
            status="completed",
        )

        with patch.object(api_gateway_main, "invoke_agent", AsyncMock(return_value=invoke_response)):
            response = await api_gateway_main.handle_a2a_send_message(
                "planner",
                "default",
                {
                    "message": {
                        "messageId": "msg-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Summarize the research"}],
                    }
                },
                "req-1",
                "gateway-req-1",
            )

        task = response["result"]["task"]
        self.assertEqual(task["kind"], "task")
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(task["history"][0]["kind"], "message")
        self.assertEqual(task["history"][0]["parts"][0]["kind"], "text")
        self.assertEqual(task["artifacts"][0]["parts"][0]["text"], "Delegated summary")
        self.assertEqual(task["artifacts"][0]["kind"], "artifact")
        self.assertEqual(task["artifacts"][0]["parts"][0]["kind"], "text")
        self.assertEqual(len(task["history"]), 2)

        get_response = api_gateway_main.handle_a2a_get_task(
            "planner",
            "default",
            {"id": task["id"], "historyLength": 1},
            "req-2",
        )

        fetched_task = get_response["result"]["task"]
        self.assertEqual(fetched_task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(len(fetched_task["history"]), 1)
        self.assertEqual(fetched_task["artifacts"][0]["parts"][0]["text"], "Delegated summary")

    async def test_handle_a2a_stream_message_translates_runtime_events(self) -> None:
        async def upstream_events():
            yield 'event: response.delta\ndata: {"delta": "Hel"}\n\n'
            yield 'event: response.delta\ndata: {"delta": "lo"}\n\n'
            yield 'event: response.completed\ndata: {"status": "completed", "policy_name": "strict-enterprise-policy"}\n\n'

        async def fake_invoke_agent_stream(*_args, **_kwargs):
            return api_gateway_main.StreamingResponse(upstream_events(), media_type="text/event-stream")

        with patch.object(api_gateway_main, "invoke_agent_stream", side_effect=fake_invoke_agent_stream):
            response = await api_gateway_main.handle_a2a_stream_message(
                "planner",
                "default",
                {
                    "message": {
                        "messageId": "msg-stream-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Say hello"}],
                    }
                },
                "req-stream-1",
                "gateway-stream-1",
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))

        payload = "".join(chunks)
        self.assertIn('"artifactUpdate"', payload)
        self.assertIn('"statusUpdate"', payload)
        self.assertIn('"kind": "artifact-update"', payload)
        self.assertIn('"kind": "status-update"', payload)
        self.assertIn('TASK_STATE_COMPLETED', payload)

        stored_record = next(iter(api_gateway_main.A2A_TASK_STORE.values()))
        task_id = stored_record["task"]["id"]
        get_response = api_gateway_main.handle_a2a_get_task(
            "planner",
            "default",
            {"id": task_id},
            "req-stream-2",
        )
        fetched_task = get_response["result"]["task"]
        self.assertEqual(fetched_task["artifacts"][0]["parts"][0]["text"], "Hello")
        self.assertEqual(fetched_task["metadata"]["policyName"], "strict-enterprise-policy")

    async def test_a2a_jsonrpc_accepts_langsmith_method_names(self) -> None:
        raw_request = types.SimpleNamespace(
            headers={},
            query_params={},
            base_url="http://gateway.local/",
            json=AsyncMock(
                return_value={
                    "jsonrpc": "2.0",
                    "id": "rpc-1",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": "msg-1",
                            "role": "ROLE_USER",
                            "parts": [{"text": "Hello"}],
                        }
                    },
                }
            ),
        )

        with patch.object(
            api_gateway_main,
            "handle_a2a_send_message",
            AsyncMock(return_value={"jsonrpc": "2.0", "id": "rpc-1", "result": {"task": {"id": "task-1"}}}),
        ):
            response = await api_gateway_main.a2a_jsonrpc("planner", raw_request, namespace="default", user={})

        payload = json.loads(response.body)
        self.assertEqual(payload["id"], "rpc-1")
        self.assertEqual(payload["result"]["task"]["id"], "task-1")


class GatewayInvokeProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_agent_artifact_proxies_runtime_file_response(self) -> None:
        response = httpx.Response(
            200,
            content=b"%PDF-1.4 sample",
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="AZ305_summary.pdf"',
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, **kwargs):
                self.url = url
                self.kwargs = kwargs
                return response

        fake_client = FakeAsyncClient()

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=fake_client,
        ):
            proxied = await api_gateway_main.download_agent_artifact(
                "demo",
                "/tmp/AZ305_summary.pdf",
                "default",
                user={},
            )

        self.assertEqual(fake_client.kwargs["params"], {"path": "/tmp/AZ305_summary.pdf"})
        self.assertEqual(proxied.media_type, "application/pdf")
        self.assertEqual(proxied.headers.get("content-disposition"), 'attachment; filename="AZ305_summary.pdf"')
        self.assertEqual(proxied.body, b"%PDF-1.4 sample")

    async def test_invoke_agent_rejects_invalid_runtime_json(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(200, text="not-json")

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=FakeAsyncClient(),
        ):
            with self.assertRaises(HTTPException) as context:
                await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("invalid JSON", str(context.exception.detail))

    async def test_invoke_agent_returns_a2a_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
        )
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "caller-thread",
                "model": "gpt-4",
                "status": "completed",
                "a2a": {
                    "targetAgent": "analysis-agent",
                    "targetNamespace": "team-b",
                    "targetThreadId": "callee-thread",
                    "responseStatus": "completed",
                },
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with patch.object(
            api_gateway_main.asyncio,
            "to_thread",
            return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "langgraph"}}},
        ), patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()):
            invoke_response = await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertEqual(invoke_response.a2a["targetAgent"], "analysis-agent")
        self.assertEqual(invoke_response.a2a["targetThreadId"], "callee-thread")

    async def test_invoke_agent_forwards_team_context_and_caller_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="Investigate the incident",
            caller_agent_name="planner",
            caller_agent_namespace="team-a",
            parent_thread_id="thread-parent",
            caller_request_id="req-123",
            team_context={"objective": "Produce a reusable incident summary."},
        )
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {}
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, **kwargs):
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                return response

        with patch.object(
            api_gateway_main.asyncio,
            "to_thread",
            return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "langgraph"}}},
        ), patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()):
            await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={})

        forwarded = captured["json"]
        self.assertEqual(forwarded["caller_agent_name"], "planner")
        self.assertEqual(forwarded["caller_agent_namespace"], "team-a")
        self.assertEqual(forwarded["parent_thread_id"], "thread-parent")
        self.assertEqual(forwarded["caller_request_id"], "req-123")
        self.assertEqual(forwarded["team_context"]["objective"], "Produce a reusable incident summary.")

    async def test_invoke_agent_forwards_and_returns_subagent_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="Coordinate a root-cause analysis",
            subagent_strategy="parallel",
            subagents=[
                {
                    "name": "analysis-agent",
                    "namespace": "team-b",
                    "role": "incident analyst",
                    "task": "Inspect the failing workflow.",
                    "result_file_path": "artifacts/analysis.md",
                }
            ],
        )
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {}
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
                "subagents": {
                    "strategy": "parallel",
                    "count": 1,
                    "results": [
                        {
                            "name": "analysis-agent",
                            "namespace": "team-b",
                            "status": "completed",
                            "resultFilePath": "artifacts/analysis.md",
                        }
                    ],
                },
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, **kwargs):
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                return response

        with patch.object(
            api_gateway_main.asyncio,
            "to_thread",
            return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "langgraph"}}},
        ), patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()):
            invoke_response = await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={})

        forwarded = captured["json"]
        self.assertEqual(forwarded["subagent_strategy"], "parallel")
        self.assertEqual(forwarded["subagents"][0]["name"], "analysis-agent")
        self.assertEqual(forwarded["subagents"][0]["result_file_path"], "artifacts/analysis.md")
        self.assertEqual(invoke_response.subagents["strategy"], "parallel")
        self.assertEqual(invoke_response.subagents["results"][0]["resultFilePath"], "artifacts/analysis.md")

    async def test_invoke_agent_preserves_non_object_tool_result(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="Call the reporting tool",
            tool_name="report.generate",
            mcp_server="reporting",
        )
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
                "tool_name": "report.generate",
                "tool_result": ["row-1", "row-2"],
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with patch.object(
            api_gateway_main.asyncio,
            "to_thread",
            return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "langgraph"}}},
        ), patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()):
            invoke_response = await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={})

        self.assertEqual(invoke_response.tool_name, "report.generate")
        self.assertEqual(invoke_response.tool_result, ["row-1", "row-2"])

    async def test_invoke_agent_stream_emits_response_error_event_for_upstream_failure(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        error_response = httpx.Response(503, text=json.dumps({"detail": "runtime cold start"}))

        class FakeStreamContext:
            async def __aenter__(self):
                return error_response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamContext()

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=FakeAsyncClient(),
        ):
            response = await api_gateway_main.invoke_agent_stream("demo", request, raw_request, "default", user={})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        payload = "".join(chunks)
        self.assertIn("event: response.error", payload)
        self.assertIn("runtime cold start", payload)

    async def test_invoke_agent_stream_emits_keepalive_for_idle_upstream(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})

        class FakeStreamResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_text(self):
                await asyncio.sleep(0.02)
                yield "event: response.completed\ndata: {\"thread_id\": \"t-1\", \"status\": \"completed\"}\n\n"

        class FakeStreamContext:
            async def __aenter__(self):
                return FakeStreamResponse()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamContext()

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=FakeAsyncClient(),
        ), patch.object(api_gateway_main, "STREAM_KEEPALIVE_SECONDS", 0.01):
            response = await api_gateway_main.invoke_agent_stream("demo", request, raw_request, "default", user={})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        payload = "".join(chunks)
        self.assertIn(": keepalive", payload)
        self.assertIn("event: response.completed", payload)


class LogStreamTests(unittest.TestCase):
    """Tests for the agent log endpoints including the new SSE streaming endpoint."""

    @classmethod
    def _ensure_k8s_mock(cls):
        """Ensure a mock kubernetes module exists in sys.modules for local imports."""
        if "kubernetes" not in sys.modules:
            k8s_mod = types.ModuleType("kubernetes")
            k8s_client_mod = types.ModuleType("kubernetes.client")
            k8s_watch_mod = types.ModuleType("kubernetes.watch")
            k8s_mod.client = k8s_client_mod
            k8s_mod.watch = k8s_watch_mod
            sys.modules["kubernetes"] = k8s_mod
            sys.modules["kubernetes.client"] = k8s_client_mod
            sys.modules["kubernetes.watch"] = k8s_watch_mod

    def setUp(self):
        self._ensure_k8s_mock()
        from unittest.mock import MagicMock
        self._mock_core = MagicMock()
        self._core_patcher = patch.object(
            sys.modules["kubernetes.client"], "CoreV1Api", return_value=self._mock_core,
            create=True,
        )
        self._core_patcher.start()

    def tearDown(self):
        self._core_patcher.stop()

    def test_get_agent_logs_returns_pod_log_with_timestamps(self) -> None:
        fake_pod = types.SimpleNamespace(
            metadata=types.SimpleNamespace(name="my-pod-0")
        )
        fake_log_text = "2026-03-17T10:00:00Z INFO starting\n2026-03-17T10:00:01Z INFO ready"
        self._mock_core.read_namespaced_pod_log.return_value = fake_log_text

        with patch.object(api_gateway_main, "verify_token", return_value={"sub": "u1", "namespaces": ["ns1"]}), \
             patch.object(api_gateway_main, "read_agent", return_value={}), \
             patch.object(api_gateway_main, "list_agent_pods", return_value=[fake_pod]):
            result = api_gateway_main.get_agent_logs(
                agent_name="myagent", namespace="ns1", tail=200,
                user={"sub": "u1", "namespaces": ["ns1"]},
            )
            self.assertEqual(result["agent_name"], "myagent")
            self.assertEqual(result["pod_name"], "my-pod-0")
            self.assertIn("starting", result["logs"])
            call_kwargs = self._mock_core.read_namespaced_pod_log.call_args
            self.assertTrue(call_kwargs.kwargs.get("timestamps", False))

    def test_get_agent_logs_clamps_tail_parameter(self) -> None:
        """Tail parameter should be clamped between 1 and 5000."""
        fake_pod = types.SimpleNamespace(
            metadata=types.SimpleNamespace(name="pod-0")
        )
        self._mock_core.read_namespaced_pod_log.return_value = ""

        with patch.object(api_gateway_main, "verify_token", return_value={"sub": "u1", "namespaces": ["ns1"]}), \
             patch.object(api_gateway_main, "read_agent", return_value={}), \
             patch.object(api_gateway_main, "list_agent_pods", return_value=[fake_pod]):
            api_gateway_main.get_agent_logs(
                agent_name="myagent", namespace="ns1", tail=99999,
                user={"sub": "u1", "namespaces": ["ns1"]},
            )
            call_kwargs = self._mock_core.read_namespaced_pod_log.call_args
            self.assertEqual(call_kwargs.kwargs.get("tail_lines"), 5000)

    def test_sse_event_format(self) -> None:
        """sse_event produces valid SSE with proper termination."""
        result = api_gateway_main.sse_event("log.line", {"line": "hello world"})
        self.assertTrue(result.startswith("event: log.line\ndata: "))
        self.assertTrue(result.endswith("\n\n"))
        data_line = result.split("\n")[1]
        payload = json.loads(data_line.removeprefix("data: "))
        self.assertEqual(payload["line"], "hello world")

    def test_get_agent_logs_404_no_pods(self) -> None:
        """Should 404 when no runtime pods exist."""
        with patch.object(api_gateway_main, "verify_token", return_value={"sub": "u1", "namespaces": ["ns1"]}), \
             patch.object(api_gateway_main, "read_agent", return_value={}), \
             patch.object(api_gateway_main, "list_agent_pods", return_value=[]):
            with self.assertRaises(HTTPException) as ctx:
                api_gateway_main.get_agent_logs(
                    agent_name="myagent", namespace="ns1",
                    user={"sub": "u1", "namespaces": ["ns1"]},
                )
            self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()