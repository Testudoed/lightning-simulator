import asyncio
import json
import sys
import wave
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lightning_simulator.audio import PygameAudio, resolve_audio_file
from lightning_simulator.config import AudioConfig, Config, load_config
from lightning_simulator.routing import AudioRouter, command


def write_wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        audio.writeframes(b"\0" * 400)
    return path


@pytest.mark.parametrize("kind", ["relative", "absolute", "home"])
def test_custom_paths_resolve_for_both_selected_audio_files(tmp_path, kind):
    config_file = tmp_path / "config.toml"
    selected = {}
    expected = {}
    for role in ("background", "thunder"):
        if kind == "relative":
            selected[role] = f"sounds/{role} recording.wav"
            expected[role] = tmp_path / selected[role]
        elif kind == "absolute":
            expected[role] = tmp_path / "absolute" / f"{role}.wav"
            selected[role] = str(expected[role])
        else:
            selected[role] = f"~/audio/{role}.wav"
            expected[role] = Path.home() / "audio" / f"{role}.wav"
    config_file.write_text(
        "[audio]\n" + "\n".join(f"{role} = {json.dumps(value)}" for role, value in selected.items())
    )
    config = load_config(config_file)
    for role in selected:
        assert getattr(config.audio, role) == str(expected[role].resolve())


@pytest.mark.parametrize("problem", ["missing", "empty", "lfs_pointer"])
def test_audio_file_validation_reports_the_selected_file(tmp_path, problem):
    path = tmp_path / "selected.wav"
    if problem == "empty":
        path.touch()
    elif problem == "lfs_pointer":
        path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 100\n")
    with ExitStack() as resources, pytest.raises((OSError, ValueError), match="selected.wav"):
        resolve_audio_file(str(path), resources)


def fake_pygame(monkeypatch):
    channel = Mock()
    channel.get_busy.return_value = True
    mixer = Mock()
    mixer.Channel.return_value = channel
    mixer.get_init.return_value = (44100, -16, 2)
    mixer.music.get_busy.return_value = True
    monkeypatch.setitem(sys.modules, "pygame", SimpleNamespace(mixer=mixer))
    return mixer, channel


def test_playback_loads_configured_files_and_keeps_background_through_triggers(
    monkeypatch, tmp_path
):
    mixer, channel = fake_pygame(monkeypatch)
    background = write_wav(tmp_path / "music" / "rain.wav")
    thunder = write_wav(tmp_path / "thunder.wav")
    config_file = tmp_path / "config.toml"
    config_file.write_text('[audio]\nbackground="music/rain.wav"\nthunder="thunder.wav"')

    async def scenario():
        audio = PygameAudio(load_config(config_file).audio)
        try:
            audio.start()
            audio.set_connected(True)
            channel.get_busy.return_value = False
            await audio.thunder()
            await audio.thunder()
            mixer.music.load.assert_called_once_with(str(background))
            mixer.Sound.assert_called_once_with(str(thunder))
            mixer.music.play.assert_called_once_with(-1)
            assert channel.play.call_count == 2
        finally:
            audio.close()

    asyncio.run(scenario())


def test_doctor_checks_custom_files_instead_of_bundled_recordings(monkeypatch, tmp_path):
    from lightning_simulator import audio as audio_module
    from lightning_simulator.diagnostics import doctor

    background = write_wav(tmp_path / "rain.wav")
    thunder = write_wav(tmp_path / "thunder.wav")
    config = replace(
        Config(),
        audio=replace(
            AudioConfig(),
            background=str(background),
            thunder=str(thunder),
        ),
    )

    def no_bundled_resource(name):
        raise AssertionError("Configured custom files must be used")

    monkeypatch.setattr(audio_module, "sound_resource", no_bundled_resource)
    result = asyncio.run(doctor(config, simulate=True))
    checks = {check["name"]: check for check in result["checks"]}
    assert result["ok"]
    assert checks["audio.background"]["detail"] == str(background)
    assert checks["audio.thunder"]["detail"] == str(thunder)


def test_doctor_reports_missing_selected_audio(tmp_path):
    from lightning_simulator.diagnostics import doctor

    missing = tmp_path / "missing-thunder.wav"
    config = replace(Config(), audio=replace(AudioConfig(), thunder=str(missing)))
    result = asyncio.run(doctor(config, simulate=True))
    check = next(check for check in result["checks"] if check["name"] == "audio.thunder")
    assert not result["ok"] and not check["ok"]
    assert str(missing) in check["detail"]


def test_doctor_does_not_require_files_when_audio_is_disabled(tmp_path):
    from lightning_simulator.diagnostics import doctor

    config = replace(
        Config(),
        audio=replace(
            AudioConfig(),
            enabled=False,
            background=str(tmp_path / "missing-background.wav"),
            thunder=str(tmp_path / "missing-thunder.wav"),
        ),
    )
    result = asyncio.run(doctor(config, simulate=True))
    assert result["ok"]
    assert not any(check["name"].startswith("audio.") for check in result["checks"])


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
        config = replace(AudioConfig(), output="bluetooth", speaker_address="AA:BB:CC:DD:EE:FF")
        audio, pulse = PygameAudio(config), PulseServer()
        router = AudioRouter(config, audio, runner=pulse)
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
        audio, pulse = PygameAudio(AudioConfig(output="bluetooth")), PulseServer()
        router = AudioRouter(audio.config, audio, runner=pulse)
        await router.check()
        assert audio.started
        mixer.music.get_busy.side_effect = RuntimeError("server lost")
        mixer.music.stop.side_effect = RuntimeError("server lost")
        await router.check()
        assert audio.started and mixer.music.play.call_count == 2
        audio.close()

    asyncio.run(scenario())
