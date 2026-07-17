import asyncio

from core.clock import TickClock


async def test_sleep_ticks_wakes_on_advance():
    clock = TickClock()
    woke_at: list[int] = []

    async def worker(n):
        await clock.sleep_ticks(n)
        woke_at.append(clock.tick)

    t1 = asyncio.create_task(worker(1))
    t2 = asyncio.create_task(worker(3))
    await asyncio.sleep(0)          # let workers park
    assert woke_at == []
    for _ in range(3):
        clock.advance()
        await asyncio.sleep(0)      # let woken workers run
    await asyncio.gather(t1, t2)
    assert sorted(woke_at) == [1, 3]
    assert clock.tick == 3


async def test_zero_sleep_returns_immediately():
    clock = TickClock()
    await clock.sleep_ticks(0)
    assert clock.tick == 0
