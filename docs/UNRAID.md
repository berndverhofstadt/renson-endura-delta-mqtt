# Running on Unraid

Unraid has no equivalent of `--env-file`, so every setting is a **Variable**
config entry in the container template. That is the intended way to configure
this bridge on Unraid.

The container is **stateless** — no volumes, no appdata share, nothing to back
up. Delete and recreate it freely; all state lives on the unit and the broker.

## Option A: install the template file

Copy [`unraid/renson-endura-delta-mqtt.xml`](../unraid/renson-endura-delta-mqtt.xml)
to your Unraid server at:

```
/boot/config/plugins/dockerMan/templates-user/my-renson-bridge.xml
```

From a terminal on the server:

```bash
cd /boot/config/plugins/dockerMan/templates-user/
wget -O my-renson-bridge.xml \
  https://raw.githubusercontent.com/berndverhofstadt/renson-endura-delta-mqtt/main/unraid/renson-endura-delta-mqtt.xml
```

Then **Docker → Add Container**, and pick `renson-bridge` from the *Template*
dropdown at the top. Every variable is pre-populated with its default and its
description; fill in the two required ones and hit Apply.

## Option B: add the container by hand

**Docker → Add Container**, then:

| Field | Value |
|---|---|
| Name | `renson-bridge` |
| Repository | `ghcr.io/berndverhofstadt/renson-endura-delta-mqtt:main` |
| Network Type | `Bridge` |
| Extra Parameters | `--restart=unless-stopped` |

Then **Add another Path, Port, Variable, Label or Device** once per setting
below, choosing **Config Type: Variable** each time. *Key* is the variable name,
*Value* is your setting.

Required:

| Key | Value |
|---|---|
| `RENSON_HOST` | your unit's IP, e.g. `192.168.1.60` |
| `MQTT_HOST` | your broker's hostname or IP |

Usually wanted:

| Key | Example | Notes |
|---|---|---|
| `MQTT_PORT` | `8883` | TLS turns on automatically for 8883/8884/443 |
| `MQTT_USERNAME` | `renson` | omit for an anonymous broker |
| `MQTT_PASSWORD` | *your password* | see the `&` warning below |
| `MQTT_BASE_TOPIC` | `home/ventilation/renson` | |
| `MQTT_DISCOVERY_ENABLED` | `true` | openHAB and Home Assistant both consume these |
| `CONTROLS_ENABLED` | `true` | `false` for a read-only bridge |
| `POLL_INTERVAL_SECONDS` | `15` | minimum 5 |
| `TZ` | `Europe/Brussels` | log timestamps only |

The full list is in [`.env.example`](../.env.example); every variable there works
identically here.

Optionally add **Config Type: Port**, container port `8080`, host port `8081`, to
reach `/health` from elsewhere. The container's own healthcheck works without
this, so Unraid will show the health status either way.

## Gotchas

**`&` in a password breaks hand-edited XML.** If you type the password into the
Unraid *UI*, Unraid escapes it for you and all is well. But if you edit a
template XML by hand, `&` must be written `&amp;`, along with `<` as `&lt;` and
`>` as `&gt;`. A raw `&` makes the template unparseable and Unraid will silently
fail to load it. This is why the shipped template leaves the password empty.

**Verify the broker actually accepts the credentials.** A wrong username or
password shows up as `rc=5 (Connection Refused: not authorised.)` in the
container log, and the container will restart in a loop. Check
**Docker → renson-bridge → Logs**.

**The consumer needs broker access too.** Your openHAB or Home Assistant MQTT
user needs *read* on the state tree, and on the discovery tree if you use
auto-discovery. Forgetting this is the classic failure: the bridge log looks
perfectly healthy while nothing appears in openHAB. See
[`mosquitto/acl.example`](../mosquitto/acl.example).

**Pin a version for production.** `:main` moves with every push to the default
branch. Once a tagged release exists, prefer e.g.
`ghcr.io/berndverhofstadt/renson-endura-delta-mqtt:0.1.0` so an Unraid auto-update
cannot surprise you.

**Unraid's update check** works normally against GHCR: the *Docker* tab will show
"update ready" when a new image is pushed for your tag.

## Verifying it works

Container log after a successful start:

```
INFO controls_enabled=True installer_settings=False command_slugs=...
INFO discovery_announced prefix=homeassistant device_id=renson_endura_delta
INFO cycle_success fields_reported=191 published=89 last_success=...
```

`fields_reported` is what the unit returned; `published` is how many passed
validation and reached MQTT. A unit without the CO2/IAQ sensor option will report
fewer — that is expected, not an error.
