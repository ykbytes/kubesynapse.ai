"""kubesynapse API Gateway — modular FastAPI routers.

Each module exposes a ``router`` instance that is mounted in ``main.py``.
"""

from .a2a import router as a2a_router
from .admin import router as admin_router
from .agents import router as agents_router
from .auth import router as auth_router
from .chat import router as chat_router
from .llm import router as llm_router
from .observability import router as observability_router
from .webhooks import router as webhooks_router
from .workflows import router as workflows_router

__all__ = [
    "a2a_router",
    "admin_router",
    "agents_router",
    "auth_router",
    "chat_router",
    "llm_router",
    "observability_router",
    "webhooks_router",
    "workflows_router",
]
