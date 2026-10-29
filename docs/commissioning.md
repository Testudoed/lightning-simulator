# Commissioning record

Status: **wired audio playback verified on the target Pi**; see the
[audio test record](commissioning/2026-10-26-wired-audio.md). Complete the remaining
commissioning checks below and keep copies with the machine's deployment notes.
Software simulation is not a visual LED pass.

## LED spike (direct 3.3 V first)

- Operator, date/time, Pi model, Debian/kernel and Python versions:
- Strip model/counts, physical strip boundary index, color order:
- Power supply identity (5 V / 10 A), feeds/fuses, wiring and common-ground points:
- Data cable/ground lengths, resistor and bulk capacitor:
- `/boot/firmware/config.txt` settings and confirmation of reboot:
- Loaded voltage at first and second strips, intended brightness:
- JSON report filename and software result (completed/error/interrupted):
- Visual solid red/green/blue/white and alternating patterns:
- Moving pixel at every position, both ends and strip boundary:
- Blackout and five-flash test:
- Full 600-second stress completed with CPU activity:
- Flicker, stuck pixels, missed updates or other observations:
- Visual result (pass/fail/unassessed), operator initials:
- Faults corrected and repeat results:
- If needed: 74AHCT125 comparison wiring/report/observations and conclusion:
- Accepted production wiring (direct or shifter), brightness and operating conditions:

A pass applies to the recorded setup and observations; it does not establish an
electrical guarantee across other conditions. Require the shifter only when the
comparison establishes it is needed.

## Inputs and spotlights

- [ ] At boot, LED and relay outputs inactive; held button/PIR cannot trigger until inactive.
- [ ] PIR warmup ignores activation; low at end arms, high at end requires a subsequent low.
- [ ] Motion produces one sequence per new detection, no repeats while held high.
- [ ] Motion ending lets the current sequence finish; busy retriggers do not queue.
- [ ] Spotlights stay dark during the trail/gaps and follow each full-strip flash.
- [ ] Momentary/hold starts once; release never stops lightning or thunder.
- [ ] Toggle starts once; next press changes spotlight latch without stopping playback.
- [ ] Steady spotlight state begins immediately after the last flash, before thunder ends.
- [ ] Release/toggle-off during a flash allows all remaining flashes, then finishes off.
- [ ] Busy presses do not restart or queue lightning.
- [ ] Switch bounce causes no extra presses; configured 50 ms default verified.
- [ ] Background position is continuous through every button changes.
- [ ] Relay module is active-high, 3.3 V-compatible, driven through its integrated driver.
- [ ] Relay COM/NO switches the separate 12 V spotlight supply; polarity verified.
- [ ] Relay logic uses its rated 3 V/3.3 V supply; 12 V stays off logic and Pi.
- [ ] Mechanical relay timing checked at minimum flash/gap durations.
- [ ] Relay inactive while Pi is unpowered, booting, stopped and restarting.
- [ ] Service restart during each effect stage clears outputs and never restores toggle latch.

## Audio and unattended boot

- Selected audio mode (`wired` by default, or `bluetooth`):
- Wired device name, output volume and listening observations:
- [ ] Wired mode uses the Pi jack with powered speakers, including with HDMI connected.
- [ ] Wired background and thunder overlap audibly; button changes preserve background position.
- [ ] Wired test stops cleanly; missing output or audio-server failure leaves lighting operational.
- [ ] Wired mode works without Bluetooth, a speaker address or a virtual sink.

For optional Bluetooth mode:

- Speaker model/address, pairing/trust, A2DP profile, volume and latency observations:
- [ ] Boot with speaker absent: lighting operational, no queued thunder.
- [ ] Power speaker on later: background audible at its current position.
- [ ] Background and thunder overlap audibly with acceptable mixed volume.
- [ ] Drop connection during thunder: lighting continues, thunder stops, no later replay.
- [ ] Reconnect repeatedly: one loopback, no duplicate/delayed thunder, background continuous.
- [ ] Commands time out without freezing input handling.
- [ ] Reboot with no login: lingering user service, GPIO/SPI access and audio all work.
- [ ] SIGTERM clears LEDs, stops triggered audio and releases relay promptly.
- [ ] Final config archived; Spotlight control enabled only after relay acceptance.
