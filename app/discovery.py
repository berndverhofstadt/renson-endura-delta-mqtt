"""Home Assistant style MQTT auto-discovery, consumable by openHAB's MQTT binding.

Enable with MQTT_DISCOVERY_ENABLED=true. Confirmed working end to end: configs
land on the broker and openHAB discovers the device from them. The generated text
config from tools/generate_openhab_config.py remains available as an alternative
for setups that prefer files.

With CONTROLS_ENABLED=false only `sensor` and `binary_sensor` are announced,
which happens to be the best-supported subset in openHAB.

Entities are announced with the human `label` from the field catalog rather than
the device's own cryptic field names (T11, RH11, SUP fan speed).

Config topics are retained, so flipping a setting could otherwise leave ghost
entities behind - announce() retracts the variant it is not using.

The discovery prefix is a second topic tree, so a broker ACL needs both:

    topic readwrite home/ventilation/renson/#
    topic readwrite homeassistant/+/renson_endura_delta/#
"""

import json

from app.topics import FILTER_RESET, command_topic, state_topic
from shared.fields import controllable, FIELDS

# unit -> (HA device_class, HA unit_of_measurement)
SENSOR_UNITS = {
    "degC": ("temperature", "°C"),
    "ppm": ("carbon_dioxide", "ppm"),
    "%": (None, "%"),
    "rpm": (None, "rpm"),
    "m3/h": (None, "m³/h"),
    "V": ("voltage", "V"),
    "d": ("duration", "d"),
    "min": ("duration", "min"),
}

HUMIDITY_SLUGS = {"indoor_humidity", "exhaust_humidity"}


def build_announcer(bridge, config, base_topic, status_topic):
    if not config.get("mqtt_discovery_enabled"):
        return None
    return DiscoveryAnnouncer(bridge, config, base_topic, status_topic)


class DiscoveryAnnouncer:
    def __init__(self, bridge, config, base_topic, status_topic):
        self.bridge = bridge
        self.base_topic = base_topic
        self.status_topic = status_topic
        self.prefix = config["mqtt_discovery_prefix"].rstrip("/")
        self.device_id = config["mqtt_discovery_device_id"]
        self.device = {
            "identifiers": [self.device_id],
            "name": config["mqtt_discovery_device_name"],
            "manufacturer": "Renson",
            "model": "Endura Delta",
        }
        # With controls off, nothing gets a command topic: advertising entities
        # that silently do nothing is worse than not advertising them.
        self.controls_enabled = config.get("controls_enabled", True)
        self.controllable_slugs = (
            {f.slug for f in controllable(config["expose_installer_settings"])}
            if self.controls_enabled else set()
        )

    def _config_topic(self, component, object_id):
        return f"{self.prefix}/{component}/{self.device_id}/{object_id}/config"

    def _retract(self, component, object_id):
        """Delete a retained config, so a flipped setting cannot leave a ghost.

        An empty payload is how the convention removes an entity; without this,
        turning controls off would leave the old switch/select/number configs
        retained on the broker and still discoverable.
        """
        self.bridge.publish(self._config_topic(component, object_id), "", retain=True)

    def _publish(self, component, object_id, payload):
        payload = {
            **payload,
            "unique_id": f"{self.device_id}_{object_id}",
            "object_id": f"{self.device_id}_{object_id}",
            "availability_topic": self.status_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": self.device,
        }
        self.bridge.publish(self._config_topic(component, object_id),
                            json.dumps(payload), retain=True)

    def _refresh_device(self, readings):
        """Fill in the real model and firmware, once a poll has told us them."""
        if not readings:
            return
        model = readings.get(("Device type", (0, 0, 0)))
        firmware = readings.get(("Firmware version", (0, 0, 0)))
        if model:
            self.device["model"] = model
        if firmware:
            self.device["sw_version"] = firmware

    def announce(self, readings=None):
        self._refresh_device(readings)
        for field in FIELDS:
            writable = field.slug in self.controllable_slugs
            component, payload = self._describe(field, writable)
            # A field is a switch or a binary_sensor, a select or a sensor, and
            # so on depending on whether it is writable right now. Retract the
            # variant we are not using, in case a previous run published it.
            other, _ = self._describe(field, not writable)
            if other != component:
                self._retract(other, field.slug)
            self._publish(component, field.slug, payload)

        if self.controls_enabled:
            self._publish("button", FILTER_RESET, {
                "name": "Filter reset",
                "command_topic": command_topic(self.base_topic, FILTER_RESET),
                "payload_press": "PRESS",
                "icon": "mdi:air-filter",
            })
        else:
            self._retract("button", FILTER_RESET)

    def _describe(self, field, writable):
        state = state_topic(self.base_topic, field)
        name = field.label

        if field.kind == "bool":
            if writable:
                return "switch", {
                    "name": name, "state_topic": state,
                    "command_topic": command_topic(self.base_topic, field.slug),
                    "payload_on": "ON", "payload_off": "OFF",
                    "state_on": "ON", "state_off": "OFF",
                }
            return "binary_sensor", {
                "name": name, "state_topic": state,
                "payload_on": "ON", "payload_off": "OFF",
            }

        if field.kind == "enum" and writable:
            return "select", {
                "name": name, "state_topic": state,
                "command_topic": command_topic(self.base_topic, field.slug),
                "options": list(field.options or []),
            }

        if field.kind == "number" and writable:
            payload = {
                "name": name, "state_topic": state,
                "command_topic": command_topic(self.base_topic, field.slug),
                "mode": "box",
            }
            if field.minimum is not None:
                payload["min"] = field.minimum
            if field.maximum is not None:
                payload["max"] = field.maximum
            device_class, unit = SENSOR_UNITS.get(field.unit, (None, None))
            if unit:
                payload["unit_of_measurement"] = unit
            return "number", payload

        if field.kind in ("string", "time", "enum"):
            return "sensor", {"name": name, "state_topic": state}

        device_class, unit = SENSOR_UNITS.get(field.unit, (None, None))
        if field.slug in HUMIDITY_SLUGS:
            device_class = "humidity"
        payload = {"name": name, "state_topic": state, "state_class": "measurement"}
        if device_class:
            payload["device_class"] = device_class
        if unit:
            payload["unit_of_measurement"] = unit
        return "sensor", payload
