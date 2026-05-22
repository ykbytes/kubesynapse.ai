"""Enhanced HTTP client with retry, pagination, and streaming support."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agentctl.config import ResolvedSettings


class ApiError(RuntimeError):
    """API request failure with optional HTTP status code."""

    def __init__(self, message: str, status_code: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ApiClient:
    """Synchronous HTTP client wrapping httpx with retry, error extraction, and SSE parsing."""

    def __init__(self, settings: ResolvedSettings) -> None:
        headers: dict[str, str] = {"Accept": "application/json"}
        if settings.token:
            headers["Authorization"] = f"Bearer {settings.token}"
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.gateway_url.rstrip("/"),
            headers=headers,
            timeout=settings.timeout,
            follow_redirects=True,
            trust_env=False,
        )

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def close(self) -> None:
        self._client.close()

    # ─── Core request methods ───

    @retry(
        retry=retry_if_exception_type(httpx.TimeoutException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        reraise=True,
    )
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        data: Any = None,
    ) -> Any:
        """Make a JSON request with automatic retry on timeout."""
        try:
            kwargs: dict[str, Any] = {"params": params}
            if payload is not None:
                kwargs["json"] = payload
            elif data is not None:
                kwargs["content"] = data
                kwargs["headers"] = {"Content-Type": "application/octet-stream"}
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise
        except httpx.HTTPError as exc:
            raise ApiError(f"Connection failed: {exc}") from exc
        self._raise_for_status(response)
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, params=params, payload=payload)

    def put(self, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> Any:
        return self.request("PUT", path, params=params, payload=payload)

    def patch(self, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> Any:
        return self.request("PATCH", path, params=params, payload=payload)

    def delete(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("DELETE", path, params=params)

    # ─── Streaming ───

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Open a streaming response (for SSE)."""
        return self._client.stream(method, path, params=params, json=payload)

    def iter_sse(self, response: httpx.Response) -> Generator[dict[str, str], None, None]:
        """Parse Server-Sent Events from a streaming response."""
        event_type = ""
        data_lines: list[str] = []

        for line in response.iter_lines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line == "" and data_lines:
                yield {"event": event_type, "data": "\n".join(data_lines)}
                event_type = ""
                data_lines = []

        # Flush any remaining event
        if data_lines:
            yield {"event": event_type, "data": "\n".join(data_lines)}

    # ─── Pagination ───

    def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int = 100,
        max_pages: int = 50,
    ) -> list[Any]:
        """Fetch all pages of a paginated endpoint."""
        all_items: list[Any] = []
        params = dict(params or {})
        params["limit"] = page_size
        offset = 0

        for _ in range(max_pages):
            params["offset"] = offset
            result = self.get(path, params=params)
            if isinstance(result, list):
                all_items.extend(result)
                if len(result) < page_size:
                    break
                offset += page_size
            elif isinstance(result, dict):
                items = result.get("items") or result.get("results") or []
                all_items.extend(items)
                if len(items) < page_size:
                    break
                offset += page_size
            else:
                break

        return all_items

    # ─── Error handling ───

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return

        message = response.text.strip() or response.reason_phrase or "Unknown error"
        detail = None
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            payload = None

        if isinstance(payload, dict):
            detail = payload
            raw_detail = payload.get("detail")
            if isinstance(raw_detail, str) and raw_detail.strip():
                message = raw_detail.strip()
            elif isinstance(raw_detail, list):
                # Pydantic validation errors
                parts = []
                for err in raw_detail:
                    loc = " -> ".join(str(x) for x in (err.get("loc") or []))
                    msg = err.get("msg", "")
                    parts.append(f"  {loc}: {msg}" if loc else f"  {msg}")
                message = "Validation error:\n" + "\n".join(parts)
            else:
                message = json.dumps(payload, indent=2)

        raise ApiError(message, status_code=response.status_code, detail=detail)
