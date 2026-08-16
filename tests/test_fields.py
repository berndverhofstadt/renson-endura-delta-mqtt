from shared.fields import BY_NAME, BY_SLUG, DANGEROUS, FIELDS, controllable


def test_slugs_and_names_are_unique():
    assert len(BY_SLUG) == len(FIELDS)
    assert len(BY_NAME) == len(FIELDS)


def test_every_control_is_actually_writable_on_the_device():
    for field in FIELDS:
        if field.control in ("operational", "installer"):
            assert field.writable, f"{field.name} is exposed as a control but is read-only"


def test_enums_declare_their_options():
    for field in FIELDS:
        if field.kind == "enum":
            assert field.options, f"{field.name} is an enum without options"


def test_dangerous_fields_are_never_controllable():
    for name in DANGEROUS:
        assert BY_NAME[name].control == "blocked"

    exposed = {f.name for f in controllable(expose_installer=True)}
    assert not (exposed & DANGEROUS)


def test_installer_fields_are_hidden_by_default():
    default = {f.name for f in controllable(expose_installer=False)}
    assert "Manual level" in default
    assert "Input 1 function" not in default
    assert "Input 1 function" in {f.name for f in controllable(expose_installer=True)}


def test_input_values_are_read_only():
    # These mirror the physical contacts; the fire-safety stop cannot be faked.
    for slug in ("input1_value", "input2_value", "input3_value"):
        assert not BY_SLUG[slug].writable
        assert BY_SLUG[slug].control is None
