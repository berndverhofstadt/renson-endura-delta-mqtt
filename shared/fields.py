"""
Field catalog for the Renson Endura Delta local JSON API.

Source: probed live against a physical unit, since Renson publishes no API
documentation. Reference device:

    Device type       ED 450 T4 L SHT IAQ CO2 W02
    Firmware version  Endura Delta 0.0.69
    Hardware version  7

The unit exposes an unauthenticated HTTP JSON API on port 80:

    GET  /JSON/ModifiedItems?wsn=<any integer>
         -> {"ModifiedItems":[{"Name":..,"Index":[i0,i1,i2],"Value":".."}, ..]}
         Despite the name it always returns the *complete* set of fields for
         any wsn value - there is no delta or session tracking to manage.

    GET  /JSON/Vars/<Field%20Name>?index0=0&index1=0&index2=0
         -> {"Value":".."}

    POST /JSON/Vars/<Field%20Name>?index0=0&index1=0&index2=0
         body {"Value":".."} -> 200 with the accepted value, or 400 if the
         field is read-only.

The index0/index1/index2 query parameters are mandatory; omitting them
returns 404. All values are transported as strings, including numerics.

`writable` below was established empirically by POSTing each field's own
current value back and recording 200 (writable) vs 400 (read-only). 40 of
the 191 fields accepted writes on the reference unit.

`control` decides what this bridge is willing to write:

    None            read-only, or writable but never exposed as a control
    "operational"   safe day-to-day control, exposed by default
    "installer"     commissioning value, only when EXPOSE_INSTALLER=true
    "blocked"       writable but REFUSED unconditionally - see DANGEROUS below

Units without the IAQ/CO2/RH sensor option will not report every field here.
The poller publishes whatever the device actually returns and skips the rest,
so the same catalog works across Endura Delta variants.
"""

from dataclasses import dataclass
from typing import Optional

REFERENCE_MODEL = "ED 450 T4 L SHT IAQ CO2 W02"
REFERENCE_FIRMWARE = "Endura Delta 0.0.69"

# `Manual level` silently coerces any unrecognised payload to "Off" and still
# answers 200 - a typo would quietly drop the unit back to automatic mode
# instead of erroring. Every enum write is therefore validated locally first.
MANUAL_LEVELS = ["Off", "Level1", "Level2", "Level3", "Level4", "Breeze"]
PROGRAM_LEVELS = ["Level1", "Level2", "Level3", "Level4"]

# Writing 0 to `Total nominal airflow` really does spin both fans down, but the
# firmware then reads 0 rpm as fan failure and latches error 35
# (SupFanTachoError) and 36 (EtaFanTachoError). Both are "Critical warning -
# the unit has stopped working": the fans stay off, `Error list` and
# `System startup` are read-only so nothing clears them over the network, and
# recovery needs a physical power cycle or TouchDisplay > Error Log > Clear.
#
# Do not use these fields to stop ventilation. The supported stop is the
# hardware input contact with `Input N function` = 0 (fire safety), which the
# firmware handles without tripping the tacho check. See docs/FIRE_SAFETY.md.
DANGEROUS = {
    "Total nominal airflow",
    "Level1 airflow percentage",
    "Level2 airflow percentage",
    "Level3 airflow percentage",
    "Level4 airflow percentage",
}


# Renson names the sensors by air-path position and abbreviates the fan sides,
# which is unhelpful in a dashboard. `name` stays exactly as the device spells it
# because that is what the API needs; `label` is what humans see. Anything not
# listed here falls back to its device name.
LABELS = {
    "T11": "Indoor temperature",
    "RH11": "Indoor humidity",
    "T21": "Outdoor temperature",
    "T22": "Supply temperature",
    "T12": "Exhaust temperature",
    "RH12": "Exhaust humidity",
    "T21bis": "Outdoor temperature (secondary sensor)",
    "IAQ": "Indoor air quality",
    "Target SUP airflow": "Target supply airflow",
    "Target ETA airflow": "Target extract airflow",
    "Current SUP airflow": "Current supply airflow",
    "Current ETA airflow": "Current extract airflow",
    "Measured SUP airflow": "Measured supply airflow",
    "Measured ETA airflow": "Measured extract airflow",
    "SUP fan active": "Supply fan active",
    "ETA fan active": "Extract fan active",
    "SUP fan speed": "Supply fan speed",
    "ETA fan speed": "Extract fan speed",
    "SUP fan voltage": "Supply fan voltage",
    "ETA fan voltage": "Extract fan voltage",
    "SUP constant flow sensor value": "Supply constant-flow sensor",
    "ETA constant flow sensor value": "Extract constant-flow sensor",
    "SUP flow offset": "Supply flow offset",
    "ETA flow offset": "Extract flow offset",
    "Date and time": "Device date and time",
    "Region": "Region setting",
    "Unbalance": "Supply/extract unbalance",
}


@dataclass
class Field:
    name: str
    slug: str
    category: str
    unit: str = ""
    kind: str = "number"          # number | string | enum | bool | time
    writable: bool = False        # accepted a write on the reference firmware
    control: Optional[str] = None
    options: Optional[list] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    index: tuple = (0, 0, 0)
    note: str = ""
    label: Optional[str] = None

    def __post_init__(self):
        if self.label is None:
            self.label = LABELS.get(self.name, self.name)


FIELDS = [
    # -- device identity -----------------------------------------------------
    Field("Device type", "device_type", "device", kind="string"),
    Field("Firmware version", "firmware_version", "device", kind="string"),
    Field("Hardware version", "hardware_version", "device", kind="string"),
    Field("Device name", "device_name", "device", kind="string", writable=True),
    Field("MAC", "mac", "device", kind="string"),
    Field("Warranty number", "warranty_number", "device", kind="string"),
    Field("Region", "region", "device", kind="string", writable=True, control="installer"),
    Field("Registration complete", "registration_complete", "device", kind="bool"),
    Field("Date and time", "device_time", "device", kind="string", writable=True,
          note="Device-local format, e.g. '16 aug 2026 13:02'"),

    # -- climate sensors ----------------------------------------------------
    Field("T11", "indoor_temperature", "climate", unit="degC",
          note="Extract air from the house. Inferred: with the bypass fully open in "
               "summer T11 tracks T12 (exhaust) while T21 tracks T22 (supply)."),
    Field("RH11", "indoor_humidity", "climate", unit="%",
          note="Relative humidity of the extract air"),
    Field("T21", "outdoor_temperature", "climate", unit="degC",
          note="Outdoor air intake"),
    Field("T22", "supply_temperature", "climate", unit="degC",
          note="Air supplied into the house"),
    Field("T12", "exhaust_temperature", "climate", unit="degC",
          note="Air exhausted outside"),
    Field("RH12", "exhaust_humidity", "climate", unit="%"),
    Field("T21bis", "outdoor_temperature_secondary", "climate", unit="degC",
          note="Second outdoor sensor. Absent on the reference unit, which reports "
               "-63.09 - the range check in app/validation.py drops such readings."),
    Field("CO2", "co2", "climate", unit="ppm"),
    Field("IAQ", "iaq", "climate", note="Indoor air quality index (unitless)"),

    # -- ventilation state --------------------------------------------------
    Field("Current ventilation level", "current_level", "ventilation", kind="string",
          note="Effective level, e.g. 'Auto Level3' or 'Manual Level2'"),
    Field("Current program level", "program_level", "ventilation", kind="string"),
    Field("Current pollution level", "pollution_level", "ventilation", kind="string"),
    Field("Manual level", "manual_level", "ventilation", kind="enum", writable=True,
          control="operational", options=MANUAL_LEVELS,
          note="'Off' means no manual override (back to automatic), NOT fans off"),
    Field("Ventilation timer", "ventilation_timer", "ventilation", kind="string",
          writable=True, control="operational",
          note="Timed boost, format '<minutes> min <Level>', e.g. '30 min Level3'. "
               "'0 min Level3' means no timer running."),

    # -- air quality triggers ----------------------------------------------
    Field("CO2 threshold", "co2_threshold", "airquality", unit="ppm", writable=True,
          control="operational", minimum=400, maximum=2000),
    Field("CO2 hysteresis", "co2_hysteresis", "airquality", unit="ppm", writable=True,
          control="operational", minimum=0, maximum=500),
    Field("Trigger internal pollution alert on CO2", "trigger_on_co2", "airquality",
          kind="bool", writable=True, control="operational"),
    Field("Trigger internal pollution alert on IAQ", "trigger_on_iaq", "airquality",
          kind="bool", writable=True, control="operational"),
    Field("Trigger internal pollution alert on RH", "trigger_on_rh", "airquality",
          kind="bool", writable=True, control="operational"),
    Field("Internal CO2 pollution alert", "alert_co2", "airquality", kind="bool"),
    Field("Internal IAQ pollution alert", "alert_iaq", "airquality", kind="bool"),
    Field("Internal RH pollution alert", "alert_rh", "airquality", kind="bool"),
    Field("External pollution alert", "alert_external", "airquality", kind="bool"),
    Field("QualiSensor pollution alert", "qualisensor_alert", "airquality", kind="bool",
          writable=True),
    Field("QualiSensor error count", "qualisensor_errors", "airquality", writable=True),

    # -- day / night schedule ----------------------------------------------
    Field("Start daytime", "start_daytime", "schedule", kind="time", writable=True,
          control="operational", note="Format 'H:MM', e.g. '7:30'"),
    Field("Start night-time", "start_nighttime", "schedule", kind="time", writable=True,
          control="operational", note="Format 'H:MM', e.g. '20:00'"),
    Field("Day pollution-triggered ventilation level", "day_pollution_level", "schedule",
          kind="enum", writable=True, control="operational", options=PROGRAM_LEVELS),
    Field("Night pollution-triggered ventilation level", "night_pollution_level", "schedule",
          kind="enum", writable=True, control="operational", options=PROGRAM_LEVELS),

    # -- breeze -------------------------------------------------------------
    Field("Breeze enable", "breeze_enable", "breeze", kind="bool", writable=True,
          control="operational"),
    Field("Breeze level", "breeze_level", "breeze", kind="enum", writable=True,
          control="operational", options=PROGRAM_LEVELS),
    Field("Breeze activation temperature", "breeze_temperature", "breeze", unit="degC",
          writable=True, control="operational", minimum=15, maximum=30),
    Field("Breeze conditions met", "breeze_conditions_met", "breeze", kind="bool"),

    # -- heat exchanger -----------------------------------------------------
    Field("Bypass level", "bypass_level", "exchanger", unit="%",
          note="0 = closed (recover heat), 100 = fully open (bypass exchanger)"),
    Field("Bypass activation temperature", "bypass_temperature", "exchanger", unit="degC",
          writable=True, control="operational", minimum=15, maximum=30),
    Field("Frost protection active", "frost_protection", "exchanger", kind="bool"),
    Field("Preheater enabled", "preheater_enabled", "exchanger", kind="bool", writable=True,
          control="installer"),
    Field("Preheater power", "preheater_power", "exchanger", unit="%"),
    Field("Target plate temp", "target_plate_temperature", "exchanger", unit="degC",
          writable=True, control="installer"),

    # -- filter -------------------------------------------------------------
    Field("Filter remaining time", "filter_remaining", "filter", unit="d", writable=True,
          control="operational", minimum=0, maximum=400,
          note="Writing this to the value of 'Filter preset time' resets the filter "
               "counter and zeroes 'Filter used time'. This is the filter reset."),
    Field("Filter used time", "filter_used", "filter", unit="d"),
    Field("Filter preset time", "filter_preset", "filter", unit="d", writable=True,
          control="operational", minimum=30, maximum=400),

    # -- fireplace ----------------------------------------------------------
    Field("Fireplace remaining time", "fireplace_remaining", "fireplace", unit="min",
          writable=True,
          note="Writable, although the manual states the fireplace function can only be "
               "started by an external switch. Writing a non-zero value may start it - "
               "untested, so this bridge does not expose it as a control."),
    Field("Fireplace preset time", "fireplace_preset", "fireplace", unit="min", writable=True,
          control="operational", minimum=1, maximum=60),
    Field("Fireplace flow delta", "fireplace_flow_delta", "fireplace", unit="%", writable=True,
          control="installer"),

    # -- airflow / fans -----------------------------------------------------
    Field("Target SUP airflow", "target_supply_airflow", "airflow", unit="m3/h"),
    Field("Target ETA airflow", "target_extract_airflow", "airflow", unit="m3/h"),
    Field("Current SUP airflow", "current_supply_airflow", "airflow", unit="m3/h"),
    Field("Current ETA airflow", "current_extract_airflow", "airflow", unit="m3/h"),
    Field("Measured SUP airflow", "measured_supply_airflow", "airflow", unit="m3/h",
          note="Can return the literal string 'nan' while the fans are ramping, and "
               "holds a stale value while they are stopped. Trust 'SUP fan active' and "
               "'Current SUP airflow' over this one."),
    Field("Measured ETA airflow", "measured_extract_airflow", "airflow", unit="m3/h",
          note="Same caveats as the supply side"),
    Field("SUP fan active", "supply_fan_active", "airflow", kind="bool"),
    Field("ETA fan active", "extract_fan_active", "airflow", kind="bool"),
    Field("SUP fan speed", "supply_fan_speed", "airflow", unit="rpm"),
    Field("ETA fan speed", "extract_fan_speed", "airflow", unit="rpm"),
    Field("SUP fan voltage", "supply_fan_voltage", "airflow", unit="V"),
    Field("ETA fan voltage", "extract_fan_voltage", "airflow", unit="V"),
    Field("Unbalance", "unbalance", "airflow", unit="%"),
    Field("Total nominal airflow", "total_nominal_airflow", "airflow", unit="m3/h",
          writable=True, control="blocked",
          note="Commissioned airflow. Writing it is what trips errors 35/36 - see DANGEROUS."),
    Field("Level1 airflow percentage", "level1_percentage", "airflow", unit="%",
          writable=True, control="blocked"),
    Field("Level2 airflow percentage", "level2_percentage", "airflow", unit="%",
          writable=True, control="blocked"),
    Field("Level3 airflow percentage", "level3_percentage", "airflow", unit="%",
          writable=True, control="blocked"),
    Field("Level4 airflow percentage", "level4_percentage", "airflow", unit="%",
          writable=True, control="blocked"),
    Field("SUP flow offset", "supply_flow_offset", "airflow", writable=True, control="installer"),
    Field("ETA flow offset", "extract_flow_offset", "airflow", writable=True, control="installer"),
    Field("SUP constant flow sensor value", "supply_flow_sensor", "airflow"),
    Field("ETA constant flow sensor value", "extract_flow_sensor", "airflow"),

    # -- input / output contacts -------------------------------------------
    # `Input N value` is READ-ONLY: it mirrors the physical contact and cannot be
    # driven over the API, which is why a fire-safety stop needs real wiring.
    Field("Input 1 value", "input1_value", "io", kind="bool"),
    Field("Input 2 value", "input2_value", "io", kind="bool"),
    Field("Input 3 value", "input3_value", "io"),
    Field("Input 1 function", "input1_function", "io", writable=True, control="installer",
          note="0=off supply+discharge (fire safety), 1=off discharge, "
               "2=off supply (C-system), 3=start fireplace, 4=reset filter"),
    Field("Input 2 function", "input2_function", "io", writable=True, control="installer",
          note="Same codes as input 1"),
    Field("Input 3 function", "input3_function", "io", writable=True, control="installer",
          note="0 = analogue input ignored"),
    Field("Output 1 value", "output1_value", "io", kind="bool"),
    Field("Output 2 value", "output2_value", "io", kind="bool"),
    Field("Output 3 value", "output3_value", "io"),
    Field("Output 1 function", "output1_function", "io", writable=True, control="installer",
          note="0=general error message, 1=filter message"),
    Field("Output 2 function", "output2_function", "io", writable=True, control="installer",
          note="0=general error message, 1=filter message"),
    Field("Output 3 function", "output3_function", "io", writable=True, control="installer"),

    # -- diagnostics --------------------------------------------------------
    Field("SD card mounted", "sd_card_mounted", "diagnostics", kind="bool"),
    Field("System startup", "system_startup", "diagnostics", kind="bool"),
]

# `Error list` is a 5-slot array of the most recent errors, newest first, each
# formatted "<C|W> <d/m/Y H:MM> <code>: <Name>", e.g.
# "C 16/8/2026 13:16 36: EtaFanTachoError". Read-only.
ERROR_SLOTS = 5
ERROR_FIELD = "Error list"

BY_NAME = {field.name: field for field in FIELDS}
BY_SLUG = {field.slug: field for field in FIELDS}


def controllable(expose_installer=False):
    """Fields this bridge will accept writes for, given the installer setting."""
    allowed = {"operational"} | ({"installer"} if expose_installer else set())
    return [f for f in FIELDS if f.control in allowed and f.name not in DANGEROUS]
