"""Optimization ROI study commands."""

from __future__ import annotations

from pathlib import Path
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
        "  agentctl optimizations candidates --workflow daily-standup\n"
        "  agentctl optimizations candidate cand-123\n"
        "  agentctl optimizations manifest cand-123 --output candidate.yaml\n"
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


def _expected_gain(candidate: dict[str, Any]) -> str:
    savings = candidate.get("expected_savings")
    if not isinstance(savings, dict):
        return "pending"
    metrics = (
        ("time", "duration_saved_percent"),
        ("tokens", "tokens_saved_percent"),
        ("tools", "tool_calls_saved_percent"),
        ("cost", "cost_saved_percent"),
    )
    values = [
        f"{round(value)}% {label}"
        for label, key in metrics
        if isinstance((value := savings.get(key)), (int, float))
    ]
    return " · ".join(values[:3]) or "pending"


def _candidate_state(candidate: dict[str, Any]) -> str:
    if candidate.get("lifecycle_state") == "archived":
        return "archived"
    if candidate.get("status") == "promoted":
        return "promoted"
    return str(candidate.get("approval_status") or candidate.get("status") or "pending")


def _confirm(message: str, assume_yes: bool) -> None:
    if not assume_yes and not typer.confirm(message):
        raise typer.Abort()


@optimizations_app.command("candidates")
def candidates_list(
    workflow_name: str | None = typer.Option(None, "--workflow", help="Filter by source workflow name."),
    status: str | None = typer.Option(None, "--status", help="Filter by lifecycle or approval state."),
    approval_status: str | None = typer.Option(None, "--approval", help="Filter by approval state."),
    tag: str | None = typer.Option(None, "--tag", help="Filter by candidate tag."),
    search: str | None = typer.Option(None, "--search", help="Search candidate name, ID, workflow, or tags."),
    include_archived: bool = typer.Option(False, "--include-archived", help="Include archived candidates."),
    limit: int = typer.Option(100, "--limit", min=1, max=200),
    offset: int = typer.Option(0, "--offset", min=0),
) -> None:
    """List the durable candidate registry across optimization studies."""
    settings = get_settings()
    params: dict[str, Any] = {
        **_ns_params(),
        "include_archived": include_archived,
        "limit": limit,
        "offset": offset,
    }
    for key, value in (
        ("workflow_name", workflow_name),
        ("status", status),
        ("approval_status", approval_status),
        ("tag", tag),
        ("search", search),
    ):
        if value:
            params[key] = value
    try:
        with _api() as client:
            data = client.get("/api/optimizations/candidates", params=params)
    except ApiError as exc:
        fatal(str(exc))

    candidates = _study_response_items(data)
    rows = [
        {
            **candidate,
            "name": candidate.get("candidate_workflow_name") or candidate.get("name"),
            "state": _candidate_state(candidate),
            "expected_gain": _expected_gain(candidate),
            "tags_display": ", ".join(str(tag) for tag in candidate.get("tags") or []),
        }
        for candidate in candidates
    ]
    print_table(
        rows,
        columns=[
            ("CANDIDATE", "name"),
            ("STATE", "state"),
            ("EXPECTED GAIN", "expected_gain"),
            ("TRIALS", "trial_count"),
            ("TAGS", "tags_display"),
            ("CREATED", "created_at"),
        ],
        title=f"Optimization candidates in {settings.namespace}",
        output_format=settings.output_format,
    )


@optimizations_app.command("candidate")
def candidate_show(candidate_id: str = typer.Argument(..., help="Optimization candidate ID.")) -> None:
    """Show one persisted candidate, its study, resources, and trials."""
    settings = get_settings()
    try:
        with _api() as client:
            data = client.get(f"/api/optimizations/candidates/{candidate_id}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    if not isinstance(data, dict) or not isinstance(data.get("candidate"), dict):
        fatal("Unexpected candidate payload.")
    candidate = dict(data["candidate"])
    candidate["manifest_resource_count"] = len(candidate.get("manifest_bundle") or [])
    candidate["trial_count"] = len(data.get("trials") or [])
    payload = {**data, "candidate": candidate}
    print_detail(payload, title=f"Optimization Candidate: {candidate_id}", output_format=settings.output_format)


@optimizations_app.command("manifest")
def candidate_manifest(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    output: str = typer.Option("-", "--output", "-o", help="Write YAML to a file, or '-' for stdout."),
) -> None:
    """Download the exact validated candidate manifest bundle."""
    try:
        with _api() as client:
            manifest = client.get_text(
                f"/api/optimizations/candidates/{candidate_id}/manifest",
                accept="application/yaml",
            )
    except ApiError as exc:
        fatal(str(exc))
    if output == "-":
        typer.echo(manifest, nl=False)
        return
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest, encoding="utf-8")
    typer.echo(f"Wrote {path}")


@optimizations_app.command("tags")
def candidate_tags(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    add: list[str] | None = typer.Option(None, "--add", help="Tag to add. Repeat for multiple tags."),
    remove: list[str] | None = typer.Option(None, "--remove", help="Tag to remove. Repeat for multiple tags."),
) -> None:
    """Add or remove searchable candidate tags."""
    settings = get_settings()
    try:
        with _api() as client:
            detail = client.get(f"/api/optimizations/candidates/{candidate_id}", params=_ns_params())
            candidate = detail.get("candidate") if isinstance(detail, dict) else None
            if not isinstance(candidate, dict):
                fatal("Unexpected candidate payload.")
            tags = [str(tag) for tag in candidate.get("tags") or []]
            removals = {value.casefold() for value in (remove or [])}
            tags = [tag for tag in tags if tag.casefold() not in removals]
            known = {tag.casefold() for tag in tags}
            for tag in add or []:
                value = tag.strip()
                if value and value.casefold() not in known:
                    tags.append(value)
                    known.add(value.casefold())
            result = client.patch(f"/api/optimizations/candidates/{candidate_id}", payload={"tags": tags})
    except ApiError as exc:
        fatal(str(exc))
    print_detail(result, title=f"Candidate Tags: {candidate_id}", output_format=settings.output_format)


@optimizations_app.command("archive")
def candidate_archive(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Archive a candidate while preserving its audit history."""
    _confirm(f"Archive candidate {candidate_id}?", yes)
    settings = get_settings()
    try:
        with _api() as client:
            result = client.delete(f"/api/optimizations/candidates/{candidate_id}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    print_detail(result, title=f"Archived Candidate: {candidate_id}", output_format=settings.output_format)


@optimizations_app.command("approve")
def candidate_approve(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    reason: str = typer.Option(..., "--reason", help="Audit reason for approval."),
) -> None:
    """Approve a candidate for apply and trial execution."""
    settings = get_settings()
    try:
        with _api() as client:
            result = client.post(
                f"/api/optimizations/candidates/{candidate_id}/approval",
                payload={"decision": "approved", "reason": reason},
            )
    except ApiError as exc:
        fatal(str(exc))
    print_detail(result, title=f"Approved Candidate: {candidate_id}", output_format=settings.output_format)


@optimizations_app.command("apply")
def candidate_apply(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    execute: bool = typer.Option(False, "--execute", help="Apply resources instead of validating a dry run."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt for real apply."),
) -> None:
    """Validate a candidate with server-side dry run, or explicitly apply it."""
    if execute:
        _confirm(f"Apply candidate {candidate_id} to the cluster?", yes)
    settings = get_settings()
    try:
        with _api() as client:
            result = client.post(
                f"/api/optimizations/candidates/{candidate_id}/apply",
                payload={"dry_run": not execute},
            )
    except ApiError as exc:
        fatal(str(exc))
    title = "Applied Candidate" if execute else "Candidate Dry Run"
    print_detail(result, title=f"{title}: {candidate_id}", output_format=settings.output_format)


@optimizations_app.command("run")
def candidate_run(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    input_text: str = typer.Option("", "--input", help="Workflow trial input."),
    baseline_execution_id: str | None = typer.Option(None, "--baseline-execution", help="Baseline run to pair."),
    notes: str | None = typer.Option(None, "--notes", help="Trial audit notes."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the execution confirmation."),
) -> None:
    """Run an approved candidate and persist a paired ROI trial."""
    _confirm(f"Run candidate {candidate_id}?", yes)
    settings = get_settings()
    try:
        with _api() as client:
            result = client.post(
                f"/api/optimizations/candidates/{candidate_id}/run",
                payload={
                    "input": input_text,
                    "baseline_execution_id": baseline_execution_id,
                    "notes": notes,
                },
            )
    except ApiError as exc:
        fatal(str(exc))
    print_detail(result, title=f"Candidate Trial: {candidate_id}", output_format=settings.output_format)


@optimizations_app.command("promote")
def candidate_promote(
    candidate_id: str = typer.Argument(..., help="Optimization candidate ID."),
    reason: str = typer.Option(..., "--reason", help="Promotion audit reason."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the promotion confirmation."),
) -> None:
    """Promote a proof-gate winner after explicit confirmation."""
    _confirm(f"Promote candidate {candidate_id}?", yes)
    settings = get_settings()
    try:
        with _api() as client:
            result = client.post(
                f"/api/optimizations/candidates/{candidate_id}/promotion",
                payload={"reason": reason},
            )
    except ApiError as exc:
        fatal(str(exc))
    print_detail(result, title=f"Promoted Candidate: {candidate_id}", output_format=settings.output_format)


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
