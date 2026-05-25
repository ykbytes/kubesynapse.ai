"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

from typing import Any, cast

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Depends, HTTPException, Response

from routers.chat import (
    _ALLOWED_SECRET_KEYS,
    _LLM_PROXY_TIMEOUT,
    _PROVIDER_META,
    _PROVIDER_REGISTRY_META,
    LLM_SECRET_NAME,
    CustomProviderRequest,
    LLMKeyUpdate,
    LLMModelDeleteRequest,
    LLMModelEntry,
    ProviderCredentialUpdate,
    _custom_provider_secret_key,
    _fetch_copilot_models,
    _fetch_opencode_go_models,
    _fetch_opencode_zen_models,
    _fetch_openrouter_models,
    _litellm_headers,
    _normalize_provider_id,
    _provider_registry_response,
    _read_or_create_provider_registry_configmap,
    _save_provider_registry_state,
    _update_provider_auth_secret,
)

router = APIRouter(tags=["llm"])


def _read_secret_key_value(key_name: str) -> str | None:
    try:
        import base64

        from kubernetes import client as k8s_client

        ns = os.getenv("POD_NAMESPACE", "ai-platform")
        secret = k8s_client.CoreV1Api().read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
        raw = (getattr(secret, "data", None) or {}).get(key_name, "")
        if raw:
            return base64.b64decode(raw).decode("utf-8").strip() or None
    except Exception:
        pass
    return (os.getenv(key_name) or "").strip() or None

@router.get("/providers")
async def provider_registry_list(user=Depends(verify_token)):
    """List built-in and custom providers for the OpenCode-style settings UX."""
    ensure_role(user, "viewer")
    return await _provider_registry_response()


@router.get("/providers/catalog")
async def provider_registry_catalog(user=Depends(verify_token)):
    """Return a flattened model catalog for runtime-compatible provider/model picks."""
    ensure_role(user, "viewer")
    payload = await _provider_registry_response()
    catalog: list[dict[str, Any]] = []
    for provider in cast(list[dict[str, Any]], payload.get("providers") or []):
        if not bool(provider.get("connected")):
            continue
        provider_id = str(provider.get("id") or "").strip()
        provider_label = str(provider.get("label") or provider_id).strip()
        for model in cast(list[dict[str, Any]], provider.get("models") or []):
            model_id = str(model.get("id") or "").strip()
            if not provider_id or not model_id:
                continue
            catalog.append(
                {
                    "provider_id": provider_id,
                    "provider_label": provider_label,
                    "model_id": model_id,
                    "model_ref": f"{provider_id}/{model_id}",
                    "connected": bool(provider.get("connected")),
                    "kind": str(provider.get("kind") or "builtin"),
                    "description": model.get("description"),
                }
            )
    return {"models": catalog}


@router.put("/providers/{provider_id}/credentials")
def provider_registry_update_credentials(provider_id: str, body: ProviderCredentialUpdate, user=Depends(verify_token)):
    """Store provider auth in the dedicated provider-auth secret. Admin only."""
    ensure_role(user, "admin")
    normalized_provider_id = _normalize_provider_id(provider_id)
    value = body.api_key.strip()
    if not value:
        raise HTTPException(status_code=400, detail="api_key must not be blank")

    if normalized_provider_id in _PROVIDER_REGISTRY_META:
        secret_key = str(_PROVIDER_REGISTRY_META[normalized_provider_id]["secret_key"])
    else:
        _, _, state = _read_or_create_provider_registry_configmap()
        custom_providers = cast(dict[str, dict[str, Any]], state.get("custom_providers") or {})
        if normalized_provider_id not in custom_providers:
            raise HTTPException(status_code=404, detail=f"Unknown provider: {normalized_provider_id}")
        secret_key = str(custom_providers[normalized_provider_id].get("secret_key_name") or _custom_provider_secret_key(normalized_provider_id))

    _update_provider_auth_secret(values={secret_key: value})
    logger.info("Updated provider credential for %s (by user %s)", normalized_provider_id, user.get("sub", "unknown"))
    return {"status": "updated", "provider_id": normalized_provider_id}


@router.get("/providers/{provider_id}/models")
async def provider_registry_models(provider_id: str, user=Depends(verify_token)):
    """Return model entries for a single provider."""
    ensure_role(user, "viewer")
    normalized_provider_id = _normalize_provider_id(provider_id)
    payload = await _provider_registry_response()
    providers = cast(list[dict[str, Any]], payload.get("providers") or [])
    for provider in providers:
        if str(provider.get("id") or "") == normalized_provider_id:
            return {"provider_id": normalized_provider_id, "models": provider.get("models") or []}
    raise HTTPException(status_code=404, detail=f"Unknown provider: {normalized_provider_id}")


@router.post("/providers/custom", status_code=201)
def provider_registry_upsert_custom_provider(body: CustomProviderRequest, user=Depends(verify_token)):
    """Create or update a custom OpenAI-compatible provider. Admin only."""
    ensure_role(user, "admin")
    provider_id = _normalize_provider_id(body.provider_id)
    if provider_id in _PROVIDER_REGISTRY_META:
        raise HTTPException(status_code=400, detail="Built-in provider IDs cannot be overwritten")

    base_url = body.base_url.strip()
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="base_url must be an http or https URL")

    api, configmap, state = _read_or_create_provider_registry_configmap()
    custom_providers = cast(dict[str, dict[str, Any]], state.setdefault("custom_providers", {}))
    secret_key_name = str(custom_providers.get(provider_id, {}).get("secret_key_name") or _custom_provider_secret_key(provider_id))
    custom_providers[provider_id] = {
        "name": body.name.strip(),
        "description": (body.description or "").strip() or None,
        "base_url": base_url,
        "headers": dict(body.headers.items()),
        "models": body.models,
        "secret_key_name": secret_key_name,
    }
    _save_provider_registry_state(api, configmap, state)
    if body.api_key and body.api_key.strip():
        _update_provider_auth_secret(values={secret_key_name: body.api_key.strip()})
    logger.info("Upserted custom provider %s (by user %s)", provider_id, user.get("sub", "unknown"))
    return {"status": "created", "provider_id": provider_id}


@router.delete("/providers/custom/{provider_id}")
def provider_registry_delete_custom_provider(provider_id: str, user=Depends(verify_token)):
    """Delete a custom provider and remove its stored auth material. Admin only."""
    ensure_role(user, "admin")
    normalized_provider_id = _normalize_provider_id(provider_id)
    api, configmap, state = _read_or_create_provider_registry_configmap()
    custom_providers = cast(dict[str, dict[str, Any]], state.get("custom_providers") or {})
    if normalized_provider_id not in custom_providers:
        raise HTTPException(status_code=404, detail=f"Unknown custom provider: {normalized_provider_id}")
    entry = custom_providers.pop(normalized_provider_id)
    _save_provider_registry_state(api, configmap, state)
    secret_key_name = str(entry.get("secret_key_name") or _custom_provider_secret_key(normalized_provider_id))
    _update_provider_auth_secret(remove_keys={secret_key_name})
    logger.info("Deleted custom provider %s (by user %s)", normalized_provider_id, user.get("sub", "unknown"))
    return {"status": "deleted", "provider_id": normalized_provider_id}


@router.get("/llm/health")
async def llm_health(user=Depends(verify_token)):
    """Proxy LiteLLM health check."""
    ensure_role(user, "viewer")
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/health/liveliness", headers=_litellm_headers())
            return {"status": "healthy" if resp.status_code == 200 else "unhealthy", "litellm_status": resp.status_code}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


@router.get("/llm/models")
async def llm_list_models(response: Response, user=Depends(verify_token)):
    """List model deployments configured in LiteLLM."""
    ensure_role(user, "viewer")
    response.headers["Cache-Control"] = "no-store"
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/model/info", headers=_litellm_headers())
            resp.raise_for_status()
            data = resp.json()
            return {"models": data.get("data", [])}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (model/info): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


@router.post("/llm/models", status_code=201)
async def llm_add_model(body: LLMModelEntry, user=Depends(verify_token)):
    """Add a model deployment to LiteLLM."""
    ensure_role(user, "admin")
    payload = {"model_name": body.model_name, "litellm_params": body.litellm_params}
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.post(
                f"{LITELLM_INTERNAL_URL}/model/new",
                headers={**_litellm_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (model/new): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


@router.post("/llm/models/delete")
async def llm_delete_model(body: LLMModelDeleteRequest, user=Depends(verify_token)):
    """Delete a model deployment from LiteLLM."""
    ensure_role(user, "admin")
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.post(
                f"{LITELLM_INTERNAL_URL}/model/delete",
                headers={**_litellm_headers(), "Content-Type": "application/json"},
                json={"id": body.id},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (model/delete): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


@router.get("/llm/keys")
def llm_list_keys(user=Depends(verify_token)):
    """List which LLM API key env vars are set (names only, never values)."""
    ensure_role(user, "admin")
    try:
        from kubernetes import client as k8s_client

        secret = k8s_client.CoreV1Api().read_namespaced_secret(
            name=LLM_SECRET_NAME,
            namespace=os.getenv("POD_NAMESPACE", "ai-platform"),
        )
        data: dict[str, str] = getattr(secret, "data", None) or {}
        result: list[dict[str, Any]] = []
        for key_name in sorted(_ALLOWED_SECRET_KEYS):
            result.append(
                {
                    "name": key_name,
                    "is_set": key_name in data and bool(data[key_name]),
                }
            )
        return {"keys": result}
    except Exception as exc:
        logger.error("Failed to read LLM secret: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to read secret") from exc


@router.put("/llm/keys")
def llm_update_keys(body: LLMKeyUpdate, user=Depends(verify_token)):
    """Update LLM API key values in the K8s Secret. Operator-or-admin."""
    ensure_role(user, "admin")

    # Validate key names
    for key_name in body.keys:
        if key_name not in _ALLOWED_SECRET_KEYS:
            raise HTTPException(status_code=400, detail=f"Key '{key_name}' is not a recognized LLM provider key")
        if len(body.keys[key_name]) > 500:
            raise HTTPException(status_code=400, detail=f"Key value for '{key_name}' is too long")

    try:
        import base64

        from kubernetes import client as k8s_client

        ns = os.getenv("POD_NAMESPACE", "ai-platform")
        api = k8s_client.CoreV1Api()
        secret = api.read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
        existing_data: dict[str, str] = getattr(secret, "data", None) or {}

        for key_name, value in body.keys.items():
            existing_data[key_name] = base64.b64encode(value.encode("utf-8")).decode("ascii")

        secret.data = existing_data  # type: ignore[union-attr]
        api.replace_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns, body=secret)
        logger.info("Updated LLM API keys: %s (by user %s)", list(body.keys.keys()), user.get("sub", "unknown"))
        return {"status": "updated", "keys": list(body.keys.keys())}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update LLM secret: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to update secret") from exc


# ─────────────────────────────────────────────────────────────
# Provider-centric LLM management (new, cleaner API)
# ─────────────────────────────────────────────────────────────


class ProviderModelAdd(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=300, description="Model identifier (e.g. gpt-4o-mini)")
    alias: str | None = Field(None, max_length=200, description="Optional alias; defaults to model_id")


@router.get("/llm/providers")
async def llm_list_providers(response: Response, user=Depends(verify_token)):
    """Unified provider view: merges model list + key status grouped by provider."""
    ensure_role(user, "viewer")
    response.headers["Cache-Control"] = "no-store"

    # Fetch models from LiteLLM
    models_by_provider: dict[str, list[dict[str, Any]]] = {k: [] for k in _PROVIDER_META}
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/model/info", headers=_litellm_headers())
            resp.raise_for_status()
            raw_models = resp.json().get("data", [])
            for m in raw_models:
                litellm_model = str((m.get("litellm_params") or {}).get("model", ""))
                model_api_base = str((m.get("litellm_params") or {}).get("api_base", "") or "")
                # Match by api_base first (most specific - works even when
                # LiteLLM redacts the api_key from /model/info responses).
                matched = False
                for key_name, meta in _PROVIDER_META.items():
                    if meta.get("api_base") and model_api_base and meta["api_base"] in model_api_base:
                        models_by_provider[key_name].append(m)
                        matched = True
                        break
                if not matched:
                    # Fall back to litellm prefix match
                    for key_name, meta in _PROVIDER_META.items():
                        if litellm_model.startswith(meta["prefix"]):
                            models_by_provider[key_name].append(m)
                            break
    except Exception as exc:
        logger.warning("Could not fetch LiteLLM models for providers view: %s", exc)

    # Fetch key status from K8s Secret
    key_status: dict[str, bool] = {}
    is_admin = (user.get("role") or "viewer") in ("admin",)
    if is_admin:
        try:
            from kubernetes import client as k8s_client

            secret = k8s_client.CoreV1Api().read_namespaced_secret(
                name=LLM_SECRET_NAME,
                namespace=os.getenv("POD_NAMESPACE", "ai-platform"),
            )
            data: dict[str, str] = getattr(secret, "data", None) or {}
            for key_name in _ALLOWED_SECRET_KEYS:
                key_status[key_name] = key_name in data and bool(data[key_name])
        except Exception as exc:
            logger.warning("Could not read LLM secret for providers view: %s", exc)

    # Build response
    providers = []
    for key_name, meta in _PROVIDER_META.items():
        raw = models_by_provider.get(key_name, [])
        provider_models = []
        for m in raw:
            provider_models.append(
                {
                    "model_name": m.get("model_name", ""),
                    "litellm_model": str((m.get("litellm_params") or {}).get("model", "")),
                    "id": str((m.get("model_info") or {}).get("id", "")),
                }
            )
        providers.append(
            {
                "key_name": key_name,
                "label": meta["label"],
                "prefix": meta["prefix"],
                "is_configured": key_status.get(key_name, False) if is_admin else None,
                "model_count": len(provider_models),
                "models": provider_models,
            }
        )

    return {"providers": providers}


@router.get("/llm/providers/{provider}/suggestions")
async def llm_provider_suggestions(provider: str, q: str = "", user=Depends(verify_token)):
    """Return model suggestions for a provider.

    Merges already-configured models from LiteLLM with live provider catalogs when
    available. Supports ``?q=`` for server-side filtering.
    """
    ensure_role(user, "viewer")
    if provider not in _PROVIDER_META:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    meta = _PROVIDER_META[provider]
    prefix = meta["prefix"]

    # Fetch already-configured models from LiteLLM for this provider
    configured: list[dict[str, str]] = []
    configured_ids: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/model/info", headers=_litellm_headers())
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                litellm_model = str((m.get("litellm_params") or {}).get("model", ""))
                model_api_base = str((m.get("litellm_params") or {}).get("api_base", "") or "")
                provider_api_base = meta.get("api_base", "")
                # Match by api_base first (works even when LiteLLM redacts api_key)
                is_match = False
                if provider_api_base and model_api_base and provider_api_base in model_api_base:
                    is_match = True
                elif not provider_api_base and litellm_model.startswith(prefix):
                    # Prefix match only for providers WITHOUT a custom api_base
                    is_match = True
                if is_match:
                    model_id = litellm_model[len(prefix) :] if litellm_model.startswith(prefix) else litellm_model
                    configured_ids.add(model_id)
                    configured.append(
                        {
                            "model_id": model_id,
                            "display_name": m.get("model_name", model_id),
                            "description": "Already configured",
                        }
                    )
    except Exception as exc:
        logger.warning("Could not fetch LiteLLM models for suggestions: %s", exc)

    # For OpenRouter, fetch live models from the API
    if provider == "OPENROUTER_API_KEY":
        or_key = _read_secret_key_value("OPENROUTER_API_KEY")
        live_models = await _fetch_openrouter_models(or_key)
        # Mark already-configured and merge
        live_suggestions = []
        for lm in live_models:
            entry = dict(lm)
            if lm["model_id"] in configured_ids:
                entry["description"] = "Already configured"
            live_suggestions.append(entry)

        # Apply search filter
        if q:
            ql = q.lower()
            live_suggestions = [
                s
                for s in live_suggestions
                if ql in s["model_id"].lower()
                or ql in s["display_name"].lower()
                or ql in s.get("description", "").lower()
            ]

        # Put configured first, then unconfigured, limit results
        configured_live = [s for s in live_suggestions if s.get("description") == "Already configured"]
        unconfigured_live = [s for s in live_suggestions if s.get("description") != "Already configured"]
        combined = configured_live + unconfigured_live
        return {"provider": provider, "suggestions": combined[:100]}

    if provider in {"OPENCODE_API_KEY", "OPENCODE_GO_API_KEY"}:
        provider_key = _read_secret_key_value(provider)
        if not provider_key:
            return {"provider": provider, "suggestions": [], "error": "No API key configured"}
        try:
            live_models = (
                await _fetch_opencode_zen_models(provider_key)
                if provider == "OPENCODE_API_KEY"
                else await _fetch_opencode_go_models(provider_key)
            )
        except Exception as exc:
            logger.warning("Failed to fetch live models for %s: %s", provider, exc)
            return {"provider": provider, "suggestions": [], "error": str(exc)}

        live_suggestions = []
        for lm in live_models:
            entry = dict(lm)
            if lm["model_id"] in configured_ids:
                entry["description"] = "Already configured"
            live_suggestions.append(entry)

        combined = configured + live_suggestions
        if q:
            combined = [s for s in combined if _suggestion_matches(s, q)]

        configured_live = [s for s in combined if s.get("description") == "Already configured"]
        unconfigured_live = [s for s in combined if s.get("description") != "Already configured"]
        return {"provider": provider, "suggestions": (configured_live + unconfigured_live)[:100]}

    # For GitHub Copilot, fetch live models from the Copilot API
    if provider == "GITHUB_COPILOT_TOKEN":
        cp_token = _read_secret_key_value("GITHUB_COPILOT_TOKEN")

        live_suggestions = configured.copy()
        if cp_token:
            live_models = await _fetch_copilot_models(cp_token)
            for lm in live_models:
                entry = dict(lm)
                if lm["model_id"] in configured_ids:
                    entry["description"] = "Already configured"
                live_suggestions.append(entry)

        if q:
            live_suggestions = [s for s in live_suggestions if _suggestion_matches(s, q)]

        configured_live = [s for s in live_suggestions if s.get("description") == "Already configured"]
        unconfigured_live = [s for s in live_suggestions if s.get("description") != "Already configured"]
        return {"provider": provider, "suggestions": (configured_live + unconfigured_live)[:100]}

    return {"provider": provider, "suggestions": configured[:100]}


@router.post("/llm/providers/{provider}/models", status_code=201)
async def llm_add_provider_model(provider: str, body: ProviderModelAdd, user=Depends(verify_token)):
    """Add a model to LiteLLM via the simplified provider-centric API."""
    ensure_role(user, "admin")
    if provider not in _PROVIDER_META:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    meta = _PROVIDER_META[provider]
    raw_alias = (body.alias or "").strip() or body.model_id.split("/")[-1]
    # Prefix Copilot aliases with "copilot-" to avoid collisions with direct OpenAI models
    alias = f"copilot-{raw_alias}" if provider == "GITHUB_COPILOT_TOKEN" else raw_alias
    litellm_model = f"{meta['prefix']}{body.model_id}"
    api_key_ref = f"os.environ/{provider}"

    # For Copilot, read the actual token from the K8s secret instead of using
    # os.environ/ reference, because the token is set dynamically after LiteLLM
    # pod start so the env var may not be present.
    actual_api_key: str | None = None
    actual_api_base: str | None = None
    if provider in {"GITHUB_COPILOT_TOKEN", "OPENCODE_API_KEY", "OPENCODE_GO_API_KEY"}:
        actual_api_key = _read_secret_key_value(provider)
        if not actual_api_key:
            raise HTTPException(status_code=400, detail=f"{meta['label']} credential is not configured.")
        if provider == "GITHUB_COPILOT_TOKEN":
            try:
                exchanged_token, resolved_api_endpoint = await _exchange_copilot_session_token(actual_api_key)
                actual_api_key = exchanged_token
                actual_api_base = resolved_api_endpoint or meta.get("api_base") or None
            except Exception as exc:
                logger.warning(
                    "Failed to exchange GitHub token for Copilot session token; falling back to stored OAuth token: %s",
                    exc,
                )
                actual_api_base = meta.get("api_base") or None
        else:
            actual_api_base = meta.get("api_base") or None

    litellm_params: dict[str, Any] = {
        "model": litellm_model,
        "api_key": actual_api_key if actual_api_key else api_key_ref,
    }
    if provider == "GITHUB_COPILOT_TOKEN":
        if actual_api_base:
            litellm_params["api_base"] = actual_api_base
    elif meta.get("api_base"):
        litellm_params["api_base"] = meta["api_base"]
    if meta.get("extra_headers"):
        litellm_params["extra_headers"] = json.loads(meta["extra_headers"])

    payload = {
        "model_name": alias,
        "litellm_params": litellm_params,
    }
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.post(
                f"{LITELLM_INTERNAL_URL}/model/new",
                headers={**_litellm_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (provider model add): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


# --------------------------------------------------------------------------- #
#  GitHub Copilot - OAuth Device Flow                                          #
# --------------------------------------------------------------------------- #

_COPILOT_CLIENT_ID = "Ov23li8tweQw6odWQebz"
_COPILOT_DEVICE_CODE_URL = "https://github.com/login/device/code"
_COPILOT_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"

# In-memory device flow state (keyed by user sub). Cleared on success/error.
_copilot_device_flows: dict[str, dict[str, Any]] = {}


def _normalized_search_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _suggestion_matches(entry: dict[str, str], query: str) -> bool:
    ql = query.lower()
    qn = _normalized_search_text(query)
    for text in (entry.get("model_id", ""), entry.get("display_name", ""), entry.get("description", "")):
        lowered = text.lower()
        if ql in lowered:
            return True
        if qn and qn in _normalized_search_text(text):
            return True
    return False


def _outbound_ssl_verify() -> str:
    return certifi.where()


async def _copilot_get_json(url: str, headers: dict[str, str]) -> Any:
    last_error: Exception | None = None
    for verify in (_outbound_ssl_verify(), False):
        try:
            async with httpx.AsyncClient(timeout=15.0, trust_env=True, verify=verify) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError:
            raise
        except httpx.TransportError as exc:
            last_error = exc
            if verify is not False:
                logger.warning(
                    "Copilot HTTPS request failed with certificate verification; retrying insecurely: %s", exc
                )
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Copilot request failed")


async def _exchange_copilot_session_token(github_oauth_token: str) -> tuple[str, str | None]:
    data = await _copilot_get_json(
        "https://api.github.com/copilot_internal/v2/token",
        {
            "Authorization": f"token {github_oauth_token}",
            "Accept": "application/json",
            "User-Agent": "GitHubCopilotChat/0.25.2024",
            "Editor-Version": "vscode/1.96.2",
            "Editor-Plugin-Version": "copilot-chat/0.25.2024",
        },
    )

    token = str(data.get("token") or "").strip()
    if not token:
        raise ValueError("Copilot token exchange response did not include a session token")

    endpoints = data.get("endpoints") if isinstance(data.get("endpoints"), dict) else {}
    api_endpoint = str(endpoints.get("api") or "").strip() or None
    return token, api_endpoint


@router.post("/copilot/auth/device")
async def copilot_auth_device(user=Depends(verify_token)):
    """Initiate GitHub OAuth device flow for Copilot."""
    ensure_role(user, "admin")
    user_id = user.get("sub", "unknown")

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                _COPILOT_DEVICE_CODE_URL,
                data={"client_id": _COPILOT_CLIENT_ID, "scope": "read:user"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Copilot device flow initiation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to contact GitHub for device auth") from exc

    user_code = data.get("user_code", "")
    verification_uri = data.get("verification_uri", "https://github.com/login/device")
    device_code = data.get("device_code", "")
    interval = int(data.get("interval", 5))

    if not device_code:
        raise HTTPException(status_code=502, detail="GitHub did not return a device code")

    _copilot_device_flows[user_id] = {
        "device_code": device_code,
        "interval": interval,
    }

    return {
        "user_code": user_code,
        "verification_uri": verification_uri,
        "interval": interval,
    }


@router.post("/copilot/auth/poll")
async def copilot_auth_poll(user=Depends(verify_token)):
    """Poll GitHub for device flow completion. On success stores token in K8s secret."""
    ensure_role(user, "admin")
    user_id = user.get("sub", "unknown")
    flow = _copilot_device_flows.get(user_id)
    if not flow:
        raise HTTPException(status_code=400, detail="No pending device flow. Call /api/copilot/auth/device first.")

    device_code = flow["device_code"]
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                _COPILOT_ACCESS_TOKEN_URL,
                data={
                    "client_id": _COPILOT_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Copilot token poll failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to contact GitHub for token") from exc

    # Check for pending/slow_down/error states
    error = data.get("error")
    if error == "authorization_pending":
        return {"status": "pending"}
    if error == "slow_down":
        new_interval = int(data.get("interval", flow["interval"] + 5))
        flow["interval"] = new_interval
        return {"status": "pending", "interval": new_interval}
    if error:
        _copilot_device_flows.pop(user_id, None)
        return {"status": "error", "error": data.get("error_description", error)}

    access_token = data.get("access_token", "").strip()
    if not access_token:
        _copilot_device_flows.pop(user_id, None)
        return {"status": "error", "error": "No access token in GitHub response"}

    # Store token in K8s secret
    try:
        import base64

        from kubernetes import client as k8s_client

        ns = os.getenv("POD_NAMESPACE", "ai-platform")
        api = k8s_client.CoreV1Api()
        secret = api.read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
        existing_data = getattr(secret, "data", None) or {}
        existing_data["GITHUB_COPILOT_TOKEN"] = base64.b64encode(access_token.encode("utf-8")).decode("ascii")
        secret.data = existing_data  # type: ignore[union-attr]
        api.replace_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns, body=secret)
        logger.info("Stored Copilot token for user %s", user_id)
    except Exception as exc:
        logger.error("Failed to store Copilot token in K8s secret: %s", exc)
        _copilot_device_flows.pop(user_id, None)
        raise HTTPException(status_code=502, detail="Token received but failed to store in cluster secret") from exc

    _copilot_device_flows.pop(user_id, None)
    return {"status": "success"}


@router.get("/copilot/auth/status")
def copilot_auth_status(user=Depends(verify_token)):
    """Check if a Copilot token is stored in the K8s secret."""
    ensure_role(user, "admin")
    try:
        from kubernetes import client as k8s_client

        secret = k8s_client.CoreV1Api().read_namespaced_secret(
            name=LLM_SECRET_NAME,
            namespace=os.getenv("POD_NAMESPACE", "ai-platform"),
        )
        data: dict[str, str] = getattr(secret, "data", None) or {}
        is_set = "GITHUB_COPILOT_TOKEN" in data and bool(data["GITHUB_COPILOT_TOKEN"])
        return {"connected": is_set}
    except Exception as exc:
        logger.warning("Failed to check Copilot status: %s", exc)
        return {"connected": False}


if __name__ == "__main__":
    import uvicorn  # type: ignore[import-untyped]

    uvicorn.run(app, host="0.0.0.0", port=8080)


# --------------------------------------------------------------------------- #
#  Notification SSE stream                                                     #
# --------------------------------------------------------------------------- #
