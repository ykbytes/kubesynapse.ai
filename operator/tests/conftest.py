"""Shared fixtures for operator tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

# ---------------------------------------------------------------------------
# Pre-import mocks (must happen before operator modules are loaded)
# ---------------------------------------------------------------------------


def _passthrough_decorator(*args, **kwargs):
    def decorator(func):
        return func
    return decorator


class _PermanentError(Exception):
    pass


class _TemporaryError(Exception):
    def __init__(self, *args, delay=None, **kwargs):
        super().__init__(*args)
        self.delay = delay


# Mock croniter
croniter_module = types.ModuleType("croniter")


class _CroniterBadCronError(Exception):
    pass


def _croniter(*args, **kwargs):
    raise AssertionError("croniter should not be invoked in manifest tests")


croniter_module.CroniterBadCronError = _CroniterBadCronError
croniter_module.croniter = _croniter
sys.modules.setdefault("croniter", croniter_module)

# Mock kopf
kopf_module = types.ModuleType("kopf")
kopf_module.on = types.SimpleNamespace(
    startup=_passthrough_decorator,
    cleanup=_passthrough_decorator,
    create=_passthrough_decorator,
    update=_passthrough_decorator,
    delete=_passthrough_decorator,
    resume=_passthrough_decorator,
    field=_passthrough_decorator,
)
kopf_module.timer = _passthrough_decorator
kopf_module.adopt = lambda *args, **kwargs: None
kopf_module.PermanentError = _PermanentError
kopf_module.TemporaryError = _TemporaryError
kopf_module.OperatorSettings = type("OperatorSettings", (), {})
sys.modules.setdefault("kopf", kopf_module)

# Mock kubernetes
kubernetes_module = types.ModuleType("kubernetes")
client_module = types.ModuleType("kubernetes.client")
config_module = types.ModuleType("kubernetes.config")
rest_module = types.ModuleType("kubernetes.client.rest")
rest_module.ApiException = type("ApiException", (Exception,), {"status": None})
config_module.ConfigException = type("ConfigException", (Exception,), {})

# Add common K8s client mocks
client_module.ApiClient = MagicMock
client_module.CoreV1Api = MagicMock
client_module.CustomObjectsApi = MagicMock
client_module.AppsV1Api = MagicMock
client_module.NetworkingV1Api = MagicMock
client_module.RbacAuthorizationV1Api = MagicMock
client_module.V1Namespace = MagicMock
client_module.V1Secret = MagicMock
client_module.V1ConfigMap = MagicMock
client_module.V1Deployment = MagicMock
client_module.V1Service = MagicMock
client_module.V1ServiceAccount = MagicMock
client_module.V1PolicyRule = MagicMock
client_module.V1Role = MagicMock
client_module.V1RoleBinding = MagicMock
client_module.V1ClusterRole = MagicMock
client_module.V1ClusterRoleBinding = MagicMock
client_module.V1NetworkPolicy = MagicMock
client_module.V1ObjectMeta = MagicMock
client_module.V1Container = MagicMock
client_module.V1PodSpec = MagicMock
client_module.V1PodTemplateSpec = MagicMock
client_module.V1ResourceRequirements = MagicMock
client_module.V1EnvVar = MagicMock
client_module.V1Volume = MagicMock
client_module.V1VolumeMount = MagicMock
client_module.V1PersistentVolumeClaim = MagicMock
client_module.V1PersistentVolumeClaimSpec = MagicMock
client_module.V1RoleRef = MagicMock
client_module.V1Subject = MagicMock
client_module.V1LimitRange = MagicMock
client_module.V1ResourceQuota = MagicMock
client_module.V1ResourceQuotaSpec = MagicMock
client_module.V1LimitRangeSpec = MagicMock
client_module.V1LimitRangeItem = MagicMock
client_module.V1DeploymentSpec = MagicMock
client_module.V1StatefulSet = MagicMock
client_module.V1StatefulSetSpec = MagicMock

kubernetes_module.client = client_module
kubernetes_module.config = config_module
client_module.rest = rest_module
sys.modules.setdefault("kubernetes", kubernetes_module)
sys.modules.setdefault("kubernetes.client", client_module)
sys.modules.setdefault("kubernetes.config", config_module)
sys.modules.setdefault("kubernetes.client.rest", rest_module)

# Add operator to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---------------------------------------------------------------------------
# Import operator modules after mocking
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api_exception():
    """Return a factory for K8s ApiException instances."""
    def _factory(status: int, reason: str = "", body: str = ""):
        exc = rest_module.ApiException(f"status={status}")
        exc.status = status
        exc.reason = reason
        exc.body = body
        return exc
    return _factory


@pytest.fixture
def mock_logger():
    """Return a mock logger for controller tests."""
    return Mock()


@pytest.fixture
def sample_agent_spec():
    """Return a minimal valid AIAgent spec."""
    return {
        "runtime": {"kind": "opencode", "version": "1.0"},
        "model": {"provider": "openai", "model": "gpt-4"},
        "tenant": "default",
        "mcpServers": [],
        "mcpSidecars": [],
    }


@pytest.fixture
def sample_tenant_spec():
    """Return a minimal valid AgentTenant spec."""
    return {
        "namespacePrefix": "tenant-",
        "quota": {
            "maxAgents": 10,
            "maxWorkflows": 50,
        },
    }
