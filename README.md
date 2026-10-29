# Lightning simulator for Raspberry Pi 4B

Debian 13 Trixie, Python 3.13 and uv. One unprivileged application controls 120
SPI LEDs, streams background storm audio, mixes the supplied thunder recording,
and optionally switches 12 V Ghostlight spotlights through a relay module.

Follow the [deployment guide](docs/deployment.md) for installation, Pi boot
settings, wiring, audio and automatic startup.

```console
uv sync
uv run lightning-simulator doctor --simulate
uv run lightning-simulator simulate --mode motion --duration 8
uv run lightning-simulator simulate --mode hold --duration 8
uv run lightning-simulator simulate --mode toggle --duration 8
```

Simulation uses fake LEDs, inputs, spotlight output and audio, and skips PIR warmup.
It works on a workstation without the Pi extra. All imports are safe without
hardware. Running `lightning-simulator` with no subcommand starts the real app.

| Mode | Trigger | Spotlight state after the final flash |
|---|---|---|
| `motion` | One sequence per new detection. Busy detections are dropped. | Follows the current PIR level. |
| `momentary` (or `hold`) | Press starts one sequence. Holding does not repeat. | On while the button is held; release turns off. |
| `toggle` | First press starts one sequence and latches lights on; next press unlatches. | On until toggled off. |

Button releases and toggle-off presses **never interrupt lightning or thunder**.
During the strikes, spotlights follow the full-strip flashes: off during the dim
trail and gaps, on at full flash. These flashes continue even if the actor has
already released the button or toggled off. Immediately after the final flash,
the spotlights adopt the current button/latch state, without waiting for thunder
or a final dark gap. The addressable strip returns to black.

A sequence remains busy until both strikes and thunder finish. Busy presses can
change the desired spotlight state but never queue or restart lightning.
Background audio keeps its position. On process start, outputs are inactive and
an inactive input is required before arming; toggle state is never persisted.
Buttons use a stable 50 ms software debounce; motion has a configurable 60 s warmup.
Shutdown and device failures still stop effects and release outputs.

Enable the installed relay with `[lights] enabled = true` in TOML, and set
`trigger.mode = "toggle"` or `"momentary"` for the actor button. The old `[prop]`
section is replaced by `[lights]`; remove it when upgrading. PicoSTORM forwarding
has been removed. Keep `pins.relay = 23` for the existing GPIO wiring.
The spotlight's **12 V supply is separate from the strip's 5 V supply**; see the
[relay wiring](docs/deployment.md#3-wire-the-hardware).

Each lightning strike **grows a dim, continuously lit path from top to bottom**.
When the path reaches the bottom, the whole strip flashes at full configured
brightness, then switches off. The sequence repeats **three times** by default,
with a short dark pause between strikes. The default direction runs from the
first LED to the last, reversing the previous moving-trail effect.

Set `[effect]` options in TOML to adjust the movement and flash:

```toml
[effect]
flashes = 3
animation = "travel"
direction = "forward" # Use "reverse" to start from the last LED instead
travel_seconds = 0.15
leader_brightness = 0.25
bolt_width = 12
flash_min = 0.05
flash_max = 0.2
```

`travel_seconds` is the requested time to reach the bottom; larger values slow
the growth. `leader_brightness` controls the path's brightness relative to the
full-white flash. `bolt_width` sets how many new pixels light up per growth step;
previously lit pixels stay on. Hardware throughput can limit the maximum speed.
`flash_min` / `flash_max` set the brief full-brightness hold after reaching the
bottom, and `gap_min` / `gap_max` set the dark pause before the next strike.
The full-white flash respects `leds.brightness` (255 by default).
The optional `animation = "flash"` skips the growing path.

Preview one three-strike sequence on the Pi without a trigger or audio setup:

```console
.venv/bin/lightning-simulator --config config.example.toml component-test leds --duration 5
```

The duration is a maximum: the command finishes when the sequence ends and clears
the LEDs. Increase it when testing slower travel or longer gaps.

Copy [config.example.toml](config.example.toml) and use the global `--config`
option **before** a subcommand:

```console
uv run lightning-simulator --config config.example.toml doctor
uv run lightning-simulator --config config.example.toml component-test input --duration 20
```

Choose your audio files in the TOML file passed to `--config`:

```toml
[audio]
output = "wired"
device = "" # Auto-detect the Pi headphone jack
background = "~/audio/rain.mp3"
thunder = "~/audio/thunder.wav"
```

Both settings accept absolute paths, `~/` paths, or paths relative to the TOML
file's directory. Background audio loops continuously; the selected thunder
recording plays over it when triggered. The bundled recordings remain the
defaults: `resource:background_storm.mp3` and `resource:lightning_strike.wav`.

Check the selected files without opening Pi hardware:

```console
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml doctor --simulate
```

`doctor` checks that the selected files exist, are readable and nonempty, and
are not Git LFS pointers. Use `component-test audio` to
check playback. Restart the application after changing audio paths; for the user
service, run `systemctl --user restart lightning_simulation.service`.

Wired audio is the default: connect the Pi 4's 3.5 mm jack to the powered
speakers' AUX/line input. The app selects `bcm2835 Headphones` directly through
PipeWire and mixes background/thunder there. No Bluetooth pairing or virtual
sink configuration is needed. An exact PipeWire sink name in `audio.device`
can select another wired output, such as a USB audio adapter. Use
`pactl list short sinks` to list names. The automatic selection uses the Pi jack
even when an HDMI output is available.

Bluetooth remains optional. Set `audio.output="bluetooth"`, configure
`audio.speaker_address`, and follow the [Bluetooth setup](docs/deployment.md#optional-bluetooth-instead-of-wired-audio).
That mode uses the persistent `lightning_mix` sink and reconnects a paired speaker.

The [deployment guide](docs/deployment.md) covers the Pi, headless Bluetooth,
user service, hardware wiring and bounded component tests. Defaults are motion
mode, wired audio, full configured LED brightness, 0.35 background volume, 0.65
thunder volume and spotlight output **disabled**.

Development checks:

```console
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

The wheel includes both original sounds under `lightning_simulator/sounds/`.
They are Git LFS files: materialize them with `git lfs pull` before building.
See [verification.md](docs/verification.md) for clean-wheel verification.

MIT license; see [LICENSE.txt](LICENSE.txt).
