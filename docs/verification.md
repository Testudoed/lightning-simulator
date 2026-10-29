# Software verification

Verified on the development workstation with Python 3.13.16. These checks do
not substitute for commissioning on the Raspberry Pi.

- `uv sync` resolved and installed the locked base/development environment.
- `uv sync --extra pi` built rpi-ws281x 5.0.0 and installed gpiod 2.5.0 and pygame
  2.6.1. Driver signatures/constants were inspected without opening hardware.
- `pytest -q`: 94 passing tests using fake hardware, controlled time and fake audio.
  Coverage includes all modes, busy behavior, spotlight flash synchronization and uninterrupted button playback, startup
  warmup/held inputs, stable debounce, cancellation, output cleanup after failures,
  stale GPIO fd readiness, and Bluetooth/audio recovery without background restarts.
  Lightning tests cover growth in both directions, the path remaining lit until
  reaching the bottom, a full-white peak followed by blackout, configurable path
  brightness and traversal time, three strikes by default, and cancellation
  during growth, peak and dark pause. Slow rendering still reaches the bottom
  and yields so cancellation stays responsive.
  Whole-strip flashes remain available through `effect.animation="flash"`.
  Audio tests verify selected custom files reach pygame, absolute/relative/home
  paths resolve correctly, and triggers retain the current background stream.
  Diagnostics check the configured recordings, report missing/empty/LFS-pointer
  files, and skip file requirements when audio is disabled.
  Routing tests cover automatic Pi headphone selection, explicit wired devices,
  wired operation without Bluetooth or a virtual sink, output loss/recovery,
  no queued thunder, and mode-specific diagnostics including muted outputs.
- A 12-second audio-only test on the target Pi successfully selected the onboard
  jack, played background and triggered thunder, and stopped without software
  errors. The operator confirmed audible output. See the
  [wired audio test record](commissioning/2026-10-26-wired-audio.md).
- Ruff lint and formatting checks passed, along with `git diff --check`.
- Motion, hold and toggle CLI simulations ran successfully. SIGTERM during active
  simulated playback exited cleanly and reported inactive outputs in each mode.
- The standalone simulated SPI spike completed its visual sequence plus a one-second
  stress run. A separate SIGTERM run wrote an interrupted software report. Both
  retained `operator_visual_result=unassessed`; no visual LED pass is claimed.
- `systemd-analyze --user verify lightning_simulation.service` exited successfully.
  The workstation emitted an unrelated warning about its installed spice-vdagent unit.
- `uv build` produced a wheel through the source distribution. The source archive
  includes the Python version file, lock, deployment files and commissioning guide.
- A wheel installed in a fresh `/tmp` virtual environment with only Click runs
  `doctor --simulate` and simulation from outside the repository, without gpiod,
  pygame or rpi-ws281x. Both sound resources are present and match the supplied
  source bytes.

The preserved sound hashes are:

```text
b2664a4e92206adca25373733f084228458d62e5cadc76667af10fc1a6321582  background_storm.mp3
3d24f4b25b9e48fc6475c5a39ccf5df3eed00b8766d87fd27607efd381612a8f  lightning_strike.wav
```

To repeat the clean-wheel check (choose the built wheel path):

```console
uv sync --locked
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv build
uv venv /tmp/lightning-wheel-check --python 3.13
uv pip install --python /tmp/lightning-wheel-check/bin/python dist/lightning_simulator-*.whl
cd /tmp
/tmp/lightning-wheel-check/bin/lightning-simulator doctor --simulate
/tmp/lightning-wheel-check/bin/lightning-simulator simulate --mode toggle --duration 8
```

**Outstanding target checks:** the full 600-second direct 3.3 V LED spike,
visual colors/positions/flicker, supply measurements, relay wiring and inactive
hardware default, Bluetooth pairing/A2DP playback and audible mixing, physical
disconnect/reconnect behavior, and unattended boot under the lingering `pi` user
manager. Use [commissioning.md](commissioning.md) to record those results.
