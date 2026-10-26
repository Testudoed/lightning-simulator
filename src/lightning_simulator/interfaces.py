"""Replaceable controller boundaries; all event timestamps use monotonic seconds."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from lightning_simulator.leds import RGB


@dataclass(frozen=True)
class InputEvent:
    active: bool
    timestamp: float


class Trigger(Protocol):
    def events(self) -> AsyncIterator[InputEvent]: ...


class LEDs(Protocol):
    count: int

    def pixels(self, colors: Sequence[RGB]) -> None: ...
    def fill(self, color: RGB) -> None: ...
    def clear(self) -> None: ...


class Audio(Protocol):
    async def thunder(self) -> None: ...
    def stop_thunder(self) -> None: ...


class PropOutput(Protocol):
    def set_active(self, active: bool) -> None: ...
