"""Compatibility import; install requirements-assistant.txt first.

New callers install code/assistant-sdk directly, without the backend app.
"""
from hbcn_assistant import AssistantClient, AssistantRunError

__all__ = ["AssistantClient", "AssistantRunError"]
