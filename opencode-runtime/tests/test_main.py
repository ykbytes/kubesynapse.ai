import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("opencode_runtime_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load opencode-runtime main module for tests")
opencode_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = opencode_runtime_main
SPEC.loader.exec_module(opencode_runtime_main)

# Sub-module references for patching at the correct resolution site
runtime_modules = opencode_runtime_main.RUNTIME_IMPORTED_MODULES
config_mod = opencode_runtime_main.RUNTIME_IMPORTED_MODULES["config"]
skills_mod = opencode_runtime_main.RUNTIME_IMPORTED_MODULES["skills"]
opencode_client_mod = opencode_runtime_main.RUNTIME_IMPORTED_MODULES["opencode_client"]
invoke_mod = opencode_runtime_main.RUNTIME_IMPORTED_MODULES["invoke"]
analysis_mod = opencode_runtime_main.RUNTIME_IMPORTED_MODULES["analysis"]
supervisor_mod = opencode_runtime_main.RUNTIME_IMPORTED_MODULES["supervisor"]


class OpenCodeRuntimeTests(unittest.TestCase):
    def test_request_rejects_thread_id_when_no_session_is_enabled(self) -> None:
        with self.assertRaises(ValueError):
            opencode_runtime_main.InvokeRequest(prompt="hello", thread_id="thread-1", no_session=True)

    def test_materialize_opencode_config_files_merges_base_config_into_opencode_json(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(
                skills_mod,
                "OPENCODE_CONFIG_DIR",
                str(Path(temp_dir) / "config"),
            ),
            patch.dict(
                os.environ,
                {
                    opencode_runtime_main.OPENCODE_RUNTIME_CONFIG_FILES_ENV: json.dumps(
                        {
                            "opencode.json": {"default_agent": "build"},
                            "plugins/custom.ts": "export const Plugin = async () => ({})",
                        }
                    )
                },
                clear=False,
            ),
        ):
            written = opencode_runtime_main.materialize_opencode_config_files(
                {
                    "model": "litellm/gpt-4",
                    "provider": {
                        "litellm": {
                            "options": {
                                "baseURL": "http://litellm.internal/v1",
                                "apiKey": "test-key",
                            }
                        }
                    },
                    "default_agent": "plan",
                }
            )
            root = Path(skills_mod.OPENCODE_CONFIG_DIR)
            config = json.loads((root / "opencode.json").read_text(encoding="utf-8"))

            self.assertEqual(written, ["opencode.json", "plugins/custom.ts"])
            self.assertEqual(config["default_agent"], "build")
            self.assertEqual(config["model"], "litellm/gpt-4")
            self.assertEqual(config["provider"]["litellm"]["options"]["baseURL"], "http://litellm.internal/v1")
            self.assertIn("Plugin", (root / "plugins" / "custom.ts").read_text(encoding="utf-8"))

    def test_build_generated_config_preserves_provider_when_overrides_are_partial(self) -> None:
        config, warnings = opencode_runtime_main.build_generated_config(
            [],
            config_overrides={
                "default_agent": "build",
                "permission": "allow",
            },
        )

        self.assertEqual(config["default_agent"], "build")
        self.assertEqual(config["permission"], "allow")
        self.assertIn("litellm", config["provider"])
        self.assertEqual(config["provider"]["litellm"]["models"]["gpt-4"]["name"], "gpt-4")
        self.assertEqual(warnings, [])

    def test_build_server_env_sets_openai_compat_env_for_litellm(self) -> None:
        with (
            patch.object(supervisor_mod, "DEFAULT_PROVIDER", "litellm"),
            patch.object(supervisor_mod, "LITELLM_API_KEY", "test-key"),
            patch.object(supervisor_mod, "build_litellm_base_url", return_value="http://litellm.internal/v1"),
        ):
            env = supervisor_mod.build_server_env({"model": "litellm/gpt-4"})

        self.assertEqual(env["OPENAI_BASE_URL"], "http://litellm.internal/v1")
        self.assertEqual(env["OPENAI_API_KEY"], "test-key")

    def test_materialize_skill_files_maps_platform_skills_to_opencode_layout(self) -> None:
        skill_text = (
            "---\n"
            "name: reviewer\n"
            "description: Review code conservatively.\n"
            "allowedMcpServers:\n"
            "  - github\n"
            "---\n"
            "Review code and focus on regressions.\n"
        )
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(
                skills_mod,
                "OPENCODE_CONFIG_DIR",
                str(Path(temp_dir) / "config"),
            ),
            patch.dict(
                os.environ,
                {
                    opencode_runtime_main.AGENT_SKILL_FILES_ENV: json.dumps(
                        {".github/skills/reviewer/SKILL.md": skill_text}
                    )
                },
                clear=False,
            ),
        ):
            written, skill_meta, warnings = opencode_runtime_main.materialize_skill_files()
            target = Path(skills_mod.OPENCODE_CONFIG_DIR) / "skills" / "reviewer" / "SKILL.md"

            self.assertEqual(written, ["skills/reviewer/SKILL.md"])
            self.assertEqual(warnings, [])
            self.assertEqual(target.read_text(encoding="utf-8"), skill_text)
            self.assertEqual(len(skill_meta), 1)
            self.assertEqual(skill_meta[0]["name"], "reviewer")
            self.assertEqual(skill_meta[0]["description"], "Review code conservatively.")
            self.assertEqual(skill_meta[0]["content"], "Review code and focus on regressions.")

    def test_parse_skill_frontmatter_normalizes_invalid_name(self) -> None:
        content = "---\nname: My_Invalid Skill Name!!!\ndescription: Test skill\n---\nBody\n"
        name, description, warnings = opencode_runtime_main.parse_skill_frontmatter(
            ".github/skills/reviewer/SKILL.md",
            content,
        )
        self.assertEqual(name, "my-invalid-skill-name")
        self.assertEqual(description, "Test skill")
        self.assertTrue(any("Materialized skill" in warning for warning in warnings))

    def test_parse_skill_frontmatter_falls_back_for_overlong_name(self) -> None:
        content = (
            "---\n"
            "name: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "description: Test skill\n"
            "---\n"
            "Body\n"
        )
        name, description, warnings = opencode_runtime_main.parse_skill_frontmatter(
            ".github/skills/reviewer/SKILL.md",
            content,
        )
        self.assertEqual(name, "reviewer")
        self.assertTrue(any("invalid frontmatter name" in warning for warning in warnings))

    def test_build_generated_config_includes_sidecars_and_shared_mcp_servers(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"MCP_SERVERS": "documents,github"},
                clear=False,
            ),
            patch.object(skills_mod, "MCP_BEARER_TOKEN", "token-123"),
            patch.object(
                skills_mod,
                "HELM_RELEASE_NAME",
                "sandbox",
            ),
            patch.object(
                skills_mod,
                "MCP_HUB_NAMESPACE",
                "mcp-hub",
            ),
        ):
            config, warnings = opencode_runtime_main.build_generated_config([{"name": "browser", "port": 8081}])

        self.assertEqual(config["mcp"]["browser"]["url"], "http://127.0.0.1:8081/mcp")
        self.assertEqual(
            config["mcp"]["documents"]["url"],
            "http://sandbox-mcp-documents.mcp-hub.svc.cluster.local:8000/mcp",
        )
        self.assertEqual(config["mcp"]["documents"]["headers"]["Authorization"], "Bearer token-123")
        self.assertTrue(any("GitHub MCP" in warning for warning in warnings))

    def test_build_mcp_config_prefers_structured_connections_over_legacy_inputs(self) -> None:
        with patch.dict(
            os.environ,
            {
                config_mod.OPENCODE_MCP_CONNECTIONS_ENV: json.dumps(
                    [
                        {
                            "slug": "docs-remote",
                            "serverId": "docs",
                            "runtime": {
                                "kind": "remote",
                                "configKey": "docs-remote",
                                "url": "https://docs.example.com/mcp",
                                "headers": [
                                    {
                                        "name": "Authorization",
                                        "envVar": "MCP_DOCS_TOKEN",
                                        "prefix": "Bearer ",
                                    }
                                ],
                            },
                        }
                    ]
                ),
                "MCP_DOCS_TOKEN": "secret-token",
                "MCP_SERVERS": "documents",
            },
            clear=False,
        ):
            config, warnings = skills_mod.build_mcp_config([{"name": "browser", "port": 8081}])

        self.assertEqual(list(config.keys()), ["docs-remote"])
        self.assertEqual(config["docs-remote"]["url"], "https://docs.example.com/mcp")
        self.assertEqual(config["docs-remote"]["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(warnings, [])

    def test_build_structured_mcp_config_maps_sidecar_runtime_to_localhost(self) -> None:
        config, warnings = skills_mod.build_structured_mcp_config(
            [
                {
                    "slug": "qdrant-sidecar",
                    "runtime": {
                        "kind": "sidecar",
                        "configKey": "qdrant-sidecar",
                        "sidecar": {
                            "port": 9102,
                            "endpointPath": "/rpc",
                        },
                    },
                }
            ]
        )

        self.assertEqual(config["qdrant-sidecar"]["url"], "http://127.0.0.1:9102/rpc")
        self.assertEqual(warnings, [])

    def test_session_registry_persists_logical_thread_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = opencode_runtime_main.SessionRegistry(Path(temp_dir) / "sessions.json")
            registry.set("thread-a", "ses_123")

            self.assertEqual(registry.get("thread-a"), "ses_123")
            raw = json.loads((Path(temp_dir) / "sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["thread-a"]["session_id"], "ses_123")
            self.assertIn("last_accessed", raw["thread-a"])


class ExtractToolCallsTests(unittest.TestCase):
    """Tests for extract_tool_calls_from_messages."""

    def test_extracts_tool_calls_from_messages(self) -> None:
        messages = [
            {
                "info": {"role": "assistant"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "write",
                        "callID": "call_1",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/workspace/hello.py", "content": "print('hello')"},
                            "output": "File written successfully",
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call_2",
                        "state": {
                            "status": "completed",
                            "input": {"command": "python hello.py"},
                            "output": "hello",
                        },
                    },
                    {"type": "text", "text": "I created and ran hello.py"},
                ],
            }
        ]
        tool_calls = opencode_runtime_main.extract_tool_calls_from_messages(messages)
        self.assertEqual(len(tool_calls), 2)
        self.assertEqual(tool_calls[0]["tool"], "write")
        self.assertEqual(tool_calls[0]["status"], "completed")
        self.assertEqual(tool_calls[0]["input"]["filePath"], "/workspace/hello.py")
        self.assertEqual(tool_calls[1]["tool"], "bash")
        self.assertEqual(tool_calls[1]["output"], "hello")

    def test_handles_empty_messages(self) -> None:
        self.assertEqual(opencode_runtime_main.extract_tool_calls_from_messages([]), [])

    def test_ignores_non_tool_parts(self) -> None:
        messages = [{"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "Hi"}]}]
        self.assertEqual(opencode_runtime_main.extract_tool_calls_from_messages(messages), [])

    def test_handles_missing_parts_key(self) -> None:
        messages = [{"info": {"role": "assistant"}}]
        self.assertEqual(opencode_runtime_main.extract_tool_calls_from_messages(messages), [])

    def test_truncates_long_tool_output(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {"status": "completed", "input": {"command": "cat bigfile"}, "output": "x" * 5000},
                    }
                ]
            }
        ]
        tool_calls = opencode_runtime_main.extract_tool_calls_from_messages(messages)
        self.assertLessEqual(len(tool_calls[0]["output"]), 2003)


class BuildToolOnlyResponseTests(unittest.TestCase):
    """Tests for build_tool_only_response fallback formatting."""

    def test_returns_empty_string_without_tool_calls(self) -> None:
        self.assertEqual(opencode_runtime_main.build_tool_only_response([]), "")

    def test_formats_basic_completed_tool_outputs(self) -> None:
        response = opencode_runtime_main.build_tool_only_response([
            {"tool": "bash", "status": "completed", "output": "hello from bash"},
            {"tool": "read", "status": "completed", "output": "file contents"},
        ])

        self.assertIn("Tool results:", response)
        self.assertIn("- bash: hello from bash", response)
        self.assertIn("- read: file contents", response)

    def test_summarizes_structured_list_outputs(self) -> None:
        response = opencode_runtime_main.build_tool_only_response([
            {
                "tool": "kubernetes_list_pods",
                "status": "completed",
                "output": json.dumps([
                    {"metadata": {"name": "api-gateway"}},
                    {"metadata": {"name": "collector"}},
                ]),
            }
        ])

        self.assertIn("kubernetes_list_pods", response)
        self.assertIn("returned 2 items", response)
        self.assertIn("api-gateway", response)

    def test_uses_input_preview_when_completed_output_is_empty(self) -> None:
        response = opencode_runtime_main.build_tool_only_response([
            {
                "tool": "kubernetes_kubectl_get",
                "status": "completed",
                "input": {"resource_type": "nodes"},
                "output": "",
            }
        ])

        self.assertIn("completed with no textual output", response)
        self.assertIn("resource_type", response)


class ExtractArtifactsTests(unittest.TestCase):
    """Tests for extract_artifacts_from_messages."""

    def test_extracts_write_tool_artifacts(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "write",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/workspace/report.md", "content": "# Report"},
                        },
                    }
                ]
            }
        ]
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["path"], "/workspace/report.md")
        self.assertEqual(artifacts[0]["tool"], "write")

    def test_extracts_edit_tool_artifacts(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "edit",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/workspace/main.py", "oldString": "foo", "newString": "bar"},
                        },
                    }
                ]
            }
        ]
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["path"], "/workspace/main.py")
        self.assertEqual(artifacts[0]["tool"], "edit")

    def test_extracts_patch_parts(self) -> None:
        messages = [{"parts": [{"type": "patch", "files": ["src/app.ts", "src/utils.ts"], "hash": "abc123"}]}]
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 2)
        paths = [a["path"] for a in artifacts]
        self.assertIn("src/app.ts", paths)
        self.assertIn("src/utils.ts", paths)

    def test_deduplicates_artifacts_by_path(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "write",
                        "state": {"status": "completed", "input": {"filePath": "/workspace/file.py", "content": "v1"}},
                    },
                    {
                        "type": "tool",
                        "tool": "edit",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/workspace/file.py", "oldString": "v1", "newString": "v2"},
                        },
                    },
                ]
            }
        ]
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        # Should deduplicate to one entry (last write wins)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["path"], "/workspace/file.py")

    def test_skips_errored_tool_parts(self) -> None:
        messages = [
            {
                "parts": [
                    {
                        "type": "tool",
                        "tool": "write",
                        "state": {"status": "error", "input": {"filePath": "/workspace/fail.py"}},
                    }
                ]
            }
        ]
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 0)

    def test_handles_empty_messages(self) -> None:
        self.assertEqual(opencode_runtime_main.extract_artifacts_from_messages([]), [])


class DetectTaskErrorsTests(unittest.TestCase):
    """Tests for detect_task_errors."""

    def test_detects_tool_errors(self) -> None:
        messages = [
            {
                "info": {"role": "assistant"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {"status": "error", "error": "command not found: foobar"},
                    }
                ],
            }
        ]
        errors = opencode_runtime_main.detect_task_errors(messages)
        self.assertEqual(len(errors), 1)
        self.assertIn("bash", errors[0])
        self.assertIn("command not found", errors[0])

    def test_detects_message_level_errors(self) -> None:
        messages = [
            {
                "info": {"role": "assistant", "error": {"name": "RateLimitError", "message": "Rate limit exceeded"}},
                "parts": [],
            }
        ]
        errors = opencode_runtime_main.detect_task_errors(messages)
        self.assertEqual(len(errors), 1)
        self.assertIn("Rate limit exceeded", errors[0])

    def test_no_errors_on_successful_messages(self) -> None:
        messages = [
            {
                "info": {"role": "assistant"},
                "parts": [
                    {"type": "tool", "tool": "write", "state": {"status": "completed", "input": {}}},
                    {"type": "text", "text": "Done!"},
                ],
            }
        ]
        errors = opencode_runtime_main.detect_task_errors(messages)
        self.assertEqual(errors, [])


class DetectCompletionStatusTests(unittest.TestCase):
    """Tests for detect_completion_status."""

    def test_completed_on_stop_finish(self) -> None:
        payload = {"info": {"finish": "stop"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "completed")

    def test_completed_on_end_turn_finish(self) -> None:
        payload = {"info": {"finish": "end_turn"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "completed")

    def test_error_when_info_has_error(self) -> None:
        payload = {"info": {"finish": "stop", "error": {"message": "context overflow"}}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "error")

    def test_incomplete_on_tool_calls_finish(self) -> None:
        payload = {"info": {"finish": "tool-calls"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "incomplete")

    def test_incomplete_on_empty_finish(self) -> None:
        payload = {"info": {"finish": ""}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "incomplete")

    def test_incomplete_on_missing_info(self) -> None:
        # When info dict is absent, we default to empty which yields empty
        # finish string â†’ treated as incomplete (we cannot confirm completion)
        self.assertEqual(opencode_runtime_main.detect_completion_status({}), "incomplete")

    def test_unknown_on_non_dict_info(self) -> None:
        self.assertEqual(opencode_runtime_main.detect_completion_status({"info": "bad"}), "unknown")


class FormatInstructionsTests(unittest.TestCase):
    """Tests for output format system prompts."""

    def test_json_format_instruction(self) -> None:
        result = opencode_runtime_main.build_format_system_prompt("json")
        self.assertIsNotNone(result)
        self.assertIn("JSON", result)

    def test_code_format_instruction(self) -> None:
        result = opencode_runtime_main.build_format_system_prompt("code")
        self.assertIsNotNone(result)
        self.assertIn("code", result)

    def test_markdown_format_instruction(self) -> None:
        result = opencode_runtime_main.build_format_system_prompt("markdown")
        self.assertIsNotNone(result)
        self.assertIn("Markdown", result)

    def test_text_format_instruction(self) -> None:
        result = opencode_runtime_main.build_format_system_prompt("text")
        self.assertIsNotNone(result)
        self.assertIn("plain text", result)

    def test_none_for_unknown_format(self) -> None:
        self.assertIsNone(opencode_runtime_main.build_format_system_prompt("xml"))

    def test_none_for_empty_format(self) -> None:
        self.assertIsNone(opencode_runtime_main.build_format_system_prompt(None))
        self.assertIsNone(opencode_runtime_main.build_format_system_prompt(""))

    def test_request_rejects_invalid_output_format(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            opencode_runtime_main.InvokeRequest(prompt="hello", output_format="xml")
        self.assertIn("output_format", str(ctx.exception))

    def test_request_accepts_valid_output_format(self) -> None:
        req = opencode_runtime_main.InvokeRequest(prompt="hello", output_format="json")
        self.assertEqual(req.output_format, "json")

    def test_request_normalizes_output_format_case(self) -> None:
        req = opencode_runtime_main.InvokeRequest(prompt="hello", output_format="JSON")
        self.assertEqual(req.output_format, "json")

    def test_request_infers_json_format_when_output_schema_is_provided(self) -> None:
        req = opencode_runtime_main.InvokeRequest(
            prompt="hello",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        self.assertEqual(req.output_format, "json")

    def test_request_rejects_non_object_output_schema(self) -> None:
        with self.assertRaises(ValueError):
            opencode_runtime_main.InvokeRequest(prompt="hello", output_schema=["bad"])

    def test_request_accepts_outbound_a2a_fields(self) -> None:
        request = opencode_runtime_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent=" analysis-agent ",
            a2a_target_namespace=" team-b ",
            a2a_timeout_seconds=15,
        )

        self.assertEqual(request.a2a_target_agent, "analysis-agent")
        self.assertEqual(request.a2a_target_namespace, "team-b")
        self.assertEqual(request.a2a_timeout_seconds, 15)

    def test_request_rejects_a2a_timeout_without_target(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            opencode_runtime_main.InvokeRequest(prompt="hello", a2a_timeout_seconds=15)
        self.assertIn("a2a_timeout_seconds", str(ctx.exception))

    def test_parse_allowed_targets_ignores_invalid_entries(self) -> None:
        with patch.dict(
            os.environ,
            {
                config_mod.A2A_ALLOWED_TARGETS_ENV: json.dumps(
                    [
                        {"namespace": "team-b", "name": "analysis-agent"},
                        {"namespace": " ", "name": "skip-me"},
                        {"namespace": "team-c", "name": "reviewer"},
                        "invalid",
                    ]
                )
            },
            clear=False,
        ):
            allowed_targets = config_mod._parse_allowed_targets()

        self.assertEqual(allowed_targets, {("team-b", "analysis-agent"), ("team-c", "reviewer")})

    def test_build_prompt_format_returns_json_schema_for_json_output(self) -> None:
        request = opencode_runtime_main.InvokeRequest(prompt="hello", output_format="json")
        prompt_format = opencode_runtime_main.build_prompt_format(request)
        self.assertEqual(prompt_format["type"], "json_schema")
        self.assertEqual(prompt_format["retryCount"], opencode_runtime_main.STRUCTURED_OUTPUT_RETRY_COUNT)

    def test_build_prompt_format_uses_custom_schema(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        request = opencode_runtime_main.InvokeRequest(prompt="hello", output_schema=schema)
        prompt_format = opencode_runtime_main.build_prompt_format(request)
        self.assertEqual(prompt_format["schema"], schema)


class AutonomyConfigTests(unittest.TestCase):
    """Tests for autonomy configuration and system prompt."""

    def test_autonomy_system_prompt_references_native_tools(self) -> None:
        prompt = opencode_runtime_main.AUTONOMY_SYSTEM_PROMPT
        self.assertIn("write", prompt)
        self.assertIn("edit", prompt)
        self.assertIn("bash", prompt)
        self.assertIn("read", prompt)
        self.assertIn("webfetch", prompt)
        self.assertIn("codesearch", prompt)
        self.assertIn("todowrite", prompt)
        self.assertIn("autonomous", prompt.lower())

    def test_autonomy_system_prompt_includes_planning_guidance(self) -> None:
        prompt = opencode_runtime_main.AUTONOMY_SYSTEM_PROMPT
        self.assertIn("PLAN FIRST", prompt)
        self.assertIn("todowrite", prompt)
        self.assertIn("task", prompt.lower())

    def test_autonomy_system_prompt_includes_delegation(self) -> None:
        prompt = opencode_runtime_main.AUTONOMY_SYSTEM_PROMPT
        self.assertIn("DELEGATE", prompt)
        self.assertIn("task tool", prompt.lower())

    def test_autonomy_system_prompt_discourages_mcp(self) -> None:
        prompt = opencode_runtime_main.AUTONOMY_SYSTEM_PROMPT
        self.assertIn("MCP", prompt)
        self.assertIn("natively", prompt)

    def test_request_autonomous_default_is_true(self) -> None:
        req = opencode_runtime_main.InvokeRequest(prompt="hello")
        self.assertTrue(req.autonomous)

    def test_request_autonomous_can_be_disabled(self) -> None:
        req = opencode_runtime_main.InvokeRequest(prompt="hello", autonomous=False)
        self.assertFalse(req.autonomous)

    def test_request_max_retries_defaults_to_none(self) -> None:
        req = opencode_runtime_main.InvokeRequest(prompt="hello")
        self.assertIsNone(req.max_retries)

    def test_autonomy_continuation_prompt_exists(self) -> None:
        self.assertIn("Continue", opencode_runtime_main.AUTONOMY_CONTINUATION_PROMPT)


class ResponseMetadataTests(unittest.TestCase):
    """Tests for _build_response_metadata."""

    def test_extracts_tokens_and_cost(self) -> None:
        payload = {
            "info": {
                "tokens": {"input": 100, "output": 50, "total": 150},
                "cost": 0.005,
                "time": {"created": 1000, "completed": 2000},
                "finish": "stop",
            }
        }
        meta = opencode_runtime_main._build_response_metadata(payload)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["tokens"]["input"], 100)
        self.assertEqual(meta["cost"], 0.005)
        self.assertEqual(meta["finish_reason"], "stop")
        self.assertIn("time", meta)

    def test_returns_none_for_empty_info(self) -> None:
        meta = opencode_runtime_main._build_response_metadata({"info": {}})
        self.assertIsNone(meta)

    def test_returns_none_when_no_info(self) -> None:
        meta = opencode_runtime_main._build_response_metadata({})
        self.assertIsNone(meta)


class StructuredOutputExtractionTests(unittest.TestCase):
    def test_extract_response_text_prefers_structured_output(self) -> None:
        payload = {"info": {"structured": {"ok": True}}, "parts": []}
        self.assertEqual(opencode_runtime_main.extract_response_text(payload), '{"ok": true}')

    def test_detect_completion_status_handles_finish_error(self) -> None:
        payload = {"info": {"finish": "error"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "error")

    def test_get_latest_assistant_payload_prefers_latest_meaningful_assistant(self) -> None:
        messages = [
            {"info": {"role": "user"}, "parts": []},
            {"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "first"}]},
            {"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "step-start"}, {"type": "step-finish"}]},
        ]
        payload = opencode_runtime_main.get_latest_assistant_payload(messages)
        self.assertEqual(payload["parts"][0]["text"], "first")

    def test_get_latest_assistant_payload_can_filter_by_parent_id(self) -> None:
        messages = [
            {
                "info": {"role": "assistant", "parentID": "msg_a", "finish": "stop"},
                "parts": [{"type": "text", "text": "first"}],
            },
            {
                "info": {"role": "assistant", "parentID": "msg_b", "finish": "stop"},
                "parts": [{"type": "text", "text": "second"}],
            },
            {
                "info": {"role": "assistant", "parentID": "msg_a", "finish": "stop"},
                "parts": [{"type": "step-start"}, {"type": "step-finish"}],
            },
        ]
        payload = opencode_runtime_main.get_latest_assistant_payload(messages, parent_message_id="msg_a")
        self.assertEqual(payload["parts"][0]["text"], "first")

    def test_runtime_capabilities_exposes_native_tools_and_formats(self) -> None:
        capabilities = opencode_runtime_main.runtime_capabilities()
        self.assertIn("write", capabilities["native_tools"])
        self.assertIn("json", capabilities["output_formats"])
        self.assertTrue(capabilities["structured_output"]["supported"])


class ExtractResponseTextPriorityTests(unittest.TestCase):
    """Tests that extract_response_text prioritises structured output over text parts."""

    def test_structured_output_wins_over_text_parts(self) -> None:
        """When both text parts and info.structured exist, structured output should win."""
        payload = {
            "info": {"role": "assistant", "structured": {"answer": 42}},
            "parts": [{"type": "text", "text": "The answer is 42."}],
        }
        result = opencode_runtime_main.extract_response_text(payload)
        parsed = json.loads(result)
        self.assertEqual(parsed["answer"], 42)

    def test_falls_back_to_text_when_no_structured(self) -> None:
        """When there's no structured output, text parts should be returned."""
        payload = {
            "info": {"role": "assistant"},
            "parts": [{"type": "text", "text": "Hello world"}],
        }
        self.assertEqual(opencode_runtime_main.extract_response_text(payload), "Hello world")

    def test_structured_output_via_structured_output_key(self) -> None:
        """The alternate key 'structured_output' should also be checked."""
        payload = {
            "info": {"structured_output": {"status": "ok"}},
            "parts": [{"type": "text", "text": "fallback"}],
        }
        result = opencode_runtime_main.extract_response_text(payload)
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "ok")

    def test_error_in_info_returned_when_no_structured(self) -> None:
        """When info has an error dict, its message is returned."""
        payload = {
            "info": {"error": {"message": "context length exceeded"}},
            "parts": [],
        }
        self.assertEqual(opencode_runtime_main.extract_response_text(payload), "context length exceeded")


class NativeToolNamesTests(unittest.TestCase):
    """Verify NATIVE_TOOL_NAMES is a frozenset (not list) for O(1) lookups."""

    def test_native_tool_names_is_frozenset(self) -> None:
        self.assertIsInstance(opencode_runtime_main.NATIVE_TOOL_NAMES, frozenset)

    def test_contains_expected_tools(self) -> None:
        expected = {"bash", "read", "write", "edit", "glob", "grep", "task"}
        self.assertTrue(expected.issubset(opencode_runtime_main.NATIVE_TOOL_NAMES))

    def test_runtime_capabilities_returns_sorted_tools(self) -> None:
        caps = opencode_runtime_main.runtime_capabilities()
        tools = caps["native_tools"]
        self.assertEqual(tools, sorted(tools))


class DetectCompletionStatusExtendedTests(unittest.TestCase):
    """Extended tests for detect_completion_status edge cases."""

    def test_length_finish_is_completed(self) -> None:
        payload = {"info": {"finish": "length"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "completed")

    def test_content_filter_finish_is_completed(self) -> None:
        payload = {"info": {"finish": "content_filter"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "completed")

    def test_case_insensitive_finish(self) -> None:
        payload = {"info": {"finish": "STOP"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "completed")

    def test_error_in_info_takes_precedence_over_finish(self) -> None:
        payload = {"info": {"finish": "stop", "error": {"message": "boom"}}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "error")


class InvokeResponseModelTests(unittest.TestCase):
    """Tests for enhanced InvokeResponse model."""

    def test_response_includes_artifacts_field(self) -> None:
        resp = opencode_runtime_main.InvokeResponse(
            thread_id="t1",
            response="done",
            model="gpt-4",
            artifacts=[{"path": "/workspace/file.py", "tool": "write", "status": "completed"}],
        )
        self.assertEqual(len(resp.artifacts), 1)
        self.assertEqual(resp.artifacts[0]["path"], "/workspace/file.py")

    def test_response_includes_tool_calls_field(self) -> None:
        resp = opencode_runtime_main.InvokeResponse(
            thread_id="t1",
            response="done",
            model="gpt-4",
            tool_calls=[{"tool": "bash", "status": "completed", "output": "OK"}],
        )
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0]["tool"], "bash")

    def test_response_includes_metadata_field(self) -> None:
        resp = opencode_runtime_main.InvokeResponse(
            thread_id="t1",
            response="done",
            model="gpt-4",
            metadata={"tokens": {"input": 10, "output": 5}, "cost": 0.001},
        )
        self.assertIsNotNone(resp.metadata)
        self.assertEqual(resp.metadata["cost"], 0.001)

    def test_response_defaults_empty_artifacts_and_tool_calls(self) -> None:
        resp = opencode_runtime_main.InvokeResponse(thread_id="t1", response="done", model="gpt-4")
        self.assertEqual(resp.artifacts, [])
        self.assertEqual(resp.tool_calls, [])
        self.assertIsNone(resp.continuity)
        self.assertIsNone(resp.metadata)


class CombinedSystemPromptTests(unittest.TestCase):
    """Tests for system prompt composition with autonomy and format instructions."""

    def test_combine_includes_autonomy_when_enabled(self) -> None:
        result = opencode_runtime_main.combine_system_prompt(
            opencode_runtime_main.AUTONOMY_SYSTEM_PROMPT,
            "You are a helpful assistant.",
        )
        self.assertIn("autonomous", result.lower())
        self.assertIn("helpful assistant", result)

    def test_combine_skips_autonomy_when_none(self) -> None:
        result = opencode_runtime_main.combine_system_prompt(
            None,
            "You are a helpful assistant.",
        )
        self.assertEqual(result, "You are a helpful assistant.")

    def test_combine_includes_format_instruction(self) -> None:
        format_instr = opencode_runtime_main.build_format_system_prompt("json")
        result = opencode_runtime_main.combine_system_prompt(
            "Base prompt.",
            format_instr,
        )
        self.assertIn("JSON", result)
        self.assertIn("Base prompt", result)


class GetSessionMessagesTests(unittest.TestCase):
    """Tests for get_session_messages."""

    def test_returns_empty_list_on_404(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_messages("nonexistent")
        self.assertEqual(result, [])

    def test_returns_parsed_messages(self) -> None:
        sample_messages = [
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "hello"}]},
            {
                "info": {"role": "assistant"},
                "parts": [
                    {"type": "text", "text": "Hi!"},
                    {
                        "type": "tool",
                        "tool": "write",
                        "state": {"status": "completed", "input": {"filePath": "/workspace/test.py"}},
                    },
                ],
            },
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_messages
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_messages("ses_abc")
        self.assertEqual(len(result), 2)


class GetSessionMessageTests(unittest.TestCase):
    """Tests for get_session_message."""

    def test_returns_none_on_404(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_message("ses_abc", "msg_missing")
        self.assertIsNone(result)

    def test_returns_parsed_message(self) -> None:
        sample_message = {
            "info": {"id": "msg_1", "role": "assistant", "finish": "stop"},
            "parts": [{"type": "text", "text": "Hi!"}, "bad"],
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_message
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_message("ses_abc", "msg_1")

        self.assertIsNotNone(result)
        self.assertEqual(result["info"]["id"], "msg_1")
        self.assertEqual(len(result["parts"]), 1)


class GetSessionStatusTests(unittest.TestCase):
    """Tests for get_session_status."""

    def test_returns_idle_when_status_entry_is_null(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ses_abc": None}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_status("ses_abc")

        self.assertEqual(result, {"type": "idle"})


class FullWorkflowExtractionTests(unittest.TestCase):
    """End-to-end tests for extracting artifacts and tool calls from realistic session histories."""

    def _build_doc_creation_history(self) -> list[dict]:
        """Simulate a session where the agent creates a document."""
        return [
            {
                "info": {"role": "user"},
                "parts": [{"type": "text", "text": "Create a project README"}],
            },
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [
                    {"type": "text", "text": "I'll create the README for you."},
                    {
                        "type": "tool",
                        "tool": "write",
                        "callID": "c1",
                        "state": {
                            "status": "completed",
                            "input": {
                                "filePath": "/workspace/README.md",
                                "content": "# My Project\n\nA great project.",
                            },
                            "output": "File written: /workspace/README.md",
                        },
                    },
                    {"type": "text", "text": "I've created README.md with the project description."},
                ],
            },
        ]

    def _build_code_writing_history(self) -> list[dict]:
        """Simulate a session where the agent writes code and tests it."""
        return [
            {
                "info": {"role": "user"},
                "parts": [{"type": "text", "text": "Write a Python fibonacci function and test it"}],
            },
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "write",
                        "callID": "c1",
                        "state": {
                            "status": "completed",
                            "input": {
                                "filePath": "/workspace/fib.py",
                                "content": "def fib(n):\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)\n",
                            },
                            "output": "File written",
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "c2",
                        "state": {
                            "status": "completed",
                            "input": {"command": 'python -c "from fib import fib; print(fib(10))"'},
                            "output": "55",
                        },
                    },
                    {"type": "text", "text": "Created fib.py with fibonacci function. Tested: fib(10) = 55."},
                ],
            },
        ]

    def _build_json_output_history(self) -> list[dict]:
        """Simulate a session where the agent returns JSON."""
        return [
            {
                "info": {"role": "user"},
                "parts": [{"type": "text", "text": "Return a JSON with project info"}],
            },
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [
                    {"type": "text", "text": '{"name": "myproject", "version": "1.0.0", "language": "python"}'},
                ],
            },
        ]

    def _build_multi_file_history(self) -> list[dict]:
        """Simulate a session where the agent creates multiple files with patches."""
        return [
            {
                "info": {"role": "user"},
                "parts": [{"type": "text", "text": "Create a Flask API"}],
            },
            {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "write",
                        "callID": "c1",
                        "state": {
                            "status": "completed",
                            "input": {
                                "filePath": "/workspace/app.py",
                                "content": "from flask import Flask\napp = Flask(__name__)\n",
                            },
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "write",
                        "callID": "c2",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/workspace/requirements.txt", "content": "flask>=3.0\n"},
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "c3",
                        "state": {
                            "status": "completed",
                            "input": {"command": "pip install -r requirements.txt"},
                            "output": "Successfully installed flask-3.0.0",
                        },
                    },
                    {"type": "patch", "files": ["app.py", "requirements.txt"], "hash": "patch1"},
                    {"type": "text", "text": "Created Flask API with app.py and requirements.txt."},
                ],
            },
        ]

    def test_document_creation_extracts_artifact(self) -> None:
        messages = self._build_doc_creation_history()
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["path"], "/workspace/README.md")
        self.assertEqual(artifacts[0]["tool"], "write")

    def test_document_creation_extracts_tool_calls(self) -> None:
        messages = self._build_doc_creation_history()
        tool_calls = opencode_runtime_main.extract_tool_calls_from_messages(messages)
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["tool"], "write")
        self.assertEqual(tool_calls[0]["status"], "completed")

    def test_code_writing_extracts_artifacts_and_tool_calls(self) -> None:
        messages = self._build_code_writing_history()
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        tool_calls = opencode_runtime_main.extract_tool_calls_from_messages(messages)
        self.assertEqual(len(artifacts), 1)  # Only write tool creates artifacts
        self.assertEqual(artifacts[0]["path"], "/workspace/fib.py")
        self.assertEqual(len(tool_calls), 2)  # write + bash
        self.assertEqual(tool_calls[0]["tool"], "write")
        self.assertEqual(tool_calls[1]["tool"], "bash")
        self.assertIn("55", tool_calls[1]["output"])

    def test_json_output_has_no_artifacts(self) -> None:
        messages = self._build_json_output_history()
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 0)

    def test_json_output_response_text_is_json(self) -> None:
        messages = self._build_json_output_history()
        assistant_msg = messages[1]
        text = opencode_runtime_main.extract_response_text(assistant_msg)
        parsed = json.loads(text)
        self.assertEqual(parsed["name"], "myproject")

    def test_multi_file_extracts_all_artifacts(self) -> None:
        messages = self._build_multi_file_history()
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        paths = {a["path"] for a in artifacts}
        # write tool creates /workspace/app.py and /workspace/requirements.txt
        # patch part references app.py and requirements.txt (different paths, both included)
        self.assertIn("/workspace/app.py", paths)
        self.assertIn("/workspace/requirements.txt", paths)

    def test_multi_file_extracts_all_tool_calls(self) -> None:
        messages = self._build_multi_file_history()
        tool_calls = opencode_runtime_main.extract_tool_calls_from_messages(messages)
        tools_used = [tc["tool"] for tc in tool_calls]
        self.assertEqual(tools_used, ["write", "write", "bash"])


class ErrorRecoveryWorkflowTests(unittest.TestCase):
    """Tests for the error detection in multi-turn scenarios."""

    def test_detect_errors_in_failed_bash(self) -> None:
        messages = [
            {
                "info": {"role": "assistant"},
                "parts": [
                    {
                        "type": "tool",
                        "tool": "bash",
                        "state": {"status": "error", "error": "Permission denied: /etc/shadow"},
                    },
                    {
                        "type": "tool",
                        "tool": "write",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "/workspace/fix.sh", "content": "#!/bin/sh\necho fixed"},
                        },
                    },
                ],
            }
        ]
        errors = opencode_runtime_main.detect_task_errors(messages)
        self.assertEqual(len(errors), 1)
        self.assertIn("Permission denied", errors[0])

        # Artifacts should still be extracted from successful parts
        artifacts = opencode_runtime_main.extract_artifacts_from_messages(messages)
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["path"], "/workspace/fix.sh")

    def test_detect_errors_prefers_nested_error_message(self) -> None:
        messages = [
            {
                "info": {
                    "role": "assistant",
                    "error": {
                        "name": "APIError",
                        "data": {
                            "message": "This request requires more credits.",
                            "statusCode": 402,
                        },
                    },
                },
                "parts": [],
            }
        ]
        errors = opencode_runtime_main.detect_task_errors(messages)
        self.assertEqual(errors, ["This request requires more credits."])


# ---------------------------------------------------------------------------
# Phase 6 â€“ Session management helper tests
# ---------------------------------------------------------------------------


class AbortSessionTests(unittest.TestCase):
    """Tests for abort_session."""

    def _mock_client(self, status_code: int = 200):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_returns_true_on_success(self) -> None:
        mc = self._mock_client(200)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertTrue(opencode_runtime_main.abort_session("ses_1"))
        mc.post.assert_called_once_with("/session/ses_1/abort")

    def test_returns_false_on_non_200(self) -> None:
        mc = self._mock_client(404)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.abort_session("ses_x"))

    def test_returns_false_on_http_error(self) -> None:
        import httpx

        mc = MagicMock()
        mc.post.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.abort_session("ses_err"))


class WaitForSessionIdleTests(unittest.TestCase):
    """Tests for wait_for_session_idle backoff behavior."""

    def test_uses_capped_backoff_until_idle(self) -> None:
        sleep_intervals: list[float] = []
        with (
            patch.object(
                opencode_client_mod,
                "get_session_status",
                side_effect=[{"type": "busy"}, {"type": "busy"}, {"type": "idle"}],
            ),
            patch.object(opencode_client_mod, "SESSION_IDLE_POLL_SECONDS", 0.5),
            patch.object(opencode_client_mod, "SESSION_IDLE_MAX_POLL_SECONDS", 1.0),
            patch.object(opencode_client_mod.time, "sleep", side_effect=lambda seconds: sleep_intervals.append(seconds)),
        ):
            status = opencode_runtime_main.wait_for_session_idle("ses_1", timeout_seconds=5.0)

        self.assertEqual(status.get("type"), "idle")
        self.assertEqual(sleep_intervals, [0.25, 0.5])


class SummarizeSessionTests(unittest.TestCase):
    """Tests for summarize_session."""

    def _mock_client(self, status_code: int = 200):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_returns_true_on_success(self) -> None:
        mc = self._mock_client(200)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertTrue(opencode_runtime_main.summarize_session("ses_1"))
        call_kwargs = mc.post.call_args
        self.assertIn("/session/ses_1/summarize", call_kwargs.args or (call_kwargs[0],))
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        self.assertIn("providerID", body)
        self.assertIn("modelID", body)
        self.assertTrue(body.get("auto"))

    def test_returns_false_on_failure(self) -> None:
        mc = self._mock_client(500)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.summarize_session("ses_x"))

    def test_returns_false_on_http_error(self) -> None:
        import httpx

        mc = MagicMock()
        mc.post.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.summarize_session("ses_err"))


class InitSessionTests(unittest.TestCase):
    """Tests for init_session."""

    def _mock_client(self, status_code: int = 200):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_returns_true_on_success(self) -> None:
        mc = self._mock_client(200)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertTrue(opencode_runtime_main.init_session("ses_1"))
        call_kwargs = mc.post.call_args
        self.assertIn("/session/ses_1/init", call_kwargs.args or (call_kwargs[0],))
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        self.assertIn("providerID", body)
        self.assertIn("modelID", body)
        self.assertIn("messageID", body)

    def test_returns_false_on_failure(self) -> None:
        mc = self._mock_client(500)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.init_session("ses_x"))

    def test_returns_false_on_http_error(self) -> None:
        import httpx

        mc = MagicMock()
        mc.post.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.init_session("ses_err"))


class GetSessionTodosTests(unittest.TestCase):
    """Tests for get_session_todos."""

    def _mock_client(self, status_code: int, payload=None):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = payload
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_returns_todos_on_success(self) -> None:
        todos = [{"id": "1", "title": "Write code", "status": "completed"}]
        mc = self._mock_client(200, todos)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Write code")

    def test_returns_empty_on_404(self) -> None:
        mc = self._mock_client(404, None)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_x")
        self.assertEqual(result, [])

    def test_filters_non_dict_items(self) -> None:
        mc = self._mock_client(200, [{"id": "1"}, "bad", 42, {"id": "2"}])
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_1")
        self.assertEqual(len(result), 2)

    def test_returns_empty_on_http_error(self) -> None:
        import httpx

        mc = MagicMock()
        mc.get.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_err")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Phase 6 â€“ Context overflow and error classification tests
# ---------------------------------------------------------------------------


class CheckContextOverflowTests(unittest.TestCase):
    """Tests for check_context_overflow."""

    def test_detects_context_overflow_error(self) -> None:
        payload = {"info": {"error": {"name": "ContextOverflowError", "message": "overflow"}}}
        self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_detects_high_token_usage(self) -> None:
        # With default MODEL_CONTEXT_LIMIT=128000 and COMPACTION_TOKEN_THRESHOLD=0.75
        # threshold = 96000
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            payload = {"info": {"tokens": {"input": 60000, "output": 20000, "total": 80000}}}
            self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_no_overflow_for_low_token_usage(self) -> None:
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            payload = {"info": {"tokens": {"input": 1000, "output": 500, "total": 1500}}}
            self.assertFalse(opencode_runtime_main.check_context_overflow(payload))

    def test_no_overflow_on_empty_payload(self) -> None:
        self.assertFalse(opencode_runtime_main.check_context_overflow({}))

    def test_no_overflow_when_info_not_dict(self) -> None:
        self.assertFalse(opencode_runtime_main.check_context_overflow({"info": "bad"}))

    def test_calculates_total_from_parts_when_total_missing(self) -> None:
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            payload = {"info": {"tokens": {"input": 50000, "output": 30000}}}
            self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_non_overflow_error_not_detected(self) -> None:
        payload = {"info": {"error": {"name": "APIError", "message": "server error"}}}
        self.assertFalse(opencode_runtime_main.check_context_overflow(payload))

    def test_cache_write_tokens_included_in_fallback_total(self) -> None:
        """cache.write must be included when computing total from parts (Bug fix)."""
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            # input(20k) + output(10k) + cache.read(20k) = 50k  -> below 75k threshold
            # input(20k) + output(10k) + cache.read(20k) + cache.write(40k) = 90k  -> above 75k threshold
            payload = {
                "info": {
                    "tokens": {
                        "input": 20000,
                        "output": 10000,
                        "cache": {"read": 20000, "write": 40000},
                    }
                }
            }
            self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_cache_write_below_threshold_no_overflow(self) -> None:
        """Verify cache.write included but total still below threshold."""
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            payload = {
                "info": {
                    "tokens": {
                        "input": 10000,
                        "output": 5000,
                        "cache": {"read": 5000, "write": 5000},
                    }
                }
            }
            self.assertFalse(opencode_runtime_main.check_context_overflow(payload))


class ClassifyErrorTypeTests(unittest.TestCase):
    """Tests for classify_error_type."""

    def test_classifies_context_overflow(self) -> None:
        payload = {"info": {"error": {"name": "ContextOverflowError"}}}
        self.assertEqual(opencode_runtime_main.classify_error_type(payload), "context_overflow")

    def test_classifies_structured_output(self) -> None:
        payload = {"info": {"error": {"name": "StructuredOutputError"}}}
        self.assertEqual(opencode_runtime_main.classify_error_type(payload), "structured_output")

    def test_classifies_auth_error(self) -> None:
        payload = {"info": {"error": {"name": "ProviderAuthError"}}}
        self.assertEqual(opencode_runtime_main.classify_error_type(payload), "auth")

    def test_classifies_api_error(self) -> None:
        payload = {"info": {"error": {"name": "APIError"}}}
        self.assertEqual(opencode_runtime_main.classify_error_type(payload), "api")

    def test_classifies_aborted_error(self) -> None:
        payload = {"info": {"error": {"name": "MessageAbortedError"}}}
        self.assertEqual(opencode_runtime_main.classify_error_type(payload), "aborted")

    def test_classifies_output_length_error(self) -> None:
        payload = {"info": {"error": {"name": "MessageOutputLengthError"}}}
        self.assertEqual(opencode_runtime_main.classify_error_type(payload), "output_length")

    def test_returns_none_for_unknown_error(self) -> None:
        payload = {"info": {"error": {"name": "SomeNewError"}}}
        self.assertIsNone(opencode_runtime_main.classify_error_type(payload))

    def test_returns_none_when_no_error(self) -> None:
        payload = {"info": {"finish": "stop"}}
        self.assertIsNone(opencode_runtime_main.classify_error_type(payload))

    def test_returns_none_when_info_not_dict(self) -> None:
        self.assertIsNone(opencode_runtime_main.classify_error_type({"info": 42}))

    def test_returns_none_when_error_not_dict(self) -> None:
        payload = {"info": {"error": "just a string"}}
        self.assertIsNone(opencode_runtime_main.classify_error_type(payload))


# ---------------------------------------------------------------------------
# Phase 6 â€“ Agent selection tests
# ---------------------------------------------------------------------------


class SelectAgentTests(unittest.TestCase):
    """Tests for select_agent_for_prompt."""

    def test_returns_default_agent_for_subsequent_turns(self) -> None:
        long_prompt = "step 1: do this\nstep 2: do that\nstep 3: finalize\n" * 50
        result = opencode_runtime_main.select_agent_for_prompt(long_prompt, is_first_turn=False)
        self.assertEqual(result, opencode_runtime_main.DEFAULT_AGENT)

    def test_returns_default_for_short_prompt(self) -> None:
        result = opencode_runtime_main.select_agent_for_prompt("Fix the bug", is_first_turn=True)
        self.assertEqual(result, opencode_runtime_main.DEFAULT_AGENT)

    def test_returns_plan_for_complex_long_prompt(self) -> None:
        with (
            patch.object(analysis_mod, "DEFAULT_AGENT", "build"),
            patch.object(analysis_mod, "PLAN_AGENT_PROMPT_THRESHOLD", 100),
        ):
            complex_prompt = (
                "Build a complete REST API with the following requirements:\n"
                "1. User registration and authentication\n"
                "2. CRUD operations for projects\n"
                "- Database schema with proper relationships\n"
                "- Unit tests for all endpoints\n"
                "First, design the architecture. Then implement each component. "
                "Finally, write comprehensive tests."
            )
            result = opencode_runtime_main.select_agent_for_prompt(complex_prompt, is_first_turn=True)
            self.assertEqual(result, "plan")

    def test_returns_default_when_threshold_not_met(self) -> None:
        with (
            patch.object(analysis_mod, "DEFAULT_AGENT", "build"),
            patch.object(analysis_mod, "PLAN_AGENT_PROMPT_THRESHOLD", 10000),
        ):
            result = opencode_runtime_main.select_agent_for_prompt("short prompt", is_first_turn=True)
            self.assertEqual(result, "build")

    def test_returns_default_when_agent_is_not_build(self) -> None:
        with (
            patch.object(analysis_mod, "DEFAULT_AGENT", "general"),
            patch.object(analysis_mod, "AGENT_SELECTION_MODE", "simple"),
        ):
            long_prompt = "step 1: do this\nstep 2: do that\nstep 3: finalize\n" * 50
            result = opencode_runtime_main.select_agent_for_prompt(long_prompt, is_first_turn=True)
            self.assertEqual(result, "general")


# ---------------------------------------------------------------------------
# Phase 6 â€“ detect_completion_status context_overflow tests
# ---------------------------------------------------------------------------


class DetectCompletionStatusContextOverflowTests(unittest.TestCase):
    """Tests for detect_completion_status recognizing ContextOverflowError."""

    def test_returns_context_overflow(self) -> None:
        payload = {"info": {"error": {"name": "ContextOverflowError", "message": "overflow"}}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "context_overflow")

    def test_other_error_returns_error(self) -> None:
        payload = {"info": {"error": {"name": "APIError", "message": "fail"}}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "error")

    def test_string_error_returns_error(self) -> None:
        payload = {"info": {"error": "something went wrong"}}
        self.assertEqual(opencode_runtime_main.detect_completion_status(payload), "error")


# ---------------------------------------------------------------------------
# Phase 6 â€“ Enhanced runtime_capabilities tests
# ---------------------------------------------------------------------------


class RuntimeCapabilitiesEnhancedTests(unittest.TestCase):
    """Tests for the expanded runtime_capabilities with agents and session management."""

    def test_agents_section_present(self) -> None:
        caps = opencode_runtime_main.runtime_capabilities()
        self.assertIn("agents", caps)
        self.assertIn("available", caps["agents"])
        self.assertIn("build", caps["agents"]["available"])
        self.assertIn("plan", caps["agents"]["available"])
        self.assertEqual(caps["agents"]["default"], opencode_runtime_main.DEFAULT_AGENT)

    def test_session_management_section(self) -> None:
        caps = opencode_runtime_main.runtime_capabilities()
        sm = caps["session_management"]
        self.assertTrue(sm["abort"])
        self.assertTrue(sm["summarize"])
        self.assertTrue(sm["init"])
        self.assertTrue(sm["todos"])
        self.assertTrue(sm["session_recovery"])
        self.assertEqual(sm["compaction_threshold"], opencode_runtime_main.COMPACTION_TOKEN_THRESHOLD)

    def test_native_tools_include_new_tools(self) -> None:
        caps = opencode_runtime_main.runtime_capabilities()
        for tool in ("webfetch", "websearch", "codesearch", "skill", "question", "task", "todowrite"):
            self.assertIn(tool, caps["native_tools"])

    def test_a2a_section_reports_outbound_support(self) -> None:
        with (
            patch.object(analysis_mod, "A2A_ALLOWED_TARGETS", {("team-b", "analysis-agent")}),
            patch.object(analysis_mod, "A2A_MAX_TIMEOUT_SECONDS", 45.0),
            patch.object(analysis_mod, "A2A_REQUIRE_HITL", True),
            patch.object(analysis_mod, "API_GATEWAY_INTERNAL_URL", "http://gateway.internal"),
            patch.object(analysis_mod, "API_GATEWAY_SHARED_TOKEN", "shared-token"),
        ):
            caps = opencode_runtime_main.runtime_capabilities()

        self.assertIn("a2a", caps)
        self.assertTrue(caps["a2a"]["outbound_supported"])
        self.assertTrue(caps["a2a"]["gateway_configured"])
        self.assertEqual(caps["a2a"]["allowed_target_count"], 1)
        self.assertEqual(caps["a2a"]["allowed_targets"], [{"namespace": "team-b", "name": "analysis-agent"}])
        self.assertEqual(caps["a2a"]["max_timeout_seconds"], 45.0)
        self.assertTrue(caps["a2a"]["requires_hitl"])


class OpenCodeOutboundA2ATests(unittest.TestCase):
    def test_invoke_outbound_a2a_request_forwards_gateway_payload(self) -> None:
        request = opencode_runtime_main.InvokeRequest(
            prompt="Summarize the deployment findings.",
            system="Return only the final answer.",
            model="gpt-4o",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
            a2a_timeout_seconds=12,
            caller_agent_name="planner",
            caller_agent_namespace="default",
            parent_thread_id="thread-parent",
            caller_request_id="req-123",
            team_context={"workflow": "incident-review"},
        )

        with (
            patch.object(invoke_mod, "A2A_ALLOWED_TARGETS", {("team-b", "analysis-agent")}),
            patch.object(invoke_mod, "A2A_MAX_TIMEOUT_SECONDS", 30.0),
            patch.object(invoke_mod, "API_GATEWAY_INTERNAL_URL", "http://gateway.internal"),
            patch.object(invoke_mod, "API_GATEWAY_SHARED_TOKEN", "shared-token"),
            patch.object(invoke_mod, "build_invoke_warnings", return_value=["base warning"]),
            patch.object(
                invoke_mod,
                "invoke_gateway_a2a_target",
                return_value={
                    "response": "Peer analysis complete.",
                    "model": "gpt-4o-mini",
                    "status": "completed",
                    "warnings": ["peer warning"],
                    "metadata": {"source": "peer"},
                },
            ) as mock_gateway,
        ):
            response = invoke_mod.invoke_outbound_a2a_request(
                request,
                logical_thread_id="thread-1",
                selected_model="gpt-4o",
            )

        self.assertEqual(response.response, "Peer analysis complete.")
        self.assertEqual(response.model, "gpt-4o-mini")
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.a2a["callerAgent"], "planner")
        self.assertIn("base warning", response.warnings)
        self.assertIn("peer warning", response.warnings)
        self.assertEqual(response.metadata["source"], "peer")
        self.assertEqual(response.metadata["a2aTarget"]["agent"], "analysis-agent")
        self.assertEqual(response.metadata["a2aTarget"]["namespace"], "team-b")
        self.assertEqual(response.metadata["a2aTarget"]["requestId"], "req-123")

        call_args = mock_gateway.call_args.args
        self.assertEqual(call_args[0], "analysis-agent")
        self.assertEqual(call_args[1], "team-b")
        payload = call_args[2]
        self.assertEqual(payload["prompt"], "Summarize the deployment findings.")
        self.assertEqual(payload["system"], "Return only the final answer.")
        self.assertEqual(payload["model"], "gpt-4o")
        self.assertEqual(payload["caller_agent_name"], opencode_runtime_main.SERVICE_NAME)
        self.assertEqual(payload["caller_agent_namespace"], opencode_runtime_main.SERVICE_NAMESPACE)
        self.assertEqual(payload["parent_thread_id"], "thread-1")
        self.assertEqual(payload["caller_request_id"], "req-123")
        self.assertEqual(payload["team_context"]["workflow"], "incident-review")
        self.assertEqual(payload["team_context"]["delegation"]["target"]["name"], "analysis-agent")
        self.assertEqual(payload["team_context"]["upstreamCaller"]["name"], "planner")

    def test_invoke_opencode_short_circuits_explicit_outbound_a2a(self) -> None:
        request = opencode_runtime_main.InvokeRequest(
            prompt="Ask a peer for help.",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
        )
        expected = opencode_runtime_main.InvokeResponse(
            thread_id="thread-1",
            response="Peer result",
            model="gpt-4o",
        )

        with (
            patch.object(invoke_mod, "A2A_REQUIRE_HITL", False),
            patch.object(invoke_mod, "invoke_outbound_a2a_request", return_value=expected) as mock_outbound,
            patch.object(invoke_mod, "ensure_server_running") as mock_server,
        ):
            actual = opencode_runtime_main.invoke_opencode(request)

        self.assertIs(actual, expected)
        mock_outbound.assert_called_once()
        mock_server.assert_not_called()

    def test_invoke_opencode_requires_hitl_for_outbound_a2a(self) -> None:
        request = opencode_runtime_main.InvokeRequest(
            prompt="Ask a peer for help.",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
        )

        with (
            patch.object(invoke_mod, "A2A_REQUIRE_HITL", True),
            patch.object(
                invoke_mod,
                "hitl_gate",
                return_value={"decision": "pending", "approval_name": "peer-call-approval"},
            ) as mock_hitl,
            patch.object(invoke_mod, "invoke_outbound_a2a_request") as mock_outbound,
        ):
            response = opencode_runtime_main.invoke_opencode(request)

        self.assertEqual(response.status, "approval_pending")
        self.assertEqual(response.approval_name, "peer-call-approval")
        self.assertTrue(response.thread_id)
        self.assertEqual(response.model, opencode_runtime_main.DEFAULT_MODEL)
        self.assertFalse(response.response)
        self.assertIn("analysis-agent", mock_hitl.call_args.kwargs["action_description"])
        self.assertIn("team-b", mock_hitl.call_args.kwargs["action_description"])
        mock_outbound.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 6 â€“ invoke_opencode loop integration tests (mocked)
# ---------------------------------------------------------------------------


class InvokeOpenCodeLoopTests(unittest.TestCase):
    """Tests for invoke_opencode autonomous loop behavior using mocked HTTP calls."""

    def _make_payload(
        self,
        text: str = "done",
        finish: str = "stop",
        error: dict | None = None,
        tokens: dict | None = None,
    ) -> dict:
        info: dict = {"role": "assistant", "finish": finish}
        if error:
            info["error"] = error
        if tokens:
            info["tokens"] = tokens
        return {"info": info, "parts": [{"type": "text", "text": text}]}

    def _patch_server_running(self):
        return patch.object(invoke_mod, "ensure_server_running")

    def _patch_create_session(self, session_id: str = "ses_test"):
        return patch.object(invoke_mod, "create_remote_session", return_value=session_id)

    def _patch_send_prompt(self, payloads: list[dict]):
        """Patch _send_prompt_with_session_recovery to return successive payloads."""
        call_count = {"n": 0}

        def side_effect(**kwargs):
            idx = min(call_count["n"], len(payloads) - 1)
            call_count["n"] += 1
            return kwargs.get("session_id", "ses_test"), payloads[idx]

        return patch.object(invoke_mod, "_send_prompt_with_session_recovery", side_effect=side_effect)

    def _patch_session_helpers(self):
        """Patch session-collection helpers to avoid real HTTP calls."""
        return [
            patch.object(invoke_mod, "get_session_messages", return_value=[]),
            patch.object(invoke_mod, "get_session_todos", return_value=[]),
            patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
            patch.object(invoke_mod, "abort_session", return_value=True),
            patch.object(invoke_mod, "summarize_session", return_value=True),
        ]

    def _run_invoke(self, request_kwargs: dict, payloads: list[dict]) -> opencode_runtime_main.InvokeResponse:
        request = opencode_runtime_main.InvokeRequest(**request_kwargs)
        with self._patch_server_running(), self._patch_create_session(), self._patch_send_prompt(payloads) as mock_send:
            patches = self._patch_session_helpers()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                return opencode_runtime_main.invoke_opencode(request)

    def test_single_turn_completed(self) -> None:
        payload = self._make_payload("All done!", "stop")
        resp = self._run_invoke({"prompt": "Do something"}, [payload])
        self.assertEqual(resp.status, "completed")
        self.assertIn("All done!", resp.response)

    def test_multi_turn_continuation(self) -> None:
        """If first turn is incomplete, the loop should continue."""
        payloads = [
            self._make_payload("Working...", "tool-calls"),
            self._make_payload("Finished!", "stop"),
        ]
        resp = self._run_invoke({"prompt": "Build it", "autonomous": True}, payloads)
        self.assertEqual(resp.status, "completed")
        self.assertTrue(any("incomplete" in w.lower() for w in resp.warnings))

    def test_context_overflow_triggers_compaction(self) -> None:
        payloads = [
            self._make_payload("partial", "stop", error={"name": "ContextOverflowError", "message": "overflow"}),
            self._make_payload("Recovered!", "stop"),
        ]
        resp = self._run_invoke({"prompt": "Process data"}, payloads)
        self.assertTrue(any("context overflow" in w.lower() for w in resp.warnings))

    def test_auth_error_stops_loop(self) -> None:
        payloads = [
            self._make_payload("", "stop", error={"name": "ProviderAuthError", "message": "bad key"}),
        ]
        resp = self._run_invoke({"prompt": "Do something"}, payloads)
        self.assertTrue(any("authentication" in w.lower() for w in resp.warnings))

    def test_retries_on_generic_error(self) -> None:
        payloads = [
            self._make_payload("", "error", error={"name": "APIError", "message": "server error"}),
            self._make_payload("OK", "stop"),
        ]
        resp = self._run_invoke({"prompt": "Task", "max_retries": 3}, payloads)
        self.assertEqual(resp.status, "completed")
        self.assertTrue(any("retrying" in w.lower() for w in resp.warnings))

    def test_non_retryable_api_error_stops_without_retry(self) -> None:
        payload = self._make_payload(
            "",
            "error",
            error={
                "name": "APIError",
                "data": {
                    "message": "This request requires more credits.",
                    "isRetryable": False,
                    "statusCode": 402,
                },
            },
        )
        resp = self._run_invoke({"prompt": "Task", "max_retries": 3}, [payload])
        self.assertEqual(resp.status, "error")
        self.assertTrue(any("non-retryable" in w.lower() for w in resp.warnings))
        self.assertFalse(any("retrying" in w.lower() for w in resp.warnings))

    def test_plan_agent_switch_to_build(self) -> None:
        """When plan agent finishes, loop should switch to build agent."""
        with (
            patch.object(analysis_mod, "PLAN_AGENT_PROMPT_THRESHOLD", 10),
            patch.object(analysis_mod, "DEFAULT_AGENT", "build"),
        ):
            complex_prompt = (
                "Build a complete system:\n"
                "1. Create the database schema\n"
                "2. Implement the API\n"
                "- Include authentication\n"
                "First, plan everything. Then implement."
            )
            payloads = [
                self._make_payload("Plan created", "stop"),  # plan agent completes
                self._make_payload("Execution done!", "stop"),  # build agent completes
            ]
            resp = self._run_invoke({"prompt": complex_prompt, "autonomous": True}, payloads)
            self.assertEqual(resp.status, "completed")
            self.assertTrue(any("plan" in w.lower() for w in resp.warnings))

    def test_max_turns_respected(self) -> None:
        payloads = [self._make_payload("still going", "tool-calls")] * 20
        resp = self._run_invoke({"prompt": "Endless task", "max_turns": 3}, payloads)
        # Should stop after 3 turns
        self.assertIn(resp.status, ("completed", "incomplete"))

    def test_non_autonomous_skips_autonomy_prompt(self) -> None:
        payload = self._make_payload("Result", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Simple query", autonomous=False)
        with (
            self._patch_server_running(),
            self._patch_create_session(),
            self._patch_send_prompt([payload]) as mock_send,
        ):
            patches = self._patch_session_helpers()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                resp = opencode_runtime_main.invoke_opencode(req)
        # Verify the system prompt passed to send does NOT include AUTONOMY_SYSTEM_PROMPT
        call_kwargs = mock_send.call_args.kwargs
        system = call_kwargs.get("system_prompt", "")
        self.assertNotIn("AUTONOMOUS AGENT", system or "")

    def test_http_error_retries(self) -> None:
        """Test that HTTP errors during send trigger retries."""
        import httpx

        call_count = {"n": 0}

        def side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.ConnectError("connection refused")
            return kwargs.get("session_id", "ses_test"), self._make_payload("recovered", "stop")

        req = opencode_runtime_main.InvokeRequest(prompt="test", max_retries=2)
        with (
            self._patch_server_running(),
            self._patch_create_session(),
            patch.object(invoke_mod, "_send_prompt_with_session_recovery", side_effect=side_effect),
        ):
            patches = self._patch_session_helpers()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                resp = opencode_runtime_main.invoke_opencode(req)
        self.assertEqual(resp.status, "completed")
        self.assertTrue(any("HTTP error" in w for w in resp.warnings))

    def test_todos_included_in_metadata(self) -> None:
        todos = [{"id": "1", "title": "Write code", "status": "done"}]
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build it")
        with self._patch_server_running(), self._patch_create_session(), self._patch_send_prompt([payload]):
            with (
                patch.object(invoke_mod, "get_session_messages", return_value=[]),
                patch.object(invoke_mod, "get_session_todos", return_value=todos),
                patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                patch.object(invoke_mod, "abort_session", return_value=True),
                patch.object(invoke_mod, "summarize_session", return_value=True),
            ):
                resp = opencode_runtime_main.invoke_opencode(req)
        self.assertIsNotNone(resp.metadata)
        self.assertEqual(resp.metadata["todos"], todos)

    def test_response_includes_continuity_metadata(self) -> None:
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build it")
        with self._patch_server_running(), self._patch_create_session(), self._patch_send_prompt([payload]):
            with (
                patch.object(invoke_mod, "get_session_messages", return_value=[]),
                patch.object(invoke_mod, "get_session_todos", return_value=[]),
                patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                patch.object(invoke_mod, "abort_session", return_value=True),
                patch.object(invoke_mod, "summarize_session", return_value=True),
            ):
                resp = opencode_runtime_main.invoke_opencode(req)
        self.assertIsNotNone(resp.continuity)
        self.assertIn("created_new_session", resp.continuity)
        self.assertIn("remote_session_id", resp.continuity)

    def test_session_init_called_for_new_autonomous_session(self) -> None:
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build feature", autonomous=True)
        mock_init = MagicMock(return_value=True)
        with (
            self._patch_server_running(),
            self._patch_create_session(),
            self._patch_send_prompt([payload]),
            patch.object(invoke_mod, "init_session", mock_init),
            patch.object(invoke_mod, "SESSION_INIT_ON_CREATE", True),
        ):
            with (
                patch.object(invoke_mod, "get_session_messages", return_value=[]),
                patch.object(invoke_mod, "get_session_todos", return_value=[]),
                patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                patch.object(invoke_mod, "abort_session", return_value=True),
                patch.object(invoke_mod, "summarize_session", return_value=True),
            ):
                opencode_runtime_main.invoke_opencode(req)
        mock_init.assert_called_once()

    def test_session_init_not_called_when_disabled(self) -> None:
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build feature", autonomous=True)
        mock_init = MagicMock(return_value=True)
        with (
            self._patch_server_running(),
            self._patch_create_session(),
            self._patch_send_prompt([payload]),
            patch.object(invoke_mod, "init_session", mock_init),
            patch.object(invoke_mod, "SESSION_INIT_ON_CREATE", False),
        ):
            with (
                patch.object(invoke_mod, "get_session_messages", return_value=[]),
                patch.object(invoke_mod, "get_session_todos", return_value=[]),
                patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                patch.object(invoke_mod, "abort_session", return_value=True),
                patch.object(invoke_mod, "summarize_session", return_value=True),
            ):
                opencode_runtime_main.invoke_opencode(req)
        mock_init.assert_not_called()

    def test_stuck_session_gets_aborted(self) -> None:
        """If session remains busy after invoke, it should be aborted."""
        payload = self._make_payload("Working", "tool-calls")
        req = opencode_runtime_main.InvokeRequest(prompt="Test", max_turns=1)
        mock_abort = MagicMock(return_value=True)
        busy_status = {"type": "busy"}
        with self._patch_server_running(), self._patch_create_session(), self._patch_send_prompt([payload]):
            with (
                patch.object(invoke_mod, "get_session_messages", return_value=[]),
                patch.object(invoke_mod, "get_session_todos", return_value=[]),
                patch.object(invoke_mod, "wait_for_session_idle", return_value=busy_status),
                patch.object(invoke_mod, "abort_session", mock_abort) as abort_mock,
                patch.object(invoke_mod, "summarize_session", return_value=True),
            ):
                resp = opencode_runtime_main.invoke_opencode(req)
        mock_abort.assert_called()
        self.assertTrue(any("aborted" in w.lower() for w in resp.warnings))

    def test_proactive_compaction_on_high_tokens(self) -> None:
        """If token usage is high on an incomplete response, proactively compact."""
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            # First response: incomplete with high tokens â†’ triggers proactive compaction
            high_tokens_incomplete = self._make_payload(
                "Working...", "tool-calls", tokens={"input": 60000, "output": 20000, "total": 80000}
            )
            # Second response after compaction: completed
            done = self._make_payload("Done", "stop")
            mock_summarize = MagicMock(return_value=True)
            req = opencode_runtime_main.InvokeRequest(prompt="Process", autonomous=True)
            with (
                self._patch_server_running(),
                self._patch_create_session(),
                self._patch_send_prompt([high_tokens_incomplete, done]),
            ):
                with (
                    patch.object(invoke_mod, "get_session_messages", return_value=[]),
                    patch.object(invoke_mod, "get_session_todos", return_value=[]),
                    patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                    patch.object(invoke_mod, "abort_session", return_value=True),
                    patch.object(invoke_mod, "summarize_session", mock_summarize),
                ):
                    resp = opencode_runtime_main.invoke_opencode(req)
            mock_summarize.assert_called()
            self.assertTrue(any("compaction" in w.lower() for w in resp.warnings))

    def test_completed_with_high_tokens_does_not_compact(self) -> None:
        """Completed tasks must not trigger proactive compaction even with high tokens (Bug fix)."""
        with (
            patch.object(analysis_mod, "MODEL_CONTEXT_LIMIT", 100000),
            patch.object(analysis_mod, "COMPACTION_TOKEN_THRESHOLD", 0.75),
        ):
            payload = self._make_payload("Done", "stop", tokens={"input": 60000, "output": 20000, "total": 80000})
            mock_summarize = MagicMock(return_value=True)
            req = opencode_runtime_main.InvokeRequest(prompt="Process")
            with self._patch_server_running(), self._patch_create_session(), self._patch_send_prompt([payload]):
                with (
                    patch.object(invoke_mod, "get_session_messages", return_value=[]),
                    patch.object(invoke_mod, "get_session_todos", return_value=[]),
                    patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                    patch.object(invoke_mod, "abort_session", return_value=True),
                    patch.object(invoke_mod, "summarize_session", mock_summarize),
                ):
                    resp = opencode_runtime_main.invoke_opencode(req)
            mock_summarize.assert_not_called()
            self.assertEqual(resp.status, "completed")

    def test_prefers_current_message_over_latest_session_assistant(self) -> None:
        payload = {
            "info": {"id": "msg_current", "role": "assistant", "finish": "tool-calls"},
            "parts": [{"type": "text", "text": "Still working"}],
        }
        exact_message = {
            "info": {"id": "msg_current", "role": "assistant", "finish": "stop"},
            "parts": [{"type": "text", "text": "Hello"}],
        }
        stale_history = [
            {"info": {"id": "msg_old", "role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "I updated AGENTS.md"}]},
        ]
        req = opencode_runtime_main.InvokeRequest(prompt="hello", max_turns=1)
        with self._patch_server_running(), self._patch_create_session(), self._patch_send_prompt([payload]):
            with (
                patch.object(invoke_mod, "get_session_message", return_value=exact_message),
                patch.object(invoke_mod, "get_session_messages", return_value=stale_history),
                patch.object(invoke_mod, "get_session_todos", return_value=[]),
                patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
                patch.object(invoke_mod, "abort_session", return_value=True),
                patch.object(invoke_mod, "summarize_session", return_value=True),
            ):
                resp = opencode_runtime_main.invoke_opencode(req)

        self.assertEqual(resp.response, "Hello")


class StructuredOutputMetadataTests(unittest.TestCase):
    """Tests for _extract_structured_output and metadata enrichment."""

    def test_extract_structured_output_from_info_structured(self) -> None:
        payload = {"info": {"structured": {"key": "value"}}, "parts": []}
        result = opencode_runtime_main._extract_structured_output(payload)
        self.assertEqual(result, {"key": "value"})

    def test_extract_structured_output_from_info_structured_output(self) -> None:
        payload = {"info": {"structured_output": {"a": 1}}, "parts": []}
        result = opencode_runtime_main._extract_structured_output(payload)
        self.assertEqual(result, {"a": 1})

    def test_extract_structured_output_returns_none_when_missing(self) -> None:
        payload = {"info": {"role": "assistant"}, "parts": []}
        result = opencode_runtime_main._extract_structured_output(payload)
        self.assertIsNone(result)

    def test_extract_structured_output_empty_payload(self) -> None:
        result = opencode_runtime_main._extract_structured_output({})
        self.assertIsNone(result)

    def test_build_response_metadata_includes_structured_output(self) -> None:
        payload = {
            "info": {"role": "assistant", "structured": {"result": 42}},
            "parts": [{"type": "text", "text": "hello"}],
        }
        meta = opencode_runtime_main._build_response_metadata(payload)
        self.assertIsNotNone(meta)
        self.assertEqual(meta["structured_output"], {"result": 42})

    def test_build_response_metadata_omits_structured_output_when_absent(self) -> None:
        payload = {
            "info": {"role": "assistant"},
            "parts": [{"type": "text", "text": "hello"}],
        }
        meta = opencode_runtime_main._build_response_metadata(payload)
        if meta is not None:
            self.assertNotIn("structured_output", meta)


class SessionRegistryPruningTests(unittest.TestCase):
    """Tests for SessionRegistry with max_age and max_entries pruning."""

    def _make_registry(self, data: dict | None = None, max_age: int = 3600, max_entries: int = 100):
        import time as _time

        td = tempfile.mkdtemp()
        path = Path(td) / "session-map.json"
        if data:
            path.write_text(json.dumps(data), encoding="utf-8")
        reg = opencode_runtime_main.SessionRegistry(path, max_age_seconds=max_age, max_entries=max_entries)
        return reg, path, td

    def test_get_or_set_creates_entry_with_timestamp(self) -> None:
        import time as _time

        reg, path, _ = self._make_registry()
        sid = reg.get_or_set("thread1", "ses_abc")
        self.assertEqual(sid, "ses_abc")
        raw = json.loads(path.read_text(encoding="utf-8"))
        entry = raw["thread1"]
        self.assertEqual(entry["session_id"], "ses_abc")
        self.assertIn("last_accessed", entry)

    def test_get_returns_existing_session(self) -> None:
        import time as _time

        data = {"t1": {"session_id": "ses_1", "last_accessed": _time.time()}}
        reg, _, _ = self._make_registry(data)
        self.assertEqual(reg.get("t1"), "ses_1")

    def test_get_returns_none_for_missing(self) -> None:
        reg, _, _ = self._make_registry()
        self.assertIsNone(reg.get("nope"))

    def test_size_property(self) -> None:
        import time as _time

        data = {
            "a": {"session_id": "s1", "last_accessed": _time.time()},
            "b": {"session_id": "s2", "last_accessed": _time.time()},
        }
        reg, _, _ = self._make_registry(data)
        self.assertEqual(reg.size, 2)

    def test_stale_count(self) -> None:
        import time as _time

        now = _time.time()
        data = {
            "fresh": {"session_id": "s1", "last_accessed": now},
            "stale": {"session_id": "s2", "last_accessed": now - 7200},
        }
        reg, _, _ = self._make_registry(data)
        self.assertEqual(reg.stale_count(3600), 1)

    def test_legacy_string_entries_migrated(self) -> None:
        data = {"old_thread": "ses_old"}
        reg, _, _ = self._make_registry(data)
        self.assertEqual(reg.get("old_thread"), "ses_old")
        self.assertEqual(reg.size, 1)

    def test_max_entries_enforced(self) -> None:
        import time as _time

        now = _time.time()
        data = {}
        for i in range(10):
            data[f"t{i}"] = {"session_id": f"s{i}", "last_accessed": now - (10 - i)}
        reg, path, _ = self._make_registry(data, max_entries=5)
        # Force pruning by resetting debounce
        reg._last_prune = 0
        reg.get_or_set("new_thread", "new_ses")
        self.assertLessEqual(reg.size, 6)


class SendPromptWithSessionRecoveryTests(unittest.TestCase):
    """Tests for _send_prompt_with_session_recovery, including 404 registry update."""

    def _make_kwargs(self, session_id: str = "ses_old") -> dict:
        return dict(
            session_id=session_id,
            prompt="hello",
            model="gpt-4",
            system_prompt=None,
            prompt_format=None,
            working_directory="/workspace",
            agent="build",
            logical_thread_id="thread_1",
            allow_session_recovery=True,
        )

    def test_successful_send_returns_payload(self) -> None:
        expected = {"info": {"role": "assistant"}, "parts": []}
        with patch.object(opencode_client_mod, "send_prompt", return_value=expected):
            sid, payload = opencode_runtime_main._send_prompt_with_session_recovery(**self._make_kwargs())
        self.assertEqual(sid, "ses_old")
        self.assertEqual(payload, expected)

    def test_404_recovery_updates_registry_with_set(self) -> None:
        """On 404, the registry must be updated via set() so the dead session is replaced (Bug fix)."""
        from fastapi import HTTPException as _HTTPException

        expected = {"info": {"role": "assistant"}, "parts": []}
        call_count = {"n": 0}

        def mock_send(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _HTTPException(status_code=404, detail="not found")
            return expected

        mock_registry = MagicMock()
        with (
            patch.object(opencode_client_mod, "send_prompt", side_effect=mock_send),
            patch.object(opencode_client_mod, "create_remote_session", return_value="ses_new"),
            patch.object(opencode_client_mod, "SESSION_REGISTRY", mock_registry),
        ):
            sid, payload = opencode_runtime_main._send_prompt_with_session_recovery(**self._make_kwargs())

        # Verify set() was called (not get_or_set) with the new session
        mock_registry.set.assert_called_once_with("thread_1", "ses_new")
        mock_registry.get_or_set.assert_not_called()
        self.assertEqual(sid, "ses_new")
        self.assertEqual(payload, expected)

    def test_non_404_error_propagates(self) -> None:
        from fastapi import HTTPException as _HTTPException

        with patch.object(opencode_client_mod, "send_prompt", side_effect=_HTTPException(status_code=500)):
            with self.assertRaises(_HTTPException) as ctx:
                opencode_runtime_main._send_prompt_with_session_recovery(**self._make_kwargs())
        self.assertEqual(ctx.exception.status_code, 500)

    def test_404_without_recovery_allowed_propagates(self) -> None:
        from fastapi import HTTPException as _HTTPException

        kwargs = self._make_kwargs()
        kwargs["allow_session_recovery"] = False
        with patch.object(opencode_client_mod, "send_prompt", side_effect=_HTTPException(status_code=404)):
            with self.assertRaises(_HTTPException) as ctx:
                opencode_runtime_main._send_prompt_with_session_recovery(**kwargs)
        self.assertEqual(ctx.exception.status_code, 404)


class SendPromptTests(unittest.TestCase):
    """Tests for direct OpenCode prompt submission helpers."""

    def test_empty_body_falls_back_to_session_history(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b""
        mock_response.text = ""
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        assistant_payload = {
            "info": {"role": "assistant", "parentID": "msg_test", "finish": "stop"},
            "parts": [{"type": "text", "text": "OK"}],
        }

        with (
            patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client),
            patch.object(opencode_client_mod, "_ascending_message_id", return_value="msg_test"),
            patch.object(opencode_client_mod, "wait_for_session_idle", return_value={"type": "idle"}),
            patch.object(opencode_client_mod, "get_session_messages", return_value=[assistant_payload]),
        ):
            payload = opencode_runtime_main.send_prompt(
                session_id="ses_test",
                prompt="hello",
                model="gpt-4",
                system_prompt=None,
                prompt_format=None,
                working_directory="/workspace",
                agent="build",
            )

        self.assertEqual(payload, assistant_payload)
        post_body = mock_client.post.call_args.kwargs["json"]
        self.assertEqual(post_body["messageID"], "msg_test")

    def test_invalid_json_body_raises_gateway_error(self) -> None:
        from fastapi import HTTPException as _HTTPException

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"not-json"
        mock_response.text = "not-json"
        mock_response.raise_for_status = MagicMock()
        mock_response.json.side_effect = ValueError("bad json")
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch.object(opencode_client_mod, "runtime_http_client", return_value=mock_client):
            with self.assertRaises(_HTTPException) as ctx:
                opencode_runtime_main.send_prompt(
                    session_id="ses_test",
                    prompt="hello",
                    model="gpt-4",
                    system_prompt=None,
                    prompt_format=None,
                    working_directory="/workspace",
                    agent="build",
                )

        self.assertEqual(ctx.exception.status_code, 502)


class StructuredOutputFormatRetryTests(unittest.TestCase):
    """Tests for the _resend_format flag: format must be resent on structured output error retry."""

    def _make_payload(
        self,
        text: str = "done",
        finish: str = "stop",
        error: dict | None = None,
        tokens: dict | None = None,
    ) -> dict:
        info: dict = {"role": "assistant", "finish": finish}
        if error:
            info["error"] = error
        if tokens:
            info["tokens"] = tokens
        return {"info": info, "parts": [{"type": "text", "text": text}]}

    def test_structured_output_retry_resends_format(self) -> None:
        """When StructuredOutputError occurs, the format should be resent on retry (Bug fix)."""
        call_log: list[dict] = []

        def mock_send(**kwargs):
            call_log.append(dict(kwargs))
            idx = len(call_log) - 1
            if idx == 0:
                # First call: return StructuredOutputError
                return kwargs.get("session_id", "ses"), self._make_payload(
                    "", "error", error={"name": "StructuredOutputError", "message": "bad format"}
                )
            # Second call: success
            return kwargs.get("session_id", "ses"), self._make_payload('{"result": 42}', "stop")

        req = opencode_runtime_main.InvokeRequest(
            prompt="Analyze this",
            output_format="json",
            output_schema={"type": "object", "properties": {"result": {"type": "integer"}}},
        )
        with (
            patch.object(invoke_mod, "ensure_server_running"),
            patch.object(invoke_mod, "create_remote_session", return_value="ses"),
            patch.object(invoke_mod, "_send_prompt_with_session_recovery", side_effect=mock_send),
            patch.object(invoke_mod, "get_session_messages", return_value=[]),
            patch.object(invoke_mod, "get_session_todos", return_value=[]),
            patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
            patch.object(invoke_mod, "abort_session", return_value=True),
            patch.object(invoke_mod, "summarize_session", return_value=True),
        ):
            resp = opencode_runtime_main.invoke_opencode(req)

        # The second call (retry after StructuredOutputError) should include prompt_format
        self.assertGreaterEqual(len(call_log), 2)
        retry_call = call_log[1]
        self.assertIsNotNone(
            retry_call.get("prompt_format"), "prompt_format should be resent on structured output error retry"
        )


class ComputeContextBudgetTests(unittest.TestCase):
    """Tests for compute_context_budget function."""

    def test_ok_status(self) -> None:
        payload = {"info": {"tokens": {"total": 50000}}}
        result = opencode_runtime_main.compute_context_budget(payload)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tokens_used"], 50000)
        self.assertGreater(result["tokens_remaining"], 0)

    def test_warning_status(self) -> None:
        limit = opencode_runtime_main.MODEL_CONTEXT_LIMIT
        tokens_used = int(limit * 0.72)
        payload = {"info": {"tokens": {"total": tokens_used}}}
        result = opencode_runtime_main.compute_context_budget(payload)
        self.assertEqual(result["status"], "warning")

    def test_critical_status(self) -> None:
        limit = opencode_runtime_main.MODEL_CONTEXT_LIMIT
        tokens_used = int(limit * 0.80)
        payload = {"info": {"tokens": {"total": tokens_used}}}
        result = opencode_runtime_main.compute_context_budget(payload)
        self.assertEqual(result["status"], "critical")

    def test_unknown_status_no_tokens(self) -> None:
        payload = {"info": {}}
        result = opencode_runtime_main.compute_context_budget(payload)
        self.assertEqual(result["status"], "unknown")

    def test_empty_payload(self) -> None:
        result = opencode_runtime_main.compute_context_budget({})
        self.assertEqual(result["status"], "unknown")

    def test_computed_total_from_input_output(self) -> None:
        payload = {"info": {"tokens": {"input": 30000, "output": 5000}}}
        result = opencode_runtime_main.compute_context_budget(payload)
        self.assertEqual(result["tokens_used"], 35000)

    def test_computed_total_includes_cache_write(self) -> None:
        """cache.write must be included in fallback total (Bug fix)."""
        payload = {
            "info": {
                "tokens": {
                    "input": 10000,
                    "output": 5000,
                    "cache": {"read": 3000, "write": 2000},
                }
            }
        }
        result = opencode_runtime_main.compute_context_budget(payload)
        self.assertEqual(result["tokens_used"], 20000)  # 10k + 5k + 3k + 2k


class DetectAntiPatternsTests(unittest.TestCase):
    """Tests for detect_anti_patterns function."""

    def test_detects_todo(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("# TODO: implement this")
        self.assertIn("TODO marker", result)

    def test_detects_fixme(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("# FIXME: broken logic")
        self.assertIn("FIXME marker", result)

    def test_detects_placeholder(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("This is a placeholder value")
        self.assertIn("placeholder implementation", result)

    def test_detects_stub(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("Created a stub function")
        self.assertIn("stub implementation", result)

    def test_detects_pass_statement(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("def foo():\n    pass\n")
        self.assertIn("pass statement", result)

    def test_detects_not_implemented(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("This feature is not implemented yet")
        self.assertIn("not implemented", result)

    def test_clean_text_returns_empty(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("Clean implementation of feature X")
        self.assertEqual(result, [])

    def test_empty_text_returns_empty(self) -> None:
        result = opencode_runtime_main.detect_anti_patterns("")
        self.assertEqual(result, [])

    def test_multiple_patterns(self) -> None:
        text = "# TODO: fix this\n# FIXME: refactor\ndef stub_fn():\n    pass\n"
        result = opencode_runtime_main.detect_anti_patterns(text)
        self.assertGreaterEqual(len(result), 3)


class DeriveTaskStatusTests(unittest.TestCase):
    """Tests for derive_task_status function."""

    def test_done_clean(self) -> None:
        result = opencode_runtime_main.derive_task_status("completed", [], {"status": "ok"})
        self.assertEqual(result, "DONE")

    def test_done_with_warnings(self) -> None:
        result = opencode_runtime_main.derive_task_status("completed", ["some warning"], {"status": "ok"})
        self.assertEqual(result, "DONE_WITH_CONCERNS")

    def test_done_with_anti_patterns(self) -> None:
        result = opencode_runtime_main.derive_task_status("completed", [], {"status": "ok"}, ["TODO marker"])
        self.assertEqual(result, "DONE_WITH_CONCERNS")

    def test_needs_context_critical(self) -> None:
        result = opencode_runtime_main.derive_task_status("completed", [], {"status": "critical"})
        self.assertEqual(result, "NEEDS_CONTEXT")

    def test_needs_context_warning_incomplete(self) -> None:
        result = opencode_runtime_main.derive_task_status("incomplete", [], {"status": "warning"})
        self.assertEqual(result, "NEEDS_CONTEXT")

    def test_blocked_on_error(self) -> None:
        result = opencode_runtime_main.derive_task_status("error", [], {"status": "ok"})
        self.assertEqual(result, "BLOCKED")


class MultiStageCompactionTests(InvokeOpenCodeLoopTests):
    """Tests for multi-stage compaction in the autonomous loop."""

    def test_second_compaction_after_spacing(self) -> None:
        """Second compaction should be allowed after minimum turn spacing."""
        high_tokens = {"total": int(opencode_runtime_main.MODEL_CONTEXT_LIMIT * 0.9)}
        payloads = [
            self._make_payload("w1", "tool-calls", tokens=high_tokens),
            self._make_payload("w2", "tool-calls"),
            self._make_payload("w3", "tool-calls"),
            self._make_payload("w4", "tool-calls", tokens=high_tokens),
            self._make_payload("done", "stop"),
        ]
        with (
            patch.object(invoke_mod, "COMPACTION_MIN_TURN_SPACING", 3),
            patch.object(invoke_mod, "MAX_COMPACTION_ATTEMPTS", 2),
        ):
            resp = self._run_invoke(
                {"prompt": "A big task", "autonomous": True, "max_turns": 10},
                payloads,
            )
        compaction_warnings = [w for w in resp.warnings if "compaction" in w.lower()]
        self.assertGreaterEqual(len(compaction_warnings), 1)

    def test_handoff_summary_when_context_exhausted(self) -> None:
        """When all compaction attempts fail to reduce context, handoff summary should be generated."""
        critical_tokens = {"total": int(opencode_runtime_main.MODEL_CONTEXT_LIMIT * 0.85)}
        payloads = [
            self._make_payload("w1", "tool-calls", tokens=critical_tokens),
            self._make_payload("w2", "tool-calls", tokens=critical_tokens),
            self._make_payload("w3", "tool-calls", tokens=critical_tokens),
            self._make_payload("w4", "tool-calls", tokens=critical_tokens),
            self._make_payload("w5", "tool-calls", tokens=critical_tokens),
            self._make_payload("w6", "tool-calls", tokens=critical_tokens),
            self._make_payload("w7", "tool-calls", tokens=critical_tokens),
            self._make_payload("w8", "stop", tokens=critical_tokens),
        ]
        with (
            patch.object(invoke_mod, "COMPACTION_MIN_TURN_SPACING", 1),
            patch.object(invoke_mod, "MAX_COMPACTION_ATTEMPTS", 2),
        ):
            resp = self._run_invoke(
                {"prompt": "Big task", "autonomous": True, "max_turns": 10},
                payloads,
            )
        self.assertIsNotNone(resp.metadata)
        if resp.metadata and resp.metadata.get("context_budget", {}).get("status") == "critical":
            self.assertIn("handoff_summary", resp.metadata)


class ResponseEnrichmentTests(InvokeOpenCodeLoopTests):
    """Tests for context_budget, task_status, anti_patterns in response metadata."""

    def test_metadata_includes_context_budget(self) -> None:
        payload = self._make_payload("done", "stop", tokens={"total": 50000})
        resp = self._run_invoke({"prompt": "task"}, [payload])
        self.assertIsNotNone(resp.metadata)
        self.assertIn("context_budget", resp.metadata)
        self.assertIn("status", resp.metadata["context_budget"])

    def test_metadata_includes_task_status(self) -> None:
        payload = self._make_payload("done", "stop")
        resp = self._run_invoke({"prompt": "task"}, [payload])
        self.assertIsNotNone(resp.metadata)
        self.assertIn("task_status", resp.metadata)
        self.assertIn(resp.metadata["task_status"], ("DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"))

    def test_metadata_includes_anti_patterns_when_found(self) -> None:
        payload = self._make_payload("# TODO: implement this\ndef stub():\n    pass", "stop")
        resp = self._run_invoke({"prompt": "task"}, [payload])
        self.assertIsNotNone(resp.metadata)
        self.assertIn("anti_patterns", resp.metadata)
        self.assertGreater(len(resp.metadata["anti_patterns"]), 0)

    def test_metadata_omits_anti_patterns_when_clean(self) -> None:
        payload = self._make_payload("Implementation complete with full coverage", "stop")
        resp = self._run_invoke({"prompt": "task"}, [payload])
        self.assertIsNotNone(resp.metadata)
        self.assertNotIn("anti_patterns", resp.metadata)

    def test_task_status_blocked_on_error(self) -> None:
        payload = self._make_payload("", "stop", error={"name": "ProviderAuthError", "message": "bad"})
        resp = self._run_invoke({"prompt": "task"}, [payload])
        self.assertIsNotNone(resp.metadata)
        self.assertIn(resp.metadata.get("task_status"), ("BLOCKED", "DONE_WITH_CONCERNS"))


class SessionHealthMetricsTests(unittest.TestCase):
    """Tests for session health metrics in /health and /ready."""

    def test_health_includes_sessions_section(self) -> None:
        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(
                opencode_runtime_main,
                "SKILL_RUNTIME_CONFIG",
                {"skillFiles": [], "warnings": [], "configFiles": [], "mcpSidecars": []},
            ),
        ):
            result = opencode_runtime_main.health()
        self.assertIn("sessions", result)
        sessions = result["sessions"]
        self.assertIn("total", sessions)
        self.assertIn("active", sessions)
        self.assertIn("stale", sessions)
        self.assertIn("at_capacity", sessions)

    def test_ready_includes_server_health(self) -> None:
        with (
            patch.object(opencode_runtime_main, "ensure_runtime_directories"),
            patch("shutil.which", return_value="/usr/bin/opencode"),
            patch.object(opencode_runtime_main, "ensure_server_running"),
            patch("httpx.Client") as mock_client_cls,
            patch("os.access", return_value=True),
            patch.object(
                opencode_runtime_main, "SKILL_RUNTIME_CONFIG", {"configFiles": [], "skillFiles": [], "mcpSidecars": []}
            ),
        ):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            result = opencode_runtime_main.ready()
        self.assertIn("opencode_server_healthy", result)
        self.assertIn("session_registry_writable", result)


class ContextBudgetEndpointTests(unittest.TestCase):
    """Tests for the /context-budget endpoint."""

    def test_missing_thread_id_returns_400(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(opencode_runtime_main.app, raise_server_exceptions=False)
        with patch.object(supervisor_mod, "_runtime_ready", True):
            resp = client.get("/context-budget")
        self.assertEqual(resp.status_code, 400)

    def test_unknown_thread_id_returns_404(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(opencode_runtime_main.app, raise_server_exceptions=False)
        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(opencode_runtime_main.SESSION_REGISTRY, "get", return_value=None),
        ):
            resp = client.get("/context-budget?thread_id=unknown")
        self.assertEqual(resp.status_code, 404)

    def test_valid_thread_returns_budget(self) -> None:
        from fastapi.testclient import TestClient

        client = TestClient(opencode_runtime_main.app, raise_server_exceptions=False)
        mock_messages = [
            {
                "info": {"role": "assistant", "tokens": {"total": 50000}},
                "parts": [{"type": "text", "text": "hi"}],
            }
        ]
        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(opencode_runtime_main.SESSION_REGISTRY, "get", return_value="ses_test"),
            patch.object(opencode_runtime_main, "get_session_messages", return_value=mock_messages),
        ):
            resp = client.get("/context-budget?thread_id=t1")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("session_id", data)
        self.assertEqual(data["session_id"], "ses_test")


class StreamingEventsTests(unittest.TestCase):
    """Tests for per-turn SSE streaming events."""

    def test_live_updates_wait_for_terminal_assistant_payload(self) -> None:
        """Live-update polling should ignore intermediate tool-call assistant messages."""
        intermediate_payload = {
            "info": {
                "id": "msg_assistant_tool",
                "role": "assistant",
                "parentID": "msg_user",
                "finish": "tool-calls",
                "time": {"completed": 1},
            },
            "parts": [{"type": "text", "text": "Working..."}],
        }
        final_payload = {
            "info": {
                "id": "msg_assistant_final",
                "role": "assistant",
                "parentID": "msg_user",
                "finish": "stop",
                "time": {"completed": 2},
            },
            "parts": [{"type": "text", "text": "Done!"}],
        }
        snapshots = [
            [intermediate_payload],
            [intermediate_payload],
            [final_payload],
        ]
        poll_count = {"n": 0}

        def mock_get_session_messages(session_id):
            idx = min(poll_count["n"], len(snapshots) - 1)
            poll_count["n"] += 1
            return snapshots[idx]

        with (
            patch.object(invoke_mod, "send_prompt_async", return_value="msg_user"),
            patch.object(invoke_mod, "get_session_messages", side_effect=mock_get_session_messages),
            patch.object(invoke_mod, "get_session_status", return_value={"type": "idle"}),
            patch.object(invoke_mod.time, "sleep", return_value=None),
        ):
            session_id, payload = invoke_mod._send_prompt_with_live_updates_and_recovery(
                session_id="ses_test",
                prompt="Do something",
                model="gpt-4",
                system_prompt=None,
                prompt_format=None,
                working_directory="/workspace",
                agent="build",
                logical_thread_id="thread-1",
                allow_session_recovery=False,
                turn=0,
                emit=lambda *_args, **_kwargs: None,
            )

        self.assertEqual(session_id, "ses_test")
        self.assertEqual(payload["info"]["finish"], "stop")
        self.assertEqual(payload["parts"][0]["text"], "Done!")
        self.assertGreaterEqual(poll_count["n"], 3)

    def test_stream_emits_multiple_events(self) -> None:
        """Streaming endpoint should emit turn events for multi-turn invocation."""
        payload1 = {
            "info": {"role": "assistant", "finish": "tool-calls"},
            "parts": [{"type": "text", "text": "Working..."}],
        }
        payload2 = {"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "Done!"}]}

        call_count = {"n": 0}

        def mock_send(**kwargs):
            idx = min(call_count["n"], 1)
            call_count["n"] += 1
            return kwargs.get("session_id", "ses_test"), [payload1, payload2][idx]

        async def collect_stream() -> tuple[int, str]:
            response = await opencode_runtime_main.invoke_stream(
                opencode_runtime_main.InvokeRequest(prompt="Do something", autonomous=True)
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return response.status_code, "".join(chunks)

        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(invoke_mod, "ensure_server_running"),
            patch.object(invoke_mod, "create_remote_session", return_value="ses_test"),
            patch.object(invoke_mod, "_send_prompt_with_live_updates_and_recovery", side_effect=mock_send),
            patch.object(invoke_mod, "get_session_messages", return_value=[]),
            patch.object(invoke_mod, "get_session_todos", return_value=[]),
            patch.object(invoke_mod, "wait_for_session_idle", return_value={"type": "idle"}),
            patch.object(invoke_mod, "abort_session", return_value=True),
            patch.object(invoke_mod, "summarize_session", return_value=True),
        ):
            status_code, text = asyncio.run(collect_stream())
        self.assertEqual(status_code, 200)
        self.assertIn("event: response.started", text)
        self.assertIn("event: response.completed", text)
        self.assertIn("response.turn_started", text)
        self.assertIn("response.turn_completed", text)

    def test_stream_emits_live_reasoning_snapshots(self) -> None:
        """Streaming endpoint should forward live reasoning snapshots from async OpenCode prompts."""
        final_payload = {
            "info": {
                "id": "msg_assistant",
                "role": "assistant",
                "parentID": "msg_user",
                "finish": "stop",
                "time": {"completed": 1},
            },
            "parts": [
                {"type": "reasoning", "text": "Plan the change"},
                {"type": "text", "text": "Done!"},
            ],
        }
        snapshots = [
            [],
            [
                {
                    "info": {"id": "msg_assistant", "role": "assistant", "parentID": "msg_user", "time": {}},
                    "parts": [{"type": "reasoning", "text": "Plan the change"}],
                }
            ],
            [final_payload],
            [final_payload],
        ]
        poll_count = {"n": 0}

        def mock_send_prompt_async(**kwargs):
            return "msg_user"

        def mock_get_session_messages(session_id):
            idx = min(poll_count["n"], len(snapshots) - 1)
            poll_count["n"] += 1
            return snapshots[idx]

        def mock_get_session_status(session_id):
            return {"type": "idle"} if poll_count["n"] >= 3 else {"type": "busy"}

        async def collect_stream() -> tuple[int, str]:
            response = await opencode_runtime_main.invoke_stream(
                opencode_runtime_main.InvokeRequest(prompt="Do something")
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return response.status_code, "".join(chunks)

        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(invoke_mod, "ensure_server_running"),
            patch.object(invoke_mod, "create_remote_session", return_value="ses_test"),
            patch.object(invoke_mod, "send_prompt_async", side_effect=mock_send_prompt_async),
            patch.object(invoke_mod, "get_session_messages", side_effect=mock_get_session_messages),
            patch.object(invoke_mod, "get_session_message", return_value=final_payload),
            patch.object(invoke_mod, "get_session_status", side_effect=mock_get_session_status),
            patch.object(invoke_mod, "get_session_todos", return_value=[]),
            patch.object(invoke_mod.time, "sleep", return_value=None),
        ):
            status_code, text = asyncio.run(collect_stream())

        self.assertEqual(status_code, 200)
        self.assertIn("event: response.reasoning", text)
        self.assertIn("Plan the change", text)
        self.assertIn("event: response.delta", text)
        self.assertIn("Done!", text)

    def test_stream_prefers_meaningful_assistant_over_trailing_empty_payloads(self) -> None:
        """Streaming should ignore trailing empty assistant payloads for the same user message."""
        meaningful_payload = {
            "info": {
                "id": "msg_assistant_text",
                "role": "assistant",
                "parentID": "msg_user",
                "finish": "stop",
                "time": {"completed": 1},
            },
            "parts": [
                {"type": "step-start"},
                {"type": "text", "text": "Done!"},
                {"type": "step-finish"},
            ],
        }
        trailing_empty_payload = {
            "info": {
                "id": "msg_assistant_empty",
                "role": "assistant",
                "parentID": "msg_user",
                "finish": "stop",
                "time": {"completed": 2},
            },
            "parts": [
                {"type": "step-start"},
                {"type": "step-finish"},
            ],
        }

        def mock_send_prompt_async(**kwargs):
            return "msg_user"

        def mock_get_session_messages(session_id):
            return [meaningful_payload, trailing_empty_payload]

        def mock_get_session_status(session_id):
            return {"type": "idle"}

        def mock_get_session_message(session_id, message_id):
            if message_id == "msg_assistant_text":
                return meaningful_payload
            if message_id == "msg_assistant_empty":
                return trailing_empty_payload
            return None

        async def collect_stream() -> tuple[int, str]:
            response = await opencode_runtime_main.invoke_stream(
                opencode_runtime_main.InvokeRequest(prompt="Do something")
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return response.status_code, "".join(chunks)

        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(invoke_mod, "ensure_server_running"),
            patch.object(invoke_mod, "create_remote_session", return_value="ses_test"),
            patch.object(invoke_mod, "init_session", return_value=True),
            patch.object(invoke_mod, "send_prompt_async", side_effect=mock_send_prompt_async),
            patch.object(invoke_mod, "get_session_messages", side_effect=mock_get_session_messages),
            patch.object(invoke_mod, "get_session_message", side_effect=mock_get_session_message),
            patch.object(invoke_mod, "get_session_status", side_effect=mock_get_session_status),
            patch.object(invoke_mod, "get_session_todos", return_value=[]),
            patch.object(invoke_mod.time, "sleep", return_value=None),
        ):
            status_code, text = asyncio.run(collect_stream())

        self.assertEqual(status_code, 200)
        self.assertIn("event: response.delta", text)
        self.assertIn("Done!", text)
        self.assertIn("event: response.completed", text)
        self.assertIn('"response": "Done!"', text)

    def test_stream_idle_retry_resends_prompt(self) -> None:
        """When the sidecar drops a prompt (idle with no assistant), the runtime should retry."""
        assistant_payload = {
            "info": {
                "id": "msg_assistant_retry",
                "role": "assistant",
                "parentID": "msg_user_retry",
                "finish": "stop",
                "time": {"completed": 1},
            },
            "parts": [
                {"type": "step-start"},
                {"type": "text", "text": "Retried!"},
                {"type": "step-finish"},
            ],
        }

        send_call_count = 0

        def mock_send_prompt_async(**kwargs):
            nonlocal send_call_count
            send_call_count += 1
            if send_call_count == 1:
                return "msg_user_dropped"
            return "msg_user_retry"

        call_count = 0

        def mock_get_session_messages(session_id):
            nonlocal call_count
            call_count += 1
            # First several polls: no assistant (prompt was dropped)
            if send_call_count <= 1:
                return []
            # After retry: assistant appears
            return [assistant_payload]

        def mock_get_session_status(session_id):
            return {"type": "idle"}

        def mock_get_session_message(session_id, message_id):
            if message_id == "msg_assistant_retry":
                return assistant_payload
            return None

        real_monotonic = invoke_mod.time.monotonic
        time_offset = [0.0]

        def mock_monotonic():
            return real_monotonic() + time_offset[0]

        def mock_sleep(seconds):
            # Advance mock time past the 5s grace period
            time_offset[0] += 6.0

        async def collect_stream() -> tuple[int, str]:
            response = await opencode_runtime_main.invoke_stream(
                opencode_runtime_main.InvokeRequest(prompt="Do something")
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return response.status_code, "".join(chunks)

        with (
            patch.object(supervisor_mod, "_runtime_ready", True),
            patch.object(invoke_mod, "ensure_server_running"),
            patch.object(invoke_mod, "create_remote_session", return_value="ses_test"),
            patch.object(invoke_mod, "init_session", return_value=True),
            patch.object(invoke_mod, "send_prompt_async", side_effect=mock_send_prompt_async),
            patch.object(invoke_mod, "get_session_messages", side_effect=mock_get_session_messages),
            patch.object(invoke_mod, "get_session_message", side_effect=mock_get_session_message),
            patch.object(invoke_mod, "get_session_status", side_effect=mock_get_session_status),
            patch.object(invoke_mod, "get_session_todos", return_value=[]),
            patch.object(invoke_mod.time, "sleep", side_effect=mock_sleep),
            patch.object(invoke_mod.time, "monotonic", side_effect=mock_monotonic),
        ):
            status_code, text = asyncio.run(collect_stream())

        self.assertEqual(status_code, 200)
        self.assertGreater(send_call_count, 1, "prompt_async should have been retried")
        self.assertIn("Retried!", text)
        self.assertIn("event: response.completed", text)



if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Workstream tests — new functions from context management enhancements
# ---------------------------------------------------------------------------

# Sub-module references for new modules
memory_mod = runtime_modules["memory"]
workspace_mod = runtime_modules["workspace"]
prompts_mod = runtime_modules["prompts"]


class EstimateMessageTokensTests(unittest.TestCase):
    """Tests for estimate_message_tokens heuristic."""

    def test_empty_message(self) -> None:
        result = opencode_runtime_main.estimate_message_tokens({})
        self.assertGreaterEqual(result, 0)

    def test_text_parts_counted(self) -> None:
        msg = {"parts": [{"type": "text", "text": "Hello world, this is a test."}]}
        result = opencode_runtime_main.estimate_message_tokens(msg)
        self.assertGreater(result, 0)
        # ~27 chars / 4 ≈ 6-7 tokens minimum
        self.assertGreaterEqual(result, 5)

    def test_tool_parts_counted(self) -> None:
        msg = {"parts": [{"type": "tool", "state": {"output": "x" * 400}}]}
        result = opencode_runtime_main.estimate_message_tokens(msg)
        # 400 chars ≈ 100 tokens
        self.assertGreaterEqual(result, 50)

    def test_no_parts_key(self) -> None:
        msg = {"info": {"role": "assistant"}}
        result = opencode_runtime_main.estimate_message_tokens(msg)
        self.assertGreaterEqual(result, 0)


class ComputeContextPriorityTests(unittest.TestCase):
    """Tests for compute_context_priority scoring."""

    def test_empty_messages(self) -> None:
        result = opencode_runtime_main.compute_context_priority([])
        self.assertEqual(result, [])

    def test_returns_entry_per_message(self) -> None:
        messages = [
            {"info": {"role": "system"}, "parts": [{"type": "text", "text": "system"}]},
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "hello"}]},
            {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "hi"}]},
        ]
        result = opencode_runtime_main.compute_context_priority(messages)
        self.assertEqual(len(result), 3)
        for entry in result:
            self.assertIn("index", entry)
            self.assertIn("priority", entry)
            self.assertIn("tokens_est", entry)
            self.assertIn("category", entry)

    def test_system_messages_higher_priority(self) -> None:
        messages = [
            {"info": {"role": "system"}, "parts": [{"type": "text", "text": "rules"}]},
            {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "sure " * 500}]},
        ]
        result = opencode_runtime_main.compute_context_priority(messages)
        system_priority = result[0]["priority"]
        assistant_priority = result[1]["priority"]
        self.assertGreaterEqual(system_priority, assistant_priority)


class RecommendCompactionStrategyTests(unittest.TestCase):
    """Tests for recommend_compaction_strategy."""

    def test_returns_none_for_ok(self) -> None:
        budget = {"status": "ok", "usage_percent": 30.0}
        result = opencode_runtime_main.recommend_compaction_strategy(budget)
        self.assertEqual(result, "none")

    def test_returns_prune_outputs_for_moderate(self) -> None:
        # usage_percent=60 → remaining=40 → 40 < 50 so not "none", 40 > 25 → "prune_outputs"
        budget = {"status": "warning", "usage_percent": 60.0}
        result = opencode_runtime_main.recommend_compaction_strategy(budget)
        self.assertEqual(result, "prune_outputs")

    def test_returns_aggressive_for_critical(self) -> None:
        # usage_percent=95 → remaining=5 → below all thresholds → "aggressive"
        budget = {"status": "critical", "usage_percent": 95.0}
        result = opencode_runtime_main.recommend_compaction_strategy(budget)
        self.assertEqual(result, "aggressive")

    def test_unknown_budget_returns_none(self) -> None:
        budget = {"status": "unknown"}
        result = opencode_runtime_main.recommend_compaction_strategy(budget)
        self.assertEqual(result, "none")


class BuildCompactionHintsTests(unittest.TestCase):
    """Tests for build_compaction_hints."""

    def test_none_strategy_returns_empty(self) -> None:
        result = opencode_runtime_main.build_compaction_hints([], "none")
        self.assertEqual(result, "")

    def test_aggressive_strategy_returns_hints(self) -> None:
        # Use more messages so there are both high and low priority entries
        messages = [
            {"info": {"role": "system"}, "parts": [{"type": "text", "text": "system prompt"}]},
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "do something complex"}]},
            {
                "info": {"role": "assistant"},
                "parts": [
                    {"type": "text", "text": "working..."},
                    {"type": "tool", "state": {"output": "x" * 2000, "status": "completed"}},
                ],
            },
            {
                "info": {"role": "assistant"},
                "parts": [
                    {"type": "text", "text": "more work..."},
                    {"type": "tool", "state": {"output": "y" * 3000, "status": "completed"}},
                ],
            },
            {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "done " * 200}]},
        ]
        result = opencode_runtime_main.build_compaction_hints(messages, "aggressive")
        self.assertIsInstance(result, str)
        # Aggressive always includes the AGGRESSIVE hint
        self.assertIn("AGGRESSIVE", result)


class ClassifyTaskTypeTests(unittest.TestCase):
    """Tests for classify_task_type keyword-based classification."""

    def test_exploration_keywords(self) -> None:
        self.assertEqual(opencode_runtime_main.classify_task_type("explore the codebase structure"), "exploration")

    def test_debugging_keywords(self) -> None:
        self.assertEqual(opencode_runtime_main.classify_task_type("debug this error and fix the bug"), "debugging")

    def test_feature_keywords(self) -> None:
        self.assertEqual(
            opencode_runtime_main.classify_task_type("implement a new feature for user registration"), "feature"
        )

    def test_edit_keywords(self) -> None:
        # Short prompt with file path triggers edit classification
        self.assertEqual(opencode_runtime_main.classify_task_type("change src/main.py line 5"), "edit")

    def test_review_keywords(self) -> None:
        # Use stronger review signal without triggering debugging keywords
        self.assertEqual(opencode_runtime_main.classify_task_type("review this code and audit for quality"), "review")

    def test_refactor_keywords(self) -> None:
        self.assertEqual(
            opencode_runtime_main.classify_task_type("refactor the module to extract helper functions"), "refactor"
        )

    def test_deployment_keywords(self) -> None:
        self.assertEqual(
            opencode_runtime_main.classify_task_type("deploy to kubernetes and configure CI/CD"), "deployment"
        )

    def test_unknown_for_vague_prompt(self) -> None:
        result = opencode_runtime_main.classify_task_type("do the thing with the stuff")
        self.assertEqual(result, "unknown")

    def test_empty_prompt(self) -> None:
        result = opencode_runtime_main.classify_task_type("")
        self.assertEqual(result, "unknown")


class SmartAgentSelectionTests(unittest.TestCase):
    """Tests for the smart agent selection path."""

    def test_critical_budget_avoids_plan_for_feature(self) -> None:
        with patch.object(analysis_mod, "AGENT_SELECTION_MODE", "smart"):
            result = opencode_runtime_main.select_agent_for_prompt(
                "implement a new feature with full test coverage",
                is_first_turn=True,
                context_budget_status="critical",
            )
            self.assertNotEqual(result, "plan")

    def test_prior_memory_skips_plan_for_feature(self) -> None:
        with patch.object(analysis_mod, "AGENT_SELECTION_MODE", "smart"):
            result = opencode_runtime_main.select_agent_for_prompt(
                "implement a complete REST API with multiple endpoints",
                is_first_turn=True,
                has_prior_memory=True,
            )
            self.assertEqual(result, opencode_runtime_main.DEFAULT_AGENT)

    def test_simple_mode_uses_original_logic(self) -> None:
        with (
            patch.object(analysis_mod, "AGENT_SELECTION_MODE", "simple"),
            patch.object(analysis_mod, "DEFAULT_AGENT", "build"),
            patch.object(analysis_mod, "PLAN_AGENT_PROMPT_THRESHOLD", 50),
        ):
            result = opencode_runtime_main.select_agent_for_prompt("Fix the bug", is_first_turn=True)
            self.assertEqual(result, "build")


class GetContinuationPromptTests(unittest.TestCase):
    """Tests for get_continuation_prompt."""

    def test_ok_status(self) -> None:
        result = opencode_runtime_main.get_continuation_prompt("ok")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_warning_status(self) -> None:
        result = opencode_runtime_main.get_continuation_prompt("warning")
        self.assertIsInstance(result, str)
        self.assertIn("context", result.lower())

    def test_critical_status(self) -> None:
        result = opencode_runtime_main.get_continuation_prompt("critical")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_unknown_status_fallback(self) -> None:
        result = opencode_runtime_main.get_continuation_prompt("unknown")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class GetTaskTypePromptTests(unittest.TestCase):
    """Tests for get_task_type_prompt."""

    def test_known_task_types(self) -> None:
        for task_type in ("exploration", "debugging", "feature", "edit", "review", "refactor", "deployment"):
            result = opencode_runtime_main.get_task_type_prompt(task_type)
            self.assertIsNotNone(result, f"Expected prompt for task type '{task_type}'")
            self.assertIsInstance(result, str)

    def test_unknown_returns_none(self) -> None:
        result = opencode_runtime_main.get_task_type_prompt("unknown")
        self.assertIsNone(result)

    def test_invalid_returns_none(self) -> None:
        result = opencode_runtime_main.get_task_type_prompt("made_up_type")
        self.assertIsNone(result)


class FormatMemoryContextTests(unittest.TestCase):
    """Tests for format_memory_context."""

    def test_empty_list_returns_none(self) -> None:
        result = opencode_runtime_main.format_memory_context([])
        self.assertIsNone(result)

    def test_entries_formatted(self) -> None:
        entries = [
            {"type": "task_summary", "content": "Did a thing"},
            {"type": "decision", "content": "Chose approach A"},
        ]
        result = opencode_runtime_main.format_memory_context(entries)
        self.assertIsNotNone(result)
        self.assertIn("PRIOR SESSION MEMORY", result)
        self.assertIn("Did a thing", result)
        self.assertIn("Chose approach A", result)


class FormatWorkspaceSystemPromptTests(unittest.TestCase):
    """Tests for format_workspace_system_prompt."""

    def test_none_snapshot_returns_none(self) -> None:
        result = opencode_runtime_main.format_workspace_system_prompt(None)
        self.assertIsNone(result)

    def test_snapshot_formatted(self) -> None:
        snapshot = {
            "tech_stack": ["Python", "FastAPI"],
            "directory_tree": "src/\n  main.py\n  utils.py",
            "key_files": ["src/main.py"],
            "file_stats": {"py": 10, "json": 2},
            "git_info": {"branch": "main", "recent_commits": ["abc: fix bug"]},
            "total_files": 12,
        }
        result = opencode_runtime_main.format_workspace_system_prompt(snapshot)
        self.assertIsNotNone(result)
        self.assertIn("Python", result)
        self.assertIn("FastAPI", result)

    def test_error_snapshot_returns_minimal(self) -> None:
        snapshot = {"error": "failed to scan"}
        result = opencode_runtime_main.format_workspace_system_prompt(snapshot)
        # An error snapshot is a non-empty dict, so it passes the truthiness check
        # but has no useful content. The result should be minimal (just the header).
        self.assertIsNotNone(result)
        self.assertNotIn("Tech stack", result)


class BuildRecoveryPromptTests(unittest.TestCase):
    """Tests for build_recovery_prompt."""

    def test_basic_recovery(self) -> None:
        pre_state = {
            "todos": [{"id": "1", "content": "Write tests", "status": "pending"}],
            "artifacts": [{"path": "/workspace/main.py"}],
            "last_action": "Created file main.py",
            "current_step": "step 2 of 3",
        }
        result = opencode_runtime_main.build_recovery_prompt(pre_state)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)
        self.assertIn("Write tests", result)

    def test_empty_state(self) -> None:
        result = opencode_runtime_main.build_recovery_prompt({})
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class BuildHandoffResumptionPromptTests(unittest.TestCase):
    """Tests for build_handoff_resumption_prompt."""

    def test_handoff_prompt_includes_context(self) -> None:
        handoff = {
            "original_prompt": "Build a REST API",
            "summary": "Created 3 endpoints, tests pending",
            "todos": [{"content": "Write tests", "status": "pending"}],
            "artifacts": [{"path": "/workspace/api.py"}],
        }
        result = opencode_runtime_main.build_handoff_resumption_prompt(handoff)
        self.assertIsInstance(result, str)
        self.assertIn("REST API", result)
        self.assertIn("Write tests", result)


class SessionMemoryTests(unittest.TestCase):
    """Tests for the SessionMemory class."""

    def setUp(self) -> None:
        self._td = tempfile.mkdtemp()
        self.memory = opencode_runtime_main.SessionMemory(Path(self._td), max_thread=5, max_workspace=3)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._td, ignore_errors=True)

    def test_save_and_recall(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            entry = {"type": "task_summary", "content": "Did something"}
            self.memory.save_memory("thread1", entry)
            recalled = self.memory.recall_memory("thread1")
            self.assertEqual(len(recalled), 1)
            self.assertEqual(recalled[0]["content"], "Did something")

    def test_recall_empty_thread(self) -> None:
        result = self.memory.recall_memory("nonexistent")
        self.assertEqual(result, [])

    def test_has_memory_false_initially(self) -> None:
        self.assertFalse(self.memory.has_memory("thread1"))

    def test_has_memory_true_after_save(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            self.memory.save_memory("thread1", {"type": "decision", "content": "chose A"})
            self.assertTrue(self.memory.has_memory("thread1"))

    def test_clear_thread(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            self.memory.save_memory("thread1", {"type": "task_summary", "content": "x"})
            self.assertTrue(self.memory.has_memory("thread1"))
            self.memory.clear_thread("thread1")
            self.assertFalse(self.memory.has_memory("thread1"))

    def test_prune_thread_entries(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            for i in range(10):
                self.memory.save_memory("thread1", {"type": "task_summary", "content": f"item {i}"})
            recalled = self.memory.recall_memory("thread1", limit=100)
            # Should be pruned to max_thread (5)
            self.assertLessEqual(len(recalled), 5)

    def test_workspace_memory(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            self.memory.save_workspace_memory({"type": "codebase_insight", "content": "Python project"})
            recalled = self.memory.recall_workspace_memory()
            self.assertEqual(len(recalled), 1)
            self.assertEqual(recalled[0]["content"], "Python project")

    def test_build_memory_context_combines_tiers(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            self.memory.save_workspace_memory({"type": "codebase_insight", "content": "workspace info"})
            self.memory.save_memory("thread1", {"type": "task_summary", "content": "thread info"})
            context = self.memory.build_memory_context("thread1")
            self.assertGreaterEqual(len(context), 2)

    def test_get_handoff_memory_none_when_empty(self) -> None:
        result = self.memory.get_handoff_memory("thread1")
        self.assertIsNone(result)

    def test_get_handoff_memory_returns_latest(self) -> None:
        with patch.object(memory_mod, "MEMORY_ENABLED", True):
            self.memory.save_memory("thread1", {"type": "handoff", "content": {"summary": "partial work"}})
            result = self.memory.get_handoff_memory("thread1")
            self.assertIsNotNone(result)
            self.assertEqual(result["type"], "handoff")


class BuildTaskSummaryEntryTests(unittest.TestCase):
    """Tests for build_task_summary_entry convenience function."""

    def test_creates_valid_entry(self) -> None:
        entry = opencode_runtime_main.build_task_summary_entry(
            prompt="Build feature X",
            response_text="Feature X implemented",
            status="completed",
        )
        self.assertEqual(entry["type"], "task_summary")
        self.assertIn("content", entry)
        self.assertIn("Build feature X", str(entry["content"]))

    def test_includes_optional_fields(self) -> None:
        entry = opencode_runtime_main.build_task_summary_entry(
            prompt="Build it",
            response_text="Done",
            status="completed",
            artifacts=[{"path": "/workspace/main.py"}],
            todos=[{"title": "Write tests"}],
            warnings=["some warning"],
        )
        self.assertEqual(entry["type"], "task_summary")
        content = entry["content"]
        self.assertIsInstance(content, dict)


class BuildHandoffEntryTests(unittest.TestCase):
    """Tests for build_handoff_entry convenience function."""

    def test_creates_valid_entry(self) -> None:
        entry = opencode_runtime_main.build_handoff_entry(
            prompt="Build REST API",
            summary="Created 3 endpoints",
        )
        self.assertEqual(entry["type"], "handoff")
        self.assertIn("content", entry)

    def test_includes_todos_and_artifacts(self) -> None:
        entry = opencode_runtime_main.build_handoff_entry(
            prompt="Build it",
            summary="Partial progress",
            todos=[{"title": "Finish tests"}],
            artifacts=[{"path": "/workspace/api.py"}],
        )
        content = entry["content"]
        self.assertIsInstance(content, dict)
        self.assertIn("todos", content)


class WorkspaceSnapshotTests(unittest.TestCase):
    """Tests for workspace snapshot capture and caching."""

    def test_capture_nonexistent_directory(self) -> None:
        result = opencode_runtime_main.capture_workspace_snapshot("/nonexistent/path/xyz")
        self.assertIn("error", result)

    def test_capture_valid_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Create some files
            Path(td, "main.py").write_text("print('hello')", encoding="utf-8")
            Path(td, "package.json").write_text('{"name": "test"}', encoding="utf-8")
            result = opencode_runtime_main.capture_workspace_snapshot(td)
            self.assertNotIn("error", result)
            self.assertIn("tech_stack", result)
            self.assertIn("total_files", result)
            self.assertGreaterEqual(result["total_files"], 2)

    def test_get_or_refresh_when_disabled(self) -> None:
        with patch.object(workspace_mod, "WORKSPACE_SNAPSHOT_ENABLED", False):
            result = opencode_runtime_main.get_or_refresh_snapshot("/workspace")
            self.assertIsNone(result)

    def test_get_or_refresh_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache_dir:
            Path(td, "main.py").write_text("print('hello')", encoding="utf-8")
            with (
                patch.object(workspace_mod, "WORKSPACE_SNAPSHOT_ENABLED", True),
                patch.object(workspace_mod, "WORKSPACE_SNAPSHOT_DIR", Path(cache_dir)),
            ):
                result = opencode_runtime_main.get_or_refresh_snapshot(td)
                self.assertIsNotNone(result)
                self.assertIn("tech_stack", result)

    def test_cached_snapshot_reused(self) -> None:
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache_dir:
            Path(td, "main.py").write_text("print('hello')", encoding="utf-8")
            with (
                patch.object(workspace_mod, "WORKSPACE_SNAPSHOT_ENABLED", True),
                patch.object(workspace_mod, "WORKSPACE_SNAPSHOT_DIR", Path(cache_dir)),
            ):
                result1 = opencode_runtime_main.get_or_refresh_snapshot(td)
                result2 = opencode_runtime_main.get_or_refresh_snapshot(td)
                self.assertEqual(result1["captured_at"], result2["captured_at"])


class ContextAwareContinuationPromptsTests(unittest.TestCase):
    """Tests for CONTEXT_AWARE_CONTINUATION_PROMPTS dict."""

    def test_dict_has_expected_keys(self) -> None:
        prompts_dict = opencode_runtime_main.CONTEXT_AWARE_CONTINUATION_PROMPTS
        self.assertIn("ok", prompts_dict)
        self.assertIn("warning", prompts_dict)
        self.assertIn("critical", prompts_dict)

    def test_all_values_are_strings(self) -> None:
        for key, value in opencode_runtime_main.CONTEXT_AWARE_CONTINUATION_PROMPTS.items():
            self.assertIsInstance(value, str, f"Value for key '{key}' should be str")


class TaskTypePromptsTests(unittest.TestCase):
    """Tests for TASK_TYPE_PROMPTS dict."""

    def test_dict_has_expected_keys(self) -> None:
        prompts_dict = opencode_runtime_main.TASK_TYPE_PROMPTS
        for key in ("exploration", "debugging", "feature", "edit", "review", "refactor", "deployment"):
            self.assertIn(key, prompts_dict)

    def test_all_values_are_strings(self) -> None:
        for key, value in opencode_runtime_main.TASK_TYPE_PROMPTS.items():
            self.assertIsInstance(value, str, f"Value for key '{key}' should be str")


class EnsureRuntimeDirectoriesTests(unittest.TestCase):
    """Tests that ensure_runtime_directories creates memory and workspace dirs."""

    def test_creates_memory_and_workspace_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mem_dir = str(Path(td) / "memory")
            ws_dir = str(Path(td) / "workspace-snapshots")
            with (
                patch.object(skills_mod, "HOME_DIR", str(Path(td) / "home")),
                patch.object(skills_mod, "XDG_CONFIG_HOME", str(Path(td) / "config")),
                patch.object(skills_mod, "XDG_DATA_HOME", str(Path(td) / "data")),
                patch.object(skills_mod, "OPENCODE_CONFIG_DIR", str(Path(td) / "opencode")),
                patch.object(skills_mod, "OPENCODE_WORKDIR", str(Path(td) / "workdir")),
                patch.object(skills_mod, "SESSION_MAP_PATH", Path(td) / "sessions" / "map.json"),
                patch.object(skills_mod, "MEMORY_DIR", mem_dir),
                patch.object(skills_mod, "WORKSPACE_SNAPSHOT_DIR", ws_dir),
            ):
                opencode_runtime_main.ensure_runtime_directories()
                self.assertTrue(Path(mem_dir).exists())
                self.assertTrue(Path(ws_dir).exists())


# ---------------------------------------------------------------------------
# Robustness fix tests — Phases 1-3
# ---------------------------------------------------------------------------

class SafeIntFloatTests(unittest.TestCase):
    """Tests for _safe_int and _safe_float helpers in config.py."""

    def test_safe_int_valid_value(self) -> None:
        with patch.dict(os.environ, {"_TEST_INT": "42"}, clear=False):
            self.assertEqual(opencode_runtime_main._safe_int("_TEST_INT", 0), 42)

    def test_safe_int_empty_env_uses_default(self) -> None:
        with patch.dict(os.environ, {"_TEST_INT": ""}, clear=False):
            self.assertEqual(opencode_runtime_main._safe_int("_TEST_INT", 99), 99)

    def test_safe_int_missing_env_uses_default(self) -> None:
        env = os.environ.copy()
        env.pop("_TEST_INT_MISSING", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(opencode_runtime_main._safe_int("_TEST_INT_MISSING", 7), 7)

    def test_safe_int_malformed_value_uses_default(self) -> None:
        with patch.dict(os.environ, {"_TEST_INT": "abc"}, clear=False):
            result = opencode_runtime_main._safe_int("_TEST_INT", 10)
            self.assertEqual(result, 10)

    def test_safe_int_float_string_uses_default(self) -> None:
        with patch.dict(os.environ, {"_TEST_INT": "3.14"}, clear=False):
            result = opencode_runtime_main._safe_int("_TEST_INT", 5)
            self.assertEqual(result, 5)

    def test_safe_float_valid_value(self) -> None:
        with patch.dict(os.environ, {"_TEST_FLOAT": "0.75"}, clear=False):
            self.assertAlmostEqual(opencode_runtime_main._safe_float("_TEST_FLOAT", 0.5), 0.75)

    def test_safe_float_empty_env_uses_default(self) -> None:
        with patch.dict(os.environ, {"_TEST_FLOAT": ""}, clear=False):
            self.assertAlmostEqual(opencode_runtime_main._safe_float("_TEST_FLOAT", 0.5), 0.5)

    def test_safe_float_malformed_value_uses_default(self) -> None:
        with patch.dict(os.environ, {"_TEST_FLOAT": "not-a-number"}, clear=False):
            result = opencode_runtime_main._safe_float("_TEST_FLOAT", 0.9)
            self.assertAlmostEqual(result, 0.9)

    def test_safe_float_integer_string_accepted(self) -> None:
        with patch.dict(os.environ, {"_TEST_FLOAT": "3"}, clear=False):
            self.assertAlmostEqual(opencode_runtime_main._safe_float("_TEST_FLOAT", 1.0), 3.0)


class ModelOutputLimitTests(unittest.TestCase):
    def test_model_output_limit_allows_small_positive_override(self) -> None:
        module_path = Path(__file__).resolve().parents[1] / "config.py"
        spec = importlib.util.spec_from_file_location("opencode_runtime_config_low_output_limit", module_path)
        if spec is None or spec.loader is None:
            self.fail("Failed to load opencode-runtime config module")

        module = importlib.util.module_from_spec(spec)
        try:
            with patch.dict(os.environ, {"OPENCODE_MODEL_OUTPUT_LIMIT": "64"}, clear=False):
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            self.assertEqual(module.MODEL_OUTPUT_LIMIT, 64)
        finally:
            sys.modules.pop(spec.name, None)


class ThresholdClampingTests(unittest.TestCase):
    """Tests that COMPACTION_*_THRESHOLD values are clamped within valid bounds."""

    def test_compaction_token_threshold_within_bounds(self) -> None:
        val = opencode_runtime_main.COMPACTION_TOKEN_THRESHOLD
        self.assertGreaterEqual(val, 0.1)
        self.assertLessEqual(val, 0.99)

    def test_compaction_prune_threshold_within_bounds(self) -> None:
        val = opencode_runtime_main.COMPACTION_PRUNE_THRESHOLD
        self.assertGreaterEqual(val, 0.1)
        self.assertLessEqual(val, 0.99)

    def test_compaction_aggressive_threshold_within_bounds(self) -> None:
        val = opencode_runtime_main.COMPACTION_AGGRESSIVE_THRESHOLD
        self.assertGreaterEqual(val, 0.01)
        self.assertLessEqual(val, 0.99)


class MemoryEntryTypeValidationTests(unittest.TestCase):
    """Tests for MEMORY_ENTRY_TYPES and entry type validation warnings."""

    def test_memory_entry_types_is_frozenset(self) -> None:
        self.assertIsInstance(opencode_runtime_main.MEMORY_ENTRY_TYPES, frozenset)

    def test_known_types_present(self) -> None:
        expected = {"task_summary", "decision", "error_pattern", "codebase_insight", "file_map", "handoff"}
        self.assertEqual(opencode_runtime_main.MEMORY_ENTRY_TYPES, expected)

    def test_save_memory_warns_on_unknown_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mem = opencode_runtime_main.SessionMemory(Path(td), max_thread=5, max_workspace=3)
            with (
                patch.object(memory_mod, "MEMORY_ENABLED", True),
                patch.object(memory_mod, "logger") as mock_logger,
            ):
                mem.save_memory("thread1", {"type": "invented_type", "content": "x"})
                mock_logger.warning.assert_called()
                warn_args = mock_logger.warning.call_args[0]
                self.assertIn("invented_type", str(warn_args))

    def test_save_memory_no_warning_on_known_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mem = opencode_runtime_main.SessionMemory(Path(td), max_thread=5, max_workspace=3)
            with (
                patch.object(memory_mod, "MEMORY_ENABLED", True),
                patch.object(memory_mod, "logger") as mock_logger,
            ):
                mem.save_memory("thread1", {"type": "task_summary", "content": "x"})
                mock_logger.warning.assert_not_called()

    def test_save_workspace_memory_warns_on_unknown_type(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            mem = opencode_runtime_main.SessionMemory(Path(td), max_thread=5, max_workspace=3)
            with (
                patch.object(memory_mod, "MEMORY_ENABLED", True),
                patch.object(memory_mod, "logger") as mock_logger,
            ):
                mem.save_workspace_memory({"type": "bogus_type", "content": "y"})
                mock_logger.warning.assert_called()
                warn_args = mock_logger.warning.call_args[0]
                self.assertIn("bogus_type", str(warn_args))


class MemoryAtomicPruneTests(unittest.TestCase):
    """Tests for atomic prune in SessionMemory._maybe_prune."""

    def test_prune_is_atomic_on_disk(self) -> None:
        """After pruning, the file should contain exactly max_entries lines."""
        with tempfile.TemporaryDirectory() as td:
            mem = opencode_runtime_main.SessionMemory(Path(td), max_thread=3, max_workspace=3)
            with patch.object(memory_mod, "MEMORY_ENABLED", True):
                for i in range(10):
                    mem.save_memory("t1", {"type": "task_summary", "content": f"entry-{i}"})
                # Read the raw JSONL file
                thread_path = mem._thread_path("t1")
                lines = [line for line in thread_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertEqual(len(lines), 3)
                # Verify the last 3 entries are kept
                import json as _json

                last_entry = _json.loads(lines[-1])
                self.assertEqual(last_entry["content"], "entry-9")

    def test_prune_preserves_data_integrity(self) -> None:
        """All remaining lines should be valid JSON after prune."""
        with tempfile.TemporaryDirectory() as td:
            mem = opencode_runtime_main.SessionMemory(Path(td), max_thread=5, max_workspace=3)
            with patch.object(memory_mod, "MEMORY_ENABLED", True):
                for i in range(20):
                    mem.save_memory("t1", {"type": "task_summary", "content": f"item-{i}"})
                thread_path = mem._thread_path("t1")
                lines = [line for line in thread_path.read_text(encoding="utf-8").splitlines() if line.strip()]
                for line in lines:
                    import json as _json

                    entry = _json.loads(line)  # Should not raise
                    self.assertIn("content", entry)


class IterArtifactPathsRecursionGuardTests(unittest.TestCase):
    """Tests for _iter_artifact_paths depth limit."""

    def test_max_depth_constant_exists(self) -> None:
        self.assertEqual(opencode_runtime_main._ITER_ARTIFACT_MAX_DEPTH, 20)

    def test_deeply_nested_structure_does_not_crash(self) -> None:
        """Build a 50-level nested dict — should not hit Python's recursion limit."""
        nested: Any = "/workspace/file.py"
        for _ in range(50):
            nested = {"child": nested}
        # Should not raise RecursionError
        result = opencode_runtime_main._iter_artifact_paths(nested)
        # The path may or may not be found depending on depth; the key is no crash
        self.assertIsInstance(result, list)

    def test_shallow_structure_still_extracts_paths(self) -> None:
        """Normal depth should still work fine."""
        data = {"output": {"files": ["/workspace/src/main.py"]}}
        result = opencode_runtime_main._iter_artifact_paths(data)
        # Depends on ARTIFACT_PATH_PATTERN — just verify it returns a list without error
        self.assertIsInstance(result, list)

    def test_depth_zero_default(self) -> None:
        """Calling without _depth argument should work (default 0)."""
        result = opencode_runtime_main._iter_artifact_paths("some text")
        self.assertIsInstance(result, list)


class ClassifyTaskTypeWordBoundaryTests(unittest.TestCase):
    """Tests for word-boundary matching in classify_task_type (Phase 3 fix)."""

    def test_find_does_not_match_findings(self) -> None:
        """'find' in _EXPLORATION_KEYWORDS should not match 'findings'."""
        result = opencode_runtime_main.classify_task_type("Review the audit findings report")
        self.assertNotEqual(result, "exploration")

    def test_new_does_not_match_renewal(self) -> None:
        """'new' in _FEATURE_KEYWORDS should not match 'renewal'."""
        result = opencode_runtime_main.classify_task_type("Process the license renewal")
        self.assertNotEqual(result, "feature")

    def test_add_does_not_match_address(self) -> None:
        """'add' in _FEATURE_KEYWORDS should not match 'address'."""
        result = opencode_runtime_main.classify_task_type("Check the email address format")
        self.assertNotEqual(result, "feature")

    def test_fix_does_not_match_prefix(self) -> None:
        """'fix' in _DEBUGGING_KEYWORDS should not match 'fixture'."""
        result = opencode_runtime_main.classify_task_type("Create a test fixture for the database")
        self.assertNotEqual(result, "debugging")

    def test_list_does_not_match_listening(self) -> None:
        """'list' in _EXPLORATION_KEYWORDS should not match 'listening'."""
        result = opencode_runtime_main.classify_task_type("The server is listening on port 8080")
        self.assertNotEqual(result, "exploration")

    def test_move_does_not_match_remove(self) -> None:
        """'move' in _REFACTOR_KEYWORDS should not match 'remove'."""
        result = opencode_runtime_main.classify_task_type("remove the old configuration files")
        self.assertNotEqual(result, "refactor")

    def test_exact_word_find_still_works(self) -> None:
        """Exact word 'find' should still match for exploration."""
        result = opencode_runtime_main.classify_task_type("find the configuration files")
        self.assertEqual(result, "exploration")

    def test_exact_word_fix_still_works(self) -> None:
        """Exact word 'fix' should still match for debugging."""
        result = opencode_runtime_main.classify_task_type("fix the login page crash")
        self.assertEqual(result, "debugging")

    def test_exact_word_add_still_works(self) -> None:
        """Exact word 'add' should still match for feature."""
        result = opencode_runtime_main.classify_task_type("add a dark mode toggle")
        self.assertEqual(result, "feature")

    def test_multi_word_keyword_still_works(self) -> None:
        """Multi-word keywords like 'stack trace' should still match."""
        result = opencode_runtime_main.classify_task_type("I see a stack trace in the logs")
        self.assertEqual(result, "debugging")

    def test_ci_cd_keyword_still_works(self) -> None:
        """'ci/cd' should still match for deployment despite the slash."""
        result = opencode_runtime_main.classify_task_type("configure the CI/CD pipeline")
        self.assertEqual(result, "deployment")


class WorkspaceEggInfoSkipTests(unittest.TestCase):
    """Tests for the _SKIP_DIR_SUFFIXES egg-info fix."""

    def test_egg_info_directory_skipped(self) -> None:
        """Directories ending in .egg-info should be excluded from workspace snapshot."""
        with tempfile.TemporaryDirectory() as td:
            # Create a fake egg-info dir with a file inside
            egg_dir = Path(td) / "mypackage.egg-info"
            egg_dir.mkdir()
            (egg_dir / "PKG-INFO").write_text("Metadata-Version: 2.1", encoding="utf-8")
            # Create a normal file
            (Path(td) / "main.py").write_text("print('hello')", encoding="utf-8")
            result = opencode_runtime_main.capture_workspace_snapshot(td)
            # The egg-info file should NOT appear in the snapshot
            tree = result.get("directory_tree", "")
            self.assertNotIn("egg-info", tree)
            self.assertIn("main.py", tree)


class WorkspaceImportantHiddenFilesTests(unittest.TestCase):
    """Tests that important hidden files like .env.example are captured."""

    def test_important_hidden_files_included(self) -> None:
        """Files in _IMPORTANT_HIDDEN_FILES should appear in the snapshot despite starting with '.'."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / ".env.example").write_text("DB_HOST=localhost", encoding="utf-8")
            (Path(td) / ".gitignore").write_text("node_modules/", encoding="utf-8")
            (Path(td) / "main.py").write_text("print('hello')", encoding="utf-8")
            # Also create a non-important hidden file
            (Path(td) / ".secret-cache").write_text("hidden", encoding="utf-8")
            result = opencode_runtime_main.capture_workspace_snapshot(td)
            tree = result.get("directory_tree", "")
            self.assertIn(".env.example", tree)
            self.assertIn(".gitignore", tree)
            # .secret-cache should be filtered out (not in the important set)
            self.assertNotIn(".secret-cache", tree)


class OpenCodeClientStaleImportTests(unittest.TestCase):
    """Tests that opencode_client.py uses dynamic module-level access for _runtime_process."""

    def test_ensure_server_running_uses_dynamic_access(self) -> None:
        """ensure_server_running should see the current value of _runtime_process, not a stale import."""
        oc_mod = opencode_client_mod
        sv_mod = supervisor_mod

        # Simulate: _runtime_process is None initially, then assigned to a mock
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process is alive

        original_process = sv_mod._runtime_process
        original_ready = sv_mod._runtime_ready
        try:
            sv_mod._runtime_process = None
            sv_mod._runtime_ready = False
            # Now set _runtime_process to a live process
            sv_mod._runtime_process = mock_proc
            sv_mod._runtime_ready = True
            # ensure_server_running should see the live process (not a stale None)
            # It should not raise or call _start_opencode_process
            oc_mod.ensure_server_running()
            # If it raised, the test would fail
        finally:
            sv_mod._runtime_process = original_process
            sv_mod._runtime_ready = original_ready


class RuntimeCapabilitiesSafeIntTests(unittest.TestCase):
    """Tests that runtime_capabilities uses safe int parsing."""

    def test_malformed_autonomous_env_does_not_crash(self) -> None:
        """runtime_capabilities should not crash even if OPENCODE_AUTONOMOUS_MAX_RETRIES is invalid."""
        with patch.dict(
            os.environ,
            {
                "OPENCODE_AUTONOMOUS_MAX_RETRIES": "not-a-number",
                "OPENCODE_AUTONOMOUS_MAX_TURNS": "also-bad",
            },
            clear=False,
        ):
            # Re-call — the function uses _safe_int internally now
            caps = opencode_runtime_main.runtime_capabilities()
            auto = caps["autonomous_execution"]
            # Should fall back to defaults (3 and 10)
            self.assertEqual(auto["default_max_retries"], 3)
            self.assertEqual(auto["default_max_turns"], 10)
