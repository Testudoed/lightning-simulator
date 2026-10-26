# First deliverable: direct 3.3 V SPI compatibility spike

Run this independently of the full controller. It requests neither the PIR nor
relay GPIO and does not initialize audio. Do this on the target Pi before
accepting production LED wiring.

## Wiring and boot settings

With power disconnected, move LED data to **BCM10 / physical pin 19**. Keep LED
power at **5 V** using the existing **5 V, 10 A** supply. Connect supply ground,
both strip grounds and Pi GND (for example physical pin 6). Supply each strip
with its own suitably rated, fused power feed. Connect the first strip's DOUT
to the second strip's DIN so positions span all 120 pixels. Record the index
at the strip boundary. Do not connect both DINs in parallel.

The Pi header must not carry LED load current. Power the Pi normally; connect
the grounds, not the separate positive supplies. Use a short data cable with a
nearby ground return. Put a 330 ohm series resistor near the first DIN and a
1000 uF capacitor rated at least 10 V across 5 V/GND near the strip power input,
with correct polarity. These values follow [Adafruit's pixel wiring guidance](https://learn.adafruit.com/adafruit-neopixel-uberguide/best-practices).

### Raspberry Pi 4B header pinout

Physical pin numbers identify positions on the 40-pin header; BCM numbers identify
GPIO signals used by the software. Viewed from above with the USB/Ethernet ports
on the right and the GPIO header along the top edge, physical pin 1 is at the
left end in the row closer to the board's centre. Pin 2 is directly above it,
closer to the board edge. The table below lists adjacent odd/even pin pairs,
starting from that end. See the [official Raspberry Pi GPIO pinout](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio).

| Odd-row signal | Physical pin | Physical pin | Even-row signal |
|---|---:|---:|---|
| 3.3 V | 1 | 2 | 5 V |
| BCM2 / I2C SDA | 3 | 4 | 5 V |
| BCM3 / I2C SCL | 5 | **6** | **GND — common ground for this spike** |
| BCM4 | 7 | 8 | BCM14 / UART TX |
| GND | 9 | 10 | BCM15 / UART RX |
| BCM17 | 11 | 12 | BCM18 |
| BCM27 | 13 | 14 | GND |
| BCM22 | 15 | 16 | BCM23 |
| 3.3 V | 17 | 18 | BCM24 |
| **BCM10 / SPI0 MOSI — LED data** | **19** | 20 | GND |
| BCM9 / SPI0 MISO | 21 | 22 | BCM25 |
| BCM11 / SPI0 SCLK | 23 | 24 | BCM8 / SPI0 CE0 |
| GND | 25 | 26 | BCM7 / SPI0 CE1 |
| BCM0 / ID_SD (HAT EEPROM) | 27 | 28 | BCM1 / ID_SC (HAT EEPROM) |
| BCM5 | 29 | 30 | GND |
| BCM6 | 31 | 32 | BCM12 |
| BCM13 | 33 | 34 | GND |
| BCM19 | 35 | 36 | BCM16 |
| BCM26 | 37 | 38 | BCM20 |
| GND | 39 | 40 | BCM21 |

For the direct-data spike, connect only these two Pi header pins:

- **Physical 19 / BCM10:** through the 330 ohm resistor to the first strip's DIN.
- **Physical 6 / GND:** to the external supply negative and both strip grounds.

The strips receive +5 V directly from the external supply. Leave Pi power pins
1, 2, 4 and 17 unconnected to the LED power wiring. SCLK, MISO and chip-select
pins also have no strip connection: the driver uses SPI to generate pulse-width
data on MOSI, which the LEDs decode without a separate clock wire. PIR, button
and relay connections are not needed for this standalone spike.

### SPI boot settings and fixed core clock

In `/boot/firmware/config.txt`, enable SPI and fix the Pi 4 core clock, then reboot:

```ini
[all]
dtparam=spi=on
[pi4]
core_freq=500
core_freq_min=500
```

On the Pi 4, SPI timing depends on the GPU core clock. Dynamic core-frequency
changes between idle and load can change the SPI pulse widths, which carry the
LED data. Setting both `core_freq` and `core_freq_min` to 500 MHz keeps that clock
fixed so updates have consistent timing. These settings control the GPU core
clock; they do not fix the ARM CPU frequency. The [driver's Pi 4 SPI guidance](https://github.com/jgarff/rpi_ws281x#limitations)
requires them for this backend.

Confirm that later entries do not override these settings. Verify
`/dev/spidev0.0` is present and writable by your user. Dedicate SPI0 to the LEDs;
no other SPI device may share it. These clock settings and the SPI bus
restriction come from [rpi_ws281x's driver documentation](https://github.com/jgarff/rpi_ws281x#limitations).
The driver selects SPI from BCM10, using channel 0 at 800 kHz LED signaling.
120 RGB pixels fit the normal 4096-byte SPI transfer buffer; the configuration
limits count to 400 for this installation. See the deployment guide for GPIO/SPI
permissions and source-build packages if needed.

## Run and observe

From the repository on the Pi, with any old LED/app services stopped:

```console
uv sync --locked --extra pi --no-dev
uv run --locked --no-dev --extra pi lightning-spi-spike --brightness 255 --duration 600 --report led-spike-direct.json --notes 'Record cable length, strip model, power feeds and loaded voltage'
```

Use your intended production brightness if it differs from 255. The standalone
Python module also works: `uv run --extra pi python -m lightning_simulator.spi_spike`.
The application wrapper `lightning-simulator --config ... led-spike` takes
brightness/color order from TOML; its diagnostic count remains fixed at 120.

Observe all 120 positions during:

1. Solid red, green, blue and white, about one second each.
2. Alternating red/green and blue/white patterns.
3. One white pixel moving from index 0 to 119, including the strip boundary.
4. Blackout and five lightning flashes at the selected brightness.
5. Ten minutes of repeated patterns and flashes, with about 25% activity on one
   CPU core in a worker thread. Check for flicker, missed updates and stuck pixels.

The program clears LEDs on completion, Ctrl-C and SIGTERM, and attempts blackout
on device errors. No software cleanup can operate after power loss or SIGKILL.
An update/device error fails the software check and exits nonzero. A JSON report
records setup, Python/platform, boot config, requested duration, elapsed time,
software errors and interruption status. `operator_visual_result` is deliberately
`unassessed`: the program cannot see incorrect LED output. A simulated run
(`--simulate --duration 1`) exercises code only and cannot establish compatibility.

## Acceptance and fallback

Record observations in [commissioning.md](commissioning.md) and retain the JSON.
**Pass** requires completed software stress plus correct colors and positions on
both strips, with no observed flicker, stuck pixels or missed updates. Continue
using direct 3.3 V data when that setup passes. This is evidence for the tested
setup, not an electrical guarantee across temperatures, cables or replacement strips.

**Fail:** inspect common ground, DIN/DOUT direction, connections, loaded voltage
at both strips, SPI clock stability, permissions and driver/color-order settings
first. Repeat the diagnostic after fixing any problem. If signal level remains
suspect, repeat with a **74AHCT125** (TTL input thresholds) powered at 5 V:

| 74AHCT125 SO14/TSSOP14 pin | Connection |
|---|---|
| 14 VCC | LED supply +5 V, with 0.1 uF ceramic decoupling to pin 7 |
| 7 GND | Common Pi/LED ground |
| 1 /1OE | Ground (enables channel 1) |
| 2 1A | Pi BCM10 / physical 19 |
| 3 1Y | 330 ohm resistor, then first strip DIN |
| 4, 10, 13 unused /OE | +5 V (disables unused buffers) |
| 5, 9, 12 unused A | Ground; leave unused Y outputs unconnected |

Verify the package pinout against the [NXP datasheet](https://cdn-shop.adafruit.com/datasheets/74AHC125.pdf).
Keep 5 V away from the Pi input/data pin. Do not substitute an AHC125 or a passive
bidirectional I2C shifter. Run the same test with `--wiring 74AHCT125` and a new
report filename. Require the shifter only if this comparison establishes it is
needed; otherwise keep the direct-data setup as commissioned.
