"""Runtime adapter factory for pipeline execution dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.runtime_adapters.acp_adapter import ACPAdapter
from app.services.runtime_adapters.base import RuntimeAdapter, RuntimeAdapterError
from app.services.runtime_adapters.opencode_cli_adapter import OpenCodeCLIAdapter
from app.services.runtime_adapters.openrouter_adapter import OpenRouterAdapter

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.openclaw.gateway_dispatch import GatewayDispatchService
    from app.services.openclaw.gateway_rpc import GatewayConfig


class RuntimeAdapterFactory:
    """Creates the appropriate runtime adapter based on runtime name."""

    @staticmethod
    def create(
        runtime: str,
        session: AsyncSession | None = None,
        dispatch: GatewayDispatchService | None = None,
        gateway_config: GatewayConfig | None = None,
        session_key: str | None = None,
        agent_name: str | None = None,
        workdir: str | None = None,
        api_key: str | None = None,
    ) -> RuntimeAdapter:
        """Create a runtime adapter by name."""
        if runtime == "acp":
            if not all([session, dispatch, gateway_config, session_key, agent_name]):
                raise RuntimeAdapterError(
                    "ACP adapter requires session, dispatch, gateway_config, session_key, and agent_name."
                )
            return ACPAdapter(
                session=session,
                dispatch=dispatch,
                gateway_config=gateway_config,
                session_key=session_key,
                agent_name=agent_name,
            )

        if runtime == "opencode_cli":
            return OpenCodeCLIAdapter(workdir=workdir)

        if runtime == "openrouter":
            return OpenRouterAdapter(api_key=api_key)

        raise RuntimeAdapterError(f"Unknown runtime: {runtime}. Use 'acp', 'opencode_cli', or 'openrouter'.")
