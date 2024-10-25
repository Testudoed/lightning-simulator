from rpi_ws281x import Color, PixelStrip

LED_COUNT = 30
LED_PIN = 18
LED_BRIGHTNESS = 255
LED_CHANNEL = 0

strip = PixelStrip(LED_COUNT, LED_PIN, brightness=LED_BRIGHTNESS, channel=LED_CHANNEL)
strip.begin()


def on():
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(255, 255, 255))
    strip.show()


def off():
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(0, 0, 0))
    strip.show()
