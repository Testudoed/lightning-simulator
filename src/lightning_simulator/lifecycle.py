"""SIGINT/SIGTERM both cancel the main task and run its finally blocks."""

import asyncio
import signal


async def with_signals(coro):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    try:
        return await coro
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def run(coro):
    return asyncio.run(with_signals(coro))
