import asyncio

from utils.log import log

class Loop:
    def __init__(self, coro, *, seconds=0, minutes=0, hours=0, days=0, years=0):
        self.coro = coro
        self.interval = seconds + minutes*60 + hours*3600 + days*86400 + years*31536000
        self._task: asyncio.Task | None = None
        self._before_loop = None
        self._running = False
        self._instance = None

    def __get__(self, instance, owner):
        self._instance = instance
        return self

    async def _runner(self):
        log(f"[Loop] Runner started for '{self.coro.__name__}' (interval={self.interval}s)", "info")
        try:
            if self._before_loop:
                log(f"[Loop] Executing before_loop for '{self.coro.__name__}'", "info")
                await self._before_loop(self._instance)
                log(f"[Loop] before_loop complete for '{self.coro.__name__}'", "info")

            while self._running:
                try:
                    await self.coro(self._instance)
                    log(f"[Loop] '{self.coro.__name__}' cycle complete; sleeping {self.interval}s", "debug")
                except Exception as e:
                    log(f"[Loop Error] {self.coro.__name__}: {e}", "error")

                try:
                    await asyncio.sleep(self.interval)
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"[Loop Error] Runner crashed for '{self.coro.__name__}': {e}", "error")
        finally:
            self._running = False
            self._task = None
            log(f"[Loop] Runner exiting for '{self.coro.__name__}'", "warn")

    def start(self):
        if self._running:
            log(f"[Loop] start() ignored for '{self.coro.__name__}' because it is already running", "warn")
            return
        self._running = True
        try:
            self._task = asyncio.create_task(self._runner())
            log(f"[Loop] Task created for '{self.coro.__name__}'", "info")
        except RuntimeError as e:
            self._running = False
            self._task = None
            log(f"[Loop Error] Failed to start '{self.coro.__name__}': {e}", "error")

    def cancel(self):
        self._running = False
        if self._task:
            self._task.cancel()
            log(f"[Loop] Task cancelled for '{self.coro.__name__}'", "warn")

    def before_loop(self, coro):
        self._before_loop = coro
        return coro

    @property
    def is_running(self):
        return self._running

    @property
    def current_task(self):
        return self._task


def loop(
    *,
    seconds=0,
    minutes=0,
    hours=0,
    days=0,
    years=0
):
    def decorator(func):
        return Loop(
            func,
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            days=days,
            years=years
        )
    return decorator