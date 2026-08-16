# Stopping ventilation on a fire alarm

**Short version: this cannot be done over the network, and attempting it will
disable your unit until someone physically resets it.** Use the unit's input
contact.

## Why not over the API

The Endura Delta has a proper fire-safety function: an input contact configured
as `Input N function = 0` — *"turn off supply and discharge (fire safety)"* —
which stops both fans in firmware.

That function is triggered by the **physical** contact only.
`Input 1/2/3 value` are read-only: POSTing to them returns HTTP 400 and the fans
keep running. There is no other field that stops the unit.

The one field that *does* stop the fans is `Total nominal airflow`. Writing 0
ramps them down over about 8 seconds — and then the firmware reads 0 rpm as
fan failure and latches two critical errors:

```
C 16/8/2026 13:16 35: SupFanTachoError
C 16/8/2026 13:16 36: EtaFanTachoError
```

Per the manual both mean *"critical warning — the unit has stopped working"*.
Verified consequences:

- Restoring `Total nominal airflow` to its original value does **not** restart
  the fans.
- Neither does forcing `Manual level` to Level2/Level3, re-triggering the
  airflow value (419 → 420), or toggling manual mode off and on.
- `Error list` and `System startup` are read-only, so nothing clears the fault
  over HTTP.
- Recovery requires `TouchDisplay → Error Log → Clear` or a 30-second mains
  power cycle.

A fire alarm that leaves ventilation dead until someone walks to the machine is
worse than the problem it solves. `shared/renson_client.py` therefore refuses
these writes unconditionally, and this bridge never stops the fans.

## The supported approach

Wire a volt-free (dry) contact to the unit's 24 V DC input on the main board and
set that input's function to 0.

1. **Set the function.** In the app or on the TouchDisplay:
   *Settings → input and output → Input 1 → position 0*. Over the API, with
   `EXPOSE_INSTALLER_SETTINGS=true`:
   ```
   mosquitto_pub -t home/ventilation/renson/set/input1_function -m 0
   ```
   Many units already ship with `Input 1 function = 0`. Check
   `home/ventilation/renson/io/input1_function`.

2. **Wire the contact.** The 24 V DC input is item 14 on the main board (see
   manual §7.1.2, p. 36). Contact closed = function active = fans stopped.

3. **Drive it from your alarm.** In order of preference:

   - **Directly from the fire panel**, if it has a spare volt-free relay output.
     Fewest moving parts: panel → contact → firmware. No network, no broker, no
     container in the safety path.
   - **A relay module at the unit** (e.g. a Shelly in dry-contact mode)
     subscribed to your fire-alarm MQTT topic. Necessary when the panel is not
     physically near the ventilation unit. This does put wifi and the broker in
     the chain — a real trade-off, but still firmware-supported and, unlike the
     software route, it fails safe: if the relay never closes the unit simply
     keeps ventilating.

A **latching** alarm signal suits this well. Hold the contact closed for as long
as the alarm is active and the unit stays stopped; release it and the unit
resumes on its own, with no error to clear and no API involvement.

> The manual (p. 47) notes that driving the fans through the I/O contacts on your
> own logic is at your own risk, and that under NBN D50-001 (Belgium) the unit
> may never be switched off permanently. Input position 0 is the manufacturer's
> own fire-safety function, so this is what it is for — but it is worth knowing
> the rule exists.

## What this bridge does

Monitoring and verification, never actuation. Set `FIRE_ALARM_TOPIC` to your
alarm topic and the bridge will:

- mirror the alarm state to `<base>/fire/alarm`
- publish `<base>/fire/stop_confirmed` = `ON` once **both** `SUP fan active` and
  `ETA fan active` read 0 while the alarm is active
- log at ERROR level when an alarm is active but the fans are still turning,
  which means the contact did not do its job

That last point is the practical benefit of the hardware route: you get a stop
you can *observe* rather than one you have to trust.

```
FIRE_ALARM_TOPIC=home/fire/alarm
FIRE_ALARM_PAYLOAD_ON=1,on,true,open,alarm,fire
```

An openHAB rule can then alert on
`RensonFireAlarm == OPEN && RensonFireStopConfirmed == CLOSED` — the alarm fired
but the ventilation is still running.
