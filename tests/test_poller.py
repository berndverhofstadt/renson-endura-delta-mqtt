import json
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
