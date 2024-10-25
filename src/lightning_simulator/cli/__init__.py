import click

from lightning_simulator.__about__ import __version__


@click.group(context_settings={"help_option_names": ["-h", "--help"]}, invoke_without_command=True)
@click.version_option(version=__version__, prog_name="Lightning Simulator")
@click.pass_context
def lightning_simulator(ctx: click.Context):
    if ctx.invoked_subcommand is None:
        import lightning_simulator.lightning_simulator as lt

        lt.main()

@lightning_simulator.command
def test_on():
    from lightning_simulator.scripts import led_test

    led_test.on()


@lightning_simulator.command
def test_off():
    from lightning_simulator.scripts import led_test

    led_test.off()
