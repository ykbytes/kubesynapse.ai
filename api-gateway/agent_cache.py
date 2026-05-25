"""Redis-based caching for agent reads — reduces K8s API load.

Provides ``read_agent_cached()`` — a drop-in replacement for ``read_agent()``
that caches agent CRDs in Redis for a configurable TTL (default 30s).

When Redis is unavailable, falls back to direct K8s API reads with no caching.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("api-gateway.agent-cache")

_REDIS_URL = os.getenv("REDIS_URL", "").strip()
_AGENT_CACHE_TTL = int(os.getenv("AGENT_CACHE_TTL_SECONDS", "30"))

_redis_client: Any = None


def _get_redis():
    """Return a Redis client, or None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    url = _REDIS_URL
    if not url:
        # Build from components
        host = os.getenv("REDIS_HOST", "").strip()
        if not host:
            return None
        port = os.getenv("REDIS_PORT", "6379")
        password = os.getenv("REDIS_PASSWORD", "").strip()
        url = f"redis://:{password}@{host}:{port}" if password else f"redis://{host}:{port}"

    try:
        import redis
        _redis_client = redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, decode_responses=False)
        _redis_client.ping()
        logger.info("Redis agent cache connected (%s)", url.split("@")[-1] if "@" in url else url)
    except Exception:
        logger.debug("Redis agent cache unavailable — falling back to direct K8s reads")
        _redis_client = None
    return _redis_client


def _cache_key(namespace: str, agent_name: str) -> str:
    return f"agent:{namespace}:{agent_name}"


def read_agent_cached(agent_name: str, namespace: str) -> dict[str, Any]:
    """Read an AIAgent CRD, with Redis caching if available.

    Returns the same dict shape as ``read_agent()``.
    """
    from _core import read_agent as _k8s_read

    redis = _get_redis()
    if redis is None:
        return _k8s_read(agent_name, namespace)

    key = _cache_key(namespace, agent_name)
    try:
        cached = redis.get(key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass  # Cache miss or Redis error — fall through to K8s read

    # K8s read
    agent = _k8s_read(agent_name, namespace)

    # Store in cache
    try:
        redis.setex(key, _AGENT_CACHE_TTL, json.dumps(agent, default=str))
    except Exception:
        pass

    return agent


def invalidate_agent_read_cache(*, agent_name: str, namespace: str) -> None:
    """Remove a cached agent entry after mutation (create/update/delete)."""
    redis = _get_redis()
    if redis is None:
        return
    try:
        redis.delete(_cache_key(namespace, agent_name))
    except Exception:
        pass
