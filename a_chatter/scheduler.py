"""A_chatter 后台调度器。"""

from typing import Dict

import asyncio

from .service import AChatterService
from .utils import utc_now


class AChatterScheduler:
    """扫描到期任务和自动主动发起机会。"""

    def __init__(self, service: AChatterService) -> None:
        self._service = service
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._task_locks: Dict[str, asyncio.Lock] = {}
        self._last_auto_scan = 0.0

    async def start(self) -> None:
        """启动后台调度。"""

        if self._task is not None and not self._task.done():
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="a-chatter-scheduler")

    async def stop(self) -> None:
        """停止后台调度。"""

        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                if self._service.config.plugin.enabled:
                    await self._run_once()
            except Exception:
                self._service.ctx.logger.exception("A_chatter 调度循环执行失败")
            tick_seconds = max(5, int(self._service.config.scheduler.tick_seconds))
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=tick_seconds)
            except asyncio.TimeoutError:
                pass

    async def _run_once(self) -> None:
        now = utc_now()
        due_tasks = await self._service.storage.list_due_tasks(now)
        for task in due_tasks:
            lock = self._task_locks.setdefault(task.task_id, asyncio.Lock())
            if lock.locked():
                continue
            async with lock:
                latest = await self._service.storage.get_task(task.task_id)
                if latest is None or latest.status.value != "active":
                    continue
                if latest.next_run_at is None or latest.next_run_at > utc_now():
                    continue
                await self._service.execute_task(latest)

        loop_time = asyncio.get_running_loop().time()
        auto_scan_seconds = max(30, int(self._service.config.scheduler.auto_scan_seconds))
        if loop_time - self._last_auto_scan >= auto_scan_seconds:
            self._last_auto_scan = loop_time
            await self._service.scan_auto_targets()

