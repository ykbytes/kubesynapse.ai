"""Test fixtures for agentctl CLI tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock

import pytest

from agentctl.config import ResolvedSettings


@pytest.fixture
def test_settings() -> ResolvedSettings:
    return ResolvedSettings(
        gateway_url="http://test-gateway:8080",
        token="test-token",
        namespace="test-ns",
        timeout=10.0,
        output_format="table",
    )


@pytest.fixture
def temp_config_dir(monkeypatch: Any, tmp_path: Path) -> Path:
    """Override config/data dirs to a temp directory."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    monkeypatch.setattr("agentctl.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("agentctl.config.DATA_DIR", data_dir)
    monkeypatch.setattr("agentctl.config.CONFIG_FILE", config_dir / "config.yaml")
    monkeypatch.setattr("agentctl.config.CREDENTIALS_FILE", data_dir / "credentials.yaml")
    return tmp_path
