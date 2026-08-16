import pytest

from app.commands import CommandHandler
from shared.fields import DANGEROUS
from shared.renson_client import RensonError

BASE = "home/ventilation/renson"


class FakeClient:
    def __init__(self, values=None):
        self.values = values or {}
        self.writes = []

    def read_field(self, name, index=(0, 0, 0)):
        return self.values.get(name)

    def write_field(self, name, value, index=(0, 0, 0)):
        if name in DANGEROUS:
            raise RensonError(f"refusing to write '{name}'")
        self.writes.append((name, value))
        return value


def handler(client, **kwargs):
    return CommandHandler(client, BASE, **kwargs)


def test_manual_level_is_normalised_before_it_reaches_the_device():
    client = FakeClient()
    assert handler(client).handle(f"{BASE}/set/manual_level", "level2")
    assert client.writes == [("Manual level", "Level2")]


def test_invalid_enum_never_reaches_the_device():
    client = FakeClient()
    assert not handler(client).handle(f"{BASE}/set/manual_level", "Stop")
    assert client.writes == []


def test_filter_reset_writes_preset_into_remaining():
    client = FakeClient({"Filter preset time": "180"})
    assert handler(client).handle(f"{BASE}/set/filter_reset", "PRESS")
    assert client.writes == [("Filter remaining time", "180")]


def test_filter_reset_ignores_a_stray_payload():
    client = FakeClient({"Filter preset time": "180"})
    assert not handler(client).handle(f"{BASE}/set/filter_reset", "OFF")
    assert client.writes == []


def test_blocked_field_is_not_a_command_at_all():
    client = FakeClient()
    assert not handler(client, expose_installer=True).handle(
        f"{BASE}/set/total_nominal_airflow", "0")
    assert client.writes == []


def test_installer_field_needs_the_flag():
    client = FakeClient()
    assert not handler(client).handle(f"{BASE}/set/input1_function", "0")
    assert client.writes == []
    assert handler(client, expose_installer=True).handle(f"{BASE}/set/input1_function", "0")
    assert client.writes == [("Input 1 function", "0")]


def test_read_only_field_is_rejected_locally():
    client = FakeClient()
    assert not handler(client, expose_installer=True).handle(f"{BASE}/set/co2", "500")
    assert client.writes == []


def test_controls_disabled_blocks_everything():
    client = FakeClient({"Filter preset time": "180"})
    disabled = handler(client, enabled=False)
    assert not disabled.handle(f"{BASE}/set/manual_level", "Level1")
    assert not disabled.handle(f"{BASE}/set/filter_reset", "PRESS")
    assert client.writes == []


def test_unrelated_topic_is_ignored():
    client = FakeClient()
    assert not handler(client).handle("home/fire/alarm", "1")


def test_client_guard_refuses_dangerous_writes():
    client = FakeClient()
    with pytest.raises(RensonError):
        client.write_field("Total nominal airflow", "0")
