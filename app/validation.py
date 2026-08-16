"""Value coercion for readings, and validation of writes before they leave.

Two device quirks drive this module:

  * Every value arrives as a string, and some numeric fields return the literal
    "nan" while the fans ramp between setpoints.
  * `Manual level` (and the other enums) answer 200 for *any* payload, silently
    coercing what they do not recognise to a default. A rejected write therefore
    looks identical to an accepted one, so enums must be checked here first.
"""

import re
from math import isfinite

# Plausibility windows, applied per unit. A reading outside its window is
# dropped rather than published: the reference unit has no second outdoor
# sensor and reports -63.09 for T21bis, which would otherwise look real.
RANGES = {
    "degC": (-45.0, 80.0),
    "%": (0.0, 100.0),
    "ppm": (0.0, 10000.0),
    "rpm": (0.0, 6000.0),
    "m3/h": (0.0, 1000.0),
    "V": (0.0, 24.0),
    "d": (0.0, 400.0),
    "min": (0.0, 1440.0),
}

BOOL_TRUE = {"1", "true", "on", "yes"}
BOOL_FALSE = {"0", "false", "off", "no"}

TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
# "0 min Level3", "30 min Level1"
TIMER_PATTERN = re.compile(r"^(\d{1,4})\s*min\s*(Level[1-4])$", re.IGNORECASE)


def slugify(name):
    value = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return re.sub(r"_+", "_", value).strip("_")


def coerce_reading(field, raw):
    """Turn a raw device string into an MQTT payload, or None to skip it."""
    if raw is None:
        return None

    text = str(raw).strip()
    if text == "":
        return None

    if field.kind in ("string", "time", "enum"):
        return text

    if field.kind == "bool":
        lowered = text.lower()
        if lowered in BOOL_TRUE:
            return "ON"
        if lowered in BOOL_FALSE:
            return "OFF"
        return None

    try:
        numeric = float(text)
    except ValueError:
        # Covers the literal "nan" the airflow fields emit while ramping.
        return None
    if not isfinite(numeric):
        return None

    low, high = RANGES.get(field.unit, (None, None))
    if low is not None and not (low <= numeric <= high):
        return None

    # Most numerics arrive as "315.000000"; publish them tidily without
    # inventing precision the device did not report.
    return str(int(numeric)) if numeric == int(numeric) else f"{numeric:.2f}"


class ValidationError(ValueError):
    pass


def validate_write(field, payload):
    """Return the exact string to send to the device, or raise ValidationError."""
    text = str(payload).strip()
    if text == "":
        raise ValidationError(f"{field.slug}: empty payload")

    if field.kind == "enum":
        # Case-insensitive match, but send the catalog's exact spelling: the
        # device would accept "level3" with a 200 and then ignore it.
        for option in field.options or []:
            if text.lower() == option.lower():
                return option
        raise ValidationError(
            f"{field.slug}: {text!r} is not one of {', '.join(field.options or [])}"
        )

    if field.kind == "bool":
        lowered = text.lower()
        if lowered in BOOL_TRUE:
            return "1"
        if lowered in BOOL_FALSE:
            return "0"
        raise ValidationError(f"{field.slug}: {text!r} is not a boolean")

    if field.kind == "time":
        if not TIME_PATTERN.match(text):
            raise ValidationError(f"{field.slug}: {text!r} is not a 'H:MM' time")
        return text

    if field.slug == "ventilation_timer":
        match = TIMER_PATTERN.match(text)
        if not match:
            raise ValidationError(
                f"{field.slug}: {text!r} must look like '30 min Level3'"
            )
        return f"{int(match.group(1))} min {match.group(2).capitalize()}"

    if field.kind == "string":
        return text

    try:
        numeric = float(text)
    except ValueError as exc:
        raise ValidationError(f"{field.slug}: {text!r} is not a number") from exc
    if not isfinite(numeric):
        raise ValidationError(f"{field.slug}: {text!r} is not finite")
    if field.minimum is not None and numeric < field.minimum:
        raise ValidationError(f"{field.slug}: {numeric} is below minimum {field.minimum}")
    if field.maximum is not None and numeric > field.maximum:
        raise ValidationError(f"{field.slug}: {numeric} is above maximum {field.maximum}")

    return str(int(numeric)) if numeric == int(numeric) else str(numeric)
