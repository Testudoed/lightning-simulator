"""Uninterrupted lightning with synchronized, actor-controlled spotlights."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

from lightning_simulator.config import Config
from lightning_simulator.effects import leader_frame, leader_steps
from lightning_simulator.interfaces import Audio, InputEvent, LEDs, LightOutput
from lightning_simulator.leds import WHITE

log = logging.getLogger(__name__)


class Controller:
    def __init__(
        self,
        config: Config,
        leds: LEDs,
        audio: Audio,
        lights: LightOutput,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable] = asyncio.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ):
        self.config, self.leds, self.audio, self.lights = config, leds, audio, lights
        self.now, self.sleep, self.uniform = now, sleep, uniform
        warmup = config.trigger.warmup_seconds if config.trigger.mode == "motion" else 0
        self.ready_at = now() + warmup
        self.active = None
        self.armed = False
        self.latched = False
        self.flashes_running = False
        self.flash_active = False
        self.effect_task = None
        self.failed = asyncio.get_running_loop().create_future()
        self.lights.set_active(False)
        self.leds.clear()

    @property
    def busy(self):
        return self.effect_task is not None and not self.effect_task.done()

    def arm(self, timestamp):
        if not self.armed and timestamp >= self.ready_at and self.active is False:
            self.armed = True
            log.info("Input armed after inactive level")

    async def handle(self, event: InputEvent):
        previous, self.active = self.active, event.active
        self.arm(event.timestamp)
        if not self.armed or event.active == previous:
            return
        log.info("Input %s at %.6f", "active" if event.active else "inactive", event.timestamp)
        mode = self.config.trigger.mode
        if mode in ("motion", "hold", "momentary"):
            self.latched = event.active
            if event.active:
                if not self.busy:
                    self.start_effect()
                else:
                    log.info("Local retrigger ignored while busy")
        elif event.active:
            self.latched = not self.latched
            log.info("Toggle latch %s", self.latched)
            if self.latched:
                self.start_effect()
        self.update_lights()

    def update_lights(self):
        # During strikes, full flashes override the actor's steady-light request.
        self.lights.set_active(self.flash_active if self.flashes_running else self.latched)

    def start_effect(self):
        if not self.busy:
            self.flashes_running = True
            self.flash_active = False
            self.update_lights()
            log.info("Sequence started")
            self.effect_task = asyncio.create_task(self.sequence(), name="lightning-effect")
            self.effect_task.add_done_callback(self._effect_finished)

    def _effect_finished(self, task):
        if task.cancelled():
            return
        if exc := task.exception():
            log.error("Sequence failed: %s", exc)
            if not self.failed.done():
                # Return the exception as a value to avoid an unretrieved-future warning.
                self.failed.set_result(exc)
        else:
            log.info("Sequence finished (flashes and thunder)")

    async def flashes(self):
        effect = self.config.effect
        self.flashes_running = True
        try:
            for strike in range(effect.flashes):
                if effect.animation == "travel":
                    await self.travel()
                self.leds.fill(WHITE)
                self.flash_active = True
                self.update_lights()
                await self.sleep(self.uniform(effect.flash_min, effect.flash_max))
                self.leds.clear()
                self.flash_active = False
                if strike < effect.flashes - 1:
                    self.update_lights()
                    await self.sleep(self.uniform(effect.gap_min, effect.gap_max))
        finally:
            self.flashes_running = False
            self.flash_active = False
            try:
                self.leds.clear()
            finally:
                self.update_lights()

    async def travel(self):
        effect = self.config.effect
        steps = leader_steps(self.leds.count, effect.bolt_width)
        interval = effect.travel_seconds / max(1, len(steps) - 1)
        level = round(255 * effect.leader_brightness)
        started = self.now()
        for step, reached in enumerate(steps):
            self.leds.pixels(
                leader_frame(
                    self.leds.count,
                    reached,
                    level,
                    effect.direction,
                )
            )
            if step < len(steps) - 1:
                # Account for time spent sending SPI frames without skipping scene positions.
                # Always yield, even if hardware throughput makes the requested speed impossible.
                await self.sleep(max(0, started + (step + 1) * interval - self.now()))

    async def sequence(self):
        # TaskGroup cancels the sibling on error and waits for both on success.
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.flashes())
                group.create_task(self.audio.thunder())
        except BaseException:
            self.latched = False
            self.lights.set_active(False)
            raise
        finally:
            self.audio.stop_thunder()

    async def stop(self):
        self.latched = False
        # Release the light relay before awaiting local cancellation.
        try:
            self.lights.set_active(False)
        finally:
            try:
                if self.effect_task is not None:
                    self.effect_task.cancel()
                    await asyncio.gather(self.effect_task, return_exceptions=True)
                    self.effect_task = None
            finally:
                try:
                    self.audio.stop_thunder()
                finally:
                    self.leds.clear()
        log.info("Outputs inactive")
