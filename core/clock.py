"""Logical tick clock — the single source of time for the whole system.

Determinism rule: decisions are functions of world-state and of the *logical*
tick, never of wall-clock. `time.time()` is banned everywhere except deriving a
deterministic pseudo-wall (`ticks * TICK_S`) for a manifest's `wall_s` field.

`TickClock.advance()` is called once per orchestrator tick; it releases every
coroutine currently parked in `sleep_ticks()`. Because releasing is done by
resolving pre-registered futures (not an Event set/clear), there is no wakeup
race: a worker that parks after `advance()` simply waits for the next one.
"""
from __future__ import annotations

import asyncio


class TickClock:
    def __init__(self) -> None:
        self._tick: int = 0
        self._waiters: list[asyncio.Future] = []

    @property
    def tick(self) -> int:
        return self._tick

    def now(self) -> int:
        return self._tick

    def advance(self) -> int:
        """Advance one logical tick and wake all parked sleepers."""
        self._tick += 1
        waiters, self._waiters = self._waiters, []
        for fut in waiters:
            if not fut.done():
                fut.set_result(self._tick)
        return self._tick

    async def sleep_ticks(self, n: int) -> None:
        """Park until `n` more ticks have elapsed. n<=0 returns immediately."""
        if n <= 0:
            return
        target = self._tick + n
        while self._tick < target:
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._waiters.append(fut)
            await fut
