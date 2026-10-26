import logging

log = logging.getLogger(__name__)


class GPIOProp:
    """Active-high relay module; request the line atomically at its inactive value."""

    def __init__(self, chip, pin):
        self.chip, self.pin = chip, pin
        self.request = None
        self.active = False

    def start(self):
        import gpiod
        from gpiod.line import Direction, Value

        self.request = gpiod.request_lines(
            self.chip,
            consumer="lightning-picostorm",
            config={
                self.pin: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.INACTIVE,
                )
            },
        )
        self.active = False

    def set_active(self, active):
        from gpiod.line import Value

        if self.request is not None:
            self.request.set_value(self.pin, Value.ACTIVE if active else Value.INACTIVE)
        if active != self.active:
            log.info("PicoSTORM relay %s", "active" if active else "inactive")
        self.active = active

    def close(self):
        if self.request is not None:
            try:
                self.set_active(False)
            finally:
                self.request.release()
                self.request = None


class SimProp:
    def __init__(self):
        self.active = False
        self.history = []

    def start(self):
        self.set_active(False)

    def set_active(self, active):
        self.active = active
        self.history.append(active)

    def close(self):
        self.set_active(False)


class DisabledProp:
    """Disabled forwarding owns no GPIO and retains no event history."""

    def start(self):
        pass

    def set_active(self, active):
        pass

    def close(self):
        pass
