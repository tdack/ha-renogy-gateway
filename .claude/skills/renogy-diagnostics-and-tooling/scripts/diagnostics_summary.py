#!/usr/bin/env python3
"""diagnostics_summary.py — summarise a downloaded HA diagnostics JSON.

Built against exactly what ha-renogy-gateway's diagnostics.py emits:
    {
      "entry_data":    {<config entry keys, sensitive ones "**REDACTED**">},
      "devices":       [{"did_str", "pid", "sku", "name", "online",
                         "field_count", "writable_fields",
                         "subscribable_fields"}, ...],
      "total_devices": <int>,
      "total_fields":  <int>
    }
HA's diagnostics download wraps that payload under a top-level "data" key
(alongside "home_assistant", "integration_manifest", ...); both the wrapped
download and the bare payload are accepted.

NOTE the payload contains per-device COUNTS only — no per-field values and
no ctrl_sp_blacklist. Those must come from debug logs or live inspection.

Usage:
    python3 diagnostics_summary.py <diagnostics.json>

Flags raised:
    - device with field_count == 0        (discovery RPC drops — see SKILL.md)
    - device offline
    - sensitive entry_data key present but NOT "**REDACTED**"
    - count mismatch between totals and the device list

Exit codes: 0 = summarised, 2 = unrecognised structure / bad usage.
"""

from __future__ import annotations

import json
import sys

# Mirrors diagnostics.py's _REDACT (plus email, which lives under CONF_EMAIL).
SENSITIVE = {
    "email",
    "password",
    "access_token",
    "refresh_token",
    "rtm_token",
    "rtm_did",
    "device_uuid",
}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    with open(sys.argv[1], encoding="utf-8") as fh:
        raw = json.load(fh)

    data = raw
    if "devices" not in data and isinstance(raw.get("data"), dict):
        data = raw["data"]  # HA download wrapper
    if not isinstance(data.get("devices"), list):
        print(
            "ERROR: no 'devices' list found — not a renogy_gateway diagnostics dump?",
            file=sys.stderr,
        )
        return 2

    devices = data["devices"]
    entry = data.get("entry_data", {})
    flags: list[str] = []

    print("== rig summary ==")
    print(f"devices: {data.get('total_devices', len(devices))}   "
          f"fields: {data.get('total_fields', '?')}")
    print()
    header = f"{'name':<28} {'did_str':<12} {'pid':<10} {'sku':<18} {'online':<7} {'fields':>6} {'writ':>5} {'subs':>5}"
    print(header)
    print("-" * len(header))
    for d in devices:
        print(
            f"{str(d.get('name', '?')):<28} {str(d.get('did_str', '?')):<12} "
            f"{str(d.get('pid', '?')):<10} {str(d.get('sku', '?')):<18} "
            f"{str(bool(d.get('online'))):<7} {d.get('field_count', 0):>6} "
            f"{d.get('writable_fields', 0):>5} {d.get('subscribable_fields', 0):>5}"
        )
        if d.get("field_count", 0) == 0:
            flags.append(
                f"{d.get('name')} ({d.get('did_str')}): ZERO fields — schema "
                "resolution failed (get_product/get_model RPC drops); expect "
                "no entities for this device"
            )
        if not d.get("online"):
            flags.append(f"{d.get('name')} ({d.get('did_str')}): reported offline")

    # totals sanity
    if "total_fields" in data:
        summed = sum(d.get("field_count", 0) for d in devices)
        if summed != data["total_fields"]:
            flags.append(
                f"total_fields={data['total_fields']} but device field_counts "
                f"sum to {summed}"
            )

    # redaction check
    for k, v in entry.items():
        if k in SENSITIVE and v != "**REDACTED**":
            flags.append(
                f"entry_data['{k}'] is NOT redacted — do not share this file"
            )

    print()
    print(f"entry_data keys: {', '.join(sorted(entry)) or '(none)'}")
    print()
    if flags:
        print("== flags ==")
        for f in flags:
            print(f"  ! {f}")
    else:
        print("== flags ==\n  (none — rig looks healthy)")

    print()
    print("note: this dump carries per-device counts only. Per-field values, "
          "phantom-instance decisions and ctrl_sp_blacklist contents are NOT "
          "included — use debug logs for those.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
