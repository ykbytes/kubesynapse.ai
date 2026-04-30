from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator


WORKSPACE_DIR = Path(os.getenv("VIBE_WORKDIR", "/workspace")).resolve()
STATE_DIR = Path(os.getenv("VIBE_HOME", "/app/state/home/.vibe")).resolve()
DEFAULT_MODEL_ALIAS = (os.getenv("VIBE_ACTIVE_MODEL") or "devstral-small").strip() or "devstral-small"
DEFAULT_SYSTEM_PROMPT = (os.getenv("VIBE_SYSTEM_PROMPT") or "").strip()
VIBE_BIN = os.getenv("VIBE_BIN", "/opt/venv/bin/vibe")


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=16000)
    thread_id: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=255)
    system: str | None = Field(default=None, max_length=32000)
    no_session: bool = False
    max_turns: int | None = Field(default=None, ge=1, le=1000)
    working_directory: str | None = Field(default=None, max_length=512)
    output_format: str | None = Field(default=None, max_length=32)
    output_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_request(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.working_directory = self.working_directory.strip() or None if self.working_directory is not None else None
        self.output_format = self.output_format.strip().lower() or None if self.output_format is not None else None
        if not self.prompt:
            raise ValueError("prompt must not be blank")
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    continuity: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


app = FastAPI(title="KubeSynapse Mistral Vibe Runtime", version="0.1.0")


def _resolve_workdir(raw_value: str | None) -> Path:
    if not raw_value:
        return WORKSPACE_DIR
    candidate = (WORKSPACE_DIR / raw_value).resolve() if not Path(raw_value).is_absolute() else Path(raw_value).resolve()
    if WORKSPACE_DIR != candidate and WORKSPACE_DIR not in candidate.parents:
        raise HTTPException(status_code=400, detail=f"working_directory '{raw_value}' must stay inside /workspace")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"working_directory '{raw_value}' does not exist")
    return candidate


def _extract_assistant_response(messages: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(messages, list):
        return ("", [])
    response_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() == "assistant":
            content = str(message.get("content") or "").strip()
            if content:
                response_parts.append(content)
            raw_tool_calls = message.get("tool_calls")
            if isinstance(raw_tool_calls, list):
                for tool_call in raw_tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                    tool_calls.append(
                        {
                            "tool": str(function.get("name") or "tool"),
                            "status": "completed",
                            "input": function.get("arguments"),
                        }
                    )
    return ("\n\n".join(part for part in response_parts if part).strip(), tool_calls)


def _run_vibe(request: InvokeRequest) -> InvokeResponse:
    workdir = _resolve_workdir(request.working_directory)
    env = os.environ.copy()
    env.setdefault("VIBE_HOME", str(STATE_DIR))
    env.setdefault("HOME", str(STATE_DIR.parent))
    env.setdefault("MISTRAL_API_KEY", os.getenv("MISTRAL_API_KEY", ""))
    env["VIBE_ACTIVE_MODEL"] = request.model or DEFAULT_MODEL_ALIAS

    prompt = request.prompt
    system_prompt = request.system or DEFAULT_SYSTEM_PROMPT
    if system_prompt:
        prompt = f"[System Instructions]\n{system_prompt}\n\n[User Request]\n{prompt}"

    cmd = [VIBE_BIN, "--prompt", prompt, "--output", "json"]
    if request.max_turns:
        cmd.extend(["--max-turns", str(request.max_turns)])

    process = subprocess.run(
        cmd,
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=float(os.getenv("VIBE_MODEL_TIMEOUT_SECONDS", "300")),
    )

    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    if process.returncode != 0:
        raise HTTPException(status_code=502, detail=stderr or stdout or f"vibe exited with code {process.returncode}")

    try:
        messages = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse vibe JSON output: {exc}") from exc

    response_text, tool_calls = _extract_assistant_response(messages)
    if not response_text and not tool_calls:
        response_text = "Invocation completed."

    return InvokeResponse(
        thread_id=request.thread_id or f"vibe-{uuid.uuid4().hex[:12]}",
        response=response_text,
        model=request.model or DEFAULT_MODEL_ALIAS,
        status="completed",
        tool_calls=tool_calls,
        metadata={
            "runtime": "mistral-vibe",
            "raw_message_count": len(messages) if isinstance(messages, list) else 0,
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if not Path(VIBE_BIN).exists():
        raise HTTPException(status_code=503, detail="vibe binary not found")
    return {"status": "ready"}


@app.post("/invoke")
def invoke(request: InvokeRequest) -> JSONResponse:
    response = _run_vibe(request)
    return JSONResponse(response.model_dump(mode="json"))


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    async def event_stream() -> Any:
        yield 'event: response.turn_started\ndata: {"turn":1,"agent":"mistral-vibe"}\n\n'
        try:
            response = await asyncio.to_thread(_run_vibe, request)
        except HTTPException as exc:
            payload = json.dumps({"error": str(exc.detail)})
            yield f"event: response.error\ndata: {payload}\n\n"
            return

        if response.response:
            payload = json.dumps({"delta": response.response})
            yield f"event: response.delta\ndata: {payload}\n\n"
        for tool_call in response.tool_calls:
            payload = json.dumps(tool_call)
            yield f"event: response.tool_call\ndata: {payload}\n\n"
        yield f"event: response.turn_completed\ndata: {json.dumps({'status': response.status, 'response_length': len(response.response)})}\n\n"
        yield f"event: response.completed\ndata: {json.dumps(response.model_dump(mode='json'))}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/abort")
def abort() -> dict[str, bool]:
    return {"ok": True}


@app.post("/cancel")
def cancel() -> dict[str, bool]:
    return {"ok": True}


def _handle_signal(_signum: int, _frame: Any) -> None:
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)
