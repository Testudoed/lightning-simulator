"""Wired output by default, with optional Bluetooth routing and bounded recovery."""

import asyncio
import json
import logging
import shlex
import time

from lightning_simulator.audio import PygameAudio
from lightning_simulator.config import AudioConfig

log = logging.getLogger(__name__)


async def command(*args, timeout=3):
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        raise
    if process.returncode:
        raise RuntimeError(
            f"{args[0]} failed ({process.returncode}): "
            f"{stderr.decode(errors='replace').strip()[:300]}"
        )
    return stdout.decode()


def speaker_sink(sinks, address):
    prefix = "bluez_output." + address.replace(":", "_").upper() + "."
    for sink in sinks:
        name = sink.get("name", "")
        if name.upper().startswith(prefix.upper()):
            props = sink.get("properties", {})
            profile = str(props.get("api.bluez5.profile", ""))
            protocol = str(props.get("bluetooth.protocol", ""))
            if "a2dp" in (name + profile + protocol).lower():
                return name
    return None


def wired_sink(sinks, device=""):
    if device:
        return next((sink["name"] for sink in sinks if sink.get("name") == device), None)
    for sink in sinks:
        name = sink.get("name", "")
        props = sink.get("properties", {})
        identity = " ".join(
            str(props.get(key, ""))
            for key in (
                "api.alsa.card.name",
                "alsa.card_name",
                "alsa.name",
                "node.nick",
            )
        ).lower()
        if name.startswith("alsa_output.") and "bcm2835 headphones" in identity:
            return name
    return None


def owned_loopbacks(modules, sink):
    return [
        module
        for module in modules
        if module.get("name") == "module-loopback"
        and f"source={sink}.monitor" in shlex.split(module.get("argument") or "")
    ]


class AudioRouter:
    def __init__(self, config: AudioConfig, audio: PygameAudio, runner=command):
        self.config, self.audio, self.runner = config, audio, runner
        self.last_error = None

    async def call(self, *args):
        return await self.runner(*args, timeout=self.config.command_timeout)

    async def remove_routes(self, modules):
        for module in owned_loopbacks(modules, self.config.sink):
            await self.call("pactl", "unload-module", str(module["index"]))

    def ensure_audio(self, sink):
        if self.audio.started and (self.audio.output_sink != sink or not self.audio.healthy()):
            log.warning("Audio output changed or stream lost; reinitializing background")
            self.audio.close()
        self.audio.start(sink)

    async def check(self):
        sinks = json.loads(await self.call("pactl", "--format=json", "list", "sinks"))
        if self.config.output == "wired":
            target = wired_sink(sinks, self.config.device)
            if target is None:
                self.audio.close()
                requested = self.config.device or "Pi headphone jack (bcm2835 Headphones)"
                raise RuntimeError(f"Wired audio output not found: {requested}")
            self.ensure_audio(target)
            self.audio.set_connected(True)
            return
        modules = json.loads(await self.call("pactl", "--format=json", "list", "modules"))
        if not any(s.get("name") == self.config.sink for s in sinks):
            raise RuntimeError(
                f"Missing persistent sink {self.config.sink}; install PipeWire drop-in"
            )
        self.ensure_audio(self.config.sink)
        target = (
            speaker_sink(sinks, self.config.speaker_address)
            if self.config.speaker_address
            else None
        )
        routes = owned_loopbacks(modules, self.config.sink)
        if target is None:
            self.audio.set_connected(False)
            await self.remove_routes(modules)
            if self.config.speaker_address:
                await self.call(
                    "bluetoothctl",
                    "--timeout",
                    str(max(1, int(self.config.command_timeout))),
                    "connect",
                    self.config.speaker_address,
                )
            return
        expected = f"sink={target}"
        if len(routes) != 1 or expected not in shlex.split(routes[0].get("argument") or ""):
            self.audio.set_connected(False)
            await self.remove_routes(modules)
            await self.call(
                "pactl",
                "load-module",
                "module-loopback",
                f"source={self.config.sink}.monitor",
                expected,
                "latency_msec=100",
                "source_dont_move=true",
                "sink_dont_move=true",
                "sink_input_properties=node.dont-fallback=true",
            )
        self.audio.set_connected(True)

    async def run(self):
        if self.config.output == "bluetooth" and not self.config.speaker_address:
            log.warning("No Bluetooth speaker address configured; background will run silently")
        while True:
            started = time.monotonic()
            try:
                await self.check()
                if self.last_error is not None:
                    log.info("Audio routing commands recovered")
                self.last_error = None
            except Exception as exc:
                self.audio.set_connected(False)
                message = str(exc)
                if message != self.last_error:
                    log.warning("Audio unavailable; lighting continues: %s", message)
                    self.last_error = message
            await asyncio.sleep(
                max(0, self.config.reconnect_seconds - (time.monotonic() - started))
            )

    async def close(self):
        self.audio.set_connected(False)
        if self.config.output == "wired":
            return
        try:
            modules = json.loads(await self.call("pactl", "--format=json", "list", "modules"))
            await self.remove_routes(modules)
        except Exception as exc:
            log.warning("Audio route cleanup: %s", exc)
