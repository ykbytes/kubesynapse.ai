import logging
import os
import re
import time
import hashlib
from datetime import datetime, timezone
from typing import Any

from croniter import CroniterBadCronError, croniter  # type: ignore[import-untyped]
from utils import build_workflow_run_id, now_iso, validate_workflow_graph, workflow_journal_path
import kopf

import kubernetes.client  # type: ignore[import-untyped]
import kubernetes.config  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

logger = logging.getLogger("operator")


def get_string_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def get_int_env(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(int(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid integer value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(float(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid float value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_csv_env(name: str) -> list[str]:
    raw_value = os.getenv(name, "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


LITELLM_SVC = os.getenv("LITELLM_SVC_NAME", "ai-agent-sandbox-litellm")
SECRET_NAME = os.getenv("LLM_SECRET_NAME", "ai-agent-sandbox-llm-api-keys")
RUNTIME_IMAGE = os.getenv("AGENT_RUNTIME_IMAGE", "ghcr.io/your-org/ai-agent-runtime:latest")
RUNTIME_IMAGE_PULL_POLICY = get_string_env("AGENT_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
GOOSE_RUNTIME_IMAGE = os.getenv("GOOSE_RUNTIME_IMAGE", "ghcr.io/your-org/ai-goose-runtime:latest")
GOOSE_RUNTIME_IMAGE_PULL_POLICY = get_string_env("GOOSE_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
GOOSE_DEFAULT_PROVIDER = get_string_env("GOOSE_DEFAULT_PROVIDER", "litellm")
RUNTIME_SERVICE_ACCOUNT = os.getenv("RUNTIME_SERVICE_ACCOUNT", "ai-agent-runtime")
RUNTIME_CLUSTER_ROLE = os.getenv("RUNTIME_CLUSTER_ROLE", "ai-agent-runtime-role")
QDRANT_SVC = os.getenv("QDRANT_SVC_NAME", "ai-agent-sandbox-qdrant")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "agent-knowledge")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
DEFAULT_STORAGE_SIZE = os.getenv("AGENT_STORAGE_SIZE", "1Gi")
CLUSTER_SECRET_STORE = os.getenv("CLUSTER_SECRET_STORE", "ai-agent-sandbox-vault-backend")
SECRET_PROVISIONING_MODE = os.getenv("SECRET_PROVISIONING_MODE", "native").strip().lower() or "native"
DEFAULT_LITELLM_MASTER_KEY = os.getenv("DEFAULT_LITELLM_MASTER_KEY", "").strip()
API_PORT = 8080
PROTECTED_NAMESPACES = {"default", "kube-system", "kube-public", "kube-node-lease"}
OPERATOR_NAMESPACE = os.getenv("OPERATOR_NAMESPACE", "default").strip() or "default"
OPERATOR_PEERING_NAME = get_string_env("OPERATOR_PEERING_NAME", "ai-agent-sandbox-operator")
WORKER_IMAGE = os.getenv("WORKER_IMAGE", "ghcr.io/your-org/ai-operator:latest")
WORKER_SERVICE_ACCOUNT_NAME = os.getenv("WORKER_SERVICE_ACCOUNT_NAME", "default").strip() or "default"
WORKER_ARTIFACT_SIZE = os.getenv("WORKER_ARTIFACT_SIZE", "2Gi")
WORKER_ARTIFACT_STORAGE_CLASS = os.getenv("WORKER_ARTIFACT_STORAGE_CLASS", "").strip()
WORKER_TTL_SECONDS_AFTER_FINISHED = get_int_env("WORKER_TTL_SECONDS_AFTER_FINISHED", 3600, minimum=0)
WORKER_ACTIVE_DEADLINE_SECONDS = get_int_env("WORKER_ACTIVE_DEADLINE_SECONDS", 1800, minimum=60)
WORKER_IMAGE_PULL_POLICY = os.getenv("WORKER_IMAGE_PULL_POLICY", "IfNotPresent").strip() or "IfNotPresent"
WORKER_CPU_REQUEST = os.getenv("WORKER_CPU_REQUEST", "100m").strip() or "100m"
WORKER_MEMORY_REQUEST = os.getenv("WORKER_MEMORY_REQUEST", "128Mi").strip() or "128Mi"
WORKER_CPU_LIMIT = os.getenv("WORKER_CPU_LIMIT", "500m").strip() or "500m"
WORKER_MEMORY_LIMIT = os.getenv("WORKER_MEMORY_LIMIT", "512Mi").strip() or "512Mi"
AGENT_RUNTIME_TIMEOUT_SECONDS = str(get_float_env("AGENT_RUNTIME_TIMEOUT_SECONDS", 360.0, minimum=1.0))
EVAL_SCHEDULE_POLL_SECONDS = get_int_env("EVAL_SCHEDULE_POLL_SECONDS", 60, minimum=15)
SCHEDULED_EVAL_QUEUE_STALE_SECONDS = get_int_env("SCHEDULED_EVAL_QUEUE_STALE_SECONDS", 600, minimum=60)
WORKFLOW_POLL_SECONDS = get_int_env("WORKFLOW_POLL_SECONDS", 30, minimum=15)
WORKFLOW_QUEUE_STALE_SECONDS = get_int_env("WORKFLOW_QUEUE_STALE_SECONDS", 300, minimum=60)
WORKFLOW_RUNNING_STALE_SECONDS = get_int_env("WORKFLOW_RUNNING_STALE_SECONDS", 900, minimum=60)
ARTIFACT_MOUNT_PATH = "/artifacts"
AGENT_HITL_MODE = os.getenv("AGENT_HITL_MODE", "enforce").strip().lower()
HITL_NOTIFICATION_WEBHOOK_URL = os.getenv("HITL_NOTIFICATION_WEBHOOK_URL", "").strip()
AGENT_CPU_REQUEST = os.getenv("AGENT_CPU_REQUEST", "100m").strip() or "100m"
AGENT_MEMORY_REQUEST = os.getenv("AGENT_MEMORY_REQUEST", "256Mi").strip() or "256Mi"
AGENT_CPU_LIMIT = os.getenv("AGENT_CPU_LIMIT", "1").strip() or "1"
AGENT_MEMORY_LIMIT = os.getenv("AGENT_MEMORY_LIMIT", "1Gi").strip() or "1Gi"
IMAGE_PULL_SECRETS = get_csv_env("IMAGE_PULL_SECRETS")
SUPPORTED_RUNTIME_KINDS = {"langgraph", "goose"}
# MCP Hub: namespace where shared enterprise MCP servers run and the auth
# secret that agents must present as a bearer token on every MCP call.
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip()
MCP_AUTH_SECRET_NAME = os.getenv("MCP_AUTH_SECRET_NAME", "ai-agent-sandbox-mcp-auth").strip()
OPEN_SANDBOX_RUNTIME_ENV: dict[str, str] = {
    "OPEN_SANDBOX_DOMAIN": os.getenv("OPEN_SANDBOX_DOMAIN", "").strip(),
    "OPEN_SANDBOX_PROTOCOL": os.getenv("OPEN_SANDBOX_PROTOCOL", "http").strip() or "http",
    "OPEN_SANDBOX_USE_SERVER_PROXY": os.getenv("OPEN_SANDBOX_USE_SERVER_PROXY", "false").strip() or "false",
    "OPEN_SANDBOX_REQUEST_TIMEOUT_SECONDS": os.getenv("OPEN_SANDBOX_REQUEST_TIMEOUT_SECONDS", "300").strip() or "300",
    "OPEN_SANDBOX_CONNECT_TIMEOUT_SECONDS": os.getenv("OPEN_SANDBOX_CONNECT_TIMEOUT_SECONDS", "30").strip() or "30",
    "OPEN_SANDBOX_DEFAULT_TTL_SECONDS": os.getenv("OPEN_SANDBOX_DEFAULT_TTL_SECONDS", "600").strip() or "600",
    "OPEN_SANDBOX_DEFAULT_IMAGE": os.getenv("OPEN_SANDBOX_DEFAULT_IMAGE", "python:3.11").strip() or "python:3.11",
    "OPEN_SANDBOX_CODE_IMAGE": os.getenv(
        "OPEN_SANDBOX_CODE_IMAGE", "opensandbox/code-interpreter:latest"
    ).strip()
    or "opensandbox/code-interpreter:latest",
    "OPEN_SANDBOX_BROWSER_IMAGE": os.getenv(
        "OPEN_SANDBOX_BROWSER_IMAGE", "opensandbox/chrome:latest"
    ).strip()
    or "opensandbox/chrome:latest",
    "OPEN_SANDBOX_EDITOR_IMAGE": os.getenv(
        "OPEN_SANDBOX_EDITOR_IMAGE", "opensandbox/vscode:latest"
    ).strip()
    or "opensandbox/vscode:latest",
    "OPEN_SANDBOX_PYTHON_VERSION": os.getenv("OPEN_SANDBOX_PYTHON_VERSION", "3.11").strip() or "3.11",
    "OPEN_SANDBOX_JAVA_VERSION": os.getenv("OPEN_SANDBOX_JAVA_VERSION", "17").strip() or "17",
    "OPEN_SANDBOX_NODE_VERSION": os.getenv("OPEN_SANDBOX_NODE_VERSION", "20").strip() or "20",
    "OPEN_SANDBOX_GO_VERSION": os.getenv("OPEN_SANDBOX_GO_VERSION", "1.24").strip() or "1.24",
    "OPEN_SANDBOX_SECURE_RUNTIME_TYPE": os.getenv("OPEN_SANDBOX_SECURE_RUNTIME_TYPE", "").strip(),
}
OPEN_SANDBOX_API_KEY_SECRET_NAME = os.getenv("OPEN_SANDBOX_API_KEY_SECRET_NAME", "").strip()
OPEN_SANDBOX_API_KEY_SECRET_KEY = os.getenv("OPEN_SANDBOX_API_KEY_SECRET_KEY", "api-key").strip() or "api-key"


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
    """Ensure K8s client is authenticated when the operator starts."""
    settings.persistence.finalizer = "sandbox.enterprise.ai/finalizer"
    settings.peering.name = OPERATOR_PEERING_NAME
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config.")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kubeconfig file.")


def sandbox_name(agent_name: str) -> str:
    return f"{agent_name}-sandbox"


def slugify_name(value: str, max_length: int = 63) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "resource"
    trimmed = slug[:max_length].rstrip("-")
    return trimmed or "resource"


def hashed_resource_name(prefix: str, namespace: str, name: str, suffix: str = "") -> str:
    digest = hashlib.sha1(f"{prefix}:{namespace}:{name}:{suffix}".encode("utf-8")).hexdigest()[:10]
    base = slugify_name(f"{prefix}-{namespace}-{name}", max_length=max(1, 63 - len(digest) - 1))
    return f"{base}-{digest}"


def worker_artifact_pvc_name(kind: str, namespace: str, name: str) -> str:
    return hashed_resource_name(f"{kind}-artifacts", namespace, name)


def artifact_file_path(kind: str, namespace: str, name: str, generation: int) -> str:
    safe_namespace = slugify_name(namespace, max_length=40)
    safe_name = slugify_name(name, max_length=40)
    return f"{kind}s/{safe_namespace}/{safe_name}/generation-{generation}.json"


def build_artifact_ref(
    pvc_name: str,
    path: str,
    generation: int,
    *,
    journal_path: str | None = None,
) -> dict[str, Any]:
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        "updatedAt": now_iso(),
        **({"journalPath": journal_path} if journal_path else {}),
    }


def parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_eval_schedule(schedule: str) -> None:
    try:
        croniter(schedule, datetime.now(timezone.utc))
    except (CroniterBadCronError, ValueError) as exc:
        raise kopf.PermanentError(f"Invalid AgentEval schedule '{schedule}': {exc}") from exc


def scheduled_eval_due(schedule: str, last_run_value: str | None) -> bool:
    last_run = parse_iso_datetime(last_run_value)
    if last_run is None:
        return False

    next_run = croniter(schedule, last_run).get_next(datetime)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    else:
        next_run = next_run.astimezone(timezone.utc)
    return datetime.now(timezone.utc) >= next_run


def validate_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    message_bus = str(spec.get("messageBus") or "in-memory").strip() or "in-memory"
    if message_bus != "in-memory":
        raise kopf.PermanentError(
            "AgentWorkflow.spec.messageBus is reserved for future use. Only 'in-memory' is supported today."
        )

    try:
        return validate_workflow_graph(spec.get("steps") or [])
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc


def build_journal_ref(pvc_name: str, path: str, generation: int) -> dict[str, Any]:
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        "updatedAt": now_iso(),
    }


def workflow_should_requeue(status: dict[str, Any], job_state: str) -> str | None:
    phase = str(status.get("phase", "") or "")
    if phase not in {"queued", "running"}:
        return None

    summary = status.get("summary", {}) or {}
    now = datetime.now(timezone.utc)

    if phase == "queued":
        queued_at = parse_iso_datetime(str(summary.get("queuedAt") or ""))
        if queued_at is None:
            return None
        queue_age_seconds = (now - queued_at).total_seconds()
        if job_state in {"active", "pending"} and queue_age_seconds < WORKFLOW_QUEUE_STALE_SECONDS:
            return None
        if queue_age_seconds >= WORKFLOW_QUEUE_STALE_SECONDS:
            return f"queued workflow exceeded {WORKFLOW_QUEUE_STALE_SECONDS}s with worker job state '{job_state}'"
        if job_state in {"missing", "failed"}:
            return f"queued workflow lost worker job with state '{job_state}'"
        return None

    updated_at = parse_iso_datetime(str(summary.get("updatedAt") or summary.get("startedAt") or ""))
    if updated_at is None:
        return None
    running_age_seconds = (now - updated_at).total_seconds()
    if job_state in {"active", "pending"} and running_age_seconds < WORKFLOW_RUNNING_STALE_SECONDS:
        return None
    if job_state in {"missing", "failed"}:
        return f"running workflow lost worker job with state '{job_state}'"
    if running_age_seconds >= WORKFLOW_RUNNING_STALE_SECONDS:
        return f"running workflow exceeded {WORKFLOW_RUNNING_STALE_SECONDS}s without progress"
    return None


def resolve_agent_policy(namespace: str, policy_ref: str | None) -> tuple[str | None, dict[str, Any]]:
    custom_api = kubernetes.client.CustomObjectsApi()
    if policy_ref:
        try:
            policy = custom_api.get_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentpolicies",
                name=policy_ref,
            )
            return policy_ref, policy.get("spec", {})
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' was not found") from exc
            raise

    policies = custom_api.list_namespaced_custom_object(
        group="sandbox.enterprise.ai",
        version="v1alpha1",
        namespace=namespace,
        plural="agentpolicies",
    ).get("items", [])
    policies.sort(key=lambda item: item.get("metadata", {}).get("name", ""))
    if not policies:
        return None, {}
    policy = policies[0]
    return policy.get("metadata", {}).get("name"), policy.get("spec", {})


def resolve_tenant_for_namespace(namespace: str) -> dict[str, Any] | None:
    custom_api = kubernetes.client.CustomObjectsApi()
    tenants = custom_api.list_cluster_custom_object(
        group="sandbox.enterprise.ai",
        version="v1alpha1",
        plural="agenttenants",
    ).get("items", [])
    for tenant in tenants:
        tenant_spec = tenant.get("spec", {})
        if tenant_spec.get("namespace") == namespace:
            return tenant_spec
    return None


def validate_agent_model(model: str, policy_spec: dict[str, Any], tenant_spec: dict[str, Any] | None) -> None:
    policy_models = set(policy_spec.get("allowedModels", []))
    if policy_models and model not in policy_models:
        raise kopf.PermanentError(
            f"Model '{model}' is not allowed by AgentPolicy. Allowed models: {sorted(policy_models)}"
        )

    tenant_models = set((tenant_spec or {}).get("allowedModels", []))
    if tenant_models and model not in tenant_models:
        raise kopf.PermanentError(
            f"Model '{model}' is not allowed for tenant namespace. Allowed models: {sorted(tenant_models)}"
        )


def resolve_runtime_kind(spec: dict[str, Any]) -> str:
    runtime_spec = spec.get("runtime") or {}
    runtime_kind = "langgraph"
    if isinstance(runtime_spec, dict):
        runtime_kind = str(runtime_spec.get("kind") or "langgraph").strip().lower() or "langgraph"
    if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
        raise kopf.PermanentError(
            f"Unsupported AIAgent.spec.runtime.kind '{runtime_kind}'. Supported values: {sorted(SUPPORTED_RUNTIME_KINDS)}"
        )
    return runtime_kind


def validate_runtime_configuration(runtime_kind: str, spec: dict[str, Any]) -> None:
    if runtime_kind != "goose":
        return
    if spec.get("mcpServers"):
        raise kopf.PermanentError(
            "Goose runtime integration does not yet support spec.mcpServers. Use the LangGraph runtime for MCP routing today."
        )
    if spec.get("mcpSidecars"):
        raise kopf.PermanentError(
            "Goose runtime integration does not yet support spec.mcpSidecars. Use the LangGraph runtime for sidecar-based MCP tools today."
        )


def ensure_runtime_access(namespace: str) -> None:
    core_api = kubernetes.client.CoreV1Api()
    rbac_api = kubernetes.client.RbacAuthorizationV1Api()

    service_account = kubernetes.client.V1ServiceAccount(
        metadata=kubernetes.client.V1ObjectMeta(name=RUNTIME_SERVICE_ACCOUNT, namespace=namespace),
        image_pull_secrets=[
            kubernetes.client.V1LocalObjectReference(name=secret_name) for secret_name in IMAGE_PULL_SECRETS
        ]
        or None,
    )
    try:
        core_api.create_namespaced_service_account(namespace=namespace, body=service_account)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_service_account(
                name=RUNTIME_SERVICE_ACCOUNT,
                namespace=namespace,
                body=service_account,
            )
        else:
            raise

    binding = kubernetes.client.V1RoleBinding(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{RUNTIME_SERVICE_ACCOUNT}-binding",
            namespace=namespace,
        ),
        role_ref=kubernetes.client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="ClusterRole",
            name=RUNTIME_CLUSTER_ROLE,
        ),
        subjects=[
            kubernetes.client.V1Subject(
                kind="ServiceAccount",
                name=RUNTIME_SERVICE_ACCOUNT,
                namespace=namespace,
            )
        ],
    )
    try:
        rbac_api.create_namespaced_role_binding(namespace=namespace, body=binding)
    except ApiException as exc:
        if exc.status == 409:
            rbac_api.patch_namespaced_role_binding(
                name=f"{RUNTIME_SERVICE_ACCOUNT}-binding",
                namespace=namespace,
                body=binding,
            )
        else:
            raise


def build_pvc_spec(storage_size: str, storage_class_name: str | None = None) -> dict[str, Any]:
    pvc_spec: dict[str, Any] = {
        "accessModes": ["ReadWriteOnce"],
        "resources": {"requests": {"storage": storage_size}},
    }
    if storage_class_name:
        pvc_spec["storageClassName"] = storage_class_name
    return pvc_spec


def create_worker_artifact_pvc_manifest(kind: str, resource_namespace: str, resource_name: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": worker_artifact_pvc_name(kind, resource_namespace, resource_name),
            "namespace": OPERATOR_NAMESPACE,
            "labels": {
                "app": "operator-worker-artifacts",
                "sandbox.enterprise.ai/resource-kind": kind,
                "sandbox.enterprise.ai/resource-name": resource_name,
                "sandbox.enterprise.ai/resource-namespace": resource_namespace,
            },
        },
        "spec": build_pvc_spec(WORKER_ARTIFACT_SIZE, WORKER_ARTIFACT_STORAGE_CLASS or None),
    }


def create_mcp_auth_secret_manifest(namespace: str) -> dict[str, Any]:
    core_api = kubernetes.client.CoreV1Api()
    try:
        source_secret = core_api.read_namespaced_secret(
            name=MCP_AUTH_SECRET_NAME,
            namespace=MCP_HUB_NAMESPACE,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise kopf.TemporaryError(
                f"MCP auth secret '{MCP_AUTH_SECRET_NAME}' was not found in namespace '{MCP_HUB_NAMESPACE}'.",
                delay=15,
            ) from exc
        raise

    bearer_token = (source_secret.data or {}).get("bearer-token")
    if not bearer_token:
        raise kopf.TemporaryError(
            f"MCP auth secret '{MCP_AUTH_SECRET_NAME}' is missing the bearer-token key.",
            delay=15,
        )

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": MCP_AUTH_SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "sandbox.enterprise.ai/managed-by": "operator",
                "sandbox.enterprise.ai/secret-purpose": "mcp-auth",
            },
        },
        "type": source_secret.type or "Opaque",
        "data": {"bearer-token": bearer_token},
    }


def create_agent_service_manifest(name: str, namespace: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": sandbox_name(name),
            "namespace": namespace,
            "labels": {"app": "ai-agent", "agent-name": name},
        },
        "spec": {
            "selector": {"app": "ai-agent", "agent-name": name},
            "ports": [{"name": "http", "port": API_PORT, "targetPort": "http"}],
        },
    }


def create_agent_statefulset_manifest(
    name: str,
    namespace: str,
    spec: dict[str, Any],
    policy_name: str | None,
    policy_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_kind = resolve_runtime_kind(spec)
    validate_runtime_configuration(runtime_kind, spec)
    model = spec.get("model", "gpt-4")
    mcp_servers = spec.get("mcpServers") or []
    mcp_sidecars = spec.get("mcpSidecars") or []
    enable_gvisor = spec.get("enableGVisor", False)
    system_prompt = spec.get("systemPrompt", "")

    pod_security_context = {
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container_security_context = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }

    env = [
        {"name": "AGENT_MODEL", "value": model},
        {"name": "AGENT_NAME", "value": name},
        {"name": "AGENT_NAMESPACE", "value": namespace},
        {"name": "AGENT_SYSTEM_PROMPT", "value": system_prompt},
    ]

    volume_mounts = [
        {"name": "tmp-volume", "mountPath": "/tmp"},
        {"name": "state-volume", "mountPath": "/app/state"},
    ]
    volumes: list[dict[str, Any]] = [{"name": "tmp-volume", "emptyDir": {}}]

    agent_image = RUNTIME_IMAGE
    agent_image_pull_policy = RUNTIME_IMAGE_PULL_POLICY

    if runtime_kind == "goose":
        agent_image = GOOSE_RUNTIME_IMAGE
        agent_image_pull_policy = GOOSE_RUNTIME_IMAGE_PULL_POLICY
        volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
        volumes.append({"name": "workspace-volume", "emptyDir": {}})
        env.extend(
            [
                {"name": "GOOSE_PROVIDER", "value": GOOSE_DEFAULT_PROVIDER},
                {"name": "GOOSE_MODEL", "value": model},
                {"name": "GOOSE_SYSTEM_PROMPT", "value": system_prompt},
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}:4000"},
                {"name": "LITELLM_BASE_PATH", "value": "v1/chat/completions"},
                {
                    "name": "LITELLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": "LITELLM_MASTER_KEY",
                            "optional": True,
                        }
                    },
                },
            ]
        )
    else:
        env.extend(
            [
                {"name": "LITELLM_API_BASE", "value": f"http://{LITELLM_SVC}:4000"},
                {"name": "MCP_SERVERS", "value": ",".join(mcp_servers)},
                {
                    "name": "MCP_SIDECARS",
                    "value": ",".join(f"http://localhost:{item.get('port', 8080)}" for item in mcp_sidecars),
                },
                {"name": "QDRANT_URL", "value": f"http://{QDRANT_SVC}:6333"},
                {"name": "QDRANT_COLLECTION", "value": QDRANT_COLLECTION},
                {
                    "name": "LITELLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": "LITELLM_MASTER_KEY",
                            "optional": True,
                        }
                    },
                },
            ]
        )
        if policy_name:
            env.append({"name": "AGENT_POLICY_NAME", "value": policy_name})
        if OTEL_ENDPOINT:
            env.append({"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": OTEL_ENDPOINT})
        if AGENT_HITL_MODE:
            env.append({"name": "HITL_MODE", "value": AGENT_HITL_MODE})
        if HITL_NOTIFICATION_WEBHOOK_URL:
            env.append({"name": "HITL_NOTIFICATION_WEBHOOK_URL", "value": HITL_NOTIFICATION_WEBHOOK_URL})
        env.append({"name": "MCP_HUB_NAMESPACE", "value": MCP_HUB_NAMESPACE})
        allowed_mcp_servers = (policy_spec or {}).get("allowedMcpServers") or []
        env.append({"name": "ALLOWED_MCP_SERVERS", "value": ",".join(allowed_mcp_servers)})
        env.append({
            "name": "MCP_BEARER_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": MCP_AUTH_SECRET_NAME,
                    "key": "bearer-token",
                    "optional": True,
                }
            },
        })
        for env_name, env_value in OPEN_SANDBOX_RUNTIME_ENV.items():
            if env_value:
                env.append({"name": env_name, "value": env_value})
        if OPEN_SANDBOX_API_KEY_SECRET_NAME:
            env.append({
                "name": "OPEN_SANDBOX_API_KEY",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": OPEN_SANDBOX_API_KEY_SECRET_NAME,
                        "key": OPEN_SANDBOX_API_KEY_SECRET_KEY,
                        "optional": True,
                    }
                },
            })

    agent_container = {
        "name": "agent-runtime",
        "image": agent_image,
        "imagePullPolicy": agent_image_pull_policy,
        "securityContext": container_security_context,
        "ports": [{"containerPort": API_PORT, "name": "http"}],
        "resources": {
            "requests": {"cpu": AGENT_CPU_REQUEST, "memory": AGENT_MEMORY_REQUEST},
            "limits": {"cpu": AGENT_CPU_LIMIT, "memory": AGENT_MEMORY_LIMIT},
        },
        "readinessProbe": {
            "httpGet": {"path": "/ready", "port": "http"},
            "initialDelaySeconds": 5,
            "periodSeconds": 10,
        },
        "livenessProbe": {
            "httpGet": {"path": "/health", "port": "http"},
            "initialDelaySeconds": 15,
            "periodSeconds": 20,
        },
        "volumeMounts": volume_mounts,
        "env": env,
    }

    containers = [agent_container]
    if runtime_kind == "langgraph":
        for index, sidecar_spec in enumerate(mcp_sidecars):
            sidecar_name = sidecar_spec.get("name", f"tool-{index}")
            containers.append(
                {
                    "name": f"mcp-{sidecar_name}",
                    "image": sidecar_spec.get("image", "busybox"),
                    "ports": [{"containerPort": sidecar_spec.get("port", 8080)}],
                    "securityContext": container_security_context,
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": "500m", "memory": "256Mi"},
                    },
                    "volumeMounts": [{"name": "tmp-volume", "mountPath": "/tmp"}],
                }
            )

    pod_spec: dict[str, Any] = {
        "serviceAccountName": RUNTIME_SERVICE_ACCOUNT,
        "securityContext": pod_security_context,
        "containers": containers,
        "volumes": volumes,
    }
    if IMAGE_PULL_SECRETS:
        pod_spec["imagePullSecrets"] = [{"name": secret_name} for secret_name in IMAGE_PULL_SECRETS]
    if enable_gvisor:
        pod_spec["runtimeClassName"] = "runsc"

    storage_spec = spec.get("storage", {})

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": sandbox_name(name),
            "namespace": namespace,
            "labels": {"app": "ai-agent", "agent-name": name, "runtime-kind": runtime_kind},
        },
        "spec": {
            "serviceName": sandbox_name(name),
            "replicas": 1,
            "selector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "updateStrategy": {"type": "RollingUpdate"},
            "persistentVolumeClaimRetentionPolicy": {
                "whenDeleted": "Retain",
                "whenScaled": "Retain",
            },
            "template": {
                "metadata": {"labels": {"app": "ai-agent", "agent-name": name, "runtime-kind": runtime_kind}},
                "spec": pod_spec,
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "state-volume"},
                    "spec": build_pvc_spec(
                        storage_spec.get("size", DEFAULT_STORAGE_SIZE),
                        storage_spec.get("storageClassName"),
                    ),
                }
            ],
        },
    }


def ensure_persistent_storage(namespace: str, manifest: dict[str, Any]) -> None:
    core_api = kubernetes.client.CoreV1Api()
    try:
        core_api.create_namespaced_persistent_volume_claim(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status != 409:
            raise


def ensure_service(namespace: str, manifest: dict[str, Any]) -> None:
    core_api = kubernetes.client.CoreV1Api()
    service_name = manifest["metadata"]["name"]
    try:
        core_api.create_namespaced_service(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_service(name=service_name, namespace=namespace, body=manifest)
            return
        raise


def ensure_statefulset(namespace: str, manifest: dict[str, Any]) -> None:
    apps_api = kubernetes.client.AppsV1Api()
    statefulset_name = manifest["metadata"]["name"]
    try:
        apps_api.create_namespaced_stateful_set(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            apps_api.patch_namespaced_stateful_set(name=statefulset_name, namespace=namespace, body=manifest)
            return
        raise


def ensure_secret(namespace: str, manifest: dict[str, Any]) -> None:
    core_api = kubernetes.client.CoreV1Api()
    secret_name = str(manifest["metadata"]["name"])
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_secret(name=secret_name, namespace=namespace, body=manifest)
            return
        raise


def ensure_tenant_runtime_secret(namespace: str, tenant_name: str, logger: logging.Logger) -> None:
    if SECRET_PROVISIONING_MODE == "external-secrets":
        external_secret = {
            "apiVersion": "external-secrets.io/v1beta1",
            "kind": "ExternalSecret",
            "metadata": {"name": SECRET_NAME, "namespace": namespace},
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": CLUSTER_SECRET_STORE, "kind": "ClusterSecretStore"},
                "target": {"name": SECRET_NAME},
                "data": [
                    {
                        "secretKey": "LITELLM_MASTER_KEY",
                        "remoteRef": {"key": "litellm-master-key"},
                    }
                ],
            },
        }
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            custom_api.create_namespaced_custom_object(
                group="external-secrets.io",
                version="v1beta1",
                namespace=namespace,
                plural="externalsecrets",
                body=external_secret,
            )
            logger.info("ExternalSecret '%s' provisioned for tenant '%s'", SECRET_NAME, tenant_name)
        except ApiException as exc:
            if exc.status == 409:
                try:
                    custom_api.patch_namespaced_custom_object(
                        group="external-secrets.io",
                        version="v1beta1",
                        namespace=namespace,
                        plural="externalsecrets",
                        name=SECRET_NAME,
                        body=external_secret,
                    )
                except ApiException as patch_exc:
                    raise kopf.TemporaryError(
                        f"Failed to update ExternalSecret '{SECRET_NAME}' for tenant '{tenant_name}': {patch_exc}",
                        delay=30,
                    ) from patch_exc
            else:
                raise kopf.TemporaryError(
                    f"Failed to reconcile ExternalSecret '{SECRET_NAME}' for tenant '{tenant_name}': {exc}",
                    delay=30,
                ) from exc
        return

    if not DEFAULT_LITELLM_MASTER_KEY:
        logger.warning(
            "Skipping tenant runtime secret provisioning for '%s' because DEFAULT_LITELLM_MASTER_KEY is empty.",
            tenant_name,
        )
        return

    secret_manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "managed-by": "ai-agent-sandbox",
                "tenant": tenant_name,
            },
        },
        "type": "Opaque",
        "stringData": {"LITELLM_MASTER_KEY": DEFAULT_LITELLM_MASTER_KEY},
    }
    ensure_secret(namespace, secret_manifest)
    logger.info("Secret '%s' provisioned for tenant '%s'", SECRET_NAME, tenant_name)


def create_mcp_network_policy_manifest(name: str, namespace: str, allowed_mcp_types: list[str]) -> dict[str, Any]:
    """Create/replace a per-agent NetworkPolicy that restricts MCP egress to
    only the mcp-server pod *types* listed in AgentPolicy.spec.allowedMcpServers.

    Each allowed type generates a separate egress rule using the pod label
    ``mcp.sandbox.enterprise.ai/type=<type>`` ANDed with the mcp-hub namespace
    label ``sandbox.enterprise.ai/mcp-hub=true``.  If allowedMcpServers is
    empty, no MCP egress is allowed at all.
    """
    egress_rules: list[dict[str, Any]] = []
    for mcp_type in allowed_mcp_types:
        egress_rules.append({
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"sandbox.enterprise.ai/mcp-hub": "true"}
                    },
                    "podSelector": {
                        "matchLabels": {"mcp.sandbox.enterprise.ai/type": mcp_type}
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8000}],
        })

    manifest: dict[str, Any] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{sandbox_name(name)}-mcp-egress",
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "agent-name": name,
                "sandbox.enterprise.ai/policy-type": "mcp-egress",
            },
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "policyTypes": ["Egress"],
            "egress": egress_rules,
        },
    }
    return manifest


def ensure_network_policy(namespace: str, manifest: dict[str, Any]) -> None:
    networking_api = kubernetes.client.NetworkingV1Api()
    policy_name = str(manifest["metadata"]["name"])
    try:
        networking_api.create_namespaced_network_policy(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            networking_api.replace_namespaced_network_policy(
                name=policy_name, namespace=namespace, body=manifest
            )
        else:
            raise


def create_agent_resources(spec: dict[str, Any], name: str, namespace: str) -> None:
    ensure_runtime_access(namespace)
    policy_name, policy_spec = resolve_agent_policy(namespace, spec.get("policyRef"))
    tenant_spec = resolve_tenant_for_namespace(namespace)
    validate_agent_model(spec.get("model", "gpt-4"), policy_spec, tenant_spec)
    allowed_mcp = sorted(
        {
            str(item).strip()
            for item in (policy_spec.get("allowedMcpServers") or [])
            if str(item).strip()
        }
    )

    service_manifest = create_agent_service_manifest(name, namespace)
    statefulset_manifest = create_agent_statefulset_manifest(name, namespace, spec, policy_name, policy_spec)
    network_policy_manifest = create_mcp_network_policy_manifest(name, namespace, allowed_mcp)
    mcp_auth_secret_manifest: dict[str, Any] | None = None
    if allowed_mcp:
        mcp_auth_secret_manifest = create_mcp_auth_secret_manifest(namespace)

    for manifest in (service_manifest, statefulset_manifest, network_policy_manifest, mcp_auth_secret_manifest):
        if manifest is None:
            continue
        kopf.adopt(manifest)

    ensure_service(namespace, service_manifest)
    if mcp_auth_secret_manifest is not None:
        ensure_secret(namespace, mcp_auth_secret_manifest)
    ensure_statefulset(namespace, statefulset_manifest)
    ensure_network_policy(namespace, network_policy_manifest)


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def create_agent(spec: dict[str, Any], name: str, namespace: str, logger: Any, **kwargs: Any) -> None:
    logger.info("Creating sandbox for AIAgent %s in %s", name, namespace)
    try:
        create_agent_resources(spec, name, namespace)
        logger.info("Sandbox resources for %s created successfully", name)
    except ApiException as exc:
        logger.error("Exception when creating agent resources: %s", exc)
        if exc.status in (400, 422):
            raise kopf.PermanentError(f"Invalid agent resource spec: {exc}") from exc
        raise kopf.TemporaryError(f"Failed to create agent resources: {exc}", delay=10) from exc


@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def update_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    logger.info("Updating AIAgent %s by patching its singleton StatefulSet", name)

    try:
        create_agent_resources(spec, name, namespace)
        logger.info("AIAgent %s updated successfully", name)
    except ApiException as exc:
        logger.error("Failed to recreate sandbox resources: %s", exc)
        if exc.status in (400, 422):
            raise kopf.PermanentError(f"Invalid pod spec for update: {exc}") from exc
        raise kopf.TemporaryError(f"Unexpected error during update: {exc}", delay=5) from exc


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def delete_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    logger.info("AIAgent %s deleted. StatefulSet and Service will be garbage-collected; PVCs are retained.", name)


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def create_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    tenant_name = spec.get("tenantName", name)
    target_ns = spec.get("namespace", f"agent-tenant-{tenant_name}")
    quota_spec = spec.get("resourceQuota", {})
    admin_users = spec.get("adminUsers", [])

    if target_ns in PROTECTED_NAMESPACES or target_ns == OPERATOR_NAMESPACE:
        raise kopf.PermanentError(
            f"Refusing to provision tenant '{tenant_name}' into protected namespace '{target_ns}'."
        )

    logger.info("Provisioning tenant '%s' in namespace '%s'", tenant_name, target_ns)

    core_api = kubernetes.client.CoreV1Api()
    rbac_api = kubernetes.client.RbacAuthorizationV1Api()

    namespace_body = kubernetes.client.V1Namespace(
        metadata=kubernetes.client.V1ObjectMeta(
            name=target_ns,
            labels={
                "managed-by": "ai-agent-sandbox",
                "tenant": tenant_name,
                # Required by the mcp-hub NetworkPolicy to allow ingress from
                # tenant agent pods into the mcp-hub namespace MCP server pods.
                "sandbox.enterprise.ai/tenant": "true",
            },
        )
    )
    try:
        core_api.create_namespace(body=namespace_body)
        logger.info("Namespace '%s' created", target_ns)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespace(
                name=target_ns,
                body={"metadata": {"labels": namespace_body.metadata.labels}},
            )
            logger.info("Namespace '%s' already exists", target_ns)
        elif exc.status in (400, 422):
            raise kopf.PermanentError(f"Invalid namespace spec: {exc}") from exc
        else:
            raise

    ensure_runtime_access(target_ns)

    hard_limits = {}
    if quota_spec.get("maxCPU"):
        hard_limits["limits.cpu"] = quota_spec["maxCPU"]
    if quota_spec.get("maxMemory"):
        hard_limits["limits.memory"] = quota_spec["maxMemory"]
    if quota_spec.get("maxPods"):
        hard_limits["pods"] = str(quota_spec["maxPods"])
    if quota_spec.get("maxGPU"):
        hard_limits["requests.nvidia.com/gpu"] = quota_spec["maxGPU"]

    if hard_limits:
        quota_body = kubernetes.client.V1ResourceQuota(
            metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-quota"),
            spec=kubernetes.client.V1ResourceQuotaSpec(hard=hard_limits),
        )
        try:
            core_api.create_namespaced_resource_quota(namespace=target_ns, body=quota_body)
            logger.info("ResourceQuota created for tenant '%s': %s", tenant_name, hard_limits)
        except ApiException as exc:
            if exc.status == 409:
                core_api.patch_namespaced_resource_quota(
                    name=f"{tenant_name}-quota",
                    namespace=target_ns,
                    body=quota_body,
                )
            else:
                raise

    limit_range = kubernetes.client.V1LimitRange(
        metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-limits"),
        spec=kubernetes.client.V1LimitRangeSpec(
            limits=[
                kubernetes.client.V1LimitRangeItem(
                    type="Container",
                    default={"cpu": "500m", "memory": "512Mi"},
                    default_request={"cpu": "100m", "memory": "128Mi"},
                )
            ]
        ),
    )
    try:
        core_api.create_namespaced_limit_range(namespace=target_ns, body=limit_range)
        logger.info("LimitRange created for tenant '%s'", tenant_name)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_limit_range(
                name=f"{tenant_name}-limits",
                namespace=target_ns,
                body=limit_range,
            )
        else:
            raise

    role = kubernetes.client.V1Role(
        metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-agent-admin", namespace=target_ns),
        rules=[
            kubernetes.client.V1PolicyRule(
                api_groups=["sandbox.enterprise.ai"],
                resources=["aiagents", "agentpolicies", "agentapprovals", "agentworkflows", "agentevals"],
                verbs=["*"],
            ),
            kubernetes.client.V1PolicyRule(
                api_groups=[""],
                resources=["pods", "pods/exec", "pods/portforward", "pods/log", "services"],
                verbs=["get", "list", "watch", "create"],
            ),
        ],
    )
    try:
        rbac_api.create_namespaced_role(namespace=target_ns, body=role)
    except ApiException as exc:
        if exc.status == 409:
            rbac_api.patch_namespaced_role(
                name=f"{tenant_name}-agent-admin",
                namespace=target_ns,
                body=role,
            )
        else:
            raise

    for user in admin_users:
        safe_user = re.sub(r"[^a-z0-9-]", "-", user.lower().strip()).strip("-")
        if not safe_user:
            logger.warning("Skipping empty or invalid user string: %s", user)
            continue

        binding = kubernetes.client.V1RoleBinding(
            metadata=kubernetes.client.V1ObjectMeta(
                name=f"{tenant_name}-{safe_user}-binding",
                namespace=target_ns,
            ),
            role_ref=kubernetes.client.V1RoleRef(
                api_group="rbac.authorization.k8s.io",
                kind="Role",
                name=f"{tenant_name}-agent-admin",
            ),
            subjects=[
                kubernetes.client.V1Subject(
                    kind="User",
                    name=user,
                    api_group="rbac.authorization.k8s.io",
                )
            ],
        )
        try:
            rbac_api.create_namespaced_role_binding(namespace=target_ns, body=binding)
            logger.info("RoleBinding created for user '%s' in tenant '%s'", user, tenant_name)
        except ApiException as exc:
            if exc.status == 409:
                rbac_api.patch_namespaced_role_binding(
                    name=f"{tenant_name}-{safe_user}-binding",
                    namespace=target_ns,
                    body=binding,
                )
            else:
                raise

    ensure_tenant_runtime_secret(target_ns, tenant_name, logger)

    logger.info("Tenant '%s' fully provisioned", tenant_name)


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def delete_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    tenant_name = spec.get("tenantName", name)
    target_ns = spec.get("namespace", f"agent-tenant-{tenant_name}")
    if target_ns in PROTECTED_NAMESPACES:
        logger.error("Refusing to delete protected namespace '%s' via tenant deletion.", target_ns)
        return

    logger.info("Deleting tenant '%s' by removing namespace '%s'", tenant_name, target_ns)
    try:
        kubernetes.client.CoreV1Api().delete_namespace(name=target_ns)
    except ApiException as exc:
        if exc.status != 404:
            raise


def patch_custom_status(plural: str, namespace: str, name: str, status: dict[str, Any]) -> None:
    kubernetes.client.CustomObjectsApi().patch_namespaced_custom_object_status(
        group="sandbox.enterprise.ai",
        version="v1alpha1",
        namespace=namespace,
        plural=plural,
        name=name,
        body={"status": status},
    )


def ensure_worker_artifact_storage(kind: str, resource_namespace: str, resource_name: str) -> str:
    manifest = create_worker_artifact_pvc_manifest(kind, resource_namespace, resource_name)
    ensure_persistent_storage(OPERATOR_NAMESPACE, manifest)
    return str(manifest["metadata"]["name"])


def create_worker_job_manifest(
    kind: str,
    resource_namespace: str,
    resource_name: str,
    generation: int,
    artifact_pvc_name: str,
    artifact_path: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    timestamp = int(time.time())
    job_name = hashed_resource_name(kind, resource_namespace, resource_name, suffix=f"{generation}-{timestamp}")
    artifact_journal_path = workflow_journal_path(artifact_path)
    pod_security_context = {
        "runAsNonRoot": True,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container_security_context = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": OPERATOR_NAMESPACE,
            "labels": {
                "app": "operator-worker",
                "sandbox.enterprise.ai/resource-kind": kind,
                "sandbox.enterprise.ai/resource-name": resource_name,
                "sandbox.enterprise.ai/resource-namespace": resource_namespace,
            },
        },
        "spec": {
            "ttlSecondsAfterFinished": WORKER_TTL_SECONDS_AFTER_FINISHED,
            "activeDeadlineSeconds": WORKER_ACTIVE_DEADLINE_SECONDS,
            "backoffLimit": 1,
            "template": {
                "metadata": {
                    "labels": {
                        "app": "operator-worker",
                        "sandbox.enterprise.ai/resource-kind": kind,
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": WORKER_SERVICE_ACCOUNT_NAME,
                    "securityContext": pod_security_context,
                    "imagePullSecrets": [{"name": secret_name} for secret_name in IMAGE_PULL_SECRETS],
                    "containers": [
                        {
                            "name": "worker",
                            "image": WORKER_IMAGE,
                            "imagePullPolicy": WORKER_IMAGE_PULL_POLICY,
                            "command": ["python", "/app/worker.py"],
                            "securityContext": container_security_context,
                            "resources": {
                                "requests": {"cpu": WORKER_CPU_REQUEST, "memory": WORKER_MEMORY_REQUEST},
                                "limits": {"cpu": WORKER_CPU_LIMIT, "memory": WORKER_MEMORY_LIMIT},
                            },
                            "env": [
                                {"name": "WORKER_KIND", "value": kind},
                                {"name": "TARGET_NAMESPACE", "value": resource_namespace},
                                {"name": "TARGET_NAME", "value": resource_name},
                                {"name": "OPERATOR_NAMESPACE", "value": OPERATOR_NAMESPACE},
                                {"name": "WORKER_JOB_NAME", "value": job_name},
                                {"name": "ARTIFACT_PATH", "value": artifact_path},
                                {"name": "ARTIFACT_JOURNAL_PATH", "value": artifact_journal_path},
                                {"name": "ARTIFACT_PVC_NAME", "value": artifact_pvc_name},
                                {"name": "AGENT_RUNTIME_TIMEOUT_SECONDS", "value": AGENT_RUNTIME_TIMEOUT_SECONDS},
                                {"name": "WORKFLOW_RUN_ID", "value": run_id or ""},
                                {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                            ],
                            "volumeMounts": [
                                {"name": "artifacts", "mountPath": ARTIFACT_MOUNT_PATH},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "artifacts",
                            "persistentVolumeClaim": {"claimName": artifact_pvc_name},
                        },
                        {"name": "tmp", "emptyDir": {}},
                    ],
                },
            },
        },
    }


def enqueue_worker_job(
    kind: str,
    resource_namespace: str,
    resource_name: str,
    generation: int,
    artifact_pvc_name: str,
    artifact_path: str,
    *,
    run_id: str | None = None,
) -> str:
    manifest = create_worker_job_manifest(
        kind,
        resource_namespace,
        resource_name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=run_id,
    )
    batch_api = kubernetes.client.BatchV1Api()
    batch_api.create_namespaced_job(namespace=OPERATOR_NAMESPACE, body=manifest)
    return str(manifest["metadata"]["name"])


def read_job_state(name: str, namespace: str) -> str:
    if not name:
        return "missing"

    batch_api = kubernetes.client.BatchV1Api()
    try:
        job = batch_api.read_namespaced_job(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            return "missing"
        raise

    status = job.status
    if status is None:
        return "pending"
    if (status.active or 0) > 0:
        return "active"
    if (status.succeeded or 0) > 0:
        return "succeeded"
    if (status.failed or 0) > 0:
        return "failed"
    return "pending"


def enqueue_eval_job(
    spec: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    *,
    scheduled: bool = False,
) -> None:
    test_suite = spec.get("testSuite") or []
    generation = int((meta or {}).get("generation", 1))
    artifact_pvc_name = ensure_worker_artifact_storage("eval", namespace, name)
    artifact_path = artifact_file_path("eval", namespace, name, generation)
    job_name = enqueue_worker_job(
        "eval",
        namespace,
        name,
        generation,
        artifact_pvc_name,
        artifact_path,
    )
    summary = {
        "queuedAt": now_iso(),
        "caseCount": len(test_suite),
        "completedCases": 0,
    }
    if scheduled:
        summary["scheduleTriggered"] = True
    patch_custom_status(
        "agentevals",
        namespace,
        name,
        {
            "phase": "queued",
            "observedGeneration": generation,
            "artifactRef": build_artifact_ref(artifact_pvc_name, artifact_path, generation),
            "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
            "summary": summary,
        },
    )
    logger.info("Queued eval '%s/%s' for background execution in job '%s'.", namespace, name, job_name)


def enqueue_workflow_job(
    spec: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    *,
    current_status: dict[str, Any] | None = None,
    run_id: str | None = None,
    requeue_reason: str | None = None,
) -> str:
    graph = validate_workflow_spec(spec)
    steps = spec.get("steps") or []
    generation = int((meta or {}).get("generation", 1))
    workflow_status = current_status or {}
    resolved_run_id = run_id or str(workflow_status.get("runId") or "") or build_workflow_run_id(
        namespace,
        name,
        generation,
    )
    artifact_pvc_name = ensure_worker_artifact_storage("workflow", namespace, name)
    artifact_path = artifact_file_path("workflow", namespace, name, generation)
    journal_path = workflow_journal_path(artifact_path)
    job_name = enqueue_worker_job(
        "workflow",
        namespace,
        name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=resolved_run_id,
    )
    existing_summary = workflow_status.get("summary", {}) or {}
    summary = {
        **existing_summary,
        "queuedAt": now_iso(),
        "updatedAt": now_iso(),
        "completedSteps": int(existing_summary.get("completedSteps", 0) or 0),
        "totalSteps": len(steps),
        "rootSteps": graph.get("roots") or [],
        "runId": resolved_run_id,
    }
    if requeue_reason:
        summary["lastRequeueReason"] = requeue_reason

    patch_custom_status(
        "agentworkflows",
        namespace,
        name,
        {
            "phase": "queued",
            "runId": resolved_run_id,
            "currentStep": str(workflow_status.get("currentStep", "") or ""),
            "observedGeneration": generation,
            "artifactRef": build_artifact_ref(
                artifact_pvc_name,
                artifact_path,
                generation,
                journal_path=journal_path,
            ),
            "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
            "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
            "summary": summary,
            "pendingApproval": None,
            "stepStates": workflow_status.get("stepStates", {}) or {},
        },
    )
    logger.info(
        "Queued workflow '%s/%s' for background execution in job '%s' with run '%s'.",
        namespace,
        name,
        job_name,
        resolved_run_id,
    )
    return job_name


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def run_workflow(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    graph = validate_workflow_spec(spec)
    steps = spec.get("steps") or []

    current_status = status or {}
    generation = int((meta or {}).get("generation", 1))
    observed_generation = int(current_status.get("observedGeneration", 0) or 0)
    phase = str(current_status.get("phase", ""))
    if observed_generation == generation and phase in {"queued", "running", "waiting-approval", "completed"}:
        logger.info("Workflow '%s' generation %s is already %s; skipping enqueue.", name, generation, phase)
        return

    try:
        patch_custom_status(
            "agentworkflows",
            namespace,
            name,
            {
                **current_status,
                "summary": {
                    **(current_status.get("summary", {}) or {}),
                    "totalSteps": len(steps),
                    "rootSteps": graph.get("roots") or [],
                    "updatedAt": now_iso(),
                },
            },
        )
        enqueue_workflow_job(spec, meta, name, namespace, logger, current_status=current_status)
    except ApiException as exc:
        logger.error("Failed to enqueue workflow '%s/%s': %s", namespace, name, exc)
        raise kopf.TemporaryError(f"Failed to enqueue workflow: {exc}", delay=10) from exc


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def run_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    test_suite = spec.get("testSuite") or []
    if not test_suite:
        raise kopf.PermanentError("AgentEval must contain at least one test case")

    schedule = str(spec.get("schedule") or "").strip()
    if schedule:
        validate_eval_schedule(schedule)

    current_status = status or {}
    generation = int((meta or {}).get("generation", 1))
    observed_generation = int(current_status.get("observedGeneration", 0) or 0)
    phase = str(current_status.get("phase", ""))
    if observed_generation == generation and phase in {"queued", "running", "completed", "failed"}:
        logger.info("Eval '%s/%s' generation %s is already %s; skipping enqueue.", name, namespace, generation, phase)
        return

    try:
        enqueue_eval_job(spec, meta, name, namespace, logger)
    except ApiException as exc:
        logger.error("Failed to enqueue eval '%s/%s': %s", namespace, name, exc)
        raise kopf.TemporaryError(f"Failed to enqueue eval: {exc}", delay=10) from exc


@kopf.timer(
    "sandbox.enterprise.ai",
    "v1alpha1",
    "agentworkflows",
    interval=WORKFLOW_POLL_SECONDS,
)  # type: ignore[arg-type]
def run_workflow_watchdog(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:  # type: ignore[misc]
    del kwargs

    current_status = status or {}
    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    reason = workflow_should_requeue(current_status, job_state)
    if reason is None:
        return

    logger.warning(
        "Workflow '%s/%s' will be re-enqueued by watchdog: %s",
        namespace,
        name,
        reason,
    )
    try:
        enqueue_workflow_job(
            spec,
            meta,
            name,
            namespace,
            logger,
            current_status=current_status,
            run_id=str(current_status.get("runId") or "") or None,
            requeue_reason=reason,
        )
    except ApiException as exc:
        logger.error("Failed to re-enqueue stale workflow '%s/%s': %s", namespace, name, exc)
        raise kopf.TemporaryError(f"Failed to re-enqueue workflow: {exc}", delay=10) from exc


@kopf.timer(
    "sandbox.enterprise.ai",
    "v1alpha1",
    "agentevals",
    interval=EVAL_SCHEDULE_POLL_SECONDS,
)  # type: ignore[arg-type]
def run_scheduled_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs

    schedule = str(spec.get("schedule") or "").strip()
    if not schedule:
        return

    validate_eval_schedule(schedule)

    current_status = status or {}
    phase = str(current_status.get("phase", ""))
    if phase == "running":
        return

    retry_stale_queue = False
    if phase == "queued":
        summary = current_status.get("summary", {}) or {}
        queued_at = parse_iso_datetime(str(summary.get("queuedAt") or ""))
        if queued_at is None:
            logger.warning(
                "Scheduled eval '%s/%s' is queued without queuedAt metadata; waiting for the next timer tick.",
                namespace,
                name,
            )
            return

        worker_job = current_status.get("workerJob", {}) or {}
        job_state = read_job_state(
            str(worker_job.get("name") or ""),
            str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
        )
        queue_age_seconds = (datetime.now(timezone.utc) - queued_at).total_seconds()
        if job_state in {"active", "pending"}:
            return
        if queue_age_seconds < SCHEDULED_EVAL_QUEUE_STALE_SECONDS:
            return

        retry_stale_queue = True
        logger.warning(
            "Scheduled eval '%s/%s' is stuck in phase 'queued' with worker job state '%s'; re-enqueueing.",
            namespace,
            name,
            job_state,
        )

    if not retry_stale_queue and not scheduled_eval_due(schedule, str(current_status.get("lastRun") or "")):
        return

    try:
        enqueue_eval_job(spec, meta, name, namespace, logger, scheduled=True)
    except ApiException as exc:
        logger.error("Failed to enqueue scheduled eval '%s/%s': %s", namespace, name, exc)
        raise kopf.TemporaryError(f"Failed to enqueue scheduled eval: {exc}", delay=10) from exc


@kopf.on.field("sandbox.enterprise.ai", "v1alpha1", "agentapprovals", field="status.decision")  # type: ignore[arg-type]
def on_approval_decision(old: str, new: str, name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    if old == "pending" and new in ("approved", "denied"):
        logger.info("AgentApproval '%s' decision changed from '%s' to '%s'", name, old, new)
        custom_api = kubernetes.client.CustomObjectsApi()
        workflows = custom_api.list_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentworkflows",
        ).get("items", [])

        for workflow in workflows:
            workflow_name = workflow.get("metadata", {}).get("name", "")
            workflow_status = workflow.get("status", {}) or {}
            pending_approval = workflow_status.get("pendingApproval", {}) or {}
            if pending_approval.get("name") != name:
                continue
            if workflow_status.get("phase") != "waiting-approval":
                continue

            workflow_meta = workflow.get("metadata", {}) or {}
            workflow_spec = workflow.get("spec", {}) or {}
            generation = int(workflow_status.get("observedGeneration") or workflow_meta.get("generation", 1))
            run_id = str(workflow_status.get("runId") or "") or None

            if new == "approved":
                job_name = enqueue_workflow_job(
                    workflow_spec,
                    workflow_meta,
                    workflow_name,
                    namespace,
                    logger,
                    current_status=workflow_status,
                    run_id=run_id,
                    requeue_reason=f"approval '{name}' was approved",
                )
                logger.info(
                    "Resumed workflow '%s/%s' after approval '%s' via job '%s'.",
                    namespace,
                    workflow_name,
                    name,
                    job_name,
                )
            else:
                current_step = str(workflow_status.get("currentStep", "") or "")
                step_states = workflow_status.get("stepStates", {}) or {}
                if current_step:
                    current_step_state = dict(step_states.get(current_step, {}) or {})
                    current_step_state.update(
                        {
                            "status": "denied",
                            "updatedAt": now_iso(),
                            "completedAt": now_iso(),
                            "failureClass": "approval_denied",
                            "error": f"Approval '{name}' was denied",
                        }
                    )
                    step_states[current_step] = current_step_state

                artifact_ref = workflow_status.get("artifactRef", {}) or {}
                journal_path = str(
                    workflow_status.get("journalRef", {}).get("path")
                    or artifact_ref.get("journalPath")
                    or workflow_journal_path(
                        str(artifact_ref.get("path") or artifact_file_path("workflow", namespace, workflow_name, generation))
                    )
                )
                artifact_pvc_name = str(
                    artifact_ref.get("pvcName")
                    or ensure_worker_artifact_storage("workflow", namespace, workflow_name)
                )
                artifact_path = str(
                    artifact_ref.get("path")
                    or artifact_file_path("workflow", namespace, workflow_name, generation)
                )
                patch_custom_status(
                    "agentworkflows",
                    namespace,
                    workflow_name,
                    {
                        "phase": "failed",
                        "runId": workflow_status.get("runId"),
                        "currentStep": current_step,
                        "observedGeneration": generation,
                        "artifactRef": build_artifact_ref(
                            artifact_pvc_name,
                            artifact_path,
                            generation,
                            journal_path=journal_path,
                        ),
                        "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
                        "summary": {
                            **(workflow_status.get("summary", {}) or {}),
                            "failedAt": now_iso(),
                            "error": f"Approval '{name}' was denied",
                            "updatedAt": now_iso(),
                        },
                        "pendingApproval": {
                            "name": name,
                            "namespace": namespace,
                            "decision": new,
                        },
                        "stepStates": step_states,
                    },
                )
