from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

from polymarket_mm_bot.bot import run as default_run_bot
from polymarket_mm_bot.config import Config

logger = logging.getLogger("polymarket_mm_bot.server")

RunBot = Callable[[Config, Path, Path, Path], Awaitable[None]]


class BotController:
    """Owns the single running bot task, if any, on behalf of the dashboard
    server. One bot per dashboard - this is a personal local tool, not a
    multi-tenant service, so there's no need for more than one at a time."""

    def __init__(
        self,
        env_path: Path,
        flag_path: Path,
        redemption_state_path: Path,
        dashboard_state_path: Path,
        run_bot: RunBot = default_run_bot,
    ) -> None:
        self.env_path = env_path
        self.flag_path = flag_path
        self.redemption_state_path = redemption_state_path
        self.dashboard_state_path = dashboard_state_path
        self._run_bot = run_bot
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> str:
        if self.running:
            return "already running"
        # A stale flag from a previous stop would make the new run exit
        # immediately on its very first kill-switch check.
        if self.flag_path.exists():
            self.flag_path.unlink()
        config = Config.from_env(env_path=self.env_path)

        async def _guarded() -> None:
            try:
                await self._run_bot(config, self.flag_path, self.redemption_state_path, self.dashboard_state_path)
            except Exception:
                logger.exception("bot task crashed")

        self._task = asyncio.create_task(_guarded())
        return "started"

    def stop(self) -> str:
        if not self.running:
            return "not running"
        # Reuses the bot's own kill-switch mechanism rather than cancelling
        # the task directly, so shutdown goes through the same tested,
        # order-cancelling code path as a CLI-run bot stopped with `touch .stop`.
        self.flag_path.touch()
        return "stopping"
