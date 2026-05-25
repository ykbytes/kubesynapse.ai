from __future__ import annotations

import importlib.util
import sys
import sysconfig
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib_metadata
from importlib_metadata.compat import py39 as importlib_metadata_py39

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.pop("runtime_events", None)

_stdlib_operator_path = Path(sysconfig.get_paths()["stdlib"]) / "operator.py"
_operator_spec = importlib.util.spec_from_file_location("python_stdlib_operator", _stdlib_operator_path)
if _operator_spec is None or _operator_spec.loader is None:
    raise RuntimeError("Failed to load stdlib operator module for runtime tests")
_stdlib_operator = importlib.util.module_from_spec(_operator_spec)
_operator_spec.loader.exec_module(_stdlib_operator)
sys.modules["operator"] = _stdlib_operator
importlib_metadata.operator = _stdlib_operator
importlib_metadata_py39.operator = _stdlib_operator

MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("vibe_runtime_main_llm", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load vibe-runtime main module for llm event tests")
vibe_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vibe_runtime_main
SPEC.loader.exec_module(vibe_runtime_main)


class VibeLlmEventTests(unittest.TestCase):
    def test_emit_llm_call_for_response_uses_metadata_tokens(self) -> None:
        response = vibe_runtime_main.InvokeResponse(
            thread_id="thread-1",
            response="done",
            model="mistral-large",
            metadata={"tokens": {"input": 5, "output": 3, "total": 8}, "cost": 0.0},
        )

        with patch.object(vibe_runtime_main, "emit_llm_call") as mock_emit:
            vibe_runtime_main._emit_llm_call_for_response(
                execution_id="exec-1",
                thread_id="thread-1",
                session_id="session-1",
                response=response,
                fallback_duration_ms=210,
            )

        mock_emit.assert_called_once_with(
            execution_id="exec-1",
            thread_id="thread-1",
            session_id="session-1",
            model="mistral-large",
            prompt_tokens=5,
            completion_tokens=3,
            total_tokens=8,
            cost_usd=0.0,
            duration_ms=210,
        )