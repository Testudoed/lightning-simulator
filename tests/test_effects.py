import asyncio
from dataclasses import replace

import pytest

from lightning_simulator.audio import SilentAudio
from lightning_simulator.config import Config, EffectConfig
from lightning_simulator.controller import Controller
from lightning_simulator.effects import leader_frame, leader_steps
from lightning_simulator.leds import BLACK, WHITE, SimLEDs
from lightning_simulator.lights import SimLights

DIM = (64, 64, 64)


@pytest.mark.parametrize("direction", ["forward", "reverse"])
@pytest.mark.parametrize("count,width", [(120, 12), (400, 1), (8, 3), (2, 12), (1, 12)])
def test_leader_grows_from_top_to_bottom_and_keeps_its_path_lit(direction, count, width):
    previously_lit = set()
    for reached in leader_steps(count, width):
        frame = leader_frame(count, reached, 64, direction)
        lit = {i for i, color in enumerate(frame) if color != BLACK}
        expected = set(range(count - reached, count) if direction == "reverse" else range(reached))
        assert lit == expected
        assert previously_lit <= lit
        assert all(color in (BLACK, DIM) for color in frame)
        previously_lit = lit
    assert frame == [DIM] * count


def test_direction_reverses_the_same_growing_path():
    for reached in leader_steps(120, 12):
        assert leader_frame(120, reached, 64, "reverse") == list(
            reversed(
                leader_frame(120, reached, 64, "forward"),
            )
        )


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    async def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)


class RecordingLEDs(SimLEDs):
    def __init__(self, clock, render_seconds=0):
        super().__init__()
        self.clock = clock
        self.frames = []
        self.render_seconds = render_seconds

    def pixels(self, colors):
        super().pixels(colors)
        self.frames.append((self.clock.now, self.frame))
        self.clock.now += self.render_seconds


def controller(effect, leds, clock):
    return Controller(
        replace(Config(), effect=effect),
        leds,
        SilentAudio(),
        SimLights(),
        now=lambda: clock.now,
        sleep=clock.sleep,
        uniform=lambda low, high: low,
    )


@pytest.mark.parametrize("seconds", [0.2, 0.8])
def test_full_brightness_starts_after_reaching_bottom_then_blackout(seconds):
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        effect = EffectConfig(flashes=1, travel_seconds=seconds)
        c = controller(effect, leds, clock)
        leds.frames.clear()
        await c.flashes()
        assert leds.frames[0][1] == [DIM] + [BLACK] * 119
        peaks = [i for i, (_, frame) in enumerate(leds.frames) if frame == [WHITE] * 120]
        assert len(peaks) == 1
        peak = peaks[0]
        assert leds.frames[peak - 1][1] == [DIM] * 120
        assert leds.frames[peak][0] == pytest.approx(seconds)
        blackout_at, blackout = leds.frames[peak + 1]
        assert blackout == [BLACK] * 120
        assert blackout_at == pytest.approx(seconds + effect.flash_min)
        assert leds.frame == [BLACK] * 120
        assert clock.now == pytest.approx(seconds + effect.flash_min)

    asyncio.run(scenario())


def test_default_three_strikes_repeat_growth_peak_and_blackout():
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        effect = EffectConfig()
        assert effect.flashes == 3 and effect.direction == "forward"
        c = controller(effect, leds, clock)
        leds.frames.clear()
        await c.flashes()
        starts = [i for i, (_, frame) in enumerate(leds.frames) if frame == [DIM] + [BLACK] * 119]
        assert len(starts) == 3
        assert sum(frame == [WHITE] * 120 for _, frame in leds.frames) == 3
        for start in starts[1:]:
            assert leds.frames[start - 1][1] == [BLACK] * 120
            assert leds.frames[start][0] - leds.frames[start - 1][0] == pytest.approx(
                effect.gap_min
            )
        assert leds.frame == [BLACK] * 120
        assert clock.now == pytest.approx(3 * (0.15 + 0.05) + 2 * 0.05)

    asyncio.run(scenario())


@pytest.mark.parametrize("brightness", [0.1, 0.6])
def test_leader_brightness_is_independent_of_full_white_peak(brightness):
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        c = controller(EffectConfig(flashes=1, leader_brightness=brightness), leds, clock)
        leds.frames.clear()
        await c.flashes()
        level = round(255 * brightness)
        assert leds.frames[0][1][0] == (level, level, level)
        assert any(frame == [WHITE] * 120 for _, frame in leds.frames)

    asyncio.run(scenario())


def test_slow_rendering_still_reaches_bottom_and_yields_for_cancellation():
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock, render_seconds=0.04)
        c = controller(EffectConfig(flashes=1, travel_seconds=0.02), leds, clock)
        leds.frames.clear()
        await c.flashes()
        assert any(delay == 0 for delay in clock.sleeps)
        assert any(frame == [DIM] * 120 for _, frame in leds.frames)
        assert leds.frame == [BLACK] * 120
        task = asyncio.create_task(c.flashes())
        await asyncio.sleep(0)
        assert leds.frame == [DIM] + [BLACK] * 119
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and leds.frame == [BLACK] * 120

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["growth", "peak", "gap"])
def test_cancellation_blacks_out_during_every_phase(phase):
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        entered = asyncio.Event()
        sleep = clock.sleep

        async def pause_in_phase(seconds):
            await sleep(seconds)
            matches = {
                "growth": leds.frame == [DIM] + [BLACK] * 119,
                "peak": leds.frame == [WHITE] * 120,
                "gap": leds.frame == [BLACK] * 120,
            }
            if matches[phase]:
                entered.set()
                await asyncio.Future()

        clock.sleep = pause_in_phase
        c = controller(EffectConfig(), leds, clock)
        task = asyncio.create_task(c.flashes())
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and leds.frame == [BLACK] * 120

    asyncio.run(scenario())


def test_whole_strip_flash_remains_selectable():
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        effect = EffectConfig(animation="flash", flashes=1)
        c = controller(effect, leds, clock)
        leds.frames.clear()
        await c.flashes()
        assert leds.frames[0][1] == [WHITE] * 120
        assert leds.frame == [BLACK] * 120
        assert clock.now == pytest.approx(effect.flash_min)

    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["forward", "reverse"])
def test_spotlights_wait_for_full_strip_peak_after_trail(direction):
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        effect = EffectConfig(flashes=2, direction=direction)
        c = controller(effect, leds, clock)
        observations = []
        original_sleep = c.sleep

        async def observe(seconds):
            observations.append((leds.frame, c.lights.active))
            await original_sleep(seconds)

        c.sleep = observe
        c.latched = True
        await c.flashes()
        assert any(frame == [DIM] * 120 for _, frame in leds.frames)
        assert sum(frame == [WHITE] * 120 for frame, _ in observations) == 2
        for frame, active in observations:
            assert active is (frame == [WHITE] * 120)
        assert c.lights.active and leds.frame == [BLACK] * 120

    asyncio.run(scenario())
