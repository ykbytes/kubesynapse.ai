"""REST API Gateway for the AI Agent Sandbox."""

import asyncio
import contextlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from jose import jwk, jwt
from jose.utils import base64url_decode
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("api-gateway")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from kubernetes import config

        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config.")
        except Exception:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig file.")
    except Exception as exc:
        logger.warning("Failed to load K8s config on startup (API might fail): %s", exc)
    yield

app = FastAPI(
    title="AI Agent Sandbox API",
    description="Enterprise REST API for interacting with AI Agents",
    version="1.0.0",
    lifespan=lifespan,
)


def cors_origins() -> list[str]:
    raw_origins = os.getenv("API_GATEWAY_CORS_ORIGINS", "").strip()
    if not raw_origins:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-Id"],
)

NATS_URL = os.getenv("NATS_URL", "nats://ai-agent-sandbox-nats:4222")
QDRANT_URL = os.getenv("QDRANT_URL", "http://ai-agent-sandbox-qdrant:6333")
AUTH_MODE = os.getenv("API_GATEWAY_AUTH_MODE", "shared_token").strip().lower()
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", "").strip()
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip()
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "").strip()
SHARED_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
AGENT_RUNTIME_TIMEOUT_SECONDS = max(float(os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "360")), 1.0)
OIDC_JWKS_TIMEOUT_SECONDS = max(float(os.getenv("OIDC_JWKS_TIMEOUT_SECONDS", "10")), 1.0)
JWKS_CACHE: dict[str, Any] = {"keys": [], "expires_at": 0.0}
STREAM_KEEPALIVE_SECONDS = max(float(os.getenv("API_GATEWAY_STREAM_KEEPALIVE_SECONDS", "15")), 5.0)


class InvokeRequest(BaseModel):
    prompt: str = ""
    thread_id: str | None = None
    model: str | None = None
    system: str | None = None
    require_approval: bool = False
    approval_action: str | None = None
    tool_name: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = None
    debug: bool = False
    no_session: bool = False
    max_turns: int | None = None
    working_directory: str | None = None
    builtin_extensions: list[str] = Field(default_factory=list)
    stdio_extensions: list[str] = Field(default_factory=list)
    streamable_http_extensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_fields(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None
        self.working_directory = self.working_directory.strip() or None if self.working_directory is not None else None
        self.builtin_extensions = [str(item).strip() for item in self.builtin_extensions if str(item).strip()]
        self.stdio_extensions = [str(item).strip() for item in self.stdio_extensions if str(item).strip()]
        self.streamable_http_extensions = [str(item).strip() for item in self.streamable_http_extensions if str(item).strip()]
        return self


class InvokeResponse(BaseModel):
    agent_name: str
    response: str
    thread_id: str
    model: str
    policy_name: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None
    sandbox_session: dict[str, Any] | None = None
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    warnings: list[str] = Field(default_factory=list)


class ApprovalInfo(BaseModel):
    name: str
    namespace: str
    decision: str
    agent_name: str
    action: str
    requested_at: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str | None = None


class ApprovalDecisionRequest(BaseModel):
    """Body for PATCH /api/approvals/{name} — records a human decision."""

    decision: str = Field(
        pattern="^(approved|denied)$",
        description="Must be 'approved' or 'denied'",
    )
    reason: str | None = Field(
        default=None,
        max_length=1024,
        description="Optional free-text reason for the decision",
    )


class AgentInfo(BaseModel):
    name: str
    model: str
    namespace: str
    status: str
    runtime_kind: str = "langgraph"


class PolicyInfo(BaseModel):
    name: str
    namespace: str


class AgentDetail(AgentInfo):
    system_prompt: str = ""
    policy_ref: str | None = None
    storage_size: str | None = None
    enable_gvisor: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    goose_config_files: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class CreateAgentRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=4000)
    policy_ref: str | None = Field(default=None, max_length=253)
    storage_size: str | None = Field(default="1Gi", max_length=32)
    runtime_kind: str = Field(default="langgraph", pattern=r"^(langgraph|goose)$")
    enable_gvisor: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    goose_config_files: dict[str, Any] = Field(default_factory=dict)


class UpdateAgentRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=4000)
    policy_ref: str | None = Field(default=None, max_length=253)
    storage_size: str | None = Field(default="1Gi", max_length=32)
    runtime_kind: str | None = Field(default=None, pattern=r"^(langgraph|goose)$")
    enable_gvisor: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    goose_config_files: dict[str, Any] | None = None


class WorkflowStepRequest(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    agent_ref: str = Field(min_length=1, max_length=63)
    prompt: str = Field(default="", max_length=4000)
    depends_on: list[str] = Field(default_factory=list)
    require_approval: bool = False
    execution: dict[str, Any] | None = None


class WorkflowRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    description: str = Field(default="", max_length=4000)
    input: str = Field(default="", max_length=4000)
    message_bus: str = Field(default="in-memory", pattern=r"^(in-memory)$")
    steps: list[WorkflowStepRequest] = Field(default_factory=list)


class WorkflowUpdateRequest(BaseModel):
    description: str = Field(default="", max_length=4000)
    input: str = Field(default="", max_length=4000)
    message_bus: str = Field(default="in-memory", pattern=r"^(in-memory)$")
    steps: list[WorkflowStepRequest] = Field(default_factory=list)


class WorkflowInfo(BaseModel):
    name: str
    namespace: str
    description: str = ""
    input: str = ""
    message_bus: str = "in-memory"
    steps: list[WorkflowStepRequest] = Field(default_factory=list)
    phase: str = "pending"
    current_step: str = ""
    observed_generation: int | None = None
    summary: dict[str, Any] | None = None
    artifact_ref: dict[str, Any] | None = None
    journal_ref: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
    run_id: str | None = None
    step_states: dict[str, Any] | None = None
    worker_job: dict[str, Any] | None = None
    created_at: str | None = None


class EvalTestCaseRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    expected_output: str = Field(default="", max_length=4000)
    metrics: list[str] = Field(default_factory=list)


class EvalRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    agent_ref: str = Field(min_length=1, max_length=63)
    schedule: str | None = Field(default=None, max_length=128)
    test_suite: list[EvalTestCaseRequest] = Field(default_factory=list)
    failure_threshold: dict[str, Any] = Field(default_factory=dict)


class EvalUpdateRequest(BaseModel):
    agent_ref: str = Field(min_length=1, max_length=63)
    schedule: str | None = Field(default=None, max_length=128)
    test_suite: list[EvalTestCaseRequest] = Field(default_factory=list)
    failure_threshold: dict[str, Any] = Field(default_factory=dict)


class EvalInfo(BaseModel):
    name: str
    namespace: str
    agent_ref: str
    schedule: str | None = None
    test_suite: list[EvalTestCaseRequest] = Field(default_factory=list)
    failure_threshold: dict[str, Any] = Field(default_factory=dict)
    phase: str = "pending"
    passed: bool | None = None
    last_run: str | None = None
    observed_generation: int | None = None
    summary: dict[str, Any] | None = None
    artifact_ref: dict[str, Any] | None = None
    worker_job: dict[str, Any] | None = None
    created_at: str | None = None


class DeleteResponse(BaseModel):
    status: str
    kind: str
    name: str
    namespace: str


RESOURCE_GROUP = "sandbox.enterprise.ai"
RESOURCE_VERSION = "v1alpha1"
RESOURCE_KIND_BY_PLURAL = {
    "aiagents": "AIAgent",
    "agentworkflows": "AgentWorkflow",
    "agentevals": "AgentEval",
}


def agent_runtime_url(agent_name: str, namespace: str) -> str:
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:8080"


def normalized_runtime_kind(raw_value: str | None) -> str:
    runtime_kind = (raw_value or "langgraph").strip().lower() or "langgraph"
    if runtime_kind not in {"langgraph", "goose"}:
        raise ValueError(f"Unsupported runtime kind '{runtime_kind}'")
    return runtime_kind


def normalize_goose_config_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="goose_config_files paths must not be blank")
    if normalized_path.startswith("/"):
        raise HTTPException(status_code=400, detail="goose_config_files paths must be relative")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail=f"goose_config_files path '{raw_path}' is invalid")

    candidate = "/".join(parts)
    if candidate == "secrets.yaml":
        raise HTTPException(
            status_code=400,
            detail="goose_config_files cannot preseed secrets.yaml; use Kubernetes secrets and environment variables instead",
        )
    if parts[0] == "permissions":
        raise HTTPException(
            status_code=400,
            detail="goose_config_files cannot preseed permissions/* because Goose manages that path at runtime",
        )
    return candidate


def parse_goose_config_files(config_files: Any, *, source: str) -> dict[str, Any]:
    if config_files is None:
        return {}
    if not isinstance(config_files, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be a JSON object keyed by relative Goose config paths")

    normalized: dict[str, Any] = {}
    for raw_path, raw_content in sorted(config_files.items(), key=lambda item: str(item[0])):
        normalized_path = normalize_goose_config_file_path(raw_path)
        if raw_content is None:
            raise HTTPException(status_code=400, detail=f"{source}.{normalized_path} must not be null")
        normalized[normalized_path] = raw_content
    return normalized


def runtime_kind_from_spec(spec: dict[str, Any] | None) -> str:
    runtime_spec = (spec or {}).get("runtime") or {}
    if isinstance(runtime_spec, dict):
        return normalized_runtime_kind(runtime_spec.get("kind"))
    return "langgraph"


def validate_agent_runtime_compatibility(spec: dict[str, Any]) -> None:
    if runtime_kind_from_spec(spec) != "goose":
        return

    errors: list[str] = []
    if spec.get("mcpServers"):
        errors.append(
            "Goose runtime does not support mcp_servers. Use the LangGraph runtime for MCP routing today."
        )
    if spec.get("mcpSidecars"):
        errors.append(
            "Goose runtime does not support mcp_sidecars. Use the LangGraph runtime for sidecar-based MCP tools today."
        )
    if errors:
        raise HTTPException(status_code=400, detail=" ".join(errors))


def validate_invoke_runtime_compatibility(runtime_kind: str, request: InvokeRequest) -> None:
    if runtime_kind != "goose":
        return

    unsupported_fields: list[str] = []
    if request.require_approval:
        unsupported_fields.append("require_approval")
    if request.tool_name.strip():
        unsupported_fields.append("tool_name")
    if (request.mcp_server or "").strip():
        unsupported_fields.append("mcp_server")
    if request.sandbox_session is not None:
        unsupported_fields.append("sandbox_session")

    if unsupported_fields:
        joined_fields = ", ".join(unsupported_fields)
        raise HTTPException(
            status_code=400,
            detail=(
                "Goose runtime currently supports chat-style prompt invocation plus Goose-native run controls. "
                f"Unsupported fields for goose agents: {joined_fields}."
            ),
        )


def parse_json_object_response(response: httpx.Response, *, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        response_text = response.text.strip()
        preview = (response_text[:400] + "...") if len(response_text) > 400 else response_text
        raise HTTPException(
            status_code=502,
            detail=f"{context} returned invalid JSON: {preview or 'empty response'}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail=f"{context} returned a non-object JSON payload")
    return payload


def error_payload_from_body(body: bytes, fallback: str) -> dict[str, str]:
    text = body.decode("utf-8", errors="ignore").strip()
    if not text:
        return {"error": fallback}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"error": text}

    if isinstance(parsed, dict):
        for key in ("detail", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return {"error": value.strip()}

    return {"error": text}


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def sse_keepalive_comment() -> str:
    return ": keepalive\n\n"


def build_agent_spec(
    body: CreateAgentRequest | UpdateAgentRequest,
    existing_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_runtime = (existing_spec or {}).get("runtime") or {}
    existing_runtime_kind = None
    existing_goose_config_files: Any = None
    if isinstance(existing_runtime, dict):
        existing_runtime_kind = existing_runtime.get("kind")
        existing_goose = existing_runtime.get("goose") or {}
        if isinstance(existing_goose, dict):
            existing_goose_config_files = existing_goose.get("configFiles")

    runtime_kind = normalized_runtime_kind(getattr(body, "runtime_kind", None) or existing_runtime_kind)
    requested_goose_config_files = getattr(body, "goose_config_files", None)
    if requested_goose_config_files is None:
        goose_config_files = parse_goose_config_files(
            existing_goose_config_files,
            source="existing runtime.goose.configFiles",
        )
    else:
        goose_config_files = parse_goose_config_files(
            requested_goose_config_files,
            source="goose_config_files",
        )

    if runtime_kind != "goose" and goose_config_files:
        raise HTTPException(
            status_code=400,
            detail="goose_config_files is only supported when runtime_kind is 'goose'",
        )

    spec: dict[str, Any] = {
        "model": body.model.strip(),
        "systemPrompt": body.system_prompt.strip(),
        "enableGVisor": body.enable_gvisor,
        "storage": {"size": (body.storage_size or "1Gi").strip() or "1Gi"},
        "mcpServers": [server.strip() for server in body.mcp_servers if server.strip()],
        "mcpSidecars": body.mcp_sidecars,
        "runtime": {"kind": runtime_kind},
    }
    if runtime_kind == "goose" and goose_config_files:
        spec["runtime"]["goose"] = {"configFiles": goose_config_files}
    if body.policy_ref and body.policy_ref.strip():
        spec["policyRef"] = body.policy_ref.strip()
    return spec


def build_workflow_spec(body: WorkflowRequest | WorkflowUpdateRequest) -> dict[str, Any]:
    steps = []
    for step in body.steps:
        step_spec: dict[str, Any] = {
            "name": step.name.strip(),
            "agentRef": step.agent_ref.strip(),
            "prompt": step.prompt,
            "dependsOn": [
                dependency.strip()
                for dependency in step.depends_on
                if dependency.strip()
            ],
            "requireApproval": step.require_approval,
        }
        if isinstance(step.execution, dict) and step.execution:
            step_spec["execution"] = step.execution
        steps.append(step_spec)

    return {
        "description": body.description.strip(),
        "input": body.input.strip(),
        "messageBus": body.message_bus,
        "steps": steps,
    }


def build_eval_spec(body: EvalRequest | EvalUpdateRequest) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "agentRef": body.agent_ref.strip(),
        "testSuite": [
            {
                "input": test_case.input,
                "expectedOutput": test_case.expected_output,
                "metrics": test_case.metrics,
            }
            for test_case in body.test_suite
        ],
        "failureThreshold": body.failure_threshold,
    }
    if body.schedule and body.schedule.strip():
        spec["schedule"] = body.schedule.strip()
    return spec


def list_custom_resources(plural: str, namespace: str) -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        result = client.CustomObjectsApi().list_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Failed to list %s: %s", plural, exc)
        raise HTTPException(status_code=502, detail=f"Failed to list {plural}: {exc}") from exc


def read_custom_resource(plural: str, name: str, namespace: str, label: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().get_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"{label} '{name}' not found: {exc}") from exc


def create_custom_resource(plural: str, namespace: str, name: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            body={
                "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
                "kind": RESOURCE_KIND_BY_PLURAL[plural],
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                },
                "spec": spec,
            },
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 409:
            raise HTTPException(status_code=409, detail=f"Resource '{name}' already exists") from exc
        raise HTTPException(status_code=502, detail=f"Failed to create resource '{name}': {exc}") from exc


def replace_custom_resource_spec(plural: str, name: str, namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = api.get_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
        return api.replace_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
            body={
                "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
                "kind": RESOURCE_KIND_BY_PLURAL[plural],
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "resourceVersion": current.get("metadata", {}).get("resourceVersion"),
                },
                "spec": spec,
            },
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"Resource '{name}' was not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to update resource '{name}': {exc}") from exc


def delete_custom_resource(plural: str, name: str, namespace: str, label: str) -> None:
    try:
        from kubernetes import client

        client.CustomObjectsApi().delete_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{label} '{name}' not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to delete {label} '{name}': {exc}") from exc


def policy_info_from_resource(policy: dict[str, Any]) -> PolicyInfo:
    metadata = policy.get("metadata", {})
    return PolicyInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
    )


def agent_info_from_resource(agent: dict[str, Any]) -> AgentInfo:
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    runtime_spec = spec.get("runtime") or {}
    runtime_kind = "langgraph"
    if isinstance(runtime_spec, dict):
        runtime_kind = str(runtime_spec.get("kind") or "langgraph")
    namespace = metadata.get("namespace", "default")
    name = metadata.get("name", "")
    return AgentInfo(
        name=name,
        model=spec.get("model", "unknown"),
        namespace=namespace,
        status=get_agent_status(name, namespace),
        runtime_kind=runtime_kind,
    )


def agent_detail_from_resource(agent: dict[str, Any]) -> AgentDetail:
    info = agent_info_from_resource(agent)
    spec = agent.get("spec", {})
    metadata = agent.get("metadata", {})
    storage = spec.get("storage", {}) if isinstance(spec.get("storage"), dict) else {}
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    goose_runtime = runtime.get("goose") if isinstance(runtime.get("goose"), dict) else {}
    return AgentDetail(
        **info.model_dump(),
        system_prompt=spec.get("systemPrompt", "") or "",
        policy_ref=spec.get("policyRef"),
        storage_size=storage.get("size"),
        enable_gvisor=bool(spec.get("enableGVisor", False)),
        mcp_servers=spec.get("mcpServers") or [],
        mcp_sidecars=spec.get("mcpSidecars") or [],
        goose_config_files=parse_goose_config_files(
            goose_runtime.get("configFiles"),
            source="AIAgent.spec.runtime.goose.configFiles",
        ),
        created_at=metadata.get("creationTimestamp"),
    )


def workflow_info_from_resource(workflow: dict[str, Any]) -> WorkflowInfo:
    metadata = workflow.get("metadata", {})
    spec = workflow.get("spec", {})
    status = workflow.get("status", {})
    return WorkflowInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
        description=spec.get("description", "") or "",
        input=spec.get("input", "") or "",
        message_bus=spec.get("messageBus", "in-memory") or "in-memory",
        steps=[
            WorkflowStepRequest(
                name=step.get("name", ""),
                agent_ref=step.get("agentRef", ""),
                prompt=step.get("prompt", "") or "",
                depends_on=step.get("dependsOn") or [],
                require_approval=bool(step.get("requireApproval", False)),
                execution=step.get("execution") or None,
            )
            for step in spec.get("steps") or []
        ],
        phase=status.get("phase", "pending") or "pending",
        current_step=status.get("currentStep", "") or "",
        observed_generation=status.get("observedGeneration"),
        summary=status.get("summary"),
        artifact_ref=status.get("artifactRef"),
        journal_ref=status.get("journalRef"),
        pending_approval=status.get("pendingApproval"),
        run_id=status.get("runId"),
        step_states=status.get("stepStates"),
        worker_job=status.get("workerJob"),
        created_at=metadata.get("creationTimestamp"),
    )


def eval_info_from_resource(eval_resource: dict[str, Any]) -> EvalInfo:
    metadata = eval_resource.get("metadata", {})
    spec = eval_resource.get("spec", {})
    status = eval_resource.get("status", {})
    return EvalInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
        agent_ref=spec.get("agentRef", ""),
        schedule=spec.get("schedule"),
        test_suite=[
            EvalTestCaseRequest(
                input=test_case.get("input", ""),
                expected_output=test_case.get("expectedOutput", "") or "",
                metrics=test_case.get("metrics") or [],
            )
            for test_case in spec.get("testSuite") or []
        ],
        failure_threshold=spec.get("failureThreshold") or {},
        phase=status.get("phase", "pending") or "pending",
        passed=status.get("passed"),
        last_run=status.get("lastRun"),
        observed_generation=status.get("observedGeneration"),
        summary=status.get("summary"),
        artifact_ref=status.get("artifactRef"),
        worker_job=status.get("workerJob"),
        created_at=metadata.get("creationTimestamp"),
    )


def get_agents(namespace: str = "default") -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        result = api.list_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="aiagents",
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Failed to list agents: %s", exc)
        return []


def get_policies(namespace: str = "default") -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        result = client.CustomObjectsApi().list_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentpolicies",
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Failed to list policies: %s", exc)
        return []


def read_agent(agent_name: str, namespace: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().get_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="aiagents",
            name=agent_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found: {exc}") from exc


def create_agent_resource(body: CreateAgentRequest, namespace: str) -> dict[str, Any]:
    spec = build_agent_spec(body)
    validate_agent_runtime_compatibility(spec)

    try:
        from kubernetes import client

        resource_body: dict[str, Any] = {
            "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
            "kind": "AIAgent",
            "metadata": {
                "name": body.name,
                "namespace": namespace,
            },
            "spec": spec,
        }

        return client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="aiagents",
            body=resource_body,
        )
    except Exception as exc:
        if getattr(exc, "status", None) == 409:
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists") from exc
        raise HTTPException(status_code=502, detail=f"Failed to create agent '{body.name}': {exc}") from exc


def read_approval(approval_name: str, namespace: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().get_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentapprovals",
            name=approval_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_name}' not found: {exc}") from exc


def list_agent_pods(agent_name: str, namespace: str) -> list[Any]:
    try:
        from kubernetes import client

        pods = client.CoreV1Api().list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app=ai-agent,agent-name={agent_name}",
        )

        def pod_sort_key(item: Any) -> float:
            metadata = getattr(item, "metadata", None)
            creation_timestamp = getattr(metadata, "creation_timestamp", None)
            if creation_timestamp is None:
                return 0.0
            return creation_timestamp.timestamp()

        return sorted(
            pods.items,
            key=pod_sort_key,
            reverse=True,
        )
    except Exception:
        return []


def get_agent_status(agent_name: str, namespace: str) -> str:
    pods = list_agent_pods(agent_name, namespace)
    if not pods:
        return "unknown"

    pod = pods[0]
    return str(getattr(pod.status, "phase", "Unknown") or "Unknown").lower()


async def load_jwks() -> list[dict[str, Any]]:
    if JWKS_CACHE["expires_at"] > time.time():
        return JWKS_CACHE["keys"]

    if not OIDC_JWKS_URL:
        raise HTTPException(status_code=503, detail="OIDC JWKS URL is not configured")

    async with httpx.AsyncClient(timeout=OIDC_JWKS_TIMEOUT_SECONDS) as client:
        response = await client.get(OIDC_JWKS_URL)
        response.raise_for_status()
        keys = response.json().get("keys", [])

    JWKS_CACHE.update({"keys": keys, "expires_at": time.time() + 300})
    return keys


def validate_claims(claims: dict[str, Any]) -> None:
    now = int(time.time())
    if claims.get("exp") is not None and now >= int(claims["exp"]):
        raise HTTPException(status_code=401, detail="Token has expired")
    if claims.get("nbf") is not None and now < int(claims["nbf"]):
        raise HTTPException(status_code=401, detail="Token is not active yet")
    if OIDC_ISSUER and claims.get("iss") != OIDC_ISSUER:
        raise HTTPException(status_code=401, detail="Token issuer is invalid")
    if OIDC_AUDIENCE:
        audience = claims.get("aud")
        valid = audience == OIDC_AUDIENCE or (
            isinstance(audience, list) and OIDC_AUDIENCE in audience
        )
        if not valid:
            raise HTTPException(status_code=401, detail="Token audience is invalid")


async def verify_oidc_token(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    key_id = header.get("kid")
    keys = await load_jwks()
    key_data = next((item for item in keys if item.get("kid") == key_id), None)
    if key_data is None:
        raise HTTPException(status_code=401, detail="Unable to find a signing key for this token")

    signing_key = jwk.construct(key_data)
    message, encoded_signature = token.rsplit(".", 1)
    decoded_signature = base64url_decode(encoded_signature.encode("utf-8"))
    if not signing_key.verify(message.encode("utf-8"), decoded_signature):
        raise HTTPException(status_code=401, detail="Token signature is invalid")

    claims = jwt.get_unverified_claims(token)
    validate_claims(claims)
    return claims


def verify_shared_token(token: str) -> dict[str, Any]:
    if not SHARED_TOKEN:
        raise HTTPException(status_code=503, detail="Gateway shared token is not configured")
    if not hmac.compare_digest(token, SHARED_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return {"sub": "shared-token-user"}


async def verify_token(authorization: str = Header(...)) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    if AUTH_MODE == "oidc":
        return await verify_oidc_token(token)
    if AUTH_MODE == "shared_token":
        return verify_shared_token(token)
    if AUTH_MODE == "auto":
        if "." in token and OIDC_JWKS_URL:
            try:
                return await verify_oidc_token(token)
            except HTTPException as exc:
                logger.warning(
                    "OIDC token verification failed in auto mode; falling back to shared token auth: %s",
                    exc.detail,
                )
            except Exception as exc:
                logger.warning(
                    "OIDC token verification errored in auto mode; falling back to shared token auth: %s",
                    exc,
                )
        return verify_shared_token(token)
    raise HTTPException(status_code=503, detail=f"Unsupported auth mode '{AUTH_MODE}'")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "gateway": "ai-agent-sandbox",
        "auth_mode": AUTH_MODE,
        "nats_url": NATS_URL,
        "qdrant_url": QDRANT_URL,
    }


@app.get("/api/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "gateway": "ai-agent-sandbox"}


@app.get("/api/approvals/{approval_name}", response_model=ApprovalInfo)
def get_approval(
    approval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})
    status = approval.get("status", {})
    return ApprovalInfo(
        name=approval.get("metadata", {}).get("name", approval_name),
        namespace=approval.get("metadata", {}).get("namespace", namespace),
        decision=status.get("decision", "pending"),
        agent_name=spec.get("agentName", ""),
        action=spec.get("action", ""),
        requested_at=spec.get("requestedAt"),
        decided_by=status.get("decidedBy"),
        decided_at=status.get("decidedAt"),
        reason=status.get("reason"),
    )


@app.get("/api/policies", response_model=list[PolicyInfo])
def list_policies(namespace: str = "default", user=Depends(verify_token)):
    del user
    return sorted(
        [policy_info_from_resource(policy) for policy in get_policies(namespace)],
        key=lambda item: item.name,
    )


@app.patch("/api/approvals/{approval_name}", response_model=ApprovalInfo)
def decide_approval(
    approval_name: str,
    body: ApprovalDecisionRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Record an approve/deny decision on a pending AgentApproval.

    Patches the AgentApproval CRD status subresource with the decision,
    the deciding user identity (JWT ``sub`` claim), and a UTC timestamp.
    The agent runtime watches ``status.decision`` and resumes or blocks
    execution once the field is set.
    """
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})

    decided_by = str(user.get("sub", "unknown"))
    decided_at = datetime.now(timezone.utc).isoformat()

    try:
        from kubernetes import client

        client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentapprovals",
            name=approval_name,
            body={
                "status": {
                    "decision": body.decision,
                    "decidedBy": decided_by,
                    "decidedAt": decided_at,
                    "reason": body.reason or "",
                }
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to record approval decision: {exc}",
        ) from exc

    return ApprovalInfo(
        name=approval_name,
        namespace=namespace,
        decision=body.decision,
        agent_name=spec.get("agentName", ""),
        action=spec.get("action", ""),
        requested_at=spec.get("requestedAt"),
        decided_by=decided_by,
        decided_at=decided_at,
        reason=body.reason,
    )


@app.get("/api/agents", response_model=list[AgentInfo])
def list_agents(namespace: str = "default", user=Depends(verify_token)):
    return sorted([
        agent_info_from_resource(agent)
        for agent in get_agents(namespace)
    ], key=lambda item: item.name)


@app.post("/api/agents", response_model=AgentDetail, status_code=201)
def create_agent(
    body: CreateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    agent = create_agent_resource(body, namespace)
    return agent_detail_from_resource(agent)


@app.get("/api/agents/{agent_name}", response_model=AgentDetail)
def get_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return agent_detail_from_resource(read_agent(agent_name, namespace))


@app.patch("/api/agents/{agent_name}", response_model=AgentDetail)
def update_agent(
    agent_name: str,
    body: UpdateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    current_agent = read_agent(agent_name, namespace)
    next_spec = build_agent_spec(body, current_agent.get("spec", {}))
    validate_agent_runtime_compatibility(next_spec)
    updated = replace_custom_resource_spec(
        "aiagents",
        agent_name,
        namespace,
        next_spec,
    )
    return agent_detail_from_resource(updated)


@app.delete("/api/agents/{agent_name}", response_model=DeleteResponse)
def delete_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    delete_custom_resource("aiagents", agent_name, namespace, "Agent")
    return DeleteResponse(status="deleted", kind="agent", name=agent_name, namespace=namespace)


@app.get("/api/workflows", response_model=list[WorkflowInfo])
def list_workflows(namespace: str = "default", user=Depends(verify_token)):
    del user
    return sorted(
        [workflow_info_from_resource(item) for item in list_custom_resources("agentworkflows", namespace)],
        key=lambda item: item.name,
    )


@app.post("/api/workflows", response_model=WorkflowInfo, status_code=201)
def create_workflow(
    body: WorkflowRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    created = create_custom_resource(
        "agentworkflows",
        namespace,
        body.name,
        build_workflow_spec(body),
    )
    return workflow_info_from_resource(created)


@app.get("/api/workflows/{workflow_name}", response_model=WorkflowInfo)
def get_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return workflow_info_from_resource(read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow"))


@app.patch("/api/workflows/{workflow_name}", response_model=WorkflowInfo)
def update_workflow(
    workflow_name: str,
    body: WorkflowUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    updated = replace_custom_resource_spec("agentworkflows", workflow_name, namespace, build_workflow_spec(body))
    return workflow_info_from_resource(updated)


@app.delete("/api/workflows/{workflow_name}", response_model=DeleteResponse)
def delete_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    delete_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    return DeleteResponse(status="deleted", kind="workflow", name=workflow_name, namespace=namespace)


@app.get("/api/evals", response_model=list[EvalInfo])
def list_evals(namespace: str = "default", user=Depends(verify_token)):
    del user
    return sorted(
        [eval_info_from_resource(item) for item in list_custom_resources("agentevals", namespace)],
        key=lambda item: item.name,
    )


@app.post("/api/evals", response_model=EvalInfo, status_code=201)
def create_eval(
    body: EvalRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    created = create_custom_resource(
        "agentevals",
        namespace,
        body.name,
        build_eval_spec(body),
    )
    return eval_info_from_resource(created)


@app.get("/api/evals/{eval_name}", response_model=EvalInfo)
def get_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return eval_info_from_resource(read_custom_resource("agentevals", eval_name, namespace, "Eval"))


@app.patch("/api/evals/{eval_name}", response_model=EvalInfo)
def update_eval(
    eval_name: str,
    body: EvalUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    updated = replace_custom_resource_spec("agentevals", eval_name, namespace, build_eval_spec(body))
    return eval_info_from_resource(updated)


@app.delete("/api/evals/{eval_name}", response_model=DeleteResponse)
def delete_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    delete_custom_resource("agentevals", eval_name, namespace, "Eval")
    return DeleteResponse(status="deleted", kind="eval", name=eval_name, namespace=namespace)


@app.post("/api/agents/{agent_name}/invoke", response_model=InvokeResponse)
async def invoke_agent(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    agent = await asyncio.to_thread(read_agent, agent_name, namespace)
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    request_payload = request.model_dump()
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/invoke",
                json=request_payload,
                headers={"x-request-id": request_id},
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Agent invocation failed: {exc}") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Agent invocation failed")
        raise HTTPException(status_code=502, detail=f"Agent invocation failed: {error_payload['error']}")

    data = parse_json_object_response(response, context="Agent runtime /invoke")
    return InvokeResponse(
        agent_name=agent_name,
        response=data.get("response", ""),
        thread_id=data.get("thread_id", ""),
        model=data.get("model") or agent["spec"].get("model", "unknown"),
        policy_name=data.get("policy_name"),
        tool_name=data.get("tool_name"),
        tool_result=data.get("tool_result"),
        sandbox_session=data.get("sandbox_session"),
        status=data.get("status", "completed"),
        approval_name=data.get("approval_name"),
        retry_after_seconds=data.get("retry_after_seconds"),
        warnings=data.get("warnings") or [],
    )


@app.post("/api/agents/{agent_name}/invoke/stream")
async def invoke_agent_stream(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    agent = await asyncio.to_thread(read_agent, agent_name, namespace)
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    request_payload = request.model_dump()
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{agent_runtime_url(agent_name, namespace)}/invoke/stream",
                    json=request_payload,
                    headers={"x-request-id": request_id},
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield sse_event(
                            "response.error",
                            error_payload_from_body(body, "Agent invocation failed"),
                        )
                        return
                    stream_iterator = response.aiter_text()
                    next_chunk_task = asyncio.create_task(anext(stream_iterator))
                    try:
                        while True:
                            done, _ = await asyncio.wait({next_chunk_task}, timeout=STREAM_KEEPALIVE_SECONDS)
                            if not done:
                                yield sse_keepalive_comment()
                                continue

                            try:
                                chunk = next_chunk_task.result()
                            except StopAsyncIteration:
                                break

                            if chunk:
                                yield chunk

                            next_chunk_task = asyncio.create_task(anext(stream_iterator))
                    finally:
                        try:
                            if not next_chunk_task.done():
                                next_chunk_task.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await next_chunk_task
                        except NameError:
                            pass
        except Exception as exc:
            yield sse_event("response.error", {"error": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/agents/{agent_name}/logs")
def get_agent_logs(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    read_agent(agent_name, namespace)
    try:
        pods = list_agent_pods(agent_name, namespace)
        if not pods:
            raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

        pod_name = str(getattr(pods[0].metadata, "name", "") or "")
        if not pod_name:
            raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

        from kubernetes import client

        logs = client.CoreV1Api().read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container="agent-runtime",
            tail_lines=100,
        )
        return {"agent_name": agent_name, "logs": logs}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Could not retrieve logs: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
