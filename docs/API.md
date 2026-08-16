# The Renson Endura Delta local JSON API

Renson publishes no documentation for this API. Everything here was established
by probing a physical unit:

| | |
|---|---|
| Device type | `ED 450 T4 L SHT IAQ CO2 W02` |
| Firmware | `Endura Delta 0.0.69` |
| Hardware | `7` |

Other Endura Delta variants report a subset — a unit without the IAQ/CO2/RH
sensor option simply omits those fields. Run `tools/dump_fields.py` against your
own unit to see what it exposes.

## Endpoints

Plain HTTP on port 80. **No authentication of any kind** — anything that can
reach the unit can reconfigure it. Keep it on a trusted VLAN.

### Read everything

```
GET /JSON/ModifiedItems?wsn=150324488709
```

```json
{"ModifiedItems":[
  {"Name":"CO2","Index":[0,0,0],"Value":"554"},
  {"Name":"Manual level","Index":[0,0,0],"Value":"Off"}
]}
```

Returns all 191 fields in roughly 12 KB. Despite the name it is **not** a delta
feed: the full set comes back on every call, for any `wsn` value, and repeated
calls with the same `wsn` return the same thing. There is no session or change
tracking to manage — just poll it. Omitting `wsn` gives 404.

### Read one field

```
GET /JSON/Vars/<Field%20Name>?index0=0&index1=0&index2=0
-> {"Value":"554"}
```

### Write one field

```
POST /JSON/Vars/<Field%20Name>?index0=0&index1=0&index2=0
Content-Type: application/json
{"Value":"Level3"}

-> 200 {"Value":"Level3"}     accepted
-> 400                        field is read-only
```

Notes that matter:

- The three `index*` parameters are **mandatory**. Without them you get 404,
  even for scalar fields. Most fields use `0,0,0`; the arrays (`Error list`,
  `Week program *`) use the other positions.
- Field names contain spaces and must be percent-encoded in the path.
- Every value is a **string**, including numerics (`"315.000000"`, `"1"`).
- Some numeric fields return the literal `"nan"` while the fans ramp between
  setpoints. Parse defensively.

## Silent coercion

The enum fields answer **200 for any payload** and quietly substitute a default
instead of erroring. Probing `Manual level`:

| Sent | Response |
|---|---|
| `Level0` | `200 {"Value":"Off"}` |
| `BOGUS` | `200 {"Value":"Off"}` |
| `Auto` | `200 {"Value":"Off"}` |
| `Stop` | `200 {"Value":"Off"}` |

A rejected write is indistinguishable from an accepted one, so validate enums
client-side and compare the echoed value against what you sent. This bridge does
both in `app/validation.py` and `app/commands.py`.

## Writability

Established by POSTing each field's own current value back — 200 means writable,
400 means read-only. On the reference unit, **40 of 191 fields accept writes**.
See `shared/fields.py` for the authoritative per-field table.

Read-only and worth knowing about:

- All sensors: `T11`, `T21`, `T22`, `T12`, `RH11`, `RH12`, `CO2`, `IAQ`
- All measured/current airflow, fan speeds, fan voltages, `SUP/ETA fan active`
- `Input 1/2/3 value` and `Output 1/2/3 value` — these mirror the **physical**
  contacts and cannot be driven over the API. This is why a fire-safety stop
  needs real wiring; see [FIRE_SAFETY.md](FIRE_SAFETY.md).
- `Filter used time`, `Bypass level`, `Frost protection active`, `Preheater power`
- `Error list`, `System startup` — so errors cannot be cleared over the network

## Sensor naming

The temperature/humidity fields are named by air-path position, not by meaning.
The mapping below is **inferred**, not documented, from a summer reading with the
bypass fully open (100 %), where the exchanger is bypassed so extract ≈ exhaust
and outdoor ≈ supply:

| Field | Meaning | Reference reading |
|---|---|---|
| `T11` / `RH11` | Extract air from the house — **indoor** | 25.2 °C / 57.1 % |
| `T21` | Outdoor air intake — **outdoor** | 24.4 °C |
| `T22` | Supply air into the house | 25.4 °C |
| `T12` / `RH12` | Exhaust air to outside | 25.0 °C / 57.9 % |
| `T21bis` | Second outdoor sensor | −63.09 — absent on this unit |

Confirm on your own unit in winter, when the four values diverge properly.
`T21bis` reading −63.09 is how an unpopulated sensor presents; the range check
in `app/validation.py` drops readings like that rather than publishing them.

## Filter reset

`Filter used time` counts up and is read-only; `Filter remaining time` counts
down and is writable. Writing `Filter remaining time` = `Filter preset time`
resets the counter and zeroes `Filter used time` as a side effect. Verified:

```
before   used=93   remaining=87   preset=180
POST Filter remaining time = 180
after    used=0    remaining=180
```

That is the whole filter reset. Note it is not symmetric — writing a smaller
value back does not restore `Filter used time`, which stays at 0.

## Ventilation levels

`Manual level` accepts `Off`, `Level1`…`Level4`, `Breeze`. **`Off` means "no
manual override", i.e. back to automatic — it does not turn the fans off.**

`Current ventilation level` is a composite string like `Auto Level3` or
`Manual Level2`.

`Ventilation timer` is a timed boost formatted `<minutes> min <Level>`, e.g.
`30 min Level3`. `0 min Level3` means no timer is running.

## Input and output contacts

From the installation manual (p. 47). `Input N function` is writable;
`Input N value` is not.

| Code | `Input 1/2 function` |
|---|---|
| 0 | Turn off supply and discharge (**fire safety**) |
| 1 | Turn off discharge |
| 2 | Turn off supply (unit runs as a C system) |
| 3 | Start Fireplace function |
| 4 | Reset filter |

| Code | `Output 1/2 function` |
|---|---|
| 0 | General error message |
| 1 | Filter message |

Input 3 and Output 3 are the analogue 0–10 V contacts; code 0 means ignored.

## Errors

`Error list` is a five-slot array (`index2` = 0…4), newest first, each entry
formatted `<C|W> <d/m/Y H:MM> <code>: <Name>`:

```
C 16/8/2026 13:16 36: EtaFanTachoError
```

`C` marks critical errors, where the unit stops working. The array is read-only,
so **errors cannot be acknowledged over the API** — clearing needs
`TouchDisplay → Error Log → Clear` (which clears the list and restarts the unit)
or a 30-second power cycle.

While an error is active, any output contact set to function 0 goes high.

## Do not write these

⚠️ `Total nominal airflow` and `Level1..4 airflow percentage` are writable, and
setting the nominal airflow to 0 really does spin both fans down. **Do not use
this to stop ventilation.** The firmware then reads 0 rpm as fan failure and
latches:

```
C ... 35: SupFanTachoError    Critical - the unit has stopped working
C ... 36: EtaFanTachoError    Critical - the unit has stopped working
```

Both fans stay off. Restoring the airflow value does not help; neither does
forcing a level, re-triggering the value, or toggling manual mode — all verified.
Because `Error list` and `System startup` are read-only there is **no network
path to recovery**: someone has to physically power-cycle the unit or clear the
log on the TouchDisplay.

This bridge refuses these writes unconditionally in
`shared/renson_client.py`, regardless of configuration.

## No history

The unit keeps no queryable statistics. `SD card mounted` reports `1` and the
device does log internally, but nothing is exposed over HTTP — a dozen plausible
paths (`/JSON/Loggings`, `/JSON/Log`, `/JSON/Data`, `/JSON/Files`, …) all 404.
Use your home-automation platform's own persistence as the historian.
