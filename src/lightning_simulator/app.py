"""Runtime resource ownership; every initialized device is registered for cleanup."""

import asyncio
import logging
import time
from contextlib import AsyncExitStack, ExitStack
from dataclasses import replace

from lightning_simulator.audio import PygameAudio, SilentAudio, SimAudio
from lightning_simulator.config import Config
from lightning_simulator.controller import Controller
from lightning_simulator.inputs import GPIOTrigger, SimTrigger, debounce
from lightning_simulator.leds import SimLEDs, SPILEDs
from lightning_simulator.prop import DisabledProp, GPIOProp, SimProp
from lightning_simulator.routing import AudioRouter

log = logging.getLogger(__name__)


async def consume(controller, trigger, debounce_seconds):
    async for event in debounce(trigger.events(), debounce_seconds):
        await controller.handle(event)


async def warmup(controller):
    await asyncio.sleep(max(0, controller.ready_at - time.monotonic()))
    controller.arm(time.monotonic())


async def cancel(task):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def open_device(stack, device):
    stack.callback(device.close)
    device.start()
    return device


async def run_application(config: Config, *, simulate=False, duration=None):
    if simulate:
        log.info("Simulation uses fake hardware/audio; PIR warmup set to zero")
        config = replace(config, trigger=replace(config.trigger, warmup_seconds=0))
    with ExitStack() as devices:
        prop = open_device(
            devices,
            GPIOProp(config.pins.chip, config.pins.relay)
            if config.prop.enabled and not simulate
            else SimProp()
            if simulate
            else DisabledProp(),
        )
        leds = open_device(
            devices,
            SimLEDs(config.leds.count)
            if simulate
            else SPILEDs(
                config.leds.count,
                config.pins.led,
                config.leds.brightness,
                config.leds.color_order,
            ),
        )
        audio = (
            SimAudio()
            if simulate
            else PygameAudio(config.audio)
            if config.audio.enabled
            else SilentAudio()
        )
        devices.callback(audio.close)
        if simulate or not config.audio.enabled:
            audio.start()
        trigger = open_device(
            devices,
            SimTrigger(
                [
                    (0, False),
                    (0.2, True),
                    (1, False),
                    (2, True),
                    (2.5, False),
                    (5, True),
                    (5.5, False),
                ]
            )
            if simulate
            else GPIOTrigger(
                config.pins.chip,
                config.pins.pir if config.trigger.mode == "motion" else config.pins.button,
                button=config.trigger.mode != "motion",
            ),
        )
        controller = Controller(config, leds, audio, prop)
        async with AsyncExitStack() as tasks:
            router = None
            if not simulate and config.audio.enabled:
                router = AudioRouter(config.audio, audio)
                tasks.push_async_callback(router.close)
                route_task = asyncio.create_task(router.run(), name="audio-recovery")
                tasks.push_async_callback(cancel, route_task)
            warmup_task = asyncio.create_task(warmup(controller))
            tasks.push_async_callback(cancel, warmup_task)
            debounce_seconds = (
                config.trigger.debounce_ms / 1000 if config.trigger.mode != "motion" else 0
            )
            # Stop inputs first, then effects/relay, before slower Bluetooth cleanup.
            tasks.push_async_callback(controller.stop)
            input_task = asyncio.create_task(consume(controller, trigger, debounce_seconds))
            tasks.push_async_callback(cancel, input_task)
            waiting = {input_task, controller.failed}
            if router is not None:
                waiting.add(route_task)
            if duration is not None:
                timer = asyncio.create_task(asyncio.sleep(duration))
                tasks.push_async_callback(cancel, timer)
                waiting.add(timer)
            log.info(
                "Controller running: mode=%s forwarding=%s",
                config.trigger.mode,
                config.prop.enabled,
            )
            done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
            if controller.failed in done:
                raise controller.failed.result()
            for task in done:
                task.result()
        if simulate:
            log.info(
                "Simulation: thunder plays=%d, LED updates=%d, background starts=%d",
                audio.thunder_plays,
                leds.updates,
                audio.background_starts,
            )
