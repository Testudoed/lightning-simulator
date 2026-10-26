"""Streaming background and one reserved thunder channel, mixed into a stable sink."""

import asyncio
import logging
import os
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path

from lightning_simulator.config import AudioConfig

log = logging.getLogger(__name__)


def sound_resource(name):
    if name not in ("background_storm.mp3", "lightning_strike.wav"):
        raise ValueError(f"Unknown packaged sound: {name}")
    return files("lightning_simulator").joinpath("sounds", name)


def resolve_audio_file(value: str, resources: ExitStack) -> Path:
    """Resolve and check a selected file, retaining extracted resources for its owner."""
    if not value.strip():
        raise ValueError("Audio file path must not be empty")
    path = (
        resources.enter_context(as_file(sound_resource(value[9:])))
        if value.startswith("resource:")
        else Path(value).expanduser().resolve()
    )
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    with path.open("rb") as stream:
        header = stream.read(43)
    if not header:
        raise ValueError(f"Audio file is empty: {path}")
    if header.startswith(b"version https://git-lfs.github.com/spec/"):
        raise ValueError(f"{path} is a Git LFS pointer; run git lfs pull before deployment")
    return path


class PygameAudio:
    def __init__(self, config: AudioConfig):
        self.config = config
        self.mixer = self.channel = self.sound = None
        self.resources = ExitStack()
        self.connected = False

    @property
    def started(self):
        return self.mixer is not None

    def _path(self, value):
        return str(resolve_audio_file(value, self.resources))

    def start(self):
        if self.started:
            return
        os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
        os.environ["SDL_AUDIODRIVER"] = "pulseaudio"
        os.environ["PULSE_SINK"] = self.config.sink
        from pygame import mixer

        try:
            background = self._path(self.config.background)
            thunder = self._path(self.config.thunder)
            mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            self.mixer = mixer
            mixer.set_num_channels(2)
            mixer.set_reserved(1)
            self.channel = mixer.Channel(0)
            self.sound = mixer.Sound(thunder)
            self.channel.set_volume(self.config.thunder_volume)
            mixer.music.load(background)
            mixer.music.set_volume(self.config.background_volume)
            mixer.music.play(-1)
            log.info("Streaming background started on %s", self.config.sink)
        except BaseException:
            mixer.quit()
            self.mixer = self.channel = self.sound = None
            self.resources.close()
            raise

    def set_connected(self, connected):
        if connected != self.connected:
            log.info("Bluetooth audio %s", "available" if connected else "unavailable")
        self.connected = connected
        if not connected:
            self.stop_thunder()

    async def thunder(self):
        if not self.started or not self.connected:
            log.info("Thunder skipped: audio unavailable (no replay queued)")
            return
        try:
            self.channel.play(self.sound)
            while self.channel.get_busy():
                await asyncio.sleep(0.02)
        except Exception as exc:
            log.warning("Triggered audio failed; lighting continues: %s", exc)
            self.set_connected(False)
        finally:
            self.stop_thunder()

    def stop_thunder(self):
        if self.channel is not None:
            try:
                self.channel.stop()
            except Exception as exc:
                log.warning("Thunder channel stop failed: %s", exc)

    def healthy(self):
        try:
            return self.started and self.mixer.get_init() and self.mixer.music.get_busy()
        except Exception:
            return False

    def close(self):
        self.set_connected(False)
        try:
            if self.mixer is not None:
                try:
                    self.mixer.music.stop()
                finally:
                    self.mixer.quit()
        except Exception as exc:
            log.warning("Mixer cleanup after audio failure: %s", exc)
        finally:
            self.mixer = self.channel = self.sound = None
            self.resources.close()


class SimAudio:
    def __init__(self, duration=2):
        self.duration = duration
        self.thunder_plays = self.thunder_stops = self.background_starts = 0
        self.playing = False

    def start(self):
        self.background_starts += 1

    async def thunder(self):
        self.thunder_plays += 1
        self.playing = True
        try:
            await asyncio.sleep(self.duration)
        finally:
            self.playing = False

    def stop_thunder(self):
        self.thunder_stops += 1
        self.playing = False

    def close(self):
        self.stop_thunder()


class SilentAudio(SimAudio):
    def __init__(self):
        super().__init__(duration=0)
