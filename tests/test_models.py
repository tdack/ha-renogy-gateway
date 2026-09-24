"""Tests for FieldSpec.display_name's label resolution order."""

from custom_components.renogy_gateway.api.models import FieldSpec


def test_display_name_user_label_wins_over_everything() -> None:
    """A user-assigned channel name always takes precedence."""
    field = FieldSpec(
        sp="123/charger.max_current",
        name="max_current",
        field_type=3,
        ops=7,
        user_label="My Custom Name",
    )
    assert field.display_name == "My Custom Name"


def test_display_name_user_label_kept_verbatim_even_if_schema_like() -> None:
    """A user name that looks like a bare schema leaf ("Power") or isn't ASCII
    is still the user's name — it must not be filtered back to the channel key.

    Parity pin: the sibling repo's dashboard/hass-bridge discarded "Power" for
    "DC 20A 3" by running user names through a schema-label heuristic.
    """
    for label in ("Power", "power", "Küche", "客厅灯"):
        field = FieldSpec(
            sp="123/distribution_box.dc_20a_3.state",
            name="dc_20a_3.state",
            field_type=1,
            ops=7,
            user_label=label,
        )
        assert field.display_name == label


def test_display_name_falls_back_to_curated_label() -> None:
    """charger.max_current resolves to the curated English label."""
    field = FieldSpec(sp="123/charger.max_current", name="max_current", field_type=3, ops=7)
    assert field.display_name == "Max charging current"


def test_display_name_curated_label_matches_bare_leaf() -> None:
    """A bare-leaf curated label applies even under an instance prefix."""
    field = FieldSpec(
        sp="123/tpms.tp_state_1.calibration_pressure",
        name="tp_state_1.calibration_pressure",
        field_type=3,
        ops=7,
    )
    assert field.display_name == "Calibration pressure"


def test_display_name_humanises_uncurated_field() -> None:
    """A field with no curated label falls back to a humanised schema name."""
    field = FieldSpec(
        sp="123/distribution_box.dc_10a_1.state",
        name="dc_10a_1.state",
        field_type=1,
        ops=7,
    )
    assert field.display_name == "Dc 10a 1 State"


def test_namespace_property_extracts_leading_segment() -> None:
    """FieldSpec.namespace returns the namespace portion of the sp."""
    field = FieldSpec(sp="123/charger.max_current", name="max_current", field_type=3, ops=7)
    assert field.namespace == "charger"
