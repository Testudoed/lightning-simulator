import asyncio
from dataclasses import replace

import pytest
from click.testing import CliRunner

from lightning_simulator import app
from lightning_simulator.cli import lightning_simulator
from lightning_simulator.config import Config, PropConfig, load_config
from lightning_simulator.inputs import debounce
from lightning_simulator.interfaces import InputEvent


@pytest.mark.parametrize(
    "text",
    [
        '[trigger]\nmode="invalid"',
        "[trigger]\ndebounce_ms=-1",
        "[trigger]\nwarmup_seconds=nan",
        "[leds]\nbrightness=256",
        "[leds]\ncount=1.5",
        "[pins]\nled=18",
        "[pins]\npir=10",
        '[prop]\nenabled="yes"',
        "[audio]\nbackground_volume=1.1",
        '[audio]\nspeaker_address="invalid"',
        '[audio]\nbackground=""',
        '[audio]\nbackground="   "',
        '[audio]\nthunder=""',
        '[audio]\nthunder="   "',
        "[effect]\nflash_min=2\nflash_max=1",
        '[effect]\nanimation="unknown"',
        '[effect]\ndirection="unknown"',
        "[effect]\ntravel_seconds=nan",
        "[effect]\ntravel_seconds=0",
        "[effect]\nbolt_width=0",
        "[effect]\nbolt_width=1.5",
        "[effect]\nleader_brightness=0",
        "[effect]\nleader_brightness=1.1",
        "[effect]\nleader_brightness=nan",
        "[trigger]\nunknown=true",
        "[unknown]\nsetting=true",
    ],
)
def test_invalid_config_fails_before_hardware(tmp_path, text):
    config = tmp_path / "invalid.toml"
    config.write_text(text)
    with pytest.raises(ValueError):
        load_config(config)


def test_config_paths_and_safe_defaults(tmp_path):
    defaults = load_config()
    assert defaults.trigger.mode == "motion" and not defaults.prop.enabled
    assert defaults.trigger.debounce_ms == 50 and defaults.trigger.warmup_seconds == 60
    assert defaults.effect.animation == "travel" and defaults.effect.direction == "forward"
    assert defaults.effect.flashes == 3
    path = tmp_path / "custom.toml"
    path.write_text('[audio]\nbackground="music.mp3"')
    assert load_config(path).audio.background == str(tmp_path / "music.mp3")
    assert load_config(path).audio.thunder == "resource:lightning_strike.wav"
    load_config(__import__("pathlib").Path("config.example.toml"))


def test_partial_startup_failure_clears_all_initialized_hardware(monkeypatch):
    calls = []

    class Device:
        def __init__(self, *args, **kwargs):
            self.name = type(self).__name__

        def start(self):
            calls.append((self.name, "start"))

        def close(self):
            calls.append((self.name, "inactive/closed"))

    class Prop(Device):
        pass

    class LEDs(Device):
        pass

    class Input(Device):
        def start(self):
            super().start()
            raise RuntimeError("input request failed")

    monkeypatch.setattr(app, "GPIOProp", Prop)
    monkeypatch.setattr(app, "SPILEDs", LEDs)
    monkeypatch.setattr(app, "GPIOTrigger", Input)
    config = replace(Config(), prop=PropConfig(enabled=True))
    with pytest.raises(RuntimeError, match="input request failed"):
        asyncio.run(app.run_application(config))
    assert calls == [
        ("Prop", "start"),
        ("LEDs", "start"),
        ("Input", "start"),
        ("Input", "inactive/closed"),
        ("LEDs", "inactive/closed"),
        ("Prop", "inactive/closed"),
    ]


def test_debounced_iterator_flushes_last_level_and_closes_source():
    async def scenario():
        closed = []

        async def source():
            try:
                yield InputEvent(False, asyncio.get_running_loop().time())
            finally:
                closed.append(True)

        events = [event async for event in debounce(source(), 0.001)]
        assert [e.active for e in events] == [False] and closed

    asyncio.run(scenario())


def test_cli_simulation_and_doctor_without_pi_libraries():
    runner = CliRunner()
    for args in (
        ["--help"],
        ["doctor", "--simulate"],
        ["simulate", "--mode", "toggle", "--duration", "0.1"],
    ):
        result = runner.invoke(lightning_simulator, args)
        assert result.exit_code == 0, result.output
