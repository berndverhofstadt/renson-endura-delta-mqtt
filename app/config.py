import os
from pathlib import Path

MIN_POLL_INTERVAL_SECONDS = 5
BASE_FAILURE_THRESHOLD_FOR_BACKOFF = 3
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 10
MAX_BACKOFF_INTERVAL_SECONDS = 300
COOLDOWN_SECONDS = 900

TRUTHY = {"1", "true", "yes", "on"}
TLS_PORTS = (8883, 8884, 443)


def env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc


def env_str(name, default):
    value = os.getenv(name)
    return default if value is None or value == "" else value


def env_bool(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in TRUTHY


def _load_local_dotenv():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def load_config():
    _load_local_dotenv()

    host = os.getenv("RENSON_HOST")
    if not host:
        raise RuntimeError("RENSON_HOST must be set")

    mqtt_host = os.getenv("MQTT_HOST")
    if not mqtt_host:
        raise RuntimeError("MQTT_HOST must be set")

    poll_interval = max(MIN_POLL_INTERVAL_SECONDS, env_int("POLL_INTERVAL_SECONDS", 15))
    mqtt_port = env_int("MQTT_PORT", 1883)
    return {
        "renson_host": host,
        "renson_port": env_int("RENSON_PORT", 80),
        "renson_timeout_seconds": env_int("RENSON_TIMEOUT_SECONDS", 8),
        "poll_interval_seconds": poll_interval,
        "mqtt_host": mqtt_host,
        "mqtt_port": mqtt_port,
        "mqtt_username": os.getenv("MQTT_USERNAME"),
        "mqtt_password": os.getenv("MQTT_PASSWORD"),
        "mqtt_base_topic": env_str("MQTT_BASE_TOPIC", "home/ventilation/renson"),
        # Default from the port rather than to false: connecting to 8883 without
        # TLS fails in confusing ways, and silently sending credentials in the
        # clear would be worse.
        "mqtt_tls": env_bool("MQTT_TLS", mqtt_port in TLS_PORTS),
        # Home Assistant style auto-discovery. Scaffolded but off by default -
        # the openHAB files from tools/generate_openhab_config.py are the
        # supported route for now (see app/discovery.py).
        "mqtt_discovery_enabled": env_bool("MQTT_DISCOVERY_ENABLED", False),
        "mqtt_discovery_prefix": env_str("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        "mqtt_discovery_device_id": env_str("MQTT_DISCOVERY_DEVICE_ID", "renson_endura_delta"),
        "mqtt_discovery_device_name": env_str("MQTT_DISCOVERY_DEVICE_NAME", "Renson Endura Delta"),
        # Commissioning fields (airflow offsets, I/O functions, preheater,
        # region) stay hidden unless this is deliberately turned on.
        "expose_installer_settings": env_bool("EXPOSE_INSTALLER_SETTINGS", False),
        "controls_enabled": env_bool("CONTROLS_ENABLED", True),
        # Fire alarm monitoring. The bridge never stops the fans itself: the
        # only safe stop is the unit's own input contact. See docs/FIRE_SAFETY.md.
        "fire_alarm_topic": env_str("FIRE_ALARM_TOPIC", ""),
        "fire_alarm_payload_on": env_str("FIRE_ALARM_PAYLOAD_ON", "1,on,true,open,alarm,fire"),
        "log_level": env_str("LOG_LEVEL", "INFO").upper(),
        "healthcheck_port": env_int("HEALTHCHECK_PORT", 8080),
        "debug_mode": env_bool("DEBUG_MODE", False),
    }
