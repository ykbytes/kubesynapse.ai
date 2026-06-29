"""Optimization ROI study commands."""

from __future__ import annotations

from typing import Any

import typer

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import fatal, print_detail, print_json_output, print_table

optimizations_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl optimizations studies --workflow daily-standup\n"
        "  agentctl optimizations show opt-study-123\n"
        "  agentctl optimizations trace opt-study-123 --candidate-id cand-123\n"
        "  agentctl optimizations comparison opt-study-123"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


def _study_response_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _candidate_list(study: dict[str, Any]) -> list[dict[str, Any]]:
    items = study.get("candidates")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _normalise_study(item: dict[str, Any]) -> dict[str, Any]:
    proof_gate = item.get("proof_gate") if isinstance(item.get("proof_gate"), dict) else {}
    candidates = _candidate_list(item)
    trials = item.get("trials") if isinstance(item.get("trials"), list) else []
    normalized = dict(item)
    normalized["proof_status"] = str(
        item.get("proof_status")
        or proof_gate.get("status")
        or item.get("status")
        or "pending"
    )
    normalized["candidate_count"] = len(candidates)
    normalized["trial_count"] = len(trials)
    return normalized


def _select_candidate(study: dict[str, Any], candidate_id: str | None) -> dict[str, Any]:
    candidates = _candidate_list(study)
    if not candidates:
        fatal("This study has no candidates yet.")
    if candidate_id:
        for candidate in candidates:
            if str(candidate.get("id")) == candidate_id:
                return candidate
        fatal(f"Candidate '{candidate_id}' was not found in this study.")
    return candidates[-1]


@optimizations_app.command("studies")
def studies_list(
    workflow_name: str | None = typer.Option(None, "--workflow", help="Filter by workflow name."),
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    offset: int = typer.Option(0, "--offset", min=0),
) -> None:
    """List optimization ROI studies in the current namespace."""
    settings = get_settings()
    params: dict[str, Any] = {**_ns_params(), "limit": limit, "offset": offset}
    if workflow_name:
        params["workflow_name"] = workflow_name
    try:
        with _api() as client:
            data = client.get("/api/optimizations/studies", params=params)
    except ApiError as exc:
        fatal(str(exc))

    studies = [_normalise_study(item) for item in _study_response_items(data)]
    print_table(
        studies,
        columns=[
            ("ID", "id"),
            ("WORKFLOW", "workflow_name"),
            ("PROOF", "proof_status"),
            ("CANDIDATES", "candidate_count"),
            ("TRIALS", "trial_count"),
            ("CREATED", "created_at"),
        ],
        title=f"Optimization studies in {settings.namespace}",
        output_format=settings.output_format,
    )


@optimizations_app.command("show")
def study_show(study_id: str = typer.Argument(..., help="Optimization study ID.")) -> None:
    """Show one optimization study, including its candidate inventory."""
    settings = get_settings()
    try:
        with _api() as client:
            data = client.get(f"/api/optimizations/studies/{study_id}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    if not isinstance(data, dict):
        fatal("Unexpected study payload.")

    normalized = _normalise_study(data)
    detail = {
        "id": normalized.get("id"),
        "workflow_name": normalized.get("workflow_name"),
        "namespace": normalized.get("namespace"),
        "optimizer_agent_name": normalized.get("optimizer_agent_name"),
        "proof_status": normalized.get("proof_status"),
        "baseline_execution_ids": normalized.get("baseline_execution_ids"),
        "candidate_count": normalized.get("candidate_count"),
        "trial_count": normalized.get("trial_count"),
        "created_at": normalized.get("created_at"),
        "updated_at": normalized.get("updated_at"),
    }
    print_detail(
        detail,
        title=f"Optimization Study: {study_id}",
        output_format=settings.output_format,
    )

    candidates = _candidate_list(data)
    if candidates:
        print_table(
            [
                {
                    "id": candidate.get("id"),
                    "name": candidate.get("name") or candidate.get("candidate_workflow_name"),
                    "approval_status": candidate.get("approval_status"),
                    "applied": candidate.get("applied"),
                    "created_at": candidate.get("created_at"),
                }
                for candidate in candidates
            ],
            columns=[
                ("CANDIDATE", "name"),
                ("ID", "id"),
                ("APPROVAL", "approval_status"),
                ("APPLIED", "applied"),
                ("CREATED", "created_at"),
            ],
            title="Candidates",
            output_format=settings.output_format,
        )


@optimizations_app.command("trace")
def study_trace(
    study_id: str = typer.Argument(..., help="Optimization study ID."),
    candidate_id: str | None = typer.Option(None, "--candidate-id", help="Candidate ID. Defaults to the latest."),
) -> None:
    """Show the persisted observable optimizer trace for a candidate."""
    settings = get_settings()
    try:
        with _api() as client:
            study = client.get(f"/api/optimizations/studies/{study_id}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    if not isinstance(study, dict):
        fatal("Unexpected study payload.")

    candidate = _select_candidate(study, candidate_id)
    trace = candidate.get("optimizer_trace")
    if not isinstance(trace, dict) or not trace:
        fatal("This candidate does not have a persisted optimizer trace.")

    payload = {
        "study_id": study_id,
        "candidate_id": candidate.get("id"),
        "candidate_name": candidate.get("name") or candidate.get("candidate_workflow_name"),
        "optimizer_trace": trace,
    }
    print_detail(
        payload,
        title=f"Optimizer Trace: {payload['candidate_name']}",
        output_format=settings.output_format,
    )


@optimizations_app.command("roi")
def study_roi(
    study_id: str = typer.Argument(..., help="Optimization study ID."),
    candidate_id: str | None = typer.Option(None, "--candidate-id", help="Candidate ID."),
) -> None:
    """Show ROI verification status and metric deltas for a study candidate."""
    settings = get_settings()
    params = _ns_params()
    if candidate_id:
        params["candidate_id"] = candidate_id
    try:
        with _api() as client:
            data = client.get(f"/api/optimizations/studies/{study_id}/roi", params=params)
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"ROI: {study_id}", output_format=settings.output_format)


@optimizations_app.command("comparison")
def study_comparison(
    study_id: str = typer.Argument(..., help="Optimization study ID."),
    candidate_id: str | None = typer.Option(None, "--candidate-id", help="Candidate ID."),
) -> None:
    """Show baseline-versus-candidate comparison for a study."""
    settings = get_settings()
    params = _ns_params()
    if candidate_id:
        params["candidate_id"] = candidate_id
    try:
        with _api() as client:
            data = client.get(f"/api/optimizations/studies/{study_id}/comparison", params=params)
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Comparison: {study_id}", output_format=settings.output_format)
