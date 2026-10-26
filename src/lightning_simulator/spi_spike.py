"""Standalone commissioning step: uv run lightning-spi-spike --help."""

import argparse
import asyncio
import hashlib
import json
import platform
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from lightning_simulator.leds import BLACK, WHITE, SimLEDs, SPILEDs
from lightning_simulator.lifecycle import run


def moderate_load(stop):
    """About 25% of one core, in a worker; hashing releases the GIL."""
    data = b"lightning" * 8192
    while not stop.is_set():
        until = time.monotonic() + 0.01
        while time.monotonic() < until:
            hashlib.sha256(data).digest()
        stop.wait(0.03)


async def exercise(leds, duration=600, visual_step=1, pixel_step=0.04):
    async def show(colors, delay):
        leds.pixels(colors)
        await asyncio.sleep(delay)

    for name, color in zip(
        ("red", "green", "blue", "white"),
        ((255, 0, 0), (0, 255, 0), (0, 0, 255), WHITE),
        strict=True,
    ):
        print(f"VISUAL: solid {name}, all {leds.count} pixels", flush=True)
        await show([color] * leds.count, visual_step)
    print("VISUAL: alternating red/green, then blue/white", flush=True)
    for pair in (((255, 0, 0), (0, 255, 0)), ((0, 0, 255), WHITE)):
        await show([pair[i % 2] for i in range(leds.count)], visual_step)
    print(f"VISUAL: one white pixel, positions 0 through {leds.count - 1}", flush=True)
    for index in range(leds.count):
        frame = [BLACK] * leds.count
        frame[index] = WHITE
        await show(frame, pixel_step)
    print("VISUAL: blackout", flush=True)
    await show([BLACK] * leds.count, visual_step)
    print("VISUAL: five lightning flashes", flush=True)
    for _ in range(5):
        await show([WHITE] * leds.count, 0.1)
        await show([BLACK] * leds.count, 0.15)

    print(f"STRESS: {duration:g}s of repeated updates with moderate CPU activity", flush=True)
    stop = threading.Event()
    worker = threading.Thread(target=moderate_load, args=(stop,), daemon=True)
    worker.start()
    try:
        end = time.monotonic() + duration
        frame_no = 0
        while time.monotonic() < end:
            phase = frame_no % 40
            if phase < 20:
                frame = [
                    ((255, 0, 0) if (i + frame_no) % 2 else (0, 255, 0)) for i in range(leds.count)
                ]
            elif phase < 30:
                frame = [WHITE if i == frame_no % leds.count else BLACK for i in range(leds.count)]
            else:
                frame = [WHITE if phase % 2 else BLACK] * leds.count
            await show(frame, min(0.05, max(0, end - time.monotonic())))
            frame_no += 1
    finally:
        stop.set()
        worker.join(timeout=1)


async def spike(args):
    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "simulated": args.simulate,
        "wiring": args.wiring,
        "pixels": 120,
        "bcm": 10,
        "physical_pin": 19,
        "led_supply": "external 5 V / 10 A; feeds to both strips; common Pi/strip ground",
        "brightness": args.brightness,
        "color_order": args.color_order,
        "stress_seconds_requested": args.duration,
        "required_boot_settings": ["dtparam=spi=on", "core_freq=500", "core_freq_min=500"],
        "software_result": "not_started",
        "software_errors": [],
        "operator_visual_result": "unassessed",
        "operator_observations": args.notes,
        "acceptance": "Correct colors/positions; no flicker, stuck pixels or missed updates.",
    }
    boot = Path("/boot/firmware/config.txt")
    report["boot_config"] = boot.read_text() if boot.exists() else "unavailable"
    leds = (
        SimLEDs(120)
        if args.simulate
        else SPILEDs(
            brightness=args.brightness,
            color_order=args.color_order,
        )
    )
    started = time.monotonic()
    try:
        leds.start()
        await exercise(leds, args.duration)
        report["software_result"] = "completed"
    except asyncio.CancelledError:
        report["software_result"] = "interrupted"
        raise
    except Exception as exc:
        report["software_result"] = "error"
        report["software_errors"].append(str(exc))
        raise
    finally:
        try:
            leds.close()
        except Exception as exc:
            report["software_result"] = "error"
            report["software_errors"].append(f"Blackout/cleanup failed: {exc}")
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(f"SOFTWARE: {report['software_result']}; report: {args.report}", flush=True)
        print("VISUAL: unassessed. Record observations separately; software cannot see LEDs.")
    if report["software_result"] == "error":
        raise RuntimeError("LED cleanup failed; inspect the software report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=600, help="Stress duration, default 600s")
    parser.add_argument("--brightness", type=int, default=255, help="Intended brightness, 0..255")
    parser.add_argument(
        "--color-order", choices=("RGB", "GRB", "GBR", "BRG", "RBG", "BGR"), default="GRB"
    )
    parser.add_argument("--wiring", choices=("direct-3v3", "74AHCT125"), default="direct-3v3")
    parser.add_argument("--notes", default="", help="Cable lengths, measured voltage, setup notes")
    parser.add_argument("--report", type=Path, default=Path("led-spike-report.json"))
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.brightness <= 255 or not 0 <= args.duration <= 3600:
        parser.error("brightness must be 0..255 and duration 0..3600 seconds")
    try:
        run(spike(args))
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise SystemExit(130) from None
    except Exception as exc:
        parser.exit(1, f"SOFTWARE ERROR: {exc}\n")


if __name__ == "__main__":
    main()
