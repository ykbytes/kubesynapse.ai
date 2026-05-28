"""Dynamic model discovery and routing for agent invokes.

Discovers available models from LiteLLM at startup and on a refresh interval.
Provides model fallback chains and health scoring for resilient LLM routing.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from constants import LITELLM_INTERNAL_URL, LITELLM_MASTER_KEY

logger = logging.getLogger("api-gateway.model_router")


@dataclass
class ModelHealth:
    """Health metrics for a discovered model."""

    model_id: str
    total_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    last_error: str | None = None
    last_error_at: float = 0.0

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    @property
    def is_healthy(self) -> bool:
        if self.total_requests < 5:
            return True
        return self.error_rate < 0.5

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.total_latency_ms += latency_ms

    def record_failure(self, error: str) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.last_error = error
        self.last_error_at = time.monotonic()


class ModelRegistry:
    """Discovers and tracks available LLM models from LiteLLM.

    Queries LiteLLM /v1/models on startup and periodically refreshes.
    Maintains per-model health metrics for intelligent fallback routing.
    """

    def __init__(
        self,
        litellm_url: str = LITELLM_INTERNAL_URL,
        master_key: str = LITELLM_MASTER_KEY,
        refresh_interval: float = 300.0,
    ) -> None:
        self._litellm_url = litellm_url.rstrip("/")
        self._master_key = master_key
        self._refresh_interval = refresh_interval
        self._models: list[str] = []
        self._health: dict[str, ModelHealth] = {}
        self._last_refresh: float = 0.0
        self._refresh_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the model discovery service."""
        await self._refresh_models()
        self._refresh_task = asyncio.create_task(self._periodic_refresh())
        logger.info("Model registry started with %d models", len(self._models))

    async def stop(self) -> None:
        """Stop the periodic refresh task."""
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

    async def get_models(self) -> list[str]:
        """Get the list of available model IDs."""
        async with self._lock:
            if not self._models:
                await self._refresh_models()
            return list(self._models)

    async def is_model_available(self, model_id: str) -> bool:
        """Check if a specific model is available."""
        models = await self.get_models()
        return model_id in models

    async def get_fallback_chain(self, requested_model: str) -> list[str]:
        """Get a fallback chain for a model, ordered by health and provider.

        Always returns the requested model first. When the requested model
        includes a provider prefix (e.g. ``litellm/gpt-5-mini``), the base
        name (``gpt-5-mini``) is used to match against the LiteLLM model
        list so that provider-prefixed agent models always resolve correctly.

        Fallback models are organized by provider: models from the same
        provider as the requested model are preferred over cross-provider
        alternatives.
        """
        models = await self.get_models()
        if not models:
            return [requested_model]

        stripped = requested_model.split("/", 1)[-1] if "/" in requested_model else requested_model
        provider = requested_model.split("/", 1)[0] if "/" in requested_model else ""

        same_provider: list[str] = []
        cross_provider: list[str] = []

        for m in models:
            if m in (requested_model, stripped):
                continue
            health = self._health.get(m)
            is_healthy = health.is_healthy if health else True
            if not is_healthy:
                continue
            if provider and (m.startswith(f"{provider}/") or m == stripped):
                same_provider.append(m)
            else:
                cross_provider.append(m)

        fallback: list[str] = [requested_model]
        fallback.extend(same_provider)
        fallback.extend(cross_provider)
        return fallback

    def record_model_success(self, model_id: str, latency_ms: float) -> None:
        """Record a successful model invocation."""
        health = self._health.setdefault(model_id, ModelHealth(model_id=model_id))
        health.record_success(latency_ms)

    def record_model_failure(self, model_id: str, error: str) -> None:
        """Record a failed model invocation."""
        health = self._health.setdefault(model_id, ModelHealth(model_id=model_id))
        health.record_failure(error)

    async def get_model_health_summary(self) -> dict[str, dict[str, Any]]:
        """Get health summary for all models."""
        async with self._lock:
            return {
                m: {
                    "total_requests": h.total_requests,
                    "failed_requests": h.failed_requests,
                    "error_rate": round(h.error_rate, 4),
                    "avg_latency_ms": round(h.avg_latency_ms, 1),
                    "is_healthy": h.is_healthy,
                    "last_error": h.last_error,
                }
                for m, h in self._health.items()
            }

    async def _refresh_models(self) -> None:
        """Fetch available models from LiteLLM."""
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                if not hasattr(client, "get"):
                    logger.debug("Skipping LiteLLM model refresh; AsyncClient has no GET support")
                    return
                headers = {}
                if self._master_key:
                    headers["Authorization"] = f"Bearer {self._master_key}"
                response = await client.get(
                    f"{self._litellm_url}/v1/models",
                    headers=headers,
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m["id"] for m in data.get("data", [])]
                    async with self._lock:
                        old_models = set(self._models)
                        new_models = set(models)
                        self._models = models
                        self._last_refresh = time.monotonic()
                        if old_models != new_models:
                            added = new_models - old_models
                            removed = old_models - new_models
                            if added:
                                logger.info("New models discovered: %s", ", ".join(sorted(added)))
                            if removed:
                                logger.warning("Models removed: %s", ", ".join(sorted(removed)))
                else:
                    logger.warning("LiteLLM returned %d when fetching models", response.status_code)
        except Exception as exc:
            logger.error("Failed to refresh models from LiteLLM: %s", exc)

    async def _periodic_refresh(self) -> None:
        """Periodically refresh the model list."""
        while True:
            await asyncio.sleep(self._refresh_interval)
            try:
                await self._refresh_models()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Model refresh error: %s", exc)


_model_registry = ModelRegistry()


async def start_model_registry() -> None:
    """Start the global model registry."""
    await _model_registry.start()


async def stop_model_registry() -> None:
    """Stop the global model registry."""
    await _model_registry.stop()


async def get_available_models() -> list[str]:
    """Get the list of available model IDs."""
    return await _model_registry.get_models()


async def get_fallback_chain(requested_model: str) -> list[str]:
    """Get a fallback chain for a model."""
    return await _model_registry.get_fallback_chain(requested_model)


def record_model_success(model_id: str, latency_ms: float) -> None:
    """Record a successful model invocation."""
    _model_registry.record_model_success(model_id, latency_ms)


def record_model_failure(model_id: str, error: str) -> None:
    """Record a failed model invocation."""
    _model_registry.record_model_failure(model_id, error)


async def get_model_health_summary() -> dict[str, dict[str, Any]]:
    """Get health summary for all models."""
    return await _model_registry.get_model_health_summary()
