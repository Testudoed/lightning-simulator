import asyncio
from dataclasses import replace

import pytest

from lightning_simulator.audio import SilentAudio
from lightning_simulator.config import Config, EffectConfig
from lightning_simulator.controller import Controller
from lightning_simulator.effects import travel_frame, travel_heads
from lightning_simulator.leds import BLACK, WHITE, SimLEDs
from lightning_simulator.prop import SimProp


@pytest.mark.parametrize("direction", ["forward", "reverse"])
@pytest.mark.parametrize("count,width", [(120, 12), (400, 1), (8, 3), (2, 12), (1, 12)])
def test_travel_has_ordered_head_fading_trail_and_covers_every_pixel(direction, count, width):
    seen = set()
    actual_width = min(width, count)
    heads = travel_heads(count, width)
    for head in heads:
        frame = travel_frame(count, head, width, direction)
        lit = [i for i, color in enumerate(frame) if color != BLACK]
        seen.update(lit)
        assert len(lit) <= actual_width
        if head < count:
            position = count - 1 - head if direction == "reverse" else head
            assert frame[position] == WHITE
        levels = [
            frame[count - 1 - i if direction == "reverse" else i][0]
            for i in range(max(0, head - actual_width + 1), min(count, head + 1))
        ]
        assert levels == sorted(levels)
    assert seen == set(range(count))
    assert frame == [BLACK] * count


def test_direction_reverses_the_same_bolt():
    for head in travel_heads(120, 12):
        assert travel_frame(120, head, 12, "reverse") == list(
            reversed(
                travel_frame(120, head, 12, "forward"),
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
        SimProp(),
        now=lambda: clock.now,
        sleep=clock.sleep,
        uniform=lambda low, high: low,
    )


@pytest.mark.parametrize("seconds", [0.2, 0.8])
def test_travel_duration_is_configurable_and_frames_progress_instead_of_full_strip_flashes(seconds):
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        effect = EffectConfig(flashes=1, travel_seconds=seconds, direction="forward")
        c = controller(effect, leds, clock)
        leds.frames.clear()
        await c.flashes()
        frames = [frame for _, frame in leds.frames]
        assert frames[0] == [WHITE] + [BLACK] * 119
        assert frames[-1] == [BLACK] * 120
        assert all(frame.count(WHITE) <= 1 for frame in frames)
        seen = {i for frame in frames for i, color in enumerate(frame) if color != BLACK}
        assert seen == set(range(120))
        assert clock.now == pytest.approx(seconds + effect.gap_min)

    asyncio.run(scenario())


def test_five_strikes_each_traverse_and_clear_the_scene():
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        c = controller(EffectConfig(), leds, clock)
        leds.frames.clear()
        await c.flashes()
        starts = [frame for _, frame in leds.frames if frame[-1] == WHITE]
        assert len(starts) == 5
        assert all(frame == [BLACK] * 119 + [WHITE] for frame in starts)
        assert leds.frame == [BLACK] * 120
        assert clock.now == pytest.approx(5 * (0.4 + 0.05))

    asyncio.run(scenario())


def test_slow_rendering_does_not_skip_scene_positions_or_block_cancellation():
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock, render_seconds=0.04)
        c = controller(EffectConfig(flashes=1, travel_seconds=0.02), leds, clock)
        leds.frames.clear()
        await c.flashes()
        assert any(delay == 0 for delay in clock.sleeps)
        seen = {i for _, frame in leds.frames for i, color in enumerate(frame) if color != BLACK}
        assert seen == set(range(120))
        assert leds.frame == [BLACK] * 120
        task = asyncio.create_task(c.flashes())
        await asyncio.sleep(0)
        assert leds.frame[-1] == WHITE
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert task.cancelled() and leds.frame == [BLACK] * 120

    asyncio.run(scenario())


def test_original_whole_strip_flash_remains_selectable():
    async def scenario():
        clock = Clock()
        leds = RecordingLEDs(clock)
        effect = EffectConfig(animation="flash", flashes=1)
        c = controller(effect, leds, clock)
        leds.frames.clear()
        await c.flashes()
        assert leds.frames[0][1] == [WHITE] * 120
        assert leds.frame == [BLACK] * 120
        assert clock.now == pytest.approx(effect.flash_min + effect.gap_min)

    asyncio.run(scenario())
