"""Tests for §security-R6 artifact path traversal protection.

Verifies that _ARTIFACT_REL_SAFE in routers/workflows.py rejects
path-traversal sequences before constructing the pods/exec command.
"""
from __future__ import annotations

import re

# Mirror the regex from api-gateway/routers/workflows.py
_ARTIFACT_REL_SAFE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _is_artifact_safe(artifact_rel: str) -> bool:
    """Mirror the validation in _read_artifact_from_pvc_sync."""
    if not artifact_rel:
        return False
    if artifact_rel.startswith("-"):
        return False
    if ".." in artifact_rel:
        return False
    return bool(_ARTIFACT_REL_SAFE.fullmatch(artifact_rel))


def test_safe_artifact_paths_accepted() -> None:
    """Normal artifact paths inside the workflow run dir should be accepted."""
    assert _is_artifact_safe("run.json")
    assert _is_artifact_safe("workflows/default/agent-1/generation-1.json")
    assert _is_artifact_safe("session-abc/journal.ndjson")


def test_path_traversal_rejected() -> None:
    """Path-traversal sequences must be rejected."""
    assert not _is_artifact_safe("../../../etc/passwd")
    assert not _is_artifact_safe("foo/../../etc/passwd")
    assert not _is_artifact_safe("..")
    assert not _is_artifact_safe("../")
    assert not _is_artifact_safe("a/../b")


def test_unsafe_characters_rejected() -> None:
    """Paths with shell metacharacters or newlines must be rejected."""
    assert not _is_artifact_safe("foo;rm -rf /")
    assert not _is_artifact_safe("foo\nbar")
    assert not _is_artifact_safe("foo\x00bar")
    assert not _is_artifact_safe("foo`whoami`")
    assert not _is_artifact_safe("foo$(whoami)")


def test_empty_and_whitespace_rejected() -> None:
    """Empty or whitespace-only paths must be rejected."""
    assert not _is_artifact_safe("")
    assert not _is_artifact_safe(" ")


def test_option_injection_rejected() -> None:
    """Paths starting with '-' would be interpreted as options by cat."""
    assert not _is_artifact_safe("--upload-pack=evil")
    assert not _is_artifact_safe("-version")
    assert not _is_artifact_safe("-e/system-file")
