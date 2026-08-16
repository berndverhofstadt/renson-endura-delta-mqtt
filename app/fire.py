"""Fire-alarm awareness.

This bridge deliberately does NOT stop the ventilation itself. The API offers
no supported way to do it: `Input N value` is read-only, so the unit's own
fire-safety function cannot be triggered over the network, and the one writable
field that does spin the fans down (`Total nominal airflow`) makes the firmware
latch fan tacho errors 35/36 and refuse to restart until someone power-cycles
the unit. A fire alarm must never leave ventilation dead until a human walks to
the machine.

The supported stop is a dry contact on the unit's 24 V DC input with
`Input N function` = 0. What this module does is watch that it worked: it
mirrors the alarm state, reports whether both fans have actually stopped, and
logs loudly when an alarm is active while the fans are still turning.

See docs/FIRE_SAFETY.md for the wiring.
"""

import logging

LOGGER = logging.getLogger("renson.fire")


class FireMonitor:
    def __init__(self, base_topic, alarm_topic, payloads_on):
        self.base_topic = base_topic
        self.alarm_topic = alarm_topic
        self.payloads_on = {value.strip().lower() for value in payloads_on if value.strip()}
        self.alarm_active = False
        self._warned = False

    @property
    def enabled(self):
        return bool(self.alarm_topic)

    def handle(self, topic, payload):
        """Consume an inbound message. Returns True if it was the alarm topic."""
        if not self.enabled or topic != self.alarm_topic:
            return False

        active = payload.strip().lower() in self.payloads_on
        if active != self.alarm_active:
            LOGGER.warning("fire_alarm_state_changed active=%s payload=%s", active, payload)
            self._warned = False
        self.alarm_active = active
        return True

    def publish(self, bridge, supply_running, extract_running):
        """Publish alarm state and whether the hardware stop actually engaged."""
        if not self.enabled:
            return

        bridge.publish(f"{self.base_topic}/fire/alarm",
                       "ON" if self.alarm_active else "OFF", retain=True)

        # Unknown fan state (field missing this cycle) must not read as a
        # confirmed stop, so require an explicit False from both.
        stopped = supply_running is False and extract_running is False
        bridge.publish(f"{self.base_topic}/fire/stop_confirmed",
                       "ON" if (self.alarm_active and stopped) else "OFF", retain=True)

        if self.alarm_active and not stopped and not self._warned:
            LOGGER.error(
                "fire_alarm_active_but_fans_running supply=%s extract=%s - the input "
                "contact did not stop the unit; check the wiring and that "
                "'Input N function' is 0", supply_running, extract_running)
            self._warned = True
