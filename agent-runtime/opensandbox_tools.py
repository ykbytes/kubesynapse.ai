from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from env_utils import get_bool_env as _get_bool_env, get_int_env as _get_int_env

logger = logging.getLogger("opensandbox-tools")

PublishEvent = Callable[[str, dict[str, Any]], None]


class SandboxToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenSandboxSettings:
    domain: str
    api_key: str
    protocol: str
    use_server_proxy: bool
    request_timeout_seconds: int
    default_ttl_seconds: int
    connect_timeout_seconds: int
    health_check_polling_interval_ms: int
    default_image: str
    code_image: str
    browser_image: str
    editor_image: str
    browser_entrypoint: tuple[str, ...]
    code_entrypoint: tuple[str, ...]
    editor_port: int
    browser_vnc_port: int
    browser_devtools_port: int
    default_python_version: str
    default_java_version: str
    default_node_version: str
    default_go_version: str
    secure_runtime_type: str


SETTINGS = OpenSandboxSettings(
    domain=os.getenv("OPEN_SANDBOX_DOMAIN", "").strip(),
    api_key=os.getenv("OPEN_SANDBOX_API_KEY", "").strip(),
    protocol=os.getenv("OPEN_SANDBOX_PROTOCOL", "http").strip() or "http",
    use_server_proxy=_get_bool_env("OPEN_SANDBOX_USE_SERVER_PROXY", False),
    request_timeout_seconds=_get_int_env("OPEN_SANDBOX_REQUEST_TIMEOUT_SECONDS", 300, minimum=1),
    default_ttl_seconds=_get_int_env("OPEN_SANDBOX_DEFAULT_TTL_SECONDS", 600, minimum=60),
    connect_timeout_seconds=_get_int_env("OPEN_SANDBOX_CONNECT_TIMEOUT_SECONDS", 30, minimum=1),
    health_check_polling_interval_ms=_get_int_env(
        "OPEN_SANDBOX_HEALTH_CHECK_POLLING_INTERVAL_MS", 200, minimum=50
    ),
    default_image=os.getenv("OPEN_SANDBOX_DEFAULT_IMAGE", "python:3.11").strip() or "python:3.11",
    code_image=os.getenv("OPEN_SANDBOX_CODE_IMAGE", "opensandbox/code-interpreter:latest").strip()
    or "opensandbox/code-interpreter:latest",
    browser_image=os.getenv("OPEN_SANDBOX_BROWSER_IMAGE", "opensandbox/chrome:latest").strip()
    or "opensandbox/chrome:latest",
    editor_image=os.getenv("OPEN_SANDBOX_EDITOR_IMAGE", "opensandbox/vscode:latest").strip()
    or "opensandbox/vscode:latest",
    browser_entrypoint=tuple(
        item for item in os.getenv("OPEN_SANDBOX_BROWSER_ENTRYPOINT", "/entrypoint").split(" ") if item
    )
    or ("/entrypoint",),
    code_entrypoint=tuple(
        item
        for item in os.getenv(
            "OPEN_SANDBOX_CODE_ENTRYPOINT", "/opt/opensandbox/code-interpreter.sh"
        ).split(" ")
        if item
    )
    or ("/opt/opensandbox/code-interpreter.sh",),
    editor_port=_get_int_env("OPEN_SANDBOX_EDITOR_PORT", 8443, minimum=1),
    browser_vnc_port=_get_int_env("OPEN_SANDBOX_BROWSER_VNC_PORT", 5901, minimum=1),
    browser_devtools_port=_get_int_env("OPEN_SANDBOX_BROWSER_DEVTOOLS_PORT", 9222, minimum=1),
    default_python_version=os.getenv("OPEN_SANDBOX_PYTHON_VERSION", "3.11").strip() or "3.11",
    default_java_version=os.getenv("OPEN_SANDBOX_JAVA_VERSION", "17").strip() or "17",
    default_node_version=os.getenv("OPEN_SANDBOX_NODE_VERSION", "20").strip() or "20",
    default_go_version=os.getenv("OPEN_SANDBOX_GO_VERSION", "1.24").strip() or "1.24",
    secure_runtime_type=os.getenv("OPEN_SANDBOX_SECURE_RUNTIME_TYPE", "").strip(),
)


SUPPORTED_SANDBOX_TOOLS = frozenset(
    {
        "sandbox.session.create",
        "sandbox.session.info",
        "sandbox.session.endpoint",
        "sandbox.session.renew",
        "sandbox.session.pause",
        "sandbox.session.resume",
        "sandbox.session.kill",
        "sandbox.command.run",
        "sandbox.command.logs",
        "sandbox.filesystem.read",
        "sandbox.filesystem.write",
        "sandbox.filesystem.delete",
        "sandbox.filesystem.mkdir",
        "sandbox.filesystem.search",
        "sandbox.filesystem.info",
        "sandbox.metrics.get",
        "sandbox.code.start",
        "sandbox.code.run",
        "sandbox.code.context.create",
        "sandbox.code.context.delete",
        "sandbox.browser.start",
        "sandbox.editor.start",
    }
)


def sandbox_runtime_metadata() -> dict[str, Any]:
    return {
        "configured": bool(SETTINGS.domain),
        "domain": SETTINGS.domain,
        "protocol": SETTINGS.protocol,
        "useServerProxy": SETTINGS.use_server_proxy,
        "secureRuntime": SETTINGS.secure_runtime_type or None,
        "defaultTtlSeconds": SETTINGS.default_ttl_seconds,
        "supportedTools": sorted(SUPPORTED_SANDBOX_TOOLS),
        "presets": {
            "code": SETTINGS.code_image,
            "browser": SETTINGS.browser_image,
            "editor": SETTINGS.editor_image,
        },
    }


def is_sandbox_tool(tool_name: str | None) -> bool:
    return bool(tool_name and tool_name in SUPPORTED_SANDBOX_TOOLS)


def _publish(publish_event: PublishEvent | None, event: str, payload: dict[str, Any]) -> None:
    if publish_event is None:
        return
    publish_event(event, payload)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def format_tool_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)


def _ensure_configured() -> None:
    if not SETTINGS.domain:
        raise SandboxToolError(
            "OpenSandbox is not configured. Set OPEN_SANDBOX_DOMAIN and optionally OPEN_SANDBOX_API_KEY."
        )


def _as_string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _normalize_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _require_arg(tool_args: dict[str, Any], name: str) -> Any:
    value = tool_args.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SandboxToolError(f"{name} is required for this sandbox tool")
    return value


def _resolve_ttl_seconds(tool_args: dict[str, Any]) -> int:
    ttl_value = tool_args.get("ttl_seconds", SETTINGS.default_ttl_seconds)
    try:
        ttl_seconds = int(ttl_value)
    except (TypeError, ValueError) as exc:
        raise SandboxToolError(f"ttl_seconds must be an integer, got {ttl_value!r}") from exc
    if ttl_seconds < 60:
        raise SandboxToolError("ttl_seconds must be at least 60")
    return ttl_seconds


def _resolve_timeout(value: Any) -> timedelta | None:
    if value in (None, ""):
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise SandboxToolError(f"timeout_seconds must be an integer, got {value!r}") from exc
    if seconds <= 0:
        raise SandboxToolError("timeout_seconds must be positive")
    return timedelta(seconds=seconds)


def _sanitize_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
    if not session:
        return None
    return json.loads(json.dumps(session, default=_json_default))


def _serialize_endpoint(endpoint: Any) -> dict[str, Any]:
    return {
        "endpoint": endpoint.endpoint,
        "headers": dict(endpoint.headers),
    }


def _serialize_metrics(metrics: Any) -> dict[str, Any]:
    return {
        "cpuCount": metrics.cpu_count,
        "cpuUsedPercentage": metrics.cpu_used_percentage,
        "memoryTotalMiB": metrics.memory_total_in_mib,
        "memoryUsedMiB": metrics.memory_used_in_mib,
        "timestamp": metrics.timestamp,
    }


def _serialize_entry_info(entry: Any) -> dict[str, Any]:
    return {
        "path": entry.path,
        "mode": entry.mode,
        "owner": entry.owner,
        "group": entry.group,
        "size": entry.size,
        "modifiedAt": entry.modified_at.isoformat(),
        "createdAt": entry.created_at.isoformat(),
    }


def _serialize_info(info: Any) -> dict[str, Any]:
    return {
        "id": info.id,
        "status": {
            "state": info.status.state,
            "reason": info.status.reason,
            "message": info.status.message,
            "lastTransitionAt": info.status.last_transition_at.isoformat()
            if info.status.last_transition_at
            else None,
        },
        "entrypoint": list(info.entrypoint),
        "expiresAt": info.expires_at.isoformat(),
        "createdAt": info.created_at.isoformat(),
        "image": info.image.image if info.image else None,
        "metadata": dict(info.metadata or {}),
    }


def _serialize_execution(execution: Any) -> dict[str, Any]:
    return {
        "id": execution.id,
        "executionCount": execution.execution_count,
        "result": [
            {
                "text": item.text,
                "timestamp": item.timestamp,
                "extra": dict(item.extra_properties),
            }
            for item in execution.result
        ],
        "stdout": [
            {"text": message.text, "timestamp": message.timestamp}
            for message in execution.logs.stdout
        ],
        "stderr": [
            {"text": message.text, "timestamp": message.timestamp}
            for message in execution.logs.stderr
        ],
        "error": {
            "name": execution.error.name,
            "value": execution.error.value,
            "timestamp": execution.error.timestamp,
            "traceback": list(execution.error.traceback),
        }
        if execution.error
        else None,
    }


def _session_from_info(
    sandbox_id: str,
    profile: str,
    image: str,
    info: Any,
    current_session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = dict(current_session or {})
    session.update(
        {
            "sandbox_id": sandbox_id,
            "profile": profile,
            "image": image,
            "status": info.status.state,
            "expires_at": info.expires_at.isoformat(),
            "metadata": dict(info.metadata or {}),
            "entrypoint": list(info.entrypoint),
            "secure_runtime": SETTINGS.secure_runtime_type or None,
        }
    )
    session.setdefault("endpoints", {})
    session.setdefault("code_contexts", {})
    return _sanitize_session(session) or {}


def _set_session_endpoint(session: dict[str, Any], name: str, endpoint: Any) -> dict[str, Any]:
    session = dict(session)
    endpoints = dict(session.get("endpoints") or {})
    endpoints[name] = _serialize_endpoint(endpoint)
    session["endpoints"] = endpoints
    return _sanitize_session(session) or {}


def _build_connection_config(use_server_proxy: bool | None = None) -> Any:
    from opensandbox.config import ConnectionConfig

    _ensure_configured()
    return ConnectionConfig(
        domain=SETTINGS.domain,
        api_key=SETTINGS.api_key or None,
        protocol=SETTINGS.protocol,
        request_timeout=timedelta(seconds=SETTINGS.request_timeout_seconds),
        use_server_proxy=SETTINGS.use_server_proxy if use_server_proxy is None else use_server_proxy,
    )


def _build_network_policy(value: Any) -> Any | None:
    if not isinstance(value, dict):
        return None

    from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule

    egress = []
    for item in value.get("egress") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("target"):
            continue
        egress.append(NetworkRule(action=str(item.get("action", "allow")), target=str(item["target"])))

    default_action = value.get("default_action", value.get("defaultAction", "deny"))
    return NetworkPolicy(defaultAction=str(default_action), egress=egress)


def _build_volumes(value: Any) -> list[Any] | None:
    if not isinstance(value, list):
        return None

    from opensandbox.models.sandboxes import Host, PVC, Volume

    volumes = []
    for item in value:
        if not isinstance(item, dict):
            continue
        backend: dict[str, Any] = {}
        if isinstance(item.get("host"), dict) and item["host"].get("path"):
            backend["host"] = Host(path=str(item["host"]["path"]))
        if isinstance(item.get("pvc"), dict) and item["pvc"].get("claimName"):
            backend["pvc"] = PVC(claimName=str(item["pvc"]["claimName"]))
        volumes.append(
            Volume(
                name=str(item.get("name", "volume")),
                mountPath=str(item.get("mountPath", item.get("mount_path", "/mnt/data"))),
                readOnly=bool(item.get("readOnly", item.get("read_only", False))),
                subPath=item.get("subPath", item.get("sub_path")),
                **backend,
            )
        )
    return volumes or None


async def _create_sandbox(
    tool_args: dict[str, Any],
    *,
    profile: str,
    image: str,
    entrypoint: list[str] | None,
    env: dict[str, str],
    current_session: dict[str, Any] | None,
    publish_event: PublishEvent | None,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    from opensandbox import Sandbox

    config = _build_connection_config(tool_args.get("use_server_proxy"))
    ttl_seconds = _resolve_ttl_seconds(tool_args)
    metadata = _as_string_map(tool_args.get("metadata"))
    metadata.setdefault("sandbox.profile", profile)
    if SETTINGS.secure_runtime_type:
        metadata.setdefault("sandbox.secure_runtime", SETTINGS.secure_runtime_type)

    _publish(
        publish_event,
        "sandbox.lifecycle",
        {"action": "create.started", "profile": profile, "image": image, "ttlSeconds": ttl_seconds},
    )

    sandbox = await Sandbox.create(
        image,
        timeout=timedelta(seconds=ttl_seconds),
        ready_timeout=timedelta(seconds=SETTINGS.connect_timeout_seconds),
        health_check_polling_interval=timedelta(milliseconds=SETTINGS.health_check_polling_interval_ms),
        env=env,
        metadata=metadata,
        resource=_as_string_map(tool_args.get("resource")) or {"cpu": "1", "memory": "2Gi"},
        network_policy=_build_network_policy(tool_args.get("network_policy")),
        extensions=_as_string_map(tool_args.get("extensions")),
        entrypoint=entrypoint,
        volumes=_build_volumes(tool_args.get("volumes")),
        connection_config=config,
        skip_health_check=bool(tool_args.get("skip_health_check", False)),
    )
    info = await sandbox.get_info()
    session = _session_from_info(sandbox.id, profile, image, info, current_session=current_session)
    payload = {
        "tool": "sandbox.session.create",
        "profile": profile,
        "sandbox": _serialize_info(info),
        "session": session,
        "secureRuntime": SETTINGS.secure_runtime_type or None,
    }
    _publish(
        publish_event,
        "sandbox.lifecycle",
        {"action": "create.completed", "sandboxId": sandbox.id, "profile": profile, "expiresAt": session["expires_at"]},
    )
    return sandbox, session, payload


async def _connect_existing_sandbox(
    current_session: dict[str, Any] | None,
    tool_args: dict[str, Any],
    publish_event: PublishEvent | None,
    *,
    auto_create_profile: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    from opensandbox import Sandbox

    sandbox_id = str((current_session or {}).get("sandbox_id") or "").strip()
    if sandbox_id:
        _publish(publish_event, "sandbox.lifecycle", {"action": "connect.started", "sandboxId": sandbox_id})
        sandbox = await Sandbox.connect(
            sandbox_id,
            connection_config=_build_connection_config(tool_args.get("use_server_proxy")),
            connect_timeout=timedelta(seconds=SETTINGS.connect_timeout_seconds),
            health_check_polling_interval=timedelta(milliseconds=SETTINGS.health_check_polling_interval_ms),
            skip_health_check=bool(tool_args.get("skip_health_check", False)),
        )
        info = await sandbox.get_info()
        session = _session_from_info(
            sandbox.id,
            str((current_session or {}).get("profile") or tool_args.get("profile") or "generic"),
            str((current_session or {}).get("image") or info.image.image if info.image else SETTINGS.default_image),
            info,
            current_session=current_session,
        )
        _publish(publish_event, "sandbox.lifecycle", {"action": "connect.completed", "sandboxId": sandbox.id})
        return sandbox, session

    if auto_create_profile == "code":
        sandbox, session, _ = await _create_sandbox(
            tool_args,
            profile="code",
            image=str(tool_args.get("image") or SETTINGS.code_image),
            entrypoint=list(SETTINGS.code_entrypoint),
            env={
                "PYTHON_VERSION": str(tool_args.get("python_version") or SETTINGS.default_python_version),
                "JAVA_VERSION": str(tool_args.get("java_version") or SETTINGS.default_java_version),
                "NODE_VERSION": str(tool_args.get("node_version") or SETTINGS.default_node_version),
                "GO_VERSION": str(tool_args.get("go_version") or SETTINGS.default_go_version),
            },
            current_session=current_session,
            publish_event=publish_event,
        )
        return sandbox, session

    raise SandboxToolError(
        "No active sandbox session is bound to this thread. Create one first in the same thread_id."
    )


async def _poll_metrics(sandbox: Any, publish_event: PublishEvent | None, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            metrics = await sandbox.get_metrics()
            _publish(
                publish_event,
                "sandbox.metrics",
                {"sandboxId": sandbox.id, "metrics": _serialize_metrics(metrics)},
            )
        except Exception as exc:
            logger.debug("Failed to poll sandbox metrics: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            continue


def _build_execution_handlers(prefix: str, publish_event: PublishEvent | None) -> Any:
    from opensandbox.models.execd import ExecutionHandlers

    async def on_init(message: Any) -> None:
        _publish(publish_event, f"{prefix}.init", {"id": message.id, "timestamp": message.timestamp})

    async def on_stdout(message: Any) -> None:
        _publish(
            publish_event,
            f"{prefix}.stdout",
            {"text": message.text, "timestamp": message.timestamp},
        )

    async def on_stderr(message: Any) -> None:
        _publish(
            publish_event,
            f"{prefix}.stderr",
            {"text": message.text, "timestamp": message.timestamp},
        )

    async def on_result(message: Any) -> None:
        _publish(
            publish_event,
            f"{prefix}.result",
            {"text": message.text, "timestamp": message.timestamp, "extra": dict(message.extra_properties)},
        )

    async def on_execution_complete(message: Any) -> None:
        _publish(
            publish_event,
            f"{prefix}.complete",
            {
                "timestamp": message.timestamp,
                "executionTimeInMillis": message.execution_time_in_millis,
            },
        )

    async def on_error(message: Any) -> None:
        _publish(
            publish_event,
            f"{prefix}.error",
            {
                "name": message.name,
                "value": message.value,
                "timestamp": message.timestamp,
                "traceback": list(message.traceback),
            },
        )

    return ExecutionHandlers(
        on_init=on_init,
        on_stdout=on_stdout,
        on_stderr=on_stderr,
        on_result=on_result,
        on_execution_complete=on_execution_complete,
        on_error=on_error,
    )


async def _run_command(
    sandbox: Any,
    tool_args: dict[str, Any],
    publish_event: PublishEvent | None,
) -> dict[str, Any]:
    from opensandbox.models.execd import RunCommandOpts

    command = str(_require_arg(tool_args, "command"))
    timeout = _resolve_timeout(tool_args.get("timeout_seconds"))
    opts = RunCommandOpts(
        background=bool(tool_args.get("background", False)),
        working_directory=tool_args.get("working_directory"),
        timeout=timeout,
    )
    stop_event = asyncio.Event()
    metrics_task = None
    if bool(tool_args.get("stream_metrics", True)):
        metrics_task = asyncio.create_task(_poll_metrics(sandbox, publish_event, stop_event))
    try:
        execution = await sandbox.commands.run(
            command,
            opts=opts,
            handlers=_build_execution_handlers("sandbox.command", publish_event),
        )
    finally:
        if metrics_task is not None:
            stop_event.set()
            with contextlib.suppress(Exception):
                await metrics_task

    return {
        "tool": "sandbox.command.run",
        "sandboxId": sandbox.id,
        "command": command,
        "background": opts.background,
        "execution": _serialize_execution(execution),
    }


async def _run_code(
    sandbox: Any,
    session: dict[str, Any],
    tool_args: dict[str, Any],
    publish_event: PublishEvent | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from code_interpreter import CodeContext, CodeInterpreter, SupportedLanguage

    code = str(_require_arg(tool_args, "code"))
    language = str(tool_args.get("language") or SupportedLanguage.PYTHON)
    session = dict(session)
    contexts = dict(session.get("code_contexts") or {})

    async with sandbox:
        interpreter = await CodeInterpreter.create(sandbox)
        context_id = str(tool_args.get("context_id") or contexts.get(language) or "").strip()
        context = None
        if context_id:
            context = CodeContext(id=context_id, language=language)
        elif bool(tool_args.get("persist_context", True)):
            created = await interpreter.codes.create_context(language)
            context = created
            contexts[language] = created.id
            _publish(
                publish_event,
                "sandbox.code.context",
                {"action": "create", "language": language, "contextId": created.id},
            )

        stop_event = asyncio.Event()
        metrics_task = None
        if bool(tool_args.get("stream_metrics", True)):
            metrics_task = asyncio.create_task(_poll_metrics(sandbox, publish_event, stop_event))
        try:
            execution = await interpreter.codes.run(
                code,
                context=context,
                language=None if context is not None else language,
                handlers=_build_execution_handlers("sandbox.code", publish_event),
            )
        finally:
            if metrics_task is not None:
                stop_event.set()
                with contextlib.suppress(Exception):
                    await metrics_task

    session["code_contexts"] = contexts
    return {
        "tool": "sandbox.code.run",
        "sandboxId": sandbox.id,
        "language": language,
        "contextId": context.id if context is not None else contexts.get(language),
        "execution": _serialize_execution(execution),
    }, _sanitize_session(session) or {}


async def execute_sandbox_tool(
    tool_name: str,
    tool_args: dict[str, Any] | None,
    current_session: dict[str, Any] | None,
    publish_event: PublishEvent | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    tool_args = dict(tool_args or {})
    _ensure_configured()

    if tool_name == "sandbox.session.create":
        image = str(tool_args.get("image") or SETTINGS.default_image)
        entrypoint = tool_args.get("entrypoint")
        env = _as_string_map(tool_args.get("env"))
        sandbox, session, payload = await _create_sandbox(
            tool_args,
            profile=str(tool_args.get("profile") or "generic"),
            image=image,
            entrypoint=list(entrypoint) if isinstance(entrypoint, list) else None,
            env=env,
            current_session=current_session,
            publish_event=publish_event,
        )
        await sandbox.close()
        return payload, session

    if tool_name == "sandbox.browser.start":
        sandbox, session, payload = await _create_sandbox(
            tool_args,
            profile="browser",
            image=str(tool_args.get("image") or SETTINGS.browser_image),
            entrypoint=list(tool_args.get("entrypoint") or SETTINGS.browser_entrypoint),
            env=_as_string_map(tool_args.get("env")),
            current_session=current_session,
            publish_event=publish_event,
        )
        async with sandbox:
            execd_endpoint = await sandbox.get_endpoint(44772)
            vnc_endpoint = await sandbox.get_endpoint(int(tool_args.get("vnc_port") or SETTINGS.browser_vnc_port))
            devtools_endpoint = await sandbox.get_endpoint(
                int(tool_args.get("devtools_port") or SETTINGS.browser_devtools_port)
            )
            session = _set_session_endpoint(session, "execd", execd_endpoint)
            session = _set_session_endpoint(session, "vnc", vnc_endpoint)
            session = _set_session_endpoint(session, "devtools", devtools_endpoint)
            payload["endpoints"] = {
                "execd": _serialize_endpoint(execd_endpoint),
                "vnc": _serialize_endpoint(vnc_endpoint),
                "devtools": _serialize_endpoint(devtools_endpoint),
            }
            _publish(publish_event, "sandbox.endpoint", {"name": "vnc", **payload["endpoints"]["vnc"]})
            _publish(
                publish_event,
                "sandbox.endpoint",
                {"name": "devtools", **payload["endpoints"]["devtools"]},
            )
            payload["session"] = session
        return payload, session

    if tool_name == "sandbox.editor.start":
        from opensandbox.models.execd import RunCommandOpts

        sandbox, session, payload = await _create_sandbox(
            tool_args,
            profile="editor",
            image=str(tool_args.get("image") or SETTINGS.editor_image),
            entrypoint=None,
            env={
                "PYTHON_VERSION": str(tool_args.get("python_version") or SETTINGS.default_python_version),
                **_as_string_map(tool_args.get("env")),
            },
            current_session=current_session,
            publish_event=publish_event,
        )
        code_port = int(tool_args.get("port") or SETTINGS.editor_port)
        async with sandbox:
            execution = await sandbox.commands.run(
                f"code-server --bind-addr 0.0.0.0:{code_port} --auth none /workspace",
                opts=RunCommandOpts(background=True),
                handlers=_build_execution_handlers("sandbox.editor", publish_event),
            )
            endpoint = await sandbox.get_endpoint(code_port)
            session = _set_session_endpoint(session, "editor", endpoint)
            payload["command"] = _serialize_execution(execution)
            payload["endpoint"] = _serialize_endpoint(endpoint)
            payload["session"] = session
            _publish(publish_event, "sandbox.endpoint", {"name": "editor", **payload["endpoint"]})
        return payload, session

    if tool_name == "sandbox.code.start":
        sandbox, session, payload = await _create_sandbox(
            tool_args,
            profile="code",
            image=str(tool_args.get("image") or SETTINGS.code_image),
            entrypoint=list(tool_args.get("entrypoint") or SETTINGS.code_entrypoint),
            env={
                "PYTHON_VERSION": str(tool_args.get("python_version") or SETTINGS.default_python_version),
                "JAVA_VERSION": str(tool_args.get("java_version") or SETTINGS.default_java_version),
                "NODE_VERSION": str(tool_args.get("node_version") or SETTINGS.default_node_version),
                "GO_VERSION": str(tool_args.get("go_version") or SETTINGS.default_go_version),
                **_as_string_map(tool_args.get("env")),
            },
            current_session=current_session,
            publish_event=publish_event,
        )
        async with sandbox:
            endpoint = await sandbox.get_endpoint(44772)
            session = _set_session_endpoint(session, "execd", endpoint)
            payload["endpoint"] = _serialize_endpoint(endpoint)
            payload["session"] = session
        return payload, session

    if tool_name == "sandbox.session.info":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            info = await sandbox.get_info()
            session = _session_from_info(
                sandbox.id,
                str(session.get("profile") or "generic"),
                str(session.get("image") or SETTINGS.default_image),
                info,
                current_session=session,
            )
            return {"tool": tool_name, "sandbox": _serialize_info(info), "session": session}, session

    if tool_name == "sandbox.session.endpoint":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            ports_value = tool_args.get("ports")
            ports = []
            if isinstance(ports_value, list):
                ports = [int(port) for port in ports_value]
            else:
                ports = [int(_require_arg(tool_args, "port"))]
            endpoints: dict[str, Any] = {}
            for port in ports:
                endpoint = await sandbox.get_endpoint(port)
                endpoints[str(port)] = _serialize_endpoint(endpoint)
                session = _set_session_endpoint(session, str(port), endpoint)
                _publish(publish_event, "sandbox.endpoint", {"name": str(port), **endpoints[str(port)]})
            return {"tool": tool_name, "sandboxId": sandbox.id, "endpoints": endpoints, "session": session}, session

    if tool_name == "sandbox.session.renew":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            renew = await sandbox.renew(timedelta(seconds=_resolve_ttl_seconds(tool_args)))
            session = dict(session)
            session["expires_at"] = renew.expires_at.isoformat()
            session = _sanitize_session(session) or {}
            _publish(
                publish_event,
                "sandbox.lifecycle",
                {
                    "action": "renew.completed",
                    "sandboxId": sandbox.id,
                    "expiresAt": session["expires_at"],
                },
            )
            return {
                "tool": tool_name,
                "sandboxId": sandbox.id,
                "expiresAt": session["expires_at"],
                "session": session,
            }, session

    if tool_name == "sandbox.session.pause":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            await sandbox.pause()
            info = await sandbox.get_info()
            session = _session_from_info(
                sandbox.id,
                str(session.get("profile") or "generic"),
                str(session.get("image") or SETTINGS.default_image),
                info,
                current_session=session,
            )
            return {"tool": tool_name, "sandbox": _serialize_info(info), "session": session}, session

    if tool_name == "sandbox.session.resume":
        from opensandbox import Sandbox

        sandbox_id = str((current_session or {}).get("sandbox_id") or "").strip()
        if not sandbox_id:
            raise SandboxToolError(
                "No active sandbox session is bound to this thread. Create one first in the same thread_id."
            )
        sandbox = await Sandbox.resume(
            sandbox_id,
            connection_config=_build_connection_config(tool_args.get("use_server_proxy")),
            resume_timeout=timedelta(seconds=SETTINGS.connect_timeout_seconds),
            health_check_polling_interval=timedelta(milliseconds=SETTINGS.health_check_polling_interval_ms),
            skip_health_check=bool(tool_args.get("skip_health_check", False)),
        )
        async with sandbox:
            info = await sandbox.get_info()
            session = _session_from_info(
                sandbox.id,
                str((current_session or {}).get("profile") or "generic"),
                str((current_session or {}).get("image") or info.image.image if info.image else SETTINGS.default_image),
                info,
                current_session=current_session,
            )
            return {"tool": tool_name, "sandbox": _serialize_info(info), "session": session}, session

    if tool_name == "sandbox.session.kill":
        sandbox, _ = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            await sandbox.kill()
        _publish(publish_event, "sandbox.lifecycle", {"action": "kill.completed", "sandboxId": sandbox.id})
        return {"tool": tool_name, "sandboxId": sandbox.id, "status": "terminated"}, None

    if tool_name == "sandbox.command.run":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            payload = await _run_command(sandbox, tool_args, publish_event)
            payload["session"] = session
            return payload, session

    if tool_name == "sandbox.command.logs":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        execution_id = str(_require_arg(tool_args, "execution_id"))
        async with sandbox:
            logs = await sandbox.commands.get_background_command_logs(
                execution_id,
                cursor=int(tool_args["cursor"]) if tool_args.get("cursor") is not None else None,
            )
            return {
                "tool": tool_name,
                "sandboxId": sandbox.id,
                "executionId": execution_id,
                "logs": {"content": logs.content, "cursor": logs.cursor},
                "session": session,
            }, session

    if tool_name == "sandbox.filesystem.read":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        path = str(_require_arg(tool_args, "path"))
        async with sandbox:
            content = await sandbox.files.read_file(
                path,
                encoding=str(tool_args.get("encoding") or "utf-8"),
            )
            _publish(
                publish_event,
                "sandbox.filesystem.read",
                {"path": path, "bytes": len(content.encode("utf-8"))},
            )
            return {
                "tool": tool_name,
                "sandboxId": sandbox.id,
                "path": path,
                "content": content,
                "session": session,
            }, session

    if tool_name == "sandbox.filesystem.write":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            entries = tool_args.get("entries")
            if isinstance(entries, list):
                from opensandbox.models.filesystem import WriteEntry

                write_entries = [
                    WriteEntry(
                        path=str(item["path"]),
                        data=item.get("data"),
                        mode=int(item.get("mode", 755)),
                        owner=item.get("owner"),
                        group=item.get("group"),
                        encoding=str(item.get("encoding", "utf-8")),
                    )
                    for item in entries
                    if isinstance(item, dict) and item.get("path")
                ]
                await sandbox.files.write_files(write_entries)
                written_paths = [entry.path for entry in write_entries]
            else:
                path = str(_require_arg(tool_args, "path"))
                await sandbox.files.write_file(
                    path,
                    tool_args.get("data", ""),
                    encoding=str(tool_args.get("encoding") or "utf-8"),
                    mode=int(tool_args.get("mode", 755)),
                    owner=tool_args.get("owner"),
                    group=tool_args.get("group"),
                )
                written_paths = [path]
            _publish(publish_event, "sandbox.filesystem.write", {"paths": written_paths})
            return {
                "tool": tool_name,
                "sandboxId": sandbox.id,
                "writtenPaths": written_paths,
                "session": session,
            }, session

    if tool_name == "sandbox.filesystem.delete":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        paths = _normalize_paths(_require_arg(tool_args, "paths"))
        async with sandbox:
            if bool(tool_args.get("directories", False)):
                await sandbox.files.delete_directories(paths)
            else:
                await sandbox.files.delete_files(paths)
            _publish(publish_event, "sandbox.filesystem.delete", {"paths": paths})
            return {"tool": tool_name, "sandboxId": sandbox.id, "deletedPaths": paths, "session": session}, session

    if tool_name == "sandbox.filesystem.mkdir":
        from opensandbox.models.filesystem import WriteEntry

        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        paths = _normalize_paths(_require_arg(tool_args, "paths"))
        entries = [WriteEntry(path=path, mode=int(tool_args.get("mode", 755))) for path in paths]
        async with sandbox:
            await sandbox.files.create_directories(entries)
            _publish(publish_event, "sandbox.filesystem.mkdir", {"paths": paths})
            return {"tool": tool_name, "sandboxId": sandbox.id, "createdPaths": paths, "session": session}, session

    if tool_name == "sandbox.filesystem.search":
        from opensandbox.models.filesystem import SearchEntry

        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            results = await sandbox.files.search(
                SearchEntry(
                    path=str(_require_arg(tool_args, "path")),
                    pattern=str(_require_arg(tool_args, "pattern")),
                )
            )
            results_payload = [_serialize_entry_info(item) for item in results]
            return {"tool": tool_name, "sandboxId": sandbox.id, "results": results_payload, "session": session}, session

    if tool_name == "sandbox.filesystem.info":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        paths = _normalize_paths(_require_arg(tool_args, "paths"))
        async with sandbox:
            info_map = await sandbox.files.get_file_info(paths)
            payload = {path: _serialize_entry_info(info) for path, info in info_map.items()}
            return {"tool": tool_name, "sandboxId": sandbox.id, "files": payload, "session": session}, session

    if tool_name == "sandbox.metrics.get":
        sandbox, session = await _connect_existing_sandbox(current_session, tool_args, publish_event)
        async with sandbox:
            metrics = await sandbox.get_metrics()
            payload = _serialize_metrics(metrics)
            _publish(publish_event, "sandbox.metrics", {"sandboxId": sandbox.id, "metrics": payload})
            return {"tool": tool_name, "sandboxId": sandbox.id, "metrics": payload, "session": session}, session

    if tool_name == "sandbox.code.context.create":
        from code_interpreter import CodeInterpreter, SupportedLanguage

        sandbox, session = await _connect_existing_sandbox(
            current_session,
            tool_args,
            publish_event,
            auto_create_profile="code",
        )
        language = str(tool_args.get("language") or SupportedLanguage.PYTHON)
        async with sandbox:
            interpreter = await CodeInterpreter.create(sandbox)
            context = await interpreter.codes.create_context(language)
            contexts = dict(session.get("code_contexts") or {})
            contexts[language] = context.id
            session = dict(session)
            session["code_contexts"] = contexts
            session = _sanitize_session(session) or {}
            payload = {
                "tool": tool_name,
                "sandboxId": sandbox.id,
                "language": language,
                "contextId": context.id,
                "session": session,
            }
            _publish(
                publish_event,
                "sandbox.code.context",
                {
                    "action": "create",
                    "language": language,
                    "contextId": context.id,
                },
            )
            return payload, session

    if tool_name == "sandbox.code.context.delete":
        from code_interpreter import CodeInterpreter

        sandbox, session = await _connect_existing_sandbox(
            current_session,
            tool_args,
            publish_event,
            auto_create_profile="code",
        )
        context_id = str(tool_args.get("context_id") or "").strip()
        language = str(tool_args.get("language") or "").strip()
        if not context_id and not language:
            raise SandboxToolError("context_id or language is required to delete code context")
        async with sandbox:
            interpreter = await CodeInterpreter.create(sandbox)
            if context_id:
                await interpreter.codes.delete_context(context_id)
            else:
                await interpreter.codes.delete_contexts(language)
            contexts = dict(session.get("code_contexts") or {})
            if context_id:
                contexts = {key: value for key, value in contexts.items() if value != context_id}
            elif language:
                contexts.pop(language, None)
            session = dict(session)
            session["code_contexts"] = contexts
            session = _sanitize_session(session) or {}
            payload = {
                "tool": tool_name,
                "sandboxId": sandbox.id,
                "contextId": context_id or None,
                "language": language or None,
                "session": session,
            }
            _publish(
                publish_event,
                "sandbox.code.context",
                {"action": "delete", "contextId": context_id or None, "language": language or None},
            )
            return payload, session

    if tool_name == "sandbox.code.run":
        sandbox, session = await _connect_existing_sandbox(
            current_session,
            tool_args,
            publish_event,
            auto_create_profile="code",
        )
        payload, session = await _run_code(sandbox, session, tool_args, publish_event)
        payload["session"] = session
        return payload, session

    raise SandboxToolError(f"Unsupported sandbox tool '{tool_name}'")
