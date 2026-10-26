import asyncio
from dataclasses import replace

import pytest

from lightning_simulator.config import Config, TriggerConfig
from lightning_simulator.controller import Controller
from lightning_simulator.inputs import Debouncer
from lightning_simulator.interfaces import InputEvent
from lightning_simulator.leds import BLACK, WHITE, SimLEDs
from lightning_simulator.prop import SimProp


async def drain():
    for _ in range(12):
        await asyncio.sleep(0)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waiters = []

    async def sleep(self, seconds):
        future = asyncio.get_running_loop().create_future()
        self.waiters.append((self.now + seconds, future))
        await future

    async def advance(self, seconds):
        self.now += seconds
        for deadline, future in self.waiters:
            if deadline <= self.now and not future.done():
                future.set_result(None)
        await drain()


class GateAudio:
    def __init__(self):
        self.finished = asyncio.Event()
        self.plays = self.stops = 0
        self.background_starts = 1
        self.cancelled = False

    async def thunder(self):
        self.plays += 1
        try:
            await self.finished.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def stop_thunder(self):
        self.stops += 1


def setup(mode="motion", warmup=0):
    clock, leds, audio, prop = Clock(), SimLEDs(), GateAudio(), SimProp()
    config = replace(Config(), trigger=TriggerConfig(mode=mode, warmup_seconds=warmup))
    controller = Controller(
        config,
        leds,
        audio,
        prop,
        now=lambda: clock.now,
        sleep=clock.sleep,
        uniform=lambda low, high: low,
    )
    return controller, clock, leds, audio, prop


async def event(controller, clock, active):
    await controller.handle(InputEvent(active, clock.now))
    await drain()


async def finish_flashes(clock):
    for _ in range(120):
        await clock.advance(0.05)


def test_motion_edges_forward_while_busy_without_queue():
    async def scenario():
        c, clock, leds, audio, prop = setup()
        await event(c, clock, False)
        await event(c, clock, True)
        assert c.busy and audio.plays == 1 and prop.active
        await event(c, clock, False)
        assert c.busy and not prop.active and not audio.cancelled
        await event(c, clock, True)
        assert prop.active and audio.plays == 1
        await finish_flashes(clock)
        assert leds.frame == [BLACK] * 120 and c.busy
        audio.finished.set()
        await drain()
        assert not c.busy
        await event(c, clock, True)
        assert audio.plays == 1  # held high cannot retrigger after playback
        await event(c, clock, False)
        await event(c, clock, True)
        assert audio.plays == 2
        await c.stop()

    asyncio.run(scenario())


def test_hold_release_cancels_thunder_and_clears_outputs():
    async def scenario():
        c, clock, leds, audio, prop = setup("hold")
        await event(c, clock, False)
        await event(c, clock, True)
        assert leds.frame[-1] == WHITE and leds.frame.count(WHITE) == 1 and prop.active
        await event(c, clock, False)
        assert not c.busy and audio.cancelled and not prop.active
        assert leds.frame == [BLACK] * 120 and audio.background_starts == 1

    asyncio.run(scenario())


def test_toggle_survives_local_completion_and_next_press_turns_it_off():
    async def scenario():
        c, clock, leds, audio, prop = setup("toggle")
        await event(c, clock, False)
        await event(c, clock, True)
        await event(c, clock, False)
        audio.finished.set()
        await finish_flashes(clock)
        assert not c.busy and c.latched and prop.active
        await event(c, clock, True)
        assert not c.latched and not prop.active and audio.plays == 1
        await c.stop()

    asyncio.run(scenario())


def test_toggle_stop_during_playback_and_restart_never_restores_latch():
    async def scenario():
        c, clock, leds, audio, prop = setup("toggle")
        await event(c, clock, False)
        await event(c, clock, True)
        await event(c, clock, False)
        await event(c, clock, True)
        assert audio.cancelled and not c.busy and not prop.active
        await c.stop()
        fresh = Controller(c.config, leds, audio, prop, now=lambda: clock.now)
        assert not fresh.latched and not fresh.armed and not prop.active
        await event(fresh, clock, True)
        assert audio.plays == 1
        await fresh.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["motion", "hold", "toggle"])
def test_startup_held_requires_inactive_before_arming(mode):
    async def scenario():
        c, clock, leds, audio, prop = setup(mode)
        await event(c, clock, True)
        assert not c.armed and not c.busy and not prop.active
        await event(c, clock, False)
        assert c.armed and not c.busy
        await event(c, clock, True)
        assert c.busy and prop.active
        await c.stop()
        assert not prop.active and leds.frame == [BLACK] * 120

    asyncio.run(scenario())


@pytest.mark.parametrize("held_at_end", [True, False])
def test_pir_warmup_ignores_activation_and_arms_only_when_inactive(held_at_end):
    async def scenario():
        c, clock, leds, audio, prop = setup(warmup=60)
        await event(c, clock, False)
        await clock.advance(30)
        await event(c, clock, True)
        assert not c.armed and not prop.active and audio.plays == 0
        if not held_at_end:
            await event(c, clock, False)
        await clock.advance(30)
        c.arm(clock.now)
        assert c.armed is (not held_at_end)
        if held_at_end:
            await event(c, clock, False)
        await event(c, clock, True)
        assert c.busy and audio.plays == 1
        await c.stop()

    asyncio.run(scenario())


def test_busy_until_flashes_finish_even_after_thunder():
    async def scenario():
        c, clock, leds, audio, prop = setup()
        audio.finished.set()
        await event(c, clock, False)
        await event(c, clock, True)
        assert c.busy
        await finish_flashes(clock)
        assert not c.busy
        await c.stop()

    asyncio.run(scenario())


def test_effect_failure_is_reported_and_audio_cancelled():
    async def scenario():
        c, clock, leds, audio, prop = setup()

        def fail(colors):
            raise RuntimeError("SPI transfer failed")

        original_pixels = leds.pixels
        leds.pixels = fail
        c.start_effect()
        await drain()
        assert c.failed.done() and isinstance(c.failed.result(), ExceptionGroup)
        assert audio.cancelled
        leds.pixels = original_pixels
        await c.stop()

    asyncio.run(scenario())


def test_debounce_filters_bounce_and_short_presses_in_both_directions():
    state = Debouncer(0.05)
    state.feed(InputEvent(False, 0))
    assert state.flush(0.049) is None
    assert state.flush(0.05) == InputEvent(False, 0.05)
    state.feed(InputEvent(True, 0.1))
    state.feed(InputEvent(False, 0.11))
    assert state.flush(0.17) is None
    state.feed(InputEvent(True, 0.2))
    assert state.flush(0.25) == InputEvent(True, 0.25)
    state.feed(InputEvent(False, 0.3))
    state.feed(InputEvent(True, 0.31))
    state.feed(InputEvent(False, 0.32))
    assert state.flush(0.36) is None
    assert state.flush(0.38) == InputEvent(False, 0.37)


def test_relay_release_error_still_cancels_thunder_and_blacks_out_leds():
    async def scenario():
        c, clock, leds, audio, prop = setup("hold")
        await event(c, clock, False)
        await event(c, clock, True)

        def fail(active):
            raise OSError("relay device unavailable")

        prop.set_active = fail
        with pytest.raises(OSError, match="relay device unavailable"):
            await c.stop()
        assert audio.cancelled and not c.busy and leds.frame == [BLACK] * 120

    asyncio.run(scenario())
