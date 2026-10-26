import asyncio
from types import SimpleNamespace

import pytest

from lightning_simulator.leds import BLACK, WHITE, SimLEDs
from lightning_simulator.spi_spike import exercise, spike


def test_spike_covers_colors_every_position_and_blackout():
    class RecordingLEDs(SimLEDs):
        def __init__(self):
            super().__init__()
            self.frames = []

        def pixels(self, colors):
            super().pixels(colors)
            self.frames.append(self.frame)

    leds = RecordingLEDs()
    asyncio.run(exercise(leds, 0, visual_step=0, pixel_step=0))
    assert leds.frames[:4] == [
        [color] * 120 for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), WHITE)
    ]
    for position, frame in enumerate(leds.frames[6:126]):
        assert frame[position] == WHITE and frame.count(WHITE) == 1
    assert leds.frame == [BLACK] * 120


def test_spike_reports_failure_separately_from_visual_observations(monkeypatch, tmp_path):
    import json

    from lightning_simulator import spi_spike

    class FailedLEDs(SimLEDs):
        def start(self):
            raise RuntimeError("device missing")

        def close(self):
            self.cleared = True

    leds = FailedLEDs()
    monkeypatch.setattr(spi_spike, "SPILEDs", lambda **kwargs: leds)
    report = tmp_path / "spike.json"
    args = SimpleNamespace(
        simulate=False,
        brightness=255,
        color_order="GRB",
        duration=600,
        wiring="direct-3v3",
        notes="cable 20 cm",
        report=report,
    )
    with pytest.raises(RuntimeError, match="device missing"):
        asyncio.run(spike(args))
    result = json.loads(report.read_text())
    assert result["software_result"] == "error" and leds.cleared
    assert result["operator_visual_result"] == "unassessed"
    assert result["operator_observations"] == "cable 20 cm"
