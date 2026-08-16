import json
import os
import threading
import logging

from app.poller import fan_running, publish_errors, publish_readings
from app.topics import state_topic
from shared.fields import BY_SLUG

BASE = "home/ventilation/renson"
LOGGER = logging.getLogger("test")


class FakeBridge:
    def __init__(self):
        self.published = {}

    def publish(self, topic, payload, retain=True):
        self.published[topic] = payload


def test_only_reported_fields_are_published():
    readings = {
        ("CO2", (0, 0, 0)): "554",
        ("T11", (0, 0, 0)): "25.201210",
    }
    bridge = FakeBridge()
    published = publish_readings(bridge, BASE, readings, LOGGER)

    assert published == 2
    assert bridge.published[state_topic(BASE, BY_SLUG["co2"])] == "554"
    assert bridge.published[state_topic(BASE, BY_SLUG["indoor_temperature"])] == "25.20"
    # A unit without the CO2/IAQ option simply never reports IAQ.
    assert state_topic(BASE, BY_SLUG["iaq"]) not in bridge.published


def test_unpublishable_reading_does_not_count():
    readings = {("Measured SUP airflow", (0, 0, 0)): "nan"}
    bridge = FakeBridge()
    assert publish_readings(bridge, BASE, readings, LOGGER) == 0
    assert bridge.published == {}


def test_error_slots_are_collected_newest_first():
    readings = {
        ("Error list", (0, 0, 0)): "C 16/8/2026 13:16 36: EtaFanTachoError",
        ("Error list", (0, 0, 1)): "C 16/8/2026 13:16 35: SupFanTachoError",
        ("Error list", (0, 0, 2)): "",
    }
    bridge = FakeBridge()
    publish_errors(bridge, BASE, readings, LOGGER)

    errors = json.loads(bridge.published[f"{BASE}/diagnostics/errors"])
    assert errors == [
        "C 16/8/2026 13:16 36: EtaFanTachoError",
        "C 16/8/2026 13:16 35: SupFanTachoError",
    ]
    assert bridge.published[f"{BASE}/diagnostics/error_active"] == "ON"


def test_no_errors_publishes_empty_array():
    bridge = FakeBridge()
    publish_errors(bridge, BASE, {("Error list", (0, 0, 0)): ""}, LOGGER)
    assert bridge.published[f"{BASE}/diagnostics/errors"] == "[]"
    assert bridge.published[f"{BASE}/diagnostics/error_active"] == "OFF"


def test_fan_running_distinguishes_missing_from_stopped():
    assert fan_running({("SUP fan active", (0, 0, 0)): "1"}, "SUP fan active") is True
    assert fan_running({("SUP fan active", (0, 0, 0)): "0"}, "SUP fan active") is False
    assert fan_running({}, "SUP fan active") is None


def test_interruptible_sleep_returns_immediately_on_shutdown(monkeypatch):
    import time as _time
    from app import poller

    monkeypatch.setattr(poller, "SHUTDOWN", threading.Event())
    poller.SHUTDOWN.set()
    started = _time.monotonic()
    poller.interruptible_sleep(30)
    # Without the event it would block for 30s; docker would then SIGKILL us.
    assert _time.monotonic() - started < 1.0


def test_interruptible_sleep_waits_when_not_shutting_down(monkeypatch):
    import time as _time
    from app import poller

    monkeypatch.setattr(poller, "SHUTDOWN", threading.Event())
    started = _time.monotonic()
    poller.interruptible_sleep(0.2)
    assert _time.monotonic() - started >= 0.15


def test_signal_handler_sets_the_shutdown_flag(monkeypatch):
    import logging as _logging
    import signal as _signal
    from app import poller

    monkeypatch.setattr(poller, "SHUTDOWN", threading.Event())
    poller.install_signal_handlers(_logging.getLogger("test"))
    assert not poller.SHUTDOWN.is_set()
    os.kill(os.getpid(), _signal.SIGTERM)
    assert poller.SHUTDOWN.wait(2)
