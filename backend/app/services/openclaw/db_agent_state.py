"""Shared DB mutation helpers for OpenClaw agent lifecycle state."""

from __future__ import annotations

from typing import Literal

from app.core.agent_tokens import generate_agent_token, hash_agent_token
from app.core.time import utcnow
from app.models.agents import Agent
from app.services.openclaw.constants import DEFAULT_HEARTBEAT_CONFIG


def ensure_heartbeat_config(agent: Agent) -> None:
    """Ensure an agent has a heartbeat_config dict populated."""

    if agent.heartbeat_config is None:
        agent.heartbeat_config = DEFAULT_HEARTBEAT_CONFIG.copy()


def mint_agent_token(agent: Agent) -> str:
    """Generate a new raw token and update the agent's token hash.

    DEPRECATED: Use staged migration/rotation helpers instead.
    Kept only for legacy transition fallback.
    """

    raw_token = generate_agent_token()
    agent.agent_token_hash = hash_agent_token(raw_token)
    return raw_token


def mark_provision_requested(
    agent: Agent,
    *,
    action: str,
    status: str | None = None,
) -> None:
    """Mark an agent as pending provisioning/update."""

    ensure_heartbeat_config(agent)
    agent.provision_requested_at = utcnow()
    agent.provision_action = action
    if status is not None:
        agent.status = status
    agent.updated_at = utcnow()


def mark_provision_complete(
    agent: Agent,
    *,
    status: Literal["online", "offline", "provisioning", "updating", "deleting"] = "online",
    clear_confirm_token: bool = False,
) -> None:
    """Clear provisioning fields after a successful gateway lifecycle run."""

    if clear_confirm_token:
        agent.provision_confirm_token_hash = None
    agent.status = status
    agent.provision_requested_at = None
    agent.provision_action = None
    agent.updated_at = utcnow()


def current_agent_runtime_token(agent: Agent) -> str:
    """Return the token that should be written to the workspace.

    Priority:
    1. If pending version exists → return pending signed token
    2. If signed mode with no pending → return active signed token
    3. If legacy mode with no pending → raise (migration not initialized)
    """
    from app.core.agent_tokens import issue_signed_agent_token
    from app.core.config import settings

    if agent.pending_agent_token_version is not None:
        return issue_signed_agent_token(
            agent_id=agent.id,
            version=agent.pending_agent_token_version,
            secret=settings.agent_auth_secret,
        )

    if agent.agent_auth_mode == "signed":
        return issue_signed_agent_token(
            agent_id=agent.id,
            version=agent.agent_token_version,
            secret=settings.agent_auth_secret,
        )

    raise RuntimeError(
        f"Cannot resolve runtime token for legacy agent {agent.id} "
        f"(auth_mode={agent.agent_auth_mode}, no pending version). "
        f"Call begin_signed_migration first."
    )


def begin_signed_migration(agent: Agent) -> None:
    """Initialize staged migration for a legacy agent.

    Sets pending_agent_token_version to 1 (if not already set).
    Does NOT touch agent_token_hash or agent_auth_mode.
    """
    if agent.pending_agent_token_version is None:
        agent.pending_agent_token_version = 1
        agent.updated_at = utcnow()


def begin_signed_rotation(agent: Agent) -> None:
    """Initialize staged rotation for a signed agent.

    Sets pending_agent_token_version to current + 1.
    """
    agent.pending_agent_token_version = agent.agent_token_version + 1
    agent.updated_at = utcnow()


def promote_pending_token(agent: Agent) -> None:
    """Promote pending token to active after successful heartbeat.

    This is called when the first heartbeat with a pending signed token is received.
    """
    if agent.pending_agent_token_version is None:
        return

    agent.agent_token_version = agent.pending_agent_token_version
    agent.pending_agent_token_version = None
    agent.agent_auth_mode = "signed"
    agent.agent_token_hash = None
    agent.agent_auth_last_synced_at = utcnow()
    agent.agent_auth_last_error = None
    agent.updated_at = utcnow()


def rollback_pending_token(agent: Agent, error: str) -> None:
    """Rollback pending token version on provisioning failure."""
    agent.pending_agent_token_version = None
    agent.agent_auth_last_error = error
    agent.updated_at = utcnow()
