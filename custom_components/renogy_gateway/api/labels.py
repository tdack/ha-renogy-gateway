"""Curated English labels and enum translations.

Ported from renogy-gateway/packages/core/src/params.ts (LABELS,
CURATED_OPTIONS, ZH_OPTION) so the Python integration's entity names and
enum options match the canonical core's presentation curation instead of
leaking Renogy's raw schema field names and Chinese option labels into the
HA UI. PRESENTATION ONLY — capability detection (writable/min/max/etc.)
still comes entirely from the schema.
"""

# English labels keyed by "namespace.full_name" (preferred, disambiguates
# leaves reused across namespaces) or bare leaf name (fallback).
LABELS: dict[str, str] = {
    # charger
    "charger.max_current": "Max charging current",
    "charger.desired_voltage": "Target charge voltage",
    "charger.desired_current": "Target charge current",
    "charger.battery_type": "Battery type",
    "charger.system_type": "System type",
    "charger.priority": "Charge priority",
    "charger.mode": "Charge mode",
    # charge profile
    "boost_voltage": "Boost voltage",
    "float_voltage": "Float voltage",
    "balancing_voltage": "Equalize voltage",
    "equilibrium_voltage": "Equalize voltage",
    "boost_return_voltage": "Boost return voltage",
    "float_return_voltage": "Float return voltage",
    "balancing_return_voltage": "Equalize return voltage",
    "equilibrium_return_voltage": "Equalize return voltage",
    "boost_charge_time": "Boost charge time",
    "balancing_charge_time": "Equalize charge time",
    "equilibrium_charge_time": "Equalize charge time",
    "balancing_charging_period": "Equalize interval",
    "equilibrium_charge_cycle": "Equalize interval",
    "protection_voltage_high": "Over-voltage protection",
    "overvoltage_protection_voltage": "Over-voltage protection",
    "alarm_voltage_high": "Over-voltage warning",
    "overvoltage_warning_voltage": "Over-voltage warning",
    "protection_voltage_low": "Under-voltage protection",
    "undervoltage_protection_voltage": "Under-voltage protection",
    "alarm_voltage_low": "Under-voltage warning",
    "undervoltage_warning_voltage": "Under-voltage warning",
    "overvoltage_protection_return": "Over-voltage recovery",
    "undervoltage_protection_return": "Under-voltage recovery",
    "over_dic_return_voltage": "Over-discharge recovery",
    "over_dic_disconnect_voltage": "Over-discharge cutoff",
    "charging_limit_voltage": "Charge limit voltage",
    "high_volt_disconnect": "High-voltage disconnect",
    "temperature_compensation": "Temperature compensation",
    "lithium_activation": "Lithium activation",
    # channels
    "over_current_setting": "Over-current trip",
    # tanks (analog_input_r)
    "alarm_lower_threshold": "Low-level alarm",
    "alarm_lower_relieve": "Low-level alarm clears at",
    "alarm_higher_threshold": "High-level alarm",
    "alarm_higher_relieve": "High-level alarm clears at",
    "distribution_box.mode": "Sensor type",
    # temps (temp_sensor)
    "low_alarm_threshold": "Low-temp alarm",
    "low_alarm_relieve": "Low-temp alarm clears at",
    "high_alarm_threshold": "High-temp alarm",
    "high_alarm_relieve": "High-temp alarm clears at",
    "alarm_enable": "Alarm enabled",
    # tpms
    "calibration_pressure": "Calibration pressure",
    "voltage": "Battery voltage",
    # charge tips
    "full_charge_tips": "Full-charge reminder",
    "full_charge_tips_enable": "Full-charge reminder enabled",
    # system
    "socRule": "SOC source",
    "automatic_time": "Auto time sync",
    "language": "Language",
}

# Curated enum options for fields the schema leaves without `options`,
# keyed by "namespace.full_name". Renogy Modbus battery-type codes
# (1 Flooded ... 4 Lithium).
CURATED_OPTIONS: dict[str, list[dict]] = {
    "charger.battery_type": [
        {"key": 0, "value": "User-defined"},
        {"key": 1, "value": "Flooded"},
        {"key": 2, "value": "Sealed / AGM"},
        {"key": 3, "value": "Gel"},
        {"key": 4, "value": "Lithium"},
        {"key": 5, "value": "Custom"},
    ],
}

# Chinese -> English for schema-supplied option labels.
ZH_OPTION: dict[str, str] = {
    "不同步": "Off (manual)",
    "自动同步": "Auto",
    "关": "Off",
    "开": "On",
    "同步": "Sync",
    "不提示": "Do Not Prompt",
    "提示": "Prompt",
    "其他": "Other",
}
