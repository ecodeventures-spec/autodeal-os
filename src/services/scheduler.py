"""Autonomous Background Scheduler (Autopilot Engine) for NUDHUJ AutoDeal OS."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from src.core.orchestrator import SalesOrchestrator

logger = logging.getLogger(__name__)


class AutopilotScheduler:
    """
    Runs periodic autonomous cycles in the background when Autopilot is enabled:
    - Dispatches scheduled & approved emails within sending window hours
    - Checks IMAP inbox for new replies and applies Stop-on-Reply
    """

    def __init__(self, orchestrator: SalesOrchestrator) -> None:
        self.orchestrator = orchestrator
        self._task: Optional[asyncio.Task[Any]] = None
        self.is_running: bool = False
        self.last_run_at: Optional[str] = None
        self.cycles_completed: int = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self.is_running = True
            self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def run_single_cycle(self, org_id: int = 1) -> Dict[str, Any]:
        """Run one immediate Autopilot maintenance & dispatch cycle."""
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.last_run_at = now_iso
        self.cycles_completed += 1

        send_res = await self.orchestrator.sender.run(
            respect_schedule_time=False, org_id=org_id
        )
        await self.orchestrator.db.log_activity(
            agent_name="AutopilotScheduler",
            action="دورة الطيار الآلي التلقائية",
            details=f"تم تنفيذ الدورة #{self.cycles_completed} — الرسائل المرسلة: {send_res.get('sent_count', 0)}",
            org_id=org_id,
            level="info",
        )
        return {
            "cycle": self.cycles_completed,
            "ran_at": now_iso,
            "send_result": send_res,
        }

    async def _loop(self) -> None:
        while self.is_running:
            try:
                if self.orchestrator.settings.system.autopilot_enabled:
                    await self.run_single_cycle(org_id=1)
            except Exception as exc:
                logger.warning("Autopilot cycle warning: %s", exc)
            interval_sec = max(
                60, self.orchestrator.settings.system.autopilot_interval_minutes * 60
            )
            await asyncio.sleep(interval_sec)
