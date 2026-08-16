# renson-endura-delta-mqtt

MQTT bridge for the **Renson Endura Delta** ventilation unit, for openHAB and
Home Assistant. Reads every value the unit exposes, publishes it to MQTT, and
accepts a safe set of controls back — including a **filter-reset button**, so you
no longer need the Renson app for that.

Runs as a container on your own network. Talks only to the unit's local HTTP API:
no cloud, no Renson account, no internet access required.

Renson documents none of this. The API reference in [docs/API.md](docs/API.md)
was reverse-engineered from a live unit and is probably the most complete public
description of it — including the parts that will break your unit if you write
to them.

> **Status:** working against the reference unit below, with readings confirmed
> arriving in openHAB via MQTT auto-discovery. Controls are implemented and
> unit-tested, and the command path has been exercised against a live unit.

| Reference unit | |
|---|---|
| Device type | `ED 450 T4 L SHT IAQ CO2 W02` |
| Firmware | `Endura Delta 0.0.69` |
| Hardware | `7` |

Other variants report a subset of the fields; the bridge publishes whatever your
unit actually returns and skips the rest, so it should work across the range.

## What you get

**Sensors** — CO2, IAQ, indoor/outdoor/supply/exhaust temperature, indoor and
exhaust humidity, bypass position, frost protection, preheater power, target vs.
current vs. measured airflow per side, fan speeds and voltages, unbalance,
pollution alerts split per CO2/IAQ/RH, breeze state, current/manual/program/
pollution levels, filter days used and remaining, the device error log.

**Controls** — ventilation level, timed boost, CO2 threshold and hysteresis,
day/night times and their levels, breeze settings, bypass activation temperature,
filter preset, and a filter-reset button.

**Diagnostics** — the unit's own error list on
`<base>/diagnostics/errors`, plus bridge health on `<base>/status` and an HTTP
`/health` endpoint for Docker.

There is no history: the unit stores no queryable statistics, so use openHAB
persistence (or HA recorder) as the historian.

## Quick start

```bash
git clone <this repo> && cd renson-endura-delta-mqtt
cp .env.example .env
$EDITOR .env          # RENSON_HOST and MQTT_HOST are required
docker compose up -d
```

Check what your unit exposes before wiring anything up:

```bash
python -m tools.dump_fields --host 192.168.1.60 --show-published
```

### openHAB

Easiest route is auto-discovery: set `MQTT_DISCOVERY_ENABLED=true`, make sure
your MQTT broker Thing is online, and a **Renson Endura Delta** Thing appears in
the Inbox with every channel already defined.

Your openHAB MQTT user needs read access to both trees, which is easy to miss -
the bridge looks perfectly healthy while openHAB sees nothing:

```
user openhab
topic read home/ventilation/renson/#
topic read homeassistant/#
```

Alternatively, generate text configuration (don't do both, or you get duplicate
channels for the same topics):

```bash
python -m tools.generate_openhab_config --broker <your-mqtt-broker-thing-uid>
cp openhab/things/renson.things     $OPENHAB_CONF/things/
cp openhab/items/renson.items       $OPENHAB_CONF/items/
cp openhab/sitemaps/renson.sitemap  $OPENHAB_CONF/sitemaps/
```

## Topics

Base topic defaults to `home/ventilation/renson`.

| Topic | Meaning |
|---|---|
| `<base>/<category>/<slug>` | state, retained |
| `<base>/set/<slug>` | command |
| `<base>/set/filter_reset` | filter-reset button, any of `PRESS`/`ON`/`1` |
| `<base>/status` | `online` / `offline` (LWT) |
| `<base>/status/last_success` | ISO-8601 timestamp of the last good poll |
| `<base>/status/consecutive_failures` | backoff counter |
| `<base>/diagnostics/errors` | JSON array of active device errors |
| `<base>/diagnostics/error_active` | `ON` when the unit reports any error |
| `<base>/fire/alarm` | mirrored fire-alarm state |
| `<base>/fire/stop_confirmed` | `ON` once both fans have actually stopped |

Categories are `climate`, `ventilation`, `airquality`, `schedule`, `breeze`,
`exchanger`, `filter`, `fireplace`, `airflow`, `io`, `device`, `diagnostics`.

So the whole tree is one ACL line — see [mosquitto/acl.example](mosquitto/acl.example):

```
user renson
topic readwrite home/ventilation/renson/#
```

Examples:

```bash
mosquitto_pub -t home/ventilation/renson/set/manual_level     -m Level3
mosquitto_pub -t home/ventilation/renson/set/ventilation_timer -m "30 min Level3"
mosquitto_pub -t home/ventilation/renson/set/co2_threshold    -m 800
mosquitto_pub -t home/ventilation/renson/set/filter_reset     -m PRESS
```

Note `manual_level` `Off` means *no manual override* — back to automatic. It does
not turn the fans off.

## Configuration

Everything is environment variables; see [.env.example](.env.example).
`RENSON_HOST` and `MQTT_HOST` are required, the rest have defaults.

| Variable | Default | Notes |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | `15` | Floor of 5 |
| `MQTT_BASE_TOPIC` | `home/ventilation/renson` | |
| `CONTROLS_ENABLED` | `true` | `false` for a read-only bridge |
| `EXPOSE_INSTALLER_SETTINGS` | `false` | See below |
| `MQTT_DISCOVERY_ENABLED` | `false` | Home Assistant discovery, consumed by openHAB |
| `FIRE_ALARM_TOPIC` | *(unset)* | Monitoring only, see below |

### Installer settings

By default only day-to-day controls are writable. `EXPOSE_INSTALLER_SETTINGS=true`
additionally exposes commissioning values — flow offsets, input/output contact
functions, preheater, target plate temperature, region. Wrong values here will
mis-balance the unit, so leave it off unless you know why you want it.

The fields that break the unit stay blocked either way (next section).

## Safety: two things this bridge refuses to do

**1. It will not write `Total nominal airflow` or the per-level airflow
percentages.** These are writable on the device and setting nominal airflow to 0
does stop both fans — and then the firmware reads 0 rpm as fan failure, latches
critical errors 35 and 36, and refuses to restart. Restoring the value does not
help, and because `Error list` and `System startup` are read-only there is no
network path to recovery: someone has to power-cycle the unit or clear the log on
the TouchDisplay. Verified the hard way. See
[docs/API.md](docs/API.md#do-not-write-these).

**2. It will not stop your ventilation on a fire alarm.** It cannot be done
safely over the network — `Input N value` is read-only, so the unit's own
fire-safety function is unreachable from the API, and the workaround above is
what bricks it. The supported stop is a dry contact on the 24 V DC input with
`Input N function = 0`.

What the bridge does instead is *verify* that stop: set `FIRE_ALARM_TOPIC` and it
mirrors the alarm, publishes `fire/stop_confirmed` once both fans actually read
stopped, and logs loudly if an alarm is active while the fans keep turning. Full
wiring guidance in [docs/FIRE_SAFETY.md](docs/FIRE_SAFETY.md).

## Security

The unit's API has **no authentication**. Anything that can reach port 80 can
reconfigure your ventilation, including the commissioning values. Put it on a
trusted VLAN and do not expose it to the internet.

## Layout

```
app/config.py       environment parsing
app/poller.py       main loop: read, publish, apply queued commands
app/mqtt_client.py  publish + queue inbound commands off the network thread
app/commands.py     command dispatch, incl. the virtual filter-reset button
app/validation.py   reading coercion and pre-flight write validation
app/fire.py         fire-alarm mirroring and stop verification
app/discovery.py    Home Assistant discovery (opt-in via MQTT_DISCOVERY_ENABLED)
app/topics.py       topic layout, shared with the generator
app/healthcheck.py  /health for the container healthcheck
shared/fields.py    the field catalog: names, units, writability, safety flags
shared/renson_client.py  HTTP client, with the dangerous writes refused
tools/dump_fields.py            inspect a live unit, check catalog coverage
tools/generate_openhab_config.py  emit things/items/sitemap
```

`shared/fields.py` is the interesting file: it is the field-by-field record of
what the device exposes, what accepts writes, and what is unsafe to touch.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
PYTHONPATH=. .venv/bin/python -m pytest tests -q
```

`DEBUG_MODE=true` logs the publishes it would make instead of sending them.

## Contributing

Readings from other Endura Delta variants are especially useful — run
`tools/dump_fields.py` and open an issue with the "reported but not in catalog"
section. With `CONTROLS_ENABLED=false` only `sensor` and `binary_sensor` are announced,
which is the best-supported subset in openHAB. Flipping controls on or off
re-announces the right entity types and retracts the stale ones.

Two things still want confirming:

- The temperature sensor mapping (`T11`/`T21`/`T22`/`T12`) is inferred from a
  summer reading with the bypass open, not documented. Winter data would settle it.
- `Fireplace remaining time` is writable even though the manual says the
  fireplace function can only be started by an external switch. Writing a
  non-zero value may start it. Untested, so it is not exposed as a control.

## Licence

MIT.
