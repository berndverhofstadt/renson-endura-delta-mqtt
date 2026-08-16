import json

from app.discovery import build_announcer

BASE = "home/ventilation/renson"
STATUS = f"{BASE}/status"


class FakeBridge:
    def __init__(self):
        self.published = {}

    def publish(self, topic, payload, retain=True):
        self.published[topic] = payload


def config(**overrides):
    base = {
        "mqtt_discovery_enabled": True,
        "mqtt_discovery_prefix": "homeassistant",
        "mqtt_discovery_device_id": "renson_endura_delta",
        "mqtt_discovery_device_name": "Renson Endura Delta",
        "expose_installer_settings": False,
        "controls_enabled": True,
    }
    base.update(overrides)
    return base


def announce(**overrides):
    bridge = FakeBridge()
    build_announcer(bridge, config(**overrides), BASE, STATUS).announce(
        {("Device type", (0, 0, 0)): "ED 450 T4 L SHT IAQ CO2 W02",
         ("Firmware version", (0, 0, 0)): "Endura Delta 0.0.69"})
    return bridge.published


def components(published):
    counts = {}
    for topic, payload in published.items():
        if payload == "":
            continue
        counts[topic.split("/")[1]] = counts.get(topic.split("/")[1], 0) + 1
    return counts


def test_disabled_returns_no_announcer():
    assert build_announcer(FakeBridge(), config(mqtt_discovery_enabled=False),
                           BASE, STATUS) is None


def test_device_identity_comes_from_the_readings():
    published = announce()
    payload = json.loads(published["homeassistant/select/renson_endura_delta/manual_level/config"])
    assert payload["device"]["model"] == "ED 450 T4 L SHT IAQ CO2 W02"
    assert payload["device"]["sw_version"] == "Endura Delta 0.0.69"


def test_controls_produce_command_topics_and_a_button():
    published = announce()
    counts = components(published)
    assert counts["select"] == 4
    assert counts["button"] == 1
    assert counts["switch"] == 4

    payload = json.loads(published["homeassistant/select/renson_endura_delta/manual_level/config"])
    assert payload["command_topic"] == f"{BASE}/set/manual_level"
    assert payload["options"][0] == "Off"


def test_read_only_mode_announces_sensors_only():
    published = announce(controls_enabled=False)
    counts = components(published)
    assert set(counts) == {"sensor", "binary_sensor"}
    # Nothing may carry a command topic the bridge would refuse.
    for payload in published.values():
        if payload:
            assert "command_topic" not in json.loads(payload)


def test_read_only_mode_retracts_the_control_variants():
    published = announce(controls_enabled=False)
    # Empty payload is how the convention deletes a retained config.
    for topic in ("homeassistant/select/renson_endura_delta/manual_level/config",
                  "homeassistant/switch/renson_endura_delta/breeze_enable/config",
                  "homeassistant/number/renson_endura_delta/co2_threshold/config",
                  "homeassistant/button/renson_endura_delta/filter_reset/config"):
        assert published[topic] == "", topic


def test_control_mode_retracts_the_sensor_variants():
    published = announce()
    # manual_level is a select now, so any stale sensor config must be cleared.
    assert published["homeassistant/sensor/renson_endura_delta/manual_level/config"] == ""
    assert published["homeassistant/binary_sensor/renson_endura_delta/breeze_enable/config"] == ""


def test_blocked_fields_are_read_only_sensors():
    published = announce()
    payload = json.loads(
        published["homeassistant/sensor/renson_endura_delta/total_nominal_airflow/config"])
    assert "command_topic" not in payload
