import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("opencode_runtime_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load opencode-runtime main module for tests")
opencode_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = opencode_runtime_main
SPEC.loader.exec_module(opencode_runtime_main)


class OpenCodeRuntimeTests(unittest.TestCase):
    def test_request_rejects_thread_id_when_no_session_is_enabled(self) -> None:
        with self.assertRaises(ValueError):
            opencode_runtime_main.InvokeRequest(prompt="hello", thread_id="thread-1", no_session=True)

    def test_materialize_opencode_config_files_writes_into_config_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            opencode_runtime_main,
            "OPENCODE_CONFIG_DIR",
            str(Path(temp_dir) / "config"),
        ), patch.dict(
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
        ):
            written = opencode_runtime_main.materialize_opencode_config_files()
            root = Path(opencode_runtime_main.OPENCODE_CONFIG_DIR)

            self.assertEqual(written, ["opencode.json", "plugins/custom.ts"])
            self.assertEqual(
                json.loads((root / "opencode.json").read_text(encoding="utf-8")),
                {"default_agent": "build"},
            )
            self.assertIn("Plugin", (root / "plugins" / "custom.ts").read_text(encoding="utf-8"))

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
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            opencode_runtime_main,
            "OPENCODE_CONFIG_DIR",
            str(Path(temp_dir) / "config"),
        ), patch.dict(
            os.environ,
            {opencode_runtime_main.AGENT_SKILL_FILES_ENV: json.dumps({".github/skills/reviewer/SKILL.md": skill_text})},
            clear=False,
        ):
            written, warnings = opencode_runtime_main.materialize_skill_files()
            target = Path(opencode_runtime_main.OPENCODE_CONFIG_DIR) / "skills" / "reviewer" / "SKILL.md"

            self.assertEqual(written, ["skills/reviewer/SKILL.md"])
            self.assertEqual(warnings, [])
            self.assertEqual(target.read_text(encoding="utf-8"), skill_text)

    def test_parse_skill_frontmatter_normalizes_invalid_name(self) -> None:
        content = (
            "---\n"
            "name: My_Invalid Skill Name!!!\n"
            "description: Test skill\n"
            "---\n"
            "Body\n"
        )
        name, warnings = opencode_runtime_main.parse_skill_frontmatter(
            ".github/skills/reviewer/SKILL.md",
            content,
        )
        self.assertEqual(name, "my-invalid-skill-name")
        self.assertTrue(any("Materialized skill" in warning for warning in warnings))

    def test_parse_skill_frontmatter_falls_back_for_overlong_name(self) -> None:
        content = (
            "---\n"
            "name: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "description: Test skill\n"
            "---\n"
            "Body\n"
        )
        name, warnings = opencode_runtime_main.parse_skill_frontmatter(
            ".github/skills/reviewer/SKILL.md",
            content,
        )
        self.assertEqual(name, "reviewer")
        self.assertTrue(any("invalid frontmatter name" in warning for warning in warnings))

    def test_build_generated_config_includes_sidecars_and_shared_mcp_servers(self) -> None:
        with patch.dict(
            os.environ,
            {"MCP_SERVERS": "documents,github"},
            clear=False,
        ), patch.object(opencode_runtime_main, "MCP_BEARER_TOKEN", "token-123"), patch.object(
            opencode_runtime_main,
            "HELM_RELEASE_NAME",
            "sandbox",
        ), patch.object(
            opencode_runtime_main,
            "MCP_HUB_NAMESPACE",
            "mcp-hub",
        ):
            config, warnings = opencode_runtime_main.build_generated_config([{"name": "browser", "port": 8081}])

        self.assertEqual(config["mcp"]["browser"]["url"], "http://127.0.0.1:8081/mcp")
        self.assertEqual(
            config["mcp"]["documents"]["url"],
            "http://sandbox-mcp-documents.mcp-hub.svc.cluster.local:8000/mcp",
        )
        self.assertEqual(config["mcp"]["documents"]["headers"]["Authorization"], "Bearer token-123")
        self.assertTrue(any("GitHub MCP" in warning for warning in warnings))

    def test_session_registry_persists_logical_thread_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = opencode_runtime_main.SessionRegistry(Path(temp_dir) / "sessions.json")
            registry.set("thread-a", "ses_123")

            self.assertEqual(registry.get("thread-a"), "ses_123")
            self.assertEqual(json.loads((Path(temp_dir) / "sessions.json").read_text(encoding="utf-8")), {"thread-a": "ses_123"})


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
        messages = [
            {
                "parts": [
                    {"type": "patch", "files": ["src/app.ts", "src/utils.ts"], "hash": "abc123"}
                ]
            }
        ]
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
                        "state": {"status": "completed", "input": {"filePath": "/workspace/file.py", "oldString": "v1", "newString": "v2"}},
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
        # finish string → treated as incomplete (we cannot confirm completion)
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

    def test_get_latest_assistant_payload_returns_last_assistant(self) -> None:
        messages = [
            {"info": {"role": "user"}, "parts": []},
            {"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "first"}]},
            {"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "second"}]},
        ]
        payload = opencode_runtime_main.get_latest_assistant_payload(messages)
        self.assertEqual(payload["parts"][0]["text"], "second")

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
        resp = opencode_runtime_main.InvokeResponse(
            thread_id="t1", response="done", model="gpt-4"
        )
        self.assertEqual(resp.artifacts, [])
        self.assertEqual(resp.tool_calls, [])
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

        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_messages("nonexistent")
        self.assertEqual(result, [])

    def test_returns_parsed_messages(self) -> None:
        sample_messages = [
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": "hello"}]},
            {
                "info": {"role": "assistant"},
                "parts": [
                    {"type": "text", "text": "Hi!"},
                    {"type": "tool", "tool": "write", "state": {"status": "completed", "input": {"filePath": "/workspace/test.py"}}},
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

        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mock_client):
            result = opencode_runtime_main.get_session_messages("ses_abc")
        self.assertEqual(len(result), 2)


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
                            "input": {"filePath": "/workspace/README.md", "content": "# My Project\n\nA great project."},
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
                            "input": {"filePath": "/workspace/fib.py", "content": "def fib(n):\n    if n <= 1: return n\n    return fib(n-1) + fib(n-2)\n"},
                            "output": "File written",
                        },
                    },
                    {
                        "type": "tool",
                        "tool": "bash",
                        "callID": "c2",
                        "state": {
                            "status": "completed",
                            "input": {"command": "python -c \"from fib import fib; print(fib(10))\""},
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
                            "input": {"filePath": "/workspace/app.py", "content": "from flask import Flask\napp = Flask(__name__)\n"},
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


# ---------------------------------------------------------------------------
# Phase 6 – Session management helper tests
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
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertTrue(opencode_runtime_main.abort_session("ses_1"))
        mc.post.assert_called_once_with("/session/ses_1/abort")

    def test_returns_false_on_non_200(self) -> None:
        mc = self._mock_client(404)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.abort_session("ses_x"))

    def test_returns_false_on_http_error(self) -> None:
        import httpx
        mc = MagicMock()
        mc.post.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.abort_session("ses_err"))


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
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertTrue(opencode_runtime_main.summarize_session("ses_1"))
        mc.post.assert_called_once_with("/session/ses_1/summarize")

    def test_returns_false_on_failure(self) -> None:
        mc = self._mock_client(500)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.summarize_session("ses_x"))

    def test_returns_false_on_http_error(self) -> None:
        import httpx
        mc = MagicMock()
        mc.post.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
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
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertTrue(opencode_runtime_main.init_session("ses_1"))
        call_kwargs = mc.post.call_args
        self.assertIn("/session/ses_1/init", call_kwargs.args or (call_kwargs[0],))
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        self.assertIn("providerID", body)
        self.assertIn("modelID", body)
        self.assertIn("messageID", body)

    def test_returns_false_on_failure(self) -> None:
        mc = self._mock_client(500)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            self.assertFalse(opencode_runtime_main.init_session("ses_x"))

    def test_returns_false_on_http_error(self) -> None:
        import httpx
        mc = MagicMock()
        mc.post.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
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
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Write code")

    def test_returns_empty_on_404(self) -> None:
        mc = self._mock_client(404, None)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_x")
        self.assertEqual(result, [])

    def test_filters_non_dict_items(self) -> None:
        mc = self._mock_client(200, [{"id": "1"}, "bad", 42, {"id": "2"}])
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_1")
        self.assertEqual(len(result), 2)

    def test_returns_empty_on_http_error(self) -> None:
        import httpx
        mc = MagicMock()
        mc.get.side_effect = httpx.ConnectError("connection refused")
        mc.__enter__ = MagicMock(return_value=mc)
        mc.__exit__ = MagicMock(return_value=False)
        with patch.object(opencode_runtime_main, "runtime_http_client", return_value=mc):
            result = opencode_runtime_main.get_session_todos("ses_err")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Phase 6 – Context overflow and error classification tests
# ---------------------------------------------------------------------------


class CheckContextOverflowTests(unittest.TestCase):
    """Tests for check_context_overflow."""

    def test_detects_context_overflow_error(self) -> None:
        payload = {"info": {"error": {"name": "ContextOverflowError", "message": "overflow"}}}
        self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_detects_high_token_usage(self) -> None:
        # With default MODEL_CONTEXT_LIMIT=128000 and COMPACTION_TOKEN_THRESHOLD=0.75
        # threshold = 96000
        with patch.object(opencode_runtime_main, "MODEL_CONTEXT_LIMIT", 100000), \
             patch.object(opencode_runtime_main, "COMPACTION_TOKEN_THRESHOLD", 0.75):
            payload = {"info": {"tokens": {"input": 60000, "output": 20000, "total": 80000}}}
            self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_no_overflow_for_low_token_usage(self) -> None:
        with patch.object(opencode_runtime_main, "MODEL_CONTEXT_LIMIT", 100000), \
             patch.object(opencode_runtime_main, "COMPACTION_TOKEN_THRESHOLD", 0.75):
            payload = {"info": {"tokens": {"input": 1000, "output": 500, "total": 1500}}}
            self.assertFalse(opencode_runtime_main.check_context_overflow(payload))

    def test_no_overflow_on_empty_payload(self) -> None:
        self.assertFalse(opencode_runtime_main.check_context_overflow({}))

    def test_no_overflow_when_info_not_dict(self) -> None:
        self.assertFalse(opencode_runtime_main.check_context_overflow({"info": "bad"}))

    def test_calculates_total_from_parts_when_total_missing(self) -> None:
        with patch.object(opencode_runtime_main, "MODEL_CONTEXT_LIMIT", 100000), \
             patch.object(opencode_runtime_main, "COMPACTION_TOKEN_THRESHOLD", 0.75):
            payload = {"info": {"tokens": {"input": 50000, "output": 30000}}}
            self.assertTrue(opencode_runtime_main.check_context_overflow(payload))

    def test_non_overflow_error_not_detected(self) -> None:
        payload = {"info": {"error": {"name": "APIError", "message": "server error"}}}
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
# Phase 6 – Agent selection tests
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
        with patch.object(opencode_runtime_main, "DEFAULT_AGENT", "build"), \
             patch.object(opencode_runtime_main, "PLAN_AGENT_PROMPT_THRESHOLD", 100):
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
        with patch.object(opencode_runtime_main, "DEFAULT_AGENT", "build"), \
             patch.object(opencode_runtime_main, "PLAN_AGENT_PROMPT_THRESHOLD", 10000):
            result = opencode_runtime_main.select_agent_for_prompt("short prompt", is_first_turn=True)
            self.assertEqual(result, "build")

    def test_returns_default_when_agent_is_not_build(self) -> None:
        with patch.object(opencode_runtime_main, "DEFAULT_AGENT", "general"):
            long_prompt = "step 1: do this\nstep 2: do that\nstep 3: finalize\n" * 50
            result = opencode_runtime_main.select_agent_for_prompt(long_prompt, is_first_turn=True)
            self.assertEqual(result, "general")


# ---------------------------------------------------------------------------
# Phase 6 – detect_completion_status context_overflow tests
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
# Phase 6 – Enhanced runtime_capabilities tests
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
        self.assertEqual(sm["compaction_threshold"], opencode_runtime_main.COMPACTION_TOKEN_THRESHOLD)

    def test_native_tools_include_new_tools(self) -> None:
        caps = opencode_runtime_main.runtime_capabilities()
        for tool in ("webfetch", "websearch", "codesearch", "skill", "question", "task", "todowrite"):
            self.assertIn(tool, caps["native_tools"])


# ---------------------------------------------------------------------------
# Phase 6 – invoke_opencode loop integration tests (mocked)
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
        return patch.object(opencode_runtime_main, "ensure_server_running")

    def _patch_create_session(self, session_id: str = "ses_test"):
        return patch.object(opencode_runtime_main, "create_remote_session", return_value=session_id)

    def _patch_send_prompt(self, payloads: list[dict]):
        """Patch _send_prompt_with_session_recovery to return successive payloads."""
        call_count = {"n": 0}

        def side_effect(**kwargs):
            idx = min(call_count["n"], len(payloads) - 1)
            call_count["n"] += 1
            return kwargs.get("session_id", "ses_test"), payloads[idx]

        return patch.object(opencode_runtime_main, "_send_prompt_with_session_recovery", side_effect=side_effect)

    def _patch_session_helpers(self):
        """Patch session-collection helpers to avoid real HTTP calls."""
        return [
            patch.object(opencode_runtime_main, "get_session_messages", return_value=[]),
            patch.object(opencode_runtime_main, "get_session_todos", return_value=[]),
            patch.object(opencode_runtime_main, "wait_for_session_idle", return_value={"type": "idle"}),
            patch.object(opencode_runtime_main, "abort_session", return_value=True),
            patch.object(opencode_runtime_main, "summarize_session", return_value=True),
        ]

    def _run_invoke(self, request_kwargs: dict, payloads: list[dict]) -> opencode_runtime_main.InvokeResponse:
        request = opencode_runtime_main.InvokeRequest(**request_kwargs)
        with self._patch_server_running(), \
             self._patch_create_session(), \
             self._patch_send_prompt(payloads) as mock_send:
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

    def test_plan_agent_switch_to_build(self) -> None:
        """When plan agent finishes, loop should switch to build agent."""
        with patch.object(opencode_runtime_main, "PLAN_AGENT_PROMPT_THRESHOLD", 10), \
             patch.object(opencode_runtime_main, "DEFAULT_AGENT", "build"):
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
        with self._patch_server_running(), \
             self._patch_create_session(), \
             self._patch_send_prompt([payload]) as mock_send:
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
        with self._patch_server_running(), \
             self._patch_create_session(), \
             patch.object(opencode_runtime_main, "_send_prompt_with_session_recovery", side_effect=side_effect):
            patches = self._patch_session_helpers()
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                resp = opencode_runtime_main.invoke_opencode(req)
        self.assertEqual(resp.status, "completed")
        self.assertTrue(any("HTTP error" in w for w in resp.warnings))

    def test_todos_included_in_metadata(self) -> None:
        todos = [{"id": "1", "title": "Write code", "status": "done"}]
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build it")
        with self._patch_server_running(), \
             self._patch_create_session(), \
             self._patch_send_prompt([payload]):
            with patch.object(opencode_runtime_main, "get_session_messages", return_value=[]), \
                 patch.object(opencode_runtime_main, "get_session_todos", return_value=todos), \
                 patch.object(opencode_runtime_main, "wait_for_session_idle", return_value={"type": "idle"}), \
                 patch.object(opencode_runtime_main, "abort_session", return_value=True), \
                 patch.object(opencode_runtime_main, "summarize_session", return_value=True):
                resp = opencode_runtime_main.invoke_opencode(req)
        self.assertIsNotNone(resp.metadata)
        self.assertEqual(resp.metadata["todos"], todos)

    def test_session_init_called_for_new_autonomous_session(self) -> None:
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build feature", autonomous=True)
        mock_init = MagicMock(return_value=True)
        with self._patch_server_running(), \
             self._patch_create_session(), \
             self._patch_send_prompt([payload]), \
             patch.object(opencode_runtime_main, "init_session", mock_init), \
             patch.object(opencode_runtime_main, "SESSION_INIT_ON_CREATE", True):
            with patch.object(opencode_runtime_main, "get_session_messages", return_value=[]), \
                 patch.object(opencode_runtime_main, "get_session_todos", return_value=[]), \
                 patch.object(opencode_runtime_main, "wait_for_session_idle", return_value={"type": "idle"}), \
                 patch.object(opencode_runtime_main, "abort_session", return_value=True), \
                 patch.object(opencode_runtime_main, "summarize_session", return_value=True):
                opencode_runtime_main.invoke_opencode(req)
        mock_init.assert_called_once()

    def test_session_init_not_called_when_disabled(self) -> None:
        payload = self._make_payload("All done", "stop")
        req = opencode_runtime_main.InvokeRequest(prompt="Build feature", autonomous=True)
        mock_init = MagicMock(return_value=True)
        with self._patch_server_running(), \
             self._patch_create_session(), \
             self._patch_send_prompt([payload]), \
             patch.object(opencode_runtime_main, "init_session", mock_init), \
             patch.object(opencode_runtime_main, "SESSION_INIT_ON_CREATE", False):
            with patch.object(opencode_runtime_main, "get_session_messages", return_value=[]), \
                 patch.object(opencode_runtime_main, "get_session_todos", return_value=[]), \
                 patch.object(opencode_runtime_main, "wait_for_session_idle", return_value={"type": "idle"}), \
                 patch.object(opencode_runtime_main, "abort_session", return_value=True), \
                 patch.object(opencode_runtime_main, "summarize_session", return_value=True):
                opencode_runtime_main.invoke_opencode(req)
        mock_init.assert_not_called()

    def test_stuck_session_gets_aborted(self) -> None:
        """If session remains busy after invoke, it should be aborted."""
        payload = self._make_payload("Working", "tool-calls")
        req = opencode_runtime_main.InvokeRequest(prompt="Test", max_turns=1)
        mock_abort = MagicMock(return_value=True)
        busy_status = {"type": "busy"}
        with self._patch_server_running(), \
             self._patch_create_session(), \
             self._patch_send_prompt([payload]):
            with patch.object(opencode_runtime_main, "get_session_messages", return_value=[]), \
                 patch.object(opencode_runtime_main, "get_session_todos", return_value=[]), \
                 patch.object(opencode_runtime_main, "wait_for_session_idle", return_value=busy_status), \
                 patch.object(opencode_runtime_main, "abort_session", mock_abort) as abort_mock, \
                 patch.object(opencode_runtime_main, "summarize_session", return_value=True):
                resp = opencode_runtime_main.invoke_opencode(req)
        mock_abort.assert_called()
        self.assertTrue(any("aborted" in w.lower() for w in resp.warnings))

    def test_proactive_compaction_on_high_tokens(self) -> None:
        """If token usage is high but no context_overflow, proactively compact."""
        with patch.object(opencode_runtime_main, "MODEL_CONTEXT_LIMIT", 100000), \
             patch.object(opencode_runtime_main, "COMPACTION_TOKEN_THRESHOLD", 0.75):
            payload = self._make_payload("Done", "stop", tokens={"input": 60000, "output": 20000, "total": 80000})
            mock_summarize = MagicMock(return_value=True)
            req = opencode_runtime_main.InvokeRequest(prompt="Process")
            with self._patch_server_running(), \
                 self._patch_create_session(), \
                 self._patch_send_prompt([payload]):
                with patch.object(opencode_runtime_main, "get_session_messages", return_value=[]), \
                     patch.object(opencode_runtime_main, "get_session_todos", return_value=[]), \
                     patch.object(opencode_runtime_main, "wait_for_session_idle", return_value={"type": "idle"}), \
                     patch.object(opencode_runtime_main, "abort_session", return_value=True), \
                     patch.object(opencode_runtime_main, "summarize_session", mock_summarize):
                    resp = opencode_runtime_main.invoke_opencode(req)
            mock_summarize.assert_called()
            self.assertTrue(any("compaction" in w.lower() for w in resp.warnings))


if __name__ == "__main__":
    unittest.main()