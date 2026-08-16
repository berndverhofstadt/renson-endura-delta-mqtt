from app.fire import FireMonitor

BASE = "home/ventilation/renson"


class FakeBridge:
    def __init__(self):
        self.published = {}

    def publish(self, topic, payload, retain=True):
        self.published[topic] = payload


def monitor(topic="home/fire/alarm"):
    return FireMonitor(BASE, topic, ["1", "on", "true", "alarm"])


def test_disabled_without_a_topic():
    fire = FireMonitor(BASE, "", ["1"])
    assert not fire.enabled
    bridge = FakeBridge()
    fire.publish(bridge, False, False)
    assert bridge.published == {}


def test_alarm_state_tracks_payload():
    fire = monitor()
    assert fire.handle("home/fire/alarm", "1")
    assert fire.alarm_active
    assert fire.handle("home/fire/alarm", "0")
    assert not fire.alarm_active


def test_other_topics_are_not_consumed():
    fire = monitor()
    assert not fire.handle(f"{BASE}/set/manual_level", "Level1")


def test_stop_is_confirmed_only_when_both_fans_are_off():
    fire = monitor()
    fire.handle("home/fire/alarm", "alarm")
    bridge = FakeBridge()

    fire.publish(bridge, True, True)
    assert bridge.published[f"{BASE}/fire/alarm"] == "ON"
    assert bridge.published[f"{BASE}/fire/stop_confirmed"] == "OFF"

    fire.publish(bridge, False, True)
    assert bridge.published[f"{BASE}/fire/stop_confirmed"] == "OFF"

    fire.publish(bridge, False, False)
    assert bridge.published[f"{BASE}/fire/stop_confirmed"] == "ON"


def test_unknown_fan_state_is_not_a_confirmed_stop():
    fire = monitor()
    fire.handle("home/fire/alarm", "1")
    bridge = FakeBridge()
    fire.publish(bridge, None, None)
    assert bridge.published[f"{BASE}/fire/stop_confirmed"] == "OFF"


def test_no_confirmation_without_an_alarm():
    fire = monitor()
    bridge = FakeBridge()
    fire.publish(bridge, False, False)
    assert bridge.published[f"{BASE}/fire/alarm"] == "OFF"
    assert bridge.published[f"{BASE}/fire/stop_confirmed"] == "OFF"
