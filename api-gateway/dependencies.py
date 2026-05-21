"""Shared dependencies, imports, and re-exports for all API gateway routers.

This module centralizes the sprawling import graph so that individual router
files stay concise and depend on a single well-known module.
"""

from __future__ import annotations

# Standard library
import logging
import sys
import threading
from pathlib import Path
from typing import Any

# Third-party

# ---------------------------------------------------------------------------
# Path setup  (must be imported first so relative imports work)
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# ---------------------------------------------------------------------------
# Auth middleware (extracted module — §4.1)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Auth store (database layer)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Enterprise auth
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Optional / conditional imports
# ---------------------------------------------------------------------------
try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None

try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _Instrumentator = None

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("api-gateway")

# ---------------------------------------------------------------------------
# Environment-derived constants (centralized in constants.py)
# ---------------------------------------------------------------------------

SHUTDOWN = threading.Event()
AGENT_READ_CACHE_LOCK = threading.Lock()
AGENT_READ_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
