"""Frames for a moving lightning strike, in logical RGB pixel order."""

from lightning_simulator.leds import BLACK, RGB


def travel_frame(count: int, head: int, width: int, direction: str) -> list[RGB]:
    """A white head with a fading trail; the trail exits after the last pixel."""
    width = min(width, count)
    frame = [BLACK] * count
    for distance in range(width):
        position = head - distance
        if 0 <= position < count:
            level = round(255 * (width - distance) / width)
            index = count - 1 - position if direction == "reverse" else position
            frame[index] = (level, level, level)
    return frame


def travel_heads(count: int, width: int) -> tuple[int, ...]:
    """Overlapping steps cover every pixel, including when rendering runs slowly."""
    width = min(width, count)
    end = count + width - 1
    return (*range(0, end, max(1, width // 2)), end)
