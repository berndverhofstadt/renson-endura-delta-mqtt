import pytest

from app.validation import ValidationError, coerce_reading, slugify, validate_write
from shared.fields import BY_SLUG


def field(slug):
    return BY_SLUG[slug]


def test_slugify_collapses_punctuation():
    assert slugify("Day pollution-triggered ventilation level") == "day_pollution_triggered_ventilation_level"


def test_numeric_reading_is_tidied_without_inventing_precision():
    assert coerce_reading(field("target_supply_airflow"), "315.000000") == "315"
    assert coerce_reading(field("indoor_temperature"), "25.201210") == "25.20"


def test_nan_airflow_is_skipped():
    # The measured airflow fields return the literal "nan" while the fans ramp.
    assert coerce_reading(field("measured_supply_airflow"), "nan") is None


def test_absent_sensor_out_of_range_is_skipped():
    # The reference unit has no second outdoor sensor and reports -63.09.
    assert coerce_reading(field("outdoor_temperature_secondary"), "-63.090935") is None
    assert coerce_reading(field("outdoor_temperature"), "24.405405") == "24.41"


def test_bool_reading_maps_to_on_off():
    assert coerce_reading(field("frost_protection"), "0") == "OFF"
    assert coerce_reading(field("supply_fan_active"), "1") == "ON"


def test_empty_reading_is_skipped():
    assert coerce_reading(field("current_level"), "") is None
    assert coerce_reading(field("current_level"), None) is None


def test_enum_write_is_normalised_to_catalog_spelling():
    # The device answers 200 for "level3" and then ignores it, so the exact
    # spelling has to leave this process.
    assert validate_write(field("manual_level"), "level3") == "Level3"
    assert validate_write(field("manual_level"), "Breeze") == "Breeze"


def test_enum_write_rejects_unknown_value():
    with pytest.raises(ValidationError):
        validate_write(field("manual_level"), "Level9")
    with pytest.raises(ValidationError):
        validate_write(field("manual_level"), "Stop")


def test_numeric_write_honours_range():
    assert validate_write(field("co2_threshold"), "900") == "900"
    with pytest.raises(ValidationError):
        validate_write(field("co2_threshold"), "50")
    with pytest.raises(ValidationError):
        validate_write(field("co2_threshold"), "not-a-number")


def test_bool_write_becomes_device_digit():
    assert validate_write(field("breeze_enable"), "ON") == "1"
    assert validate_write(field("breeze_enable"), "off") == "0"


def test_time_write_requires_hhmm():
    assert validate_write(field("start_daytime"), "7:30") == "7:30"
    with pytest.raises(ValidationError):
        validate_write(field("start_daytime"), "25:00")


def test_ventilation_timer_format():
    assert validate_write(field("ventilation_timer"), "30 min level3") == "30 min Level3"
    with pytest.raises(ValidationError):
        validate_write(field("ventilation_timer"), "30 minutes")
