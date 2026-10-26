"""Compatibility module for the original application entry point."""


def main():
    from lightning_simulator.cli import lightning_simulator

    lightning_simulator()


if __name__ == "__main__":
    main()
