# Wired audio test — 2026-10-26

- Target: `pi@192.168.52.194` (`rpi4-4889`, Raspberry Pi 4B).
- PipeWire, pipewire-pulse and WirePlumber were already active.
- ALSA exposed `Headphones` / `bcm2835 Headphones`; PipeWire exposed
  `alsa_output.platform-fe00b840.mailbox.stereo-fallback`.
- Preflight output was unmuted at 40% volume. The test did not change the system
  output volume or the desktop's default audio output.
- The operator confirmed the powered speakers were connected and ready.
- An isolated preview used the checkout's existing Python environment and the
  new wired router with default configuration: bundled background/thunder,
  application volumes 0.35 / 0.65, and automatic Pi-jack selection.
- Preview archive SHA-256:
  `6ff08d6e7d754c9f518797e144b87154a7a4632e59bd567dc3b6f689a1349f4e`.
- Command: `python -m lightning_simulator component-test audio --duration 12`.
- Result: exit code 0; no reported playback or cleanup errors. The component test
  started streaming background and triggered one thunder while it continued.
- Operator observation: **“I heard audio.”**
- Only audio was exercised; GPIO inputs, LEDs and the prop relay were not opened.

Target log timestamps:

```text
2026-10-26 16:08:55,535 INFO Streaming background started on alsa_output.platform-fe00b840.mailbox.stereo-fallback
2026-10-26 16:08:55,536 INFO Audio output available
2026-10-26 16:09:07,328 INFO Audio output unavailable
```

The final unavailable transition records normal test shutdown. Trigger/button
behavior with physical audio, failure recovery on the target, and unattended
boot remain separate commissioning checks.
