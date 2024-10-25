import importlib.resources
import random
import signal
import time

import pygame
import RPi.GPIO as GPIO
from rpi_ws281x import Color

from lightning_simulator.led_client import PixelStrip

LED_COUNT = 120
LED_PIN = 18
LED_BRIGHTNESS = 255
LED_CHANNEL = 0
PIR_PIN = 17


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

def signal_handler(sig, frame):
    GPIO.cleanup()


def main():
    strip = PixelStrip(
        LED_COUNT, LED_PIN, brightness=LED_BRIGHTNESS, channel=LED_CHANNEL
    )
    strip.begin()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIR_PIN, GPIO.IN)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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

    delay = 5
    while True:
        if GPIO.input(PIR_PIN):
            if lightning_sound:
                lightning_sound.play()
            multiflash(strip, 5)
            time.sleep(delay)
        else:
            time.sleep(0.1)


if __name__ == "__main__":
    main()
