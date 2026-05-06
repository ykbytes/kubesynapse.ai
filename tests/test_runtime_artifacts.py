"""Artifacts tier conformance tests for KubeSynth Runtime API v1.

These tests validate the **Artifacts** tier endpoints:

- ``GET /artifacts/list``
- ``GET /artifacts/download``
- ``GET /artifacts/zip``

Tests are skipped when the runtime does not advertise ``artifacts`` in its
``/capabilities`` tiers array.
"""

from __future__ import annotations

import httpx
import pytest

from tests.runtime_conftest import (
    ARTIFACTS_LIST_SCHEMA,
    assert_has_fields,
    create_thread,
    runtime_client,
    skip_if_tier_not_supported,
    validate_json_schema,
)

pytestmark = pytest.mark.integration


class TestArtifactsTierEndpoints:
    """Tests for artifact management endpoints."""

    def test_artifacts_list_returns_files(self, runtime_client: httpx.Client) -> None:
        """GET /artifacts/list must return a files array."""
        skip_if_tier_not_supported(runtime_client, "artifacts")
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.get("/artifacts/list", params={"thread_id": thread_id})
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            validate_json_schema(data, ARTIFACTS_LIST_SCHEMA, path="ArtifactsList")
            assert_has_fields(data, ["files"])
            assert isinstance(data["files"], list)
            if data["files"]:
                first = data["files"][0]
                assert "path" in first, "Each file entry must have a path"

    def test_artifacts_download_returns_content(self, runtime_client: httpx.Client) -> None:
        """GET /artifacts/download must return file content or 404."""
        skip_if_tier_not_supported(runtime_client, "artifacts")
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.get(
            "/artifacts/download",
            params={"thread_id": thread_id, "path": "/workspace/hello.txt"},
        )
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )

    def test_artifacts_zip_returns_zip_content(self, runtime_client: httpx.Client) -> None:
        """GET /artifacts/zip must return a ZIP archive or 404."""
        skip_if_tier_not_supported(runtime_client, "artifacts")
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.get("/artifacts/zip", params={"thread_id": thread_id})
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            assert (
                "application/zip" in content_type
                or "application/octet-stream" in content_type
            ), f"Expected application/zip or octet-stream, got {content_type}"
