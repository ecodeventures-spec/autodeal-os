"""Base class for all specialized AI Sales Sub-Agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.config import AppSettings
from src.core.database import DatabaseManager
from src.core.llm import UnifiedLLMClient


class BaseSalesAgent(ABC):
    """Abstract base class providing database, settings, and LLM access to sub-agents."""

    def __init__(
        self,
        settings: AppSettings,
        db: DatabaseManager,
        llm: UnifiedLLMClient,
    ) -> None:
        self.settings = settings
        self.db = db
        self.llm = llm

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the agent's primary workflow."""
        raise NotImplementedError
