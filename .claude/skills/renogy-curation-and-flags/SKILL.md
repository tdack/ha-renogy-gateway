---
name: renogy-curation-and-flags
description: >-
  Catalogue of every curation constant in the renogy_gateway HA integration —
  the sets, dicts, patterns and tunables that decide which schema fields
  become entities and how they surface. Load when adding or changing ANY
  curation constant, when a field surfaces wrongly (a reading shown as a
  Number/Select, a phantom tank/TPMS slot, a Chinese label, a missing enum),
  when a newly discovered device surfaces wrong or missing entities that
  discovery alone cannot fix, or before touching const.py or
  discovery.py constants. Includes the strict checklist for adding an entry
  and mirroring it in the sibling renogy-gateway repo.
---

# Renogy curation constants and flags

This project has no user-facing feature flags. Its configuration axes are the
CURATION CONSTANTS below — hand-maintained sets and dicts that shape which of
the hundreds of schema-discovered fields become Home Assistant entities, which
are read-only, which are diagnostic, and how they are labelled.

Two repos are involved:

- **This repo** (`ha-renogy-gateway`) — the HA custom integration.
- **Sibling canonical repo** (`renogy-gateway`, read-only from here, checked
  out as a sibling directory, e.g. `../renogy-gateway`) — the TypeScript
  monorepo where curation canonically lives. Every curation change here MUST
  be mirrored there (or land there first) — and from HA sessions "mirrored"
  means a written proposal for the owner (see step 4 of the checklist below).

Two unwritten rules govern everything below:

1. **Evidence bar** — NO new curation entry without a capture excerpt
   (`captures/*.har` in the sibling repo) or a live observation. The schema
   lies (it marks nearly everything writable); curation entries exist to
   correct it, so each one needs proof.
2. **Never live-test writes without explicit user permission** — these
   constants gate real circuit switching.

Catalogue accurate as of **2026-07-12, v0.5.1**. These constants ARE the
drift-prone surface — re-verify with the greps in "Provenance and
maintenance" before trusting the enumerations.

## When NOT to use this skill

- Running a systematic drift reconciliation against the sibling repo → use
  `renogy-curation-parity-campaign`.
- Understanding WHY a curation entry exists (the bug history behind it) → use
  `renogy-failure-archaeology`.

---

## Axis catalogue

All paths are repo-relative under `custom_components/renogy_gateway/` unless
stated otherwise. "Sibling" paths are relative to the renogy-gateway repo root.

### 1. `api/discovery.py` — schema-to-entity gate

#### `_SKIP_NAMESPACES` (frozenset, 17 members)

```
thing, gwm, version_ctrl, driving_mode, cloud, customAlarm, scene,
charger_history, userdata_str, sys_data_str, factoryConfig, ems_gw,
buzzer, gyro, dev_ota, ssh_debug, rtc_sync
```

- **Mechanics:** applied in `RenogyDiscovery._resolve_device()` — namespaces in
  this set never enter `_get_fields()`, so none of their fields become
  entities. Three skipped namespaces are still special-cased elsewhere:
  `driving_mode` (read for `ctrl_sp_blacklist`), `userdata_str` (read for
  channel labels), `thing` (one-shot `thing.sw_ver` firmware read); `scene`
  gets its own platform via REST (PROTOCOL.md §8).
- **Evidence:** mirrors the intersection-of-intent of the curation both
  sibling apps apply.
  Namespaces like `gwmConfig`, `digital_input`, `signal`, `alternator`,
  `battery_temp_sensor`, `battery_volt_sensor` carry real data and are
  deliberately NOT skipped (see the comment block above the constant).
- **Sibling counterpart:** no single set. It is the intersection-of-intent of
  `packages/core/src/params.ts` `PARAM_HIDE_NS` (23 members — also hides
  `inverter_history`, `digital_input`, `signal`, `alternator`,
  `battery_temp_sensor`, `battery_volt_sensor`, which HA keeps) and
  `apps/dashboard/src/worker/bridge.ts` `SKIP_SUBSCRIBE_NS` (20 members —
  also skips `charger_params`, `charge_params`, `gwmConfig`,
  `inverter_history`). Expect deliberate divergence; do not blind-sync.
- **Status:** production.

#### `_ENTITY_TYPES` (frozenset)

```
{1, 2, 3}   # bool, int, float
```

- **Mechanics:** in `_expand_sp()` — a field whose schema `type` is outside
  this set (str=4, array=5, obj=7, func=8, series=9) yields no `FieldSpec`
  (types 7/8 are handled structurally: 7 recurses, 8 is dropped).
- **Evidence:** PROTOCOL.md §7.3 type codes.
- **Sibling counterpart:** no named constant — `packages/core/src/params.ts`
  `widgetType()` returns null for anything but boolean/integer/number, the
  same effective filter.
- **Status:** production.

#### `_FORCE_READONLY_LEAVES` (frozenset, case-insensitive match)

```
voltage, ac_input_voltage, ac_input_current, ac_input_frequency, output_watts
```

- **Mechanics:** via `_is_force_readonly()` in `_expand_sp()` — strips the
  write bit (`ops &= ~1`) so the field surfaces as a sensor, never a
  Number/Select. Case-insensitive because a real capture shows the same
  quantity under inconsistently-cased leaf names (e.g. `voltage` alongside
  `battery_input.Voltage`).
- **Evidence:** `captures/*.har` (sibling repo); the AC leaves come from the
  RIV1230RCH-24S inverter — no capture ever shows `gwm.get_model` for
  `ac_input`/`ac_output`/`battery_input`, and the dashboard's own curated
  labels confirm they are pure readings. See sibling commit 84856f2.
- **Sibling counterpart:** `packages/core/src/discovery.ts`
  `FORCE_READONLY_LEAVES` — identical five members. (`params.ts` also keeps a
  belt-and-suspenders `READONLY_LEAF = {'voltage'}` at presentation level.)
- **Status:** production.

#### `_FORCE_READONLY_SUFFIXES` (tuple)

```
("_today",)
```

- **Mechanics:** same write-bit strip, matched with `endswith` on the
  lower-cased leaf.
- **Evidence:** confirmed live in captures — every `_today` daily accumulator
  in the inverter's `inverter_history` model (`bat_chg_ah_today`,
  `generat_energy_today`, ...) reports `ops=[1,2,4,5,7]` with a genuine write
  bit, despite being counters nobody sets.
- **Sibling counterpart:** `packages/core/src/discovery.ts`
  `FORCE_READONLY_SUFFIXES = ['_today']`. Identical.
- **Status:** production.

#### `_FORCE_READONLY_LEAVES_BY_NAMESPACE` (dict)

```
{"tpms": {"pressure", "temperature", "battery_status", "online", "state"}}
```

- **Mechanics:** same strip, but scoped to a namespace because the leaf name
  is a genuine control elsewhere — `state` is THE writable on/off field for
  `distribution_box` channels.
- **Evidence:** PROTOCOL.md §6 documents `tpms.tp_state_N.*` as pure
  readings; observed live that some rigs mark `pressure` and `online`
  writable anyway.
- **Sibling counterpart:** `packages/core/src/discovery.ts`
  `FORCE_READONLY_BY_NS` — identical.
- **Status:** production.

#### `_FORCE_READONLY_LEAVES_BY_PID` (dict)

```
{"000F003C": {"battery_type"}}
```

- **Mechanics:** same strip, scoped to a product id because the leaf is a
  genuine writable setting on other products (the MPPT/DC-DC chargers).
- **Evidence:** RIV1230RCH-24S (pid 000F003C) reports `charger.battery_type`
  writable, but its own Chinese schema desc says battery type is fixed on
  REGO-family inverters, and the live value 14 falls outside
  `CURATED_OPTIONS`' 0–5 range. See INVERTER_HAR_FIXES_PLAN.md Priority 3;
  this-repo commit ae59831; sibling commit ffac2f3.
- **Sibling counterpart:** `packages/core/src/params.ts`
  `PARAM_FORCE_READONLY_BY_PID = {'000F003C': Set(['charger.battery_type'])}`.
  Note the structural difference: the sibling filters at the presentation
  layer keyed by `namespace.leaf`; HA strips the ops bit in discovery keyed by
  bare leaf. Same effect, different mechanism — mirror intent, not shape.
- **Status:** evidence-backed exception.

#### `_MAX_CONCURRENT` = 4

- **Mechanics:** `asyncio.Semaphore` bounding concurrent device resolution in
  `discover()` (coordinator.py separately uses its own `Semaphore(4)` for
  initial reads and subscribes).
- **Evidence:** avoids overwhelming the gateway during the connect-time burst.
- **Sibling counterpart:** `packages/core/src/discovery.ts` `mapLimit(items,
  4, ...)` — the limit `4` is passed inline, not a named constant.
- **Status:** production tunable.

#### RPC retry: `_rpc_with_retry(attempts=3, base_delay=0.3)`

- **Mechanics:** wraps `RenogyRTM.rpc()` with linear backoff
  (`base_delay * (attempt+1)`), retrying `RenogyRTMError` and `TimeoutError` —
  a layer ON TOP of rtm.py's own timeout retry, because a frame lost in the
  connect burst surfaces as an outright error which `rpc()` does not retry.
- **Sibling counterpart:** `packages/core/src/discovery.ts` `withRetry(fn,
  attempts=3, baseDelayMs=300)`. Identical numbers.
- **Status:** production tunable.

### 2. `const.py` — entity presentation gates

#### `HIDE_LEAVES` (frozenset, 17 members)

```
inverter_switch, di_mapping, di_mapping2, ctrl_sp_blacklist, alarmList,
clean_history_data, save_config, tp_bind_list, config, addr, coef,
dc_10a_count, dc_20a_count, dc_voltage_count, di_count, relay_count, ai_count
```

- **Mechanics:** checked on the leaf in `discovery._expand_sp()` — a matching
  field yields no `FieldSpec` at all (unlike force-readonly, which keeps the
  field as a sensor). For protocol internals and maintenance commands.
- **Evidence:** the six `*_count` leaves are schema-internal channel-count
  bookkeeping for `distribution_box`, confirmed via `captures/*.har`.
- **Sibling counterpart:** `packages/core/src/params.ts` `PARAM_HIDE_LEAF`
  (13 members). Deliberate divergence: the sibling additionally hides `state`
  and `ratio` (they are live controls/readings rendered by dedicated dashboard
  cards, not settings), while HA needs them as switch/sensor entities so must
  NOT hide them; HA adds the six `*_count` leaves the sibling lacks.
- **Status:** production.

#### `_DIAGNOSTIC_PATTERNS` / `is_diagnostic_field(sp)`

13 compiled regexes:

```
\.online$  alarm  fault  \berror  warning  _status$  \.status$
_state$  _code$  protocol  firmware  _version$  heartbeat
```

- **Mechanics:** `is_diagnostic_field()` matches against the
  `namespace.field_path` portion of the sp; matching read-only entities get
  `entity_category=DIAGNOSTIC` in the entity platforms (grep for callers in
  `sensor.py` / `binary_sensor.py`).
- **Sibling counterpart:** `apps/hass-bridge/src/filter.ts`
  `DEFAULT_ENTITY_FILTER_CONFIG.diagnosticPatterns` — identical 13 patterns.
- **Status:** production.

#### `RTM_RECONNECT_DELAY_MIN` = 2, `RTM_RECONNECT_DELAY_MAX` = 30 (seconds)

- **Mechanics:** exponential backoff bounds in
  `coordinator._reconnect_loop()` (`delay = min(delay * 2, MAX)`).
- **Sibling counterpart:** none equivalent —
  `apps/dashboard/src/worker/bridge.ts` uses a fixed
  `RECONNECT_DELAY_MS = 3_000` with no backoff. Different design; no parity
  obligation.
- **Status:** production tunable.

#### `CONF_*` token keys

`CONF_GATEWAY_ID`, `CONF_GATEWAY_NAME`, `CONF_REFRESH_TOKEN`,
`CONF_RTM_TOKEN`, `CONF_RTM_DID`, `CONF_DEVICE_UUID` (plus HA's own
`CONF_ACCESS_TOKEN` imported in coordinator.py/config_flow.py).

- **Mechanics:** keys under which `coordinator._persist_tokens()` writes the
  rotating token set into config entry data on every refresh (token rotation:
  the refresh token dies on each use — persistence must be immediate).
- **Deliberately NOT persisted:** the account **password**. Since 0.4.0 the
  config entry stores tokens only; existing entries were migrated to drop any
  stored password (CHANGELOG.md, `[0.4.0]`). Never reintroduce it.
- **Sibling counterpart:** none — the sibling persists tokens via a
  `TokenStore` (file / DO storage), not HA config entries.
- **Status:** production.

### 3. `coordinator.py` — phantom-slot pruning

#### `_INSTANCE_PATTERNS` (tuple of 3 regexes)

```
^ai_\d+$   ^temp_\d+$   ^tp_state_\d+$
```

- **Mechanics:** `_drop_phantom_instances()` groups fields by `channel_key`
  matching these patterns; a slot is kept only if some NON-writable field in
  it has a live seeded value. Writable settings answer with firmware defaults
  even for unbound slots (e.g. every TPMS slot reports
  `calibration_pressure=430`), so liveness is judged from genuine readings
  only.
- **Evidence:** schema advertises every tank/temp/TPMS slot the model
  supports regardless of what is wired; observed defaults on unbound slots.
- **Sibling counterpart:** `packages/core/src/params.ts` — the
  `INSTANCE_KINDS` regexes (`^ai_\d+$`, `^temp_\d+$`, `^(dc_\d+a_\d+|relay_\d+)$`,
  `^tp_state_\d+$`) plus `filterConfiguredParams()` (same
  settings-vs-measurement liveness logic, `online` also excluded). HA omits
  the channel pattern (`dc_*a_*`/`relay_*`) — box channels are always real.
- **Status:** production.

### 4. `api/labels.py` — curated label / enum / translation machinery

Ported wholesale from `packages/core/src/params.ts` in commit **d98dfc5**
(`feat(labels): port curated English labels + enum translation from core`,
released in 0.5.0). PRESENTATION ONLY — capability detection stays
schema-driven. Three tables:

#### `LABELS` (dict, 54 entries)

English labels keyed by `"namespace.full_name"` (preferred) or bare leaf
(fallback). Groups: charger (7 namespace-qualified entries such as
`charger.max_current` → "Max charging current"), charge profile (~29 leaf
entries: boost/float/equalize voltages and times, over/under-voltage
protection/warning/recovery, `temperature_compensation`,
`lithium_activation`, ...), channels (`over_current_setting`), tanks
(`alarm_lower_threshold` etc. + `distribution_box.mode` → "Sensor type"),
temps (`low_alarm_threshold` etc., `alarm_enable`), TPMS
(`calibration_pressure`, `voltage` → "Battery voltage"), charge tips
(`full_charge_tips`, `full_charge_tips_enable`), system (`socRule`,
`automatic_time`, `language`).

- **Mechanics:** consumed by `models.FieldSpec.display_name` — priority is
  user label (`userdata_str.config`) → `LABELS["ns.name"]` → `LABELS[leaf]`
  → `_humanize()`.
- **Sibling counterpart:** `packages/core/src/params.ts` `LABELS` — identical
  content (verified line-by-line 2026-07-12).

#### `CURATED_OPTIONS` (dict, 1 entry)

```
"charger.battery_type": [0 User-defined, 1 Flooded, 2 Sealed / AGM,
                         3 Gel, 4 Lithium, 5 Custom]
```

- **Mechanics:** in `discovery._expand_sp()`, schema-supplied `options` win;
  this map only fills fields the schema leaves without options. Renogy Modbus
  battery-type codes.
- **Sibling counterpart:** `params.ts` `CURATED_OPTIONS` — same content,
  shape differs (`{value, label}` there vs `{key, value}` here).

#### `ZH_OPTION` (dict, 8 entries)

Chinese → English for schema-supplied option labels: 不同步 "Off (manual)",
自动同步 "Auto", 关 "Off", 开 "On", 同步 "Sync", 不提示 "Do Not Prompt",
提示 "Prompt", 其他 "Other".

- **Mechanics:** applied where enum options are rendered — both `select.py`
  (`RenogySelect`) and `sensor.py` (`RenogyEnumSensor`) map option values
  through `ZH_OPTION`.
- **Sibling counterpart:** `params.ts` `ZH_OPTION` — identical. The sibling
  also has `UNIT_FALLBACK`, `LEAF_ORDER`, `NS_GROUP` — not ported to HA
  (ordering comes from HA itself). Its `UNIT_MAP` (安培 → A, ℃ → °C) IS
  covered in HA by `sensor.py`'s `_UNIT_MAP` — see axis 8 below.
- **Status (all three):** production.

### 5. `api/rtm.py` — protocol tunables

```
RTM_URL          = "wss://gateway.renogy.com/rtm/ws"
_RPC_TIMEOUT     = 10.0   # s, per correlated frame (_call)
_RPC_RETRIES     = 3      # rpc() retries on TimeoutError, 0.3*(n+1) backoff
_CONNECT_TIMEOUT = 10.0   # s, WS upgrade close-timeout + connect-ack wait
```

- **Sibling counterpart:** `packages/core/src/rtm.ts` — `RTM_URL` identical;
  `CALL_TIMEOUT_MS = 10_000` matches `_RPC_TIMEOUT`. The sibling's rtm has no
  built-in RPC retry loop (retry lives in discovery.ts `withRetry`); HA has
  both layers.
- **Status:** production tunables. `RTM_URL` is protocol ground truth
  (PROTOCOL.md §5); never change without a capture showing a new endpoint.

### 6. `api/auth.py` — API-impersonation constants

```
BASE_URL          = "https://gateway.renogy.com"
REFRESH_SKEW      = 60          # s before exp to proactively refresh
_APP_REGISTER_PID = "003F0000"  # the iOS app's own pseudo-product id
_APP_NODE_TYPE    = 4           # app/user node type
CLIENT_HEADERS    = app-version 1.8.82, device-version 26.5,
                    device-mode iPad8,6, device-manufacturer Apple,
                    request-channel ios, Content-Type/Accept/Accept-Language,
                    User-Agent "Renogy/1.8.82 (com.renogy.DCHome; build:2;
                    iOS 26.5.0) Alamofire/5.11.2"
```

- **Mechanics:** `CLIENT_HEADERS` sent on every REST call (+ `identity-uuid`,
  `x-token` added per-request); `_APP_REGISTER_PID`/`_APP_NODE_TYPE` drive the
  cold-boot `POST /api/v2/device/app-register` that mints the first rtmToken
  from email + password alone.
- **Evidence:** captured iOS app traffic; app-register solved 06-12 (see the
  renogy-gateway CLAUDE.md "Open/untested" note and PROTOCOL.md §2.1).
- **Sibling counterpart:** `packages/core/src/rest.ts` — the header literal
  near the top (`'app-version': '1.8.82'`, ...) and `APP_PID` /
  `APP_NODE_TYPE` (used in the app-register body around line 340).
- **Status:** production. Header values are impersonation surface — update
  only from a fresh capture of a newer app build, and mirror both repos.

### 7. `api/models.py` — curation-adjacent derivations

- `FieldSpec.display_name` — the label priority chain (user label → LABELS →
  `_humanize`). Sibling: `params.ts` `labelFor()` + `humanize()`.
- `FieldSpec.channel_key` — second dotted segment of the path
  (`distribution_box.dc_10a_1.state` → `dc_10a_1`); the join key for user
  labels and phantom-slot pruning. Sibling: `params.ts` `splitPath()`.
- `_humanize()` — capitalise-each-word fallback. Sibling: `humanize()` /
  `prettify()` in params.ts (slightly different casing rules; cosmetic).

### 8. `sensor.py` — unit normalisation (`_UNIT_MAP`)

Renogy unit string → (HA unit, device class, scale), around line 35 of
`sensor.py`; `number.py` reuses it, scaling min/max bounds and dividing
back to wire scale on write.

- **Mechanics:** normalises milli-prefixed wire units (`mA`/`mV`/`mW` →
  A/V/W at 0.001) and translates Chinese unit strings (`安培` → A,
  `℃` → °C); caps display precision.
- **Evidence:** commits `4ae1191` (0.2.6, milli-unit normalisation +
  display precision) and `fcfceb4` (0.2.8, zh unit fix), both
  capture-backed.
- **Sibling counterpart:** `packages/core/src/params.ts` `UNIT_MAP`
  (安培 → A, ℃ → °C) plus `packages/core/src/discovery.ts` `unitScale`
  (mV/mA/mW normalisation; sibling commits `c0be656`, `30d3d9d`). HA
  covers both sibling `UNIT_MAP` entries; `UNIT_FALLBACK` / `LEAF_ORDER` /
  `NS_GROUP` remain sibling-only.
- **Status:** production.

---

## How to add or change a curation entry

Follow ALL six steps, in order. Skipping step 1 or 4 is how the two repos
rot apart.

1. **Obtain evidence.** A capture excerpt (`captures/*.har`, sibling repo) or
   a live observation showing the schema lying (wrong ops, missing options,
   phantom slot, Chinese label). Method → `renogy-analysis-and-evidence`.
   No evidence, no entry.
2. **Decide scope** using the four-tier force-readonly design (narrowest
   honest scope wins; the tiers' own comments in api/discovery.py state the
   decision rule):
   - **Global leaf** (`_FORCE_READONLY_LEAVES`) — only if NO namespace
     legitimately has a writable control under that name, ever.
   - **Suffix** (`_FORCE_READONLY_SUFFIXES`) — a naming convention that is
     always a reading (`_today` accumulators).
   - **Namespace-scoped** (`_FORCE_READONLY_LEAVES_BY_NAMESPACE`) — the leaf
     is a genuine control in another namespace (e.g. `state`).
   - **Pid-scoped** (`_FORCE_READONLY_LEAVES_BY_PID`) — the leaf is a genuine
     setting on other products (e.g. `battery_type` on real chargers).
   For hiding entirely, use `HIDE_LEAVES` (protocol internal / maintenance
   command) or `_SKIP_NAMESPACES` (whole namespace is internal) instead —
   hide removes the entity; force-readonly keeps it as a sensor.
3. **Implement with an evidence comment** matching the existing style: state
   what was observed, where (capture / live / PROTOCOL.md §), and why this
   scope — read the comments above `_FORCE_READONLY_LEAVES` and
   `_FORCE_READONLY_LEAVES_BY_PID` as the template.
4. **Mirror in the sibling counterpart** named in the axis entry above
   (usually `packages/core/src/discovery.ts` for ops-stripping,
   `packages/core/src/params.ts` for labels/options/pid-presentation,
   `apps/hass-bridge/src/filter.ts` for diagnostic patterns). Mirror intent,
   not shape — the pid tier, for instance, is structurally different in each
   repo. The sibling is read-only from HA sessions: mirroring means writing
   a precise, evidence-cited proposal for the owner (exact constant, exact
   entries, evidence refs), or confirming the counterpart already exists —
   never committing to the sibling.
5. **Regression test.** Follow the existing patterns in
   `tests/test_discovery.py`: e.g.
   `test_battery_type_forced_readonly_on_inverter_pid` +
   `test_battery_type_still_writable_on_genuine_charger_pid` (always test the
   negative — that the entry does NOT over-match),
   `test_force_readonly_leaf_match_is_case_insensitive`,
   `test_skip_namespaces_matches_dashboard_curation`,
   `test_hide_leaves_excluded_from_fields`.
6. **Changelog entry** before any version bump/tag → `renogy-change-control`
   (and CLAUDE.md's release rule).

## How these drift

The sibling repo moves fast and curation changes there do NOT announce
themselves here. Recent sibling commits that changed curation surface:

- `ffac2f3` — fix(params): exclude charger.battery_type from writable
  controls on inverter pid 000F003C (added `PARAM_FORCE_READONLY_BY_PID`).
- `84856f2` — fix(core): strip write bit from schema-mislabelled readings
  (AC/tpms/_today) (added the whole `isForceReadonly` tier set).
- `824b83c` — fix(core): curate history metrics with an allowlist, not
  namespace membership (a new `packages/core/src/history.ts` curation axis
  with NO HA counterpart yet — history is dashboard-only so far).

Before relying on this catalogue for a change, diff the counterpart files
against the enumerations above; for a full sweep use
`renogy-curation-parity-campaign`.

## Provenance and maintenance

Contents verified against source on 2026-07-12 at v0.5.1 (HA repo HEAD
dc3c11f). Re-derive each set rather than trusting this file:

- Discovery sets: `grep -n "_SKIP_NAMESPACES\|_FORCE_READONLY\|_ENTITY_TYPES\|_MAX_CONCURRENT" custom_components/renogy_gateway/api/discovery.py`
- const.py: `grep -n "HIDE_LEAVES\|_DIAGNOSTIC_PATTERNS\|RTM_RECONNECT\|^CONF_" custom_components/renogy_gateway/const.py`
- Phantom patterns: `grep -n "_INSTANCE_PATTERNS" -A 6 custom_components/renogy_gateway/coordinator.py`
- Labels: `grep -c ":" custom_components/renogy_gateway/api/labels.py` and read the three dicts directly.
- Tunables: `grep -n "TIMEOUT\|RETRIES\|RTM_URL" custom_components/renogy_gateway/api/rtm.py`; `grep -n "BASE_URL\|REFRESH_SKEW\|_APP_\|app-version" custom_components/renogy_gateway/api/auth.py`
- Sibling drift: `git -C ../renogy-gateway log --oneline -- packages/core/src/params.ts packages/core/src/discovery.ts apps/hass-bridge/src/filter.ts`
