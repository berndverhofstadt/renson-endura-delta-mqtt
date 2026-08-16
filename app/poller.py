#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from app.commands import CommandHandler
from app.config import (
    BASE_FAILURE_THRESHOLD_FOR_BACKOFF,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    COOLDOWN_SECONDS,
    MAX_BACKOFF_INTERVAL_SECONDS,
    load_config,
)
from app.discovery import build_announcer
from app.fire import FireMonitor
from app.healthcheck import HealthMonitor
from app.mqtt_client import MqttBridge
from app.topics import command_wildcard, state_topic
from app.validation import coerce_reading

# The runtime depends on the field catalog/client in the sibling shared folder.
try:
    from shared.fields import ERROR_FIELD, ERROR_SLOTS, FIELDS
    from shared.renson_client import RensonClient
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    try:
        from shared.fields import ERROR_FIELD, ERROR_SLOTS, FIELDS
        from shared.renson_client import RensonClient
    except ImportError:
        raise SystemExit("Shared catalog/client files are required in the sibling 'shared' directory.")


def publish_status_quietly(bridge, topic, value, logger):
    """Publish a status topic without letting an MQTT outage kill the poll loop.

    The failure path runs precisely when the broker may be unreachable, so a
    raising publish there would escape the except block and end the process.
    """
    try:
        bridge.publish(topic, value, retain=True)
    except Exception as exc:
        logger.warning("status_publish_failed topic=%s err=%s", topic, exc)


def publish_readings(bridge, base_topic, readings, logger):
    """Publish every catalogued field the device actually reported.

    Fields absent from the response belong to hardware options this unit does
    not have, so they are skipped rather than published as empty.
    """
    published = 0
    for field in FIELDS:
        key = (field.name, field.index)
        if key not in readings:
            continue

        payload = coerce_reading(field, readings[key])
        if payload is None:
            logger.debug("reading_skipped name=%s raw=%s", field.name, readings[key])
            continue

        bridge.publish(state_topic(base_topic, field), payload, retain=True)
        published += 1
    return published


def publish_errors(bridge, base_topic, readings, logger):
    """Publish the device error log as a JSON array plus a simple active flag.

    Entries look like "C 16/8/2026 13:16 36: EtaFanTachoError"; 'C' marks the
    critical ones, where the unit stops working and needs a power cycle or a
    TouchDisplay > Error Log > Clear to recover.
    """
    errors = []
    for slot in range(ERROR_SLOTS):
        value = readings.get((ERROR_FIELD, (0, 0, slot)))
        if value not in (None, ""):
            errors.append(str(value).strip())

    bridge.publish(f"{base_topic}/diagnostics/errors", json.dumps(errors), retain=True)
    bridge.publish(f"{base_topic}/diagnostics/error_active",
                   "ON" if errors else "OFF", retain=True)
    if errors:
        logger.warning("device_errors_present errors=%s", errors)


def fan_running(readings, name):
    raw = readings.get((name, (0, 0, 0)))
    if raw is None:
        return None
    return str(raw).strip() not in ("0", "")


def main():
    config = load_config()
    logging.basicConfig(level=getattr(logging, config["log_level"], logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("renson_bridge")

    poll_interval = config["poll_interval_seconds"]
    base_topic = config["mqtt_base_topic"].rstrip("/")
    status_topic = f"{base_topic}/status"

    client = RensonClient(
        config["renson_host"],
        port=config["renson_port"],
        timeout=config["renson_timeout_seconds"],
    )
    bridge = MqttBridge(
        config["mqtt_host"],
        config["mqtt_port"],
        config["mqtt_username"],
        config["mqtt_password"],
        status_topic,
        debug_mode=config["debug_mode"],
        mqtt_tls=config["mqtt_tls"],
    )
    commands = CommandHandler(
        client,
        base_topic,
        expose_installer=config["expose_installer_settings"],
        enabled=config["controls_enabled"],
    )
    fire = FireMonitor(
        base_topic,
        config["fire_alarm_topic"],
        config["fire_alarm_payload_on"].split(","),
    )
    health_monitor = HealthMonitor(poll_interval)
    health_server = health_monitor.start_http_server("0.0.0.0", config["healthcheck_port"])

    try:
        bridge.connect()
    except Exception as exc:
        logger.exception("mqtt_connect_failed err=%s", exc)
        raise

    if config["controls_enabled"]:
        bridge.subscribe(command_wildcard(base_topic))
        logger.info("controls_enabled=True installer_settings=%s command_slugs=%s",
                    config["expose_installer_settings"], ",".join(commands.slugs))
    else:
        # Do not even subscribe: read-only should be read-only at the wire level,
        # not a handler that quietly discards commands.
        logger.info("controls_enabled=False - read-only, no command topics subscribed")
    if fire.enabled:
        bridge.subscribe(fire.alarm_topic)
        logger.info("fire_monitor_enabled topic=%s (monitoring only - the stop itself "
                    "must be a dry contact on the unit's input)", fire.alarm_topic)

    # Auto-discovery is best effort: never let it stop values from flowing.
    announcer = build_announcer(bridge, config, base_topic, status_topic)
    announced_generation = 0

    consecutive_failures = 0
    try:
        while True:
            cycle_started = time.monotonic()
            try:
                # Apply queued commands before reading, so this cycle publishes
                # the state they produced instead of a stale snapshot.
                for topic, payload in bridge.drain():
                    if fire.handle(topic, payload):
                        continue
                    try:
                        commands.handle(topic, payload)
                    except Exception as exc:
                        logger.warning("command_failed topic=%s payload=%s err=%s",
                                       topic, payload, exc)

                readings = client.read_all()

                # Announce after a read so the payloads carry the unit's real
                # model and firmware, but before the state so subscribers
                # already have the entity definitions. Re-announced on every
                # (re)connect: brokers without retained-message persistence lose
                # the configs when they restart.
                if announcer is not None and bridge.connect_count != announced_generation:
                    announced_generation = bridge.connect_count
                    try:
                        announcer.announce(readings)
                        logger.info("discovery_announced prefix=%s device_id=%s",
                                    config["mqtt_discovery_prefix"],
                                    config["mqtt_discovery_device_id"])
                    except Exception as exc:
                        logger.warning("discovery_announce_failed err=%s", exc)

                published = publish_readings(bridge, base_topic, readings, logger)
                publish_errors(bridge, base_topic, readings, logger)
                fire.publish(bridge,
                             fan_running(readings, "SUP fan active"),
                             fan_running(readings, "ETA fan active"))

                last_success = datetime.now(timezone.utc).isoformat()
                health_monitor.record_success()
                bridge.publish(f"{base_topic}/status/last_success", last_success, retain=True)
                bridge.publish(f"{base_topic}/status/consecutive_failures", 0, retain=True)
                bridge.publish(status_topic, "online", retain=True)
                consecutive_failures = 0
                logger.info("cycle_success fields_reported=%s published=%s last_success=%s",
                            len(readings), published, last_success)

            except Exception as exc:
                consecutive_failures += 1
                logger.warning("cycle_failed consecutive_failures=%s err=%s", consecutive_failures, exc)
                publish_status_quietly(bridge, f"{base_topic}/status/consecutive_failures",
                                       consecutive_failures, logger)
                publish_status_quietly(bridge, status_topic, "offline", logger)

                if consecutive_failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
                    logger.warning("circuit_breaker_triggered cooldown_seconds=%s", COOLDOWN_SECONDS)
                    time.sleep(COOLDOWN_SECONDS)
                    consecutive_failures = 0
                    publish_status_quietly(bridge, f"{base_topic}/status/consecutive_failures", 0, logger)
                    logger.warning("circuit_breaker_reset")

            elapsed = time.monotonic() - cycle_started
            if consecutive_failures > 0:
                if consecutive_failures >= BASE_FAILURE_THRESHOLD_FOR_BACKOFF:
                    sleep_for = min(
                        poll_interval * (2 ** (consecutive_failures - BASE_FAILURE_THRESHOLD_FOR_BACKOFF)),
                        MAX_BACKOFF_INTERVAL_SECONDS,
                    )
                else:
                    sleep_for = poll_interval
            else:
                sleep_for = max(0.0, poll_interval - elapsed)

            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        bridge.close()
        health_server.shutdown()
        health_server.server_close()


if __name__ == "__main__":
    main()
