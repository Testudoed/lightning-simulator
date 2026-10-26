"""Public CLI; importing it never imports Pi-specific libraries."""

import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import click

from lightning_simulator.__about__ import __version__
from lightning_simulator.config import load_config
from lightning_simulator.lifecycle import run


def execute(coro):
    try:
        return run(coro)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logging.getLogger(__name__).info("Shutdown complete")
    except Exception as exc:
        logging.getLogger(__name__).error("Application failed: %s", exc)
        raise click.ClickException(str(exc)) from exc


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="Lightning Simulator")
@click.option("--config", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--verbose", is_flag=True)
@click.pass_context
def lightning_simulator(ctx, config, verbose):
    """Run the configured controller, or select a commissioning command."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        ctx.obj = load_config(config)
    except (OSError, ValueError, TypeError) as exc:
        raise click.ClickException(f"Configuration: {exc}") from exc
    if ctx.invoked_subcommand is None:
        from lightning_simulator.app import run_application

        execute(run_application(ctx.obj))


@lightning_simulator.command()
@click.option("--mode", type=click.Choice(["motion", "hold", "toggle"]))
@click.option("--duration", type=click.FloatRange(0.1, 120), default=8, show_default=True)
@click.pass_obj
def simulate(config, mode, duration):
    """Run a bounded event timeline using fake hardware and fake audio."""
    from lightning_simulator.app import run_application

    if mode:
        config = replace(config, trigger=replace(config.trigger, mode=mode))
    execute(run_application(config, simulate=True, duration=duration))


@lightning_simulator.command()
@click.option(
    "--simulate", "simulated", is_flag=True, help="Check resources/config without Pi hardware"
)
@click.pass_obj
def doctor(config, simulated):
    """Read-only diagnostics. Never drives LEDs or relay contacts."""
    from lightning_simulator.diagnostics import doctor as check

    result = execute(check(config, simulated))
    if result is not None:
        click.echo(json.dumps(result, indent=2))
        if not result["ok"]:
            raise click.exceptions.Exit(1)


@lightning_simulator.command("component-test")
@click.argument("component", type=click.Choice(["leds", "input", "relay", "audio"]))
@click.option("--duration", type=click.FloatRange(0.1, 120), default=10, show_default=True)
@click.pass_obj
def component(config, component, duration):
    """Exercise one component for a bounded interval; always clean up."""
    from lightning_simulator.diagnostics import component_test

    execute(component_test(config, component, duration))


@lightning_simulator.command("led-spike")
@click.option("--duration", type=click.FloatRange(0, 3600), default=600, show_default=True)
@click.option("--report", type=click.Path(path_type=Path), default="led-spike-report.json")
@click.option("--wiring", type=click.Choice(["direct-3v3", "74AHCT125"]), default="direct-3v3")
@click.option("--notes", default="")
@click.option("--simulate", "simulated", is_flag=True)
@click.pass_obj
def led_spike(config, duration, report, wiring, notes, simulated):
    """120-pixel SPI compatibility spike (colors, positions, flashes, CPU stress)."""
    from lightning_simulator.spi_spike import spike

    execute(
        spike(
            SimpleNamespace(
                duration=duration,
                report=report,
                wiring=wiring,
                notes=notes,
                simulate=simulated,
                brightness=config.leds.brightness,
                color_order=config.leds.color_order,
            )
        )
    )
