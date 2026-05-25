"""McpConnection reconciler — mirrors McpConnection CRDs to PostgreSQL.

§S6-1: Makes MCP connections Kubernetes-native. The operator watches
McpConnection CRDs and syncs their spec/status to the shared ``mcp_connections``
PostgreSQL table that the API gateway reads from.

Architecture:
  - CRD (desired state) → operator controller → PostgreSQL (source of truth)
  - API gateway reads from same PostgreSQL table → `/api/v1/mcp/connections`
  - Existing DB connections get migrated to CRD resources on startup (resume)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from reconcile import execute_reconcile, log_operator_event
from sqlalchemy import JSON, Column, DateTime, Index, String, UniqueConstraint
from sqlalchemy.exc import IntegrityError

from state_store import STATE_DB_ENABLED, db_session, utc_now

logger = logging.getLogger("operator.controllers.mcp_connection")

# ---------------------------------------------------------------------------
# McpConnectionRow — mirrors api-gateway.auth_store.McpConnectionRow
# for operator-side read/write to the shared mcp_connections table.
# ---------------------------------------------------------------------------

from state_store import Base  # noqa: E402


class _McpConnectionRow(Base):
    """Operator-side model for the shared ``mcp_connections`` table."""

    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("namespace", "slug", name="uq_mcp_connections_namespace_slug"),
        Index("idx_mcp_connections_crd_ref", "namespace", "crd_name", unique=True),
        {"extend_existing": True},
    )

    id = Column(String(64), primary_key=True)
    namespace = Column(String(128), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    slug = Column(String(128), nullable=False)
    server_id = Column(String(128), nullable=False, index=True)
    transport = Column(String(32), nullable=False)
    auth_type = Column(String(64), nullable=False, default="none")
    config_json = Column(JSON, nullable=False, default=dict)
    credential_metadata_json = Column(JSON, nullable=False, default=list)
    secret_name = Column(String(253), nullable=True)
    validation_status = Column(String(32), nullable=False, default="draft")
    validation_message = Column(String(1024), nullable=True)
    validation_detail_json = Column(JSON, nullable=True)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)
    crd_name = Column(String(128), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    """Minimal slug for a connection name (consistent with api-gateway)."""
    return (
        str(name)
        .strip()
        .lower()
        .replace(" ", "-")
        .replace("_", "-")
        .replace("/", "-")
        .replace(":", "-")
    )


def _json_clone(obj: Any) -> Any:
    """Deep-clone via JSON round-trip to avoid mutation surprises."""
    if obj is None:
        return None
    return json.loads(json.dumps(obj, default=str))


def _extract_credential_metadata(entry: dict[str, Any], configured_keys: set[str]) -> list[dict[str, Any]]:
    """Build credential metadata entries from the CRD credentialSecretRef."""
    ref = entry.get("credentialSecretRef")
    if not isinstance(ref, dict):
        return []
    secret_name = str(ref.get("name", "")).strip()
    if not secret_name:
        return []
    key_map = ref.get("keys") or {}
    metadata_entries: list[dict[str, Any]] = []
    for logical_key, secret_key in (key_map.items() if isinstance(key_map, dict) else []):
        metadata_entries.append({
            "key": str(logical_key),
            "secretKey": str(secret_key),
            "label": str(logical_key).replace("_", " ").title(),
        })
    return metadata_entries


def _find_mcp_connection_cr(name: str, namespace: str) -> dict[str, Any] | None:
    """Look up the McpConnection CR that backs a DB row."""
    try:
        custom_api = kubernetes.client.CustomObjectsApi()
        return custom_api.get_namespaced_custom_object(
            group="kubesynapse.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="mcpconnections",
            name=name,
        )  # type: ignore[return-value]
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _patch_connection_status(
    namespace: str,
    name: str,
    *,
    phase: str | None = None,
    validation_status: str | None = None,
    validation_message: str | None = None,
    last_validated_at: str | None = None,
    binding_count: int | None = None,
    connection_id: str | None = None,
    oauth_status: dict[str, Any] | None = None,
    conditions: list[dict[str, Any]] | None = None,
) -> None:
    """Patch the status subresource of an McpConnection CR with 409 retry."""
    from services.k8s import patch_custom_status

    status_patch: dict[str, Any] = {}
    if phase is not None:
        status_patch["phase"] = phase
    if validation_status is not None:
        status_patch["validationStatus"] = validation_status
    if validation_message is not None:
        status_patch["validationMessage"] = validation_message
    if last_validated_at is not None:
        status_patch["lastValidatedAt"] = last_validated_at
    if binding_count is not None:
        status_patch["bindingCount"] = binding_count
    if connection_id is not None:
        status_patch["connectionId"] = connection_id
    if oauth_status is not None:
        status_patch["oauthStatus"] = oauth_status
    if conditions is not None:
        status_patch["conditions"] = conditions

    if not status_patch:
        return

    try:
        patch_custom_status("mcpconnections", namespace, name, status_patch)
    except ApiException as exc:
        if exc.status == 404:
            logger.debug(
                "McpConnection %s/%s deleted before status could be patched.",
                namespace, name,
            )
            return
        logger.warning(
            "Failed to patch McpConnection status for '%s/%s': %s",
            namespace,
            name,
            exc,
        )


def _build_conditions(phase: str, *, reason: str = "", message: str = "") -> list[dict[str, Any]]:
    """Build standard Kubernetes status conditions."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conditions: list[dict[str, Any]] = []

    ready = phase not in ("Pending", "Failed", "Deleting")
    conditions.append({
        "type": "Ready",
        "status": "True" if ready else "False",
        "reason": reason or phase,
        "message": message or f"McpConnection is in {phase} phase",
        "lastTransitionTime": now,
    })

    if phase == "Validated":
        conditions.append({
            "type": "Validated",
            "status": "True",
            "reason": "ValidationSucceeded",
            "message": "Connection validation succeeded",
            "lastTransitionTime": now,
        })
    elif phase == "Failed":
        conditions.append({
            "type": "Validated",
            "status": "False",
            "reason": reason or "ProvisioningFailed",
            "message": message or "Connection provisioning failed",
            "lastTransitionTime": now,
        })

    return conditions


def _count_agent_bindings(namespace: str, connection_id: str) -> int:
    """Count how many AIAgents reference this MCP connection by its DB id."""
    try:
        custom_api = kubernetes.client.CustomObjectsApi()
        agents = custom_api.list_namespaced_custom_object(
            group="kubesynapse.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="aiagents",
        ).get("items", [])
        count = 0
        for agent in agents:
            connections = (agent.get("spec") or {}).get("mcpConnections") or []
            for conn in connections:
                if isinstance(conn, dict) and conn.get("connectionId") == connection_id:
                    count += 1
        return count
    except ApiException:
        return 0


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------


def _reconcile_mcp_connection(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger) -> None:
    """Sync an McpConnection CRD to the PostgreSQL mcp_connections table."""
    if not STATE_DB_ENABLED:
        log_operator_event(
            logger,
            logging.WARNING,
            "State DB is disabled; skipping McpConnection reconciliation.",
            resource_kind="McpConnection",
            name=name,
            namespace=namespace,
        )
        return

    server_id = str(spec.get("serverId") or "").strip()
    if not server_id:
        raise kopf.PermanentError("McpConnection spec must include a serverId.")

    transport = str(spec.get("transport") or "remote").strip().lower()
    auth_type = str(spec.get("authType") or "none").strip().lower()
    display_name = str(spec.get("displayName") or server_id).strip()
    config_raw = spec.get("config") or {}
    config = json.loads(json.dumps(config_raw, default=str)) if isinstance(config_raw, dict) else {}

    credential_metadata = _extract_credential_metadata(spec, set())
    secret_name = str((spec.get("credentialSecretRef") or {}).get("name") or "").strip() or None

    with db_session() as session:
        existing_row = (
            session.query(_McpConnectionRow)
            .filter(
                _McpConnectionRow.namespace == namespace,
                _McpConnectionRow.crd_name == name,
            )
            .one_or_none()
        )

        if existing_row is not None:
            # Update existing row
            existing_row.server_id = server_id
            existing_row.name = display_name
            existing_row.slug = _slugify(display_name)
            existing_row.transport = transport
            existing_row.auth_type = auth_type
            existing_row.config_json = config
            existing_row.credential_metadata_json = credential_metadata
            existing_row.secret_name = secret_name
            existing_row.updated_at = utc_now()
            connection_id = existing_row.id

            log_operator_event(
                logger,
                logging.INFO,
                "Updated McpConnection DB record.",
                resource_kind="McpConnection",
                name=name,
                namespace=namespace,
                connectionId=connection_id,
                serverId=server_id,
                transport=transport,
            )
        else:
            # Create new row
            connection_id = uuid.uuid4().hex
            row = _McpConnectionRow(
                id=connection_id,
                namespace=namespace,
                name=display_name,
                slug=_slugify(display_name),
                server_id=server_id,
                transport=transport,
                auth_type=auth_type,
                config_json=config,
                credential_metadata_json=credential_metadata,
                secret_name=secret_name,
                validation_status="draft",
                crd_name=name,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                # Row may have been created by API gateway — try to find and update
                existing_by_name = (
                    session.query(_McpConnectionRow)
                    .filter(
                        _McpConnectionRow.namespace == namespace,
                        _McpConnectionRow.slug == _slugify(display_name),
                    )
                    .one_or_none()
                )
                if existing_by_name is not None:
                    existing_by_name.crd_name = name
                    existing_by_name.server_id = server_id
                    existing_by_name.transport = transport
                    existing_by_name.auth_type = auth_type
                    existing_by_name.config_json = config
                    existing_by_name.credential_metadata_json = credential_metadata
                    existing_by_name.secret_name = secret_name
                    existing_by_name.updated_at = utc_now()
                    connection_id = existing_by_name.id
                    session.flush()
                else:
                    raise

            log_operator_event(
                logger,
                logging.INFO,
                "Created McpConnection DB record from CRD.",
                resource_kind="McpConnection",
                name=name,
                namespace=namespace,
                connectionId=connection_id,
                serverId=server_id,
                transport=transport,
            )

    # Compute binding count and patch CRD status
    binding_count = _count_agent_bindings(namespace, connection_id)
    conditions = _build_conditions(
        "Provisioned",
        reason="Provisioned",
        message=f"McpConnection '{display_name}' provisioned with id {connection_id}",
    )
    _patch_connection_status(
        namespace,
        name,
        phase="Provisioned",
        validation_status="draft",
        connection_id=connection_id,
        binding_count=binding_count,
        conditions=conditions,
    )


# ---------------------------------------------------------------------------
# Migration: sync existing DB-only connections to CRD resources on startup
# ---------------------------------------------------------------------------


def _migrate_db_connections_to_crds(logger: logging.Logger) -> None:
    """Create McpConnection CRD resources for connections that exist only in the DB.

    Called at operator startup (resume). Each DB row without a corresponding CRD
    gets a McpConnection CRD created.
    """
    if not STATE_DB_ENABLED:
        return

    try:
        custom_api = kubernetes.client.CustomObjectsApi()
    except Exception:
        logger.warning("Kubernetes API unavailable; skipping MCP connection migration.")
        return

    try:
        with db_session() as session:
            rows = session.query(_McpConnectionRow).filter(_McpConnectionRow.crd_name.is_(None)).all()

            migrated_count = 0
            for row in rows:
                namespace = str(row.namespace or "default").strip() or "default"
                crd_name = f"mcp-{row.slug}"
                try:
                    body: dict[str, Any] = {
                        "apiVersion": "kubesynapse.ai/v1alpha1",
                        "kind": "McpConnection",
                        "metadata": {
                            "name": crd_name,
                            "namespace": namespace,
                            "labels": {
                                "kubesynapse.ai/managed-by": "operator",
                                "kubesynapse.ai/migrated": "true",
                            },
                        },
                        "spec": {
                            "serverId": row.server_id,
                            "transport": row.transport,
                            "authType": row.auth_type,
                            "displayName": row.name,
                            "config": row.config_json or {},
                        },
                    }
                    custom_api.create_namespaced_custom_object(
                        group="kubesynapse.ai",
                        version="v1alpha1",
                        namespace=namespace,
                        plural="mcpconnections",
                        body=body,
                    )
                    # Update the DB row to mark it as migrated
                    row.crd_name = crd_name
                    migrated_count += 1
                    logger.info("Migrated DB MCP connection '%s' to CRD '%s/%s'.", row.name, namespace, crd_name)
                except ApiException as exc:
                    if exc.status == 409:
                        # Already exists — just link
                        row.crd_name = crd_name
                        logger.info("Linked existing CRD for MCP connection '%s' (%s/%s).", row.name, namespace, crd_name)
                    else:
                        logger.warning(
                            "Failed to migrate MCP connection '%s' to CRD: %s",
                            row.name,
                            exc,
                        )
            # Commit happens automatically on successful context exit
    except Exception as exc:
        # Table may not exist yet — this is fine on first install
        logger.debug("Could not query mcp_connections for migration: %s", exc)
        return

    if migrated_count:
        log_operator_event(
            logger,
            logging.INFO,
            f"Migrated {migrated_count} existing MCP connections to CRD resources.",
            resource_kind="McpConnection",
            action="migrate",
            migratedCount=migrated_count,
        )


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------


@kopf.on.create("kubesynapse.ai", "v1alpha1", "mcpconnections")  # type: ignore[arg-type]
def create_mcp_connection(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> None:
    """Provision a new McpConnection into the database."""
    del kwargs
    execute_reconcile(
        lambda: _reconcile_mcp_connection(spec, name, namespace, logger),
        logger=logger,
        action="create-mcp-connection",
        resource_kind="McpConnection",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling McpConnection create event.",
        success_message="McpConnection provisioned to database.",
        serverId=spec.get("serverId"),
        transport=spec.get("transport"),
    )


@kopf.on.update("kubesynapse.ai", "v1alpha1", "mcpconnections")  # type: ignore[arg-type]
def update_mcp_connection(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> None:
    """Sync an updated McpConnection CRD to the database."""
    del kwargs
    execute_reconcile(
        lambda: _reconcile_mcp_connection(spec, name, namespace, logger),
        logger=logger,
        action="update-mcp-connection",
        resource_kind="McpConnection",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling McpConnection update event.",
        success_message="McpConnection database record updated.",
        serverId=spec.get("serverId"),
    )


@kopf.on.resume("kubesynapse.ai", "v1alpha1", "mcpconnections")  # type: ignore[arg-type]
def resume_mcp_connection(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> None:
    """Re-reconcile an existing McpConnection on operator restart."""
    del kwargs
    execute_reconcile(
        lambda: _reconcile_mcp_connection(spec, name, namespace, logger),
        logger=logger,
        action="resume-mcp-connection",
        resource_kind="McpConnection",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling existing McpConnection on operator startup.",
        success_message="McpConnection resume reconciliation completed.",
        serverId=spec.get("serverId"),
    )


@kopf.on.delete("kubesynapse.ai", "v1alpha1", "mcpconnections")  # type: ignore[arg-type]
def delete_mcp_connection(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    """Delete the McpConnection database record (but keep the K8s Secret)."""
    del kwargs

    if not STATE_DB_ENABLED:
        log_operator_event(
            logger,
            logging.WARNING,
            "State DB is disabled; skipping McpConnection deletion.",
            resource_kind="McpConnection",
            name=name,
            namespace=namespace,
            action="delete-mcp-connection",
        )
        return

    try:
        with db_session() as session:
            deleted = (
                session.query(_McpConnectionRow)
                .filter(_McpConnectionRow.namespace == namespace, _McpConnectionRow.crd_name == name)
                .delete()
            )
            if deleted:
                log_operator_event(
                    logger,
                    logging.INFO,
                    "Deleted McpConnection DB record.",
                    resource_kind="McpConnection",
                    name=name,
                    namespace=namespace,
                    action="delete-mcp-connection",
                )
            else:
                # Fallback: try by id or name match
                row = (
                    session.query(_McpConnectionRow)
                    .filter(
                        _McpConnectionRow.namespace == namespace,
                        _McpConnectionRow.server_id == str(spec.get("serverId") or "").strip() or name,
                    )
                    .one_or_none()
                )
                if row:
                    session.delete(row)
                    log_operator_event(
                        logger,
                        logging.INFO,
                        "Deleted McpConnection DB record (fallback match).",
                        resource_kind="McpConnection",
                        name=name,
                        namespace=namespace,
                        action="delete-mcp-connection",
                        connectionId=row.id,
                    )
    except Exception as exc:
        log_operator_event(
            logger,
            logging.ERROR,
            "Failed to delete McpConnection DB record.",
            resource_kind="McpConnection",
            name=name,
            namespace=namespace,
            action="delete-mcp-connection",
            error=str(exc),
        )
        raise
