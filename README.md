# Lightning simulator for Raspberry Pi 4B

Debian 13 Trixie, Python 3.13 and uv. One unprivileged application controls 120
SPI LEDs, streams background storm audio, mixes the supplied thunder recording,
and optionally forwards a trigger to a PicoSTORM through a relay module.

**Start with the [standalone LED compatibility spike](docs/led-spike.md).** Test
BCM10 direct 3.3 V data with the existing 5 V / 10 A LED supply before accepting
production wiring. A 74AHCT125 is a comparison fallback if signaling remains
suspect. No target-Pi electrical or visual acceptance has been performed here.

```console
uv sync
uv run lightning-simulator doctor --simulate
uv run lightning-simulator simulate --mode motion --duration 8
uv run lightning-simulator simulate --mode hold --duration 8
uv run lightning-simulator simulate --mode toggle --duration 8
```

Simulation uses fake LEDs, inputs, prop output and audio, and skips PIR warmup.
It works on a workstation without the Pi extra. All imports are safe without
hardware. Running `lightning-simulator` with no subcommand starts the real app.

| Mode | Local lightning and thunder | PicoSTORM relay when enabled |
|---|---|---|
| `motion` | One sequence per new detection. A falling PIR level lets the sequence finish. Busy detections are dropped. | Follows every PIR transition after warmup/arming, including busy detections. |
| `hold` | One sequence per press. Release cancels it immediately. Holding does not repeat. | Active until release, even after local playback finishes. |
| `toggle` | First press starts one sequence; next press stops it if still playing. | Remains latched until the next press, even after playback finishes. |

A sequence remains busy until both the five flashes and thunder finish. Button
stops clear LEDs, stop the dedicated thunder channel and release the relay.
Background audio keeps its position. No input events queue a later sequence.
On every process start outputs are inactive and an inactive input is required
before arming; toggle state is never persisted. Buttons use a stable 50 ms
software debounce; motion uses a configurable 60 s warmup.

Each lightning strike defaults to a **traveling white head with a fading trail**,
moving from the last pixel to the first across both strips. Five strikes play per
sequence. Set `[effect]` options in TOML to adjust the movement:

```toml
[effect]
animation = "travel"
direction = "reverse" # "forward" runs from the first pixel to the last
travel_seconds = 0.4
bolt_width = 12
```

`travel_seconds` is the requested time for one sweep, including its trail leaving
the scene. Larger values slow it down. `bolt_width` includes the bright head and
fading trail, capped to the pixel count. Rendering uses overlapping frames so
every position lights up; hardware throughput can limit the maximum speed.
The existing `gap_min` / `gap_max` settings control pauses between strikes.
`flash_min` / `flash_max` apply to the optional `animation = "flash"` effect,
which illuminates the whole strip simultaneously.

Preview one five-strike sequence on the Pi without a trigger or audio setup:

```console
.venv/bin/lightning-simulator --config config.example.toml component-test leds --duration 5
```

The duration is a maximum: the command finishes when the sequence ends and clears
the LEDs. Increase it when testing slower travel or longer gaps. The standalone
SPI compatibility spike keeps its diagnostic patterns and full-strip flashes.

Copy [config.example.toml](config.example.toml) and use the global `--config`
option **before** a subcommand:

```console
uv run lightning-simulator --config config.example.toml doctor
uv run lightning-simulator --config config.example.toml component-test input --duration 20
```

The [deployment guide](docs/deployment.md) covers the Pi, headless Bluetooth,
user service, hardware wiring and bounded component tests. The
[commissioning checklist](docs/commissioning.md) records acceptance results.
Defaults are motion mode, full configured LED brightness, 0.35 background volume,
0.65 thunder volume and PicoSTORM forwarding **disabled**. Set the speaker address
when commissioning. PicoSTORM's audio remains independently configured.

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
