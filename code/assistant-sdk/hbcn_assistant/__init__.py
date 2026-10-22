"""Public HTTP adapter; no database, FastAPI or model runtime dependencies."""
from .client import AssistantClient, AssistantRunError

__all__ = ["AssistantClient", "AssistantRunError"]
__version__ = "1.1.1"
