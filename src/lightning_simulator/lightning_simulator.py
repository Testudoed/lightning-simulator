import importlib.resources
import random
import time

import pygame
from rpi_ws281x import Color

from lightning_simulator.led_client import PixelStrip

# LED strip configuration:
LED_COUNT = 120
LED_PIN = 18
LED_BRIGHTNESS = 255
LED_CHANNEL = 0

strip = PixelStrip(LED_COUNT, LED_PIN, brightness=LED_BRIGHTNESS, channel=LED_CHANNEL)
strip.begin()


def lightning_flash(strip, flash_duration=0.05):
    for i in reversed(range(strip.numPixels())):
        strip.setPixelColor(i, Color(255, 255, 255))
    strip.show()
    time.sleep(flash_duration)

    for j in range(strip.numPixels()):
        strip.setPixelColor(j, Color(0, 0, 0))
    strip.show()


def multiflash(strip, flashes):
    for _ in range(flashes):
        lightning_flash(strip, flash_duration=random.uniform(0.05, 0.2))
        time.sleep(random.uniform(0.05, 0.3))


lightning_sound = None
try:
    pygame.mixer.init()
    music_file = (
        importlib.resources.files("lightning_simulator")
        / "sounds"
        / "background_storm.mp3"
    )
    lightning_strike_file = (
        importlib.resources.files("lightning_simulator")
        / "sounds"
        / "lightning_strike.wav"
    )

    pygame.mixer.music.load(music_file)
    pygame.mixer.music.set_volume(0.75)
    pygame.mixer.music.play(-1)
    lightning_sound = pygame.mixer.Sound(lightning_strike_file)
    lightning_sound.set_volume(1.0)
except pygame.error:
    pass


while True:
    time.sleep(2)
    if lightning_sound:
        lightning_sound.play()
    multiflash(strip, 5)

    delay = 5
    time.sleep(delay)
