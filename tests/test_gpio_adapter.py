import asyncio
import sys
import time
from types import SimpleNamespace

from lightning_simulator.inputs import GPIOTrigger


def test_stale_fd_readiness_never_calls_blocking_gpio_reader(monkeypatch):
    # A selector can queue one final readiness callback before read_edge_events drains the fd.
    # Reproducing that scheduling race here avoids requiring physical GPIO in the test suite.
    inactive, active = object(), object()
    monkeypatch.setitem(
        sys.modules,
        "gpiod.line",
        SimpleNamespace(
            Value=SimpleNamespace(INACTIVE=inactive, ACTIVE=active),
        ),
    )

    async def scenario():
        callbacks, removed = [], []
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "add_reader", lambda fd, cb: callbacks.append(cb))
        monkeypatch.setattr(loop, "remove_reader", lambda fd: removed.append(fd))
        queued = []
        reads = []

        class Request:
            fd = 42

            def get_value(self, pin):
                return inactive

            def wait_edge_events(self, timeout):
                assert timeout == 0
                return bool(queued)

            def read_edge_events(self):
                assert queued, "would block waiting for a GPIO edge"
                reads.append(True)
                events = list(queued)
                queued.clear()
                return events

        trigger = GPIOTrigger("/dev/gpiochip0", 27, button=True)
        trigger.request = Request()
        source = trigger.events()
        assert not (await anext(source)).active
        pending = asyncio.create_task(anext(source))
        callbacks[0]()  # stale readiness, no edge data
        for _ in range(3):
            await asyncio.sleep(0)
        assert not pending.done() and not reads
        queued.append(
            SimpleNamespace(
                line_seqno=1,
                timestamp_ns=time.monotonic_ns(),
                event_type=1,
                Type=SimpleNamespace(RISING_EDGE=1),
            )
        )
        callbacks[0]()
        assert (await pending).active
        await source.aclose()
        assert removed == [42]

    asyncio.run(scenario())


def test_initial_snapshot_error_removes_registered_reader(monkeypatch):
    monkeypatch.setitem(sys.modules, "gpiod.line", SimpleNamespace(Value=SimpleNamespace(ACTIVE=1)))

    async def scenario():
        loop = asyncio.get_running_loop()
        removed = []
        monkeypatch.setattr(loop, "add_reader", lambda fd, cb: None)
        monkeypatch.setattr(loop, "remove_reader", lambda fd: removed.append(fd))

        def fail(pin):
            raise OSError("GPIO disconnected")

        trigger = GPIOTrigger("/dev/gpiochip0", 17)
        trigger.request = SimpleNamespace(fd=42, get_value=fail)
        import pytest

        with pytest.raises(OSError, match="GPIO disconnected"):
            await anext(trigger.events())
        assert removed == [42]

    asyncio.run(scenario())
