import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("codex_runtime_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load codex-runtime main module for tests")
codex_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = codex_runtime_main
SPEC.loader.exec_module(codex_runtime_main)


class CodexRuntimeSidecarTests(unittest.TestCase):
    def test_materialize_codex_config_files_writes_into_codex_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir) / ".codex"
            with patch.dict(
                os.environ,
                {
                    codex_runtime_main.CODEX_RUNTIME_CONFIG_FILES_ENV: json.dumps(
                        {
                            "config.toml": 'model = "gpt-4"',
                            "prompts/system.md": "Be precise.",
                        }
                    )
                },
                clear=False,
            ), patch.object(codex_runtime_main, "CODEX_HOME", str(codex_home)):
                written = codex_runtime_main.materialize_codex_config_files()

            self.assertEqual(written, ["config.toml", "prompts/system.md"])
            self.assertEqual((codex_home / "config.toml").read_text(encoding="utf-8"), 'model = "gpt-4"\n')
            self.assertEqual((codex_home / "prompts" / "system.md").read_text(encoding="utf-8"), "Be precise.\n")

    def test_materialize_codex_auth_file_writes_auth_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir) / ".codex"
            auth_payload = {
                "auth_mode": "apikey",
                "OPENAI_API_KEY": "sk-test-key",
            }
            with patch.dict(
                os.environ,
                {codex_runtime_main.CODEX_AUTH_JSON_ENV: json.dumps(auth_payload)},
                clear=False,
            ), patch.object(codex_runtime_main, "CODEX_HOME", str(codex_home)):
                written_path = codex_runtime_main.materialize_codex_auth_file()

            self.assertEqual(written_path, "auth.json")
            self.assertEqual(
                json.loads((codex_home / "auth.json").read_text(encoding="utf-8")),
                auth_payload,
            )

    def test_lifespan_materializes_codex_home_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_home = root / ".codex"
            workspace = root / "workspace"
            config_home = root / ".config"
            data_home = root / ".local" / "share"
            skills_root = root / "skills"
            auth_payload = {
                "auth_mode": "apikey",
                "OPENAI_API_KEY": "sk-test-key",
            }

            async def _run_lifespan() -> None:
                async with codex_runtime_main.lifespan(codex_runtime_main.app):
                    self.assertTrue(codex_runtime_main._runtime_ready)

            with patch.dict(
                os.environ,
                {
                    codex_runtime_main.CODEX_RUNTIME_CONFIG_FILES_ENV: json.dumps(
                        {"config.toml": 'model = "gpt-4"'}
                    ),
                    codex_runtime_main.CODEX_AUTH_JSON_ENV: json.dumps(auth_payload),
                },
                clear=False,
            ), patch.object(codex_runtime_main, "CODEX_WORKDIR", str(workspace)), patch.object(
                codex_runtime_main,
                "HOME_DIR",
                str(root),
            ), patch.object(codex_runtime_main, "CODEX_HOME", str(codex_home)), patch.object(
                codex_runtime_main,
                "XDG_CONFIG_HOME",
                str(config_home),
            ), patch.object(codex_runtime_main, "XDG_DATA_HOME", str(data_home)), patch.object(
                codex_runtime_main,
                "SKILLS_ROOT",
                str(skills_root),
            ), patch.object(codex_runtime_main, "validate_runtime_startup", return_value=None):
                asyncio.run(_run_lifespan())

            self.assertFalse(codex_runtime_main._runtime_ready)
            self.assertEqual((codex_home / "config.toml").read_text(encoding="utf-8"), 'model = "gpt-4"\n')
            self.assertEqual(
                json.loads((codex_home / "auth.json").read_text(encoding="utf-8")),
                auth_payload,
            )
            self.assertEqual(codex_runtime_main.SKILL_RUNTIME_CONFIG["codexConfigFiles"], ["config.toml"])
            self.assertEqual(codex_runtime_main.SKILL_RUNTIME_CONFIG["codexAuthFile"], "auth.json")

    def test_load_codex_sidecars_normalizes_and_deduplicates_entries(self) -> None:
        with patch.dict(
            os.environ,
            {
                codex_runtime_main.CODEX_MCP_SIDECARS_ENV: json.dumps(
                    [
                        {"name": "browser", "port": 8081},
                        {"name": "browser", "port": 8081},
                        {"name": "git", "port": "8090"},
                    ]
                )
            },
            clear=False,
        ):
            parsed = codex_runtime_main.load_codex_sidecars()

        self.assertEqual(
            parsed,
            [
                {"name": "browser", "port": 8081},
                {"name": "git", "port": 8090},
            ],
        )

    @unittest.skipIf(codex_runtime_main.tomli_w is None, "tomli-w is required for Codex MCP config generation")
    def test_materialize_codex_mcp_config_merges_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_root = Path(tmpdir) / ".codex"
            config_root.mkdir(parents=True, exist_ok=True)
            config_path = config_root / "config.toml"
            config_path.write_text('model = "gpt-4"\n', encoding="utf-8")

            with patch.object(codex_runtime_main, "CODEX_HOME", str(config_root)):
                written_path = codex_runtime_main.materialize_codex_mcp_config(
                    [{"name": "browser", "port": 8081}]
                )

            self.assertEqual(written_path, "config.toml")
            rendered = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(rendered["model"], "gpt-4")
            self.assertEqual(rendered["mcp_servers"]["browser"]["url"], "http://127.0.0.1:8081/mcp")


if __name__ == "__main__":
    unittest.main()