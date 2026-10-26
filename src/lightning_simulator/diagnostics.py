"""Read-only health checks and bounded, independently selected component tests."""

import asyncio
import importlib.metadata
import json
import logging
import os
import platform
import shutil
from contextlib import AsyncExitStack, ExitStack
from dataclasses import asdict
from pathlib import Path

from lightning_simulator.app import cancel, open_device
from lightning_simulator.audio import PygameAudio, sound_resource
from lightning_simulator.bluetooth import BluetoothRouter, command
from lightning_simulator.controller import Controller
from lightning_simulator.inputs import GPIOTrigger, debounce
from lightning_simulator.leds import SPILEDs
from lightning_simulator.prop import GPIOProp, SimProp

log = logging.getLogger(__name__)


async def doctor(config, simulate=False):
    result = {"python": platform.python_version(), "config": asdict(config), "checks": []}

    def check(name, ok, detail):
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    check(
        "Python 3.13", platform.python_version_tuple()[:2] == ("3", "13"), platform.python_version()
    )
    for name in ("background_storm.mp3", "lightning_strike.wav"):
        resource = sound_resource(name)
        with resource.open("rb") as stream:
            header = stream.read(43)
        check(
            f"packaged {name}",
            len(header) == 43 and not header.startswith(b"version https://"),
            str(resource),
        )
    if not simulate:
        for name in ("gpiod", "rpi-ws281x", "pygame"):
            try:
                version = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                version = "missing; uv sync --locked --extra pi --no-dev"
            check(name, not version.startswith("missing"), version)
        for device in (config.pins.chip, "/dev/spidev0.0"):
            check(device, os.access(device, os.R_OK | os.W_OK), "Read/write access required for pi")
        boot = Path("/boot/firmware/config.txt")
        text = boot.read_text() if boot.exists() else ""
        lines = {line.split("#", 1)[0].strip() for line in text.splitlines()}
        for setting in ("dtparam=spi=on", "core_freq=500", "core_freq_min=500"):
            check(setting, setting in lines, "Presence only; confirm active section and reboot")
        if config.audio.enabled:
            for executable in ("pactl", "bluetoothctl"):
                check(executable, shutil.which(executable), "Required for Bluetooth routing")
            check(
                "speaker address",
                config.audio.speaker_address,
                config.audio.speaker_address or "unset",
            )
            try:
                sinks = json.loads(
                    await command(
                        "pactl",
                        "--format=json",
                        "list",
                        "sinks",
                        timeout=config.audio.command_timeout,
                    )
                )
                check(
                    "persistent audio sink",
                    any(s.get("name") == config.audio.sink for s in sinks),
                    config.audio.sink,
                )
            except Exception as exc:
                check("PipeWire/Pulse server", False, str(exc))
    result["ok"] = all(item["ok"] for item in result["checks"])
    return result


async def component_test(config, component, duration):
    # A component test never opens unrelated hardware.
    with ExitStack() as devices:
        if component == "leds":
            leds = open_device(
                devices,
                SPILEDs(
                    config.leds.count,
                    config.pins.led,
                    config.leds.brightness,
                    config.leds.color_order,
                ),
            )
            from lightning_simulator.audio import SilentAudio

            controller = Controller(config, leds, SilentAudio(), SimProp())
            try:
                async with asyncio.timeout(duration):
                    await controller.flashes()
            except TimeoutError:
                pass
            finally:
                await controller.stop()
        elif component == "relay":
            if not config.prop.enabled:
                raise ValueError("Set prop.enabled=true after installing the relay to test it")
            prop = open_device(devices, GPIOProp(config.pins.chip, config.pins.relay))
            prop.set_active(True)
            await asyncio.sleep(duration)
        elif component == "input":
            motion = config.trigger.mode == "motion"
            trigger = open_device(
                devices,
                GPIOTrigger(
                    config.pins.chip,
                    config.pins.pir if motion else config.pins.button,
                    button=not motion,
                ),
            )
            try:
                async with asyncio.timeout(duration):
                    async for event in debounce(
                        trigger.events(), 0 if motion else config.trigger.debounce_ms / 1000
                    ):
                        log.info("Input active=%s at %.6f", event.active, event.timestamp)
            except TimeoutError:
                pass
        elif component == "audio":
            audio = PygameAudio(config.audio)
            devices.callback(audio.close)
            router = BluetoothRouter(config.audio, audio)
            async with AsyncExitStack() as tasks:
                tasks.push_async_callback(router.close)
                route_task = asyncio.create_task(router.run())
                tasks.push_async_callback(cancel, route_task)
                start = asyncio.get_running_loop().time()
                played = False
                while asyncio.get_running_loop().time() - start < duration:
                    if audio.connected and not played:
                        # One explicit test thunder; the production router never queues triggers.
                        thunder = asyncio.create_task(audio.thunder())
                        tasks.push_async_callback(cancel, thunder)
                        played = True
                    await asyncio.sleep(0.05)
                if not played:
                    raise RuntimeError("No Bluetooth audio route became available during test")
