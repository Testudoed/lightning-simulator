# Software verification

Run the development checks from the repository root:

```console
uv sync --locked
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

The tests use fake hardware, controlled time and fake audio. They cover input
modes, debounce, startup arming, busy triggers, actor-controlled lightning/thunder restarts,
spotlight synchronization, effect frames, output cleanup and audio recovery.
They do not measure physical relay timing or observe LED/audio output. Follow the
[deployment guide](deployment.md) to install and check the actual hardware.

Both bundled recordings are Git LFS files. Run `git lfs pull` before building;
the wheel must contain the materialized audio, not LFS pointers.

To check a built wheel in a separate environment, choose a fresh directory and
the exact wheel produced by `uv build`:

```console
uv venv /tmp/lightning-wheel-check --python 3.13
uv pip install --python /tmp/lightning-wheel-check/bin/python dist/lightning_simulator-*.whl
cd /tmp
/tmp/lightning-wheel-check/bin/lightning-simulator doctor --simulate
/tmp/lightning-wheel-check/bin/lightning-simulator simulate --mode toggle --duration 8
```

These commands run without Pi hardware libraries. For real GPIO, LEDs and audio,
install the `pi` extra as described in deployment. The installed CLI provides
`doctor`, `simulate` and `component-test`; hardware tests require exclusive access
to their devices.
