import time

import RPi.GPIO as GPIO

PIR_PIN = 17

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIR_PIN, GPIO.IN)


try:
    while True:
        if GPIO.input(PIR_PIN):
            print("Motion detected! Triggering lightning and thunder.")

        time.sleep(0.5)

except KeyboardInterrupt:
    GPIO.cleanup()
