import socket

from rpi_ws281x import Color

SOCKET_PATH = "/tmp/led_strip_socket"


class PixelStrip:
    def __init__(
        self,
        num,
        pin,
        freq_hz=800000,
        dma=10,
        invert=False,
        brightness=255,
        channel=0,
        strip_type=None,
        gamma=None,
    ) -> None:
        self.leds = [Color(0, 0, 0) for i in range(num)]
        self.setBrightness(brightness)

    @classmethod
    def send_command(cls, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(SOCKET_PATH)
            sock.sendall(command.encode())

    def begin(self): ...

    def setPixelColor(self, n: int, color: Color):
        self.leds[n] = color
        PixelStrip.send_command(f"SET {n} {color.r} {color.b} {color.g}")

    def show(self):
        PixelStrip.send_command("SHOW")

    def setBrightness(self, brightness):
        PixelStrip.send_command(f"BRIGHTNESS {brightness}")

    def numPixels(self):
        """Return the number of pixels in the display."""
        return len(self.leds)

    def getPixelColor(self, n):
        """Get the 24-bit RGB color value for the LED at position n."""
        return self.leds[n]
