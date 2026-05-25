"""Shared fixtures for api-gateway tests."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pre-import mocks (must happen before main.py is loaded)
# ---------------------------------------------------------------------------

# Mock kubernetes before import
_k8s_config = types.ModuleType("kubernetes.config")
_k8s_config.load_incluster_config = lambda: None
_k8s_config.load_kube_config = lambda: None
sys.modules.setdefault("kubernetes.config", _k8s_config)

_k8s_client = types.ModuleType("kubernetes.client")
_k8s_client.ApiClient = MagicMock
_k8s_client.CoreV1Api = MagicMock
_k8s_client.CustomObjectsApi = MagicMock
_k8s_client.AppsV1Api = MagicMock
_k8s_client.NetworkingV1Api = MagicMock
_k8s_client.RbacAuthorizationV1Api = MagicMock
_k8s_client.V1Namespace = MagicMock
_k8s_client.V1Secret = MagicMock
_k8s_client.V1ConfigMap = MagicMock
_k8s_client.V1Deployment = MagicMock
_k8s_client.V1Service = MagicMock
_k8s_client.V1ServiceAccount = MagicMock
_k8s_client.V1PolicyRule = MagicMock
_k8s_client.V1Role = MagicMock
_k8s_client.V1RoleBinding = MagicMock
_k8s_client.V1ClusterRole = MagicMock
_k8s_client.V1ClusterRoleBinding = MagicMock
_k8s_client.V1NetworkPolicy = MagicMock
_k8s_client.V1ObjectMeta = MagicMock
_k8s_client.V1Container = MagicMock
_k8s_client.V1PodSpec = MagicMock
_k8s_client.V1PodTemplateSpec = MagicMock
_k8s_client.V1ResourceRequirements = MagicMock
_k8s_client.V1EnvVar = MagicMock
_k8s_client.V1Volume = MagicMock
_k8s_client.V1VolumeMount = MagicMock
_k8s_client.V1PersistentVolumeClaim = MagicMock
_k8s_client.V1PersistentVolumeClaimSpec = MagicMock
_k8s_client.V1ResourceQuota = MagicMock
_k8s_client.V1LimitRange = MagicMock
_k8s_client.V1LimitRangeItem = MagicMock
sys.modules.setdefault("kubernetes.client", _k8s_client)

# Mock passlib before auth_store imports it
passlib_module = types.ModuleType("passlib")
passlib_context = types.ModuleType("passlib.context")
passlib_context.CryptContext = lambda *args, **kwargs: types.SimpleNamespace(
    hash=lambda x: x,
    verify=lambda x, y: True,
    verify_and_update=lambda x, y: (True, None),
)
passlib_module.context = passlib_context
sys.modules.setdefault("passlib", passlib_module)
sys.modules.setdefault("passlib.context", passlib_context)

# Mock jose before import
jose_module = types.ModuleType("jose")
jose_module.jwk = types.SimpleNamespace(construct=lambda *_args, **_kwargs: None)
jose_module.jwt = types.SimpleNamespace(
    get_unverified_header=lambda _token: {},
    get_unverified_claims=lambda _token: {},
    decode=lambda *args, **kwargs: {},
    encode=lambda *args, **kwargs: "mock-jwt-token",
)
jose_module.JWTError = Exception
jose_utils_module = types.ModuleType("jose.utils")
jose_utils_module.base64url_decode = lambda value: value
sys.modules.setdefault("jose", jose_module)
sys.modules.setdefault("jose.utils", jose_utils_module)

# Set test environment variables before importing main
os.environ["API_GATEWAY_AUTH_MODE"] = "shared_token"
os.environ["API_GATEWAY_SHARED_TOKEN"] = "test-shared-token"
os.environ.setdefault("DATABASE_SQLITE_PATH", ":memory:")
os.environ.setdefault("OPENCODE_MEMORY_ENABLED", "false")

# ---------------------------------------------------------------------------
# Import main.py via importlib to control module-level side effects
# ---------------------------------------------------------------------------

MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
MODULE_DIR = str(MODULE_PATH.parent)
if MODULE_DIR not in sys.path:
    sys.path.insert(0, MODULE_DIR)

SPEC = importlib.util.spec_from_file_location("api_gateway_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load api-gateway main module for tests")
api_gateway_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api_gateway_main

# Mock heavy initialization before executing module
with (
    patch("auth_store.init_database", lambda: None),
    patch("auth_store.ensure_bootstrap_admin", lambda: None),
):
    SPEC.loader.exec_module(api_gateway_main)

# ---------------------------------------------------------------------------
# FastAPI TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Return a FastAPI TestClient for the api-gateway app."""
    from fastapi.testclient import TestClient

    app = api_gateway_main.app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return authorization headers with the test shared token."""
    return {"Authorization": "Bearer test-shared-token"}


@pytest.fixture
def mock_k8s_agents():
    """Return a list of mock agent resources for K8s API mocking."""
    return [
        {
            "apiVersion": "kubesynapse.ai/v1",
            "kind": "AIAgent",
            "metadata": {"name": "test-agent", "namespace": "default"},
            "spec": {
                "runtime": {"kind": "opencode", "version": "1.0"},
                "model": {"provider": "openai", "model": "gpt-4"},
                "tenant": "default",
                "mcpServers": [],
                "mcpSidecars": [],
            },
        }
    ]
