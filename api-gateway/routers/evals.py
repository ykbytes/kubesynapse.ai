"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Depends

router = APIRouter(tags=["evals"])

@router.get("/evals", response_model=list[EvalInfo])
def list_evals(namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    evals = sorted(
        [eval_info_from_resource(item) for item in list_custom_resources("agentevals", namespace)],
        key=lambda item: item.name,
    )
    for item in evals:
        _sync_eval_memory(item)
    return evals


@router.post("/evals", response_model=EvalInfo, status_code=201)
def create_eval(
    body: EvalRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    created = create_custom_resource(
        "agentevals",
        namespace,
        body.name,
        build_eval_spec(body),
    )
    return eval_info_from_resource(created)


def _sync_eval_memory(info: EvalInfo) -> None:
    if info.phase == "pending":
        return
    try:
        summary = info.summary or {}
        record_eval_outcome_memory(
            info.namespace,
            info.agent_ref,
            info.name,
            phase=info.phase,
            passed=info.passed,
            summary=summary if isinstance(summary, dict) else None,
        )
        if info.passed is not None:
            apply_memory_feedback(
                info.namespace,
                info.agent_ref,
                session_id=info.name,
                success=bool(info.passed),
            )
    except Exception as exc:
        logger.debug("Failed to sync eval memory for %s: %s", info.name, exc)


@router.get("/evals/{eval_name}", response_model=EvalInfo)
def get_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    info = eval_info_from_resource(read_custom_resource("agentevals", eval_name, namespace, "Eval"))
    _sync_eval_memory(info)
    return info


@router.patch("/evals/{eval_name}", response_model=EvalInfo)
def update_eval(
    eval_name: str,
    body: EvalUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    updated = replace_custom_resource_spec("agentevals", eval_name, namespace, build_eval_spec(body))
    return eval_info_from_resource(updated)


@router.delete("/evals/{eval_name}", response_model=DeleteResponse)
def delete_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    delete_custom_resource("agentevals", eval_name, namespace, "Eval")
    return DeleteResponse(status="deleted", kind="eval", name=eval_name, namespace=namespace)
