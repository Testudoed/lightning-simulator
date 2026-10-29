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
from lightning_simulator.audio import PygameAudio, resolve_audio_file
from lightning_simulator.controller import Controller
from lightning_simulator.inputs import GPIOTrigger, debounce
from lightning_simulator.leds import SPILEDs
from lightning_simulator.lights import GPIOLights, SimLights
from lightning_simulator.routing import AudioRouter, command, wired_sink

log = logging.getLogger(__name__)


async def doctor(config, simulate=False):
    result = {"python": platform.python_version(), "config": asdict(config), "checks": []}

    def check(name, ok, detail):
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})

    check(
        "Python 3.13", platform.python_version_tuple()[:2] == ("3", "13"), platform.python_version()
    )
    if config.audio.enabled:
        with ExitStack() as resources:
            for name in ("background", "thunder"):
                try:
                    selected = resolve_audio_file(getattr(config.audio, name), resources)
                    check(f"audio.{name}", True, str(selected))
                except (OSError, ValueError, RuntimeError) as exc:
                    check(f"audio.{name}", False, str(exc))
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
            executables = (
                ("pactl", "bluetoothctl") if config.audio.output == "bluetooth" else ("pactl",)
            )
            for executable in executables:
                check(executable, shutil.which(executable), "Required for selected audio output")
            if config.audio.output == "bluetooth":
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
                if config.audio.output == "wired":
                    target = wired_sink(sinks, config.audio.device)
                    check(
                        "wired audio output",
                        target,
                        target
                        or "Pi headphone jack not found; enable dtparam=audio=on "
                        "or set audio.device",
                    )
                    if target:
                        selected = next(s for s in sinks if s["name"] == target)
                        check("wired output unmuted", not selected.get("mute", False), target)
                else:
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

            controller = Controller(config, leds, SilentAudio(), SimLights())
            try:
                async with asyncio.timeout(duration):
                    await controller.flashes()
            except TimeoutError:
                pass
            finally:
                await controller.stop()
        elif component == "relay":
            if not config.lights.enabled:
                raise ValueError("Set lights.enabled=true after installing the relay to test it")
            lights = open_device(devices, GPIOLights(config.pins.chip, config.pins.relay))
            lights.set_active(True)
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
            router = AudioRouter(config.audio, audio)
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
                    raise RuntimeError("No audio output became available during test")
