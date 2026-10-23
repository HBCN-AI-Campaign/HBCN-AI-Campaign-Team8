"""Public business API version; independent of the internal runtime protocol."""
from typing import Literal

from pydantic import BaseModel

CONTRACT_VERSION = "1.3.0"
API_BASE = "/api/assistant/v1"
ASSISTANT_RUN_TIMEOUT_SECONDS = 360
ASSISTANT_RUN_EXPIRY_SECONDS = 390
ASSISTANT_CLIENT_WAIT_SECONDS = 400
ASSISTANT_RAG_QUERY_MAX_CHARS = 4000


class AssistantContractOut(BaseModel):
    contract_version: str
    api_base: str
    authentication: Literal["delegated_reviewer_jwt"]
    run_states: list[Literal["running", "completed", "error", "cancelled"]]
    public_events: list[str]
    limits: dict[str, int]
    compatibility: str
    deployment: dict[str, int | str]
    approval_authority: Literal[False]


class AssistantHTTPError(BaseModel):
    detail: str


def contract_info() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "api_base": API_BASE,
        "authentication": "delegated_reviewer_jwt",
        "run_states": ["running", "completed", "error", "cancelled"],
        "public_events": ["message_start", "step", "tool", "delta", "citations",
                          "message_end", "error", "run_end", "discussion", "members_changed"],
        "limits": {"content_chars": 8000, "knowledge_query_chars": ASSISTANT_RAG_QUERY_MAX_CHARS,
                   "event_page_size": 100,
                   "active_runs_per_session": 1,
                   "run_timeout_seconds": ASSISTANT_RUN_TIMEOUT_SECONDS,
                   "client_wait_seconds": ASSISTANT_CLIENT_WAIT_SECONDS},
        "compatibility": "Additive optional fields/events in v1; ignore unknown fields/events. Breaking changes require a new major API path.",
        "deployment": {"api_workers": 1, "model_credentials": "server_only"},
        "approval_authority": False,
    }
