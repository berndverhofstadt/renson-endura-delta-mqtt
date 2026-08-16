import pytest

import app.config
from app.config import MIN_POLL_INTERVAL_SECONDS, load_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("RENSON_HOST", "RENSON_PORT", "RENSON_TIMEOUT_SECONDS", "MQTT_HOST",
                 "MQTT_PORT", "MQTT_TLS", "MQTT_USERNAME", "MQTT_PASSWORD",
                 "MQTT_BASE_TOPIC", "POLL_INTERVAL_SECONDS", "CONTROLS_ENABLED",
                 "EXPOSE_INSTALLER_SETTINGS", "MQTT_DISCOVERY_ENABLED",
                 "FIRE_ALARM_TOPIC", "DEBUG_MODE", "LOG_LEVEL", "HEALTHCHECK_PORT"):
        monkeypatch.delenv(name, raising=False)
    # load_config() loads the repo-root .env by absolute path, so chdir does not
    # isolate it - stub the loader out instead.
    monkeypatch.setattr(app.config, "_load_local_dotenv", lambda: None)


def test_host_and_broker_are_required(monkeypatch):
    with pytest.raises(RuntimeError, match="RENSON_HOST"):
        load_config()
    monkeypatch.setenv("RENSON_HOST", "192.168.1.60")
    with pytest.raises(RuntimeError, match="MQTT_HOST"):
        load_config()


def base_env(monkeypatch):
    monkeypatch.setenv("RENSON_HOST", "192.168.1.60")
    monkeypatch.setenv("MQTT_HOST", "broker.example")


def test_defaults(monkeypatch):
    base_env(monkeypatch)
    config = load_config()
    assert config["renson_port"] == 80
    assert config["mqtt_port"] == 1883
    assert config["mqtt_base_topic"] == "home/ventilation/renson"
    assert config["controls_enabled"] is True
    assert config["expose_installer_settings"] is False
    assert config["mqtt_discovery_enabled"] is False


def test_tls_defaults_from_the_port(monkeypatch):
    base_env(monkeypatch)
    assert load_config()["mqtt_tls"] is False

    monkeypatch.setenv("MQTT_PORT", "8883")
    assert load_config()["mqtt_tls"] is True

    # An explicit setting still wins, in either direction.
    monkeypatch.setenv("MQTT_TLS", "false")
    assert load_config()["mqtt_tls"] is False


def test_poll_interval_has_a_floor(monkeypatch):
    base_env(monkeypatch)
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "1")
    assert load_config()["poll_interval_seconds"] == MIN_POLL_INTERVAL_SECONDS


def test_non_integer_env_is_rejected(monkeypatch):
    base_env(monkeypatch)
    monkeypatch.setenv("MQTT_PORT", "not-a-port")
    with pytest.raises(ValueError, match="MQTT_PORT"):
        load_config()
