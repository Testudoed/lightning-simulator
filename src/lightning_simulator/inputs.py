"""gpiod 2.x edge input and stable-level software debounce."""

import asyncio
import time
from collections.abc import AsyncIterator

from lightning_simulator.interfaces import InputEvent


class Debouncer:
    """Only emit a level that has remained unchanged for the debounce interval."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.pending = None
        self.stable = None

    def feed(self, event):
        if self.pending is None or event.active != self.pending.active:
            self.pending = InputEvent(event.active, event.timestamp + self.seconds)

    def flush(self, timestamp):
        if self.pending and timestamp >= self.pending.timestamp:
            event, self.pending = self.pending, None
            if self.stable != event.active:
                self.stable = event.active
                return event
        return None


async def debounce(source: AsyncIterator[InputEvent], seconds: float):
    if seconds == 0:
        try:
            async for event in source:
                yield event
        finally:
            await source.aclose()
        return
    state = Debouncer(seconds)
    next_event = asyncio.create_task(anext(source))
    try:
        while True:
            timeout = max(0, state.pending.timestamp - time.monotonic()) if state.pending else None
            done, _ = await asyncio.wait({next_event}, timeout=timeout)
            if done:
                try:
                    event = next_event.result()
                except StopAsyncIteration:
                    if state.pending:
                        await asyncio.sleep(max(0, state.pending.timestamp - time.monotonic()))
                        if stable := state.flush(time.monotonic()):
                            yield stable
                    return
                # If another transition arrived after a stable interval, emit that level first.
                if stable := state.flush(event.timestamp):
                    yield stable
                state.feed(event)
                next_event = asyncio.create_task(anext(source))
            elif stable := state.flush(time.monotonic()):
                yield stable
    finally:
        next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)
        await source.aclose()


class GPIOTrigger:
    def __init__(self, chip, pin, button=False):
        self.chip, self.pin, self.button = chip, pin, button
        self.request = None

    def start(self):
        import gpiod
        from gpiod.line import Bias, Clock, Direction, Edge

        self.request = gpiod.request_lines(
            self.chip,
            consumer="lightning-trigger",
            config={
                self.pin: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    active_low=self.button,
                    bias=Bias.PULL_UP if self.button else Bias.PULL_DOWN,
                    edge_detection=Edge.BOTH,
                    event_clock=Clock.MONOTONIC,
                )
            },
            event_buffer_size=256,
        )

    async def events(self):
        from gpiod.line import Value

        loop = asyncio.get_running_loop()
        ready = asyncio.Event()
        loop.add_reader(self.request.fd, ready.set)
        try:
            # Queued edges before this snapshot are obsolete; timestamps enforce ordering.
            snapshot_at = time.monotonic()
            initial = self.request.get_value(self.pin) == Value.ACTIVE
            last_seq = None
            yield InputEvent(initial, snapshot_at)
            while True:
                await ready.wait()
                ready.clear()
                # A readiness callback may already be queued after the preceding read drained
                # the fd. Never call the blocking reader for such a stale notification.
                if not self.request.wait_edge_events(timeout=0):
                    continue
                for event in self.request.read_edge_events():
                    if last_seq is not None and event.line_seqno != last_seq + 1:
                        raise RuntimeError("GPIO events lost; disarming for service restart")
                    last_seq = event.line_seqno
                    timestamp = event.timestamp_ns / 1_000_000_000
                    if timestamp >= snapshot_at:
                        yield InputEvent(event.event_type == event.Type.RISING_EDGE, timestamp)
        finally:
            loop.remove_reader(self.request.fd)

    def close(self):
        if self.request is not None:
            self.request.release()
            self.request = None


class SimTrigger:
    def __init__(self, timeline):
        self.timeline = timeline

    def start(self):
        pass

    async def events(self):
        start = time.monotonic()
        for offset, active in self.timeline:
            await asyncio.sleep(max(0, start + offset - time.monotonic()))
            yield InputEvent(active, time.monotonic())
        await asyncio.Future()

    def close(self):
        pass
