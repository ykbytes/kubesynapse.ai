from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator


def get_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return max(default, minimum)
    try:
        return max(int(raw_value), minimum)
    except ValueError:
        return max(default, minimum)


def get_float_env(name: str, default: float, *, minimum: float = 0.1) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return max(default, minimum)
    try:
        return max(float(raw_value), minimum)
    except ValueError:
        return max(default, minimum)


logging.basicConfig(
    level=os.getenv("GOOSE_RUNTIME_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("goose-runtime")

SERVICE_NAME = os.getenv("AGENT_NAME", "goose-runtime")
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default")
DEFAULT_MODEL = os.getenv("GOOSE_MODEL", os.getenv("AGENT_MODEL", "gpt-4"))
DEFAULT_PROVIDER = os.getenv("GOOSE_PROVIDER", "litellm").strip() or "litellm"
DEFAULT_SYSTEM_PROMPT = os.getenv("GOOSE_SYSTEM_PROMPT", os.getenv("AGENT_SYSTEM_PROMPT", "")).strip()
GOOSE_BINARY = os.getenv("GOOSE_BIN", "goose").strip() or "goose"
GOOSE_WORKDIR = os.getenv("GOOSE_WORKDIR", "/workspace").strip() or "/workspace"
HOME_DIR = os.getenv("HOME", "/app/state/home").strip() or "/app/state/home"
XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", f"{HOME_DIR}/.config").strip() or f"{HOME_DIR}/.config"
XDG_DATA_HOME = os.getenv("XDG_DATA_HOME", f"{HOME_DIR}/.local/share").strip() or f"{HOME_DIR}/.local/share"
MAX_PROMPT_CHARS = get_int_env("GOOSE_MAX_PROMPT_CHARS", 12000)
MAX_THREAD_ID_CHARS = get_int_env("GOOSE_MAX_THREAD_ID_CHARS", 128)
MAX_MODEL_CHARS = get_int_env("GOOSE_MAX_MODEL_CHARS", 128)
COMMAND_TIMEOUT_SECONDS = get_float_env("GOOSE_COMMAND_TIMEOUT_SECONDS", 600.0)


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    require_approval: bool = False
    approval_action: str | None = Field(default=None, max_length=512)
    tool_name: str = Field(default="", max_length=128)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_request(self) -> "InvokeRequest":
        if not self.prompt.strip():
            raise ValueError("prompt must not be blank")
        if self.require_approval:
            raise ValueError("goose runtime does not support require_approval yet")
        if self.tool_name.strip():
            raise ValueError("goose runtime does not support direct tool_name execution yet")
        if (self.mcp_server or "").strip():
            raise ValueError("goose runtime does not support gateway-routed mcp_server execution yet")
        if self.sandbox_session is not None:
            raise ValueError("goose runtime does not support sandbox_session continuity")
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    warnings: list[str] = Field(default_factory=list)


app = FastAPI(
    title="Goose Runtime Adapter",
    description="HTTP adapter that exposes Goose as an agent runtime behind the sandbox gateway",
    version="0.1.0",
)


def ensure_runtime_directories() -> None:
    for path in (GOOSE_WORKDIR, HOME_DIR, XDG_CONFIG_HOME, XDG_DATA_HOME, "/app/state"):
        os.makedirs(path, exist_ok=True)


@app.on_event("startup")
async def on_startup() -> None:
    ensure_runtime_directories()
    if shutil.which(GOOSE_BINARY) is None:
        raise RuntimeError(f"goose binary '{GOOSE_BINARY}' is not available on PATH")


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def truncate_text(value: str, limit: int = 1200) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


def normalize_session_name(thread_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in thread_id.strip())
    normalized = normalized.strip("-")
    return normalized or str(uuid.uuid4())


def combined_error_text(stdout_text: str, stderr_text: str) -> str:
    parts = [part.strip() for part in (stderr_text, stdout_text) if part.strip()]
    return "\n".join(parts).strip()


def session_not_found(stdout_text: str, stderr_text: str) -> bool:
    combined = combined_error_text(stdout_text, stderr_text).lower()
    return "no session found" in combined


def build_goose_environment(model: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": HOME_DIR,
            "XDG_CONFIG_HOME": XDG_CONFIG_HOME,
            "XDG_DATA_HOME": XDG_DATA_HOME,
            "GOOSE_PROVIDER": DEFAULT_PROVIDER,
            "GOOSE_MODEL": model,
        }
    )
    return env


def build_goose_run_command(
    *,
    prompt: str,
    model: str,
    session_name: str,
    output_format: str,
    resume: bool,
) -> list[str]:
    command = [
        GOOSE_BINARY,
        "run",
        "--name",
        session_name,
        "--text",
        prompt,
        "--provider",
        DEFAULT_PROVIDER,
        "--model",
        model,
        "--output-format",
        output_format,
    ]
    if DEFAULT_SYSTEM_PROMPT:
        command.extend(["--system", DEFAULT_SYSTEM_PROMPT])
    if resume:
        command.append("--resume")
    return command


async def execute_goose_json(
    *,
    prompt: str,
    model: str,
    session_name: str,
    allow_resume: bool,
) -> dict[str, Any]:
    attempts = [True, False] if allow_resume else [False]

    for resume in attempts:
        command = build_goose_run_command(
            prompt=prompt,
            model=model,
            session_name=session_name,
            output_format="json",
            resume=resume,
        )
        logger.info("Running Goose command for %s in %s", SERVICE_NAME, GOOSE_WORKDIR)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=GOOSE_WORKDIR,
            env=build_goose_environment(model),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=COMMAND_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise HTTPException(status_code=504, detail="Goose runtime timed out") from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode == 0:
            try:
                return json.loads(stdout_text)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Goose returned non-JSON output: {truncate_text(stdout_text)}",
                ) from exc

        if resume and session_not_found(stdout_text, stderr_text):
            logger.info("Goose session '%s' was not found, retrying without resume", session_name)
            continue

        raise HTTPException(
            status_code=502,
            detail=f"Goose invocation failed: {truncate_text(combined_error_text(stdout_text, stderr_text) or 'unknown error')}",
        )

    raise HTTPException(status_code=500, detail="Goose invocation failed before a session could be created")


def message_role(message: dict[str, Any]) -> str:
    role = message.get("role") or message.get("sender") or message.get("author") or ""
    return str(role).strip().lower()


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "body"):
            if key in value:
                text = extract_text(value.get(key))
                if text:
                    return text
    return ""


def extract_latest_assistant_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message_role(message) != "assistant":
            continue
        content = extract_text(message.get("content"))
        if content:
            return content
    return ""


async def stream_goose_events(
    *,
    prompt: str,
    model: str,
    session_name: str,
    thread_id: str,
    allow_resume: bool,
) -> AsyncIterator[str]:
    attempts = [True, False] if allow_resume else [False]

    for resume in attempts:
        command = build_goose_run_command(
            prompt=prompt,
            model=model,
            session_name=session_name,
            output_format="stream-json",
            resume=resume,
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=GOOSE_WORKDIR,
            env=build_goose_environment(model),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(process.stderr.read() if process.stderr else asyncio.sleep(0, result=b""))
        assistant_text = ""
        saw_output = False

        try:
            async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
                while True:
                    line = await process.stdout.readline() if process.stdout else b""
                    if not line:
                        break
                    payload = line.decode("utf-8", errors="replace").strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON Goose stream line: %s", payload)
                        continue

                    saw_output = True
                    event_type = str(event.get("type", "")).strip().lower()

                    if event_type == "message":
                        message = event.get("message") or {}
                        if not isinstance(message, dict) or message_role(message) != "assistant":
                            continue
                        next_text = extract_text(message.get("content"))
                        if not next_text:
                            continue
                        delta = next_text[len(assistant_text):] if next_text.startswith(assistant_text) else next_text
                        assistant_text = next_text
                        if delta:
                            yield sse_event(
                                "response.delta",
                                {
                                    "thread_id": thread_id,
                                    "delta": delta,
                                    "source": "goose",
                                },
                            )
                        continue

                    if event_type == "notification":
                        yield sse_event(
                            "goose.notification",
                            {
                                "thread_id": thread_id,
                                "extension_id": event.get("extension_id"),
                                "message": event.get("message"),
                                "data": event.get("data"),
                            },
                        )
                        continue

                    if event_type == "model_change":
                        yield sse_event(
                            "goose.model_change",
                            {
                                "thread_id": thread_id,
                                "model": event.get("model") or model,
                                "mode": event.get("mode"),
                            },
                        )
                        continue

                    if event_type == "error":
                        error_text = str(event.get("error") or "Goose invocation failed")
                        yield sse_event(
                            "response.error",
                            {
                                "thread_id": thread_id,
                                "error": error_text,
                            },
                        )
        except TimeoutError:
            process.kill()
            await process.wait()
            yield sse_event(
                "response.error",
                {
                    "thread_id": thread_id,
                    "error": "Goose runtime timed out",
                },
            )
            return
        except asyncio.CancelledError:
            process.kill()
            raise
        finally:
            await process.wait()
            stderr_bytes = await stderr_task

        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode == 0:
            yield sse_event(
                "response.completed",
                {
                    "thread_id": thread_id,
                    "response": assistant_text,
                    "model": model,
                    "status": "completed",
                    "warnings": [],
                },
            )
            return

        if resume and session_not_found("", stderr_text) and not saw_output:
            logger.info("Goose session '%s' was not found during stream startup, retrying without resume", session_name)
            continue

        yield sse_event(
            "response.error",
            {
                "thread_id": thread_id,
                "error": truncate_text(stderr_text or "Goose invocation failed"),
            },
        )
        return


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "runtime": "goose",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": DEFAULT_PROVIDER,
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {
        "status": "ready",
        "runtime": "goose",
        "goose_binary": GOOSE_BINARY,
    }


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    model = (request.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    thread_id = request.thread_id or str(uuid.uuid4())
    session_name = normalize_session_name(thread_id)
    payload = await execute_goose_json(
        prompt=request.prompt,
        model=model,
        session_name=session_name,
        allow_resume=bool(request.thread_id),
    )
    messages = payload.get("messages") if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []

    response_text = extract_latest_assistant_text([item for item in messages if isinstance(item, dict)])
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    status = "completed"
    if isinstance(metadata, dict):
        status = str(metadata.get("status") or "completed")

    return InvokeResponse(
        thread_id=thread_id,
        response=response_text,
        model=model,
        status=status,
        warnings=[],
    )


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    model = (request.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    allow_resume = bool(request.thread_id)
    thread_id = request.thread_id or str(uuid.uuid4())
    session_name = normalize_session_name(thread_id)

    async def event_generator() -> AsyncIterator[str]:
        async for event in stream_goose_events(
            prompt=request.prompt,
            model=model,
            session_name=session_name,
            thread_id=thread_id,
            allow_resume=allow_resume,
        ):
            yield event

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)