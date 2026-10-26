import asyncio
import json
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lightning_simulator.audio import PygameAudio
from lightning_simulator.config import AudioConfig, Config
from lightning_simulator.routing import AudioRouter, wired_sink

JACK = "alsa_output.platform-fe00b840.mailbox.stereo-fallback"
HEADPHONES = {
    "name": JACK,
    "mute": False,
    "properties": {"alsa.card_name": "bcm2835 Headphones"},
}
HDMI = {
    "name": "alsa_output.platform-hdmi.stereo-fallback",
    "properties": {"alsa.card_name": "vc4-hdmi-0"},
}
BLUETOOTH = {
    "name": "bluez_output.AA_BB_CC_DD_EE_FF.1",
    "properties": {"api.bluez5.profile": "a2dp-sink"},
}
USB = {"name": "alsa_output.usb-dac.analog-stereo"}


def fake_audio(monkeypatch, config=None):
    mixer = Mock()
    mixer.get_init.return_value = (44100, -16, 2)
    mixer.music.get_busy.return_value = True
    mixer.Channel.return_value.get_busy.return_value = False
    monkeypatch.setitem(sys.modules, "pygame", SimpleNamespace(mixer=mixer))
    return PygameAudio(config or AudioConfig()), mixer


class WiredServer:
    def __init__(self, sinks=None):
        self.sinks = sinks if sinks is not None else [HDMI, BLUETOOTH, HEADPHONES]
        self.calls = []

    async def __call__(self, *args, timeout):
        self.calls.append(args)
        assert args == ("pactl", "--format=json", "list", "sinks"), args
        assert timeout > 0
        return json.dumps(self.sinks)


@pytest.mark.parametrize("property_name", ["alsa.card_name", "api.alsa.card.name", "node.nick"])
def test_wired_auto_detection_uses_pi_headphones_instead_of_hdmi_or_bluetooth(property_name):
    sink = {"name": JACK, "properties": {property_name: "bcm2835 Headphones"}}
    assert wired_sink([HDMI, BLUETOOTH, sink]) == JACK
    assert wired_sink([HDMI, BLUETOOTH, USB]) is None


def test_explicit_wired_device_overrides_auto_detection():
    assert wired_sink([HEADPHONES, USB], USB["name"]) == USB["name"]
    assert wired_sink([HEADPHONES], USB["name"]) is None


def test_wired_output_plays_mixed_audio_without_bluetooth_or_virtual_sink(monkeypatch):
    async def scenario():
        audio, mixer = fake_audio(monkeypatch)
        server = WiredServer()
        router = AudioRouter(audio.config, audio, runner=server)
        try:
            await router.check()
            assert audio.connected and audio.output_sink == JACK
            assert __import__("os").environ["PULSE_SINK"] == JACK
            await audio.thunder()
            audio.stop_thunder()
            await router.check()
            mixer.music.load.assert_called_once()
            mixer.music.play.assert_called_once_with(-1)
            mixer.Channel.return_value.play.assert_called_once()
            before_close = list(server.calls)
            await router.close()
            assert server.calls == before_close
        finally:
            audio.close()

    asyncio.run(scenario())


def test_missing_wired_device_drops_thunder_and_recovers_without_replay(monkeypatch):
    async def scenario():
        audio, mixer = fake_audio(monkeypatch)
        server = WiredServer([HDMI, BLUETOOTH])
        router = AudioRouter(audio.config, audio, runner=server)
        with pytest.raises(RuntimeError, match="Wired audio output not found"):
            await router.check()
        await audio.thunder()
        assert not audio.started and not audio.connected
        mixer.Channel.return_value.play.assert_not_called()
        server.sinks.append(HEADPHONES)
        await router.check()
        assert audio.started and audio.connected
        mixer.Channel.return_value.play.assert_not_called()
        await audio.thunder()
        server.sinks.remove(HEADPHONES)
        with pytest.raises(RuntimeError, match="Wired audio output not found"):
            await router.check()
        assert not audio.started and not audio.connected
        server.sinks.append(HEADPHONES)
        await router.check()
        assert mixer.Channel.return_value.play.call_count == 1
        audio.close()

    asyncio.run(scenario())


def test_wired_output_uses_configured_device(monkeypatch):
    async def scenario():
        config = replace(AudioConfig(), device=USB["name"])
        audio, _ = fake_audio(monkeypatch, config)
        server = WiredServer([HEADPHONES, USB])
        router = AudioRouter(config, audio, runner=server)
        await router.check()
        assert audio.output_sink == USB["name"]
        audio.close()

    asyncio.run(scenario())


def test_wired_doctor_does_not_require_bluetooth_or_virtual_sink(monkeypatch):
    from lightning_simulator import diagnostics

    server = WiredServer()
    monkeypatch.setattr(diagnostics, "command", server)
    monkeypatch.setattr(
        diagnostics.shutil, "which", lambda exe: "/usr/bin/pactl" if exe == "pactl" else None
    )
    result = asyncio.run(diagnostics.doctor(Config()))
    checks = {check["name"]: check for check in result["checks"]}
    assert checks["wired audio output"]["ok"] and checks["wired output unmuted"]["ok"]
    assert "bluetoothctl" not in checks and "speaker address" not in checks
    assert "persistent audio sink" not in checks


def test_wired_doctor_reports_muted_output(monkeypatch):
    from lightning_simulator import diagnostics

    monkeypatch.setattr(diagnostics, "command", WiredServer([{**HEADPHONES, "mute": True}]))
    result = asyncio.run(diagnostics.doctor(Config()))
    muted = next(check for check in result["checks"] if check["name"] == "wired output unmuted")
    assert not muted["ok"] and not result["ok"]
