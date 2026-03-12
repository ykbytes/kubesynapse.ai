import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("goose_runtime_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load goose-runtime main module for tests")
goose_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = goose_runtime_main
SPEC.loader.exec_module(goose_runtime_main)


class GooseRuntimeTests(unittest.TestCase):
    def test_request_rejects_thread_id_when_no_session_is_enabled(self) -> None:
        with self.assertRaises(ValueError):
            goose_runtime_main.InvokeRequest(prompt="hello", thread_id="thread-1", no_session=True)

    def test_request_normalizes_blank_optional_fields(self) -> None:
        request = goose_runtime_main.InvokeRequest(
            prompt="  hello  ",
            thread_id="   ",
            model="  ",
            system="   ",
            approval_action="   ",
            builtin_extensions=[" developer ", "   "],
            stdio_extensions=[" echo tool ", "   "],
            streamable_http_extensions=[" https://example.com/mcp ", "   "],
        )

        self.assertEqual(request.prompt, "hello")
        self.assertIsNone(request.thread_id)
        self.assertIsNone(request.model)
        self.assertIsNone(request.system)
        self.assertIsNone(request.approval_action)
        self.assertEqual(request.builtin_extensions, ["developer"])
        self.assertEqual(request.stdio_extensions, ["echo tool"])
        self.assertEqual(request.streamable_http_extensions, ["https://example.com/mcp"])

    def test_request_accepts_team_context_object(self) -> None:
        request = goose_runtime_main.InvokeRequest(
            prompt="hello",
            team_context={"objective": "Investigate the regression."},
        )

        self.assertEqual(request.team_context, {"objective": "Investigate the regression."})

    def test_parse_skill_definition_extracts_goose_extension_grants(self) -> None:
        definition = goose_runtime_main.parse_skill_definition(
            ".github/skills/reviewer/SKILL.md",
            (
                "---\n"
                "name: reviewer\n"
                "description: Review code changes.\n"
                "gooseBuiltinExtensions:\n"
                "  - developer\n"
                "gooseStdioExtensions:\n"
                "  - echo reviewer-tool\n"
                "gooseStreamableHttpExtensions:\n"
                "  - https://example.com/mcp\n"
                "---\n"
                "Review conservatively and explain risks first.\n"
            ),
        )

        self.assertEqual(definition["name"], "reviewer")
        self.assertEqual(definition["gooseBuiltinExtensions"], ["developer"])
        self.assertEqual(definition["gooseStdioExtensions"], ["echo reviewer-tool"])
        self.assertEqual(definition["gooseStreamableHttpExtensions"], ["https://example.com/mcp"])

    def test_validate_skill_extension_request_rejects_ungranted_extensions(self) -> None:
        request = goose_runtime_main.InvokeRequest(
            prompt="hello",
            builtin_extensions=["developer"],
            stdio_extensions=["echo reviewer-tool"],
            streamable_http_extensions=["https://example.com/mcp"],
        )

        with patch.object(
            goose_runtime_main,
            "SKILL_RUNTIME_CONFIG",
            {
                "skills": [{"name": "reviewer"}],
                "gooseBuiltinExtensions": frozenset({"developer"}),
                "gooseStdioExtensions": frozenset(),
                "gooseStreamableHttpExtensions": frozenset(),
                "warnings": [],
            },
        ):
            with self.assertRaises(HTTPException) as context:
                goose_runtime_main.validate_skill_extension_request(request)

        self.assertIn("stdio", str(context.exception.detail))

    def test_request_rejects_invalid_team_context_shape(self) -> None:
        with self.assertRaises(ValueError):
            goose_runtime_main.InvokeRequest(prompt="hello", team_context=["not-an-object"])

    def test_build_goose_run_command_supports_documented_run_flags(self) -> None:
        command = goose_runtime_main.build_goose_run_command(
            model="gpt-4",
            session_name="thread-1",
            output_format="json",
            resume=True,
            system_prompt="stay read-only",
            max_turns=12,
            debug=True,
            no_session=False,
            builtin_extensions=["developer"],
            stdio_extensions=["echo custom-tool"],
            streamable_http_extensions=["https://example.com/mcp"],
        )

        self.assertIn("--instructions", command)
        self.assertIn("-", command)
        self.assertNotIn("--text", command)
        self.assertIn("--resume", command)
        self.assertIn("--debug", command)
        self.assertIn("--max-turns", command)
        self.assertIn("--with-builtin", command)
        self.assertIn("--with-extension", command)
        self.assertIn("--with-streamable-http-extension", command)

    def test_resolve_working_directory_stays_within_workspace(self) -> None:
        original_workdir = goose_runtime_main.GOOSE_WORKDIR
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            nested = workspace / "nested"
            nested.mkdir()
            goose_runtime_main.GOOSE_WORKDIR = str(workspace)
            try:
                resolved = Path(goose_runtime_main.resolve_working_directory("nested"))
                self.assertEqual(resolved, nested.resolve())

                with self.assertRaises(HTTPException):
                    goose_runtime_main.resolve_working_directory(str(workspace.parent))
            finally:
                goose_runtime_main.GOOSE_WORKDIR = original_workdir

    def test_build_goose_environment_sets_headless_defaults(self) -> None:
        env = goose_runtime_main.build_goose_environment("gpt-4")

        self.assertEqual(env["GOOSE_DISABLE_SESSION_NAMING"], "true")
        self.assertEqual(env["GOOSE_DISABLE_KEYRING"], "1")
        self.assertEqual(env["GOOSE_MODEL"], "gpt-4")

    def test_materialize_goose_config_files_writes_config_root_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            goose_runtime_main,
            "XDG_CONFIG_HOME",
            str(Path(temp_dir) / ".config"),
        ), patch.dict(
            goose_runtime_main.os.environ,
            {
                "GOOSE_RUNTIME_CONFIG_FILES_JSON": json.dumps(
                    {
                        "config.yaml": "GOOSE_MODE: smart_approve\nGOOSE_MAX_TURNS: 25",
                        "prompts/review.md": "Review conservatively.",
                    }
                )
            },
            clear=False,
        ):
            written_files = goose_runtime_main.materialize_goose_config_files()
            config_root = goose_runtime_main.goose_config_root()

            self.assertEqual(written_files, ["config.yaml", "prompts/review.md"])
            self.assertEqual(
                (config_root / "config.yaml").read_text(encoding="utf-8"),
                "GOOSE_MODE: smart_approve\nGOOSE_MAX_TURNS: 25\n",
            )
            self.assertEqual(
                (config_root / "prompts" / "review.md").read_text(encoding="utf-8"),
                "Review conservatively.\n",
            )

    def test_load_skill_runtime_config_builds_prompt_and_extension_sets(self) -> None:
        with patch.dict(
            goose_runtime_main.os.environ,
            {
                goose_runtime_main.SKILL_FILES_ENV: json.dumps(
                    {
                        ".github/skills/reviewer/SKILL.md": (
                            "---\n"
                            "name: reviewer\n"
                            "description: Review code changes.\n"
                            "gooseBuiltinExtensions:\n"
                            "  - developer\n"
                            "gooseStdioExtensions:\n"
                            "  - echo reviewer-tool\n"
                            "---\n"
                            "Review conservatively and explain risks first.\n"
                        )
                    }
                )
            },
            clear=False,
        ):
            config = goose_runtime_main.load_skill_runtime_config()

        self.assertEqual(config["skillFiles"], [".github/skills/reviewer/SKILL.md"])
        self.assertEqual(config["gooseBuiltinExtensions"], frozenset({"developer"}))
        self.assertEqual(config["gooseStdioExtensions"], frozenset({"echo reviewer-tool"}))
        self.assertIn("reviewer", config["prompt"])

    def test_materialize_goose_config_files_rejects_runtime_managed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            goose_runtime_main,
            "XDG_CONFIG_HOME",
            str(Path(temp_dir) / ".config"),
        ), patch.dict(
            goose_runtime_main.os.environ,
            {
                "GOOSE_RUNTIME_CONFIG_FILES_JSON": json.dumps(
                    {"permissions/tool_permissions.json": "{}"}
                )
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "runtime-managed"):
                goose_runtime_main.materialize_goose_config_files()

    def test_materialize_goose_config_files_rejects_secrets_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            goose_runtime_main,
            "XDG_CONFIG_HOME",
            str(Path(temp_dir) / ".config"),
        ), patch.dict(
            goose_runtime_main.os.environ,
            {
                "GOOSE_RUNTIME_CONFIG_FILES_JSON": json.dumps(
                    {"secrets.yaml": {"OPENAI_API_KEY": "secret"}}
                )
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "environment variables"):
                goose_runtime_main.materialize_goose_config_files()

    def test_ready_reports_resolved_goose_binary(self) -> None:
        with patch.object(goose_runtime_main, "ensure_runtime_directories") as ensure_dirs, patch.object(
            goose_runtime_main,
            "current_goose_config_files",
            return_value=["config.yaml", "prompts/review.md"],
        ), patch.object(
            goose_runtime_main.shutil,
            "which",
            return_value="/usr/local/bin/goose",
        ):
            payload = goose_runtime_main.ready()

        ensure_dirs.assert_called_once_with()
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["goose_binary_path"], "/usr/local/bin/goose")
        self.assertEqual(payload["config_files"], ["config.yaml", "prompts/review.md"])

    def test_ready_raises_when_goose_binary_is_missing(self) -> None:
        with patch.object(goose_runtime_main, "ensure_runtime_directories"), patch.object(
            goose_runtime_main.shutil,
            "which",
            return_value=None,
        ):
            with self.assertRaises(HTTPException):
                goose_runtime_main.ready()

    def test_debug_goose_info_returns_command_output(self) -> None:
        with patch.object(goose_runtime_main, "ensure_runtime_directories") as ensure_dirs, patch.object(
            goose_runtime_main,
            "materialize_goose_config_files",
            return_value=["config.yaml"],
        ) as materialize, patch.object(
            goose_runtime_main,
            "current_goose_config_files",
            return_value=["config.yaml"],
        ), patch.object(
            goose_runtime_main.shutil,
            "which",
            return_value="/usr/local/bin/goose",
        ), patch.object(
            goose_runtime_main.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/local/bin/goose", "info", "-v"],
                returncode=0,
                stdout="provider: openai\nmodel: gpt-4\n",
                stderr="",
            ),
        ) as run_command:
            payload = goose_runtime_main.debug_goose_info()

        ensure_dirs.assert_called_once_with()
        materialize.assert_called_once_with()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["returncode"], 0)
        self.assertEqual(payload["config_files"], ["config.yaml"])
        self.assertIn("provider: openai", payload["stdout"])
        run_command.assert_called_once()

    def test_debug_goose_info_reports_failed_command(self) -> None:
        with patch.object(goose_runtime_main, "ensure_runtime_directories"), patch.object(
            goose_runtime_main,
            "materialize_goose_config_files",
            return_value=["config.yaml"],
        ), patch.object(
            goose_runtime_main,
            "current_goose_config_files",
            return_value=["config.yaml"],
        ), patch.object(
            goose_runtime_main.shutil,
            "which",
            return_value="/usr/local/bin/goose",
        ), patch.object(
            goose_runtime_main.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                args=["/usr/local/bin/goose", "info", "-v"],
                returncode=1,
                stdout="",
                stderr="missing provider",
            ),
        ):
            payload = goose_runtime_main.debug_goose_info()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["returncode"], 1)
        self.assertIn("missing provider", payload["stderr"])

    def test_debug_goose_info_raises_for_timeout(self) -> None:
        with patch.object(goose_runtime_main, "ensure_runtime_directories"), patch.object(
            goose_runtime_main,
            "materialize_goose_config_files",
            return_value=[],
        ), patch.object(
            goose_runtime_main.shutil,
            "which",
            return_value="/usr/local/bin/goose",
        ), patch.object(
            goose_runtime_main.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["goose", "info", "-v"], timeout=30),
        ):
            with self.assertRaises(HTTPException) as context:
                goose_runtime_main.debug_goose_info()

        self.assertEqual(context.exception.status_code, 504)

    def test_execute_goose_json_sends_prompt_over_stdin(self) -> None:
        captured: dict[str, object] = {}

        class FakeProcess:
            returncode = 0

            async def communicate(self, input: bytes | None = None):
                captured["input"] = input
                return (
                    b'{"messages": [{"role": "assistant", "content": "done"}], "metadata": {"status": "completed"}}',
                    b"",
                )

        async def fake_create_subprocess_exec(*command, **kwargs):
            captured["command"] = command
            captured["cwd"] = kwargs.get("cwd")
            captured["stdin"] = kwargs.get("stdin")
            return FakeProcess()

        async def run_test() -> dict[str, object]:
            return await goose_runtime_main.execute_goose_json(
                prompt="multi\nline prompt",
                model="gpt-4",
                session_name="thread-1",
                allow_resume=False,
                system_prompt="",
                max_turns=8,
                debug=False,
                no_session=False,
                builtin_extensions=[],
                stdio_extensions=[],
                streamable_http_extensions=[],
                working_directory="/workspace",
            )

        with patch.object(goose_runtime_main.asyncio, "create_subprocess_exec", side_effect=fake_create_subprocess_exec):
            payload = asyncio.run(run_test())

        self.assertEqual(captured["input"], b"multi\nline prompt")
        self.assertEqual(payload["metadata"]["status"], "completed")

    def test_format_team_context_system_prompt_includes_objective_and_caller(self) -> None:
        prompt = goose_runtime_main.format_team_context_system_prompt(
            {
                "objective": "Review the failing workflow.",
                "caller": {"name": "planner", "namespace": "team-a", "threadId": "thread-1"},
                "workingAgreement": ["Return concrete findings."],
            }
        )

        self.assertIn("multi-agent collaboration", prompt)
        self.assertIn("planner", prompt)
        self.assertIn("Review the failing workflow.", prompt)

    def test_invoke_passes_team_context_into_system_prompt(self) -> None:
        captured: dict[str, object] = {}

        async def fake_execute_goose_json(**kwargs):
            captured.update(kwargs)
            return {
                "messages": [{"role": "assistant", "content": "done"}],
                "metadata": {"status": "completed"},
            }

        async def run_test() -> goose_runtime_main.InvokeResponse:
            request = goose_runtime_main.InvokeRequest(
                prompt="Investigate the issue",
                system="Stay concise.",
                team_context={
                    "objective": "Review the failing workflow.",
                    "caller": {"name": "planner", "namespace": "team-a"},
                },
            )
            with patch.object(goose_runtime_main, "execute_goose_json", side_effect=fake_execute_goose_json), patch.object(
                goose_runtime_main,
                "resolve_working_directory",
                return_value="/workspace",
            ):
                return await goose_runtime_main.invoke(request)

        response = asyncio.run(run_test())

        self.assertEqual(response.response, "done")
        self.assertIn("Stay concise.", str(captured["system_prompt"]))
        self.assertIn("Review the failing workflow.", str(captured["system_prompt"]))
        self.assertIn("planner", str(captured["system_prompt"]))


if __name__ == "__main__":
    unittest.main()