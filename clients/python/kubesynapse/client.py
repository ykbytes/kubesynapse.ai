"""kubesynapse API client — idiomatic Python SDK.

Usage:
    from kubesynapse import KubeSynapseClient

    async with KubeSynapseClient("http://localhost:8080") as client:
        health = await client.health()
        agents = await client.list_agents()
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from .models import (
    Agent,
    AgentCreate,
    AgentList,
    AgentPolicy,
    AgentWorkflow,
    AgentWorkflowCreate,
    ExecutionDetailResponse,
    ExecutionListResponse,
    HealthStatus,
)


class KubeSynapseError(Exception):
    """Raised when the kubesynapse API returns an error."""

    def __init__(self, status_code: int, message: str, detail: dict | None = None) -> None:
        self.status_code = status_code
        self.message = message
        self.detail = detail
        super().__init__(f"[{status_code}] {message}")

    @classmethod
    def from_response(cls, response: httpx.Response) -> KubeSynapseError:
        try:
            body = response.json()
            message = body.get("message", response.text)
            detail = body.get("detail")
        except Exception:
            message = response.text
            detail = None
        return cls(response.status_code, message, detail)


class KubeSynapseClient:
    """Async HTTP client for the kubesynapse API gateway.

    All endpoints are under /api/v1/ (versioned API).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    # ── Context Manager ────────────────────────────────────────────

    async def __aenter__(self) -> KubeSynapseClient:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._headers(),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()
        self._client = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self._headers(),
            )

        response = await self._client.request(method, path, **kwargs)
        if response.is_error:
            raise KubeSynapseError.from_response(response)
        if response.status_code == 204:
            return None
        return response.json()

    # ── Health ─────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        """Get API gateway health status."""
        data = await self._request("GET", "/api/v1/health")
        return HealthStatus(**data)

    async def ready(self) -> dict:
        """Check if the API gateway is ready to serve traffic."""
        return await self._request("GET", "/api/v1/ready")

    async def health_db(self) -> dict:
        """Check database connectivity."""
        return await self._request("GET", "/api/v1/health/db")

    # ── Agents ─────────────────────────────────────────────────────

    async def create_agent(self, agent: AgentCreate) -> Agent:
        """Create a new AIAgent."""
        data = await self._request(
            "POST", "/api/v1/agents",
            json=agent.model_dump(exclude_none=True),
        )
        return Agent(**data)

    async def get_agent(self, name: str, namespace: str = "kubesynapse") -> Agent:
        """Get an agent by name and namespace."""
        data = await self._request(
            "GET", f"/api/v1/agents/{namespace}/{name}"
        )
        return Agent(**data)

    async def list_agents(
        self,
        namespace: str = "kubesynapse",
        page: int = 1,
        page_size: int = 20,
    ) -> AgentList:
        """List agents with pagination."""
        data = await self._request(
            "GET", "/api/v1/agents",
            params={"namespace": namespace, "page": page, "page_size": page_size},
        )
        return AgentList(**data)

    async def delete_agent(self, name: str, namespace: str = "kubesynapse") -> None:
        """Delete an agent."""
        await self._request("DELETE", f"/api/v1/agents/{namespace}/{name}")

    # ── Workflows ──────────────────────────────────────────────────

    async def create_workflow(self, workflow: AgentWorkflowCreate) -> AgentWorkflow:
        """Create and start an AgentWorkflow."""
        data = await self._request(
            "POST", "/api/v1/workflows",
            json=workflow.model_dump(exclude_none=True),
        )
        return AgentWorkflow(**data)

    async def get_workflow(
        self, name: str, namespace: str = "kubesynapse"
    ) -> AgentWorkflow:
        """Get workflow status and results."""
        data = await self._request(
            "GET", f"/api/v1/workflows/{namespace}/{name}"
        )
        return AgentWorkflow(**data)

    async def list_workflows(
        self,
        namespace: str = "kubesynapse",
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[AgentWorkflow]:
        """List workflows with optional status filter."""
        params: dict[str, Any] = {
            "namespace": namespace,
            "page": page,
            "page_size": page_size,
        }
        if status:
            params["status"] = status
        data = await self._request("GET", "/api/v1/workflows", params=params)
        return [AgentWorkflow(**item) for item in data.get("items", data)]

    async def cancel_workflow(
        self, name: str, namespace: str = "kubesynapse"
    ) -> AgentWorkflow:
        """Cancel a running workflow."""
        data = await self._request(
            "POST", f"/api/v1/workflows/{namespace}/{name}/cancel"
        )
        return AgentWorkflow(**data)

    # ── Policies ───────────────────────────────────────────────────

    async def get_policy(self, name: str, namespace: str = "kubesynapse") -> AgentPolicy:
        """Get an AgentPolicy."""
        data = await self._request(
            "GET", f"/api/v1/policies/{namespace}/{name}"
        )
        return AgentPolicy(**data)

    async def list_policies(
        self, namespace: str = "kubesynapse"
    ) -> list[AgentPolicy]:
        """List all agent policies."""
        data = await self._request(
            "GET", "/api/v1/policies",
            params={"namespace": namespace},
        )
        return [AgentPolicy(**item) for item in data.get("items", data)]

    # ── Observability ──────────────────────────────────────────────

    async def list_executions(
        self,
        workflow_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ExecutionListResponse:
        """List workflow executions from the Execution Observatory."""
        params: dict[str, Any] = {"limit": limit}
        if workflow_name:
            params["workflow_name"] = workflow_name
        if offset:
            params["offset"] = offset
        data = await self._request("GET", "/api/v1/traces/executions", params=params)
        return ExecutionListResponse(**data)

    async def get_execution(self, execution_id: str) -> ExecutionDetailResponse:
        """Get a specific execution from the Execution Observatory."""
        data = await self._request("GET", f"/api/v1/traces/executions/{execution_id}")
        return ExecutionDetailResponse(**data)

    async def list_traces(
        self,
        workflow_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ExecutionListResponse:
        """Deprecated wrapper for list_executions()."""
        return await self.list_executions(workflow_name=workflow_name, limit=limit, offset=offset)

    async def get_trace(self, trace_id: str) -> ExecutionDetailResponse:
        """Deprecated wrapper for get_execution()."""
        return await self.get_execution(trace_id)


# ── Convenience sync wrapper ───────────────────────────────────────
# For users who can't use async/await, wrap in a sync context manager.

class SyncKubeSynapseClient:
    """Synchronous wrapper around KubeSynapseClient.

    Usage:
        client = SyncKubeSynapseClient("http://localhost:8080")
        agents = client.list_agents()
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._token = token
        self._timeout = timeout

    def _run(self, coro: Any) -> Any:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)

        return asyncio.run(coro)

    def __getattr__(self, name: str) -> Any:
        async_client = KubeSynapseClient(
            base_url=self._base_url,
            token=self._token,
            timeout=self._timeout,
        )
        async_method = getattr(async_client, name)

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return self._run(async_method(*args, **kwargs))

        return sync_wrapper
