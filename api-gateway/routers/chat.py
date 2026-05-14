"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

from typing import Any, cast

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from routers.agents import ChatMessagesSave, ChatSessionCreate, ChatSessionUpdate, _validate_session_ownership

router = APIRouter(tags=["chat"])

@router.get("/chat-sessions")
async def api_list_chat_sessions(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """List chat sessions for the given agent in the given namespace."""
    ensure_namespace_access(user, namespace)
    username = user.get("sub") or user.get("username")
    return list_chat_sessions(namespace, agent_name, username=username)


@router.post("/chat-sessions", status_code=201)
async def api_create_chat_session(
    body: ChatSessionCreate,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new chat session."""
    ensure_namespace_access(user, namespace)
    username = user.get("sub") or user.get("username")
    session_id = str(uuid.uuid4())
    return create_chat_session(namespace, body.agent_name, session_id, body.title, username=username)


@router.get("/chat-sessions/{session_id}/messages")
async def api_get_chat_messages(
    session_id: str,
    user=Depends(verify_token),
):
    """Get all messages for a chat session."""
    _validate_session_ownership(session_id, user)
    return get_chat_session_messages(session_id)


@router.put("/chat-sessions/{session_id}/messages")
async def api_save_chat_messages(
    session_id: str,
    body: ChatMessagesSave,
    user=Depends(verify_token),
):
    """Save (replace) all messages for a chat session."""
    _validate_session_ownership(session_id, user)
    save_chat_messages(session_id, [m.model_dump() for m in body.messages])
    return {"status": "ok"}


@router.patch("/chat-sessions/{session_id}")
async def api_update_chat_session(
    session_id: str,
    body: ChatSessionUpdate,
    user=Depends(verify_token),
):
    """Update a chat session title."""
    _validate_session_ownership(session_id, user)
    result = update_chat_session_title(session_id, body.title)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.delete("/chat-sessions/{session_id}")
async def api_delete_chat_session(
    session_id: str,
    user=Depends(verify_token),
):
    """Delete a chat session and all its messages."""
    _validate_session_ownership(session_id, user)
    deleted = delete_chat_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@router.patch("/memory/{record_id}", response_model=MemoryRecordInfo)
async def api_update_memory_record(
    record_id: int,
    body: MemoryRecordUpdateRequest,
    user=Depends(verify_token),
):
    record_namespace, record_username = _resolve_memory_record_owner(record_id)
    ensure_namespace_access(user, record_namespace)
    caller_username = user.get("sub") or user.get("username")
    if record_username and caller_username and record_username != caller_username:
        raise HTTPException(status_code=403, detail="Access denied: memory record belongs to another user")
    updated = update_memory_record(
        record_id,
        promoted=body.promoted,
        topic=body.topic,
        content=body.content,
        username=caller_username,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return MemoryRecordInfo(**updated)


@router.delete("/memory/{record_id}")
async def api_delete_memory_record(
    record_id: int,
    user=Depends(verify_token),
):
    record_namespace, record_username = _resolve_memory_record_owner(record_id)
    ensure_namespace_access(user, record_namespace)
    caller_username = user.get("sub") or user.get("username")
    if record_username and caller_username and record_username != caller_username:
        raise HTTPException(status_code=403, detail="Access denied: memory record belongs to another user")
    deleted = delete_memory_record(record_id, username=caller_username)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return {"status": "deleted", "id": record_id}


# ─────────────────────────────────────────────────────────────
# LLM / Provider management (proxied to the LiteLLM sidecar)
# ─────────────────────────────────────────────────────────────

_LLM_PROXY_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_OPENROUTER_API_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# -- OpenRouter model cache (TTL-based in-memory)
_openrouter_model_cache: list[dict[str, str]] = []
_openrouter_cache_ts: float = 0.0
_OPENROUTER_CACHE_TTL = 600  # 10 minutes

# -- Copilot model cache --
_copilot_model_cache: list[dict[str, str]] = []
_copilot_cache_ts: float = 0.0
_COPILOT_CACHE_TTL = 600  # 10 minutes


async def _fetch_copilot_models(copilot_token: str) -> list[dict[str, str]]:
    """Fetch available models from GitHub Copilot API with caching."""
    global _copilot_model_cache, _copilot_cache_ts

    # chat.py owns the public Copilot model fetcher, but the device-flow and
    # token-exchange helpers live in llm.py. Import lazily to avoid a module
    # cycle during router initialization.
    from routers import llm as llm_router

    now = time.monotonic()
    if _copilot_model_cache and (now - _copilot_cache_ts) < _COPILOT_CACHE_TTL:
        return _copilot_model_cache

    try:
        # Try exchanging for a Copilot session token; fall back to using the
        # OAuth token directly (works for personal GitHub tokens with Copilot).
        session_token = copilot_token
        models_url = "https://api.githubcopilot.com/models"
        try:
            exchanged, api_endpoint = await llm_router._exchange_copilot_session_token(copilot_token)
            session_token = exchanged
            if api_endpoint:
                models_url = f"{api_endpoint.rstrip('/')}/models"
        except Exception as exc:
            logger.info("Copilot token exchange failed, using OAuth token directly: %s", exc)
        data = await llm_router._copilot_get_json(
            models_url,
            {
                "Authorization": f"Bearer {session_token}",
                "Accept": "application/json",
                "User-Agent": "GitHubCopilotChat/0.25.2024",
                "Editor-Version": "vscode/1.96.2",
                "Editor-Plugin-Version": "copilot-chat/0.25.2024",
                "Copilot-Integration-Id": "vscode-chat",
                "Openai-Intent": "conversation-edits",
            },
        )
        models_raw = data if isinstance(data, list) else data.get("data", data.get("models", []))
        result: list[dict[str, str]] = []
        for m in models_raw:
            model_id = m.get("id", "") if isinstance(m, dict) else str(m)
            if not model_id:
                continue
            name = m.get("name", model_id) if isinstance(m, dict) else model_id
            caps = m.get("capabilities", {}) if isinstance(m, dict) else {}
            family = m.get("model_picker_label", m.get("family", "")) if isinstance(m, dict) else ""
            desc_parts: list[str] = []
            if family:
                desc_parts.append(family)
            if caps.get("type"):
                desc_parts.append(caps["type"])
            result.append(
                {
                    "model_id": model_id,
                    "display_name": name,
                    "description": " · ".join(desc_parts) if desc_parts else "Copilot model",
                }
            )
        _copilot_model_cache = result
        _copilot_cache_ts = now
        logger.info("Fetched %d models from GitHub Copilot API", len(result))
        return result
    except Exception as exc:
        logger.warning("Failed to fetch Copilot models: %s", exc)
        return _copilot_model_cache if _copilot_model_cache else []


async def _fetch_openrouter_models(api_key: str | None = None) -> list[dict[str, str]]:
    """Fetch models from OpenRouter API with in-memory caching."""
    import time

    global _openrouter_model_cache, _openrouter_cache_ts

    now = time.monotonic()
    if _openrouter_model_cache and (now - _openrouter_cache_ts) < _OPENROUTER_CACHE_TTL:
        return _openrouter_model_cache

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_OPENROUTER_API_TIMEOUT, trust_env=False) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models_raw = data.get("data", [])
            result: list[dict[str, str]] = []
            for m in models_raw:
                model_id = m.get("id", "")
                name = m.get("name", model_id)
                desc_parts: list[str] = []
                pricing = m.get("pricing", {})
                if pricing:
                    prompt_price = pricing.get("prompt")
                    if prompt_price is not None:
                        try:
                            p = float(prompt_price) * 1_000_000
                            desc_parts.append(f"${p:.2f}/M input")
                        except (ValueError, TypeError):
                            pass
                ctx = m.get("context_length")
                if ctx:
                    with contextlib.suppress(ValueError, TypeError):
                        desc_parts.append(f"{int(ctx) // 1000}k ctx")
                description = " · ".join(desc_parts) if desc_parts else ""
                if model_id:
                    result.append(
                        {
                            "model_id": model_id,
                            "display_name": name,
                            "description": description,
                        }
                    )
            _openrouter_model_cache = result
            _openrouter_cache_ts = now
            logger.info("Fetched %d models from OpenRouter API", len(result))
            return result
    except Exception as exc:
        logger.warning("Failed to fetch OpenRouter models: %s", exc)
        return _openrouter_model_cache  # return stale cache on error


# -- well-known provider keys accepted by the platform
_ALLOWED_SECRET_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENCODE_API_KEY",
        "OPENCODE_GO_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_API_KEY",
        "GOOGLE_API_KEY",
        "MISTRAL_API_KEY",
        "COHERE_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "GITHUB_COPILOT_TOKEN",
    }
)

# -- Provider metadata: key_name → {label, prefix for litellm, env reference}
_PROVIDER_META: dict[str, dict[str, str]] = {
    "OPENAI_API_KEY": {"label": "OpenAI", "prefix": "openai/", "placeholder": "sk-..."},
    "OPENROUTER_API_KEY": {"label": "OpenRouter", "prefix": "openrouter/", "placeholder": "sk-or-..."},
    "OPENCODE_API_KEY": {
        "label": "OpenCode Zen",
        "prefix": "openai/",
        "placeholder": "sk-...",
        "api_base": "https://opencode.ai/zen/v1",
    },
    "OPENCODE_GO_API_KEY": {
        "label": "OpenCode Go",
        "prefix": "openai/",
        "placeholder": "sk-...",
        "api_base": "https://opencode.ai/zen/go/v1",
    },
    "ANTHROPIC_API_KEY": {"label": "Anthropic", "prefix": "anthropic/", "placeholder": "sk-ant-..."},
    "AZURE_API_KEY": {"label": "Azure OpenAI", "prefix": "azure/", "placeholder": "..."},
    "GOOGLE_API_KEY": {"label": "Google AI", "prefix": "gemini/", "placeholder": "AIza..."},
    "MISTRAL_API_KEY": {"label": "Mistral", "prefix": "mistral/", "placeholder": "..."},
    "COHERE_API_KEY": {"label": "Cohere", "prefix": "cohere/", "placeholder": "..."},
    "GROQ_API_KEY": {"label": "Groq", "prefix": "groq/", "placeholder": "gsk_..."},
    "DEEPSEEK_API_KEY": {"label": "DeepSeek", "prefix": "deepseek/", "placeholder": "sk-..."},
    "TOGETHER_API_KEY": {"label": "Together AI", "prefix": "together_ai/", "placeholder": "..."},
    "FIREWORKS_API_KEY": {"label": "Fireworks", "prefix": "fireworks_ai/", "placeholder": "..."},
    "GITHUB_COPILOT_TOKEN": {
        "label": "GitHub Copilot",
        "prefix": "openai/",
        "placeholder": "Authenticated via GitHub",
        "api_base": "https://api.githubcopilot.com",
        "extra_headers": '{"Copilot-Integration-Id": "vscode-chat"}',
    },
}

# -- Popular models per provider (static, curated)
_PROVIDER_POPULAR_MODELS: dict[str, list[dict[str, str]]] = {
    "OPENAI_API_KEY": [
        {"model_id": "gpt-4o", "display_name": "GPT-4o", "description": "Most capable, multimodal"},
        {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "description": "Fast and affordable"},
        {"model_id": "gpt-4-turbo", "display_name": "GPT-4 Turbo", "description": "High capability, 128k context"},
        {"model_id": "gpt-3.5-turbo", "display_name": "GPT-3.5 Turbo", "description": "Budget option"},
        {"model_id": "o1", "display_name": "o1", "description": "Reasoning model"},
        {"model_id": "o1-mini", "display_name": "o1 Mini", "description": "Fast reasoning"},
        {"model_id": "o3-mini", "display_name": "o3 Mini", "description": "Latest reasoning, cost-effective"},
    ],
    "OPENROUTER_API_KEY": [],
    "ANTHROPIC_API_KEY": [
        {
            "model_id": "claude-sonnet-4-20250514",
            "display_name": "Claude Sonnet 4",
            "description": "Latest, most capable",
        },
        {
            "model_id": "claude-3-5-sonnet-20241022",
            "display_name": "Claude 3.5 Sonnet",
            "description": "Fast and intelligent",
        },
        {
            "model_id": "claude-3-5-haiku-20241022",
            "display_name": "Claude 3.5 Haiku",
            "description": "Fastest, most compact",
        },
        {"model_id": "claude-3-opus-20240229", "display_name": "Claude 3 Opus", "description": "Most capable (legacy)"},
    ],
    "AZURE_API_KEY": [
        {"model_id": "gpt-4o", "display_name": "GPT-4o", "description": "Azure-hosted GPT-4o"},
        {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "description": "Azure-hosted GPT-4o Mini"},
        {"model_id": "gpt-4", "display_name": "GPT-4", "description": "Azure-hosted GPT-4"},
    ],
    "GOOGLE_API_KEY": [
        {"model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "description": "Fast multimodal"},
        {"model_id": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro", "description": "1M context window"},
        {"model_id": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash", "description": "Fast, 1M context"},
    ],
    "MISTRAL_API_KEY": [
        {"model_id": "mistral-large-latest", "display_name": "Mistral Large", "description": "Top-tier reasoning"},
        {"model_id": "mistral-medium-latest", "display_name": "Mistral Medium", "description": "Balanced"},
        {"model_id": "mistral-small-latest", "display_name": "Mistral Small", "description": "Fast and affordable"},
        {"model_id": "codestral-latest", "display_name": "Codestral", "description": "Code-specialized"},
    ],
    "COHERE_API_KEY": [
        {"model_id": "command-r-plus", "display_name": "Command R+", "description": "Most capable"},
        {"model_id": "command-r", "display_name": "Command R", "description": "Balanced"},
    ],
    "GROQ_API_KEY": [
        {"model_id": "llama-3.1-70b-versatile", "display_name": "Llama 3.1 70B", "description": "Fast inference"},
        {"model_id": "llama-3.1-8b-instant", "display_name": "Llama 3.1 8B", "description": "Ultra-fast"},
        {"model_id": "mixtral-8x7b-32768", "display_name": "Mixtral 8x7B", "description": "MoE, 32K context"},
    ],
    "DEEPSEEK_API_KEY": [
        {"model_id": "deepseek-chat", "display_name": "DeepSeek Chat", "description": "General purpose"},
        {"model_id": "deepseek-coder", "display_name": "DeepSeek Coder", "description": "Code-specialized"},
        {"model_id": "deepseek-reasoner", "display_name": "DeepSeek Reasoner", "description": "Reasoning model"},
    ],
    "TOGETHER_API_KEY": [
        {
            "model_id": "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "display_name": "Llama 3.1 70B Turbo",
            "description": "Fast Llama",
        },
        {
            "model_id": "meta-llama/Llama-3.1-8B-Instruct-Turbo",
            "display_name": "Llama 3.1 8B Turbo",
            "description": "Ultra-fast Llama",
        },
        {"model_id": "Qwen/Qwen2.5-72B-Instruct-Turbo", "display_name": "Qwen 2.5 72B", "description": "Top-tier open"},
    ],
    "FIREWORKS_API_KEY": [
        {
            "model_id": "accounts/fireworks/models/llama-v3p1-70b-instruct",
            "display_name": "Llama 3.1 70B",
            "description": "Fast inference",
        },
        {
            "model_id": "accounts/fireworks/models/llama-v3p1-8b-instruct",
            "display_name": "Llama 3.1 8B",
            "description": "Low latency",
        },
    ],
    "GITHUB_COPILOT_TOKEN": [
        {"model_id": "gpt-4o", "display_name": "GPT-4o", "description": "Most capable, multimodal"},
        {"model_id": "gpt-4.1", "display_name": "GPT-4.1", "description": "Latest GPT model"},
        {"model_id": "o3-mini", "display_name": "o3 Mini", "description": "Fast reasoning"},
        {"model_id": "o4-mini", "display_name": "o4 Mini", "description": "Latest reasoning, cost-effective"},
        {"model_id": "claude-sonnet-4", "display_name": "Claude Sonnet 4", "description": "Anthropic via Copilot"},
        {
            "model_id": "claude-3.5-sonnet",
            "display_name": "Claude 3.5 Sonnet",
            "description": "Fast Anthropic via Copilot",
        },
        {"model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "description": "Google via Copilot"},
    ],
}

_PROVIDER_REGISTRY_DATA_KEY = "providers.json"
_PROVIDER_REGISTRY_VERSION = 1
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,62})$")
_OPENCODE_ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"
_OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
_OPENCODE_ZEN_GO_MODELS_URL = "https://opencode.ai/zen/go/v1/models"
_PROVIDER_AUTH_PLACEHOLDERS: dict[str, str] = {
    "opencode": "sk-...",
    "opencode-go": "sk-...",
    "github-copilot": "Authenticated via GitHub",
}
_PROVIDER_REGISTRY_META: dict[str, dict[str, Any]] = {
    "opencode": {
        "label": "OpenCode Zen",
        "description": "Recommended OpenCode-native provider with curated models from the OpenCode team.",
        "auth_type": "apiKey",
        "secret_key": "OPENCODE_API_KEY",
        "base_url": _OPENCODE_ZEN_BASE_URL,
        "docs_url": "https://opencode.ai/docs/providers/#opencode-zen",
    },
    "opencode-go": {
        "label": "OpenCode Go",
        "description": "Low-cost OpenCode provider tuned for reliable coding workloads.",
        "auth_type": "apiKey",
        "secret_key": "OPENCODE_GO_API_KEY",
        "base_url": "https://opencode.ai/zen/go/v1",
        "docs_url": "https://opencode.ai/docs/providers/#opencode-go",
    },
    "github-copilot": {
        "label": "GitHub Copilot",
        "description": "Connect a GitHub Copilot subscription through the device authorization flow.",
        "auth_type": "oauth",
        "secret_key": "GITHUB_COPILOT_TOKEN",
        "base_url": "https://api.githubcopilot.com",
        "docs_url": "https://opencode.ai/docs/providers/#github-copilot",
    },
}
_OPENCODE_GO_FALLBACK_MODELS: list[dict[str, str]] = [
    {
        "model_id": "kimi-k2.6",
        "display_name": "kimi-k2.6",
        "description": "Current kubesynapse default for bundled OpenCode agents.",
    }
]


def _provider_namespace() -> str:
    return os.getenv("POD_NAMESPACE", "ai-platform")


def _empty_provider_registry_state() -> dict[str, Any]:
    return {"version": _PROVIDER_REGISTRY_VERSION, "custom_providers": {}}


def _normalize_provider_id(raw_value: str) -> str:
    provider_id = str(raw_value or "").strip().lower()
    if not _PROVIDER_ID_RE.fullmatch(provider_id):
        raise HTTPException(
            status_code=400,
            detail="provider_id must use lowercase letters, numbers, and hyphens only.",
        )
    return provider_id


def _custom_provider_secret_key(provider_id: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", provider_id.upper()).strip("_")
    return f"CUSTOM_PROVIDER_{normalized}_API_KEY"


def _decode_secret_value(raw_value: str) -> str | None:
    if not raw_value:
        return None
    try:
        return base64.b64decode(raw_value).decode("utf-8").strip() or None
    except Exception:
        return None


def _read_or_create_provider_registry_configmap() -> tuple[Any, Any, dict[str, Any]]:
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    namespace = _provider_namespace()
    api = k8s_client.CoreV1Api()
    try:
        configmap = api.read_namespaced_config_map(name=PROVIDER_REGISTRY_CONFIGMAP_NAME, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
        body = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": PROVIDER_REGISTRY_CONFIGMAP_NAME, "namespace": namespace},
            "data": {
                _PROVIDER_REGISTRY_DATA_KEY: json.dumps(_empty_provider_registry_state(), ensure_ascii=False, sort_keys=True)
            },
        }
        api.create_namespaced_config_map(namespace=namespace, body=body)
        configmap = api.read_namespaced_config_map(name=PROVIDER_REGISTRY_CONFIGMAP_NAME, namespace=namespace)

    data = getattr(configmap, "data", None) or {}
    raw_payload = str(data.get(_PROVIDER_REGISTRY_DATA_KEY) or "").strip()
    if not raw_payload:
        return api, configmap, _empty_provider_registry_state()
    try:
        payload = json.loads(raw_payload)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Provider registry ConfigMap contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Provider registry ConfigMap must decode to an object")
    custom_providers = payload.get("custom_providers")
    if custom_providers is None:
        payload["custom_providers"] = {}
    elif not isinstance(custom_providers, dict):
        raise HTTPException(status_code=500, detail="Provider registry custom_providers must decode to an object")
    return api, configmap, payload


def _save_provider_registry_state(api: Any, configmap: Any, state: dict[str, Any]) -> None:
    data = getattr(configmap, "data", None) or {}
    data[_PROVIDER_REGISTRY_DATA_KEY] = json.dumps(state, ensure_ascii=False, sort_keys=True)
    configmap.data = data  # type: ignore[union-attr]
    api.replace_namespaced_config_map(
        name=PROVIDER_REGISTRY_CONFIGMAP_NAME,
        namespace=_provider_namespace(),
        body=configmap,
    )


def _read_or_create_provider_auth_secret() -> tuple[Any, Any, dict[str, str]]:
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    namespace = _provider_namespace()
    api = k8s_client.CoreV1Api()
    try:
        secret = api.read_namespaced_secret(name=PROVIDER_AUTH_SECRET_NAME, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": PROVIDER_AUTH_SECRET_NAME, "namespace": namespace},
            "type": "Opaque",
            "data": {},
        }
        api.create_namespaced_secret(namespace=namespace, body=body)
        secret = api.read_namespaced_secret(name=PROVIDER_AUTH_SECRET_NAME, namespace=namespace)
    data = getattr(secret, "data", None) or {}
    return api, secret, cast(dict[str, str], data)


def _update_provider_auth_secret(*, values: dict[str, str] | None = None, remove_keys: set[str] | None = None) -> None:
    api, secret, existing_data = _read_or_create_provider_auth_secret()
    next_data = dict(existing_data)
    for key_name in remove_keys or set():
        next_data.pop(key_name, None)
    for key_name, value in (values or {}).items():
        next_data[key_name] = base64.b64encode(value.encode("utf-8")).decode("ascii")
    secret.data = next_data  # type: ignore[union-attr]
    api.replace_namespaced_secret(name=PROVIDER_AUTH_SECRET_NAME, namespace=_provider_namespace(), body=secret)


def _provider_registry_model_entries(raw_models: list[dict[str, str]]) -> list[dict[str, str | None]]:
    return [
        {
            "id": str(item.get("model_id") or "").strip(),
            "name": str(item.get("display_name") or item.get("model_id") or "").strip(),
            "description": str(item.get("description") or "").strip() or None,
        }
        for item in raw_models
        if str(item.get("model_id") or "").strip()
    ]


async def _fetch_opencode_zen_models(api_key: str) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.get(
                _OPENCODE_ZEN_MODELS_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return []
        result: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            result.append({"model_id": model_id, "display_name": model_id, "description": "Live model catalog"})
        return result
    except Exception as exc:
        logger.warning("Failed to fetch OpenCode Zen models: %s", exc)
        return []


async def _fetch_opencode_go_models(api_key: str) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.get(
                _OPENCODE_ZEN_GO_MODELS_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return []
        result: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            result.append({"model_id": model_id, "display_name": model_id, "description": "Live model catalog"})
        return result
    except Exception as exc:
        logger.warning("Failed to fetch OpenCode Go models: %s", exc)
        return []


async def _provider_registry_models_for_builtin(provider_id: str, auth_data: dict[str, str]) -> list[dict[str, str | None]]:
    if provider_id == "opencode":
        api_key = _decode_secret_value(auth_data.get("OPENCODE_API_KEY", ""))
        if not api_key:
            return []
        return _provider_registry_model_entries(await _fetch_opencode_zen_models(api_key))
    if provider_id == "opencode-go":
        api_key = _decode_secret_value(auth_data.get("OPENCODE_GO_API_KEY", ""))
        if not api_key:
            return []
        return _provider_registry_model_entries(await _fetch_opencode_go_models(api_key))
    if provider_id == "github-copilot":
        copilot_token = _decode_secret_value(auth_data.get("GITHUB_COPILOT_TOKEN", ""))
        if not copilot_token:
            return []
        return _provider_registry_model_entries(await _fetch_copilot_models(copilot_token))
    return []


async def _provider_registry_response() -> dict[str, Any]:
    _, _, registry_state = _read_or_create_provider_registry_configmap()
    _, _, auth_data = _read_or_create_provider_auth_secret()

    providers: list[dict[str, Any]] = []
    for provider_id, meta in _PROVIDER_REGISTRY_META.items():
        secret_key = str(meta.get("secret_key") or "")
        providers.append(
            {
                "id": provider_id,
                "label": meta["label"],
                "kind": "builtin",
                "description": meta["description"],
                "auth_type": meta["auth_type"],
                "connected": bool(auth_data.get(secret_key)),
                "docs_url": meta.get("docs_url"),
                "base_url": meta.get("base_url"),
                "key_placeholder": _PROVIDER_AUTH_PLACEHOLDERS.get(provider_id),
                "editable": False,
                "headers": {},
                "models": await _provider_registry_models_for_builtin(provider_id, auth_data),
            }
        )

    custom_providers = cast(dict[str, dict[str, Any]], registry_state.get("custom_providers") or {})
    for provider_id, entry in sorted(custom_providers.items()):
        secret_key = str(entry.get("secret_key_name") or _custom_provider_secret_key(provider_id))
        model_ids = [
            str(raw_model).strip()
            for raw_model in cast(list[Any], entry.get("models") or [])
            if str(raw_model).strip()
        ]
        providers.append(
            {
                "id": provider_id,
                "label": str(entry.get("name") or provider_id),
                "kind": "custom",
                "description": str(entry.get("description") or "OpenAI-compatible custom provider.").strip(),
                "auth_type": "apiKey",
                "connected": bool(auth_data.get(secret_key)),
                "docs_url": None,
                "base_url": str(entry.get("base_url") or "").strip() or None,
                "key_placeholder": "sk-...",
                "editable": True,
                "headers": cast(dict[str, str], entry.get("headers") or {}),
                "models": [
                    {"id": model_id, "name": model_id, "description": None}
                    for model_id in model_ids
                ],
            }
        )

    return {"providers": providers}


def _litellm_headers() -> dict[str, str]:
    key = LITELLM_MASTER_KEY
    if not key:
        # fall back to env injected from K8s secret
        key = os.getenv("LITELLM_MASTER_KEY", "") or ""
    hdrs: dict[str, str] = {"Accept": "application/json"}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    return hdrs


class LLMModelEntry(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=200)
    litellm_params: dict[str, Any] = Field(default_factory=dict)


class LLMModelDeleteRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=200)


class LLMKeyUpdate(BaseModel):
    keys: dict[str, str] = Field(default_factory=dict, description="Map of KEY_NAME -> value")


class ProviderCredentialUpdate(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=500)


class ProviderCatalogModel(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=300)


class CustomProviderRequest(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=63)
    name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=240)
    api_key: str | None = Field(default=None, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    models: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_custom_provider_fields(self) -> CustomProviderRequest:
        normalized_headers: dict[str, str] = {}
        for raw_name, raw_value in self.headers.items():
            name = str(raw_name).strip()
            value = str(raw_value).strip()
            if not name:
                raise ValueError("Custom provider headers must use non-empty names")
            if not value:
                raise ValueError(f"Custom provider header '{name}' must not be blank")
            normalized_headers[name] = value
        self.headers = normalized_headers
        self.models = [str(model).strip() for model in self.models if str(model).strip()]
        return self


@router.get("/notifications/stream")
def stream_notifications(
    namespace: str = "default",
    user=Depends(verify_token_or_query),
):
    """Long-lived SSE connection that pushes resource status change events."""
    ensure_namespace_access(user, namespace)
    import asyncio

    async def notification_generator():
        last_agents: dict[str, str] = {}
        last_workflows: dict[str, str] = {}
        first_poll = True

        while True:
            try:
                agents = list_custom_resources("aiagents", namespace)
                workflows = list_custom_resources("agentworkflows", namespace)

                current_agents: dict[str, str] = {}
                for a in agents:
                    name = (a.get("metadata") or {}).get("name", "")
                    phase = ((a.get("status") or {}).get("phase") or "unknown").lower()
                    current_agents[name] = phase

                current_workflows: dict[str, str] = {}
                for w in workflows:
                    name = (w.get("metadata") or {}).get("name", "")
                    phase = ((w.get("status") or {}).get("phase") or "unknown").lower()
                    current_workflows[name] = phase

                if not first_poll:
                    # Agent status changes
                    for name, phase in current_agents.items():
                        prev = last_agents.get(name)
                        if prev != phase:
                            yield sse_event(
                                "agent.status_changed",
                                {
                                    "name": name,
                                    "namespace": namespace,
                                    "phase": phase,
                                    "previousPhase": prev,
                                    "timestamp": now_iso(),
                                },
                            )

                    # Deleted agents
                    for name in set(last_agents) - set(current_agents):
                        yield sse_event(
                            "agent.status_changed",
                            {
                                "name": name,
                                "namespace": namespace,
                                "phase": "deleted",
                                "previousPhase": last_agents[name],
                                "timestamp": now_iso(),
                            },
                        )

                    # Workflow status changes
                    for name, phase in current_workflows.items():
                        prev = last_workflows.get(name)
                        if prev != phase:
                            event_type = (
                                "workflow.completed"
                                if phase in ("succeeded",)
                                else "workflow.failed"
                                if phase in ("failed",)
                                else "workflow.approval_needed"
                                if phase in ("waitingapproval", "waiting_approval", "waiting-approval")
                                else "workflow.status_changed"
                            )
                            yield sse_event(
                                event_type,
                                {
                                    "name": name,
                                    "namespace": namespace,
                                    "phase": phase,
                                    "previousPhase": prev,
                                    "timestamp": now_iso(),
                                },
                            )

                    # Deleted workflows
                    for name in set(last_workflows) - set(current_workflows):
                        yield sse_event(
                            "workflow.status_changed",
                            {
                                "name": name,
                                "namespace": namespace,
                                "phase": "deleted",
                                "previousPhase": last_workflows[name],
                                "timestamp": now_iso(),
                            },
                        )

                last_agents = current_agents
                last_workflows = current_workflows
                first_poll = False

            except Exception as exc:
                logger.warning("Notification stream poll error: %s", exc)
                yield sse_event("system.error", {"message": str(exc)[:300], "timestamp": now_iso()})

            yield sse_keepalive_comment()
            await asyncio.sleep(5)

    return StreamingResponse(notification_generator(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
#  Export / Import YAML bundles                                                 #
# --------------------------------------------------------------------------- #
