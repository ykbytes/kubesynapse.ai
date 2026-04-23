import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
LOCAL_CONFIG_PATH = MODULE_PATH.parent / "config.py"


class OpenCodeRuntimeImportIsolationTests(unittest.TestCase):
    def test_main_prefers_local_config_over_preloaded_service_module(self) -> None:
        previous_config = sys.modules.get("config")
        fake_config = types.ModuleType("config")
        fake_config.__file__ = str(Path(__file__).resolve().parents[2] / "operator" / "config.py")
        fake_config.UNRELATED = True
        sys.modules["config"] = fake_config

        module_name = f"opencode_runtime_import_isolation_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError("Failed to load opencode-runtime main module for tests")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            loaded_config = module.RUNTIME_IMPORTED_MODULES["config"]
            self.assertIsNotNone(loaded_config)
            self.assertEqual(Path(str(getattr(loaded_config, "__file__", ""))).resolve(), LOCAL_CONFIG_PATH.resolve())
            self.assertTrue(hasattr(loaded_config, "A2A_ALLOWED_CALLERS"))
            self.assertFalse(hasattr(loaded_config, "UNRELATED"))
            self.assertIs(sys.modules.get("config"), fake_config)
        finally:
            sys.modules.pop(module_name, None)
            if previous_config is not None:
                sys.modules["config"] = previous_config
            else:
                sys.modules.pop("config", None)