"""Validated TOML configuration, with paths relative to the configuration file."""

import math
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class TriggerConfig:
    mode: str = "motion"
    debounce_ms: float = 50
    warmup_seconds: float = 60


@dataclass(frozen=True)
class PinsConfig:
    chip: str = "/dev/gpiochip0"
    led: int = 10
    pir: int = 17
    button: int = 27
    relay: int = 23


@dataclass(frozen=True)
class LEDConfig:
    count: int = 120
    brightness: int = 255
    color_order: str = "GRB"


@dataclass(frozen=True)
class EffectConfig:
    flashes: int = 3
    animation: str = "travel"
    direction: str = "forward"
    travel_seconds: float = 0.15
    bolt_width: int = 12
    leader_brightness: float = 0.25
    flash_min: float = 0.05
    flash_max: float = 0.2
    gap_min: float = 0.05
    gap_max: float = 0.3


@dataclass(frozen=True)
class AudioConfig:
    enabled: bool = True
    background: str = "resource:background_storm.mp3"
    thunder: str = "resource:lightning_strike.wav"
    background_volume: float = 0.35
    thunder_volume: float = 0.65
    sink: str = "lightning_mix"
    speaker_address: str = ""
    reconnect_seconds: float = 5
    command_timeout: float = 3


@dataclass(frozen=True)
class PropConfig:
    enabled: bool = False


@dataclass(frozen=True)
class Config:
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    pins: PinsConfig = field(default_factory=PinsConfig)
    leds: LEDConfig = field(default_factory=LEDConfig)
    effect: EffectConfig = field(default_factory=EffectConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    prop: PropConfig = field(default_factory=PropConfig)

    def validate(self):
        if self.trigger.mode not in ("motion", "hold", "toggle"):
            raise ValueError("trigger.mode must be motion, hold or toggle")
        if self.pins.led != 10:
            raise ValueError("pins.led must be BCM10 for SPI0 MOSI on Pi 4")
        for name in ("led", "pir", "button", "relay"):
            value = getattr(self.pins, name)
            if type(value) is not int or not 0 <= value <= 27:
                raise ValueError(f"pins.{name} must be a BCM number 0..27")
        used = [10, 9, 11, 8, 7]  # SPI0 owns its bus, including CE pins.
        used.append(self.pins.pir if self.trigger.mode == "motion" else self.pins.button)
        if self.prop.enabled:
            used.append(self.pins.relay)
        if len(set(used)) != len(used):
            raise ValueError("Configured input/relay pins conflict with each other or SPI0")
        if not self.pins.chip.startswith("/dev/gpiochip"):
            raise ValueError("pins.chip must be a /dev/gpiochip device")
        for name, value, lo, hi in (
            ("leds.count", self.leds.count, 1, 400),
            ("leds.brightness", self.leds.brightness, 0, 255),
            ("effect.flashes", self.effect.flashes, 1, 100),
            ("effect.bolt_width", self.effect.bolt_width, 1, 400),
        ):
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name} must be an integer in {lo}..{hi}")
        if self.leds.color_order not in ("RGB", "GRB", "GBR", "BRG", "RBG", "BGR"):
            raise ValueError("leds.color_order must be a permutation of RGB")
        if self.effect.animation not in ("travel", "flash"):
            raise ValueError("effect.animation must be travel or flash")
        if self.effect.direction not in ("forward", "reverse"):
            raise ValueError("effect.direction must be forward or reverse")
        ranges = {
            "trigger.debounce_ms": (self.trigger.debounce_ms, 0, 1000),
            "trigger.warmup_seconds": (self.trigger.warmup_seconds, 0, 600),
            "audio.background_volume": (self.audio.background_volume, 0, 1),
            "audio.thunder_volume": (self.audio.thunder_volume, 0, 1),
            "audio.reconnect_seconds": (self.audio.reconnect_seconds, 1, 60),
            "audio.command_timeout": (self.audio.command_timeout, 0.1, 10),
            "effect.travel_seconds": (self.effect.travel_seconds, 0.02, 10),
            "effect.leader_brightness": (self.effect.leader_brightness, 0.01, 1),
        }
        for name in ("flash_min", "flash_max", "gap_min", "gap_max"):
            ranges[f"effect.{name}"] = (getattr(self.effect, name), 0.001, 10)
        for name, (value, lo, hi) in ranges.items():
            if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name} must be a finite number in {lo}..{hi}")
        if (
            self.effect.flash_min > self.effect.flash_max
            or self.effect.gap_min > self.effect.gap_max
        ):
            raise ValueError("Effect minimum durations must not exceed maximum durations")
        if not re.fullmatch(r"[A-Za-z0-9_]+", self.audio.sink):
            raise ValueError("audio.sink must contain only letters, digits and underscores")
        for name in ("background", "thunder"):
            value = getattr(self.audio, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"audio.{name} must be a file path or packaged resource")
        if self.audio.speaker_address and not re.fullmatch(
            r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}",
            self.audio.speaker_address,
        ):
            raise ValueError("audio.speaker_address must be a Bluetooth MAC address or empty")
        return self


def load_config(path: Path | None = None) -> Config:
    data = tomllib.loads(path.read_text()) if path else {}
    section_types = {
        "trigger": TriggerConfig,
        "pins": PinsConfig,
        "leds": LEDConfig,
        "effect": EffectConfig,
        "audio": AudioConfig,
        "prop": PropConfig,
    }
    if unknown := data.keys() - section_types.keys():
        raise ValueError(f"Unknown configuration sections: {sorted(unknown)}")
    sections = {}
    for name, cls in section_types.items():
        values = data.get(name, {})
        if not isinstance(values, dict):
            raise ValueError(f"{name} must be a TOML table")
        defaults = cls()
        if unknown := values.keys() - {f.name for f in fields(cls)}:
            raise ValueError(f"Unknown {name} settings: {sorted(unknown)}")
        for key, value in values.items():
            default = getattr(defaults, key)
            allowed = (int, float) if type(default) in (int, float) else (type(default),)
            if type(value) not in allowed:
                raise ValueError(f"Invalid type for {name}.{key}")
        if name == "audio" and path:
            for key in ("background", "thunder"):
                if key in values and not values[key].startswith("resource:"):
                    if not values[key].strip():
                        raise ValueError(f"audio.{key} must be a file path or packaged resource")
                    try:
                        selected = Path(values[key]).expanduser()
                    except RuntimeError as exc:
                        raise ValueError(f"audio.{key}: {exc}") from exc
                    if not selected.is_absolute():
                        selected = path.resolve().parent / selected
                    values[key] = str(selected.resolve())
        sections[name] = cls(**values)
    return Config(**sections).validate()
