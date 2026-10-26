# Debian 13 Trixie deployment on Raspberry Pi 4B

Use the existing Trixie installation and Python 3.13. This guide assumes the
service user is `pi`, the checkout is `/home/pi/Workspace/lightning-simulator`,
and uv is installed for that user. Adjust the service paths if your checkout
lives elsewhere. Do the [LED spike](led-spike.md) before enabling the full service.

## Packages and code

Install the system audio stack, Bluetooth tools, GPIO tools and optional source
build requirements (ARM wheels may depend on OS/architecture):

```console
sudo apt update
sudo apt install git git-lfs python3.13 python3.13-dev build-essential swig pkg-config libgpiod-dev gpiod bluez pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth pulseaudio-utils libsdl2-dev libsdl2-mixer-dev libsdl2-image-dev libsdl2-ttf-dev libportmidi-dev libfreetype-dev libjpeg-dev libpng-dev
sudo systemctl enable --now bluetooth.service
```

As `pi`, in the checkout:

```console
git lfs pull
uv sync --locked --extra pi --no-dev
mkdir -p ~/.config/lightning-simulator
cp config.example.toml ~/.config/lightning-simulator/config.toml
```

`.python-version` selects 3.13 and `uv.lock` pins the dependency graph. Keep both
in version control. Deployment uses the lock without resolving new versions.
The Pi extra uses `gpiod` 2.x, `rpi_ws281x` and pygame. SPI LEDs require neither
root nor a separate LED service.

For an upgrade, first disable the previous **system** services, if installed:

```console
sudo systemctl disable --now led_service.service lightning_simulation.service
```

Remove their old unit files after migration and run `sudo systemctl daemon-reload`.
Do not run diagnostics and the application simultaneously; both would drive the
same SPI LEDs. The old world-writable socket and `rpi-lgpio` are retired.

## GPIO/SPI access and wiring

Set `/boot/firmware/config.txt` as described in the spike guide. For Debian
installations without existing device-group rules:

```console
sudo groupadd --system --force gpio
sudo groupadd --system --force spi
sudo usermod -aG gpio,spi,bluetooth pi
sudo cp deploy/udev/70-lightning-gpio-spi.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo loginctl enable-linger pi
```

Reboot after boot settings/group changes so the lingering user manager receives
the new supplementary groups. Check `id pi`, `gpioinfo`, and permissions on
`/dev/gpiochip0` and `/dev/spidev0.0`. On a Pi 4 the selected gpiochip must expose
BCM offsets 0..27; set `pins.chip` if the device enumeration differs.

| Connection | BCM | Physical header pin | Details |
|---|---:|---:|---|
| LED data | 10 | 19 | SPI0 MOSI; data resistor, external strip power and common ground |
| HC-SR501 OUT | 17 | 11 | Active-high 3.3 V signal; power sensor per its module rating, common ground |
| Button | 27 | 13 | Normally-open button to GND; internal pull-up, active-low |
| Relay module input | 23 | 16 | Active-high 3.3 V-compatible input |
| Common Pi ground | — | 6, for example | Join LED, PIR and relay module logic grounds |

Only the configured trigger input is requested. Keep input/relay pins off SPI0
(BCM7..11); configuration rejects collisions. LED power must feed both strips
directly from the external 5 V / 10 A supply; never through the Pi header.

Use a relay **module** with a documented 3.3 V-compatible, active-high input,
an integrated coil transistor/driver and flyback protection, and an inactive
hardware default. A 10 kohm pull-down at its control input can hold it inactive
while GPIO is unowned; verify the module's own bias and power-up behavior. Never
drive a bare relay coil from GPIO. Power the module according to its rating;
its control input must not source 5 V into the Pi.

The relay's isolated **COM and normally-open** contacts connect PicoSTORM **IN**
and **GND / minus**. Use only the low-voltage trigger terminal; leave its positive
terminal unused. The dry contacts do not require connecting PicoSTORM ground to
the Pi. The [PicoFX/PicoSTORM quick-start guide](https://www.frightideas.com/downloads/docs/PicoFX_Quick_Start_v115a.pdf)
documents the trigger connection and `_MOMENT` option. Create the empty `_MOMENT`
folder in the input scene folder (normally `INPUT1`). Confirm the SD card layout
against your firmware, because older manuals use an `FI-115` parent folder.
Ensure the desired triggered scene is in INPUT1 rather than only an always-looping
AMBIENT scene. In `_MOMENT` mode release ends the input scene. PicoSTORM sound,
ambient behavior and mains lighting remain separately configured on that unit.

Start with `prop.enabled=false`. Install and verify the relay's inactive boot
state, then set it true for the bounded relay test. Keep it disabled until
commissioning is complete.

## Headless Bluetooth and persistent audio sink

Use a dedicated `pi` PipeWire/WirePlumber user session, with lingering enabled.
WirePlumber's [headless Bluetooth guidance](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html)
allows Bluetooth devices without an active login using
`monitor.bluez.seat-monitoring = disabled`. The included fragment is for
WirePlumber **0.5** and permits A2DP roles. Do not install old 0.4 Lua snippets.

As `pi`:

```console
mkdir -p ~/.config/pipewire/pipewire-pulse.conf.d ~/.config/wireplumber/wireplumber.conf.d
cp deploy/pipewire-pulse.conf.d/30-lightning-mix.conf ~/.config/pipewire/pipewire-pulse.conf.d/
cp deploy/wireplumber.conf.d/51-lightning-bluetooth.conf ~/.config/wireplumber/wireplumber.conf.d/
systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service
```

Pair and trust your speaker once, using its real address in place of the example:

```console
bluetoothctl
power on
agent on
default-agent
scan on
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
scan off
quit
```

Set `audio.speaker_address` in TOML to that address. Verify an A2DP output with
`wpctl status` and `pactl --format=json list sinks`. Speaker model and address
are commissioning settings; A2DP support is assumed. Pairing is an operator step;
the service only reconnects a previously paired/trusted speaker.

The [PipeWire Pulse startup configuration](https://docs.pipewire.org/page_man_pipewire-pulse_conf_5.html)
loads a persistent [null sink](https://docs.pipewire.org/page_pulse_module_null_sink.html)
named `lightning_mix`, even while the speaker is missing. pygame streams background
to that sink and uses reserved channel 0 for thunder. The application attaches
one [loopback](https://docs.pipewire.org/page_pulse_module_loopback.html) from the
sink monitor to the matching Bluetooth A2DP sink, replacing stale loopbacks after
reconnection. It never changes the desktop's default output. If you rename the
sink, change both TOML and the drop-in and restart pipewire-pulse.

Connection checks retry every five seconds, with each external command bounded
to three seconds by default. Audio failures are logged while inputs and lighting
continue. Unavailable thunder is dropped; disconnect stops the active thunder
channel, and reconnect does not replay it. Background keeps streaming silently
through an ordinary Bluetooth outage and reconnect resumes the current position.
A complete PipeWire server failure can require reinitializing the mixer and
restarting background; this is logged. Bluetooth latency affects perceived
flash/thunder timing; tune the speaker and recording at commissioning.

## Bounded tests and service

As `pi`, from the checkout:

```console
uv run --locked --extra pi --no-dev lightning-simulator --config ~/.config/lightning-simulator/config.toml doctor
uv run --locked --extra pi --no-dev lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test input --duration 20
uv run --locked --extra pi --no-dev lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test leds --duration 5
uv run --locked --extra pi --no-dev lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test relay --duration 2
uv run --locked --extra pi --no-dev lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test audio --duration 20
```

The LED test plays one five-strike sequence using the configured animation. By
default a white head with a fading trail travels from the last pixel to the first
in each strike. Set `effect.direction="forward"` to reverse that movement, increase
`effect.travel_seconds` to slow it down, or adjust `effect.bolt_width` to change the
trail length. The command clears LEDs on completion or interruption; its duration
is an upper bound, so increase it when previewing a slower sequence. See the
[effect configuration](../config.example.toml) for all settings.

The relay test requires `prop.enabled=true`. Each command opens only its selected
component and has a 120-second maximum. The audio test streams background and
plays one thunder when a route becomes available. Ctrl-C/SIGTERM runs cleanup.
`doctor` is read-only; a successful doctor cannot prove visual/audio/electrical
correctness. Its boot-setting check verifies text presence; verify effective
settings after reboot, for example `vcgencmd get_config int` if available.

After the spike and component commissioning, install the **user** unit as `pi`:

```console
mkdir -p ~/.config/systemd/user
cp lightning_simulation.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lightning_simulation.service
journalctl --user -u lightning_simulation.service -f
```

The unit runs one `.venv` application process, with no root LED daemon. Linger
starts the user manager at boot without a login. SIGTERM clears LEDs, stops
thunder, releases the relay and closes GPIO requests before exit. Initialization
failures clean every device already opened, and a service failure restarts after
five seconds. The relay's hardware inactive default remains essential while the
process is absent. Complete [commissioning.md](commissioning.md), including an
unattended reboot, before enabling PicoSTORM forwarding for use.
