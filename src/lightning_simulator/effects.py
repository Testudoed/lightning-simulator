"""Frames for a lightning path growing down the scene, in logical RGB order."""

from lightning_simulator.leds import BLACK, RGB


def leader_frame(count: int, reached: int, level: int, direction: str) -> list[RGB]:
    """Keep the reached path lit until the full-brightness flash at the bottom."""
    frame = [(level, level, level)] * reached + [BLACK] * (count - reached)
    return list(reversed(frame)) if direction == "reverse" else frame


def leader_steps(count: int, step_pixels: int) -> tuple[int, ...]:
    """Start at the top pixel, advance in groups, and always reach the bottom."""
    return (*range(1, count, min(step_pixels, count)), count)
