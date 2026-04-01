"""Abstract runtime adapter interface for agent execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunResult:
    """Result of a run execution."""

    success: bool
    output: str = ""
    error: str | None = None
    evidence_paths: list[dict] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapterError(Exception):
    """Raised when a runtime adapter operation fails."""


class RuntimeAdapter(ABC):
    """Abstract interface for executing agent runs on different runtimes."""

    @abstractmethod
    async def spawn(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        permissions_profile: str | None = None,
        **kwargs: Any,
    ) -> RunResult:
        """Spawn a new run with the given prompt.

        This method should execute the prompt and wait for completion,
        returning the result with evidence paths.
        """

    @abstractmethod
    async def cancel(self, run_id: str) -> bool:
        """Cancel a running run. Returns True if successfully canceled."""

    @abstractmethod
    async def status(self, run_id: str) -> str:
        """Get the current status of a run."""

    @property
    @abstractmethod
    def runtime_name(self) -> str:
        """Return the name of this runtime (e.g. 'acp', 'opencode_cli', 'openrouter')."""
