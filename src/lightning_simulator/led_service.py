# led_service.py

import os
import signal
import socket
import sys

from rpi_ws281x import Color, PixelStrip

# LED strip configuration:
LED_COUNT = 120  # Number of LED pixels.
LED_PIN = 18  # GPIO pin connected to the pixels (must support PWM!).
LED_FREQ_HZ = 800000  # LED signal frequency in hertz (usually 800kHz)
LED_DMA = 10  # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 255  # Set to 0 for darkest and 255 for brightest
LED_INVERT = False  # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL = 0

# Initialize the LED strip
strip = PixelStrip(
    LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL
)
strip.begin()

# Socket configuration
SOCKET_PATH = "/tmp/led_strip_socket"


# Signal handler for cleanup
def signal_handler(sig, frame):
    set_all_leds(strip, 0, 0, 0)
    strip.show()
    # Remove the socket file
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# Function to set LED color
def set_led(strip, index, r, g, b):
    if 0 <= index < strip.numPixels():
        strip.setPixelColor(index, Color(r, g, b))


# Function to set color for all LEDs
def set_all_leds(strip, r, g, b):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(r, g, b))


# Function to show the LED strip
def show_leds(strip):
    strip.show()


# Function to set brightness for all LEDs
def set_brightness(strip, brightness):
    # Brightness should be between 0 and 255
    strip.setBrightness(max(0, min(255, brightness)))
    strip.show()


# Main socket server
def main():
    # Create and bind the socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o666)
    sock.listen(1)
    print("LED service is now running.")

    while True:
        # Accept incoming connections
        conn, _ = sock.accept()
        with conn:
            data = conn.recv(1024).decode().strip()
            if data.startswith("SET "):
                # Set individual LED: "SET <index> <r> <g> <b>"
                try:
                    _, index, r, g, b = data.split()
                    set_led(strip, int(index), int(r), int(g), int(b))
                except ValueError:
                    print("Invalid SET command received.")
            elif data.startswith("SET_ALL "):
                # Set all LEDs: "SET_ALL <r> <g> <b>"
                try:
                    _, r, g, b = data.split()
                    set_all_leds(strip, int(r), int(g), int(b))
                except ValueError:
                    print("Invalid SET_ALL command received.")
            elif data == "SHOW":
                # Show the LEDs
                show_leds(strip)
            elif data.startswith("BRIGHTNESS "):
                # Set brightness: "BRIGHTNESS <value>"
                try:
                    _, brightness = data.split()
                    set_brightness(strip, int(brightness))
                except ValueError:
                    print("Invalid BRIGHTNESS command received.")


if __name__ == "__main__":
    main()
