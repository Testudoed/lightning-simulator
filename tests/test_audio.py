import asyncio
import json
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lightning_simulator.audio import PygameAudio
from lightning_simulator.bluetooth import BluetoothRouter, command
from lightning_simulator.config import AudioConfig


def fake_pygame(monkeypatch):
    channel = Mock()
    channel.get_busy.return_value = True
    mixer = Mock()
    mixer.Channel.return_value = channel
    mixer.get_init.return_value = (44100, -16, 2)
    mixer.music.get_busy.return_value = True
    monkeypatch.setitem(sys.modules, "pygame", SimpleNamespace(mixer=mixer))
    return mixer, channel


def test_background_is_started_once_and_untouched_by_thunder_controls(monkeypatch):
    mixer, channel = fake_pygame(monkeypatch)

    async def scenario():
        audio = PygameAudio(AudioConfig())
        audio.start()
        background_calls = list(mixer.music.mock_calls)
        audio.start()
        await audio.thunder()  # disconnected: drop, no channel.play
        channel.play.assert_not_called()
        audio.set_connected(True)
        task = asyncio.create_task(audio.thunder())
        await asyncio.sleep(0)
        channel.play.assert_called_once()
        audio.stop_thunder()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        audio.set_connected(False)
        audio.set_connected(True)
        assert mixer.music.mock_calls == background_calls
        assert mixer.set_reserved.call_args.args == (1,)
        audio.close()

    asyncio.run(scenario())


def test_audio_channel_failure_is_nonfatal(monkeypatch):
    mixer, channel = fake_pygame(monkeypatch)

    async def scenario():
        audio = PygameAudio(AudioConfig())
        audio.start()
        audio.set_connected(True)
        channel.play.side_effect = RuntimeError("audio server disappeared")
        channel.stop.side_effect = RuntimeError("mixer unavailable")
        await audio.thunder()
        assert not audio.connected
        mixer.music.play.assert_called_once_with(-1)
        audio.close()

    asyncio.run(scenario())


class PulseServer:
    def __init__(self):
        self.sinks = [{"name": "lightning_mix"}]
        self.modules = []
        self.calls = []
        self.unavailable = False

    async def __call__(self, *args, timeout):
        self.calls.append(args)
        assert 0 < timeout <= 10
        if self.unavailable:
            raise RuntimeError("Pulse unavailable")
        if args[:4] == ("pactl", "--format=json", "list", "sinks"):
            return json.dumps(self.sinks)
        if args[:4] == ("pactl", "--format=json", "list", "modules"):
            return json.dumps(self.modules)
        if args[:2] == ("pactl", "load-module"):
            self.modules.append({"index": 20, "name": args[2], "argument": " ".join(args[3:])})
            return "20\n"
        if args[:2] == ("pactl", "unload-module"):
            self.modules = [m for m in self.modules if str(m["index"]) != args[2]]
            return ""
        if args[0] == "bluetoothctl":
            raise RuntimeError("Speaker absent")
        raise AssertionError(args)

    def connect(self):
        self.sinks.append(
            {
                "name": "bluez_output.AA_BB_CC_DD_EE_FF.1",
                "properties": {"api.bluez5.profile": "a2dp-sink"},
            }
        )


def test_bluetooth_absent_late_connection_disconnect_and_reconnect(monkeypatch):
    mixer, channel = fake_pygame(monkeypatch)

    async def scenario():
        config = replace(AudioConfig(), speaker_address="AA:BB:CC:DD:EE:FF")
        audio, pulse = PygameAudio(config), PulseServer()
        router = BluetoothRouter(config, audio, runner=pulse)
        with pytest.raises(RuntimeError, match="Speaker absent"):
            await router.check()
        await audio.thunder()
        channel.play.assert_not_called()
        assert audio.started and not audio.connected
        pulse.connect()
        await router.check()
        assert audio.connected and len(pulse.modules) == 1
        await router.check()
        assert len(pulse.modules) == 1  # no duplicate loopbacks
        task = asyncio.create_task(audio.thunder())
        await asyncio.sleep(0)
        assert channel.play.call_count == 1
        pulse.sinks = pulse.sinks[:1]
        with pytest.raises(RuntimeError, match="Speaker absent"):
            await router.check()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not pulse.modules and not audio.connected
        pulse.connect()
        await router.check()
        assert audio.connected and channel.play.call_count == 1  # no replay
        mixer.music.load.assert_called_once()
        mixer.music.play.assert_called_once_with(-1)
        await router.close()
        assert not pulse.modules
        audio.close()

    asyncio.run(scenario())


def test_commands_timeout_and_nonzero_exit():
    async def scenario():
        with pytest.raises(TimeoutError):
            await command(sys.executable, "-c", "import time; time.sleep(30)", timeout=0.05)
        with pytest.raises(RuntimeError, match="failed \\(2\\)"):
            await command(sys.executable, "-c", "raise SystemExit(2)")

    asyncio.run(scenario())


def test_mixer_health_error_can_recover_after_audio_server_failure(monkeypatch):
    mixer, channel = fake_pygame(monkeypatch)

    async def scenario():
        audio, pulse = PygameAudio(AudioConfig()), PulseServer()
        router = BluetoothRouter(audio.config, audio, runner=pulse)
        await router.check()
        assert audio.started
        mixer.music.get_busy.side_effect = RuntimeError("server lost")
        mixer.music.stop.side_effect = RuntimeError("server lost")
        await router.check()
        assert audio.started and mixer.music.play.call_count == 2
        audio.close()

    asyncio.run(scenario())
