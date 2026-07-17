---
name: renogy-validation-and-qa
description: >
  Testing and QA doctrine for the ha-renogy-gateway HA integration. Load when
  writing or changing tests, deciding what evidence a fix needs before it can
  be called done, checking whether a change is covered by the suite,
  interpreting a pytest/hassfest/HACS failure, or looking up which fixture or
  golden test encodes a capture-derived protocol fact. Covers the evidence
  hierarchy, conftest.py fixture anatomy, the test-file map, recipes for adding
  each kind of test, and known coverage gaps.
---

# Renogy Gateway: validation and QA

Date-stamped 2026-07-12. Facts below were verified by reading `tests/` in full
and the CI workflows at that date. Re-verify with the commands at the end.

## When NOT to use this skill

- Environment setup, installing test deps, or how to actually run pytest
  locally → `renogy-build-and-env`.
- How to capture HARs and derive protocol facts from them (the evidence
  methodology itself) → `renogy-analysis-and-evidence`.
- Whether a change is allowed to ship at all, changelog/version discipline →
  `renogy-change-control`.

## The evidence hierarchy

A claim about this integration's behaviour is only as strong as its evidence.
In descending order of authority:

1. **Real capture or live observation, encoded as a test fixture.** A HAR from
   `captures/` in the sibling renogy-gateway repo, or a live reading from the
   user's rig, gets its exact shape copied into a fixture or inline test
   payload. The suite is full of these — see "The golden inventory" below.
   Never invent a schema shape; if no capture shows it, say so in the test
   docstring.
2. **A regression test that reproduces the symptom before the fix.** The norm
   in this repo is that behaviour fixes ship with (or are locked in by) a
   regression test. Observed examples:
   - Commit `46e3cb4` ("Add regression test for tank ratio/connected
     classification", first shipped in v0.3.0) — encodes the real captured
     `analog_input_r` schema (`ops=[2,4,5,7]`, no literal write bit) to lock
     in the v0.2.7 ops fix for tank sensors.
   - Commit `d11f43e` ("test(sensor): confirm multi-namespace inverter device
     doesn't split across HA devices", v0.5.1) — checked against the
     2026-07-05 inverter HAR and adds a test so the question "does the
     dashboard's nsToRole() bug have an analogue here?" never gets
     re-litigated.
3. **CI green** — the acceptance floor, not the ceiling. All three checks must
   pass: pytest (`.github/workflows/test.yml`, Python 3.13), hassfest and the
   HACS action (`.github/workflows/validate.yml`).

A claimed fix without a failing-then-passing test is not evidence — it is an
assertion. Write the test first, watch it fail, then fix
(cross-ref `renogy-change-control`).

Live-testing `write` operations against the real rig is NEVER acceptable as a
casual verification step — it switches physical circuits. Seek explicit human
permission first, every time.

## Test suite shape

- 14 test files + `tests/conftest.py` + `tests/__init__.py` (~2,780 lines).
- Framework: `pytest-homeassistant-custom-component` + `pytest-asyncio` (see
  `requirements_test.txt`).
- `pyproject.toml` sets `asyncio_mode = "auto"` — test functions are plain
  `async def test_...` with **no** `@pytest.mark.asyncio` decorator. Do not
  add one.
- `pythonpath = ["."]` — imports are
  `from custom_components.renogy_gateway... import ...` and fixtures are
  imported `from .conftest import ...`.
- CI runs pytest on Python 3.13.

## conftest.py anatomy (`tests/conftest.py`)

Everything a new test needs already exists here. Reuse before inventing.

### Fixtures (the callable kind)

| Fixture | What it does |
|---|---|
| `auto_enable_custom_integrations` | Autouse; wraps the plugin's `enable_custom_integrations` so HA will load `custom_components/renogy_gateway` in every test. You never request it explicitly. |
| `mock_coordinator` | A `MagicMock` standing in for `RenogyCoordinator`: `.devices` pre-populated with all five mock devices, `.scenes` with both mock scenes; `async_write`, `async_run_scene`, `async_set_scene_open` are `AsyncMock`s; `get_value` returns `None` (override `.return_value`/`.side_effect` to seed cached values); register/unregister callbacks for telemetry, availability and scenes are `MagicMock`s. Use for entity-level tests — no real coordinator, no HA config entry needed. |
| `mock_setup_entry` | Patches `custom_components.renogy_gateway.async_setup_entry` to return `True` — used in config-flow tests so creating an entry does not start the real integration. |
| `mock_config_entry` | A `MockConfigEntry` (from `pytest_homeassistant_custom_component.common`) with `domain=DOMAIN`, `data=CONFIG_ENTRY_DATA`, `unique_id=f"{MOCK_EMAIL}_{MOCK_GATEWAY_ID}"`. Call `mock_config_entry.add_to_hass(hass)` before constructing a real `RenogyCoordinator`. |
| `hass` | Not defined here — provided by `pytest-homeassistant-custom-component`. A real in-memory `HomeAssistant` instance. |

### Module-level constants (import these, don't redefine)

- **Credentials/tokens:** `MOCK_EMAIL`, `MOCK_PASSWORD`, `MOCK_GATEWAY_ID`,
  `MOCK_GATEWAY_NAME`, `MOCK_DEVICE_UUID`, `MOCK_TOKENS` (a `TokenSet`),
  `CONFIG_ENTRY_DATA` (the full config-entry data dict, including tokens —
  note it deliberately contains `CONF_PASSWORD` so migration tests can prove
  it gets stripped).
- **FieldSpecs** — each encodes a distinct entity-classification case:
  - `FIELD_SOC` — read-only float sensor, `ops=6`, unit `%`.
  - `FIELD_RELAY` — writable bool, no ratio sibling → switch; carries
    `user_label="Cooling Fan"`.
  - `FIELD_LIGHT_STATE` + `FIELD_LIGHT_RATIO` — state/ratio pair; the ratio
    sibling is what makes the state field a light, not a switch.
  - `FIELD_CHARGE_VOLTAGE` — writable bounded float → number.
  - `FIELD_SOC_RULE` — writable enum with `options` → select.
  - `FIELD_AC_CURRENT_MA` — sensor in `mA` (real regression: "1399.98999 mA"
    displayed raw instead of normalising to A).
  - `FIELD_DESIRED_VOLTAGE_MV` — writable in `mV`, no schema precision →
    must scale to V and cap precision at 2dp.
  - `FIELD_MAX_CURRENT_ZH_UNIT` — unit `安培` (Chinese for Ampere), confirmed
    live via captures; must translate like `packages/core/src/params.ts`'s
    `UNIT_MAP` in the sibling repo.
  - `FIELD_ONLINE` — read-only bool → binary sensor, Diagnostic category.
  - `FIELD_UNBOUNDED_NUMBER` — writable, no min/max → number with generous
    fallback range.
  - `FIELD_TPMS_STATE` — read-only enum (`ops=6`) with options → enum sensor.
- **Devices:** `MOCK_SHUNT_DEVICE`, `MOCK_BOX_DEVICE`, `MOCK_CHARGER_DEVICE`,
  `MOCK_INVERTER_DEVICE` (offline, holds the mA/mV fields),
  `MOCK_TPMS_DEVICE` — each a `RenogyDevice` with real-looking `did_str`,
  `pid`, `sku` values.
- **Scenes:** `MOCK_MANUAL_SCENE` (conditionType 1), `MOCK_AUTO_SCENE`
  (conditionType 4, `is_open=True`) — both carry a `raw` dict mirroring the
  REST shape, because `update_scene` echoes the full raw object back.

## Test-file map

| File | Subject | Notable golden/regression tests |
|---|---|---|
| `test_discovery.py` (837 lines — the heart of the suite) | `api/discovery.py`: ops parsing, label application, ref resolution, curation overrides, blacklist, firmware decode, retry/dedupe | `test_parse_ops_matches_dashboard_semantics` (ops 5 and 7 are read+subscribe, NOT writable — the naive-bitmask regression); `test_tpms_pressure_ops5_is_not_writable`; `test_tank_ratio_and_connected_are_sensors_with_real_schema` (commit 46e3cb4); `test_inverter_today_counters_force_readonly` (`_today` accumulators genuinely carry the write bit but must be read-only); `test_tpms_readings_force_readonly_even_with_full_ops` + `test_distribution_box_state_leaf_unaffected_by_tpms_override` (namespace-scoped override and its non-leak); `test_force_readonly_leaf_match_is_case_insensitive` (`battery_input.Voltage`); `test_battery_type_forced_readonly_on_inverter_pid` / `..._still_writable_on_genuine_charger_pid` (pid-scoped, value 14 outside curated 0–5); `test_user_label_real_capture_payload` ("--" placeholder = unset); `test_user_label_double_parse`; `test_metadata_only_device_still_resolves` (Vision); `test_inverter_battery_type_resolves_readonly_end_to_end`; `test_get_model_dedupes_concurrent_calls_for_same_namespace`; `test_skip_namespaces_matches_dashboard_curation` |
| `test_coordinator.py` | `RenogyCoordinator`: write validation, phantom pruning, device merge, reconnect | `test_async_write_rejects_blacklisted_sp` / `..._unknown_sp` / `..._non_writable_field` / `..._wrong_type` / `..._out_of_range_value` (every rejection asserts `write.assert_not_awaited()`); `test_drop_phantom_instances_removes_dead_slots` and `..._ignores_writable_setting_defaults` (liveness must come from a reading, not a setting's firmware default); `test_merge_devices_keeps_prior_fields_on_empty_rediscovery`; `test_rtm_wired_to_schedule_reconnect`; `test_unexpected_disconnect_schedules_reconnect_and_marks_unavailable`; `test_async_shutdown_does_not_schedule_reconnect` |
| `test_rtm.py` | `RenogyRTM` unexpected-disconnect signalling (fake WS classes `_ClosingWS`/`_BlockingWS`) | `test_unexpected_reader_exit_fires_disconnect_callback` (regression: reader exit was silently orphaning reconnect); `test_clean_disconnect_suppresses_callback`; `test_connect_resets_closing_flag_for_next_disconnect` |
| `test_config_flow.py` | Config flow, reauth | `test_single_gateway_creates_entry` (asserts `"password" not in result["data"]`); `test_multiple_gateways_shows_selection`; `test_duplicate_entry_aborted`; `test_reauth_does_not_persist_password` |
| `test_init.py` | `async_setup_entry` / `async_migrate_entry` | `test_device_with_no_fields_still_gets_registered` (Vision needs explicit device-registry registration); `test_migrate_entry_strips_stored_password` (v1→v2 migration) |
| `test_sensor.py` | Sensor platform + classification helpers | `test_milliamp_sensor_normalised_to_amps`; `test_multi_namespace_device_does_not_split_across_ha_devices` (commit d11f43e); `test_enum_sensor_translates_chinese_option_labels`; `test_connection_type_sensor_for_metadata_only_device`; `test_sensor_diagnostic_for_status_like_field` |
| `test_switch.py` | Switch platform, load vs config classification | `test_relay_with_power_sibling_is_load_switch` / `test_relay_without_measurement_sibling_is_config_switch`; `test_switch_seeds_value_from_coordinator_cache` |
| `test_light.py` | Light platform (state+ratio pair) | `test_light_turn_on_with_brightness` (ratio write then state write, in that order); `test_light_seeds_state_and_brightness_from_coordinator_cache` |
| `test_number.py` | Number platform | `test_millivolt_number_normalised_to_volts` and `..._write_converts_back_to_raw_units` (read/write scaling are inverses); `test_chinese_ampere_unit_translated`; `test_light_ratio_field_excluded_from_number`; `test_unbounded_number_gets_fallback_range` |
| `test_select.py` | Select platform | `test_select_writes_back_the_raw_key` (writes key, never label); `test_select_translates_chinese_option_labels` |
| `test_scenes.py` | REST `get_scenes`/`update_scene`, RTM `run_scene`, button + auto-scene switch | `test_rtm_run_scene_sends_op6_rpc` (op 6 to `<gwDid>/scene.run`); `test_update_scene_echoes_raw_body_with_flipped_open` (full-object write, matching the dashboard's bridge.ts); `test_scene_entity_unavailable_when_scene_disappears` |
| `test_models.py` | `FieldSpec.display_name` resolution order | user label > curated label (incl. bare-leaf match under instance prefix) > humanised schema name |
| `test_binary_sensor.py` | Binary sensor | `test_online_field_is_diagnostic` (only test in the file) |
| `test_diagnostics.py` | Diagnostics redaction | `test_diagnostics_redacts_email_and_password` (only test in the file) |

## The golden inventory (capture-derived facts locked in tests)

These tests encode facts observed in real HARs/live rigs. Changing the
behaviour they assert requires new capture evidence, not a hunch:

- ops semantics: 5 and 7 are composite read+subscribe codes, writable only
  when literal `1` is present — `test_parse_ops_matches_dashboard_semantics`
  (inverter `Bat_Chg_Energy` reports `ops=[2,4,5,7]` and is read-only;
  PROTOCOL.md §7.4's `dc_output_ext.state` has the literal 1).
- `analog_input_r.ratio`/`connected` report `ops=[2,4,5,7]` —
  `test_tank_ratio_and_connected_are_sensors_with_real_schema`.
- `userdata_str.config` real shape: namespace-qualified keys, object values
  with `name`, `"--"` means unset, sometimes single- sometimes double-JSON
  encoded — `test_user_label_real_capture_payload`, `test_user_label_double_parse`.
- Inverter `_today` counters genuinely carry the write bit —
  `test_inverter_today_counters_force_readonly`.
- RIV1230RCH-24S (pid `000F003C`) reports `charger.battery_type=14`, outside
  the curated 0–5 range — `test_battery_type_forced_readonly_on_inverter_pid`,
  `test_inverter_battery_type_resolves_readonly_end_to_end` (07-05 HAR).
- Same inverter reports both `voltage` and `battery_input.Voltage` —
  `test_force_readonly_leaf_match_is_case_insensitive`.
- Chinese unit `安培` on `charger.max_current` — `FIELD_MAX_CURRENT_ZH_UNIT` +
  `test_chinese_ampere_unit_translated`; Chinese enum labels (关/开 etc.) —
  `test_enum_sensor_translates_chinese_option_labels`,
  `test_select_translates_chinese_option_labels`.
- Vision (pid `002C0000`) has only `thing` + `version_ctrl` namespaces and
  `protocol: "wifi"` — `test_metadata_only_device_still_resolves`,
  `test_get_product_returns_namespaces_and_protocol`,
  `test_device_with_no_fields_still_gets_registered`.
- `sw_ver` packs as 2-3-3 digit groups (11005003 → V11.5.3) —
  `test_get_firmware_decodes_packed_version`.
- Channel-count bookkeeping fields (`dc_10a_count`, ...) exist in the schema
  but are not telemetry — `test_distribution_box_channel_counts_excluded`.
- Unbound TPMS slots answer writable settings with firmware defaults while
  readings stay unset —
  `test_drop_phantom_instances_ignores_writable_setting_defaults`.

## How to add a test — recipes from the suite

### (a) Discovery/curation regression test (`test_discovery.py` pattern)

No `hass` needed. Mock the RTM, feed it the schema shape **exactly as
captured**, assert the resolved `FieldSpec`s. Cite the capture in the
docstring.

```python
async def test_my_field_classified_correctly() -> None:
    """One-line statement of the observed symptom + capture provenance."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={"sps": [{"name": "ratio", "type": 2, "ops": [2, 4, 5, 7], "unit": "%"}]}
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "analog_input_r")

    by_name = {f.name: f for f in fields}
    assert by_name["ratio"].writable is False
```

Idioms: `rtm.rpc = AsyncMock(side_effect=[...])` for multi-call sequences
(get_product then get_model, or `ref` resolution); `rtm.read = AsyncMock(...)`
for `_get_user_labels`/`_get_firmware`/`_get_ctrl_sp_blacklist`; patch
`discovery.asyncio.sleep` via `monkeypatch` when testing retries.

### (b) Entity-behaviour test (platform pattern)

Construct the entity directly with `mock_coordinator` — no platform setup, no
entity registry. Stub `async_write_ha_state` before pushing telemetry.

```python
async def test_sensor_state_from_telemetry(hass: HomeAssistant, mock_coordinator) -> None:
    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, FIELD_SOC)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()

    sensor._handle_telemetry(87.5)
    assert sensor.native_value == 87.5
```

For control paths, assert against the coordinator mock:
`mock_coordinator.async_write.assert_awaited_once_with(FIELD_RELAY.sp, True)`.
For cache seeding, set `mock_coordinator.get_value.return_value` (or
`.side_effect` for per-sp values), set `entity.entity_id`, then
`await entity.async_added_to_hass()` — see
`test_switch_seeds_value_from_coordinator_cache`.

### (c) Coordinator/reconnect test

Build a **real** `RenogyCoordinator` on the real `hass`, then stub only its
edges (`coordinator._rtm.write`, `._rtm.disconnect`,
`._connect_and_discover`):

```python
async def test_something(hass: HomeAssistant, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {MOCK_BOX_DEVICE.did_str: MOCK_BOX_DEVICE}
    coordinator._rtm.write = AsyncMock(return_value={"code": 0})
    ...
```

Every write-rejection test pairs `pytest.raises(HomeAssistantError, match=...)`
with `coordinator._rtm.write.assert_not_awaited()` — keep both halves.
Async-scheduling tests use `await asyncio.sleep(0)` to let `call_soon`/task
starts run, and `monkeypatch.setattr(...RTM_RECONNECT_DELAY_MIN, 0)` to avoid
real delays.

### (d) Config-flow test

Uses the file-local autouse `mock_auth_and_rest` fixture (patches
`config_flow.RenogyAuth` and `config_flow.RenogyREST`) plus
`@pytest.mark.usefixtures("mock_setup_entry")` when the flow will create an
entry:

```python
result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
result = await hass.config_entries.flow.async_configure(
    result["flow_id"], {"email": MOCK_EMAIL, "password": MOCK_PASSWORD}
)
await hass.async_block_till_done()
assert result["type"] is FlowResultType.CREATE_ENTRY
assert "password" not in result["data"]
```

Reauth: `await mock_config_entry.start_reauth_flow(hass)`.

### General authoring rules observed in the suite

- Docstrings state the symptom, the fix, and the capture provenance ("confirmed
  via captures/*.har in the sibling renogy-gateway repo", "the 07-05 HAR").
  Follow that convention — the docstring is where the evidence trail lives.
- Regression tests come in pairs: the fix, and the non-leak (e.g. the TPMS
  readonly override plus
  `test_distribution_box_state_leaf_unaffected_by_tpms_override`). When you
  add a scoped override, add the test proving it doesn't leak.
- Never mutate shared module-level fixtures — copy first
  (`dataclasses.replace(MOCK_AUTO_SCENE)`, see
  `test_async_set_scene_open_updates_state_and_fires_callback`).

## Acceptance discipline

Before merge, all of CI must be green:

1. **pytest** (`test.yml`) — runs on every push and PR, Python 3.13,
   `pip install -r requirements_test.txt && pytest`.
2. **hassfest** (`validate.yml`) — HA's integration validator. A failure
   usually means a `manifest.json` problem (missing/invalid keys, bad version,
   requirements format) or `strings.json` inconsistencies.
3. **HACS action** (`validate.yml`, `category: integration`) — HACS
   repository-structure rules (hacs.json, repo topics/description, README).

The evidence bar for a behaviour fix is a test that failed before the fix and
passes after. "I ran it in my head" or "the code looks right" does not clear
the bar (see `renogy-change-control`). For protocol-shape questions, the bar
is a capture (see `renogy-analysis-and-evidence`).

## Coverage honesty — observed gaps (2026-07-12)

Candidates for new tests, not criticisms; identified by reading, not by
running coverage tooling:

- **`api/auth.py` and most of `api/rest.py` have no direct tests** — no
  `test_auth.py`/`test_rest.py`; login, token refresh/rotation, and the
  401/999 refresh triggers are only exercised behind mocks. The
  token-handling tests that do exist target the config-entry side
  (`test_migrate_entry_strips_stored_password`,
  `test_reauth_does_not_persist_password`).
- **`api/rtm.py` is only tested for disconnect signalling and `run_scene`** —
  connect/auth handshake, subscribe, read, write framing and the op-code
  paths are untested. (The scene RTM path *is* tested:
  `test_rtm_run_scene_sends_op6_rpc`.)
- **Platform `async_setup_entry` wiring is untested** — entities are always
  constructed directly; no test drives full platform setup and asserts which
  entities get created for a device (the classification helpers `_is_sensor`,
  `_is_number`, `_is_select`, `_is_load_switch` are tested individually
  instead). The light platform's state/ratio pairing logic at setup time is
  therefore untested.
- **`test_binary_sensor.py` and `test_diagnostics.py` are single-test files**
  — binary sensor has no telemetry/state test; diagnostics only checks
  redaction, not payload content.
- **`button.py` is only covered via the scene button**; the coordinator's
  telemetry fan-out (delivery through `register_telemetry_callback`) is
  untested on the coordinator side, only the entity-side handlers.

## Provenance and maintenance

Re-verify the load-bearing facts:

- File count and sizes: `ls tests/ && wc -l tests/*.py` (14 test files + conftest).
- Fixture inventory: `grep -n "def \|^FIELD_\|^MOCK_" tests/conftest.py`.
- Golden test names: `grep -rn "def test_" tests/ | wc -l` and
  `grep -n "captures/\|HAR\|regression" tests/*.py`.
- CI floor: `cat .github/workflows/test.yml .github/workflows/validate.yml`.
- Cited commits: `git show --stat 46e3cb4 d11f43e`;
  `git tag --contains 46e3cb4 | head -1` (v0.3.0),
  `git tag --contains d11f43e | head -1` (v0.5.1).
- Pytest config: `grep -A3 pytest.ini_options pyproject.toml`
  (`asyncio_mode = "auto"`).
