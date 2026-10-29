# Raspberry Pi 4B setup

This guide sets up Debian 13 Trixie, Python 3.13, two addressable LED strips
(120 pixels total), an actor button, a relay switching Ghostlight Mini spotlights,
and wired speakers. The Pi runs one application as an ordinary user.

Commands assume the user is `pi` and the checkout is
`/home/pi/Workspace/lightning-simulator`. Substitute your username in commands
and use the same checkout location relative to your home, or edit the service's
`WorkingDirectory` and `ExecStart` to match.

## 1. Install the application

Install system dependencies:

```console
sudo apt update
sudo apt install curl ca-certificates git git-lfs python3.13 python3.13-dev build-essential swig pkg-config libgpiod-dev gpiod pipewire pipewire-pulse wireplumber pulseaudio-utils alsa-utils libsdl2-dev libsdl2-mixer-dev libsdl2-image-dev libsdl2-ttf-dev libportmidi-dev libfreetype-dev libjpeg-dev libpng-dev
```

If uv is not installed, use its [official installer](https://docs.astral.sh/uv/getting-started/installation/)
as `pi`:

```console
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/lightning-uv-install.sh
sh /tmp/lightning-uv-install.sh
. "$HOME/.local/bin/env"
```

Clone the repository, or use your existing checkout:

```console
mkdir -p ~/Workspace
cd ~/Workspace
git clone https://github.com/Testudoed/lightning-simulator.git
cd lightning-simulator
git lfs install
git lfs pull
uv sync --locked --extra pi --no-dev
mkdir -p ~/.config/lightning-simulator
cp config.example.toml ~/.config/lightning-simulator/config.toml
```

Copy the example only for a new installation; preserve your existing config on
upgrades. Replace its old `[prop]` table with `[lights]` if present. Git LFS must
materialize the bundled audio before use. The repository selects Python 3.13;
`uv sync --locked` installs the pinned dependencies and the `.venv` used by the service.

If upgrading from the old system services, stop them before using this version:

```console
sudo systemctl disable --now led_service.service lightning_simulation.service
```

Only run that command if those old system units are installed. This guide uses
a **user** service instead. Never run the service, a foreground controller and
hardware component tests at the same time: they use the same GPIO/SPI devices.

## 2. Configure SPI, audio and device permissions

Edit `/boot/firmware/config.txt`. Add or update these settings in the indicated
sections, ensuring later entries do not override them:

```ini
[all]
dtparam=spi=on
dtparam=audio=on

[pi4]
core_freq=500
core_freq_min=500
```

The [LED driver's Pi 4 SPI instructions](https://github.com/jgarff/rpi_ws281x#limitations)
require a fixed core clock for stable LED signaling. Dedicate SPI0 to the LED
strips; other SPI peripherals cannot share it. The SPI backend can run alongside
the Pi's analog headphone audio.

From the checkout, grant the service user access:

```console
sudo groupadd --system --force gpio
sudo groupadd --system --force spi
sudo usermod -aG gpio,spi,audio pi
sudo cp deploy/udev/70-lightning-gpio-spi.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo loginctl enable-linger pi
sudo reboot
```

After reconnecting, return to the checkout and check:

```console
cd ~/Workspace/lightning-simulator
id
ls -l /dev/gpiochip* /dev/spidev0.0
gpioinfo
```

The user needs read/write access to the GPIO chip and SPI device. On a Pi 4,
`pins.chip` must identify the chip exposing BCM GPIO offsets 0..27; its default
is `/dev/gpiochip0`. Change that setting if your device enumeration differs.

## 3. Wire the hardware

Disconnect all supplies before wiring. The three supply voltages have different
jobs:

| Supply | Powers | Ground connection |
|---|---|---|
| Pi's normal USB-C supply | Raspberry Pi | Pi GND is the signal ground below |
| External 5 V / 10 A supply | Addressable lightning strips | Join negative to Pi GND and both strip grounds |
| Regulated 3.3 V relay supply | The purchased 3 V/3.3 V relay module | Join negative to Pi GND and module logic ground |
| Separate regulated 12 V DC supply | Ghostlight Mini spotlights, through relay contacts | Returns directly from the lights; no Pi ground connection needed |

Keep the separate supply positives separate. LED and relay coil load current
must not flow through GPIO pins. The 12 V supply connects only to the relay's
**contact side** and the spotlights, never to its control/power header or the Pi.
Power the Pi through USB-C; do not connect the external strip supply to the Pi's
5 V header pins.

### Pi header connections

**Physical pin numbers are positions on the 40-pin header. BCM numbers are the
GPIO numbers used in `config.toml`.** For example, BCM23 is physical pin 16,
not physical pin 23. Locate pin 1 from the board marking and use the
[official header pinout](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio)
to orient the connector.

| Pi physical pin | BCM / signal | Connect to |
|---:|---|---|
| 19 | BCM10 / SPI0 MOSI | 330 ohm series resistor, then first strip **DIN** |
| 13 | BCM27 | One terminal of the normally-open actor button |
| 14 | GND | Other terminal of the actor button |
| 16 | BCM23 | Relay control input, marked **IN** or signal |
| 6 | GND | Common ground junction: strip supply negative, strip grounds, relay logic ground and 3.3 V relay supply negative |
| 11, optional | BCM17 | HC-SR501 PIR **OUT**, only when using motion mode |

The application enables the button's internal pull-up; a press connects BCM27
to ground. Use the switch contacts of an illuminated button; its lamp terminals
are a separate circuit. Toggle and momentary modes use the same button wiring.
Only the configured input is requested. Leave PIR disconnected for button modes.
BCM7..11 belong to SPI0 and cannot be assigned to the button, PIR or relay.

### Addressable lightning strips: 5 V power, data in series

```text
Pi physical 19 / BCM10 -- 330 ohm -- DIN [strip 1] DOUT -- DIN [strip 2]

5 V supply + -- fused feed ---------------- +5 V strip 1
           +-- separate fused feed -------- +5 V strip 2
5 V supply - ------------------------------ GND strip 1
           +------------------------------- GND strip 2
           +------------------------------- Pi physical 6 / GND
```

Follow the strip's printed arrows: data goes into **DIN**, then from the first
strip's **DOUT** into the second strip's **DIN**. Do not connect both DINs to the
Pi in parallel. The software treats them as one chain of 120 pixels. Supply each
strip directly with wire and fuse sized for its load; the header carries only
the data signal and ground reference. No strip clock connection is needed.

Keep the data cable short with a nearby ground return. Place the 330 ohm resistor
near the first DIN and a 1000 uF capacitor rated at least 10 V across the strip's
5 V/GND input, observing capacitor polarity. These follow
[Adafruit's pixel wiring guidance](https://learn.adafruit.com/adafruit-neopixel-uberguide/best-practices).

The diagram uses direct 3.3 V data from the Pi. Whether this is reliable depends
on the strip's input threshold and wiring. If a 5 V logic buffer is needed, use
a 74AHCT125 between BCM10 and the resistor/DIN: power VCC (pin 14) from strip 5 V,
GND (7) from common ground, /1OE (1) to ground, 1A (2) to BCM10, and 1Y (3) to the
resistor. Add 0.1 uF across VCC/GND at the chip, tie unused /OE pins (4, 10, 13)
high and unused inputs (5, 9, 12) low; leave unused outputs open. These are
**chip pin numbers**, not Pi header positions; confirm your package against the
[74AHCT125 datasheet](https://cdn-shop.adafruit.com/datasheets/74AHC125.pdf).

### Relay control side: 3.3 V

The purchased [Teyleten B07XGZSYJV relay module](https://www.amazon.com/dp/B07XGZSYJV)
is a **3 V/3.3 V, active-high** module with an integrated driver. Supply it with
regulated 3.3 V rated for the board's coil current. Use the printed terminal
labels, rather than assuming a left-to-right connector order:

| Relay control-side terminal | Connection |
|---|---|
| **IN** / signal | Pi BCM23, physical pin 16 |
| **GND** / **DC-** | Common Pi ground and 3.3 V relay supply negative |
| **VCC** / **DC+** | Regulated 3.3 V relay supply positive |

If the board exposes separate logic and coil power terminals, use its supplied
jumper instructions for a shared **3.3 V** board supply; both supply inputs must
receive their rated voltage. Confirm the labels on your board before powering
it. The jumper concerns the relay board's logic/coil power; it never connects to
the 12 V contact circuit. Do not power this 3.3 V board from 5 V or 12 V, and do
not drive a bare relay coil from GPIO. Keep the module's integrated driver in use.

Fit a 10 kohm pull-down between **IN** and module **GND** to request the inactive
state when the Pi GPIO is unowned. Verify that the relay stays released during
Pi startup, shutdown and power loss with the relay supply still powered.

### Relay contact side: switch the 12 V spotlights

```text
12 V supply + -- fuse -- relay COM
                        relay NO -------- spotlight + (or splitter +)
12 V supply - --------------------------- spotlight - (or splitter -)
                        relay NC -------- leave unconnected
```

**COM** is the moving contact; **NO** is normally open and closes when the relay
is active. Use **COM/NO**, so the spotlights are off when the relay is released.
Leave **NC** unused. COM is not the module's logic ground. The control header
and switched contacts are separate circuits.

The [Ghostlight Mini specifications](https://www.halloweenfxprops.com/ghostlight-mini-12-volt-mini-spotlight/)
list **12 V DC and 16 mA per light**. For multiple lights, connect them in
parallel using a suitable splitter after the relay; size the supply, fuse and
wiring for the combined load. Confirm barrel connector polarity from the
light/supply markings before attaching wires. The lights' negative returns to
the 12 V supply negative; it does not need to join Pi ground. PicoSTORM is no
longer part of the wiring.

### Optional motion sensor

For `trigger.mode="motion"`, connect HC-SR501 OUT to BCM17 (physical 11), GND
to common Pi ground, and VCC to the voltage specified for your sensor board.
The output presented to BCM17 must be 3.3 V-compatible. Motion mode ignores
activation during its configured warmup and requires an inactive level before
arming. A detection starts one sequence; further detections while busy do not
queue another.

## 4. Configure the actor button and lights

Edit `~/.config/lightning-simulator/config.toml`. Update these existing tables
rather than adding duplicate tables:

```toml
[trigger]
mode = "toggle" # Or "momentary"; "hold" is an alias for momentary
warmup_seconds = 60.0 # Used only for motion mode
debounce_ms = 50.0

[pins]
chip = "/dev/gpiochip0"
led = 10
pir = 17
button = 27
relay = 23

[lights]
enabled = false # Set true after checking the relay wiring and inactive state
```

Set `leds.count` to the total number of addressable pixels and `leds.color_order`
to your strip's order (default `GRB`). `leds.brightness` ranges from 0 to 255.
Keep the rest of the example config, including its `[effect]` and `[audio]` tables.

| Mode | Actor action | Spotlight state after the last flash |
|---|---|---|
| `toggle` | First press starts lightning and latches lights on. Next press turns the latch off. Release has no effect. | On while latched; next press turns off. |
| `momentary` / `hold` | Press starts lightning. Hold to keep the lights on afterward. | On while held; release turns off. |

In both modes, button changes **never interrupt lightning or thunder**. During
the sequence, the spotlights stay off for the dim trail, switch on with each
full-strip flash and go off in the gaps. After the final flash, they immediately
adopt the current held/latch state without waiting for thunder. If the actor
already released or toggled off, the remaining flashes still play and the
spotlights finish off. Busy presses change this desired state but do not restart
or queue a lightning sequence. Each process start clears the toggle latch and
requires the button to be released before arming.

The relay command follows the full-white LED frame. Its mechanical contacts
add operating/release delay; check alignment at the shortest configured flash
and gap times. This output switches lights on/off and does not dim them.

## 5. Set up wired audio

Connect the Pi 4's 3.5 mm headphone jack to the powered speakers' AUX/line input.
Power the speakers from their own supply. As `pi`, start the audio services:

```console
systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
```

In the existing `[audio]` table:

```toml
[audio]
enabled = true
output = "wired"
device = ""
background = "resource:background_storm.mp3"
thunder = "resource:lightning_strike.wav"
```

An empty `device` auto-selects the Pi's `bcm2835 Headphones` sink, including with
HDMI connected. Background and thunder mix into that output. For a USB audio
adapter or another wired output, set `device` to its exact sink name from:

```console
pactl list short sinks
wpctl status
```

Unmute the selected output and set its volume plus the speaker's own volume.
`doctor` reports a muted wired sink. The app does not change the desktop default
output. Wired mode needs no Bluetooth pairing or virtual sink.

To use custom recordings, replace `background` and/or `thunder` with absolute
paths, `~/` paths or paths relative to the config file's directory. For example,
`background="~/audio/rain.mp3"`. Background loops continuously; thunder plays
alongside it when triggered. Restart the application after changing audio files.
Set `audio.enabled=false` if using no sound.

## 6. Check components and run the controller

Keep the service stopped while running these commands from the checkout:

```console
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml doctor
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test input --duration 20
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test leds --duration 5
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test audio --duration 12
```

`doctor` is read-only. The input test logs presses/releases; the LED test runs
three strikes and clears the strips; the audio test plays background and one
thunder. Each component test opens only its selected hardware. A successful
software check still requires observing the actual light and audio output.

After verifying relay wiring and inactive behavior, set `lights.enabled=true`
in the config and run the relay test. It holds the spotlights on for two seconds,
then releases the relay:

```console
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml component-test relay --duration 2
```

Run the full controller in the foreground:

```console
.venv/bin/lightning-simulator --config ~/.config/lightning-simulator/config.toml
```

Release the button once after startup, then press to trigger. Confirm the trail,
full flashes, spotlight timing, final steady-light state and button-off behavior.
Ctrl-C stops the foreground app and clears its outputs. For effect adjustments,
see [config.example.toml](../config.example.toml): `travel_seconds` sets the trail
time, `direction` selects the starting end, `flash_min`/`flash_max` set full-flash
durations, and `gap_min`/`gap_max` set pauses between strikes.

## 7. Start automatically at boot

Stop the foreground app first. Install the user unit as `pi`:

```console
mkdir -p ~/.config/systemd/user
cp lightning_simulation.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now lightning_simulation.service
systemctl --user status lightning_simulation.service
journalctl --user -u lightning_simulation.service -f
```

Linger, enabled in step 2, starts the user manager without an interactive login.
The unit runs `.venv/bin/lightning-simulator` with the config in
`~/.config/lightning-simulator/config.toml`. If your checkout is elsewhere, edit
both paths in the copied unit before running `daemon-reload`.

After config edits:

```console
systemctl --user restart lightning_simulation.service
```

Before component tests or rewiring:

```console
systemctl --user stop lightning_simulation.service
```

SIGTERM clears LEDs, stops thunder and releases the relay before closing device
requests. Failures restart the service after five seconds. A restart does not
restore the toggle latch. Reboot once and confirm the service starts, the outputs
are initially inactive and the actor button works after release. The relay's
hardware pull-down provides the inactive request while the process is absent.

## Optional Bluetooth instead of wired audio

Install and enable Bluetooth:

```console
sudo apt install bluez libspa-0.2-bluetooth
sudo usermod -aG bluetooth pi
sudo systemctl enable --now bluetooth.service
```

As `pi`, install the supplied PipeWire/WirePlumber configuration:

```console
mkdir -p ~/.config/pipewire/pipewire-pulse.conf.d ~/.config/wireplumber/wireplumber.conf.d
cp deploy/pipewire-pulse.conf.d/30-lightning-mix.conf ~/.config/pipewire-pulse.conf.d/
cp deploy/wireplumber.conf.d/51-lightning-bluetooth.conf ~/.config/wireplumber/wireplumber.conf.d/
systemctl --user restart pipewire.service pipewire-pulse.service wireplumber.service
```

The WirePlumber fragment targets version 0.5 and enables headless A2DP operation
using [the documented seat-monitoring setting](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html).
Reboot after adding the group so the lingering user manager receives it.

Pair the speaker once, substituting its address:

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

Update the existing `[audio]` table:

```toml
output = "bluetooth"
speaker_address = "AA:BB:CC:DD:EE:FF"
sink = "lightning_mix"
```

Restart the application. The supplied config creates the persistent
`lightning_mix` sink; the app connects it to the paired speaker and retries lost
connections. Background resumes at its current position after an ordinary
speaker outage; unavailable thunder is dropped rather than queued. A complete
audio-server failure can restart background playback. Bluetooth latency affects
flash/thunder timing. These files and pairing are needed only for Bluetooth mode.
