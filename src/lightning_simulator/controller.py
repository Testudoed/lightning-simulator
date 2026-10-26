"""Edge-triggered state machine; forwarding is independent of local playback."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

from lightning_simulator.config import Config
from lightning_simulator.interfaces import Audio, InputEvent, LEDs, PropOutput
from lightning_simulator.leds import WHITE

log = logging.getLogger(__name__)


class Controller:
    def __init__(
        self,
        config: Config,
        leds: LEDs,
        audio: Audio,
        prop: PropOutput,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable] = asyncio.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ):
        self.config, self.leds, self.audio, self.prop = config, leds, audio, prop
        self.now, self.sleep, self.uniform = now, sleep, uniform
        warmup = config.trigger.warmup_seconds if config.trigger.mode == "motion" else 0
        self.ready_at = now() + warmup
        self.active = None
        self.armed = False
        self.latched = False
        self.effect_task = None
        self.failed = asyncio.get_running_loop().create_future()
        self.prop.set_active(False)
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
        if mode in ("motion", "hold"):
            self.prop.set_active(event.active)
            if event.active:
                if not self.busy:
                    self.start_effect()
                else:
                    log.info("Local retrigger ignored while busy")
            elif mode == "hold":
                await self.stop()
        elif event.active:
            self.latched = not self.latched
            self.prop.set_active(self.latched)
            log.info("Toggle latch %s", self.latched)
            if self.latched:
                self.start_effect()
            else:
                await self.stop()

    def start_effect(self):
        if not self.busy:
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
        try:
            for _ in range(effect.flashes):
                self.leds.fill(WHITE)
                await self.sleep(self.uniform(effect.flash_min, effect.flash_max))
                self.leds.clear()
                await self.sleep(self.uniform(effect.gap_min, effect.gap_max))
        finally:
            self.leds.clear()

    async def sequence(self):
        # TaskGroup cancels the sibling on error and waits for both on success.
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.flashes())
                group.create_task(self.audio.thunder())
        finally:
            self.audio.stop_thunder()

    async def stop(self):
        self.latched = False
        # Release external prop before awaiting local cancellation.
        try:
            self.prop.set_active(False)
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
