"""SPI0 LED driver. Importing this module never opens hardware."""

from collections.abc import Sequence

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)


class SPILEDs:
    def __init__(self, count=120, pin=10, brightness=255, color_order="GRB"):
        if pin != 10:
            raise ValueError("SPI0 MOSI on the Pi 4 header requires BCM10 (physical pin 19)")
        self.count, self.pin = count, pin
        self.brightness, self.color_order = brightness, color_order
        self.strip = None
        self.initialized = False

    def start(self):
        import rpi_ws281x

        self.strip = rpi_ws281x.PixelStrip(
            self.count,
            self.pin,
            freq_hz=800_000,
            brightness=self.brightness,
            channel=0,
            strip_type=getattr(rpi_ws281x, f"WS2811_STRIP_{self.color_order}"),
        )
        try:
            self.strip.begin()  # BCM10 selects SPI; no PWM/privileged daemon.
            self.initialized = True
            self.clear()
        except BaseException:
            self.close()
            raise

    def pixels(self, colors: Sequence[RGB]):
        if len(colors) != self.count:
            raise ValueError(f"Expected {self.count} pixels")
        for i, (r, g, b) in enumerate(colors):
            self.strip.setPixelColor(i, (r << 16) | (g << 8) | b)
        self.strip.show()

    def fill(self, color: RGB):
        self.pixels([color] * self.count)

    def clear(self):
        if self.strip is not None and self.initialized:
            self.fill(BLACK)

    def close(self):
        if self.strip is not None:
            try:
                self.clear()
            finally:
                # The binding has no public close; its atexit cleanup is idempotent.
                self.strip._cleanup()
                self.strip = None
                self.initialized = False


class SimLEDs:
    def __init__(self, count=120):
        self.count = count
        self.frame = [BLACK] * count
        self.updates = 0

    def start(self):
        self.clear()

    def pixels(self, colors):
        self.frame = list(colors)
        self.updates += 1

    def fill(self, color):
        self.pixels([color] * self.count)

    def clear(self):
        self.fill(BLACK)

    def close(self):
        self.clear()
